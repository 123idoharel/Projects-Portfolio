"""
pedestrian.py — Pedestrian Navigation Graph
============================================

Builds a walkable graph on top of the existing parking layout so that a
person standing at an elevator or entrance can be guided step-by-step to
their parked car — or vice versa.

The pedestrian graph is a completely separate data structure from the
driving graph.  It is built once (offline) and stored in
offline["pedestrian"].

════════════════════════════════════════════════════════════════════════
WHY A SEPARATE GRAPH?
════════════════════════════════════════════════════════════════════════

Drivers and pedestrians have fundamentally different movement rules:

  Drivers must                    Pedestrians can
  ──────────────────────────────  ──────────────────────────────────
  Follow one-way aisle direction  Cross aisles in any direction
  Stay on defined road surface    Walk through open corridor space
  Keep large inter-vehicle gaps   Step between tightly-packed spots
  Navigate ramps for floor change Use elevators (no ramps on foot)

So instead of reusing the driving graph with tweaked weights, we build
a dedicated graph that encodes the real physical paths a person walks.

════════════════════════════════════════════════════════════════════════
STEP 0: AUTO-DETECT CORRIDORS  (_detect_corridors)
════════════════════════════════════════════════════════════════════════

A "corridor" is the open walkway between two facing rows of spots that
have no driving road between them.  In a typical layout:

    Y=35  [row D — spots face inward ↓]
    Y=50  ─────────────── corridor ────────────────  ← pedestrian walkway
    Y=65  [row B — spots face inward ↑]

    Y=75  ════════════════ ROAD ════════════════════  ← driving aisle

    Y=85  [row A — spots face inward ↓]
    Y=100 ─────────────── corridor ────────────────  ← pedestrian walkway
    Y=115 [row C — spots face inward ↑]

Detection algorithm:
  1. Group all spots by Y-row.
  2. For every adjacent pair of Y-rows, check whether any driving road Y
     falls between them.  If no road separates them → corridor found.
  3. corridor_y = midpoint between the two rows
  4. corridor_width = Y-gap between the rows
  5. spot_pitch = median X-gap between adjacent spots in that corridor

From these, derive the entry_radius used to wire elevators to corridor nodes:
    entry_radius = corridor_width + spot_pitch  (layout-adaptive, no magic numbers)

In the current layout (2 floors × 2 corridors each):
  Corridor at Y=50  (rows D/B, width=30, pitch=15 → entry_radius=45)
  Corridor at Y=100 (rows A/C, width=30, pitch=15 → entry_radius=45)

════════════════════════════════════════════════════════════════════════
GRAPH STRUCTURE — 6 EDGE LAYERS
════════════════════════════════════════════════════════════════════════

All edges are bidirectional; all weights are Euclidean metres.
The 261 nodes and 757 edges in the current layout break down as:

Layer 1 — DRIVING ROADS  (made bidirectional for pedestrians)
─────────────────────────────────────────────────────────────
  Nodes : 37  — all driving nodes (intersections, entrance, exit, ramp)
  Edges : 64  — all driving edges, but one-way restrictions dropped
  Types : "main", "aisle"

  Rationale: a person can safely cross a parking aisle in any direction.
  These edges let the pedestrian graph route across the road infrastructure
  without having to duplicate it.

Layer 2 — SPOT NODES + SPOT_ACCESS
────────────────────────────────────
  Nodes : 150  — one SPOT_xxx node per parking space
  Edges : 204  — each spot wired to its nearest driving node(s)
  Types : "spot_access"

  Each SPOT node sits exactly at the spot's world coordinates.
  The spot_access edge is the "last metre" connection from the driving
  road infrastructure to the spot itself.

Layer 3 — CORRIDOR NODES  (the core innovation)
────────────────────────────────────────────────
  Nodes : 60   — one CORR_Ff_Yy_Xx per spot-column X per corridor
  Edges : 176  — 56 along-corridor + 120 corridor-to-spot
  Types : "corridor", "corridor_to_spot"

  Corridor nodes are placed at the corridor midline (e.g. Y=50), one per
  spot-column X that exists in that corridor.  They form a chain:

      CORR_X60 ─ CORR_X75 ─ CORR_X90 ─ ... ─ CORR_X290
         │           │           │
      spots at    spots at    spots at
      X=60 above  X=75 above  X=90 above
      and below   and below   and below

  Each CORR node is connected to:
    • its corridor neighbours left and right  ("corridor" edges)
    • the spots on both sides at the same X   ("corridor_to_spot" edges)

  This enables the most natural pedestrian movement: walk along the
  corridor, then turn perpendicular into the spot.

Layer 4 — ROW SHORTCUTS  (adjacent spots in same row)
───────────────────────────────────────────────────────
  Edges : 140  — between adjacent spots in the same row (< 25 m)
  Types : "row_shortcut"

  Lets a pedestrian walk along a row of spots laterally without needing
  to leave the row and re-enter via the corridor or road.

Layer 5 — COLUMN SHORTCUTS  (spots directly across the corridor)
────────────────────────────────────────────────────────────────
  Edges : 120  — between spots in the same column but different rows (≤ 35 m)
  Types : "column_shortcut"

  Enables direct cross-corridor movement from e.g. spot A02 (Y=85) to
  spot C02 (Y=115) across the corridor at Y=100.

Layer 6 — ELEVATOR ENTRY CONNECTIONS
──────────────────────────────────────
  Nodes : 8    — one TARGET_xxx per elevator
  Edges : 52   — entry_corridor (primary) + entry_direct / elevator_access (fallback)
  Types : "entry_corridor", "entry_direct", "elevator_access"

  Primary strategy (elevator inside a corridor):
    Wire the elevator to every CORR node within entry_radius (45 m).
    Each edge gets a tiny EPSILON=0.01 m penalty so Dijkstra prefers the
    pure corridor chain over any path that bounces through intermediate
    elevator nodes.

  Fallback strategy (road-adjacent elevator with no detected corridor):
    Wire directly to nearby road nodes and spots within a fixed radius.

════════════════════════════════════════════════════════════════════════
ROUTE COMPUTATION  (find_walk_route)
════════════════════════════════════════════════════════════════════════

Standard Dijkstra on the pedestrian graph.
  • Weight = metres (all edges are Euclidean distance)
  • Start  = elevator/entrance node (e.g. "TARGET_ELEV_TOWER_A_F0")
  • End    = spot node (e.g. "SPOT_F0-B06")

Returns:
  waypoints    — list of {id, x, y, floor, type} in walking order
  total_meters — sum of all edge weights on the path
  walk_minutes — total_meters / 1.2 m/s

Example path (Tower A elevator → spot B06):
  TARGET_ELEV_TOWER_A_F0  (75,100)  elevator        ← start
  CORR_F0_Y100_X75        (75,100)  corridor        ← step onto corridor
  SPOT_F0-A02             (75, 85)  spot            ← cross to row A
  F0_A2                  (100, 75)  intersection    ← step onto road
  SPOT_F0-B05            (125, 65)  spot            ← row shortcut
  SPOT_F0-B06            (140, 65)  spot            ← destination
  Total: 83.9 m, 1.2 min

The path uses a mix of corridor, road, and row-shortcut edges because
Dijkstra found that crossing the aisle directly was shorter than walking
the full corridor to column X=140.

════════════════════════════════════════════════════════════════════════
TURN-BY-TURN INSTRUCTIONS  (get_walk_instructions)
════════════════════════════════════════════════════════════════════════

Converts the raw waypoint list into Hebrew navigation instructions.

For each interior waypoint, computes the cross product of the incoming
and outgoing direction vectors to determine turn direction:
  cross > 0 → left (פנה שמאלה)
  cross < 0 → right (פנה ימינה)
  angle < 20° → straight (ignore — the walker won't notice)

Floor-change waypoints emit "עלה קומה" / "רד קומה" instead of a turn.
Each instruction includes:
  • text + icon for the current maneuver
  • next_action_text + icon for what's coming next (shown in the HUD)
  • distance_m to this maneuver
  • dist_to_next_m remaining after this maneuver

════════════════════════════════════════════════════════════════════════
KNOWN LIMITATIONS / FUTURE WORK
════════════════════════════════════════════════════════════════════════

Current gaps (identified but not yet implemented):

1. No intra-zone diagonal movement.
   A pedestrian walking from TOWER_A elevator diagonally to spot D09
   currently takes an L-shaped path (corridor then perpendicular).
   A direct diagonal through the open corridor space would save ~13 m.
   Fix: connect every node within the same zone (spots + CORR nodes)
   with direct Euclidean edges — let Dijkstra find the shortest diagonal.

2. No cross-zone shortcut without road crossing.
   Walking from B06 to A09 (two different zones) forces routing via the
   driving road at Y=75, adding a small detour.  In reality a person
   would step diagonally through both corridor spaces.
"""

