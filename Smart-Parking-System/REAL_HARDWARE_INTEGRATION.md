# Real Hardware Integration Guide

**Smart Parking System — Adapter Architecture**

---

## Overview

The system is designed so that connecting real hardware requires changing
**only a few lines in `server.py`**. All routing logic, navigation, spot
selection, and UI are completely unaffected.

This is achieved through an **adapter layer** in `core/adapters/` that
isolates every external data source behind a common interface:

```
┌─────────────────────────────────────────────────────────────────────┐
│                          server.py                                   │
│                                                                      │
│  sensor_adapter           vehicle_position_adapter   ped_position   │
│       │                           │                       │         │
│  ─────▼──────────────────────────▼───────────────────────▼──────── │
│                    core/adapters/                                    │
│  ─────────────────────────────────────────────────────────────────  │
│  SensorAdapter      VehiclePositionAdapter   PedestrianPositionAdapt│
│  (who says a        (who knows where         (who knows where the   │
│   spot is taken?)    the car is?)             pedestrian is?)       │
│  ─────────────────────────────────────────────────────────────────  │
│                    core/simulation.py  (routing logic — never        │
│                    core/scoring.py      changes when you swap        │
│                    core/pedestrian.py   hardware)                   │
└─────────────────────────────────────────────────────────────────────┘
```

**Today:** all three adapters are `Simulated*` variants — they run the
demo without any real hardware.

**In production:** replace each `Simulated*` line with the real adapter.
Nothing else changes.

---

## The Three Adapters

### 1. `sensor_adapter` — Spot Occupancy

Who tells the system whether a parking spot is free or occupied?

| Adapter | When to use |
|---|---|
| `SimulatedSensorAdapter` | **Today** — simulation writes occupancy itself |
| `RestPollingSensorAdapter` | Sensor platform exposes a REST API you poll |
| `MqttSensorAdapter` | Sensor platform pushes events via MQTT broker |
| `WebhookSensorAdapter` | Sensor platform POSTs to your server |

### 2. `vehicle_position_adapter` — Vehicle Location

Who knows where the car currently is inside the garage?

| Adapter | When to use |
|---|---|
| `SimulatedVehiclePositionAdapter` | **Today** — position is computed from route + speed |
| `RfidZoneVehicleAdapter` | RFID loop detectors at aisle entrances |
| *(extend `VehiclePositionAdapter`)* | UWB anchors, overhead cameras, etc. |

### 3. `ped_position_adapter` — Pedestrian Location

Who knows where the user is walking inside the garage?

| Adapter | When to use |
|---|---|
| `SimulatedPedestrianPositionAdapter` | **Today** — frontend animates walking locally |
| `BlePositionAdapter` | BLE beacons + phone app reporting RSSI |
| *(extend `PedestrianPositionAdapter`)* | UWB, WiFi fingerprinting, etc. |

---

## Switching to Real Hardware

### Step 1 — Spot Occupancy Sensors

#### Option A: The sensor system exposes a REST API (most common)

The sensor platform has an endpoint you can poll, returning a list of
spots with their current occupancy state.

**`server.py` — change these lines:**

