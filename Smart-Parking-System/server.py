"""
server.py — FastAPI Backend v8
================================

Changes from v7:
  • /api/assign_direct  — new endpoint: driver selects target group + has_disability;
                          the server automatically picks the best floor and spot using
                          the spiral/floor-competition algorithm. Replaces the two-step
                          /api/floor_options → /api/assign flow for real drivers.
  • /api/floor_options  — retained for simulation/operator tools only (unchanged).
  • /api/assign         — retained for simulation/autonomous vehicles (unchanged).

Hardware infrastructure (BLE, sensor adapters, WebSocket, pedestrian nav) is
fully preserved and unchanged from v7.
"""

import asyncio
import threading
import json
import math
import os
import random
import uuid as _uuid

SERVER_START_TOKEN = _uuid.uuid4().hex

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))
from core.config import CFG
from core.layout_loader import load_layout
from core.offline import load_or_build_offline
from core.scenarios import SCENARIOS
from core.simulation import (
    init_runtime_state,
    prefill_spots,
    tick,
    ensure_user_vehicle,
    assign_and_build_route,
    reassign_from_current,
    find_spot,
    now_ts,
    _find_forward_node,
)
from core.floor_selection import (
    select_spot_auto,
    _resolve_floor_options_base_radius,
    _select_best_spot_on_floor,
    resolve_initial_zone_radius,
    ELEVATOR_TYPES,
    _eff_sub,
)

app = FastAPI(title="Smart Parking v8")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR     = Path(__file__).parent
LAYOUTS_DIR  = BASE_DIR / "layouts"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


# ── Global simulation state ───────────────────────────────────────────────────
class SimState:
    def __init__(self):
        self.layout_path: str = ""
        self.layout: Dict = {}
        self.offline: Dict = {}
        self.runtime: Dict = {"spots": [], "vehicles": {}}
        self.scenario_name: str = "Demo"
        self.scenario: Dict = dict(SCENARIOS["Demo"])
        self.weights: Dict = dict(CFG["ui"]["default_weights"])
        self.speed: float = 3.0
        self.event_log: List[Dict] = []
        self._loaded: bool = False

    def load(self, layout_path: str, scenario_name: str = "Demo"):
        self.layout_path = layout_path
        self.layout = load_layout(layout_path)
        self.offline = load_or_build_offline(layout_path, self.layout)
        self.scenario_name = scenario_name
        self.scenario = dict(SCENARIOS.get(scenario_name, SCENARIOS["Demo"]))
        self.runtime = init_runtime_state(self.offline)
        ratio = self.scenario.get("prefill_occupied_ratio", 0.0)
        if ratio > 0:
            prefill_spots(self.runtime["spots"], ratio)
        self.event_log = []
        self._loaded = True

    def log(self, msg: str, t: str = "info"):
        self.event_log.insert(0, {
            "time": time.strftime("%H:%M:%S"),
            "msg": msg,
            "type": t,
        })
        max_log = CFG["ui"].get("max_event_log", 50)
        if len(self.event_log) > max_log:
            self.event_log.pop()


state = SimState()
_state_lock = threading.Lock()


class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        msg = json.dumps(data, default=_json_default)
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()