import math
import heapq
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

WALK_SPEED_MPS      = 1.2    # average pedestrian walking speed (m/s)
SPOT_CONNECT_RADIUS = 30.0   # max dist to connect spot to road node (world units)


def euclidean(x1, y1, x2, y2) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _detect_corridors(
    spots: List[Dict],
    driving_nodes: Dict[str, Any],
) -> Dict[int, List[Dict]]:
    """
    For each floor, auto-detect pedestrian corridors — walkways between two
    facing rows of spots that have no driving road between them.

    Returns: floor → list of corridor dicts, each with:
      y, y_low, y_high, width, x_min, x_max, spot_xs, spot_pitch, entry_radius
    """
    floors = sorted(set(int(s["floor"]) for s in spots))
    result: Dict[int, List[Dict]] = {}

    for floor in floors:
        spots_f = [s for s in spots if int(s["floor"]) == floor]

        # Internal aisle road Ys only (exclude entrance/exit/ramp perimeter nodes)
        road_ys = sorted(set(
            float(n["y"])
            for n in driving_nodes.values()
            if int(n.get("floor", 0)) == floor
            and n.get("type", "intersection") == "intersection"
        ))

        # Group spots by Y row
        by_y: Dict[float, List[Dict]] = defaultdict(list)
        for s in spots_f:
            by_y[float(s["y"])].append(s)
        row_ys = sorted(by_y.keys())

        # Median spot pitch per row
        row_pitch: Dict[float, float] = {}
        for ry, rs in by_y.items():
            xs = sorted(float(s["x"]) for s in rs)
            gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
            row_pitch[ry] = _median(gaps) if gaps else 15.0

        corridors: List[Dict] = []
        for i in range(len(row_ys) - 1):
            y_low, y_high = row_ys[i], row_ys[i + 1]
            if any(y_low < ry < y_high for ry in road_ys):
                continue   # driving road separates these rows — not a corridor

            corridor_y = (y_low + y_high) / 2.0
            width      = y_high - y_low
            xs_union   = sorted(set(
                float(s["x"]) for s in spots_f
                if abs(float(s["y"]) - y_low)  < 1.0
                or abs(float(s["y"]) - y_high) < 1.0
            ))
            pitch = _median([row_pitch[y_low], row_pitch[y_high]])

            # Layout-derived entry radius: full corridor width + one spot pitch
            entry_radius = width + pitch

            corridors.append({
                "floor":        floor,
                "y":            corridor_y,
                "y_low":        y_low,
                "y_high":       y_high,
                "width":        width,
                "x_min":        min(xs_union) if xs_union else 0,
                "x_max":        max(xs_union) if xs_union else 0,
                "spot_xs":      xs_union,
                "spot_pitch":   pitch,
                "entry_radius": entry_radius,
            })

        result[floor] = corridors
    return result