```python
# BEFORE (simulation):
sensor_adapter = SimulatedSensorAdapter(state.runtime)

# AFTER:
from core.adapters import RestPollingSensorAdapter
sensor_adapter = RestPollingSensorAdapter(
    runtime         = state.runtime,
    url             = "https://192.168.1.50/api/spots",   # sensor platform URL
    api_key         = "Bearer <your-api-key>",             # if required
    poll_interval_s = 5.0,                                 # how often to poll
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

If the platform uses different field names (`status`, `state`, `is_taken`,
etc.) — edit the `_fetch_raw_states()` method in `sensor_adapter.py` to
match. It's a single dict comprehension, clearly marked.

---

#### Option B: MQTT push (low-latency, event-driven)

The sensor platform publishes to an MQTT broker whenever a spot changes.

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

Requires: `pip install aiomqtt`

---

#### Option C: The sensor platform sends webhooks to you

The sensor system can be configured to POST to your server whenever a
spot changes state. The endpoint `POST /api/spot_event` already exists.

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

When this dict is populated, `external_to_internal()` translates every
incoming ID automatically. If an external ID has no mapping, it is passed
through unchanged (so if the naming conventions match, the dict stays empty).

---

#### Debounce Thresholds

Real sensors are noisy: a car driving slowly past a spot, a motorcycle,
or a sensor glitch can produce brief false readings. The adapter holds a
state change in a pending queue and only confirms it after the sensor has
held the same reading for:

```python
# core/adapters/sensor_adapter.py
DEBOUNCE_FREE_TO_OCC_S = 2.0   # sensor must read "occupied" for 2s before accepting
DEBOUNCE_OCC_TO_FREE_S = 3.0   # sensor must read "free" for 3s before accepting
```

Adjust these values based on your sensor hardware's observed noise characteristics.

---

### Step 2 — Vehicle Positioning

#### Option A: RFID zone checkpoints (most practical for garages)

RFID loop detectors or gate readers at the entrance of each aisle section
detect when a car enters a zone and report its tag ID. This gives coarse
but reliable position. Between checkpoints, the system uses dead reckoning
(same as simulation).

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

The `vid` must match the vehicle ID in the system. For the user's car
this is `"user_car_1"`. For managed fleet vehicles, use their plate or
tag ID as the vehicle ID when spawning via `POST /api/spawn`.

---

#### Option B: Direct position feed (UWB / overhead cameras)

If your infrastructure produces exact coordinates (UWB time-of-flight
anchors, overhead cameras with plate recognition, etc.), use the
`POST /api/vehicle_position` endpoint directly. It already exists.

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

The server writes the position and automatically re-snaps `route_i`
(the vehicle's progress along its planned route) so navigation instructions
stay synchronised with the real location.

In simulation mode this endpoint exists but has no lasting effect —
`SimulatedVehiclePositionAdapter` overwrites position every tick. Switch
to a real adapter before wiring external position feeds.

---

### Step 3 — Pedestrian Positioning (Find My Car)

**How it works today (simulation):**
The `FindMyCarScreen.jsx` frontend simulates walking locally — it advances
an animated dot along the route at 1.2 m/s. The server has no knowledge
of where the pedestrian actually is.

**How it works with real BLE beacons:**

BLE beacons (iBeacon or Eddystone) are mounted at known positions in the
garage ceiling, one per ~15 m. The phone app scans for nearby beacons,
measures their signal strength (RSSI), and the server trilaterates the user's
position from three or more readings.

#### Server side

**`server.py`:**

```python
from core.adapters import BlePositionAdapter

BEACON_MAP = {
    "B0001": {"x":  75, "y": 100, "floor": 0, "tx_power": -59},
    "B0002": {"x": 175, "y": 100, "floor": 0, "tx_power": -59},
    "B0003": {"x": 275, "y": 100, "floor": 0, "tx_power": -59},
    "B0004": {"x":  75, "y":  50, "floor": 0, "tx_power": -59},
    # one entry per physical beacon, coordinates from your layout JSON
    # tx_power: measured RSSI at 1 metre distance (calibrate per beacon model)
}

ped_position_adapter = BlePositionAdapter(beacon_map=BEACON_MAP)
```

The endpoints `POST /api/ble_scan` and `GET /api/position/{session_id}`
already exist in `server.py`. No further changes needed on the server.

#### Frontend side (`FindMyCarScreen.jsx`)

Replace the simulated walking in `usePositionSource` with API polling:

```javascript
// BEFORE (simulation — animates walking along the route):
// usePositionSource returns a position that advances at 1.2 m/s

// AFTER (real BLE):
// 1. Phone scans beacons every ~1s and POSTs to /api/ble_scan
// 2. usePositionSource polls /api/position/{sessionId} for real position

