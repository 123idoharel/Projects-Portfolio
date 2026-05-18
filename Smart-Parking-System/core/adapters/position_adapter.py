"""
position_adapter.py — Vehicle & Pedestrian Positioning Abstraction Layer
========================================================================

PURPOSE
-------
This module abstracts the position source for two distinct tracking needs:

  1. VehiclePositionAdapter  — where is the guided car right now?
  2. PedestrianPositionAdapter — where is the walking user right now?

Today both use SimulatedXxxAdapter, which computes position mathematically
from the route and elapsed time. In production each is replaced by a real
indoor positioning technology — the rest of the system is unchanged.

════════════════════════════════════════════════════════════════════════
HOW REAL INDOOR POSITIONING SYSTEMS WORK
════════════════════════════════════════════════════════════════════════

Parking garages use several technologies, roughly in order of accuracy:

  ┌─────────────────────────────────────────────────────────────────────┐
  │ Technology       │ Accuracy  │ Cost   │ Notes                       │
  ├─────────────────────────────────────────────────────────────────────┤
  │ BLE beacons      │ 1–5 m     │ Low    │ iBeacon / Eddystone, RSSI   │
  │ (Bluetooth Low   │           │        │ trilateration. Most common. │
  │  Energy)         │           │        │ Phone sees 3+ beacons.      │
  ├─────────────────────────────────────────────────────────────────────┤
  │ UWB beacons      │ 0.1–0.3 m │ High   │ Time-of-flight, very        │
  │ (Ultra Wide Band)│           │        │ precise. Used in airports   │
  │                  │           │        │ and high-end garages.       │
  ├─────────────────────────────────────────────────────────────────────┤
  │ WiFi fingerprint │ 3–8 m     │ None   │ Uses existing WiFi APs.     │
  │                  │           │        │ Less accurate than beacons. │
  ├─────────────────────────────────────────────────────────────────────┤
  │ RFID / NFC       │ Zone only │ Low    │ Car crosses a gate/zone.    │
  │ zone detection   │           │        │ Tells you "entered zone B". │
  ├─────────────────────────────────────────────────────────────────────┤
  │ Camera + CV      │ 0.5–2 m   │ High   │ Overhead cameras track      │
  │                  │           │        │ plates / bounding boxes.    │
  └─────────────────────────────────────────────────────────────────────┘

For a typical parking garage deployment, the practical choice is:
  • BLE beacons for pedestrian (phone app receives RSSI from 3+ beacons)
  • RFID zone checkpoints or camera for vehicle (fixed infrastructure)

The output in all cases is the same:
    PositionSample(id, x, y, floor, heading, accuracy_m, timestamp)

This module provides that common interface.

════════════════════════════════════════════════════════════════════════
ROUTE RE-SNAPPING
════════════════════════════════════════════════════════════════════════

When position is simulated, the vehicle/pedestrian always follows the
route exactly. With real positions, there is drift — the measured position
never sits precisely on the planned route.

Each adapter returns a PositionSample which the server uses to:
  1. Update the displayed position (x, y, floor)
  2. Re-snap route_i: find the closest segment of route_xy to the
     current real position and advance route_i accordingly.
     This ensures navigation instructions stay synchronised with reality.

The re-snapping logic lives in _snap_route_index() in this file and is
called by the server after receiving a position update.

════════════════════════════════════════════════════════════════════════
BLE TRILATERATION SKETCH  (for reference)
════════════════════════════════════════════════════════════════════════

Each BLE beacon is mounted at a known (x, y, floor) in the garage.
The phone measures RSSI (Received Signal Strength Indicator) from N beacons.
Distance estimation: d ≈ 10^((TxPower - RSSI) / (10 × n))
  where n = path-loss exponent (≈ 2.0 in open space, higher with obstacles).

With 3+ beacons, trilateration gives (x, y). Floor is determined by which
beacons are audible (each floor has beacons, different UUIDs per floor).

The phone SDK (e.g. IndoorAtlas, HERE Indoor, or custom) handles all of
this and exposes a simple callback:
    on_position_update(x, y, floor, accuracy_m, heading)

The BlePositionAdapter below wraps that callback stream into our interface.
"""

