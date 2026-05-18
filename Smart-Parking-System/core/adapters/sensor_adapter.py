"""
sensor_adapter.py — Parking Spot Occupancy Abstraction Layer
=============================================================

PURPOSE
-------
This module is the single point of contact between the parking management
system and whatever external data source reports spot occupancy.

Today that source is the internal simulation (SimulatedSensorAdapter).
In production it will be a real sensor network — magnetic floor sensors,
ultrasonic detectors, IR beams, or camera-based AI detection.

The swap from simulation to reality requires changing ONE LINE in server.py:
    sensor_adapter = SimulatedSensorAdapter(state.runtime)
    →  sensor_adapter = MqttSensorAdapter("mqtt://192.168.1.10", ...)
    →  sensor_adapter = RestPollingSensorAdapter("https://sensors.garage.com/api/spots", ...)
Everything else — routing, reservations, UI broadcasts — stays identical.

════════════════════════════════════════════════════════════════════════
HOW REAL SENSOR SYSTEMS TYPICALLY WORK
════════════════════════════════════════════════════════════════════════

Commercial parking sensor systems (e.g. Bosch ParkingSuite, Siemens
Desigo, Nedap MACE, TKH Security SpotAssist) expose occupancy data via:

  A. REST polling  — GET /api/spots  → [{id, occupied, updated_at}, ...]
     The server polls every N seconds and diffs the result.
     Most common for mid-size integrations (100–2000 spots).

  B. MQTT push     — topics like  parking/floor/0/spot/F0-A03
     Payload: {"occupied": true, "sensor_id": "S-042", "ts": 1710000000}
     Low-latency (< 1s), preferred for live dashboards.
     Implemented as an async subscriber that writes into the runtime dict.

  C. WebSocket     — similar to MQTT, proprietary protocol.

  D. Webhook / callback — sensor POSTs to our server when state changes.
     Works well with the /api/spot_event endpoint added below.

In all cases the external ID for a spot (e.g. "Level_0_Bay_3_Slot_06")
must be mapped to our internal ID ("F0-A06") via the SPOT_ID_MAP.

════════════════════════════════════════════════════════════════════════
DEBOUNCE
════════════════════════════════════════════════════════════════════════

Real sensors are noisy:
  - A car drives slowly past → sensor briefly reads "occupied"
  - A motorcycle → different signature than a car
  - Sensor glitch → single spurious flip

The adapter applies a simple debounce: a spot only transitions to OCCUPIED
after DEBOUNCE_FREE_TO_OCC_S consecutive seconds of the sensor reading
"occupied", and back to FREE after DEBOUNCE_OCC_TO_FREE_S seconds.

In simulation mode debounce is 0 (instant) because the sim is already
correct by construction.

════════════════════════════════════════════════════════════════════════
RESERVATION LOGIC (SYSTEM-MANAGED)
════════════════════════════════════════════════════════════════════════

The transition FREE → RESERVED is always managed internally by this
system's routing logic (when a vehicle is assigned a spot). The sensor
system only ever reports FREE ↔ OCCUPIED.

  Sensor reports "occupied" on a RESERVED spot → confirmed park → OCCUPIED
  Sensor reports "free" on a RESERVED spot     → debounce; if sustained → FREE
  Sensor reports "occupied" on a FREE spot     → rogue occupancy → OCCUPIED + reroute trigger
"""

import time
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger(__name__)

# ── Debounce thresholds (seconds) ────────────────────────────────────────────
DEBOUNCE_FREE_TO_OCC_S  = 2.0   # sensor must read "occupied" for this long before we accept it
DEBOUNCE_OCC_TO_FREE_S  = 3.0   # sensor must read "free" for this long before we accept it

# ── External ID → internal spot ID mapping ───────────────────────────────────
# In a real deployment, populate this from a commissioning spreadsheet or
# from the sensor management platform's API.
#
# Example:
#   "Level_0_Bay_A_Slot_03" → "F0-A03"
#   "sensor_042"            → "F0-B06"
#
# When empty, the adapter assumes external IDs ARE internal IDs (works for
# simulation and for systems that use the same naming convention).
SPOT_ID_MAP: Dict[str, str] = {}