const sessionId = useRef(`ped_${Date.now()}`).current

// In the position polling effect:
useEffect(() => {
    const interval = setInterval(async () => {
        // Send BLE scan (from native BLE SDK / Capacitor / React Native)
        const beacons = await getBleBeacons()   // your native SDK call
        await fetch('/api/ble_scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, beacons })
        })

        // Retrieve trilaterated position
        const { position } = await fetch(`/api/position/${sessionId}`).then(r => r.json())
        if (position) setCurrentPosition(position)
    }, 1000)
    return () => clearInterval(interval)
}, [])
```

This is the only frontend change required. All navigation instruction
logic, map rendering, and step detection continue to work unchanged because
they consume the same `{x, y, floor}` structure regardless of source.

---

## Complete Checklist

### Spot occupancy sensors

- [ ] Determine integration method: REST poll / MQTT / webhook
- [ ] Obtain API credentials / broker address from sensor platform
- [ ] Change `sensor_adapter = ...` in `server.py` (3–5 lines)
- [ ] If REST or MQTT: add `sensor_adapter.start_background_*()` to `startup()`
- [ ] Populate `SPOT_ID_MAP` in `sensor_adapter.py` if naming differs
- [ ] Tune `DEBOUNCE_*` thresholds to match sensor hardware noise level
- [ ] Test: occupy a real spot, verify UI updates within ~5 seconds

### Vehicle navigation

- [ ] Determine positioning method: RFID zones / UWB / camera
- [ ] For RFID: map zone IDs to layout coordinates, change `vehicle_position_adapter`
- [ ] For UWB/camera: wire infrastructure callback to `POST /api/vehicle_position`
- [ ] Test: drive the user's car through the garage, verify blue arrow tracks position

### Pedestrian navigation

- [ ] Install BLE beacons at ~15 m intervals on each floor
- [ ] Calibrate `tx_power` for each beacon model (measure RSSI at 1 m)
- [ ] Populate `BEACON_MAP` with beacon UUIDs and physical coordinates
- [ ] Change `ped_position_adapter = BlePositionAdapter(...)` in `server.py`
- [ ] Update `usePositionSource` in `FindMyCarScreen.jsx` to poll `/api/position/{id}`
- [ ] Test: walk to a parked car, verify blue dot tracks path and instructions fire correctly

---

## Files Changed Per Scenario

| Scenario | Files | Lines changed |
|---|---|---|
| Sensors via REST | `server.py` + `sensor_adapter.py` (SPOT_ID_MAP) | ~8 |
| Sensors via MQTT | `server.py` | ~6 |
| Sensors via webhook | `server.py` | ~1 |
| Vehicle RFID zones | `server.py` | ~8 |
| Vehicle UWB / camera | nothing — use existing `/api/vehicle_position` | 0 |
| Pedestrian BLE | `server.py` + `FindMyCarScreen.jsx` | ~15 |

---

## Architecture Reference

```
core/
  adapters/
    __init__.py            exports all adapter classes
    sensor_adapter.py      SensorAdapter base + all 4 concrete variants
    position_adapter.py    VehiclePositionAdapter + PedestrianPositionAdapter
                           + PositionSample dataclass + snap_route_index()

server.py                  Lines ~130–145: the 3 adapter instantiation lines
                           Lines ~430–520: new endpoints (spot_event, ble_scan,
                                          vehicle_position, position/{id})

core/simulation.py         tick() accepts position_adapter= parameter
                           (defaults to SimulatedVehiclePositionAdapter)
```

### What never changes

- `core/offline.py` — precomputed routing tables
- `core/scoring.py` — spot selection algorithm
- `core/pedestrian.py` — pedestrian graph and Dijkstra
- `core/dijkstra.py`, `core/graphs.py` — graph primitives
- All of `frontend/` except `usePositionSource` in `FindMyCarScreen.jsx`

The routing brain of the system is completely isolated from how position
and occupancy data arrives. Swap the source, keep the intelligence.