import math
import time
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════
# Common data structure
# ════════════════════════════════════════════════════════════════════════

@dataclass
class PositionSample:
    """
    A single position reading from any source.

    Fields
    ------
    entity_id   : vehicle ID (e.g. "user_car_1") or pedestrian session ID
    x, y        : world coordinates in layout units
    floor       : 0-based floor number
    heading     : direction of travel in radians (0 = east, π/2 = north)
                  None if unknown or stationary
    accuracy_m  : estimated horizontal accuracy in metres (None = unknown)
    timestamp   : unix timestamp of this reading
    source      : "simulated" | "ble" | "uwb" | "wifi" | "rfid" | "camera"
    """
    entity_id  : str
    x          : float
    y          : float
    floor      : int
    heading    : Optional[float] = None
    accuracy_m : Optional[float] = None
    timestamp  : float = field(default_factory=time.time)
    source     : str   = "simulated"


# ════════════════════════════════════════════════════════════════════════
# Route re-snapping utility
# ════════════════════════════════════════════════════════════════════════

def snap_route_index(route_xy: List, current_x: float, current_y: float,
                     current_floor: int, current_i: int) -> int:
    """
    Given a real position (x, y, floor), find which segment of route_xy
    the entity is currently on and return the updated route_i.

    Strategy: scan route_xy[current_i : current_i + LOOKAHEAD] and find
    the waypoint closest to the current real position. Never go backwards
    (route_i only increases) to prevent GPS glitches from rewinding nav.

    Used by the server after writing a real position update to a vehicle
    or pedestrian to keep route_i synchronised with the real world.

    Parameters
    ----------
    route_xy    : list of (x, y, floor) waypoints
    current_x/y : real measured position
    current_floor: measured floor
    current_i   : current route index (only scan forward from here)

    Returns
    -------
    new route_i (>= current_i)
    """
    if not route_xy or current_i >= len(route_xy) - 1:
        return current_i

    LOOKAHEAD = 10  # how many waypoints ahead to search
    best_i    = current_i
    best_dist = float("inf")

    for j in range(current_i, min(current_i + LOOKAHEAD, len(route_xy))):
        wp = route_xy[j]
        if len(wp) >= 3 and int(wp[2]) != current_floor:
            continue
        d = math.sqrt((float(wp[0]) - current_x)**2 + (float(wp[1]) - current_y)**2)
        if d < best_dist:
            best_dist = d
            best_i    = j

    return best_i


# ════════════════════════════════════════════════════════════════════════
# Base class — Vehicle
# ════════════════════════════════════════════════════════════════════════

class VehiclePositionAdapter(ABC):
    """
    Abstract source of vehicle position data.

    In simulation: computes position from route_xy + speed × dt.
    In production: receives position from infrastructure (RFID zones,
    cameras, UWB anchors) and writes it into runtime["vehicles"].
    """

    @abstractmethod
    def tick(self, runtime: Dict[str, Any], dt: float) -> None:
        """
        Called every simulation tick.
        Responsible for updating v["x"], v["y"], v["floor"], v["route_i"]
        for every DRIVING vehicle in runtime["vehicles"].
        """


class SimulatedVehiclePositionAdapter(VehiclePositionAdapter):
    """
    Moves vehicles mathematically along their route_xy at speed_mps.
    This is the current simulation behaviour — identical to what
    simulation.tick() used to do for movement.

    ── TO REPLACE WITH REAL POSITIONING ──────────────────────────────
    Replace with CameraVehicleAdapter or UwbVehicleAdapter.
    Those adapters write positions received from infrastructure into the
    same runtime["vehicles"] dict. snap_route_index() keeps route_i in sync.
    """

    def tick(self, runtime: Dict[str, Any], dt: float) -> None:
        """Advance every DRIVING vehicle along its route."""
        for v in runtime["vehicles"].values():
            if v.get("status") not in ("DRIVING",):
                continue

            route = v.get("route_xy", [])
            if not route:
                continue

            i = int(v.get("route_i", 0))
            if i >= len(route) - 1:
                # Reached end — simulation.tick() will handle PARKED transition
                continue

            speed  = float(v.get("speed_mps", 3.0))
            target = route[i + 1]
            tx, ty = float(target[0]), float(target[1])
            cx, cy = float(v["x"]), float(v["y"])

            dist_to_target = math.sqrt((tx - cx)**2 + (ty - cy)**2)
            step            = min(dist_to_target, speed * dt)

            if dist_to_target > 0.001:
                v["x"] = cx + (tx - cx) / dist_to_target * step
                v["y"] = cy + (ty - cy) / dist_to_target * step

            if step >= dist_to_target - 0.1:
                v["route_i"] = i + 1
                v["floor"]   = int(target[2]) if len(target) >= 3 else v["floor"]


