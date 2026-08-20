# Real Hardware Integration Guide

**Smart Parking System — Adapter Architecture**

---

## Overview

Connecting real hardware requires changing **only the adapter lines near the
top of `server.py`**. All routing logic, spot selection, navigation and UI are
unaffected.

This is achieved through an **adapter layer** in `core/adapters/` that isolates
every external data source behind a common interface:

```
┌─────────────────────────────────────────────────────────────────────┐
│                          server.py                                   │
│                                                                      │
│  sensor_adapter           vehicle_position_adapter   ped_position    │
│       │                           │                       │          │
│  ─────▼──────────────────────────▼───────────────────────▼────────   │
│                    core/adapters/                                    │
│  ─────────────────────────────────────────────────────────────────   │
│  SensorAdapter      VehiclePositionAdapter   PedestrianPositionAdapt │
│  (who says a        (who knows where         (who knows where the    │
│   spot is taken?)    the car is?)             pedestrian is?)        │
│  ─────────────────────────────────────────────────────────────────   │
│         core/floor_selection.py   selection + routing —              │
│         core/simulation.py        never changes when you             │
│         core/pedestrian.py        swap hardware                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Today** (`server.py`, immediately after the `from core.adapters import …`
block):

```python
sensor_adapter           = SimulatedSensorAdapter(state.runtime)
vehicle_position_adapter = SimulatedVehiclePositionAdapter()
ped_position_adapter     = ServerSimulatedPedestrianPositionAdapter()
```

**In production:** replace each `Simulated*` line with the real adapter.

---

## The Three Adapters

### 1. `sensor_adapter` — Spot Occupancy

| Adapter | When to use |
|---|---|
| `SimulatedSensorAdapter` | **Today** — the simulation writes occupancy itself; `poll_once()` is a no-op |
| `RestPollingSensorAdapter` | Sensor platform exposes a REST API you poll |
| `MqttSensorAdapter` | Sensor platform pushes events via an MQTT broker |
| `WebhookSensorAdapter` | Sensor platform POSTs to your server |

All four share the debounce state machine in the `SensorAdapter` base class and
report confirmed changes through `set_on_change(cb)`. `server.py` already wires
`_on_sensor_change` as that callback, which frees or occupies the spot, forces a
delta on the next WebSocket frame, and triggers `reassign_from_current()` when
an occupied spot had a live reservation.

### 2. `vehicle_position_adapter` — Vehicle Location

| Adapter | When to use |
|---|---|
| `SimulatedVehiclePositionAdapter` | **Today** — position computed from route + speed |
| `RfidZoneVehicleAdapter` | RFID loop detectors at aisle entrances; dead-reckons between fixes |
| `BleVehiclePositionAdapter` | Driver's phone reports BLE RSSI; reuses the pedestrian beacon grid. 1–5 m accuracy |
| *(extend `VehiclePositionAdapter`)* | UWB anchors, overhead cameras, etc. |

### 3. `ped_position_adapter` — Pedestrian Location

| Adapter | When to use |
|---|---|
| `ServerSimulatedPedestrianPositionAdapter` | **Today** — the server advances the walker along the route inside the simulation loop |
| `SimulatedPedestrianPositionAdapter` | Older client-side variant; kept for reference, not wired |
| `BlePositionAdapter` | BLE beacons + phone app reporting RSSI, trilaterated server-side |
| *(extend `PedestrianPositionAdapter`)* | UWB, WiFi fingerprinting, etc. |

---

## Switching to Real Hardware

### Step 1 — Spot Occupancy Sensors

#### Option A: The sensor system exposes a REST API (most common)

**`server.py` — change these lines:**

```python
# BEFORE (simulation):
sensor_adapter = SimulatedSensorAdapter(state.runtime)

# AFTER:
from core.adapters import RestPollingSensorAdapter
sensor_adapter = RestPollingSensorAdapter(
    runtime         = state.runtime,
    url             = "https://192.168.1.50/api/spots",   # sensor platform URL
    api_key         = "Bearer <your-api-key>",            # sent as the Authorization header
    poll_interval_s = 5.0,
)
```

**`server.py` — add one line to `startup()`:**

```python
@app.on_event("startup")
async def startup():
    ...
    sensor_adapter.start_background_polling()   # ← add this line
