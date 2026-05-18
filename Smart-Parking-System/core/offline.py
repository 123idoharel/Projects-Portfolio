"""
offline.py — Pre-computed Navigation Tables
============================================

Everything in this module is computed ONCE at startup (or loaded from a
pickle cache keyed on the layout hash) and then treated as read-only at
runtime. The goal is to answer the question "which spot is best for this
vehicle?" in a few microseconds, without re-running Dijkstra on every tick.

────────────────────────────────────────────────────────────────────────
What is computed, and why
────────────────────────────────────────────────────────────────────────

1. DRIVING GRAPH  (build_graph)
   ─────────────────────────────
   A directed weighted graph of all driving nodes and edges.
   Edge weight = length_m / speed_mps  →  travel time in seconds.
   Two versions are built:
     • normal  — edges in their defined direction (for entrance→spot routing)
     • reverse — edges flipped (for exit reverse-Dijkstra: exit→every node)

2. DIJKSTRA FROM EACH ENTRANCE  (compute_offline)
   ──────────────────────────────────────────────
   For every entrance node in the layout, run Dijkstra on the normal graph.
   Result: dist[entrance][node] = drive time in seconds from that entrance
   to that driving node.
   Stored in nav_parents / nav_dists for later route reconstruction.

3. REVERSE-DIJKSTRA FROM EACH EXIT  (compute_offline)
   ───────────────────────────────────────────────────
   For every exit target, run Dijkstra on the REVERSED graph starting at
   the exit's drive_node.  Because the graph is reversed, distances in this
   result represent "time to drive FROM any node TO the exit."
   Used by scoring.py to estimate how quickly a car can leave after parking.

4. PER-SPOT TABLES  (compute_offline — main spot loop)
   ─────────────────────────────────────────────────────
   For each parking spot, against each entrance and exit:

   drive_time[entrance]
       Minimum (Dijkstra time to best access node) + (maneuver time to spot).
       Maneuver time = euclidean_dist(access_node, spot) × MANEUVER_FACTOR.
       This represents the total time a vehicle spends driving from the
       entrance to the moment it pulls into the spot.

   best_access[entrance]
       The driving node the vehicle should use as its last turn-in point
       when approaching from this entrance.  Chosen as the access node with
       the lowest drive_time (not necessarily the geometrically nearest node).

   target_cost[elevator / exit]
       Walk distance (elevator) or reverse-drive time (exit) from this spot.
       Used by scoring.py as the primary optimisation objective:
       "park as close as possible to where you're going."

   Tie-break helpers (used ONLY for near-equal candidates):
     entrance_euclid_dist[entrance]   — floor 0: straight-line to entrance
     last_ramp_node[entrance]         — floor > 0: which ramp was used
     last_ramp_euclid_dist[entrance]  — floor > 0: distance to that ramp

5. RANKED SPOT LISTS  (rankings dict)
   ──────────────────────────────────
   Pre-sorted lists of all spots ordered by target_cost for each possible
   target type ("elevator", "elevator_tower_a", "exit", "exit_BEN_GURION",
   etc.).  scoring.py uses these ranked lists so it can scan candidates in
   best-first order without re-sorting on every vehicle arrival.

6. PEDESTRIAN GRAPH  (_build_pedestrian)
   ──────────────────────────────────────
   Delegated to pedestrian.py.  See that module for a full description.
   The result is stored in offline["pedestrian"] and used by FindMyCarScreen
   when a user walks to their parked car.

────────────────────────────────────────────────────────────────────────
Caching
────────────────────────────────────────────────────────────────────────
load_or_build_offline() hashes the layout JSON (MD5 of the serialised dict)
and stores the full offline dict as a pickle file in data/.
On the next server start with the same layout, the pickle is loaded in
milliseconds instead of re-running all Dijkstra passes.
The cache is automatically invalidated whenever the layout changes.

────────────────────────────────────────────────────────────────────────
Output shape  (offline dict)
────────────────────────────────────────────────────────────────────────
{
  "meta"            : layout metadata
  "driving_nodes"   : dict  id → {id, x, y, floor, type}
  "driving_edges"   : list  of edge dicts from the layout JSON
  "entrances"       : list  of entrance node ids
  "targets"         : list  of target dicts (elevators + exits)
  "spots"           : list  of enriched spot dicts (see spot fields above)
  "nav_parents"     : dict  entrance_id → Dijkstra parent pointers
  "nav_dists"       : dict  entrance_id → Dijkstra distance map
  "rankings"        : dict  target_key → sorted list of spot ranking dicts
  "scoring_params"  : dict  geometry constants for reassignment (see section below)
  "target_options"  : list  for the UI dropdown (labels + ids)
  "elevator_subtypes": list of unique elevator subtype strings
  "exit_ids"        : list of exit target ids
  "pedestrian"      : pedestrian graph (see pedestrian.py)
}
"""

import os
import pickle
import hashlib
import math
import json
from typing import Any, Dict, List, Tuple, Optional

from core.graphs import Graph, Node
from core.dijkstra import dijkstra_with_parent, reconstruct_path
from core.config import CFG

# Driving speeds per edge-type (meters/second)
DRIVING_SPEED_MPS              = CFG["offline"]["driving_speed_mps"]

# ── Geometry-derived algorithm factors (see settings.json for documentation) ──
_WINDOW_DIAG_FACTOR            = float(CFG["offline"]["window_diagonal_factor"])
_WINDOW_MIN_M                  = float(CFG["offline"]["window_min_m"])
_WINDOW_MAX_M                  = float(CFG["offline"]["window_max_m"])
_N_ROWS                        = int(CFG["offline"]["n_rows"])
_LOCAL_FRAC_MULTI              = float(CFG["offline"]["local_radius_frac_multi"])
_ZONE_FRAC_MULTI               = float(CFG["offline"]["zone_radius_frac_multi"])
_LOCAL_PCT_SINGLE              = float(CFG["offline"]["local_radius_pct_single"])
_ZONE_PCT_SINGLE               = float(CFG["offline"]["zone_radius_pct_single"])
_WALK_TOLERANCE_FRAC           = float(CFG["offline"]["walk_tolerance_frac"])
_FLOOR_CHANGE_PENALTY_FRAC     = float(CFG["offline"]["floor_change_penalty_frac"])