# ════════════════════════════════════════════════════════════════════════
# Base class — Pedestrian
# ════════════════════════════════════════════════════════════════════════

class PedestrianPositionAdapter(ABC):
    """
    Abstract source of pedestrian position data.

    In simulation: the frontend simulates walking (usePositionSource in
    FindMyCarScreen.jsx). No server-side pedestrian position exists.

    In production: BLE beacons or UWB anchors report the phone's position
    to the server. The server updates the pedestrian session and broadcasts
    the position back to the app, which renders it on the map.
    """

    @abstractmethod
    async def get_position(self, session_id: str) -> Optional[PositionSample]:
        """
        Return the latest known position for a pedestrian session.
        Returns None if no recent fix is available.
        """


class SimulatedPedestrianPositionAdapter(PedestrianPositionAdapter):
    """
    No server-side pedestrian position in simulation mode.

    The frontend (usePositionSource hook in FindMyCarScreen.jsx) simulates
    walking locally in the browser. The server has no pedestrian position data.

    ── TO REPLACE WITH REAL POSITIONING ──────────────────────────────
    Replace with BlePositionAdapter. The BLE SDK on the phone sends
    RSSI readings to the server via POST /api/position_update. The server
    stores the trilaterated position and returns it here. The frontend's
    usePositionSource hook then polls GET /api/position/<session_id> instead
    of simulating locally.

    This requires two coordinated changes:
      1. Server: replace this adapter, add /api/position_update endpoint
      2. Frontend: replace usePositionSource simulation with API polling
    """

    async def get_position(self, session_id: str) -> Optional[PositionSample]:
        return None  # frontend handles simulation locally


# ════════════════════════════════════════════════════════════════════════
# Production adapter stubs (filled in when hardware is available)
# ════════════════════════════════════════════════════════════════════════

class BlePositionAdapter(PedestrianPositionAdapter):
    """
    Receives BLE RSSI readings from the mobile app and returns
    trilaterated positions.

    ── INTEGRATION FLOW ──────────────────────────────────────────────
    1. Phone app scans for BLE beacons (iBeacon / Eddystone).
    2. App POSTs RSSI readings to POST /api/ble_scan:
           { "session_id": "abc123",
             "beacons": [
               {"uuid": "B0001", "rssi": -65, "tx_power": -59},
               {"uuid": "B0002", "rssi": -72, "tx_power": -59},
               {"uuid": "B0003", "rssi": -80, "tx_power": -59}
             ]}
    3. This adapter trilaterates and stores the result.
    4. Frontend calls GET /api/position/abc123 each second.

    The BEACON_MAP (uuid → x, y, floor) is loaded from the layout or a
    separate commissioning file.

    ── TO ACTIVATE ───────────────────────────────────────────────────
    In server.py:
        ped_position_adapter = BlePositionAdapter(beacon_map=BEACON_MAP)
    Then wire /api/ble_scan to ped_position_adapter.receive_rssi_scan().
    """

    def __init__(self, beacon_map: Dict[str, Dict] = None):
        # beacon_map: {"B0001": {"x": 75, "y": 100, "floor": 0, "tx_power": -59}, ...}
        self._beacon_map: Dict[str, Dict] = beacon_map or {}
        self._positions:  Dict[str, PositionSample] = {}

    def receive_rssi_scan(self, session_id: str, beacons: List[Dict]) -> Optional[PositionSample]:
        """
        Called by /api/ble_scan endpoint.
        Trilaterates position from RSSI readings and stores it.
        Returns the estimated position, or None if < 3 beacons visible.
        """
        # Filter to known beacons
        known = []
        for b in beacons:
            uid = b.get("uuid") or b.get("id")
            info = self._beacon_map.get(uid)
            if info:
                rssi     = float(b.get("rssi", -80))
                tx_power = float(b.get("tx_power") or info.get("tx_power", -59))
                # Free-space path loss model
                distance_m = 10 ** ((tx_power - rssi) / (10 * 2.0))
                known.append({**info, "distance_m": distance_m})

        if len(known) < 3:
            return None  # not enough beacons for reliable fix

        # Weighted centroid (simple approximation; use proper trilateration for production)
        total_w = sum(1.0 / max(b["distance_m"], 0.1) for b in known)
        x = sum(b["x"] * (1.0 / max(b["distance_m"], 0.1)) for b in known) / total_w
        y = sum(b["y"] * (1.0 / max(b["distance_m"], 0.1)) for b in known) / total_w
        floor = max(set(b["floor"] for b in known), key=lambda f: sum(1 for b in known if b["floor"] == f))
        accuracy = sum(b["distance_m"] for b in known) / len(known)  # rough estimate

        sample = PositionSample(
            entity_id  = session_id,
            x          = x,
            y          = y,
            floor      = floor,
            accuracy_m = accuracy,
            source     = "ble",
        )
        self._positions[session_id] = sample
        return sample

    async def get_position(self, session_id: str) -> Optional[PositionSample]:
        return self._positions.get(session_id)


