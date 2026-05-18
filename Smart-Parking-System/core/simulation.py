"""
simulation.py — Vehicle Routing, Assignment, and State Logic
=============================================================

This module is responsible for all routing decisions and state transitions.
It deliberately does NOT own vehicle movement (x/y advancement) — that is
delegated to a VehiclePositionAdapter (see core/adapters/position_adapter.py).

Responsibilities of THIS module
--------------------------------
  • Assigning spots to newly-arrived vehicles (assign_and_build_route)
  • Building the waypoint sequence a vehicle follows (route_xy)
  • Detecting stolen reservations and rerouting affected vehicles
  • Marking spots OCCUPIED when route_i reaches end of route
  • Auto-removing parked simulation vehicles after parked_until expires

NOT in this module (delegated to adapters)
------------------------------------------
  • Advancing x/y/floor of vehicles each tick  → VehiclePositionAdapter
  • Reading real spot occupancy from sensors   → SensorAdapter
  • Locating a pedestrian in the garage        → PedestrianPositionAdapter

The separation means: when you connect real GPS/UWB/RFID infrastructure,
you replace the adapter, not this file.

────────────────────────────────────────────────────────────────────────
Route building  (assign_and_build_route / reassign_from_current)
────────────────────────────────────────────────────────────────────────

A route is a list of (x, y, floor) world-coordinate waypoints stored in
vehicle["route_xy"].  The position adapter advances the vehicle along it.

Every route ends with a clean right-angle approach to the spot:

    ... → aisle_node → (spot_x, road_y) → (spot_x, spot_y)
                              ↑
                         access_pt — the point on the driving aisle
                         directly in front of the spot

_finalize_spot_approach() guarantees this by:
  1. Removing U-turns caused by rerouting (_remove_same_aisle_reversals).
  2. Trimming trailing aisle nodes that overshoot the spot's X position.
  3. Inserting access_pt at (spot_x, road_y).
  4. Appending the spot centre.

Before finalizing, _remove_same_aisle_reversals() removes any node on the
same aisle that would cause a U-turn — important for rerouted vehicles
whose forward_hint may be past the new spot.

────────────────────────────────────────────────────────────────────────
Rerouting  (reassign_from_current)
────────────────────────────────────────────────────────────────────────

When a vehicle's reserved spot is stolen (detected in tick() or triggered
by an operator action):

  1. Save forward_hint — the next driving node the vehicle is already
     heading toward — BEFORE clearing the route.  (Clearing first would
     cause _find_forward_node to fall back to the nearest node, which
     may be behind the vehicle.)

  2. Clear route_xy and route_i, set status = RECALCULATING.

  3. Call reassign_from_current(), which:

     STEP 1 — Zone search on intended_floor
       intended_floor = current physical floor (zone restarts fresh on each
       new floor the vehicle reaches).  Exception: if vehicle is still below
       the original user-chosen floor and hasn't reached it yet,
       intended_floor = original target floor (finish the trip first).

       Zone radius is purely geometry-based (no presented_walk_m).
       Base zone = TARGET_ZONE_RADIUS (from scoring_params, same as initial
       assignment zone). Expands by floor_change_expansion^n per floor change.

       ── Single instance on intended floor ──
         zone = TARGET_ZONE_RADIUS × floor_change_expansion^n
         → Take closest free spot if walk ≤ zone.
         → Fall through to Step 2 if no spot within zone.

       ── Multiple instances on intended floor (spiral) ──
         MULTI_ZONE = TARGET_ZONE_RADIUS × floor_change_expansion^n
         Spiral from LOCAL_TARGET_RADIUS up to MULTI_ZONE.
         Always check inst-1 first; switch only if another instance saves
         WALK_TOLERANCE metres of walk and is within MULTI_ZONE.
         → Fall through to Step 2 only if MULTI_ZONE fully exhausted.

     STEP 2 — Global Score (zone exhausted on intended_floor = E)
       Reached when Step 1 zone is exhausted.  Mark E as visited (permanent).
       Candidate set scored using: score = drive_time + WALK_WEIGHT × walk
         E-floor: ALL free spots. Always present in every pass — Score can
           legitimately keep filling E when an E-spot beats every other floor.
         Other floors: single best spot each (walk-closest to nearest transport
           target, drive tiebreak). Guarantees concentric fill on each new floor.
       Three passes gate OTHER-floor candidates (anchored on E, not current_floor):
         Pass 1: E + unvisited floors >= E   (no regression, no revisit)
         Pass 2: E + all floors >= E          (visited ok, no regression below E)
         Pass 3: E + all floors              (last resort — truly empty at/above E)
       If winner on N != E: pending_floor=N. Vehicle committed to N; E locked.
       If winner on E: pending_floor cleared; vehicle naturally fills E.

     STEP 3 — Legacy fallback (choose_best_spot with offline rankings)
       Only reached if the garage is essentially full.

  4. Builds a new route:
       [current_pos] + [forward_hint if ahead] + [Dijkstra path to new spot]
  5. Calls _finalize_spot_approach() to clean up the ending.

  The result is a route that continues in the vehicle's current direction
  when the new spot is ahead, or makes the shortest realistic U-turn when
  the new spot is behind.

────────────────────────────────────────────────────────────────────────
Zone geometry for reassignment
────────────────────────────────────────────────────────────────────────

Step 1 uses TARGET_ZONE_RADIUS from scoring_params as its base zone.
This is the same geometry-derived radius used in the initial assignment
Phase 1, computed from inter-instance distance (multi) or walk-distance
percentile (single) in offline.py.

The zone expands by floor_change_expansion^n per completed floor change,
making the vehicle try progressively harder to stay on each floor it reaches.
n = len(visited_floors) = number of floors exhausted so far.

There is no dependency on a walk distance shown to the driver at entry.
Each vehicle's zone is determined entirely by the garage geometry and how
many floor changes it has already undergone.

────────────────────────────────────────────────────────────────────────
Vehicle state machine
────────────────────────────────────────────────────────────────────────

  CHOOSING  →  DRIVING   (on assign_and_build_route success)
  DRIVING   →  PARKED    (when route_i reaches end of route)
  DRIVING   →  DRIVING   (on reroute — same status, new route)
  PARKED    →  LEFT      (after parked_until expires, auto-leave)

────────────────────────────────────────────────────────────────────────
Movement math  (tick())
────────────────────────────────────────────────────────────────────────

Each tick, the vehicle moves toward the next waypoint:
    step = min(dist_to_next, speed_mps × dt)
    new_pos = current + (direction_unit × step)
    if step ≥ dist_to_next − 0.1:  advance route_i

The 0.1 tolerance prevents floating-point drift from stalling a vehicle
a hair's-breadth from a waypoint forever.
"""

import math
import random
import time
from typing import Any, Dict, List, Optional

from core.dijkstra import reconstruct_path, dijkstra_with_parent
from core.graphs import Graph, Node
from core.config import CFG

