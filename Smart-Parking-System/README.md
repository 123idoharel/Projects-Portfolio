# Smart Parking System

A real-time parking guidance system with vehicle routing, spot assignment,
and pedestrian navigation. Built with FastAPI (Python) + React.

Designed from the ground up so that **connecting real hardware requires
changing only a handful of lines** — see [`REAL_HARDWARE_INTEGRATION.md`](./REAL_HARDWARE_INTEGRATION.md).

---

## What it does

| View | What you see |
|---|---|
| **Driver** | Choose a destination (elevator / exit / nearest). Get turn-by-turn navigation to an assigned spot. "I parked elsewhere" manual override. |
| **Find My Car** | Walk from the elevator back to your parked car with step-by-step pedestrian navigation. |
| **Operator** | Live top-down map, 60 fps smooth vehicle movement, event log, scenario controls. |

---

## Quick Start

### Requirements
- Python 3.9+
- Node.js 18+

### 1 — Backend

```bash
cd parking_system
pip install fastapi "uvicorn[standard]" websockets pydantic
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 2 — Frontend (development)

```bash
cd parking_system/frontend
npm install
npm run dev          # → http://localhost:5173
```

### 2 (alternative) — Frontend (production build)

```bash
cd parking_system/frontend
npm install && npm run build
# then just use the backend: http://localhost:8000
```

---

## Project Structure

```
parking_system/
│
├── server.py                    FastAPI backend — HTTP + WebSocket + adapter wiring
├── requirements.txt
├── README.md                    ← you are here
├── REAL_HARDWARE_INTEGRATION.md ← how to connect real sensors and beacons
│
├── core/                        All Python logic — pure, testable, no web framework
│   ├── adapters/                Hardware abstraction layer (swap sim ↔ real)
│   │   ├── sensor_adapter.py    Spot occupancy: Simulated / REST / MQTT / Webhook
│   │   └── position_adapter.py  Vehicle + pedestrian positioning: Sim / RFID / BLE
│   │
│   ├── graphs.py                Node + Graph data structures
│   ├── dijkstra.py              Shortest-path algorithm (used by driving + pedestrian)
│   ├── layout_loader.py         Load + validate layout JSON files
│   ├── offline.py               Pre-compute all Dijkstra tables at startup (cached)
│   ├── scoring.py               Spot selection algorithm (elevator / exit / entrance)
│   ├── simulation.py            Routing decisions + state transitions (not movement)
│   ├── pedestrian.py            6-layer pedestrian graph + walk route computation
│   ├── scenarios.py             Scenario presets (Demo / Full Simulation / etc.)
│   ├── config.py                Load settings.json
│   └── settings.json            Tunable thresholds (speeds, debounce, weights)
│
├── layouts/
│   └── azrieli_dual_lanes.json  Parking facility layout definition
│
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── api/
        │   └── parkingApi.js        REST + WebSocket API client
        ├── hooks/
        │   ├── useParking.js        Central state: spots, vehicles, stats
        │   └── useWebSocket.js      Auto-reconnecting WebSocket client
        ├── canvas/
        │   ├── ParkingRenderer.js   Operator 2D top-down map renderer
        │   ├── VehicleLayer.js      60 fps interpolation (decoupled from 20 fps server)
        │   └── WazePerspective.js   Driver perspective renderer (road surface, turns)
        └── views/
            ├── DriverView.jsx       Driver UI: choose → navigate → parked
            ├── FindMyCarScreen.jsx  Pedestrian navigation (walk to parked car)
            ├── NavCanvas.jsx        Driver navigation canvas wrapper
            ├── FloorCanvas.jsx      Per-floor map (used in operator view)
            └── OperatorView.jsx     Operator dashboard
```

---

## Architecture

### Communication

```
Browser                              FastAPI Server
  │                                       │
  ├─ GET  /api/layout ──────────────────► nodes, edges, spots, targets (once)
  │                                       │
  ├─ WebSocket /ws/state ◄──────────────── frame every 50ms (20 fps):
  │      vehicles: x, y, heading,         │   vehicles[] + spots_delta[] + stats
  │      status, route, instruction       │
  │                                       │
  ├─ POST /api/assign ─────────────────► assign spot + build route
  ├─ POST /api/spawn  ─────────────────► add simulation vehicle
  ├─ POST /api/steal  ─────────────────► force-occupy a spot (demo)
  ├─ POST /api/free   ─────────────────► free a spot
  ├─ POST /api/remove ─────────────────► remove vehicle
  ├─ POST /api/pause_vehicle ──────────► freeze vehicle in place
  ├─ POST /api/resume_vehicle ─────────► unfreeze vehicle
  ├─ POST /api/walk_route ─────────────► compute pedestrian route
  │
  │  ── Real-hardware endpoints (dormant in simulation) ──
  ├─ POST /api/spot_event ─────────────► sensor webhook (occupied/free)
  ├─ POST /api/ble_scan ───────────────► BLE RSSI scan from phone app
  ├─ POST /api/vehicle_position ───────► direct position update (UWB/camera)
  └─ GET  /api/position/{session_id} ──► get pedestrian position
```

### 60 fps smooth movement

The server ticks at 20 fps and pushes target positions.
The browser renders at 60 fps using lerp interpolation:

```
Server 20fps → target positions
                    ↓
Browser 60fps: display += (target - display) × 0.18   ← VehicleLayer.js
                    ↓
              Canvas.draw(display position)