def _json_default(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    raise TypeError(f"Not serializable: {type(obj)}")


# ── Adapter wiring ────────────────────────────────────────────────────────────
# Three lines control simulation vs. production mode.
# See REAL_HARDWARE_INTEGRATION.md for details.
#
# Sensor adapter:
#   SimulatedSensorAdapter    → internal simulation (default)
#   RestPollingSensorAdapter  → poll REST endpoint every N seconds
#   MqttSensorAdapter         → subscribe to MQTT broker
#   WebhookSensorAdapter      → receive POSTs at /api/spot_event
#
# Vehicle position adapter:
#   SimulatedVehiclePositionAdapter → dead-reckoning simulation (default)
#   BleVehiclePositionAdapter       → BLE RSSI from car's phone
#
# Pedestrian position adapter:
#   ServerSimulatedPedestrianPositionAdapter → server advances walker (default)
#   BlePositionAdapter                       → real BLE beacons
from core.adapters import (
    SimulatedSensorAdapter,
    SimulatedVehiclePositionAdapter,
    SimulatedPedestrianPositionAdapter,
    ServerSimulatedPedestrianPositionAdapter,
    BleVehiclePositionAdapter,
)

sensor_adapter           = SimulatedSensorAdapter(state.runtime)
vehicle_position_adapter = SimulatedVehiclePositionAdapter()
ped_position_adapter     = ServerSimulatedPedestrianPositionAdapter()


# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    layouts = sorted(LAYOUTS_DIR.glob("*.json"))
    preferred = LAYOUTS_DIR / "azrieli_mall_large.json"
    layout_path = str(preferred) if preferred.exists() else (str(layouts[0]) if layouts else None)
    if layout_path:
        state.load(layout_path)
        sensor_adapter.runtime = state.runtime
    asyncio.create_task(simulation_loop())


# ── Simulation loop ───────────────────────────────────────────────────────────
_prev_spot_statuses: Dict[str, str] = {}

async def simulation_loop():
    global _prev_spot_statuses
    dt_target = 0.05  # 20 fps

    while True:
        t0 = time.time()

        # Pedestrian simulation advances regardless of WS clients.
        # Sessions are cheap in-memory ops and must not stall when no browser is open.
        if state._loaded and hasattr(ped_position_adapter, 'advance_all'):
            ped_position_adapter.advance_all(dt_target * state.speed)

        if state._loaded and manager.active:
            effective_dt = dt_target * state.speed

            with _state_lock:
                # 1. Advance vehicle routing + movement
                tick(state.offline, state.runtime, state.scenario,
                     state.weights, effective_dt,
                     position_adapter=vehicle_position_adapter)

                # 2. Poll spot occupancy from sensor layer
                # (sensor_adapter.poll_once is a fast in-memory op in simulation mode)

                # 3. Simulation-only auto events (disabled when using real sensors)
                sc = state.scenario
                if sc.get("auto_exit_rate", 0) > 0:
                    if random.random() < sc["auto_exit_rate"] * effective_dt:
                        _free_random()
                if sc.get("auto_entry_rate", 0) > 0:
                    free_count = sum(1 for s in state.runtime["spots"] if s["status"] == "FREE")
                    if free_count > 3 and random.random() < sc["auto_entry_rate"] * effective_dt:
                        _auto_spawn()
                if sc.get("steal_base_rate", 0) > 0 and state.scenario_name == "סימולציה מלאה":
                    if random.random() < sc["steal_base_rate"] * effective_dt * 0.3:
                        _steal_random()

                frame = _build_frame()

            # Sensor polling may do I/O; run outside the lock
            await sensor_adapter.poll_once()
            await manager.broadcast(frame)

        elapsed = time.time() - t0
        await asyncio.sleep(max(0, dt_target - elapsed))

def _build_frame() -> Dict:
    global _prev_spot_statuses

    # spots delta (only changed)
    spots_delta = []
    for s in state.runtime["spots"]:
        prev = _prev_spot_statuses.get(s["id"])
        if prev != s["status"]:
            spots_delta.append({
                "id": s["id"],
                "status": s["status"],
                "floor": s["floor"],
                "x": s["x"],
                "y": s["y"],
                "spot_type": s.get("spot_type", "standard"),
            })
            _prev_spot_statuses[s["id"]] = s["status"]

    # vehicles
    vehicles = []
    for v in state.runtime["vehicles"].values():
        route = v.get("route_xy", [])
        ri = v.get("route_i", 0)

        # heading
        heading = 0.0
        if route and ri < len(route) - 1:
            nx, ny = float(route[ri + 1][0]), float(route[ri + 1][1])
            heading = math.atan2(ny - float(v["y"]), nx - float(v["x"]))

        # distance to spot
        dist = 0.0
        if route and ri < len(route):
            for j in range(ri, len(route) - 1):
                p1, p2 = route[j], route[j + 1]
                dist += math.sqrt((float(p2[0]) - float(p1[0]))**2 + (float(p2[1]) - float(p1[1]))**2)

        # next instruction
        instr = _get_instruction(v)

        vehicles.append({
            "id": v["id"],
            "kind": v.get("kind", "MANUAL"),
            "x": float(v["x"]),
            "y": float(v["y"]),
            "floor": int(v["floor"]),
            "heading": heading,
            "status": v.get("status", "CHOOSING"),
            "assigned_spot": v.get("assigned_spot"),
            "assigned_target_id": v.get("assigned_target_id"),
            "assigned_target_info": v.get("assigned_target_info"),
            "distance_to_spot": dist,
            "instruction": instr,
            "route_remaining": [
                [float(p[0]), float(p[1]), int(p[2])]
                for p in (route[ri:] if route else [])
                if len(p) >= 3
            ][:30],  # cap to 30 points
        })

    # stats
    spots = state.runtime["spots"]
    free = sum(1 for s in spots if s["status"] == "FREE")
    reserved = sum(1 for s in spots if s["status"] == "RESERVED")
    occupied = sum(1 for s in spots if s["status"] == "OCCUPIED")
    driving = sum(1 for v in state.runtime["vehicles"].values() if v.get("status") == "DRIVING")

    return {
        "t": time.time(),
        "vehicles": vehicles,
        "spots_delta": spots_delta,
        "stats": {
            "free": free,
            "reserved": reserved,
            "occupied": occupied,
            "total": len(spots),
            "driving": driving,
            "occupancy_pct": round((reserved + occupied) / max(1, len(spots)) * 100),
        },
        "event_log": state.event_log[:10],
    }

def _get_instruction(v: Dict) -> Dict:
    """
    Returns the NEXT maneuver instruction with distance to it.
    Format: { direction, distance_to_next, total_dist, icon, text, dist_text }
    - distance_to_next: meters until the next turn/arrival
    - total_dist:       meters remaining to destination
    So the HUD can show: "פנה ימינה בעוד 80מ'"  or  "המשך ישר 45מ'"
    """
    if v.get("status") == "RECALCULATING":
        return {"direction": "recalculating", "distance": 0, "distance_to_next": 0,
                "total_dist": 0, "icon": "⟳", "text": "מחשב מסלול מחדש...", "dist_text": ""}

    route = v.get("route_xy", [])
    i = int(v.get("route_i", 0))
    if not route or i >= len(route) - 1:
        return {"direction": "arrived", "distance": 0, "distance_to_next": 0,
                "total_dist": 0, "icon": "🏁", "text": "הגעת!", "dist_text": ""}

    # Total remaining distance
    total_dist = 0.0
    for j in range(i, len(route) - 1):
        p1, p2 = route[j], route[j + 1]
        total_dist += math.sqrt((float(p2[0]) - float(p1[0]))**2 + (float(p2[1]) - float(p1[1]))**2)

    TURN_THRESHOLD = 8.0   # cross-product magnitude to count as a turn

    # Scan ahead to find NEXT significant turn
    dist_to_next = 0.0
    for j in range(i, len(route) - 2):
        seg_len = math.sqrt(
            (float(route[j+1][0]) - float(route[j][0]))**2 +
            (float(route[j+1][1]) - float(route[j][1]))**2
        )
        dist_to_next += seg_len

        a, b, c = route[j], route[j + 1], route[j + 2]
        v1 = (float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))
        v2 = (float(c[0]) - float(b[0]), float(c[1]) - float(b[1]))
        cross = v1[0] * v2[1] - v1[1] * v2[0]

        if abs(cross) > TURN_THRESHOLD:
            direction = "left" if cross > 0 else "right"
            icon = "⬅️" if direction == "left" else "➡️"
            turn_text = "פנה שמאלה" if direction == "left" else "פנה ימינה"
            dist_rounded = round(dist_to_next)

            if dist_rounded < 5:
                # We're at the turn right now
                return {"direction": direction, "distance": total_dist,
                        "distance_to_next": 0, "total_dist": total_dist,
                        "icon": icon, "text": turn_text, "dist_text": ""}
            else:
                # Show upcoming turn with distance
                return {"direction": "straight", "distance": total_dist,
                        "distance_to_next": dist_rounded, "total_dist": total_dist,
                        "icon": "⬆️",
                        "text": f"המשך ישר {dist_rounded}מ'",
                        "dist_text": f"{turn_text} בעוד {dist_rounded}מ'",
                        "next_turn": direction, "next_icon": icon}

    # No turn ahead — straight to destination
    dist_rounded = round(total_dist)
    return {"direction": "straight", "distance": total_dist,
            "distance_to_next": dist_rounded, "total_dist": total_dist,
            "icon": "⬆️",
            "text": f"המשך ישר {dist_rounded}מ'",
            "dist_text": ""}