__all__ = [
    'init_runtime_state', 'prefill_spots', 'ensure_user_vehicle',
    'assign_and_build_route', 'reassign_from_current', 'tick', 'find_spot', 'now_ts',
    '_find_forward_node',
]

# Keep consistent with offline.py
DRIVING_SPEED_MPS        = CFG["offline"]["driving_speed_mps"]
_WALK_WEIGHT             = float(CFG["runtime"]["walk_weight"])
_FLOOR_CHANGE_EXPANSION  = float(CFG["runtime"]["floor_change_expansion"])
_SPIRAL_EXPANSION        = float(CFG["offline"]["spiral_expansion_factor"])


def now_ts() -> float:
    return time.time()


def find_spot(spots: List[Dict[str, Any]], spot_id: str) -> Optional[Dict[str, Any]]:
    for s in spots:
        if s["id"] == spot_id:
            return s
    return None


def init_runtime_state(offline: Dict[str, Any]) -> Dict[str, Any]:
    # copy spot dicts so runtime can mutate status without touching offline cache
    spots = [dict(s) for s in offline["spots"]]
    return {"spots": spots, "vehicles": {}}


def prefill_spots(spots: List[Dict[str, Any]], ratio: float) -> None:
    free = [s for s in spots if s["status"] == "FREE"]
    k = min(len(free), int(len(spots) * ratio))
    if k > 0:
        for s in random.sample(free, k):
            s["status"] = "OCCUPIED"


def ensure_user_vehicle(runtime: Dict[str, Any], vehicle_id: str, entrance_id: str, offline: Dict[str, Any]) -> Dict[str, Any]:
    if vehicle_id in runtime["vehicles"]:
        return runtime["vehicles"][vehicle_id]

    dn = offline["driving_nodes"]
    ent = dn.get(entrance_id, {})

    runtime["vehicles"][vehicle_id] = {
        "id": vehicle_id,
        "kind": "USER",
        "entrance_id": entrance_id,
        "target_type": None,
        "status": "CHOOSING",
        "assigned_spot": None,
        "assigned_target_id": None,
        "assigned_target_info": None,
        "visited_floors": [],
        "route_xy": [],
        "route_i": 0,
        "x": float(ent.get("x", 0)),
        "y": float(ent.get("y", 0)),
        "floor": int(ent.get("floor", 0)),
        "speed_mps": CFG["runtime"]["default_vehicle_speed"],
    }
    return runtime["vehicles"][vehicle_id]


def _find_nearest_node(dn: Dict[str, Any], x: float, y: float, floor: int) -> Optional[str]:
    best, best_d = None, float("inf")
    for nid, n in dn.items():
        if int(n["floor"]) == int(floor):
            d = (float(n["x"]) - x) ** 2 + (float(n["y"]) - y) ** 2
            if d < best_d:
                best_d, best = d, nid
    return best


def _build_graph(offline: Dict[str, Any]) -> Graph:
    dn = offline["driving_nodes"]
    nodes = {nid: Node(nid, d["floor"], d["x"], d["y"], d.get("type", "intersection"))
             for nid, d in dn.items()}
    dg = Graph(nodes)
    for e in offline["driving_edges"]:
        speed = DRIVING_SPEED_MPS.get(e.get("type", "main"), 2.0)
        w = float(e["length_m"]) / speed
        dg.add_edge(e["from"], e["to"], w, e.get("type", "main"), True)
    return dg


def _remove_same_aisle_reversals(xy: list) -> list:
    """
    Remove any interior node that causes a U-turn on the same horizontal aisle.
    e.g. ...→(170,75)→(200,75)→(150,75)→... removes (200,75) because the
    vehicle would drive east to 200, then reverse west — pointless detour.
    Only removes nodes on the same Y (same aisle); corner turns are kept.
    Iterates until stable (handles chains of reversal nodes).
    """
    if len(xy) < 3:
        return xy
    changed = True
    while changed:
        changed = False
        result = [xy[0]]
        i = 1
        while i < len(xy) - 1:
            prev = result[-1]
            curr = xy[i]
            nxt  = xy[i + 1]
            # Only remove if curr is on same horizontal aisle as both prev and next
            same_y_prev = abs(curr[1] - prev[1]) < 1.0 and curr[2] == prev[2]
            if same_y_prev:
                dx_in  = curr[0] - prev[0]
                dx_out = nxt[0]  - curr[0]
                if dx_in * dx_out < -1:   # direction reverses → skip curr
                    changed = True
                    i += 1
                    continue
            result.append(curr)
            i += 1
        result.append(xy[-1])
        xy = result
    return xy


def _finalize_spot_approach(xy: list, spot: dict, offline: Optional[Dict] = None) -> list:
    """
    Append a clean right-angle approach to a parking spot onto the route xy.

    Algorithm:
    0. Remove any same-aisle U-turns accumulated during rerouting.
    1. Determine road_y — the Y coordinate of the driving aisle in front of the spot.
       Uses spot["road_y"] if set. Otherwise derives it from the last route point
       (the access node) whose Y differs from the spot Y. This handles layouts where
       road_y is not explicitly stored: the approach becomes
           ... → aisle_node → (spot_x, access_node_y) → (spot_x, spot_y)
       which gives a natural right-angle turn from aisle into the spot bay.
    2. Trim any trailing aisle node that overshoots the spot (X-axis).
    3. Insert a virtual access-point waypoint at (spot_x, road_y).
    4. Append the spot centre.
    """
    road_y = spot.get("road_y")
    sx = float(spot["x"])
    sy = float(spot["y"])
    sf = int(spot["floor"])

    # ── step 0: clean any reroute-induced U-turns ────────────────────────────
    xy = _remove_same_aisle_reversals(xy)

    # ── step 1: derive road_y from the last aisle node when not explicitly set ─
    # The last route point (access node) is on the driving aisle.
    # Its Y gives us the aisle Y, which is road_y for this spot.
    if road_y is None and len(xy) >= 1:
        last_pt = xy[-1]
        last_y  = float(last_pt[1])
        # The access node should be on the aisle (different Y from spot centre)
        if abs(last_y - sy) > 0.5:
            road_y = last_y

    if road_y is not None and len(xy) >= 1:
        road_y_f = float(road_y)

        # ── step 2: trim trailing overshoot nodes on the spot's aisle ─────────
        while len(xy) >= 2:
            last = xy[-1]
            prev = xy[-2]
            on_aisle = abs(float(last[1]) - road_y_f) < 1.5 and int(last[2]) == sf
            if not on_aisle:
                break
            travel_dx  = float(last[0]) - float(prev[0])
            to_spot_dx = sx - float(last[0])
            if travel_dx * to_spot_dx < 0:   # last node overshoots spot in X
                xy.pop()
            else:
                break

        # ── step 3: insert access point at (spot_x, road_y) ──────────────────
        # This is the point on the aisle directly in front of the spot.
        # The vehicle turns here from "driving along aisle" to "entering bay".
        access_pt = (sx, road_y_f, sf)
        if not xy or (abs(float(xy[-1][0]) - sx) > 0.1 or abs(float(xy[-1][1]) - road_y_f) > 0.1):
            xy.append(access_pt)

    # ── step 4: append spot centre ────────────────────────────────────────────
    spot_pt = (sx, sy, sf)
    if not xy or (abs(float(xy[-1][0]) - sx) > 0.1 or abs(float(xy[-1][1]) - sy) > 0.1):
        xy.append(spot_pt)

    return xy