# Slow maneuver when entering spot
SPOT_MANEUVER_FACTOR_SEC_PER_M = CFG["offline"]["spot_maneuver_sec_per_meter"]


def euclidean_dist(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


# ─────────────────────────────────────────────────────────────────────────────
# Transport-mode tokens — used to decide whether two subtypes are "same
# destination, different access method" (group them) vs "different locations".
# e.g. mall_elevator + mall_escalator → group (differ in transport token)
#      offices_a     + offices_b      → separate (differ in location token)
# ─────────────────────────────────────────────────────────────────────────────
_TRANSPORT_TOKENS = frozenset({"elevator", "escalator", "stairs", "lift", "ramp"})


def _effective_subtype(t: dict) -> str:
    """Return the canonical subtype for a target.
    
    Prefers the explicit ``target_group`` field (new layouts) over the legacy
    ``subtype`` field, falling back to ``"default"`` when neither is present.
    
    Allowed target_group values: office_a, office_b, mall_elevator, mall_escalator
    """
    return t.get("target_group") or t.get("subtype") or "default"


def _should_group_subtypes(s1: str, s2: str) -> bool:
    """
    Return True when two elevator/escalator subtypes represent the same
    *destination* reached by different *transport modes*.

    Algorithm: split each subtype on '_', find the longest common prefix,
    then check if at least one of the differing suffix tokens is a known
    transport-mode keyword.  If yes → they're alternatives for the same place.
    """
    if s1 == s2:
        return False
    t1, t2 = s1.split("_"), s2.split("_")
    common_len = 0
    for a, b in zip(t1, t2):
        if a == b:
            common_len += 1
        else:
            break
    if common_len == 0:
        return False
    diff_tokens = set(t1[common_len:]) | set(t2[common_len:])
    return bool(diff_tokens & _TRANSPORT_TOKENS)


def _build_subtype_groups(subtypes: List[str]) -> Dict[str, List[str]]:
    """
    Given a list of elevator/escalator subtypes, produce a dict mapping
    group_key → [subtype, …] where grouped subtypes are alternatives for
    the same destination.  Singletons get a group_key equal to the subtype.

    Example (Mall Large):
      ['mall_elevator','mall_escalator','offices_a','offices_b']
      → {'mall': ['mall_elevator','mall_escalator'],
         'offices_a': ['offices_a'],
         'offices_b': ['offices_b']}

    Example (Dual Lanes):
      ['tower_a','tower_b','offices','street']
      → {'tower_a':['tower_a'], 'tower_b':['tower_b'],
         'offices':['offices'], 'street':['street']}
    """
    assigned: set = set()
    groups: Dict[str, List[str]] = {}

    for i, s1 in enumerate(subtypes):
        if s1 in assigned:
            continue
        group = [s1]
        for s2 in subtypes[i + 1:]:
            if s2 not in assigned and _should_group_subtypes(s1, s2):
                group.append(s2)
                assigned.add(s2)
        assigned.add(s1)

        if len(group) > 1:
            # Use the common prefix as key
            tokens = [s.split("_") for s in group]
            common = []
            for parts in zip(*tokens):
                if len(set(parts)) == 1:
                    common.append(parts[0])
                else:
                    break
            key = "_".join(common) if common else group[0]
        else:
            key = group[0]

        groups[key] = group

    return groups


def compute_scoring_params(layout: Dict[str, Any]) -> Dict[str, Any]:
    """
    Derive all scoring thresholds from layout geometry.  Called once at
    startup; results are stored in offline["scoring_params"] and passed
    into scoring.choose_best_spot() on every vehicle arrival.

    ════════════════════════════════════════════════════════════════════
    PARAMETER REFERENCE
    ════════════════════════════════════════════════════════════════════

    distance_window_by_subtype  /  distance_window_m
    ─────────────────────────────────────────────────
    Width of the candidate pool above the current minimum walk distance,
    computed per elevator subtype.

      Formula : window[sub] = walk[row_N] − walk[row_0]
                where rows are unique sorted walk-distances of F0 spots,
                N = N_ROWS = 3  (i.e. the span of the 4 nearest rows)

      distance_window_m is the global fallback used when a subtype key
      is not found in distance_window_by_subtype.

    floor_walk_eps_by_subtype
    ─────────────────────────
    Floor-preference threshold (metres) — set equal to window[sub].

      When window == EPS the floor filter stays active for the full pool:
      floor 0 is preferred over floor 1 whenever any F0 spot remains
      within the candidate window, producing a clean row-by-row F0 fill
      before F1 spots become eligible.

    time_save_min_s
    ───────────────
      Set to float("inf") — the iterative cross-row drive-time switch
      (Step 4) is intentionally disabled.

      Rationale: allowing cross-row switches based on drive-time savings
      produced counter-intuitive, jumpy assignment sequences (e.g. a spot
      26 m further from the elevator was offered before a nearby spot
      simply because it saved 44 s of driving).  Users expect spots to
      fill in natural concentric-ring order around the elevator; drive
      time is used only to break ties within the same walk-distance row
      (Step 3 sort: primary=target_cost, secondary=drive_time).

    distance_equal_eps_m / time_equal_eps_s
    ────────────────────────────────────────
      1 m and 2 s — fixed sub-spot-precision epsilons.
    ════════════════════════════════════════════════════════════════════
    """
    spots   = layout["spots"]
    targets = layout.get("targets", [])

    _ELEV_TYPES = frozenset({"elevator", "escalator"})
    _FALLBACK_EPS = 5.0

    # ── Candidate window  ────────────────────────────────────────────────────
    floor0_spots = [s for s in spots if int(s.get("floor", 0)) == 0]
    if floor0_spots:
        xs = [s["x"] for s in floor0_spots]
        ys = [s["y"] for s in floor0_spots]
        diagonal_m = math.sqrt((max(xs) - min(xs))**2 + (max(ys) - min(ys))**2)
        distance_window_m = round(max(_WINDOW_MIN_M, min(_WINDOW_MAX_M, diagonal_m * _WINDOW_DIAG_FACTOR)), 1)
    else:
        distance_window_m = 30.0

    # ── floor_walk_eps_by_subtype  ───────────────────────────────────────────
    # Computed from full spot geometry (not the live ranking) to guarantee
    # a stable value independent of current lot occupancy.
    #
    # For each elevator subtype:
    #   1. For every F0 spot, compute its Euclidean distance to the nearest
    #      elevator target of this subtype on the same floor.
    #   2. Collect the unique sorted walk distances → walks_f0.
    #   3. gap1 = walks_f0[1] - walks_f0[0]  (spacing between row 1 and row 2)
    #   4. eps  = gap1 × 1.5

    elev_targets_by_subtype: Dict[str, List[Dict]] = {}
    for t in targets:
        if t.get("type") in _ELEV_TYPES:
            sub = _effective_subtype(t)
            elev_targets_by_subtype.setdefault(sub, []).append(t)

    # ── Per-subtype walk-row window and floor EPS  ──────────────────────────
    #
    # Both the candidate window and the floor-preference EPS are derived from
    # the same geometry: the physical span of the first N_ROWS unique walk-
    # distance rows of F0 spots for each elevator subtype.
    #
    #   window[sub] = EPS[sub] = walk[row_N] − walk[row_0]
    #
    # where row indices are sorted ascending (row_0 = nearest row to elevator).
    #
    # N_ROWS = 3  means: "fill the 4 nearest walk-distance bands (rows 0–3)
    # on floor 0 before considering floor 1 or cross-row drive-time switches."
    #
    # Why window == EPS:
    #   • The candidate pool is restricted to spots within `window` of the
    #     current best walk distance.  Setting EPS equal to the window means
    #     the floor filter stays active for the entire pool: floor 0 is
    #     preferred as long as *any* F0 spot remains inside the window.
    #   • When the pool only contains F1 spots (all F0 rows exhausted), EPS
    #     is irrelevant and the filter passes naturally.
    #
    # Why N_ROWS = 4 (raised from 3):
    #   • Covers a wider walking radius before dipping to an upper floor,
    #     matching driver expectations more closely.
    #   • Validated on all tested subtypes: mall_elevator F1 never in first
    #     16 vehicles, offices never, tower deferred to V15+.
    #   • N_ROWS=3 caused F1 to appear too early (V11 for mall_elevator,
    #     V12 for tower_a) while good F0 spots still remained.
    #
    # Fallback: if fewer than N_ROWS+1 distinct walk rows exist (very small
    # layout), use the span of all available rows.

    N_ROWS = _N_ROWS
    floor_walk_eps_by_subtype: Dict[str, float] = {}
    distance_window_by_subtype: Dict[str, float] = {}

    for subtype, tlist in elev_targets_by_subtype.items():
        walk_set: set = set()
        for s in spots:
            if int(s.get("floor", 0)) != 0:
                continue
            sx, sy = float(s["x"]), float(s["y"])
            min_cost = min(
                (math.sqrt((sx - float(t["x"]))**2 + (sy - float(t["y"]))**2)
                 for t in tlist if int(t.get("floor", 0)) == 0),
                default=float("inf"),
            )
            if min_cost < float("inf"):
                walk_set.add(round(min_cost, 4))

        walks_f0 = sorted(walk_set)
        if len(walks_f0) >= 2:
            idx = min(N_ROWS, len(walks_f0) - 1)
            span = round(walks_f0[idx] - walks_f0[0], 3)
        else:
            span = _FALLBACK_EPS

        floor_walk_eps_by_subtype[subtype] = span
        distance_window_by_subtype[subtype] = span

    return {
        # ── candidate window (per elevator subtype, see above) ──────────────
        "distance_window_m":           distance_window_m,       # global fallback
        "distance_window_by_subtype":  distance_window_by_subtype,
        # ── floor preference filter (per elevator subtype) ──────────────────
        "floor_walk_eps_by_subtype":   floor_walk_eps_by_subtype,
        # ── significant-save threshold ──────────────────────────────────────
        "time_save_min_s":             999999.0,
        "time_save_frac":              float(CFG["selection"]["time_save_frac"]),
        # ── tie-break epsilons (fixed) ──────────────────────────────────────
        "distance_equal_eps_m":        1.0,
        "time_equal_eps_s":            2.0,
        # ── reassignment geometry (derived below in compute_offline and patched in) ──
        # These are placeholders; the real values are filled by compute_offline
        # after the layout geometry is fully analysed.
        "local_target_radius":         None,   # filled by compute_offline
        "target_zone_radius":          None,   # filled by compute_offline
        "walk_tolerance":              None,   # filled by compute_offline
        "floor_change_penalty":        None,   # filled by compute_offline
    }


def build_graph(layout: Dict[str, Any], reverse: bool = False) -> Tuple[Graph, Dict[str, Node]]:
    """Build a directed graph; if reverse=True, swap edge directions for exit reverse-Dijkstra."""
    d_nodes = {
        n["id"]: Node(n["id"], n["floor"], n["x"], n["y"], n.get("type", "intersection"))
        for n in layout["driving"]["nodes"]
    }
    dg = Graph(d_nodes)

    for e in layout["driving"]["edges"]:
        speed = DRIVING_SPEED_MPS.get(e.get("type", "main"), 2.0)
        w = float(e["length_m"]) / speed  # seconds
        u, v = e["from"], e["to"]
        if reverse:
            u, v = v, u
        dg.add_edge(u, v, w, e.get("type", "main"), bool(e.get("bidir", True)))

    return dg, d_nodes


def _last_ramp_on_path(path: List[str], d_nodes: Dict[str, Node]) -> Optional[str]:
    """Return the last node-id on the given path that is a ramp (node.type == 'ramp')."""
    last = None
    for nid in path:
        n = d_nodes.get(nid)
        if n and n.type == "ramp":
            last = nid
    return last


def compute_offline(layout: Dict[str, Any]) -> Dict[str, Any]:
    dg_normal, d_nodes = build_graph(layout, reverse=False)
    dg_reverse, _      = build_graph(layout, reverse=True)

    entrances = layout["entrances"]
    targets   = layout["targets"]
    spots     = layout["spots"]

    # Layout-adaptive scoring params — computed once, stored in output dict
    scoring_params = compute_scoring_params(layout)

    # Fill in group windows (needs subtype_groups, built later in this function)
    # We'll patch scoring_params["window_by_target"] after subtype_groups is ready.

    # ─────────────────────────────────────────────────────────────────────────
    # Dijkstra from entrances
    # ─────────────────────────────────────────────────────────────────────────
    entrances_data: Dict[str, Dict[str, Any]] = {}
    for ent in entrances:
        if ent in d_nodes:
            dist, parent = dijkstra_with_parent(dg_normal, ent)
            entrances_data[ent] = {"dist": dist, "parent": parent}

    # -------------------------
    # Reverse-Dijkstra from exits
    # -------------------------
    exits_data: Dict[str, Dict[str, float]] = {}
    for t in targets:
        if t.get("type") == "exit":
            exit_node = t.get("drive_node")
            if exit_node and exit_node in d_nodes:
                dist, _ = dijkstra_with_parent(dg_reverse, exit_node)
                exits_data[t["id"]] = dist

    # Elevator/escalator subtypes & exit ids
    # "escalator" is treated identically to "elevator" for walk-distance scoring
    ELEVATOR_TYPES = frozenset({"elevator", "escalator"})
    elevator_subtypes = sorted({_effective_subtype(t) for t in targets
                                 if t.get("type") in ELEVATOR_TYPES})
    exit_ids = [t["id"] for t in targets if t.get("type") == "exit"]

    # Pre-build subtype groups for the UI target_options
    subtype_groups = _build_subtype_groups(elevator_subtypes)

    spots_out: List[Dict[str, Any]] = []
    ranking_data: List[Dict[str, Any]] = []

    # Pre-map entrances to their node coordinates (for floor-0 tie-break)
    entrance_xy: Dict[str, Tuple[float, float, int]] = {}
    for ent in entrances:
        n = d_nodes.get(ent)
        if n:
            entrance_xy[ent] = (float(n.x), float(n.y), int(n.floor))

    for s in spots:
        spot_id = s["id"]
        spot_floor = int(s["floor"])
        spot_x, spot_y = float(s["x"]), float(s["y"])

        # ---------------------------------------------------------
        # tie-break helper A (floor 0): Euclid distance to entrance
        # ---------------------------------------------------------
        entrance_euclid_dist: Dict[str, float] = {}
        if spot_floor == 0:
            for ent, (ex, ey, ef) in entrance_xy.items():
                entrance_euclid_dist[ent] = euclidean_dist(spot_x, spot_y, ex, ey)

        # ---------------------------------------------------------
        # Drive time from each entrance + best access node
        # Also capture the LAST ramp used on the path to that access node.
        # ---------------------------------------------------------
        drive_time_by_ent: Dict[str, float] = {}
        best_access_by_ent: Dict[str, Optional[str]] = {}
        last_ramp_node_by_ent: Dict[str, Optional[str]] = {}
        last_ramp_euclid_dist_by_ent: Dict[str, float] = {}

        for ent, data in entrances_data.items():
            best_t, best_node = float("inf"), None

            # choose best access node by (dijkstra_time_to_node + maneuver_to_spot)
            for ap in s.get("access", []):
                node = ap.get("node")
                if node in d_nodes:
                    d_val = float(data["dist"].get(node, float("inf")))
                    if d_val < float("inf"):
                        node_obj = d_nodes[node]
                        spot_dist = euclidean_dist(node_obj.x, node_obj.y, spot_x, spot_y)
                        total = d_val + spot_dist * SPOT_MANEUVER_FACTOR_SEC_PER_M
                        if total < best_t:
                            best_t = total
                            best_node = node

            drive_time_by_ent[ent] = best_t
            best_access_by_ent[ent] = best_node

            # tie-break helper B (floors > 0): last ramp used on the path
            if best_node and spot_floor > 0:
                parent = data["parent"]
                path = reconstruct_path(parent, ent, best_node)
                last_ramp = _last_ramp_on_path(path, d_nodes)
                last_ramp_node_by_ent[ent] = last_ramp
                if last_ramp:
                    rn = d_nodes[last_ramp]
                    last_ramp_euclid_dist_by_ent[ent] = euclidean_dist(spot_x, spot_y, rn.x, rn.y)
                else:
                    last_ramp_euclid_dist_by_ent[ent] = None
            else:
                last_ramp_node_by_ent[ent] = None
                last_ramp_euclid_dist_by_ent[ent] = None

        # ---------------------------------------------------------
        # Target costs:
        # - elevator_* : WALK euclidean on same floor only
        # - exit_*     : DRIVE time using reverse-Dijkstra to exit drive_node
        # ---------------------------------------------------------
        target_costs: Dict[str, float] = {}

        # Elevator/escalator cost per subtype (each subtype = one physical destination type)
        elevator_costs_by_subtype: Dict[str, float] = {}
        best_elevator_by_subtype: Dict[str, Optional[Dict[str, Any]]] = {}

        for subtype in elevator_subtypes:
            min_cost = float("inf")
            best_elev = None
            for t in targets:
                if t.get("type") in ELEVATOR_TYPES and _effective_subtype(t) == subtype:
                    if int(t.get("floor", 0)) == spot_floor:
                        cost = euclidean_dist(spot_x, spot_y, float(t["x"]), float(t["y"]))
                        if cost < min_cost:
                            min_cost = cost
                            best_elev = {
                                "id":      t["id"],
                                "type":    t["type"],   # preserve original (elevator/escalator)
                                "subtype": subtype,
                                "label":   t.get("label", subtype),
                                "cost":    cost,
                                "x":       float(t["x"]),
                                "y":       float(t["y"]),
                                "floor":   int(t["floor"]),
                            }

            elevator_costs_by_subtype[subtype] = min_cost
            best_elevator_by_subtype[subtype]  = best_elev
            target_costs[f"elevator_{subtype}"] = min_cost

        # Group costs: best cost across all subtypes in each group
        # e.g. "elevator_mall" = min(elevator_mall_elevator, elevator_mall_escalator)
        group_costs_by_key: Dict[str, float] = {}
        best_elevator_by_group: Dict[str, Optional[Dict[str, Any]]] = {}
        for gkey, gsubtypes in subtype_groups.items():
            if len(gsubtypes) == 1:
                continue   # singleton — already has its own entry
            best_gcost = float("inf")
            best_gelev = None
            for sub in gsubtypes:
                c = elevator_costs_by_subtype.get(sub, float("inf"))
                if c < best_gcost:
                    best_gcost = c
                    best_gelev = best_elevator_by_subtype.get(sub)
            group_costs_by_key[gkey] = best_gcost
            best_elevator_by_group[gkey] = best_gelev
            target_costs[f"elevator_group_{gkey}"] = best_gcost

        # any elevator/escalator (global minimum)
        min_any_elevator = float("inf")
        best_any_elevator = None
        for subtype, cost in elevator_costs_by_subtype.items():
            if cost < min_any_elevator:
                min_any_elevator = cost
                best_any_elevator = best_elevator_by_subtype.get(subtype)
        target_costs["elevator"] = min_any_elevator

        # exit by id
        # Pre-compute euclidean distance from this spot to each exit node.
        # Used as primary sort key in exit rankings (gives smooth concentric
        # rings around the exit; drive-to-exit time has road-topology gaps).
        euclid_dist_by_exit: Dict[str, float] = {}
        exit_costs: Dict[str, float] = {}
        best_exit_info: Dict[str, Dict[str, Any]] = {}

        for exit_id in exit_ids:
            dist_map = exits_data.get(exit_id)
            if not dist_map:
                continue

            min_cost = float("inf")
            for ap in s.get("access", []):
                node = ap.get("node")
                if node in d_nodes:
                    drive_dist = float(dist_map.get(node, float("inf")))
                    if drive_dist < float("inf"):
                        node_obj = d_nodes[node]
                        spot_to_node = euclidean_dist(spot_x, spot_y, node_obj.x, node_obj.y)
                        total = drive_dist + spot_to_node * SPOT_MANEUVER_FACTOR_SEC_PER_M
                        if total < min_cost:
                            min_cost = total

            exit_costs[exit_id] = min_cost
            target_costs[f"exit_{exit_id}"] = min_cost

            # Euclidean distance: spot → exit node (ignores road topology)
            exit_t = next((t for t in targets if t.get("id") == exit_id), None)
            if exit_t:
                enode_id = exit_t.get("drive_node", "")
                enode = d_nodes.get(enode_id)
                if enode:
                    euclid_dist_by_exit[exit_id] = euclidean_dist(
                        spot_x, spot_y, enode.x, enode.y
                    )

            # meta info for UI / load counting
            tmeta = next((t for t in targets if t.get("id") == exit_id), None)
            best_exit_info[exit_id] = {
                "id": exit_id,
                "type": "exit",
                "label": (tmeta.get("label") if tmeta else exit_id),
                "cost": min_cost,
            }

        # any exit
        min_any_exit = float("inf")
        best_any_exit = None
        for exit_id, cost in exit_costs.items():
            if cost < min_any_exit:
                min_any_exit = cost
                best_any_exit = best_exit_info.get(exit_id)
        target_costs["exit"] = min_any_exit

        # -------------------------
        # Persist spot object
        # -------------------------
        spots_out.append({
            "id": spot_id,
            "floor": spot_floor,
            "x": spot_x,
            "y": spot_y,
            "status": "FREE",
            "reserved_for": None,
            "reserved_until": None,
            "theft_risk": float(s.get("theft_risk", 0.0)),
            "access": s.get("access", []),
            "drive_time": drive_time_by_ent,
            "best_access": best_access_by_ent,
            "target_cost": target_costs,
            # road_y: Y coordinate of the driving aisle in front of this spot.
            # Used to insert a right-angle approach waypoint in the route:
            # ...→ aisle_node → (spot_x, road_y) → (spot_x, spot_y)
            "road_y": s.get("road_y"),

            # spot_type: 'disabled' for accessible spots, 'standard' for all others.
            # Carried through so the assignment algorithm can filter by disability badge.
            "spot_type": s.get("spot_type", "standard"),
            # tie-break helpers (used ONLY in very-close ties)
            "entrance_euclid_dist": entrance_euclid_dist,
            "last_ramp_node": last_ramp_node_by_ent,
            "last_ramp_euclid_dist": last_ramp_euclid_dist_by_ent,
        })

        ranking_data.append({
            "id": spot_id,
            "elevator_cost": min_any_elevator,
            "best_elevator": best_any_elevator,
            "elevator_costs_by_subtype": elevator_costs_by_subtype,
            "best_elevator_by_subtype":  best_elevator_by_subtype,
            "group_costs_by_key":        group_costs_by_key,
            "best_elevator_by_group":    best_elevator_by_group,
            "exit_cost":     min_any_exit,
            "best_exit":     best_any_exit,
            "exit_costs":    exit_costs,
            "best_exit_by_id": best_exit_info,
            "euclid_dist_by_exit": euclid_dist_by_exit,
            # Per-instance walk cost: keyed by target id (e.g. "ELEV_MALL_1_F0")
            # Used when assigning after user picks a specific floor/instance
            "elevator_cost_by_instance": {
                t["id"]: euclidean_dist(spot_x, spot_y, float(t["x"]), float(t["y"]))
                for t in targets
                if t.get("type") in ELEVATOR_TYPES
                and int(t.get("floor", 0)) == spot_floor
            },
        })

    # ─────────────────────────────────────────────────────────────────────────
    # Build pre-sorted ranking lists (one per scoring target key)
    # ─────────────────────────────────────────────────────────────────────────
    rankings: Dict[str, List[Dict[str, Any]]] = {}

    rankings["elevator"] = sorted(
        [r for r in ranking_data if r["elevator_cost"] < float("inf")],
        key=lambda x: x["elevator_cost"],
    )

    for subtype in elevator_subtypes:
        rankings[f"elevator_{subtype}"] = sorted(
            [r for r in ranking_data
             if r["elevator_costs_by_subtype"].get(subtype, float("inf")) < float("inf")],
            key=lambda x: x["elevator_costs_by_subtype"].get(subtype, float("inf")),
        )

    # Per-instance rankings: one ranking per physical target id
    # e.g. "elevator_inst_ELEV_MALL_1_F0" → spots sorted by walk to that specific target
    # Used by assign when user has selected a specific floor (and thus a specific instance)
    all_elevator_targets = [t for t in targets if t.get("type") in ELEVATOR_TYPES]
    for et in all_elevator_targets:
        inst_key = f"elevator_inst_{et['id']}"
        rankings[inst_key] = sorted(
            [r for r in ranking_data
             if r["elevator_cost_by_instance"].get(et["id"], float("inf")) < float("inf")],
            key=lambda x, _tid=et["id"]: x["elevator_cost_by_instance"].get(_tid, float("inf")),
        )

    # Group rankings (multi-subtype groups, e.g. "elevator_group_mall")
    for gkey, gsubtypes in subtype_groups.items():
        if len(gsubtypes) > 1:
            rankings[f"elevator_group_{gkey}"] = sorted(
                [r for r in ranking_data
                 if r["group_costs_by_key"].get(gkey, float("inf")) < float("inf")],
                key=lambda x: x["group_costs_by_key"].get(gkey, float("inf")),
            )

    rankings["exit"] = sorted(
        [r for r in ranking_data if r["exit_cost"] < float("inf")],
        key=lambda x: x["exit_cost"],
    )

    for exit_id in exit_ids:
        # Sort by euclidean distance (spot → exit node).
        # This gives smooth concentric rings with no road-topology gaps.
        # Drive-to-exit time (exit_costs) is kept for reference but not used
        # as primary sort key here.
        _eid = exit_id  # capture for lambda
        rankings[f"exit_{exit_id}"] = sorted(
            [r for r in ranking_data
             if r["euclid_dist_by_exit"].get(_eid) is not None],
            key=lambda x, _e=_eid: x["euclid_dist_by_exit"].get(_e, float("inf")),
        )

    nav_parents = {ent: data["parent"] for ent, data in entrances_data.items()}
    nav_dists   = {ent: data["dist"]   for ent, data in entrances_data.items()}

    # ─────────────────────────────────────────────────────────────────────────
    # Build target_options for the UI
    # ─────────────────────────────────────────────────────────────────────────
    # Rules:
    # 1. Grouped subtypes (same destination, diff transport) → one entry with
    #    type="group", children=[{id, type, label, icon}, …].
    #    The frontend shows a sub-picker; the "best" option uses the group ranking.
    # 2. Singleton subtypes → one entry directly.
    # 3. Generic "nearest elevator" entry is always first.
    # 4. Exit entries follow (specific exits, then generic).
    # 5. "Nearest entrance" entry is always last.

    # Helper: pick icon by target type
    def _icon(t_type: str) -> str:
        return "🪜" if t_type == "escalator" else "🛗"

    target_options: List[Dict[str, Any]] = []

    # Generic nearest elevator (always present)
    target_options.append({
        "id":      "elevator",
        "type":    "elevator",
        "subtype": None,
        "label":   "🛗 מעלית / מדרגות (הקרובות ביותר)",
        "group":   False,
    })

    # Subtypes — grouped or singleton
    processed_subtypes: set = set()
    for gkey, gsubtypes in subtype_groups.items():
        if len(gsubtypes) > 1:
            # Multi-subtype group: emit one entry of type "group"
            # Build per-child info for the sub-picker
            children = []
            for sub in sorted(gsubtypes):
                sample = next((t for t in targets
                                if t.get("type") in ELEVATOR_TYPES
                                and _effective_subtype(t) == sub), None)
                if sample:
                    children.append({
                        "id":    f"elevator_{sub}",
                        "type":  sample["type"],
                        "label": sample.get("label", sub),
                        "icon":  _icon(sample["type"]),
                    })
            # Add an "any / doesn't matter" option as first child
            children.insert(0, {
                "id":    f"elevator_group_{gkey}",
                "type":  "elevator_group",
                "label": "לא משנה לי",
                "icon":  "✨",
            })
            # Label for the group button: use shortest unique label from children
            group_labels = [c["label"] for c in children[1:]]
            group_button_label = " / ".join(group_labels)
            target_options.append({
                "id":       f"elevator_group_{gkey}",
                "type":     "group",
                "subtype":  gkey,
                "label":    group_button_label,
                "icon":     "🛗",
                "group":    True,
                "children": children,
            })
        else:
            # Singleton subtype
            sub = gsubtypes[0]
            # Collect ALL targets with this subtype (may be multiple instances)
            all_instances = [t for t in targets
                             if t.get("type") in ELEVATOR_TYPES
                             and _effective_subtype(t) == sub]
            sample = all_instances[0] if all_instances else None
            if sample:
                # If multiple instances exist, use a generic group label
                # (e.g. "מעלית לקניון" not "מעלית לקניון 1")
                if len(all_instances) > 1:
                    # Strip trailing instance number: "מעלית לקניון 1" → "מעלית לקניון"
                    import re as _re
                    raw_label = sample.get("label", sub)
                    clean = _re.sub(r'\s*\d+\s*$', '', raw_label).strip()
                    display_label = clean if clean else raw_label
                else:
                    display_label = sample.get("label", sub)

                target_options.append({
                    "id":      f"elevator_{sub}",
                    "type":    sample["type"],
                    "subtype": sub,
                    "label":   display_label,
                    "icon":    _icon(sample["type"]),
                    "group":   False,
                })
        processed_subtypes.update(gsubtypes)

    # Exit options
    target_options.append({
        "id": "exit", "type": "exit", "exit_id": None,
        "label": "🚗 יציאה (הקרובה ביותר)", "group": False,
    })
    for t in targets:
        if t.get("type") == "exit":
            # Strip leading emoji from label (the icon field carries it separately)
            raw_label = t.get("label", t["id"])
            clean_label = raw_label.lstrip("🚗 ").strip()
            target_options.append({
                "id":      f"exit_{t['id']}",
                "type":    "exit",
                "exit_id": t["id"],
                "label":   clean_label,
                "icon":    "🚗",
                "group":   False,
            })

    # ─────────────────────────────────────────────────────────────────────────
    # Reassignment geometry parameters  (patched into scoring_params)
    # ─────────────────────────────────────────────────────────────────────────
    #
    # These are read by reassign_from_current() at runtime.  All distances are
    # Euclidean walk distances in metres; time values are seconds.
    #
    # ── Multi-instance parameters (used when ≥2 instances of same subtype
    #    exist on the same floor, e.g. mall_elevator in azrieli_mall_large) ──
    #
    # LOCAL_TARGET_RADIUS
    #   Inner preferred zone around the nearest instance.  If the closest free
    #   spot is within this radius, take it immediately without checking other
    #   instances.  Derived from the minimum inter-instance distance on any
    #   same-subtype same-floor pair:
    #     local_target_radius = (min_inter_dist / 2) × 0.40
    #   Fallback (no pairs): p30 of walk distances to nearest elevator from F0.
    #
    # TARGET_ZONE_RADIUS
    #   Outer acceptable zone.  Step 1 never picks a same-floor spot farther
    #   than this.  If no spot on intended_floor is within this radius, Step 2
    #   (floor change) is triggered.
    #     target_zone_radius = (min_inter_dist / 2) × 0.90
    #   Fallback: p70 of walk distances to nearest elevator from F0.
    #
    # WALK_TOLERANCE
    #   Hysteresis buffer for switching between instances.  A different instance
    #   is only chosen if its best spot is at least WALK_TOLERANCE closer than
    #   inst-1's best spot AND within TARGET_ZONE_RADIUS.  Prevents constant
    #   bouncing between instances near the midpoint.
    #     walk_tolerance = target_zone_radius × 0.20
    #
    # ── Single-instance parameter (used when exactly 1 instance of a subtype
    #    exists per floor, e.g. all subtypes in azrieli_dual_lanes) ──
    #
    # REASSIGN_TOLERANCE_RADIUS
    #   Added to the walk distance shown to the driver at entry (presented_walk_m)
    #   to form the acceptance threshold for Step 1:
    #     threshold = presented_walk_m + reassign_tolerance_radius
    #   The driver stays on the intended floor as long as the closest free spot
    #   is within this threshold.  Scales with the physical floor size:
    #     reassign_tolerance_radius = floor_diagonal × 0.08
    #   Factor 0.08 gives ~44 spots exhausted before floor-change in mall_large
    #   (vs 88 spots with 0.15), providing a more responsive floor-change experience.
    #
    # ── Shared ──
    #
    # FLOOR_CHANGE_PENALTY
    #   Cost (seconds) added per floor traversal in Step 2 scoring:
    #     penalty = abs(candidate_floor - intended_floor) × floor_change_penalty
    #   So floor 2 from floor 0 costs 2× and floor 3 costs 3×.
    #   Derived from one-way ramp traversal time:
    #     floor_change_penalty = (sum_ramp_lengths / ramp_speed / 2) × 0.5
    #   The ÷2 corrects for bidirectional edges listed once each.
    #   The ×0.5 reflects that the penalty represents partial (not full) cost
    #   to avoid over-penalising floor changes when the nearest spot is much
    #   closer on another floor.
    #
    # FLOOR_DIAGONAL / SCORING_PARAMS["floor_diagonal"]
    #   Stored for reference; used only to derive reassign_tolerance_radius.

    # Find minimum inter-instance distance (same subtype, same floor)
    min_inter_dist_reassign = float("inf")
    for subtype in elevator_subtypes:
        for fl in {int(t.get("floor", 0)) for t in targets if t.get("type") in ELEVATOR_TYPES}:
            inst = [t for t in targets
                    if t.get("type") in ELEVATOR_TYPES
                    and _effective_subtype(t) == subtype
                    and int(t.get("floor", 0)) == fl]
            for i, ta in enumerate(inst):
                for tb in inst[i+1:]:
                    d = euclidean_dist(float(ta["x"]), float(ta["y"]),
                                       float(tb["x"]), float(tb["y"]))
                    if d < min_inter_dist_reassign:
                        min_inter_dist_reassign = d

    floor0_spots = [s for s in spots_out if s["floor"] == 0]
    if floor0_spots and min_inter_dist_reassign < float("inf"):
        # Multiple instances: use inter-instance distance fractions
        half = min_inter_dist_reassign / 2.0
        local_target_radius = half * _LOCAL_FRAC_MULTI
        target_zone_radius  = half * _ZONE_FRAC_MULTI
    elif floor0_spots:
        # Single instance: use percentiles of all walk distances to nearest elevator
        walk_dists = []
        for s in floor0_spots:
            ec = s["target_cost"].get("elevator")
            if ec is not None and ec < float("inf"):
                walk_dists.append(ec)
        walk_dists.sort()
        n = len(walk_dists)
        if n >= 2:
            local_target_radius = walk_dists[int(n * _LOCAL_PCT_SINGLE)]
            target_zone_radius  = walk_dists[int(n * _ZONE_PCT_SINGLE)]
        else:
            local_target_radius = 40.0
            target_zone_radius  = 100.0
    else:
        local_target_radius = 40.0
        target_zone_radius  = 100.0

    walk_tolerance = target_zone_radius * _WALK_TOLERANCE_FRAC

    # FLOOR_CHANGE_PENALTY
    # One-way ramp traversal time × 0.5.
    # Ramp edges appear twice in the layout (one per direction), so we halve the
    # total to get the true one-way time, then halve again as a partial penalty.
    # Applied per floor in Step 2: penalty = abs(floor_delta) × floor_change_penalty.
    ramp_edges = [e for e in layout["driving"]["edges"] if e.get("type") == "ramp"]
    if ramp_edges:
        ramp_speed = DRIVING_SPEED_MPS.get("ramp", 1.0)
        ramp_times = [float(e["length_m"]) / ramp_speed for e in ramp_edges]
        one_way_ramp = sum(ramp_times) / 2.0   # bidirectional edges → one-way
        floor_change_penalty = one_way_ramp * _FLOOR_CHANGE_PENALTY_FRAC
    else:
        floor_change_penalty = 30.0   # fallback: 30 seconds per floor



    # floor_diagonal: the Euclidean diagonal of the floor bounding box.
    # Stored in scoring_params for reference; used by window computation above.
    if floor0_spots:
        xs = [float(s["x"]) for s in floor0_spots]
        ys = [float(s["y"]) for s in floor0_spots]
        floor_diagonal = math.sqrt((max(xs) - min(xs))**2 + (max(ys) - min(ys))**2)
    else:
        floor_diagonal = 200.0

    # floor_penalty_per_level: extra score added per floor above the zone-exhausted floor
    # during competition scoring. Represents the ramp traversal cost for extra floors.
    # = floor_change_penalty (one-way ramp time) × floor_penalty_frac
    _floor_penalty_frac = float(CFG["offline"]["floor_penalty_frac"])
    floor_penalty_per_level = round(floor_change_penalty * _floor_penalty_frac, 2)

    # Patch into scoring_params
    scoring_params["local_target_radius"]       = round(local_target_radius, 1)
    scoring_params["target_zone_radius"]        = round(target_zone_radius, 1)
    scoring_params["walk_tolerance"]            = round(walk_tolerance, 1)
    scoring_params["floor_change_penalty"]      = round(floor_change_penalty, 1)
    scoring_params["floor_penalty_per_level"]   = floor_penalty_per_level
    scoring_params["floor_diagonal"]            = round(floor_diagonal, 1)

    return {
        "meta":              layout["meta"],
        "driving_nodes":     {k: vars(v) for k, v in d_nodes.items()},
        "driving_edges":     layout["driving"]["edges"],
        "entrances":         entrances,
        "targets":           targets,
        "spots":             spots_out,
        "nav_parents":       nav_parents,
        "nav_dists":         nav_dists,
        "rankings":          rankings,
        "target_options":    target_options,
        "elevator_subtypes": elevator_subtypes,
        "subtype_groups":    subtype_groups,
        "exit_ids":          exit_ids,
        "scoring_params":    scoring_params,
        "pedestrian":        _build_pedestrian(
            layout, {k: vars(v) for k, v in d_nodes.items()}, spots_out),
    }


def get_layout_hash(layout: Dict[str, Any]) -> str:
    payload = json.dumps(layout, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(payload.encode()).hexdigest()[:12]


def load_or_build_offline(layout_path: str, layout: Dict[str, Any]) -> Dict[str, Any]:
    """Cache offline computation by a hash of the layout JSON."""
    os.makedirs("data", exist_ok=True)
    layout_hash = get_layout_hash(layout)
    cache_file = f"data/offline_{layout_hash}.pkl"

    if os.path.exists(cache_file):
        try:
            with open(cache_file, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    offline = compute_offline(layout)
    with open(cache_file, "wb") as f:
        pickle.dump(offline, f)

    return offline

def _build_pedestrian(layout, d_nodes, spots_out):
    """Build pedestrian graph — called from compute_offline."""
    from core.pedestrian import build_pedestrian_graph
    return build_pedestrian_graph(
        driving_nodes=d_nodes,
        driving_edges=layout["driving"]["edges"],
        spots=spots_out,
        targets=layout["targets"],
        entrances=layout["entrances"],
    )