# ── Helper actions ────────────────────────────────────────────────────────────
def _free_random():
    occ = [s for s in state.runtime["spots"] if s["status"] == "OCCUPIED"]
    if occ:
        s = random.choice(occ)
        s["status"] = "FREE"
        s["reserved_for"] = None
        state.log(f"🚗 {s['id']} התפנה", "exit")


def _auto_spawn():
    targets = state.offline.get("target_options", [])
    tids = [t["id"] for t in targets if t["id"] not in ("elevator", "exit", "entrance") and t.get("type") not in ("entrance",)]
    if not tids:
        return
    vid = f"A_{int(time.time() * 1000)}"
    eid = random.choice(state.layout["entrances"])
    _spawn_vehicle(vid, random.choice(tids), eid)

def _steal_random():
    reserved = [s for s in state.runtime["spots"]
                if s["status"] == "RESERVED" and s.get("reserved_for")]
    if reserved:
        _force_occupy(random.choice(reserved)["id"])


def _spawn_vehicle(
    vid: str, target_type: str, entrance_id: str,
    preferred_spot_id: Optional[str] = None,
    target_instance_id: Optional[str] = None,
    has_disability: bool = False,
) -> bool:
    dn = state.offline["driving_nodes"]
    e  = dn.get(entrance_id, {})
    state.runtime["vehicles"][vid] = {
        "id": vid, "kind": "MANUAL", "entrance_id": entrance_id,
        "target_type": target_type, "status": "CHOOSING",
        "assigned_spot": None, "assigned_target_id": None,
        "assigned_target_info": None,
        "route_xy": [], "route_i": 0,
        "visited_floors": [],
        "x": float(e.get("x", 0)), "y": float(e.get("y", 0)),
        "floor": int(e.get("floor", 0)),
        "speed_mps": 3.0,
    }
    effective = target_type
    if target_instance_id:
        inst_key = f"elevator_inst_{target_instance_id}"
        if inst_key in state.offline.get("rankings", {}):
            effective = inst_key

    if preferred_spot_id:
        locked = _reserve_preferred_spot(preferred_spot_id, vid, state.scenario["reserve_seconds"])
        ok = assign_and_build_route(
            state.offline, state.runtime, vid, effective,
            state.weights, state.scenario["reserve_seconds"],
            forced_spot_id=preferred_spot_id if locked else None,
            has_disability=has_disability,
        )
    else:
        ok = assign_and_build_route(
            state.offline, state.runtime, vid, effective,
            state.weights, state.scenario["reserve_seconds"],
            has_disability=has_disability,
        )

    if ok:
        v = state.runtime["vehicles"][vid]
        state.log(f"🚙 {vid}→{v.get('assigned_spot', '?')}{chr(32)+chr(9851) if has_disability else ''}", "entry")
    else:
        # Clean up ghost spot and ghost vehicle on assignment failure.
        # Without this, a preferred_spot_id that was reserved before the route
        # build failed will stay RESERVED forever, and the vehicle dict entry
        # stays in CHOOSING state with no route — both invisible orphans.
        if preferred_spot_id:
            s = find_spot(state.runtime["spots"], preferred_spot_id)
            if s and s.get("reserved_for") == vid:
                s["status"] = "FREE"
                s["reserved_for"] = None
        state.runtime["vehicles"].pop(vid, None)
    return ok