```

Expected response format from the sensor platform:
```json
[
  {"id": "F0-A03", "occupied": true,  "updated_at": 1710000123},
  {"id": "F0-A04", "occupied": false, "updated_at": 1710000120}
]
```

`_fetch_raw_states()` already accepts `id`, `spot_id` or `name` for the
identifier, and treats either `occupied: true` or `status: "occupied"` as
occupied. For anything else, edit that method — it is a short, clearly marked
loop.

**Two things to know before you deploy this:**

1. `RestPollingSensorAdapter._fetch_raw_states()` uses **`aiohttp`**, which is
   not in `requirements.txt`. Add `aiohttp>=3.9` before switching.
2. The simulation loop in `server.py` already calls `await
   sensor_adapter.poll_once()` on every tick (20 fps) whenever a WebSocket
   client is connected. `start_background_polling()` runs an independent loop at
   `poll_interval_s`. Both are safe — the debounce state machine deduplicates —
   but if you do **not** want HTTP traffic at 20 fps, either rely solely on the
   background task and make `poll_once()` read a cached snapshot (as
   `MqttSensorAdapter` does), or drop the per-tick call.

---

#### Option B: MQTT push (low-latency, event-driven)

**`server.py`:**

```python
from core.adapters import MqttSensorAdapter
sensor_adapter = MqttSensorAdapter(
    runtime      = state.runtime,
    broker_url   = "mqtt://192.168.1.10:1883",
    topic_prefix = "parking/spot/",   # topics: parking/spot/F0-A03, etc.
    username     = "garagesys",
    password     = "secret",
)
```

**`server.py` — `startup()`:**

```python
sensor_adapter.start_background_task()
```

Expected MQTT message (topic `parking/spot/F0-A03`):
```json
{"occupied": true, "sensor_id": "S-042", "ts": 1710000000}
```

The subscriber writes into an internal `_latest` dict; `poll_once()` snapshots
it, so the per-tick call in the simulation loop costs nothing.

Requires: `pip install aiomqtt`

---

#### Option C: The sensor platform sends webhooks to you

`POST /api/spot_event` already exists and is the lowest-effort path.

**`server.py`:**

```python
from core.adapters import WebhookSensorAdapter
sensor_adapter = WebhookSensorAdapter(runtime=state.runtime)
```

Configure the sensor platform to POST to:
```
POST https://your-server.com/api/spot_event
Content-Type: application/json

{
  "spot_id":    "F0-A03",
  "occupied":   true,
  "sensor_id":  "S-042",        // optional
  "confidence": 0.95,           // optional — events below 0.7 are dropped
  "timestamp":  1710000000      // optional
}
```

Useful detail: the endpoint works **even without swapping the adapter**. If
`sensor_adapter` is not a `WebhookSensorAdapter`, the handler falls back to
translating the id via `external_to_internal()` and applying the change
directly through `_on_sensor_change()`. That path skips debouncing, so use it
for smoke-testing only; switch to `WebhookSensorAdapter` in production.

---

#### Spot ID Mapping

Real sensor systems often use their own naming convention
(`"Level_0_Bay_A_Slot_03"` instead of `"F0-A03"`).

Populate the mapping in `core/adapters/sensor_adapter.py`:

```python
SPOT_ID_MAP = {
    "Level_0_Bay_A_Slot_01": "F0-A01",
    "Level_0_Bay_A_Slot_02": "F0-A02",
    "Level_0_Bay_A_Slot_03": "F0-A03",
    # ...
}
```

`external_to_internal()` translates every incoming id. Unmapped ids pass
through unchanged, so if your naming already matches, leave the dict empty.

---

#### Debounce Thresholds

Real sensors are noisy: a car driving slowly past a spot, a motorcycle, or a
glitch can produce brief false readings. The base adapter holds a state change
in a pending queue and only confirms it after the sensor has held the same
reading for:

```python
# core/adapters/sensor_adapter.py
DEBOUNCE_FREE_TO_OCC_S = 2.0   # must read "occupied" for 2 s before accepting
DEBOUNCE_OCC_TO_FREE_S = 3.0   # must read "free" for 3 s before accepting
```

`SimulatedSensorAdapter` overrides both to `0.0`. Tune the real values to your
hardware's observed noise characteristics.

---

### Step 2 — Vehicle Positioning

#### Option A: RFID zone checkpoints (most practical for garages)

RFID loop detectors or gate readers at the entrance of each aisle section
detect a car entering a zone and report its tag id. Coarse but reliable.
Between checkpoints the adapter dead-reckons exactly as the simulation does.

**`server.py`:**

```python
from core.adapters import RfidZoneVehicleAdapter
vehicle_position_adapter = RfidZoneVehicleAdapter(
    zone_map = {
        "ZONE_AISLE_A": {"x_center": 100, "y_center": 75,  "floor": 0},
        "ZONE_AISLE_B": {"x_center": 175, "y_center": 65,  "floor": 0},
        "ZONE_AISLE_C": {"x_center": 175, "y_center": 115, "floor": 0},
        # one entry per RFID zone, coordinates from your layout JSON
    }
)
```

Wire your RFID event callback to the adapter:

```python
# called by your RFID integration when a tag is read at a checkpoint:
vehicle_position_adapter.receive_zone_event(vid, "ZONE_AISLE_A", state.runtime)
```

`receive_zone_event` moves the vehicle to the zone centroid and re-snaps
`route_i` via `snap_route_index()`, so navigation instructions stay in sync.

The `vid` must match the vehicle id in the system. For the driver's own car
that is `"user_car_1"`. For fleet vehicles, use the plate or tag id as the
vehicle id when spawning via `POST /api/spawn`.

---

#### Option B: BLE via the driver's phone

`BleVehiclePositionAdapter` reuses the same beacon grid as pedestrian
navigation — no extra hardware beyond what Step 3 already needs.

```python
from core.adapters import BleVehiclePositionAdapter
vehicle_position_adapter = BleVehiclePositionAdapter(beacon_map=BEACON_MAP)
```

**This one is not plug-and-play.** `POST /api/ble_scan` currently accepts only
`{ session_id, beacons }` and routes everything to `ped_position_adapter`. To
use the vehicle variant you must extend `BleScanRequest` with an `entity_type`
(and `entity_id`) field and branch in the handler:

```python
class BleScanRequest(BaseModel):
    session_id : str
    beacons    : List[Dict[str, Any]]
    entity_type: str = "pedestrian"     # ← add
    entity_id  : Optional[str] = None   # ← add