def build_pedestrian_graph(
    driving_nodes: Dict[str, Any],
    driving_edges: List[Dict[str, Any]],
    spots: List[Dict[str, Any]],
    targets: List[Dict[str, Any]],
    entrances: List[str],
) -> Dict[str, Any]:
    """Build the full pedestrian navigation graph."""

    corridors_by_floor = _detect_corridors(spots, driving_nodes)

    ped_nodes: Dict[str, Dict] = {}
    ped_adj:   Dict[str, List[Tuple]] = {}

    def _add_node(nid, x, y, floor, ntype, **extra):
        ped_nodes[nid] = {"id": nid, "x": float(x), "y": float(y),
                          "floor": int(floor), "type": ntype, **extra}
        if nid not in ped_adj:
            ped_adj[nid] = []

    def _add_edge(u, v, dist_m, etype):
        if u in ped_adj and v in ped_adj:
            ped_adj[u].append((v, dist_m, etype))
            ped_adj[v].append((u, dist_m, etype))

    # ── Layer 1: driving nodes + edges (bidirectional) ────────────────────────
    for nid, n in driving_nodes.items():
        _add_node(nid, n["x"], n["y"], n["floor"], n.get("type", "intersection"))

    for e in driving_edges:
        u, v = e["from"], e["to"]
        if u in ped_nodes and v in ped_nodes:
            dist = float(e.get("length_m", euclidean(
                ped_nodes[u]["x"], ped_nodes[u]["y"],
                ped_nodes[v]["x"], ped_nodes[v]["y"],
            )))
            _add_edge(u, v, dist, e.get("type", "road"))

    # ── Layer 2: spot nodes + spot_access to nearest road node ───────────────
    spot_nearest_node: Dict[str, str] = {}
    for s in spots:
        sid  = f"SPOT_{s['id']}"
        sx, sy, sf = float(s["x"]), float(s["y"]), int(s["floor"])
        _add_node(sid, sx, sy, sf, "spot", spot_id=s["id"])

        best_dist, best_node = float("inf"), None
        for nid, n in driving_nodes.items():
            if int(n["floor"]) != sf:
                continue
            d = euclidean(sx, sy, float(n["x"]), float(n["y"]))
            if d < best_dist:
                best_dist, best_node = d, nid

        access_nids = {ap["node"] for ap in s.get("access", []) if ap["node"] in ped_nodes}
        if best_node:
            access_nids.add(best_node)
            spot_nearest_node[s["id"]] = best_node

        for anid in access_nids:
            if anid in ped_nodes:
                d = euclidean(sx, sy, ped_nodes[anid]["x"], ped_nodes[anid]["y"])
                if d <= SPOT_CONNECT_RADIUS:
                    _add_edge(sid, anid, d, "spot_access")

    # ── Layer 3: corridor nodes ───────────────────────────────────────────────
    # One CORR node per spot-column X, per corridor.
    # Connects: corridor ↔ corridor (walk along), corridor ↔ spot (turn in)
    corr_node_id: Dict[Tuple, str] = {}   # (floor, corridor_y, x) → node_id

    for floor, corridors in corridors_by_floor.items():
        for c in corridors:
            cy, y_low, y_high = c["y"], c["y_low"], c["y_high"]
            prev_cid = None
            for x in c["spot_xs"]:
                cid = f"CORR_F{floor}_Y{int(cy)}_X{int(x)}"
                _add_node(cid, x, cy, floor, "corridor")
                corr_node_id[(floor, cy, x)] = cid

                # Connect to previous corridor node (walk along corridor)
                if prev_cid is not None:
                    dx = abs(x - ped_nodes[prev_cid]["x"])
                    _add_edge(cid, prev_cid, dx, "corridor")

                # Connect to spots above (y_low) and below (y_high) at this X
                for s in spots:
                    if int(s["floor"]) != floor:
                        continue
                    if abs(float(s["x"]) - x) > 0.5:
                        continue
                    sy_s = float(s["y"])
                    if abs(sy_s - y_low) < 1.0 or abs(sy_s - y_high) < 1.0:
                        d = euclidean(x, cy, float(s["x"]), sy_s)
                        _add_edge(cid, f"SPOT_{s['id']}", d, "corridor_to_spot")
                prev_cid = cid

    # ── Layer 4: row shortcuts (adjacent spots in same row) ───────────────────
    rows: Dict[Tuple, List] = defaultdict(list)
    for s in spots:
        parts = s["id"].split("-")
        if len(parts) == 2:
            row_letter = "".join(c for c in parts[1] if c.isalpha()) or "X"
            rows[(int(s["floor"]), parts[0], row_letter)].append(s)

    for row_spots in rows.values():
        row_sorted = sorted(row_spots, key=lambda s: (float(s["x"]), float(s["y"])))
        for i in range(len(row_sorted) - 1):
            a, b = row_sorted[i], row_sorted[i + 1]
            d = euclidean(float(a["x"]), float(a["y"]), float(b["x"]), float(b["y"]))
            if d < 25.0:
                _add_edge(f"SPOT_{a['id']}", f"SPOT_{b['id']}", d, "row_shortcut")

    # ── Layer 5: column shortcuts (same X, different rows — cross corridor) ───
    columns: Dict[Tuple, List] = defaultdict(list)
    for s in spots:
        col_key = (int(s["floor"]), round(float(s["x"]) / 5) * 5)
        columns[col_key].append(s)

    for col_spots in columns.values():
        col_sorted = sorted(col_spots, key=lambda s: float(s["y"]))
        for i in range(len(col_sorted) - 1):
            a, b = col_sorted[i], col_sorted[i + 1]
            d = euclidean(float(a["x"]), float(a["y"]), float(b["x"]), float(b["y"]))
            if d <= 35.0:
                _add_edge(f"SPOT_{a['id']}", f"SPOT_{b['id']}", d, "column_shortcut")

    # ── Layer 6: elevators ────────────────────────────────────────────────────
    entry_points: List[Dict] = []

    for t in targets:
        if t.get("type") not in ("elevator", "escalator"):
            continue
        t_type = t.get("type", "elevator")
        tx, ty, tf = float(t["x"]), float(t["y"]), int(t.get("floor", 0))
        tid = f"TARGET_{t['id']}"
        _add_node(tid, tx, ty, tf, t_type)

        floor_corridors = corridors_by_floor.get(tf, [])
        my_corridor = None
        for c in floor_corridors:
            # Elevator is "in" a corridor if its Y sits within the corridor's Y band
            if c["y_low"] - 5 <= ty <= c["y_high"] + 5:
                my_corridor = c
                break

        if my_corridor:
            # Strategy A: elevator in a corridor → wire to corridor nodes.
            #
            # EPSILON penalty: add a tiny 0.01m to every entry_corridor edge.
            # This ensures Dijkstra always prefers the pure corridor chain over
            # routes that bounce through intermediate elevator nodes (which sit
            # on corridor nodes at d=0 and would otherwise create equal-cost
            # tie-breaks, causing visually confusing "routes via other elevators").
            ENTRY_EPSILON = 0.01
            r = my_corridor["entry_radius"]
            connected = False
            for x in my_corridor["spot_xs"]:
                cid = corr_node_id.get((tf, my_corridor["y"], x))
                if cid is None:
                    continue
                d = euclidean(tx, ty, x, my_corridor["y"])
                if d <= r:
                    _add_edge(tid, cid, d + ENTRY_EPSILON, "entry_corridor")
                    connected = True
            if not connected:
                # Fallback: nearest corridor node
                best_cid, best_d = None, float("inf")
                for x in my_corridor["spot_xs"]:
                    cid = corr_node_id.get((tf, my_corridor["y"], x))
                    if cid:
                        d = euclidean(tx, ty, x, my_corridor["y"])
                        if d < best_d:
                            best_d, best_cid = d, cid
                if best_cid:
                    _add_edge(tid, best_cid, best_d + ENTRY_EPSILON, "entry_corridor")
        else:
            # Strategy B: road-adjacent elevator (no corridor detected)
            road_ys_f = sorted(set(
                float(n["y"])
                for n in driving_nodes.values()
                if int(n.get("floor", 0)) == tf
                and n.get("type", "intersection") == "intersection"
            ))
            def _no_road_between(spot_y, elev_y):
                lo, hi = min(spot_y, elev_y), max(spot_y, elev_y)
                return not any(lo < ry < hi for ry in road_ys_f)

            for nid, n in driving_nodes.items():
                if int(n.get("floor", 0)) != tf:
                    continue
                d = euclidean(tx, ty, float(n["x"]), float(n["y"]))
                if d < 60.0:
                    _add_edge(tid, nid, d, "elevator_access")

            fallback_r = 45.0
            for s in spots:
                if int(s["floor"]) != tf:
                    continue
                d = euclidean(tx, ty, float(s["x"]), float(s["y"]))
                if d <= fallback_r and _no_road_between(float(s["y"]), ty):
                    sid = f"SPOT_{s['id']}"
                    if sid in ped_adj:
                        _add_edge(tid, sid, d, "entry_direct")

        entry_points.append({
            "id": tid, "label": t.get("label", t["id"]),
            "floor": tf, "type": t_type, "target_id": t["id"],
        })

    for eid in entrances:
        if eid in ped_nodes:
            n = ped_nodes[eid]
            entry_points.append({
                "id": eid, "label": f"כניסה {eid.replace('ENT_','').replace('_',' ')}",
                "floor": n["floor"], "type": "entrance", "target_id": eid,
            })

    seen: set = set()
    entry_points = [e for e in entry_points if not (e["id"] in seen or seen.add(e["id"]))]

    return {
        "ped_nodes":         ped_nodes,
        "ped_adj":           ped_adj,
        "entry_points":      entry_points,
        "spot_nearest_node": spot_nearest_node,
        "corridors":         corridors_by_floor,
    }