def _euclid_xy(ax, ay, bx, by):
    dx, dy = ax - bx, ay - by
    return (dx * dx + dy * dy) ** 0.5


def _pick_entrance_spot(spots, entrance_id, driving_nodes):
    """
    Initial assignment for "הכי קרוב אליי":
    Closest FREE spot to the entrance by Euclidean distance, floor 0 first.
    If floor 0 is empty, try floor 1, etc.
    Tiebreaker: drive_time from entrance, then spot id.
    """
    ent_node = driving_nodes.get(entrance_id, {})
    ex, ey = float(ent_node.get("x", 0)), float(ent_node.get("y", 0))

    free = [s for s in spots if s and s.get("status") == "FREE"]
    if not free:
        return None

    for fl in sorted({int(s.get("floor", 0)) for s in free}):
        candidates = [s for s in free if int(s.get("floor", 0)) == fl]
        if not candidates:
            continue
        candidates.sort(key=lambda s: (
            _euclid_xy(float(s.get("x", 0)), float(s.get("y", 0)), ex, ey),
            float(s.get("drive_time", {}).get(entrance_id, float("inf"))),
            s["id"],
        ))
        return candidates[0]
    return None


def _pick_reassign_spot(spots, vehicle, driving_nodes):
    """
    Reassignment for "הכי קרוב אליי":
    Closest FREE spot to the vehicle's CURRENT position by Euclidean distance,
    on the vehicle's current floor.
    If current floor has no free spots, use the ramp node of the current floor
    as the reference point for the next floor up, and so on.
    Tiebreaker: drive_time from entrance, then spot id.
    """
    vx, vy = float(vehicle.get("x", 0)), float(vehicle.get("y", 0))
    current_floor = int(vehicle.get("floor", 0))
    entrance_id = vehicle.get("entrance_id", "")

    free = [s for s in spots if s and s.get("status") == "FREE"]
    if not free:
        return None

    all_floors = sorted({int(s.get("floor", 0)) for s in free})
    # Start from current floor, then higher floors in order
    floors_ordered = [f for f in all_floors if f >= current_floor]
    if not floors_ordered:
        floors_ordered = all_floors  # fallback: any floor

    ref_x, ref_y = vx, vy  # reference point starts at vehicle position

    for fl in floors_ordered:
        candidates = [s for s in free if int(s.get("floor", 0)) == fl]
        if not candidates:
            # No spots on this floor — update ref point to the ramp of this floor
            ramp_key = f"RAMP_F{fl}"
            ramp_node = driving_nodes.get(ramp_key, {})
            if ramp_node:
                ref_x = float(ramp_node.get("x", ref_x))
                ref_y = float(ramp_node.get("y", ref_y))
            continue
        candidates.sort(key=lambda s: (
            _euclid_xy(float(s.get("x", 0)), float(s.get("y", 0)), ref_x, ref_y),
            float(s.get("drive_time", {}).get(entrance_id, float("inf"))),
            s["id"],
        ))
        return candidates[0]
    return None


def assign_and_build_route(offline: Dict[str, Any], runtime: Dict[str, Any], vid: str,
                           target_type: str, weights: Dict[str, Any], reserve_sec: int,
                           forced_spot_id: Optional[str] = None,
                           has_disability: bool = False) -> bool:
    """Assign spot and build route from ENTRANCE to SPOT.

    Assignment priority:
      1. forced_spot_id — spot was pre-reserved by server (real driver confirmed choice).
      2. floor-options algorithm — same spiral/closest logic used for the UI preview,
         so simulation vehicles receive identical assignments to real drivers.
      3. choose_best_spot — legacy ranking fallback, only if the above finds nothing
         (garage essentially full or target type not handled by floor-options logic).

    If forced_spot_id is given, use that specific spot (must already be RESERVED for vid).
    """
    from core.floor_selection import select_spot_auto as _select_spot_auto
    from core.scoring import choose_best_spot

    v = runtime["vehicles"][vid]
    v["target_type"] = target_type
    entrance_id = v["entrance_id"]

    ELEVATOR_TYPES = frozenset({"elevator", "escalator"})

    def _eff_sub(t):
        return t.get("target_group") or t.get("subtype") or "default"

    if forced_spot_id:
        # ── Path 1: spot already chosen and locked by the user ────────────────
        best = next(
            (s for s in runtime["spots"] if s["id"] == forced_spot_id),
            None,
        )
        if not best:
            return False

        # Attach the nearest elevator target as _chosen_target so presented_walk_m
        # is recorded correctly on the vehicle.
        spot_floor = int(best.get("floor", 0))

        if target_type.startswith("elevator_inst_"):
            inst_id = target_type[len("elevator_inst_"):]
            chosen_target = next(
                (t for t in offline["targets"] if t.get("id") == inst_id), None
            )
        else:
            sub = (target_type[len("elevator_"):]
                   if target_type.startswith("elevator_") else "")
            floor_ts = [
                t for t in offline["targets"]
                if t.get("type") in ELEVATOR_TYPES
                and int(t.get("floor", 0)) == spot_floor
                and (not sub or _eff_sub(t) == sub)
            ]
            chosen_target = min(
                floor_ts,
                key=lambda t: math.sqrt(
                    (float(best["x"]) - float(t["x"])) ** 2 +
                    (float(best["y"]) - float(t["y"])) ** 2
                ),
                default=None,
            )

        if chosen_target:
            walk_to_target = math.sqrt(
                (float(best["x"]) - float(chosen_target["x"])) ** 2 +
                (float(best["y"]) - float(chosen_target["y"])) ** 2
            )
            best["_chosen_target"] = {
                "id":    chosen_target["id"],
                "type":  chosen_target["type"],
                "label": chosen_target.get("label", ""),
            }

    else:
        # ── Path 2: autonomous assignment — use floor-options algorithm ───────
        # This is the SAME algorithm as /api/floor_options so simulation vehicles
        # receive identical assignments to real drivers, making the operator view
        # a faithful mirror of actual system behaviour.
        best = None
        chosen_tid = None

        # ── Entrance mode: closest FREE spot by Euclidean distance from entrance ──
        if target_type == "entrance":
            best = _pick_entrance_spot(
                runtime["spots"], entrance_id, offline["driving_nodes"]
            )
            if best is not None:
                best["_chosen_target"] = {
                    "id": entrance_id, "type": "entrance",
                    "label": "כניסה", "cost": 0.0,
                }

        elif (target_type.startswith("elevator") or
              any(_eff_sub(t) == target_type
                  for t in offline["targets"]
                  if t.get("type") in ELEVATOR_TYPES)):
            best, _, chosen_tid, _assigned_floor = _select_spot_auto(
                target_type, entrance_id, offline, runtime,
                has_disability=has_disability,
            )
            # Note: committed_floor and pending_floor are NOT set here.
            # The original design keeps initial assignment simple.
            # reassign_from_current manages floor tracking independently.
            if best and chosen_tid:
                # Compute walk and attach _chosen_target for presented_walk_m
                chosen_target_obj = next(
                    (t for t in offline["targets"] if t.get("id") == chosen_tid), None
                )
                if chosen_target_obj:
                    walk_m = math.sqrt(
                        (float(best["x"]) - float(chosen_target_obj["x"])) ** 2 +
                        (float(best["y"]) - float(chosen_target_obj["y"])) ** 2
                    )
                    best["_chosen_target"] = {
                        "id":    chosen_target_obj["id"],
                        "type":  chosen_target_obj.get("type", "elevator"),
                        "label": chosen_target_obj.get("label", ""),
                    }

        # ── Path 3: legacy fallback (garage nearly full or non-elevator type) ─
        if not best:
            best = choose_best_spot(
                runtime["spots"],
                entrance_id,
                target_type,
                offline["targets"],
                runtime["vehicles"],
                weights,
                offline_rankings=offline.get("rankings"),
                scoring_params=offline.get("scoring_params"),
            )

    if not best:
        return False

    v["assigned_spot"] = best["id"]
    if best.get("status") != "RESERVED":  # don't double-reserve
        best["status"] = "RESERVED"
        best["reserved_for"] = vid
        best["reserved_until"] = now_ts() + reserve_sec

    target = best.pop("_chosen_target", None)
    if target:
        v["assigned_target_id"]   = target.get("id")
        v["assigned_target_info"] = target

    dn = offline["driving_nodes"]
    access = best.get("best_access", {}).get(entrance_id) or best["access"][0]["node"]

    parents = offline.get("nav_parents", {}).get(entrance_id)
    if not parents:
        dg = _build_graph(offline)
        _, parents = dijkstra_with_parent(dg, entrance_id)

    path = reconstruct_path(parents, entrance_id, access)

    xy = []
    for n in path:
        if n in dn:
            xy.append((float(dn[n]["x"]), float(dn[n]["y"]), int(dn[n]["floor"])))

    xy = _finalize_spot_approach(xy, best)

    v["route_xy"] = xy
    v["route_i"] = 0
    v["status"] = "DRIVING"

    if xy:
        v["x"], v["y"], v["floor"] = xy[0]

    return True