def _force_occupy(spot_id: str, thief: str = "THIEF"):
    global _prev_spot_statuses
    with _state_lock:
        for s in state.runtime["spots"]:
            if s["id"] != spot_id:
                continue
            affected = s.get("reserved_for")
            s["status"]       = "OCCUPIED"
            s["reserved_for"] = thief
            _prev_spot_statuses.pop(spot_id, None)

            if affected and affected in state.runtime["vehicles"]:
                v = state.runtime["vehicles"][affected]
                forward_hint = _find_forward_node(state.offline["driving_nodes"], v)
                v["status"]             = "RECALCULATING"
                v["assigned_spot"]      = None
                v["assigned_target_id"] = None
                v["route_xy"]           = []
                v["route_i"]            = 0
                state.log(f"🚧 {spot_id} נגנב! מחשב מחדש עבור {affected}...", "steal")
                ok = reassign_from_current(
                    state.offline, state.runtime, affected,
                    state.weights, state.scenario["reserve_seconds"],
                    forward_hint=forward_hint,
                )
                if ok:
                    new_spot = state.runtime["vehicles"][affected].get("assigned_spot", "?")
                    state.runtime["vehicles"][affected]["status"] = "DRIVING"
                    _prev_spot_statuses.pop(new_spot, None)
                    state.log(f"🔄 {affected} הוסב לחניה {new_spot}", "entry")
                else:
                    state.runtime["vehicles"][affected]["status"] = "CHOOSING"
                    state.log(f"⚠️ {affected} לא מצא חניה פנויה", "info")
            else:
                state.log(f"🚧 {spot_id} נגנב!", "steal")
            break


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/layouts")
def get_layouts():
    files = sorted(LAYOUTS_DIR.glob("*.json"))
    return [{"path": str(f), "name": f.stem} for f in files]


@app.get("/api/scenarios")
def get_scenarios():
    return {k: {"description": v.get("description", k), **v} for k, v in SCENARIOS.items()}


@app.get("/api/layout")
def get_layout_data():
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    ol = state.offline
    return {
        "meta": ol["meta"],
        "nodes": ol["driving_nodes"],
        "edges": ol["driving_edges"],
        "entrances": ol["entrances"],
        "targets": ol["targets"],
        "target_options": ol.get("target_options", []),
        "subtype_groups": ol.get("subtype_groups", {}),
        "scoring_params": ol.get("scoring_params", {}),
        "spots_initial": [
            {"id": s["id"], "x": s["x"], "y": s["y"], "floor": s["floor"],
             "status": s["status"], "spot_type": s.get("spot_type", "standard")}
            for s in state.runtime["spots"]
        ],
        "floors": sorted({s["floor"] for s in state.runtime["spots"]}),
    }


class LoadRequest(BaseModel):
    layout_path: str
    scenario_name: str = "Demo"


@app.post("/api/load")
def load_layout_endpoint(req: LoadRequest):
    global _prev_spot_statuses
    with _state_lock:
        state.load(req.layout_path, req.scenario_name)
        sensor_adapter.runtime = state.runtime
        _prev_spot_statuses = {}   # force full delta on next frame
    return {"ok": True, "layout": req.layout_path, "scenario": req.scenario_name}


class SpawnRequest(BaseModel):
    vid: str
    target_type: str
    entrance_id: str = ""
    preferred_spot_id: Optional[str] = None
    target_instance_id: Optional[str] = None
    has_disability: bool = False


@app.post("/api/spawn")
def spawn_vehicle(req: SpawnRequest):
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    if req.vid in state.runtime["vehicles"]:
        raise HTTPException(400, "Vehicle ID already exists")
    ent = req.entrance_id or state.offline["entrances"][0]
    with _state_lock:
        ok = _spawn_vehicle(req.vid, req.target_type, ent,
                            req.preferred_spot_id, req.target_instance_id,
                            has_disability=req.has_disability)
    if not ok:
        raise HTTPException(409, "No free spot available")
    return {"ok": True}


# ── /api/floor_options — kept for simulation/operator tools ──────────────────