def external_to_internal(external_id: str) -> Optional[str]:
    """Map an external sensor spot ID to the internal system spot ID."""
    return SPOT_ID_MAP.get(external_id, external_id)


# ════════════════════════════════════════════════════════════════════════
# Base class
# ════════════════════════════════════════════════════════════════════════

class SensorAdapter(ABC):
    """
    Abstract base for all spot-occupancy data sources.

    Subclasses implement _fetch_raw_states() which returns a dict of
    {internal_spot_id: bool} where True = occupied, False = free.

    The base class handles:
      • debounce (pending state changes that haven't held long enough)
      • writing confirmed changes into runtime["spots"]
      • calling on_change callback so the server can trigger rerouting
    """

    def __init__(self, runtime: Dict[str, Any]):
        self._runtime        = runtime
        self._on_change_cb: Optional[Callable[[str, str], None]] = None
        # pending[spot_id] = (new_state: bool, first_seen_ts: float)
        self._pending: Dict[str, tuple] = {}

    def set_on_change(self, cb: Callable[[str, str], None]) -> None:
        """
        Register a callback fired when a spot's status is confirmed changed.
        Signature: cb(spot_id: str, new_status: str)
        The server uses this to trigger rerouting when a reserved spot goes OCCUPIED.
        """
        self._on_change_cb = cb

    @abstractmethod
    async def _fetch_raw_states(self) -> Dict[str, bool]:
        """
        Fetch the latest occupancy from the source.
        Returns: {internal_spot_id: occupied_bool}
        Must be implemented by each concrete adapter.
        """

    @abstractmethod
    def get_debounce_free_to_occ(self) -> float:
        """Seconds to debounce FREE→OCCUPIED transition."""

    @abstractmethod
    def get_debounce_occ_to_free(self) -> float:
        """Seconds to debounce OCCUPIED→FREE transition."""

    async def poll_once(self) -> None:
        """
        Fetch current sensor states, apply debounce, write confirmed changes.
        Called by the simulation loop on every tick (simulated) or by a
        background polling task (real sensors).
        """
        try:
            raw = await self._fetch_raw_states()
        except Exception as e:
            logger.warning(f"SensorAdapter fetch error: {e}")
            return

        now = time.time()
        spots_by_id = {s["id"]: s for s in self._runtime["spots"]}

        for spot_id, sensor_occupied in raw.items():
            spot = spots_by_id.get(spot_id)
            if not spot:
                continue

            current = spot["status"]

            # Determine what the sensor is asking us to transition to
            if sensor_occupied:
                target_status = "OCCUPIED"
                threshold = self.get_debounce_free_to_occ()
            else:
                # Sensor says free — only meaningful if currently OCCUPIED
                # (we never let sensors override RESERVED back to FREE without debounce)
                if current == "FREE":
                    self._pending.pop(spot_id, None)
                    continue
                target_status = "FREE"
                threshold = self.get_debounce_occ_to_free()

            # Already in target state?
            if current == target_status:
                self._pending.pop(spot_id, None)
                continue

            # Start or continue debounce
            if spot_id not in self._pending or self._pending[spot_id][0] != target_status:
                self._pending[spot_id] = (target_status, now)
                continue

            held_for = now - self._pending[spot_id][1]
            if held_for < threshold:
                continue  # not yet confirmed

            # ── Confirmed transition ──────────────────────────────────────
            self._pending.pop(spot_id, None)
            old_status = current
            spot["status"] = target_status
            if target_status == "FREE":
                spot["reserved_for"]  = None
                spot["reserved_until"] = None

            logger.info(f"Spot {spot_id}: {old_status} → {target_status} (held {held_for:.1f}s)")

            if self._on_change_cb:
                try:
                    self._on_change_cb(spot_id, target_status)
                except Exception as e:
                    logger.error(f"on_change callback error for {spot_id}: {e}")


# ════════════════════════════════════════════════════════════════════════
# Adapter 1 — Simulation (current behaviour, unchanged)
# ════════════════════════════════════════════════════════════════════════