class RfidZoneVehicleAdapter(VehiclePositionAdapter):
    """
    Tracks vehicles using RFID zone checkpoints at aisle entrances.

    Each zone checkpoint is a gate or loop detector that reads the car's
    RFID tag and reports which zone it entered/exited.

    This gives coarse position (zone, not exact coordinates). The adapter
    sets the vehicle's position to the zone centroid and advances route_i
    to the first waypoint within that zone.

    ── TO ACTIVATE ───────────────────────────────────────────────────
    In server.py:
        vehicle_position_adapter = RfidZoneVehicleAdapter(
            zone_map = layout["rfid_zones"]  # from layout JSON
        )
    Wire RFID events to vehicle_position_adapter.receive_zone_event().

    Between RFID checkpoints, the adapter falls back to dead reckoning
    (speed × time) just like the simulated adapter.
    """

    def __init__(self, zone_map: Dict[str, Dict] = None):
        # zone_map: {"ZONE_A": {"x_center": 175, "y_center": 85, "floor": 0}, ...}
        self._zone_map   = zone_map or {}
        self._sim        = SimulatedVehiclePositionAdapter()
        self._zone_fixes: Dict[str, Tuple[float, float, int]] = {}  # vid → (x, y, floor)

    def receive_zone_event(self, vid: str, zone_id: str, runtime: Dict) -> None:
        """Called when RFID scanner detects a vehicle entering a zone."""
        zone = self._zone_map.get(zone_id)
        if not zone:
            logger.warning(f"Unknown zone: {zone_id}")
            return
        x, y, floor = float(zone["x_center"]), float(zone["y_center"]), int(zone["floor"])
        self._zone_fixes[vid] = (x, y, floor)
        v = runtime["vehicles"].get(vid)
        if v:
            v["x"], v["y"], v["floor"] = x, y, floor
            v["route_i"] = snap_route_index(v.get("route_xy", []), x, y, floor, int(v.get("route_i", 0)))

    def tick(self, runtime: Dict[str, Any], dt: float) -> None:
        """Between RFID fixes, use dead reckoning (same as simulation)."""
        self._sim.tick(runtime, dt)


# ════════════════════════════════════════════════════════════════════════
# BleVehiclePositionAdapter
# Reuses BLE beacon infrastructure for vehicle positioning.
# The driver's phone is in the car → same beacons, same protocol,
# different entity_type. This makes BLE beacons serve double-duty:
# pedestrian nav AND vehicle nav, with zero additional hardware.
# ════════════════════════════════════════════════════════════════════════