@app.get("/api/floor_options")
def get_floor_options(target_type: str, entrance_id: str = ""):
    """
    Compute the best available spot per floor for a given target_type.
    Used by the operator view and simulation tools.
    Returns floors in ascending order; each item:
      { floor, spot_id, walk_m, free_count, target_instance_id }
    """
    if not state._loaded:
        raise HTTPException(503, "Not loaded")

    ol      = state.offline
    ent_id  = entrance_id or ol["entrances"][0]
    spots   = state.runtime["spots"]
    targets = ol["targets"]
    nav_dists = ol["nav_dists"]
    d_nodes   = ol["driving_nodes"]

    def edist(ax, ay, bx, by):
        return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)

    requested_group = target_type
    is_generic_entrance = (target_type == "entrance")
    is_generic_elevator = (target_type == "elevator")

    if not is_generic_entrance and not is_generic_elevator:
        for prefix in ("elevator_group_", "elevator_inst_", "elevator_"):
            if requested_group.startswith(prefix):
                requested_group = requested_group[len(prefix):]
                break

    if target_type.startswith("elevator_inst_"):
        inst_id = target_type[len("elevator_inst_"):]
        t_obj = next((t for t in targets if t.get("id") == inst_id), None)
        if t_obj:
            requested_group = _eff_sub(t_obj)

    if is_generic_entrance:
        free_spots = [s for s in spots if s.get("status") == "FREE"]
        if not free_spots:
            return {"floors": []}
        ent_node = d_nodes.get(ent_id, {})
        ex, ey = float(ent_node.get("x", 0)), float(ent_node.get("y", 0))
        def _euclid(s):
            return math.sqrt((float(s.get("x", 0)) - ex)**2 + (float(s.get("y", 0)) - ey)**2)
        floors_asc = sorted({int(s.get("floor", 0)) for s in free_spots})
        for fl in floors_asc:
            fl_spots = sorted(
                [s for s in free_spots if int(s.get("floor", 0)) == fl],
                key=lambda s: (_euclid(s), float(s.get("drive_time", {}).get(ent_id, float("inf"))), s["id"])
            )
            if fl_spots:
                best_s = fl_spots[0]
                free_fl = [s for s in free_spots if int(s.get("floor", 0)) == fl]
                return {"floors": [{"floor": best_s["floor"], "spot_id": best_s["id"],
                    "walk_m": round(_euclid(best_s), 1), "free_count": len(free_fl),
                    "target_instance_id": None}]}
        return {"floors": []}

    if is_generic_elevator:
        all_elev = [t for t in targets if t.get("type") in ELEVATOR_TYPES]
        if not all_elev:
            return {"floors": []}
        nav_dist_from_ent = nav_dists.get(ent_id, {})
        def _drive_to_t(t):
            tx, ty, tf = float(t["x"]), float(t["y"]), int(t.get("floor", 0))
            best = float("inf")
            for nid, nd in d_nodes.items():
                if int(nd.get("floor", 0)) == tf:
                    d = nav_dist_from_ent.get(nid, float("inf"))
                    if d < float("inf"):
                        w = edist(float(nd["x"]), float(nd["y"]), tx, ty)
                        if d + w * 0.3 < best:
                            best = d + w * 0.3
            return best
        floor0_elev = [t for t in all_elev if int(t.get("floor", 0)) == 0]
        if not floor0_elev:
            return {"floors": []}
        requested_group = _eff_sub(min(floor0_elev, key=_drive_to_t))

    all_targets_for_group = [
        t for t in targets
        if t.get("type") in ELEVATOR_TYPES and _eff_sub(t) == requested_group
    ]
    if not all_targets_for_group:
        return {"floors": []}

    nav_dist_from_ent = nav_dists.get(ent_id, {})
    base_r = _resolve_floor_options_base_radius(all_targets_for_group, spots)
    floors = sorted({int(t.get("floor", 0)) for t in all_targets_for_group})

    results = []
    for fl in floors:
        free_on_floor = [s for s in spots if int(s.get("floor", 0)) == fl and s.get("status") == "FREE"]
        if not free_on_floor:
            continue
        floor_targets = [t for t in all_targets_for_group if int(t.get("floor", 0)) == fl]
        if not floor_targets:
            continue
        best_spot, best_walk, chosen_tid = _select_best_spot_on_floor(
            fl, free_on_floor, floor_targets, ent_id, nav_dist_from_ent, d_nodes, base_r,
        )
        if best_spot is not None:
            results.append({
                "floor": fl, "spot_id": best_spot["id"],
                "walk_m": round(best_walk, 1),
                "free_count": len(free_on_floor),
                "target_instance_id": chosen_tid,
            })
    results.sort(key=lambda r: r["floor"])
    return {"floors": results}


# ── /api/assign_direct — v8 driver endpoint ──────────────────────────────────

class AssignDirectRequest(BaseModel):
    """
    v8 driver assignment request.

    target_group    : elevator group name (e.g. 'mall_elevator', 'office_a', 'office_b')
    entrance_id     : entrance node (optional; defaults to layout default)
    has_disability  : True → disabled spots included in the eligible pool
    """
    target_group   : str
    entrance_id    : str = ""
    has_disability : bool = False
@app.post("/api/assign_direct")
def assign_direct(req: AssignDirectRequest):
    """
    Fully automatic spot assignment for real drivers (v8 flow).

    The algorithm:
      1. Spiral within INITIAL_ZONE_RADIUS on floor 0 (or committed floor).
      2. If zone exhausted → floor competition across all remaining floors,
         scored by drive_time + WALK_WEIGHT × walk_to_elevator.
      3. Winner's floor is committed (no return to earlier floors even on reassign).
      4. has_disability=True includes spots with spot_type=='disabled'.

    Returns:
      { ok, assigned_spot, floor, walk_m, spot_label, target_instance_id }
    """
    if not state._loaded:
        raise HTTPException(503, "Not loaded")

    USER_ID = "user_car_1"
    ent_id  = req.entrance_id or state.offline["entrances"][0]

    ensure_user_vehicle(state.runtime, USER_ID, ent_id, state.offline)

    with _state_lock:
        # Single clean path: assign_and_build_route handles selection,
        # reservation, and route building atomically.
        ok = assign_and_build_route(
            state.offline, state.runtime, USER_ID,
            req.target_group, state.weights,
            state.scenario["reserve_seconds"],
            has_disability=req.has_disability,
        )
        if not ok:
            raise HTTPException(409, "No free spot available")

        v = state.runtime["vehicles"][USER_ID]
        # Get assigned info for response
        spot_id = v.get("assigned_spot", "")
        spot_obj = next((s for s in state.runtime["spots"] if s["id"] == spot_id), None)
        assigned_floor = int(spot_obj["floor"]) if spot_obj else 0
        walk_m = float("inf")
        ti = v.get("assigned_target_info") or {}
        if ti.get("id"):
            tgt = next((t for t in state.offline["targets"] if t.get("id") == ti["id"]), None)
            if tgt and spot_obj:
                import math as _math
                walk_m = _math.sqrt((float(spot_obj["x"])-float(tgt["x"]))**2+(float(spot_obj["y"])-float(tgt["y"]))**2)

    v       = state.runtime["vehicles"][USER_ID]
    sid     = v.get("assigned_spot", "")
    floor_n = assigned_floor if assigned_floor is not None else 0

    # Build human-readable label: "קומה 0 · B06"
    spot_short = sid.replace(f"F{floor_n}-", "") if sid else "?"
    floor_label = f"קומה {floor_n}" if floor_n >= 0 else f"B{abs(floor_n)}"
    spot_label  = f"{floor_label} · {spot_short}"

    state.log(f"🚗 {USER_ID} → {sid} ({floor_label})", "entry")
    return {
        "ok":                True,
        "assigned_spot":     sid,
        "floor":             floor_n,
        "walk_m":            round(walk_m, 1) if walk_m != float("inf") else None,
        "spot_label":        spot_label,
        "target_instance_id": ti.get("id"),
    }