```

Vehicles never jump — they flow exactly like Waze.

### Offline pre-computation

At startup, `offline.py` runs Dijkstra from every entrance and from every
exit (reversed graph). Results are cached by layout hash in `data/`.
On the next restart with the same layout, cache loads in milliseconds.

Per spot, the cache stores:
- `drive_time[entrance]` — seconds from entrance to this spot
- `best_access[entrance]` — which road node to turn from
- `target_cost[elevator/exit]` — walk distance or drive-to-exit time
- Tie-break helpers (Euclidean to entrance, last ramp used)

### Spot selection algorithm (scoring.py)

**Elevator mode** (distance-first with significant-save switching):
1. Keep only spots within 15 m of the best walk distance.
2. Start with the closest-to-elevator spot.
3. Switch to a farther spot only if it saves ≥ max(35 s, 40% of current drive time).
4. Fine tie-break: drive time → Euclidean to entrance / last ramp.

**Exit mode**: weighted score = `distance×10 + congestion×2 + drive_time×0.5`

### Pedestrian graph (pedestrian.py)

A separate 261-node / 757-edge graph built on top of the driving layout.
Six edge layers:

| Layer | Purpose |
|---|---|
| Driving roads (bidirectional) | Cross aisles freely |
| Spot access | Last metre from road to spot |
| Corridor nodes (CORR_*) | Walk along the open space between facing rows |
| Row shortcuts | Step laterally between adjacent spots |
| Column shortcuts | Cross the corridor directly to the facing spot |
| Elevator entry | Wire elevators into the corridor chain |

Corridors are detected automatically from the layout — no hardcoded Y values.

### Adapter layer (core/adapters/)

Three swappable data sources. Today all are `Simulated*`.
To connect real hardware, replace one or more — see `REAL_HARDWARE_INTEGRATION.md`.

```
sensor_adapter           → who reports spot occupancy?
vehicle_position_adapter → where is the car?
ped_position_adapter     → where is the pedestrian?
```

---

## Layout JSON Format

Layouts live in `layouts/`. The operator can switch between them at runtime.

```jsonc
{
  "meta": { "name": "My Garage", "floors": 2 },

  "driving": {
    "nodes": [
      { "id": "F0_A1", "floor": 0, "x": 50, "y": 75, "type": "intersection" }
    ],
    "edges": [
      { "from": "F0_A1", "to": "F0_A2", "length_m": 50, "type": "main", "bidir": true }
    ]
  },

  "spots": [
    {
      "id": "F0-A01",
      "floor": 0,  "x": 60,  "y": 85,
      "road_y": 75,                         // Y of the driving aisle in front
      "access": [{ "node": "F0_A1" }],      // which road node to approach from
      "theft_risk": 0.0
    }
  ],

  "targets": [
    { "id": "ELEV_TOWER_A", "type": "elevator", "floor": 0, "x": 75, "y": 100,
      "subtype": "tower_a", "label": "Tower A" },
    { "id": "EXIT_MAIN", "type": "exit", "drive_node": "EXIT_NODE_ID",
      "label": "Main Exit" }
  ],

  "entrances": ["ENT_LANE_A", "ENT_LANE_B"]
}
```

**Node types:** `intersection` · `entrance` · `exit` · `ramp` · `elevator`
**Edge types:** `main` · `aisle` · `ramp` · `turn`

---

## Configuration (core/settings.json)

```jsonc
{
  "selection": {
    "distance_window_m":   15.0,  // candidate window above best walk distance
    "distance_equal_eps_m": 1.0,  // treat walk distances as equal within this
    "time_equal_eps_s":     2.0,  // treat drive times as equal within this
    "time_save_min_s":     35.0,  // minimum meaningful time saving
    "time_save_frac":       0.40  // fraction of current drive time for significance
  },
  "offline": {
    "driving_speed_mps": { "main": 3.0, "aisle": 2.4, "ramp": 1.2 },
    "spot_maneuver_sec_per_meter": 0.30
  },
  "runtime": {
    "default_vehicle_speed": 3.0
  }
}
```

---

## Scenarios

| Name | Description |
|---|---|
| `Demo` | Full manual control. No auto events. |
| `זרימת יציאה` | 85% pre-filled, vehicles leave gradually. |
| `סימולציה מלאה` | Continuous arrivals, departures, and spot theft. |
| `Normal` | Standard operating mode. |

---

## Key Design Decisions

**Why a separate pedestrian graph?**
Drivers must follow one-way aisles and stay on roads. Pedestrians can cross
aisles freely, walk through corridor space between rows, and step between
adjacent spots. Re-using the driving graph with tweaked weights would be
incorrect — a separate graph encodes the real physical paths.

**Why offline pre-computation?**
Running Dijkstra from every entrance on every vehicle arrival would be
O(V log V) per request. Pre-computing once at startup reduces spot assignment
to a table lookup — microseconds instead of milliseconds.

**Why adapters instead of direct code?**
The routing intelligence (Dijkstra, scoring, pedestrian graph) never needs
to know how position data arrives. Separating "what happens" from "where
the data comes from" means hardware integration is additive, not invasive.

**Why lerp interpolation in the browser?**
WebSocket pushes at 20 fps (50 ms intervals). Without interpolation,
vehicles would visibly jump at each update. The browser renders at 60 fps
and smoothly interpolates between server-provided positions, giving the
same fluid feel as commercial navigation apps.