class BleVehiclePositionAdapter(VehiclePositionAdapter):
    """
    Vehicle positioning via BLE beacons — using the driver's phone.

    The driver's phone is inside the car, so the same BLE beacon
    infrastructure used for pedestrian navigation also tracks the vehicle.
    No additional hardware is required beyond what pedestrian nav needs.

    Accuracy is 1–5 m — sufficient for aisle-level vehicle guidance.
    For lane-precision (sub-1 m), use UWB or a camera instead.

    ── HOW IT WORKS ──────────────────────────────────────────────────────
    1. Driver app continuously scans BLE beacons while navigating.
    2. App POSTs RSSI readings to POST /api/ble_scan with entity_type="vehicle"
       and the vehicle ID.
    3. This adapter trilaterates the position and stores it.
    4. On each tick, the adapter writes the latest position into
       runtime["vehicles"][vid] and calls snap_route_index().
    5. Between BLE fixes (phone scans every ~1s), dead reckoning fills gaps.

    ── DIFFERENCE FROM BlePositionAdapter (pedestrian) ─────────────────
    • entity_type is "vehicle" (not "pedestrian")
    • tick() writes into runtime["vehicles"] (VehiclePositionAdapter contract)
    • Falls back to SimulatedVehiclePositionAdapter between fixes
    • Heading is computed from last two position fixes (no compass needed)

    ── TO ACTIVATE ───────────────────────────────────────────────────────
    In server.py:
        vehicle_position_adapter = BleVehiclePositionAdapter(
            beacon_map = BEACON_MAP   # same dict as ped_position_adapter
        )
    In /api/ble_scan, route entity_type="vehicle" here:
        if req.entity_type == "vehicle":
            vehicle_position_adapter.receive_rssi_scan(req.entity_id, req.beacons)
        else:
            ped_position_adapter.receive_rssi_scan(req.session_id, req.beacons)
    """

    def __init__(self, beacon_map: Dict[str, Dict] = None):
        self._beacon_map: Dict[str, Dict] = beacon_map or {}
        # Latest BLE-derived positions: {vid: PositionSample}
        self._ble_fixes:  Dict[str, PositionSample] = {}
        # Dead-reckoning fallback for gaps between BLE scans
        self._sim = SimulatedVehiclePositionAdapter()

    def receive_rssi_scan(self, vid: str, beacons: List[Dict]) -> Optional[PositionSample]:
        """
        Trilaterate vehicle position from a BLE scan and store it.
        Called by /api/ble_scan when entity_type == "vehicle".
        Returns the estimated PositionSample, or None if < 3 beacons visible.
        """
        known = []
        for b in beacons:
            uid  = b.get("uuid") or b.get("id")
            info = self._beacon_map.get(uid)
            if info:
                rssi      = float(b.get("rssi", -80))
                tx_power  = float(b.get("tx_power") or info.get("tx_power", -59))
                distance_m = 10 ** ((tx_power - rssi) / (10 * 2.0))
                known.append({**info, "distance_m": distance_m})

        if len(known) < 3:
            return None

        total_w = sum(1.0 / max(b["distance_m"], 0.1) for b in known)
        x = sum(b["x"] * (1.0 / max(b["distance_m"], 0.1)) for b in known) / total_w
        y = sum(b["y"] * (1.0 / max(b["distance_m"], 0.1)) for b in known) / total_w
        floor = max(
            set(b["floor"] for b in known),
            key=lambda f: sum(1 for b in known if b["floor"] == f),
        )

        # Compute heading from previous fix (if available)
        heading = None
        prev = self._ble_fixes.get(vid)
        if prev and (x != prev.x or y != prev.y):
            heading = math.atan2(y - prev.y, x - prev.x)

        sample = PositionSample(
            entity_id  = vid,
            x          = x,
            y          = y,
            floor      = floor,
            heading    = heading,
            accuracy_m = sum(b["distance_m"] for b in known) / len(known),
            source     = "ble_vehicle",
        )
        self._ble_fixes[vid] = sample
        return sample

    def tick(self, runtime: Dict[str, Any], dt: float) -> None:
        """
        Apply latest BLE fixes to vehicles, then fill gaps with dead reckoning.

        For each DRIVING vehicle:
          1. If a fresh BLE fix exists (< 2s old) → apply it + snap route_i.
          2. Otherwise → dead-reckoning via SimulatedVehiclePositionAdapter.

        This means the car stays smooth even when BLE scan intervals are wide.
        """
        now = time.time()
        FIX_MAX_AGE_S = 2.0  # discard BLE fixes older than this

        for v in runtime["vehicles"].values():
            if v.get("status") != "DRIVING":
                continue
            vid   = v["id"]
            fix   = self._ble_fixes.get(vid)
            if fix and (now - fix.timestamp) < FIX_MAX_AGE_S:
                v["x"]     = fix.x
                v["y"]     = fix.y
                v["floor"] = fix.floor
                v["route_i"] = snap_route_index(
                    v.get("route_xy", []), fix.x, fix.y, fix.floor,
                    int(v.get("route_i", 0)),
                )

        # Dead-reckoning fills the gaps for vehicles without a fresh fix
        self._sim.tick(runtime, dt)