# ── /api/assign — retained for simulation / operator / autonomous ─────────────

class AssignRequest(BaseModel):
    target_type       : str
    entrance_id       : str = ""
    preferred_spot_id : Optional[str] = None
    target_instance_id: Optional[str] = None


@app.post("/api/assign")
def assign_user(req: AssignRequest):
    """Legacy/simulation assignment. Uses two-step: caller provides preferred_spot_id
    from /api/floor_options. Still used by operator tools and simulation vehicles."""
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    USER_ID    = "user_car_1"
    entrance_id = req.entrance_id or state.layout["entrances"][0]
    ensure_user_vehicle(state.runtime, USER_ID, entrance_id, state.offline)

    effective = req.target_type
    if req.target_instance_id:
        inst_key = f"elevator_inst_{req.target_instance_id}"
        if inst_key in state.offline.get("rankings", {}):
            effective = inst_key

    with _state_lock:
        if req.preferred_spot_id:
            locked = _reserve_preferred_spot(
                req.preferred_spot_id, USER_ID, state.scenario["reserve_seconds"]
            )
            ok = assign_and_build_route(
                state.offline, state.runtime, USER_ID, effective,
                state.weights, state.scenario["reserve_seconds"],
                forced_spot_id=req.preferred_spot_id if locked else None,
            )
        else:
            ok = assign_and_build_route(
                state.offline, state.runtime, USER_ID, effective,
                state.weights, state.scenario["reserve_seconds"],
            )

    if not ok:
        raise HTTPException(409, "No free spot available")
    v = state.runtime["vehicles"][USER_ID]
    return {"ok": True, "assigned_spot": v.get("assigned_spot")}


def _reserve_preferred_spot(spot_id: str, vid: str, reserve_secs: float) -> bool:
    s = find_spot(state.runtime["spots"], spot_id)
    if not s or s.get("status") != "FREE":
        return False
    s["status"]         = "RESERVED"
    s["reserved_for"]   = vid
    s["reserved_until"] = now_ts() + reserve_secs
    return True


# ── /api/target_groups — for the v8 frontend ──────────────────────────────────

@app.get("/api/target_groups")
def get_target_groups():
    """
    Return the available destination groups for the driver UI.

    Response shape:
      {
        "mall":    [{ id, label, icon, group }],   # mall_elevator, mall_escalator
        "offices": [{ id, label, icon, group }],   # office_a, office_b, ...
      }

    If only one office group exists, `offices` has one item; the UI skips the
    sub-picker and goes directly to the disability question.
    """
    if not state._loaded:
        raise HTTPException(503, "Not loaded")

    targets  = state.offline.get("targets", [])
    seen     = set()
    mall     = []
    offices  = []

    def _icon(g: str) -> str:
        if "mall_elevator" in g: return "🛗"
        if "mall_escalator" in g: return "🪜"
        return "🏢"

    def _label(t: Dict) -> str:
        return t.get("label") or t.get("target_group") or t.get("subtype") or t.get("id", "")

    for t in targets:
        if t.get("type") not in ELEVATOR_TYPES:
            continue
        # Use F0 targets to define the groups (one entry per group)
        if int(t.get("floor", 0)) != 0:
            continue
        grp = _eff_sub(t)
        if grp in seen:
            continue
        seen.add(grp)
        item = {"id": grp, "label": _label(t), "icon": _icon(grp), "group": grp}
        if "office" in grp:
            offices.append(item)
        else:
            mall.append(item)

    return {"mall": mall, "offices": offices}


# ── Steal / Free / Occupy manual ─────────────────────────────────────────────

class StealRequest(BaseModel):
    spot_id: str


@app.post("/api/steal")
def steal_spot(req: StealRequest):
    _force_occupy(req.spot_id, f"T_{random.randint(100, 999)}")
    return {"ok": True}


class FreeRequest(BaseModel):
    spot_id: Optional[str] = None