def find_walk_route(
    ped_nodes: Dict[str, Any],
    ped_adj:   Dict[str, List[Tuple]],
    from_node_id: str,
    to_spot_id:   str,
) -> Optional[Dict]:
    """Dijkstra on the pedestrian graph."""
    dest = f"SPOT_{to_spot_id}" if to_spot_id in [
        n.get("spot_id") for n in ped_nodes.values()
    ] else to_spot_id

    if from_node_id not in ped_adj or dest not in ped_adj:
        return None

    dist   = {nid: float("inf") for nid in ped_nodes}
    parent = {nid: None         for nid in ped_nodes}
    dist[from_node_id] = 0.0
    pq = [(0.0, from_node_id)]

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        if u == dest:
            break
        for v, w, _ in ped_adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v]   = nd
                parent[v] = u
                heapq.heappush(pq, (nd, v))

    if dist[dest] == float("inf"):
        return None

    path, curr = [], dest
    while curr is not None:
        n = ped_nodes[curr]
        path.append({"x": n["x"], "y": n["y"], "floor": n["floor"],
                     "type": n.get("type", "node"), "id": curr})
        if curr == from_node_id:
            break
        curr = parent.get(curr)
    path.reverse()

    total_m = dist[dest]
    return {
        "waypoints":    path,
        "total_meters": round(total_m, 1),
        "walk_minutes": round(total_m / WALK_SPEED_MPS / 60, 1),
    }