# ════════════════════════════════════════════════════════════════════════
# ServerSimulatedPedestrianPositionAdapter
# Simulation that runs on the SERVER, not the frontend.
# The frontend polls /api/position/{session_id} — exactly as it will
# with real BLE data. Zero frontend changes needed when going live.
# ════════════════════════════════════════════════════════════════════════

class ServerSimulatedPedestrianPositionAdapter(PedestrianPositionAdapter):
    """
    Server-side pedestrian position simulation.

    REPLACES SimulatedPedestrianPositionAdapter.

    The key architectural difference:
    ┌──────────────────────────────────────────────────────────────────────┐
    │ SimulatedPedestrianPositionAdapter (old)                             │
    │   server returns None → frontend animates locally in browser         │
    │   problem: frontend and server are out of sync                       │
    │            switching to real BLE requires changing BOTH sides        │
    ├──────────────────────────────────────────────────────────────────────┤
    │ ServerSimulatedPedestrianPositionAdapter (this class)                │
    │   server simulates walking and stores PositionSample                 │
    │   frontend polls GET /api/position/{session_id} (same as real BLE)  │
    │   switching to real BLE = swap this class for BlePositionAdapter     │
    │   frontend code does NOT change at all                               │
    └──────────────────────────────────────────────────────────────────────┘

    ── HOW IT WORKS ──────────────────────────────────────────────────────
    1. When a walk route is computed (POST /api/walk_route), the server
       calls register_session(session_id, waypoints) on this adapter.
    2. advance_all(dt) is called each simulation tick (or a dedicated
       pedestrian tick in server.py's simulation_loop).
    3. The position advances along the waypoints at WALK_SPEED_MPS.
    4. GET /api/position/{session_id} returns the current PositionSample.
    5. The frontend polls this endpoint — identical behaviour to real BLE.

    ── TO SWITCH TO REAL BLE ─────────────────────────────────────────────
    In server.py, change ONE line:
        ped_position_adapter = ServerSimulatedPedestrianPositionAdapter()
        →  ped_position_adapter = BlePositionAdapter(beacon_map=BEACON_MAP)

    The /api/position/{session_id} endpoint and the frontend are unchanged.
    """

    WALK_SPEED_MPS = 1.4  # m/s — realistic walking speed in a garage

    def __init__(self):
        # session_id → {"waypoints": [...], "seg_idx": int, "t_in_seg": float}
        self._sessions:  Dict[str, Dict] = {}
        self._positions: Dict[str, PositionSample] = {}

    def register_session(self, session_id: str, waypoints: List[Dict]) -> None:
        """
        Called by server.py when a new walk route is computed (POST /api/walk_route).

        Stores the waypoints and sets initial position at the start of the route,
        but does NOT start advancing yet. Call resume_session() to begin movement
        (triggered by POST /api/start_navigation when user presses the start button).

        This separation mirrors the real-world flow:
          register_session  = route planned, user sees preview, no movement
          resume_session    = user started walking, position updates begin

        With BlePositionAdapter: register_session is a no-op; movement starts
        naturally when the phone begins sending RSSI scans.
        """
        if not waypoints:
            return
        self._sessions[session_id] = {
            "waypoints": waypoints,
            "seg_idx":   0,
            "t_in_seg":  0.0,
            "paused":    True,   # ← wait for resume_session() before advancing
        }
        wp0 = waypoints[0]
        self._positions[session_id] = PositionSample(
            entity_id = session_id,
            x         = float(wp0["x"]),
            y         = float(wp0["y"]),
            floor     = int(wp0["floor"]),
            source    = "simulated",
        )

    def resume_session(self, session_id: str) -> None:
        """
        Start (or resume) advancing a session.
        Called when the user presses the navigation start button.

        With real BLE: no-op — phone scans drive position updates directly.
        """
        state = self._sessions.get(session_id)
        if state:
            state["paused"] = False

    def advance_all(self, dt: float) -> None:
        """
        Advance ALL active pedestrian sessions by dt seconds.
        Called once per simulation tick from server.py's simulation_loop.
        """
        for session_id, state in list(self._sessions.items()):
            self._advance_session(session_id, state, dt)

    def _advance_session(self, session_id: str, state: Dict, dt: float) -> None:
        """Move one session forward by dt seconds along its waypoints."""
        if state.get("paused", True):
            return  # waiting for resume_session() — user hasn't pressed start yet

        waypoints = state["waypoints"]
        seg_idx   = state["seg_idx"]
        t_in_seg  = state["t_in_seg"]

        if seg_idx >= len(waypoints) - 1:
            return  # reached destination

        step = self.WALK_SPEED_MPS * dt
        t_in_seg += step

        # Advance through segments until time budget is consumed
        while seg_idx < len(waypoints) - 1:
            a = waypoints[seg_idx]
            b = waypoints[seg_idx + 1]
            seg_len = math.sqrt(
                (float(b["x"]) - float(a["x"])) ** 2 +
                (float(b["y"]) - float(a["y"])) ** 2
            )
            if seg_len < 0.001:
                seg_idx += 1
                continue
            if t_in_seg < seg_len:
                break
            t_in_seg -= seg_len
            seg_idx  += 1

        state["seg_idx"]  = seg_idx
        state["t_in_seg"] = t_in_seg

        # Interpolate position within current segment
        if seg_idx >= len(waypoints) - 1:
            wp = waypoints[-1]
            x, y, floor = float(wp["x"]), float(wp["y"]), int(wp["floor"])
            heading = None
        else:
            a = waypoints[seg_idx]
            b = waypoints[seg_idx + 1]
            seg_len = math.sqrt(
                (float(b["x"]) - float(a["x"])) ** 2 +
                (float(b["y"]) - float(a["y"])) ** 2
            )
            frac = min(t_in_seg / seg_len, 1.0) if seg_len > 0 else 0.0
            x     = float(a["x"]) + frac * (float(b["x"]) - float(a["x"]))
            y     = float(a["y"]) + frac * (float(b["y"]) - float(a["y"]))
            floor = int(a["floor"])
            heading = math.atan2(float(b["y"]) - float(a["y"]),
                                 float(b["x"]) - float(a["x"]))

        # Compute distance from start (for step detection on frontend)
        dist = 0.0
        for i in range(seg_idx):
            a = waypoints[i]; b = waypoints[i + 1]
            dist += math.sqrt(
                (float(b["x"]) - float(a["x"])) ** 2 +
                (float(b["y"]) - float(a["y"])) ** 2
            )
        dist += t_in_seg

        self._positions[session_id] = PositionSample(
            entity_id    = session_id,
            x            = x,
            y            = y,
            floor        = floor,
            heading      = heading,
            accuracy_m   = None,   # simulated → no uncertainty
            source       = "simulated",
        )
        # Attach distFromStart as extra field for frontend step detection
        self._positions[session_id].dist_from_start = dist  # type: ignore[attr-defined]

    def clear_session(self, session_id: str) -> None:
        """Remove a session when user leaves Find My Car screen."""
        self._sessions.pop(session_id, None)
        self._positions.pop(session_id, None)

    async def get_position(self, session_id: str) -> Optional[PositionSample]:
        return self._positions.get(session_id)