def _find_forward_node(dn: Dict[str, Any], v: Dict[str, Any]) -> Optional[str]:
    """
    Find the best node to start rerouting from.
    Strategy: use the NEXT waypoint in the current route (the node the vehicle
    is already heading toward). This avoids backtracking.
    Falls back to nearest node if route is exhausted.
    """
    route = v.get("route_xy", [])
    route_i = int(v.get("route_i", 0))

    # Walk forward in the route to find the next node that exists in driving_nodes
    for look_ahead in range(1, 4):
        idx = route_i + look_ahead
        if idx >= len(route):
            break
        rx, ry, rf = route[idx]
        # Find driving node at this position
        best, best_d = None, float("inf")
        for nid, n in dn.items():
            if int(n["floor"]) != int(rf):
                continue
            d = (float(n["x"]) - rx) ** 2 + (float(n["y"]) - ry) ** 2
            if d < best_d:
                best_d, best = d, nid
        if best and best_d < 4.0:  # within ~2 world units → confirmed match
            return best

    # Fallback: nearest node to current position
    return _find_nearest_node(dn, v["x"], v["y"], v.get("floor", 0))


def reassign_from_current(offline: Dict[str, Any], runtime: Dict[str, Any], vid: str,
                          weights: Dict[str, Any], reserve_sec: int,
                          forward_hint: Optional[str] = None) -> bool:
    """
    Reassign a vehicle whose reserved spot was stolen.

    Canonical three-step algorithm (see ALGORITHM.md):

    STEP 1 — Zone search on intended_floor
      intended_floor is always the floor Step 1 searches — derived from
      pending_floor (if set) or original_target_floor / current_floor.
      Single instance:   closest free spot within TARGET_ZONE_RADIUS × 1.8^n.
      Multi-instance:    spiral from LOCAL_TARGET_RADIUS up to TARGET_ZONE_RADIUS × 1.8^n,
                         preferring nearest instance by current drive time.
      Zone is purely geometry-based (no presented_walk_m); expands with floor changes.
      If Step 1 finds nothing → Step 2.

    STEP 2 — Global Score (zone exhausted on intended_floor = E)
      Mark E as visited (append to visited_floors, never cleared).
      Candidate set:
        • E-floor: ALL free spots — ALWAYS included in every scoring pass.
          This is the key invariant: E-floor spots compete directly with
          other-floor candidates so Score can legitimately stay on E when
          an E-spot beats everything else. No artificial zone enforcement
          applies after the zone boundary fires.
        • Other floors: only the single best transport-target-closest spot
          per floor (walk-closest, drive tiebreak). Guarantees concentric
          fill on every floor the vehicle subsequently visits.
      Three passes gate which OTHER-floor candidates join the E-floor pool.
      All passes are anchored on E (= intended_floor), NOT current_floor:
        Pass 1: E-floor + unvisited floors ≥ E   (preferred — no regression)
        Pass 2: E-floor + all floors ≥ E          (visited ok, no regression)
        Pass 3: E-floor + all floors              (last resort — truly empty above E)
      Scoring: score = drive_time + WALK_WEIGHT × walk_to_nearest_transport_target
      If winner on floor N ≠ E → pending_floor = N.
        Vehicle is committed to N. E is already in visited_floors (locked).
        On next reassign, intended_floor = N, Step 1 runs there with expanded
        1.8^n radius. Vehicle will NEVER navigate back to E or floors below N
        (except Pass 3 last resort when the garage is genuinely empty above N).
      If winner on E → pending_floor = None. Vehicle stays on E naturally.

    STEP 3 — Legacy fallback (choose_best_spot with offline rankings)

    Parameters
    ----------
    offline      : pre-computed layout data (driving_nodes, targets, scoring_params, …)
    runtime      : live state (spots, vehicles)
    vid          : vehicle id to reassign
    weights      : scoring weight overrides (currently unused in Steps 1-2)
    reserve_sec  : how many seconds to hold the new reservation
    forward_hint : driving-graph node the vehicle is currently heading toward;
                   if None, computed via _find_forward_node(). Must be captured
                   BEFORE clearing route_xy — see module docstring.
    """
    from core.scoring import choose_best_spot

    v = runtime["vehicles"].get(vid)
    if not v:
        return False

    dn      = offline["driving_nodes"]
    targets = offline["targets"]
    spots   = runtime["spots"]
    target_type = v.get("target_type", "elevator")
    sp      = offline.get("scoring_params", {})

    LOCAL_TARGET_RADIUS    = float(sp.get("local_target_radius")      or 40.0)
    TARGET_ZONE_RADIUS     = float(sp.get("target_zone_radius")       or 100.0)
    WALK_TOLERANCE         = float(sp.get("walk_tolerance")           or 20.0)
    FLOOR_PENALTY_PER_LVL  = float(sp.get("floor_penalty_per_level")  or 0.0)
    WALK_WEIGHT            = _WALK_WEIGHT

    # ── Entrance mode: closest FREE spot by Euclidean from CURRENT position ──
    if target_type == "entrance":
        entrance_id = v["entrance_id"]
        best = _pick_reassign_spot(spots, v, dn)
        if not best:
            v["status"] = "CHOOSING"
            return False
        # Commit reservation
        v["assigned_spot"] = best["id"]
        if best.get("status") != "RESERVED":
            best["status"]         = "RESERVED"
            best["reserved_for"]   = vid
            best["reserved_until"] = now_ts() + reserve_sec
        # Build route from vehicle's current forward node to the new spot
        cur_nearest = forward_hint or _find_forward_node(dn, v) or entrance_id
        dg_ent = _build_graph(offline)
        real_dists_ent, parents_ent = dijkstra_with_parent(dg_ent, cur_nearest)
        access_node = best.get("best_access", {}).get(entrance_id) or best["access"][0]["node"]
        path_ent = reconstruct_path(parents_ent, cur_nearest, access_node)
        xy = [(v["x"], v["y"], v["floor"])]
        if cur_nearest in dn:
            fn = dn[cur_nearest]
            fnx, fny, fnf = float(fn["x"]), float(fn["y"]), int(fn["floor"])
            if (fnx - v["x"]) ** 2 + (fny - v["y"]) ** 2 > 1:
                xy.append((fnx, fny, fnf))
        for n in path_ent:
            if n in dn:
                nx_, ny_, nf_ = float(dn[n]["x"]), float(dn[n]["y"]), int(dn[n]["floor"])
                if (nx_ - xy[-1][0]) ** 2 + (ny_ - xy[-1][1]) ** 2 > 1:
                    xy.append((nx_, ny_, nf_))
        xy = _finalize_spot_approach(xy, best)
        v["route_xy"] = xy
        v["route_i"]  = 0
        v["status"]   = "DRIVING"
        if xy:
            v["x"], v["y"], v["floor"] = xy[0]
        return True

    nearest = forward_hint or _find_forward_node(dn, v) or v["entrance_id"]
    dg = _build_graph(offline)
    real_dists, parents = dijkstra_with_parent(dg, nearest)

    # ── Helpers ───────────────────────────────────────────────────────────────
    ELEVATOR_TYPES = frozenset({"elevator", "escalator"})

    def eff_sub(t):
        return t.get("target_group") or t.get("subtype") or "default"

    def spot_walk(s, t) -> float:
        return math.sqrt((float(s["x"]) - float(t["x"])) ** 2 +
                         (float(s["y"]) - float(t["y"])) ** 2)

    def drive_to_target_approx(t) -> float:
        """Approximate drive time from vehicle to target node (used to sort instances)."""
        tx, ty = float(t["x"]), float(t["y"])
        best = float("inf")
        for nid, nd in dn.items():
            if int(nd.get("floor", 0)) == int(t.get("floor", 0)):
                d = real_dists.get(nid, float("inf"))
                if d < float("inf"):
                    w = math.sqrt((float(nd["x"]) - tx) ** 2 +
                                  (float(nd["y"]) - ty) ** 2)
                    candidate = d + w * 0.3
                    if candidate < best:
                        best = candidate
        return best

    def drive_to_spot(s) -> float:
        """Drive time from vehicle's current node to spot s."""
        best = float("inf")
        for ap in s.get("access", []):
            d = float(real_dists.get(ap["node"], float("inf")))
            if d < best:
                best = d
        return best

    # Requested subtype — narrows which elevator instances are considered.
    # Derived once from the vehicle's original target_type and held constant.
    requested_sub = None
    if target_type.startswith("elevator_inst_"):
        inst_id = target_type[len("elevator_inst_"):]
        t_obj   = next((t for t in targets if t.get("id") == inst_id), None)
        if t_obj:
            requested_sub = eff_sub(t_obj)
    elif (target_type.startswith("elevator_") and
          not target_type.startswith("elevator_group_")):
        requested_sub = target_type[len("elevator_"):]

    def get_floor_instances(floor: int) -> list:
        """
        All transport targets (elevator OR escalator) on `floor` matching the
        requested subtype.  'Single-instance' means exactly one target of this
        subtype on the floor (single closest-walk rule); 'multi-instance' means
        two or more (spiral expansion with WALK_TOLERANCE switching threshold).
        Works identically regardless of whether the targets are elevators,
        escalators, or a mix — target type is irrelevant; only the subtype group
        (target_group / subtype field) determines instance grouping.
        """
        return [t for t in targets
                if t.get("type") in ELEVATOR_TYPES
                and int(t.get("floor", 0)) == floor
                and (requested_sub is None or eff_sub(t) == requested_sub)]

    def best_spot_for_instance(t, floor: int):
        """
        Pick the FREE spot on `floor` closest (Euclidean walk) to transport
        target `t` (elevator or escalator).
        Tiebreak: minimum drive time from the vehicle's current position.
        Returns (spot, walk_m) or None.
        """
        best_s, best_w, best_dt = None, float("inf"), float("inf")
        for s in spots:
            if s.get("status") != "FREE" or int(s.get("floor", 0)) != floor:
                continue
            w  = spot_walk(s, t)
            dt = drive_to_spot(s)
            if w < best_w or (w == best_w and dt < best_dt):
                best_w, best_dt, best_s = w, dt, s
        return (best_s, best_w) if best_s else None

    # ── State carried on the vehicle ─────────────────────────────────────────
    current_floor   = int(v.get("floor", 0))
    visited_floors  = list(v.get("visited_floors") or [])

    # original_target_floor: the floor the user chose at entry.
    # Used so the vehicle completes its upward trip before considering current floor.
    original_target_floor = current_floor
    if target_type.startswith("elevator_inst_"):
        inst_id2 = target_type[len("elevator_inst_"):]
        t_obj2   = next((t for t in targets if t.get("id") == inst_id2), None)
        if t_obj2:
            original_target_floor = int(t_obj2.get("floor", current_floor))

    # ── Resolve intended_floor ────────────────────────────────────────────────
    # intended_floor is the floor Step 1 always searches — it is NEVER current_floor
    # when a pending_floor exists or when the vehicle hasn't reached its chosen floor.
    #
    # Priority (highest first):
    #   1. pending_floor — Step 2 already committed to this floor; run Step 1 there.
    #      If the vehicle has now physically arrived (current == pending), clear it.
    #   2. original_target_floor — vehicle still en route upward to user's choice.
    #   3. current_floor — default once on or past the chosen floor.
    pending_floor = v.get("pending_floor")
    if pending_floor is not None:
        if current_floor == pending_floor:
            # Arrived — clear pending and let Step 1 run normally on this floor.
            v["pending_floor"] = None
            pending_floor = None
            intended_floor = current_floor
        else:
            # Still in transit toward committed floor — Step 1 runs there already.
            intended_floor = pending_floor
    elif (original_target_floor not in visited_floors
          and current_floor < original_target_floor):
        # Still travelling upward to user-chosen floor.
        intended_floor = original_target_floor
    else:
        intended_floor = current_floor

    # ── Permanently banned floors ────────────────────────────────────────────
    # A floor is permanently banned from assignment — in every step and every
    # pass — under exactly two conditions:
    #
    #   1. It is in visited_floors.
    #      visited_floors is append-only. A floor enters it when Step 2 exhausts
    #      it and commits the vehicle to a higher floor. It can never be revisited.
    #
    #   2. It is strictly below pending_floor (when pending_floor is set).
    #      pending_floor records an in-transit commitment: the vehicle has been
    #      assigned a spot on floor N and is physically heading there but has not
    #      yet arrived. Any floor below N is behind the vehicle's commitment and
    #      must never be assigned — regardless of whether it is in visited_floors,
    #      how good its spots are, or which step/pass is running.
    #
    # These two conditions are the complete and authoritative definition of
    # "permanently banned." Pass 3 (last resort) may reach below intended_floor
    # but only to floors that are not banned by either condition above.
    _pending_at_entry = v.get("pending_floor")   # value before possible clearing above
    # After clearing logic above, pending_floor local var may be None (arrived).
    # Use the pre-clearing value for the lower-bound — if vehicle just arrived,
    # pending_floor was already cleared and intended_floor = current_floor, so
    # _pending_at_entry is None and no extra lower bound applies.
    banned_floors = set(visited_floors)
    if _pending_at_entry is not None:
        # All floors strictly below the committed floor are banned.
        banned_floors.update(f for f in range(_pending_at_entry))

    chosen_spot: Optional[dict] = None
    chosen_target: Optional[dict] = None

    # ═════════════════════════════════════════════════════════════════════════
    # STEP 1 — Zone search on intended_floor
    # ═════════════════════════════════════════════════════════════════════════
    # Never run on a banned floor (visited_floors or below pending commitment).
    floor_insts = (
        [] if intended_floor in banned_floors
        else get_floor_instances(intended_floor)
    )

    if floor_insts:
        # Sort instances by ascending drive time — inst-1 is physically nearest.
        insts_sorted = sorted(floor_insts, key=drive_to_target_approx)

        # Zone radius expands with each completed floor change.
        # n = number of floor changes already made (len(visited_floors)).
        # expansion = floor_change_expansion ^ n  (default 1.8^n).
        # On floor 0 (n=0): expansion=1.0 → base zone radius.
        # On floor 1 (n=1): expansion=1.8 → 80% larger zone.
        # On floor 2 (n=2): expansion=3.24 → vehicle tries hard to stay here.
        n         = len(visited_floors)
        expansion = _FLOOR_CHANGE_EXPANSION ** n

        if len(insts_sorted) == 1:
            # ── Single instance ───────────────────────────────────────────────
            # Acceptance threshold = TARGET_ZONE_RADIUS × expansion.
            # No dependency on presented_walk_m: the zone is purely geometry-based,
            # matching the initial assignment zone, and grows per floor change.
            ZONE_RADIUS = TARGET_ZONE_RADIUS * expansion

            result = best_spot_for_instance(insts_sorted[0], intended_floor)
            if result and result[1] <= ZONE_RADIUS:
                chosen_spot, chosen_target = result[0], insts_sorted[0]

        else:
            # ── Multi-instance spiral ─────────────────────────────────────────
            # MULTI_ZONE = TARGET_ZONE_RADIUS × expansion.
            # Spiral starts at LOCAL_TARGET_RADIUS and expands up to MULTI_ZONE.
            # Mirrors the initial assignment spiral with growing tolerance.
            MULTI_ZONE = TARGET_ZONE_RADIUS * expansion
            local_r    = LOCAL_TARGET_RADIUS

            while local_r <= MULTI_ZONE * 1.001:
                # Recompute inst-1's best walk at each radius step (occupancy changes).
                inst1_result = best_spot_for_instance(insts_sorted[0], intended_floor)
                inst1_walk   = inst1_result[1] if inst1_result else float("inf")

                # Check instances in drive-time order (inst-1 first).
                # inst-k must save k × WALK_TOLERANCE walk vs inst-1 to be preferred.
                for k, tk in enumerate(insts_sorted):
                    res_k = best_spot_for_instance(tk, intended_floor)
                    if not res_k:
                        continue
                    walk_k = res_k[1]
                    if (walk_k <= local_r
                            and walk_k <= inst1_walk - k * WALK_TOLERANCE
                            and walk_k <= MULTI_ZONE):
                        chosen_spot, chosen_target = res_k[0], tk
                        break

                if chosen_spot:
                    break
                if local_r >= MULTI_ZONE:
                    break
                local_r = min(local_r * _SPIRAL_EXPANSION, MULTI_ZONE)

            # Fallback: closest spot to any instance within MULTI_ZONE (inst-1 first).
            if not chosen_spot:
                for ti in insts_sorted:
                    result = best_spot_for_instance(ti, intended_floor)
                    if result and result[1] <= MULTI_ZONE:
                        chosen_spot, chosen_target = result[0], ti
                        break

    # ═════════════════════════════════════════════════════════════════════════
    # STEP 2 — Global Score (zone exhausted on intended_floor = E)
    # ═════════════════════════════════════════════════════════════════════════
    # Reached only when Step 1 found nothing.
    #
    # First action: mark E as visited (append-only — never cleared).
    #
    # Candidate set design (per spec):
    #   E-floor  → ALL free spots are ALWAYS present in every scoring pass.
    #              The three-pass system only gates OTHER floors — E is never
    #              gated. This lets Score keep filling E beyond the zone when
    #              an E-spot scores better than any other floor's representative.
    #   O-floors → only the single best spot per floor (min walk to nearest
    #              transport target — elevator OR escalator — with drive tiebreak).
    #              This guarantees concentric fill on every floor subsequently visited.
    #
    # Three passes anchor which OTHER-floor candidates join the E-floor pool.
    # All passes are anchored on E (= intended_floor), NOT current_floor.
    # Anchoring on E is critical: a vehicle physically on F0 but committed to F1
    # (pending=1) has intended_floor=F1 (=E on next Step 2), so Pass 1 correctly
    # excludes F0 — it is below E and already visited.
    #
    #   Pass 1: E-floor + unvisited floors ≥ E    (preferred — no regression, no revisit)
    #   Pass 2: E-floor + all floors ≥ E           (visited ok, no regression below E)
    #   Pass 3: E-floor + all floors               (last resort — garage empty at/above E)
    #
    # KEY COMMITMENT INVARIANT:
    #   Once Score picks floor N ≠ E, pending_floor = N. visited_floors already
    #   contains E (locked forever). On every subsequent reassign, intended_floor = N
    #   (or higher). The vehicle NEVER navigates back to E or any floor below N
    #   unless Pass 3 fires — meaning the garage is completely empty at and above N.
    if not chosen_spot:
        E = intended_floor
        if E not in visited_floors:
            visited_floors.append(E)
            banned_floors.add(E)   # keep banned_floors in sync

        all_floors = sorted(set(
            int(t.get("floor", 0)) for t in targets
            if t.get("type") in ELEVATOR_TYPES
            and (requested_sub is None or eff_sub(t) == requested_sub)
        ))
        unvisited_floors = [f for f in all_floors if f not in visited_floors]

        # Other-floor sets per pass (E excluded — always present in e_candidates).
        #
        # banned_floors (computed above) is the authoritative set of floors that
        # may NEVER appear in any pass. It contains:
        #   • all visited_floors (exhausted, committed away from permanently)
        #   • all floors strictly below pending_floor if pending was set on entry
        #     (vehicle is in transit to that floor; nothing behind it is reachable)
        #
        # E itself is excluded separately (always in e_candidates pool).
        # Pass 3 is the only pass that may go below E, but it still cannot include
        # any floor in banned_floors.
        other_pass1 = [f for f in all_floors if f > E  and f not in banned_floors]
        other_pass2 = [f for f in all_floors if f >= E and f not in banned_floors and f != E]
        other_pass3 = [f for f in all_floors if f != E and f not in banned_floors]

        # Pre-collect all E-floor candidates once (reused in every pass).
        e_floor_t = get_floor_instances(E) or [
            t for t in targets
            if t.get("type") in ELEVATOR_TYPES
            and int(t.get("floor", 0)) == E
        ]
        e_candidates = []   # list of (spot, floor_targets)
        if e_floor_t:
            for s in spots:
                if s.get("status") == "FREE" and int(s.get("floor", 0)) == E:
                    e_candidates.append((s, e_floor_t))

        def _best_score_in_passes(other_floor_sets):
            """
            Score E-floor candidates (always present) together with the best
            spot from each other floor specified by the current pass.
            Stop at the first pass that yields any winner.

            Scoring formula:
                score = drive_time(vehicle→spot)
                      + WALK_WEIGHT × walk(spot→elevator)
                      + max(0, floor - E) × FLOOR_PENALTY_PER_LVL

            E-floor  : floor_depth = 0 (no penalty). Every FREE spot included.
            O-floor above E: floor_depth = floor - E ≥ 1. Penalty grows with
                       each additional floor, gently favouring lower floors.
            O-floor below E (Pass 3 only): floor_depth = 0 (no extra penalty —
                       already implicitly costly via longer drive_time).

            O-floor candidates: only the single best spot per floor (min walk,
                       drive tiebreak). Ensures concentric fill on each new floor.

            Commitment invariant: once the winner is on floor N ≠ E, pending_floor=N.
            E is locked in visited_floors. Vehicle never returns below N unless
            Pass 3 fires (garage empty at and above N).
            """
            for other_floors in other_floor_sets:
                # Build other-floor candidates (one best per floor).
                other_candidates = []
                for f in other_floors:
                    floor_t = get_floor_instances(f) or [
                        t for t in targets
                        if t.get("type") in ELEVATOR_TYPES
                        and int(t.get("floor", 0)) == f
                    ]
                    if not floor_t:
                        continue
                    best_s, best_w, best_dt = None, float("inf"), float("inf")
                    for s in spots:
                        if s.get("status") != "FREE" or int(s.get("floor", 0)) != f:
                            continue
                        w  = min(spot_walk(s, t) for t in floor_t)
                        dt = drive_to_spot(s)
                        if w < best_w or (w == best_w and dt < best_dt):
                            best_w, best_dt, best_s = w, dt, s
                    if best_s:
                        other_candidates.append((best_s, floor_t))

                # Combined pool: E-floor always present.
                all_candidates = e_candidates + other_candidates
                if not all_candidates:
                    continue

                best_score  = float("inf")
                winner_spot   = None
                winner_target = None

                for s, floor_t in all_candidates:
                    dt_val = drive_to_spot(s)
                    if dt_val == float("inf"):
                        continue
                    walk_w     = min(spot_walk(s, t) for t in floor_t)
                    spot_floor = int(s.get("floor", E))
                    # floor_depth: floors above E (current exhausted floor).
                    # E-floor candidates have depth 0 (no penalty).
                    # Candidates below E (Pass 3 only) also get depth 0 — they are
                    # already penalised implicitly by longer drive times.
                    floor_depth = max(0, spot_floor - E)
                    score  = (dt_val
                              + WALK_WEIGHT * walk_w
                              + floor_depth * FLOOR_PENALTY_PER_LVL)
                    if score < best_score:
                        best_score    = score
                        winner_spot   = s
                        winner_target = min(floor_t, key=lambda t: spot_walk(s, t))

                if winner_spot:
                    return winner_spot, winner_target

            # If nothing found even with E-floor candidates included, return None.
            return None, None

        chosen_spot, chosen_target = _best_score_in_passes(
            (other_pass1, other_pass2, other_pass3)
        )

    # ── STEP 3: Legacy fallback ───────────────────────────────────────────────
    # Only reached when Steps 1 and 2 both found nothing.
    # banned_floors is enforced: discard any result on a banned floor.
    if not chosen_spot:
        _s3 = choose_best_spot(
            spots, v["entrance_id"], target_type, targets,
            runtime["vehicles"], weights,
            offline_rankings=offline.get("rankings"),
            real_time_dists=real_dists, scoring_params=sp,
        )
        if _s3 and int(_s3.get("floor", 0)) not in banned_floors:
            chosen_spot = _s3

    if not chosen_spot:
        v["status"] = "CHOOSING"
        return False

    # ── Commit ────────────────────────────────────────────────────────────────
    # Persist visited_floors — append-only, never cleared.
    v["visited_floors"] = visited_floors

    # pending_floor: tracks that the vehicle is physically heading to a floor
    # it has not yet reached. Must stay set until the vehicle physically arrives.
    #
    # Rule: pending = chosen_spot_floor if chosen_spot_floor != current_floor
    #                 else None
    #
    # The comparison is against current_floor (physical position), NOT intended_floor.
    # Reason: if the vehicle is on F0 and the new spot is on F1, pending must stay 1
    # even if intended_floor was already 1 (i.e. the previous pending was 1 and we
    # just reassigned to another F1 spot). Clearing against intended_floor was the bug:
    # it cleared pending the moment any F1 spot was chosen, even while vehicle on F0.
    chosen_spot_floor = int(chosen_spot.get("floor", current_floor))
    v["pending_floor"] = (chosen_spot_floor
                          if chosen_spot_floor != current_floor
                          else None)

    v["assigned_spot"]          = chosen_spot["id"]
    chosen_spot["status"]       = "RESERVED"
    chosen_spot["reserved_for"] = vid
    chosen_spot["reserved_until"] = now_ts() + reserve_sec

    if chosen_target:
        v["assigned_target_id"]   = chosen_target.get("id")
        v["assigned_target_info"] = {
            "id":    chosen_target.get("id"),
            "type":  chosen_target.get("type", "elevator"),
            "label": chosen_target.get("label", ""),
        }
    elif chosen_spot.get("_chosen_target"):
        ti = chosen_spot.pop("_chosen_target")
        v["assigned_target_id"]   = ti.get("id")
        v["assigned_target_info"] = ti

    # ── Build route ───────────────────────────────────────────────────────────
    best_access, best_d = None, float("inf")
    for ap in chosen_spot["access"]:
        d = float(real_dists.get(ap["node"], float("inf")))
        if d < best_d:
            best_d, best_access = d, ap["node"]
    if not best_access:
        best_access = chosen_spot["access"][0]["node"]

    path = reconstruct_path(parents, nearest, best_access)
    xy   = [(v["x"], v["y"], v["floor"])]
    if nearest in dn:
        fn = dn[nearest]
        fnx, fny, fnf = float(fn["x"]), float(fn["y"]), int(fn["floor"])
        if (fnx - v["x"]) ** 2 + (fny - v["y"]) ** 2 > 1:
            xy.append((fnx, fny, fnf))
    for n in path:
        if n in dn:
            nx = float(dn[n]["x"])
            ny = float(dn[n]["y"])
            nf = int(dn[n]["floor"])
            if (nx - xy[-1][0]) ** 2 + (ny - xy[-1][1]) ** 2 > 1:
                xy.append((nx, ny, nf))

    xy = _finalize_spot_approach(xy, chosen_spot)
    v["route_xy"] = xy
    v["route_i"]  = 0
    v["status"]   = "DRIVING"
    if xy:
        v["x"], v["y"], v["floor"] = xy[0]
    return True