# in ble_scan():
if req.entity_type == "vehicle":
    vehicle_position_adapter.receive_rssi_scan(req.entity_id, req.beacons)
else:
    ped_position_adapter.receive_rssi_scan(req.session_id, req.beacons)
```

Accuracy is 1–5 m — enough for aisle-level guidance. For lane precision
(sub-1 m), use UWB or a camera instead.

---

#### Option C: Direct position feed (UWB / overhead cameras)

If your infrastructure produces exact coordinates, use `POST
/api/vehicle_position` directly. It already exists and needs no changes.

```
POST /api/vehicle_position
{
  "vid":     "user_car_1",
  "x":       142.3,
  "y":        75.1,
  "floor":    0,
  "heading":  1.57,     // radians, optional
  "source":  "uwb"
}
```

The server writes the position and re-snaps `route_i` so navigation
instructions stay synchronised with the real location.

In simulation mode this endpoint exists but has no lasting effect —
`SimulatedVehiclePositionAdapter` overwrites the position on the next tick.
Switch to a real adapter (or one that dead-reckons from external fixes) before
wiring an external position feed.

---

### Step 3 — Pedestrian Positioning (Find My Car)

**How it works today:** the pedestrian walker is simulated **on the server**,
not in the browser. `POST /api/walk_route` registers a session with
`ServerSimulatedPedestrianPositionAdapter.register_session(session_id,
waypoints)`; `POST /api/start_navigation` un-pauses it; `advance_all()` is
called every tick from the simulation loop; and `FindMyCarScreen.jsx` polls
`GET /api/position/{session_id}` roughly once per second.

**This is the key point for integration:** the frontend already consumes real
server positions. It does not know or care how they were produced.

**Switching to real BLE beacons:**

BLE beacons (iBeacon or Eddystone) are mounted at known positions in the garage
ceiling, roughly one per 15 m. The phone app scans nearby beacons, measures RSSI,
and the server trilaterates from three or more readings.

#### Server side — this is the whole change

**`server.py`:**

```python
from core.adapters import BlePositionAdapter

BEACON_MAP = {
    "B0001": {"x":  75, "y": 100, "floor": 0, "tx_power": -59},
    "B0002": {"x": 175, "y": 100, "floor": 0, "tx_power": -59},
    "B0003": {"x": 275, "y": 100, "floor": 0, "tx_power": -59},
    "B0004": {"x":  75, "y":  50, "floor": 0, "tx_power": -59},
    # one entry per physical beacon, coordinates from your layout JSON
    # tx_power: measured RSSI at 1 metre (calibrate per beacon model)
}