@app.post("/api/free")
def free_spot(req: FreeRequest):
    with _state_lock:
        if req.spot_id:
            s = find_spot(state.runtime["spots"], req.spot_id)
            if s:
                s["status"] = "FREE"
                s["reserved_for"] = None
                state.log(f"✅ {req.spot_id} שוחרר", "exit")
        else:
            _free_random()
    return {"ok": True}


class OccupyManualRequest(BaseModel):
    spot_id: str


@app.post("/api/occupy_manual")
def occupy_manual(req: OccupyManualRequest):
    global _prev_spot_statuses
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    with _state_lock:
        s = find_spot(state.runtime["spots"], req.spot_id)
        if not s:
            raise HTTPException(404, f"Spot {req.spot_id} not found")
        s["status"]         = "OCCUPIED"
        s["reserved_for"]   = "MANUAL_PARK"
        s["reserved_until"] = None
        _prev_spot_statuses.pop(req.spot_id, None)
        state.log(f"🅿️ {req.spot_id} סומן כתפוס (דיווח ידני)", "info")
    return {"ok": True}


class RemoveRequest(BaseModel):
    vid: str


@app.post("/api/remove")
def remove_vehicle(req: RemoveRequest):
    with _state_lock:
        v = state.runtime["vehicles"].pop(req.vid, None)
        if v and v.get("assigned_spot"):
            s = find_spot(state.runtime["spots"], v["assigned_spot"])
            if s:
                s["status"]       = "FREE"
                s["reserved_for"] = None
    state.log(f"❌ {req.vid} הוסר", "remove")
    return {"ok": True}


class ResetRequest(BaseModel):
    layout_path:   Optional[str] = None
    scenario_name: Optional[str] = None


@app.post("/api/reset")
def reset_simulation(req: ResetRequest):
    global _prev_spot_statuses
    lp  = req.layout_path   or state.layout_path
    sc  = req.scenario_name or state.scenario_name
    with _state_lock:
        state.load(lp, sc)
        sensor_adapter.runtime = state.runtime
        _prev_spot_statuses    = {}
    return {"ok": True}


@app.get("/api/server_token")
def get_server_token():
    return {"token": SERVER_START_TOKEN}


@app.post("/api/clean_session")
def clean_session():
    global _prev_spot_statuses
    if not state._loaded:
        return {"ok": True, "cleared": 0}
    count = 0
    for vid, v in list(state.runtime["vehicles"].items()):
        spot_id = v.get("assigned_spot")
        if spot_id:
            s = find_spot(state.runtime["spots"], spot_id)
            if s and s["status"] == "RESERVED":
                s["status"]       = "FREE"
                s["reserved_for"] = None
        del state.runtime["vehicles"][vid]
        count += 1
    _prev_spot_statuses = {}
    state.log(f"🔄 סשן חדש — {count} רכבים הוסרו", "info")
    return {"ok": True, "cleared": count}


class SpeedRequest(BaseModel):
    speed: float


@app.post("/api/speed")
def set_speed(req: SpeedRequest):
    state.speed = max(0.1, min(10.0, req.speed))
    return {"ok": True, "speed": state.speed}


# ── Pedestrian navigation ─────────────────────────────────────────────────────

@app.get("/api/ped_entry_points")
def get_ped_entry_points():
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    ped = state.offline.get("pedestrian")
    if not ped:
        raise HTTPException(503, "Pedestrian graph not available")
    return {"entry_points": ped["entry_points"]}


class WalkRouteRequest(BaseModel):
    from_id   : str
    spot_id   : str
    session_id: Optional[str] = None


@app.post("/api/walk_route")
def get_walk_route(req: WalkRouteRequest):
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    from core.pedestrian import find_walk_route, get_walk_instructions
    ped = state.offline.get("pedestrian")
    if not ped:
        raise HTTPException(503, "Pedestrian graph not available")
    result = find_walk_route(ped["ped_nodes"], ped["ped_adj"], req.from_id, req.spot_id)
    if not result:
        raise HTTPException(404, f"No pedestrian route found from {req.from_id} to {req.spot_id}")
    instructions = get_walk_instructions(result["waypoints"])
    if req.session_id and hasattr(ped_position_adapter, "register_session"):
        ped_position_adapter.register_session(req.session_id, result["waypoints"])
    return {
        "waypoints":    result["waypoints"],
        "total_meters": result["total_meters"],
        "walk_minutes": result["walk_minutes"],
        "instructions": instructions,
        "session_id":   req.session_id,
    }


@app.get("/api/state")
def get_full_state():
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    spots = [
        {"id": s["id"], "x": s["x"], "y": s["y"], "floor": s["floor"],
         "status": s["status"], "spot_type": s.get("spot_type", "standard")}
        for s in state.runtime["spots"]
    ]
    return {
        "spots": spots,
        "vehicles": _build_frame()["vehicles"],
        "stats":    _build_frame()["stats"],
        "scenario_name": state.scenario_name,
        "speed": state.speed,
        "event_log": state.event_log,
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    await manager.connect(ws)
    if state._loaded:
        full = {
            "type": "full",
            "spots": [
                {"id": s["id"], "x": s["x"], "y": s["y"], "floor": s["floor"],
                 "status": s["status"], "spot_type": s.get("spot_type", "standard")}
                for s in state.runtime["spots"]
            ],
            **_build_frame(),
        }
        await ws.send_text(json.dumps(full, default=_json_default))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── Serve frontend ────────────────────────────────────────────────────────────

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"error": "Frontend not built. Run: cd frontend && npm run build"}
else:
    @app.get("/")
    def root():
        return {"message": "Backend running. Build frontend: cd frontend && npm run build"}