class SimulatedSensorAdapter(SensorAdapter):
    """
    Reads occupancy directly from the runtime dict — i.e., the simulation
    itself is the "sensor". This is the current behaviour.

    poll_once() is a no-op because simulation.tick() already writes status
    changes directly into runtime["spots"]. The adapter just mirrors reality.

    ── TO REPLACE WITH REAL SENSORS ──────────────────────────────────────
    Replace this class with MqttSensorAdapter or RestPollingSensorAdapter.
    The rest of the system is unaffected.
    """

    async def _fetch_raw_states(self) -> Dict[str, bool]:
        # Simulation manages its own state — nothing to fetch
        return {}

    def get_debounce_free_to_occ(self) -> float:
        return 0.0  # simulation is already correct by construction

    def get_debounce_occ_to_free(self) -> float:
        return 0.0

    async def poll_once(self) -> None:
        pass  # simulation.tick() writes directly — no-op


# ════════════════════════════════════════════════════════════════════════
# Adapter 2 — REST polling  (plug in a real endpoint URL to activate)
# ════════════════════════════════════════════════════════════════════════

class RestPollingSensorAdapter(SensorAdapter):
    """
    Polls a REST endpoint every POLL_INTERVAL_S seconds.

    Expected response format (array of spot objects):
        [
          {"id": "F0-A03", "occupied": true,  "updated_at": 1710000123},
          {"id": "F0-A04", "occupied": false, "updated_at": 1710000120},
          ...
        ]

    ── TO ACTIVATE ───────────────────────────────────────────────────────
    In server.py, replace:
        sensor_adapter = SimulatedSensorAdapter(state.runtime)
    with:
        sensor_adapter = RestPollingSensorAdapter(
            runtime    = state.runtime,
            url        = "https://sensors.mygarage.com/api/spots",
            api_key    = "Bearer sk-...",
            poll_interval_s = 5.0,
        )
    Then call sensor_adapter.start_background_polling() during startup.
    """

    POLL_INTERVAL_S = 5.0

    def __init__(self, runtime: Dict, url: str, api_key: str = "",
                 poll_interval_s: float = 5.0):
        super().__init__(runtime)
        self._url             = url
        self._api_key         = api_key
        self._poll_interval   = poll_interval_s
        self._task: Optional[asyncio.Task] = None

    async def _fetch_raw_states(self) -> Dict[str, bool]:
        import aiohttp
        headers = {"Authorization": self._api_key} if self._api_key else {}
        async with aiohttp.ClientSession() as session:
            async with session.get(self._url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
        result = {}
        for item in data:
            external_id = item.get("id") or item.get("spot_id") or item.get("name")
            occupied    = bool(item.get("occupied") or item.get("status") == "occupied")
            internal_id = external_to_internal(external_id)
            if internal_id:
                result[internal_id] = occupied
        return result

    def get_debounce_free_to_occ(self) -> float:
        return DEBOUNCE_FREE_TO_OCC_S

    def get_debounce_occ_to_free(self) -> float:
        return DEBOUNCE_OCC_TO_FREE_S

    def start_background_polling(self) -> None:
        """Start an asyncio task that polls continuously."""
        self._task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self._poll_interval)


# ════════════════════════════════════════════════════════════════════════
# Adapter 3 — MQTT push  (low-latency, event-driven)
# ════════════════════════════════════════════════════════════════════════