def tick(offline: Dict[str, Any], runtime: Dict[str, Any], scenario: Dict[str, Any],
         weights: Dict[str, Any], dt: float,
         position_adapter=None) -> None:
    """
    Advance the simulation by one time step of length dt (seconds).

    This function handles routing logic and state transitions only.
    Physical movement of vehicles (updating x/y/floor/route_i) is delegated
    to position_adapter, which is swappable without touching this function.

    Parameters
    ----------
    offline           : precomputed navigation tables from offline.py (read-only)
    runtime           : mutable state dict — {"spots": [...], "vehicles": {...}}
    scenario          : scenario config (reserve_seconds, disable_auto_leave, ...)
    weights           : scoring weights for spot selection
    dt                : time step in seconds (effective = real_dt × speed_multiplier)
    position_adapter  : VehiclePositionAdapter that updates vehicle x/y/route_i.
                        Defaults to SimulatedVehiclePositionAdapter (current behaviour).

    ── HOW TO PLUG IN REAL VEHICLE POSITIONING ───────────────────────────────
    Pass a real adapter once per loop iteration:

        from core.adapters import RfidZoneVehicleAdapter
        adapter = RfidZoneVehicleAdapter(zone_map=layout["rfid_zones"])
        # wire: adapter.receive_zone_event(vid, zone_id, runtime)  ← from your RFID callback
        tick(offline, runtime, scenario, weights, dt, position_adapter=adapter)

    The adapter writes v["x"], v["y"], v["floor"], v["route_i"] for each DRIVING
    vehicle. This function then handles steal-detection and arrival-detection,
    which are always server-side regardless of how position is measured.
    ──────────────────────────────────────────────────────────────────────────
    """
    from core.adapters import SimulatedVehiclePositionAdapter
    if position_adapter is None:
        position_adapter = SimulatedVehiclePositionAdapter()

    spots    = runtime["spots"]
    vehicles = runtime["vehicles"]

    # ── Step 1: Detect stolen reservations → reroute ──────────────────────
    # A reservation is "stolen" when the spot is OCCUPIED by someone else,
    # or RESERVED for a different vehicle. Detected here every tick so the
    # affected vehicle is rerouted within one frame of the theft.
    for vid, v in list(vehicles.items()):
        if v.get("status") not in ("DRIVING",):
            continue

        sid = v.get("assigned_spot")
        if not sid:
            continue

        s = find_spot(spots, sid)
        if not s:
            continue

        stolen = (s["status"] == "OCCUPIED") or (
            s["status"] == "RESERVED" and s.get("reserved_for") != vid
        )

        if stolen:
            v["assigned_spot"] = None
            # Capture forward-hint BEFORE clearing the route — the node the
            # vehicle is currently heading toward, so the new route continues
            # forward rather than routing back toward the entrance.
            forward_hint = _find_forward_node(offline["driving_nodes"], v)
            v["route_xy"] = []
            v["route_i"]  = 0
            v["status"]   = "RECALCULATING"
            reassign_from_current(offline, runtime, vid, weights,
                                  scenario.get("reserve_seconds", 60),
                                  forward_hint=forward_hint)

    # ── Step 2: Move vehicles ──────────────────────────────────────────────────────
    # Delegated to position_adapter.
    # Simulation: SimulatedVehiclePositionAdapter advances x/y mathematically.
    # Production: RfidZoneVehicleAdapter / UwbVehicleAdapter writes real positions
    #             received from infrastructure and calls snap_route_index().
    position_adapter.tick(runtime, dt)

    # ── Step 3: Detect arrival (route_i at end of route) → PARKED ─────────
    # Done here (not in the adapter) because it involves spot state mutation,
    # which is always the server's responsibility.
    for v in vehicles.values():
        if v.get("status") != "DRIVING":
            continue
        route = v.get("route_xy", [])
        if not route:
            continue
        i = int(v.get("route_i", 0))
        if i >= len(route) - 1:
            v["status"] = "PARKED"
            s = find_spot(spots, v.get("assigned_spot"))
            if s:
                s["status"]        = "OCCUPIED"
                s["reserved_for"]  = v["id"]
                s["reserved_until"] = None
                v["x"], v["y"] = float(s["x"]), float(s["y"])
                v["floor"]     = int(s["floor"])

    # auto leave
    if not scenario.get("disable_auto_leave"):
        now = now_ts()
        for v in vehicles.values():
            if v.get("status") == "PARKED" and v.get("parked_until"):
                if now > v["parked_until"]:
                    s = find_spot(spots, v.get("assigned_spot"))
                    if s:
                        s["status"] = "FREE"
                        s["reserved_for"] = None
                    v["status"] = "LEFT"