def _turn_direction(v1x, v1y, v2x, v2y) -> Optional[str]:
    cross = v1x * v2y - v1y * v2x
    dot   = v1x * v2x + v1y * v2y
    mag1  = math.sqrt(v1x**2 + v1y**2)
    mag2  = math.sqrt(v2x**2 + v2y**2)
    if mag1 < 0.001 or mag2 < 0.001:
        return None
    angle = abs(math.degrees(math.atan2(abs(cross), dot)))
    if angle < 20:
        return None
    return "left" if cross > 0 else "right"


def get_walk_instructions(waypoints: List[Dict]) -> List[Dict]:
    """Convert raw waypoints into turn-by-turn Hebrew instructions."""
    if not waypoints or len(waypoints) < 2:
        return []

    cumulative = [0.0] * len(waypoints)
    for k in range(1, len(waypoints)):
        a, b = waypoints[k - 1], waypoints[k]
        cumulative[k] = cumulative[k - 1] + euclidean(a["x"], a["y"], b["x"], b["y"])
    total_dist = cumulative[-1]

    maneuvers = []
    for k in range(1, len(waypoints) - 1):
        a, b, c = waypoints[k - 1], waypoints[k], waypoints[k + 1]
        if a["floor"] != b["floor"]:
            maneuvers.append((k, "floor_change", b["floor"] - a["floor"], cumulative[k]))
            continue
        if b["floor"] != c["floor"]:
            continue
        v1x, v1y = b["x"] - a["x"], b["y"] - a["y"]
        v2x, v2y = c["x"] - b["x"], c["y"] - b["y"]
        turn = _turn_direction(v1x, v1y, v2x, v2y)
        if turn:
            maneuvers.append((k, "turn", turn, cumulative[k]))

    def _text(mtype, mval):
        if mtype == "turn":
            return ("פנה ימינה" if mval == "right" else "פנה שמאלה",
                    "↱" if mval == "right" else "↰")
        if mtype == "floor_change":
            return ("עלה קומה" if mval > 0 else "רד קומה",
                    "🏃" if mval > 0 else "⬇️")
        return "המשך ישר", "⬆️"

    instructions = []
    if not maneuvers:
        instructions.append({
            "text": f"המשך ישר {round(total_dist)}מ'",
            "icon": "⬆️", "distance_m": round(total_dist), "floor_change": False,
            "next_action_text": "הגעת לרכב", "next_action_icon": "🎯",
            "dist_to_next_m": round(total_dist),
        })
    else:
        prev_dist = 0.0
        for idx, (wp_idx, mtype, mval, mdist) in enumerate(maneuvers):
            seg_dist = round(mdist - prev_dist)
            if idx + 1 < len(maneuvers):
                nx_txt, nx_ico = _text(maneuvers[idx+1][1], maneuvers[idx+1][2])
            else:
                nx_txt, nx_ico = "הגעת לרכב", "🎯"
            cur_txt, cur_ico = _text(mtype, mval)
            if seg_dist > 2:
                instructions.append({
                    "text": f"המשך ישר {seg_dist}מ'", "icon": "⬆️",
                    "distance_m": seg_dist, "floor_change": False,
                    "next_action_text": cur_txt, "next_action_icon": cur_ico,
                    "dist_to_next_m": seg_dist,
                })
            instructions.append({
                "text": cur_txt, "icon": cur_ico, "distance_m": 0,
                "floor_change": mtype == "floor_change",
                "next_action_text": nx_txt, "next_action_icon": nx_ico,
                "dist_to_next_m": round(total_dist - mdist),
            })
            prev_dist = mdist
        remaining = round(total_dist - maneuvers[-1][3])
        if remaining > 2:
            instructions.append({
                "text": f"המשך ישר {remaining}מ'", "icon": "⬆️",
                "distance_m": remaining, "floor_change": False,
                "next_action_text": "הגעת לרכב", "next_action_icon": "🎯",
                "dist_to_next_m": remaining,
            })

    instructions.append({
        "text": "הגעת לרכב שלך! 🚗", "icon": "🎯", "distance_m": 0,
        "floor_change": False, "next_action_text": "", "next_action_icon": "",
        "dist_to_next_m": 0,
    })
    return instructions