class MqttSensorAdapter(SensorAdapter):
    """
    Subscribes to an MQTT broker and receives occupancy events in real time.

    Expected topic structure:
        parking/<floor>/spot/<spot_id>
    Expected payload (JSON):
        {"occupied": true, "sensor_id": "S-042", "ts": 1710000000, "confidence": 0.97}

    Or flat topic per spot:
        parking/spot/F0-A03   payload: {"occupied": true}

    ── TO ACTIVATE ───────────────────────────────────────────────────────
    In server.py, replace SimulatedSensorAdapter with:
        sensor_adapter = MqttSensorAdapter(
            runtime      = state.runtime,
            broker_url   = "mqtt://192.168.1.10:1883",
            topic_prefix = "parking/spot/",
            username     = "garagesys",
            password     = "secret",
        )
        sensor_adapter.start_background_task()

    Requires: pip install aiomqtt
    """

    def __init__(self, runtime: Dict, broker_url: str, topic_prefix: str = "parking/spot/",
                 username: str = "", password: str = ""):
        super().__init__(runtime)
        self._broker_url    = broker_url
        self._topic_prefix  = topic_prefix
        self._username      = username
        self._password      = password
        # Latest readings from MQTT (written by subscriber, read by poll_once)
        self._latest: Dict[str, bool] = {}
        self._task: Optional[asyncio.Task] = None

    async def _fetch_raw_states(self) -> Dict[str, bool]:
        return dict(self._latest)  # snapshot of latest MQTT state

    def get_debounce_free_to_occ(self) -> float:
        return DEBOUNCE_FREE_TO_OCC_S

    def get_debounce_occ_to_free(self) -> float:
        return DEBOUNCE_OCC_TO_FREE_S

    def start_background_task(self) -> None:
        self._task = asyncio.create_task(self._subscribe_loop())

    async def _subscribe_loop(self) -> None:
        """
        Connect to broker and process messages indefinitely.
        Reconnects automatically on disconnect.
        """
        try:
            import aiomqtt
        except ImportError:
            logger.error("aiomqtt not installed. Run: pip install aiomqtt")
            return

        while True:
            try:
                async with aiomqtt.Client(
                    hostname = self._broker_url.replace("mqtt://", "").split(":")[0],
                    port     = int(self._broker_url.split(":")[-1]) if ":" in self._broker_url else 1883,
                    username = self._username or None,
                    password = self._password or None,
                ) as client:
                    await client.subscribe(f"{self._topic_prefix}#")
                    async for message in client.messages:
                        await self._handle_message(str(message.topic), message.payload)
            except Exception as e:
                logger.warning(f"MQTT connection error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _handle_message(self, topic: str, payload: bytes) -> None:
        import json as _json
        try:
            data     = _json.loads(payload)
            occupied = bool(data.get("occupied", False))
            # Extract spot ID from topic: "parking/spot/F0-A03" → "F0-A03"
            external_id = topic.split("/")[-1]
            internal_id = external_to_internal(external_id)
            if internal_id:
                self._latest[internal_id] = occupied
                # Immediately apply (no need to wait for next poll cycle)
                await self.poll_once()
        except Exception as e:
            logger.debug(f"MQTT message parse error: {e}")


# ════════════════════════════════════════════════════════════════════════
# Adapter 4 — Webhook receiver  (sensor POSTs to our server)
# ════════════════════════════════════════════════════════════════════════

class WebhookSensorAdapter(SensorAdapter):
    """
    Receives occupancy updates pushed by the sensor system to our server.
    Used when the sensor platform supports outbound webhooks / callbacks.

    The server exposes POST /api/spot_event, which calls
    adapter.receive_event(spot_id, occupied).

    No background polling needed — events arrive as they happen.

    ── TO ACTIVATE ───────────────────────────────────────────────────────
    In server.py, replace SimulatedSensorAdapter with:
        sensor_adapter = WebhookSensorAdapter(runtime = state.runtime)

    The /api/spot_event endpoint (already in server.py) feeds this adapter.
    Configure the sensor platform to POST to:
        https://your-server.com/api/spot_event
    """

    def __init__(self, runtime: Dict):
        super().__init__(runtime)
        self._pending_events: Dict[str, bool] = {}

    async def _fetch_raw_states(self) -> Dict[str, bool]:
        events = dict(self._pending_events)
        self._pending_events.clear()
        return events

    def get_debounce_free_to_occ(self) -> float:
        return DEBOUNCE_FREE_TO_OCC_S

    def get_debounce_occ_to_free(self) -> float:
        return DEBOUNCE_OCC_TO_FREE_S

    def receive_event(self, spot_id: str, occupied: bool) -> None:
        """Called by the /api/spot_event endpoint when a webhook arrives."""
        internal_id = external_to_internal(spot_id)
        if internal_id:
            self._pending_events[internal_id] = occupied