# ── Real-hardware endpoints ───────────────────────────────────────────────────

class SpotEventRequest(BaseModel):
    spot_id   : str
    occupied  : bool
    sensor_id : Optional[str] = None
    confidence: float = 1.0
    timestamp : Optional[float] = None


@app.post("/api/spot_event")
async def spot_event(req: SpotEventRequest):
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    if req.confidence < 0.7:
        return {"ok": True, "action": "dropped_low_confidence"}
    from core.adapters import WebhookSensorAdapter
    if isinstance(sensor_adapter, WebhookSensorAdapter):
        sensor_adapter.receive_event(req.spot_id, req.occupied)
        await sensor_adapter.poll_once()
    else:
        from core.adapters import external_to_internal
        internal_id = external_to_internal(req.spot_id)
        s = find_spot(state.runtime["spots"], internal_id)
        if s:
            new_status = "OCCUPIED" if req.occupied else "FREE"
            if s["status"] != new_status:
                _on_sensor_change(internal_id, new_status)
    state.log(
        f"📡 {'תפוס' if req.occupied else 'פנוי'}: {req.spot_id}"
        + (f" [{req.sensor_id}]" if req.sensor_id else ""),
        "sensor"
    )
    return {"ok": True}


def _on_sensor_change(spot_id: str, new_status: str) -> None:
    global _prev_spot_statuses
    s = find_spot(state.runtime["spots"], spot_id)
    if not s:
        return
    s["status"] = new_status
    if new_status == "FREE":
        s["reserved_for"]   = None
        s["reserved_until"] = None
    _prev_spot_statuses.pop(spot_id, None)
    if new_status == "OCCUPIED":
        affected = s.get("reserved_for")
        if affected and affected in state.runtime["vehicles"]:
            _force_occupy(spot_id, "SENSOR_DETECTED")
        else:
            state.log(f"📡 {spot_id} נתפס (חיישן)", "sensor")
    else:
        state.log(f"📡 {spot_id} התפנה (חיישן)", "sensor")


sensor_adapter.set_on_change(_on_sensor_change)


class BleScanRequest(BaseModel):
    session_id: str
    beacons   : List[Dict[str, Any]]


@app.post("/api/ble_scan")
async def ble_scan(req: BleScanRequest):
    from core.adapters import BlePositionAdapter
    if isinstance(ped_position_adapter, BlePositionAdapter):
        sample = ped_position_adapter.receive_rssi_scan(req.session_id, req.beacons)
        if sample:
            return {"ok": True, "position": {
                "x": sample.x, "y": sample.y, "floor": sample.floor,
                "accuracy_m": sample.accuracy_m, "source": sample.source,
            }}
    return {"ok": True, "position": None}


@app.post("/api/start_navigation")
async def start_navigation(req: dict):
    session_id = req.get("session_id")
    if not session_id:
        raise HTTPException(400, "session_id required")
    if hasattr(ped_position_adapter, "resume_session"):
        ped_position_adapter.resume_session(session_id)
    return {"ok": True, "session_id": session_id}


@app.get("/api/position/{session_id}")
async def get_position(session_id: str):
    sample = await ped_position_adapter.get_position(session_id)
    if sample:
        return {"ok": True, "position": {
            "x": sample.x, "y": sample.y, "floor": sample.floor,
            "heading": sample.heading, "accuracy_m": sample.accuracy_m,
            "timestamp": sample.timestamp, "source": sample.source,
            "distFromStart": getattr(sample, "dist_from_start", None),
        }}
    return {"ok": True, "position": None}


class VehiclePositionRequest(BaseModel):
    vid    : str
    x      : float
    y      : float
    floor  : int
    heading: Optional[float] = None
    source : str = "external"


@app.post("/api/vehicle_position")
def update_vehicle_position(req: VehiclePositionRequest):
    if not state._loaded:
        raise HTTPException(503, "Not loaded")
    v = state.runtime["vehicles"].get(req.vid)
    if not v:
        raise HTTPException(404, f"Vehicle {req.vid} not found")
    from core.adapters import snap_route_index
    v["x"] = req.x; v["y"] = req.y; v["floor"] = req.floor
    if req.heading is not None:
        v["_heading_override"] = req.heading
    v["route_i"] = snap_route_index(
        v.get("route_xy", []), req.x, req.y, req.floor, int(v.get("route_i", 0))
    )
    return {"ok": True, "route_i": v["route_i"]}


class PauseRequest(BaseModel):
    vid: str


@app.post("/api/pause_vehicle")
def pause_vehicle(req: PauseRequest):
    v = state.runtime["vehicles"].get(req.vid)
    if not v:
        return {"ok": False, "reason": "vehicle not found"}
    if v.get("status") == "DRIVING":
        v["_paused_status"] = "DRIVING"
        v["status"] = "PAUSED"
    return {"ok": True}


@app.post("/api/resume_vehicle")
def resume_vehicle(req: PauseRequest):
    v = state.runtime["vehicles"].get(req.vid)
    if not v:
        return {"ok": False, "reason": "vehicle not found"}
    if v.get("status") == "PAUSED":
        v["status"] = v.pop("_paused_status", "DRIVING")
    return {"ok": True}