ped_position_adapter = BlePositionAdapter(beacon_map=BEACON_MAP)
```

`POST /api/ble_scan` and `GET /api/position/{session_id}` already exist and
handle `BlePositionAdapter` correctly.

Two consequences of the swap, both harmless:
- `BlePositionAdapter` has no `register_session`, `resume_session` or
  `advance_all`, so `/api/walk_route`, `/api/start_navigation` and the
  simulation loop all skip their pedestrian branches — every call site is
  already guarded with `hasattr(...)`.
- `receive_rssi_scan()` returns `None` until at least three mapped beacons are
  visible, and `/api/position/{id}` then returns `{"position": null}`. The
  frontend already tolerates a null position.

#### Phone side

The only new work is on the device. It must scan beacons and POST them roughly
once per second:

```javascript
const beacons = await getBleBeacons()      // native BLE SDK / Capacitor / RN
await fetch('/api/ble_scan', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ session_id: sessionId, beacons })
})
```

`FindMyCarScreen.jsx` needs **no change** — `usePositionSource` already polls
`/api/position/{sessionId}`. Map rendering, step detection and instruction
logic all consume the same `{x, y, floor}` structure regardless of source.

---

## Complete Checklist

### Spot occupancy sensors

- [ ] Determine integration method: REST poll / MQTT / webhook
- [ ] Obtain API credentials / broker address from the sensor platform
- [ ] Change `sensor_adapter = ...` in `server.py` (3–7 lines)
- [ ] If REST: add `aiohttp` to `requirements.txt`, and decide whether to keep the per-tick `poll_once()`
- [ ] If REST or MQTT: add `sensor_adapter.start_background_*()` to `startup()`
- [ ] Populate `SPOT_ID_MAP` in `sensor_adapter.py` if naming differs
- [ ] Tune `DEBOUNCE_*` thresholds to match sensor hardware noise level
- [ ] Test: occupy a real spot, verify the UI updates within ~5 seconds
- [ ] Test: occupy a spot that is currently RESERVED, verify the affected vehicle reroutes

### Vehicle navigation

- [ ] Determine positioning method: RFID zones / BLE phone / UWB / camera
- [ ] For RFID: map zone ids to layout coordinates, change `vehicle_position_adapter`, wire `receive_zone_event()`
- [ ] For BLE: extend `BleScanRequest` with `entity_type` / `entity_id` and branch in `/api/ble_scan`
- [ ] For UWB/camera: wire the infrastructure callback to `POST /api/vehicle_position`
- [ ] Test: drive the user's car through the garage, verify the chevron tracks position and instructions stay in sync

### Pedestrian navigation

- [ ] Install BLE beacons at ~15 m intervals on each floor
- [ ] Calibrate `tx_power` for each beacon model (measure RSSI at 1 m)
- [ ] Populate `BEACON_MAP` with beacon UUIDs and physical coordinates
- [ ] Change `ped_position_adapter = BlePositionAdapter(...)` in `server.py`
- [ ] Test: walk to a parked car, verify the dot tracks the path and instructions fire correctly
- [ ] Test: stand where fewer than 3 beacons are visible, verify the UI degrades gracefully

---

## Files Changed Per Scenario

| Scenario | Files | Lines changed |
|---|---|---|
| Sensors via REST | `server.py` + `requirements.txt` (+ `SPOT_ID_MAP`) | ~10 |
| Sensors via MQTT | `server.py` | ~8 |
| Sensors via webhook | `server.py` | ~2 |
| Vehicle RFID zones | `server.py` | ~8 |
| Vehicle BLE (phone) | `server.py` (adapter + `/api/ble_scan` branch) | ~12 |
| Vehicle UWB / camera | nothing — use existing `/api/vehicle_position` | 0 |
| Pedestrian BLE | `server.py` only (frontend already polls) | ~10 |

---

## Architecture Reference

```
core/
  adapters/
    __init__.py            exports every adapter class + PositionSample,
                           external_to_internal, SPOT_ID_MAP, snap_route_index
    sensor_adapter.py      SensorAdapter base + 4 concrete variants
                           (Simulated / RestPolling / Mqtt / Webhook)
    position_adapter.py    VehiclePositionAdapter  → Simulated · RfidZone · BleVehicle
                           PedestrianPositionAdapter → Simulated ·
                             ServerSimulated (active) · Ble
                           + PositionSample dataclass + snap_route_index()

server.py                  ~L160–172 : the 3 adapter instantiation lines
                           ~L1121    : POST /api/spot_event
                           ~L1175    : POST /api/ble_scan
                           ~L1188    : POST /api/start_navigation
                           ~L1198    : GET  /api/position/{session_id}
                           ~L1220    : POST /api/vehicle_position
                           ~L1241    : POST /api/pause_vehicle
                           ~L1252    : POST /api/resume_vehicle

core/simulation.py         tick(..., position_adapter=None) — falls back to a
                           module-level SimulatedVehiclePositionAdapter when None
```

### What never changes

- `core/offline.py` — precomputed routing tables
- `core/floor_selection.py` — primary spot + floor selection
- `core/scoring.py` — legacy ranking fallback
- `core/pedestrian.py` — pedestrian graph and Dijkstra
- `core/dijkstra.py`, `core/graphs.py` — graph primitives
- `core/layout_loader.py`, `layouts/*.json`
- All of `frontend/` — including `FindMyCarScreen.jsx`, which already consumes
  server-provided positions

The routing brain of the system is completely isolated from how position and
occupancy data arrives. Swap the source, keep the intelligence.
