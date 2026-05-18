# scoring.py
"""
scoring.py — Spot Selection Algorithm
======================================

Given a vehicle at an entrance asking for a spot near a specific target
(elevator or exit), this module selects the single best available parking
spot by balancing two competing goals:

  • proximity to destination  (target_cost — walk to elevator, or drive to exit)
  • ease of arrival           (drive_time  — how long to reach the spot from entrance)

════════════════════════════════════════════════════════════════════════
ELEVATOR MODE  (target_type starts with "elevator")
════════════════════════════════════════════════════════════════════════

The algorithm operates in four ordered steps.  All parameters are
supplied by offline.compute_scoring_params() and documented there.

──────────────────────────────────────────────────────────────────────
STEP 1 — Candidate window  (per-subtype)
──────────────────────────────────────────────────────────────────────
  Compute min_tc = min(target_cost) across all free spots.
  Keep only spots where target_cost ≤ min_tc + WINDOW[subtype].

  WINDOW[subtype] = walk[row_3] − walk[row_0]  (span of 4 nearest rows)
  Derived offline from full layout geometry; stored per subtype in
  scoring_params["distance_window_by_subtype"].

  Purpose: restrict competition to spots within a natural walking
  radius of the elevator, preventing distant spots from displacing
  nearby ones through drive-time optimisation.

──────────────────────────────────────────────────────────────────────
STEP 2 — Floor filter
──────────────────────────────────────────────────────────────────────
  Prefer the lowest available floor by restricting the pool to floor F
  when min_walk[F] ≤ min_walk[higher floors] + FLOOR_EPS[subtype].

  FLOOR_EPS[subtype] == WINDOW[subtype]  (they are set equal in offline.py)

  This equality is the key invariant: any F0 spot that exists within the
  candidate window keeps F0 preferred.  F1 is only admitted when all F0
  spots inside the window are occupied.

  Iterate floor indices ascending (0, 1, 2, …); stop at the first
  floor that satisfies the condition and restrict the pool to that floor.

  Fixes two historical bugs:
    BUG-1: F1 selected over F0 at equal walk distance due to 3 s road-
           geometry artifact in drive_time.
    BUG-2: Iterative switch failed to return to F0-row2 after F0-row1
           was exhausted because F1's drive_time inflated the threshold.

──────────────────────────────────────────────────────────────────────
STEP 3 — Distance-first sort with drive-time tie-breaking
──────────────────────────────────────────────────────────────────────
  Sort the (floor-filtered) pool by (target_cost ASC, drive_time ASC).
  Set current = pool[0].

  This is the primary selection: the spot closest to the elevator wins;
  among equal-walk spots, the one with the shortest drive from the
  entrance wins.

  Drive-time is intentionally limited to a tie-breaker role here.
  Cross-row switching based on drive-time savings was removed because it
  produced jumpy, counter-intuitive fill sequences: spots 26 m further
  from the elevator were offered before nearby spots simply because they
  saved 44 s of driving.  Drivers expect spots to fill in concentric
  rings around the elevator; drive time is visible to the driver in
  real time and is a secondary concern.

──────────────────────────────────────────────────────────────────────
STEP 4 — Close-bucket tie-break
──────────────────────────────────────────────────────────────────────
  Collect all pool spots where |target_cost − current.target_cost| ≤ 1 m.
  Sort by (floor ASC, drive_time ASC).

  If |best.drive_time − current.drive_time| ≤ 2 s, apply the geometric
  tie-break:
    • floor 0  → prefer smallest Euclidean distance to the entrance node
    • floor 1+ → prefer closest Euclidean distance to the last ramp node

════════════════════════════════════════════════════════════════════════
EXIT MODE  (target_type starts with "exit")
════════════════════════════════════════════════════════════════════════

Pure proximity sort: spots are ranked by target_cost (= reverse-Dijkstra
drive time to the exit) ascending.  Drive time from the entrance is used
only as a tie-breaker within TIME_EQUAL_EPS_S (2 s).

  Why pure proximity:
    Drivers choosing an exit target want to park as close as possible to
    their exit so they can leave quickly.  The time spent driving from the
    entrance to the spot is a secondary concern — the driver can observe
    it on their screen and decide accordingly.  The previous weighted
    formula (target_cost×10 + drive×0.5) occasionally offered a spot with
    a 2 s better exit cost but 65 s extra entrance-drive, which felt
    counter-intuitive.

  Congestion load (number of vehicles heading to the same exit) is still
  used as a secondary sort key to spread load across exits and aisles.

════════════════════════════════════════════════════════════════════════
ENTRANCE MODE  (target_type == "entrance")
════════════════════════════════════════════════════════════════════════

Select the spot with the shortest drive_time from the entrance.

════════════════════════════════════════════════════════════════════════
Rerouting  (real_time_dists parameter)
════════════════════════════════════════════════════════════════════════

When a vehicle is reassigned mid-journey, simulation.py passes fresh
Dijkstra distances from the vehicle's current road node as
real_time_dists, overriding precomputed drive_time values.

════════════════════════════════════════════════════════════════════════
ELEVATOR_GROUP mode  (target_type == "elevator_group_<key>")
════════════════════════════════════════════════════════════════════════

Uses the group ranking list (best cost across all subtypes in the group).
Window and EPS fall back to min(values) across all subtypes in the group.
"""

from typing import Dict, List, Optional
from core.config import CFG

# Module-level defaults (fallbacks if no scoring_params supplied)
_DEFAULT_DISTANCE_WINDOW_M = CFG["selection"]["distance_window_m"]
_DEFAULT_DIST_EQUAL_EPS_M  = CFG["selection"]["distance_equal_eps_m"]
_DEFAULT_TIME_EQUAL_EPS_S  = CFG["selection"]["time_equal_eps_s"]
_DEFAULT_TIME_SAVE_MIN_S   = CFG["selection"]["time_save_min_s"]
_DEFAULT_TIME_SAVE_FRAC    = CFG["selection"]["time_save_frac"]

# Fallback floor-preference EPS when scoring_params does not carry the
# per-subtype dict (e.g. old cached offline data or unit tests).
FLOOR_EPS_FALLBACK = 5.0


def _tie_key_for_close_candidates(c: Dict, entrance_id: str) -> float:
    """Return the final tie-break key (smaller is better)."""
    spot = c["spot"]
    floor = int(spot.get("floor", 0))

    # Floor 0: prefer closer to entrance (Euclidean in the layout plane)
    if floor == 0:
        return float(spot.get("entrance_euclid_dist", {}).get(entrance_id, float("inf")))

    # Floors > 0: prefer closer to the last ramp used in the entrance->access path
    val = spot.get("last_ramp_euclid_dist", {}).get(entrance_id)
    return float("inf") if val is None else float(val)


def choose_best_spot(
    spots: List[Dict],
    entrance_id: str,
    target_type: str,
    targets: List[Dict],
    vehicles: Dict,
    weights: Dict,
    tolerance_val: float = 0.0,
    offline_rankings: Dict = None,
    real_time_dists: Dict = None,
    scoring_params: Dict = None,
) -> Optional[Dict]:
    """
    Choose the best parking spot for a given entrance and target_type.

    scoring_params (optional)
        Layout-adaptive thresholds from offline.compute_scoring_params().
        Overrides the module-level defaults.  Keys:
          time_save_min_s, time_save_frac, distance_window_m,
          distance_equal_eps_m, time_equal_eps_s.
    """
    # ── Resolve per-call scoring thresholds ──────────────────────────────────
    p = scoring_params or {}
    DISTANCE_WINDOW_M = float(p.get("distance_window_m",    _DEFAULT_DISTANCE_WINDOW_M))
    DIST_EQUAL_EPS_M  = float(p.get("distance_equal_eps_m", _DEFAULT_DIST_EQUAL_EPS_M))
    TIME_EQUAL_EPS_S  = float(p.get("time_equal_eps_s",     _DEFAULT_TIME_EQUAL_EPS_S))
    TIME_SAVE_MIN_S   = float(p.get("time_save_min_s",      _DEFAULT_TIME_SAVE_MIN_S))
    TIME_SAVE_FRAC    = float(p.get("time_save_frac",       _DEFAULT_TIME_SAVE_FRAC))

    # ── Normalise target_type ────────────────────────────────────────────────
    # "elevator_group_<key>" → use the group ranking list directly.
    # "elevator_inst_<target_id>" → use per-instance ranking for zone-filling
    is_group = target_type.startswith("elevator_group_")
    is_inst  = target_type.startswith("elevator_inst_")
    if is_group:
        group_key = target_type[len("elevator_group_"):]
    elif is_inst:
        inst_target_id = target_type[len("elevator_inst_"):]
    else:
        group_key = None

    # ── Entrance mode: Euclidean distance from entrance, floor 0 first ────────
    if target_type == "entrance":
        ent_node = {}  # we don't have driving_nodes here; use entrance_euclid_dist
        free = [s for s in spots if s and s.get("status") == "FREE"]
        if not free:
            return None
        floors_asc = sorted({int(s.get("floor", 0)) for s in free})
        for fl in floors_asc:
            candidates = [s for s in free if int(s.get("floor", 0)) == fl]
            if not candidates:
                continue
            def _key(s):
                euclid = float(s.get("entrance_euclid_dist", {}).get(entrance_id, float("inf")))
                if real_time_dists:
                    dt = min((float(real_time_dists.get(ap["node"], float("inf")))
                              for ap in s.get("access", [])), default=float("inf"))
                else:
                    dt = float(s.get("drive_time", {}).get(entrance_id, float("inf")))
                return (euclid, dt, s["id"])
            candidates.sort(key=_key)
            best = candidates[0]
            best["_chosen_target"] = {
                "id": entrance_id, "type": "entrance",
                "label": "כניסה", "cost": 0.0,
            }
            return best
        return None
    # ── Rankings-based path ──────────────────────────────────────────────────
    if not offline_rankings:
        return None

    ranked_list = offline_rankings.get(target_type, [])
    if not ranked_list:
        # Graceful fallbacks
        if target_type.startswith("elevator_group_"):
            ranked_list = offline_rankings.get("elevator", [])
        elif target_type.startswith("elevator_inst_"):
            # Fall back to the subtype ranking if instance ranking missing
            ranked_list = offline_rankings.get("elevator", [])
        elif target_type.startswith("elevator_"):
            ranked_list = offline_rankings.get("elevator", [])
        elif target_type.startswith("exit_"):
            ranked_list = offline_rankings.get("exit", [])

    if not ranked_list:
        return None

    spots_map = {s["id"]: s for s in spots}

    # elevator_group_* and elevator_inst_* are both treated as elevator mode
    is_elevator        = target_type.startswith("elevator")
    is_specific_target = (
        "_" in target_type
        and target_type not in ("elevator", "exit")
    )

    # -----------------------------
    # Congestion/load per target
    # -----------------------------
    load_by_target: Dict[str, int] = {}
    for v in vehicles.values():
        if v.get("status") == "DRIVING":
            tid = v.get("assigned_target_id")
            if tid:
                load_by_target[tid] = load_by_target.get(tid, 0) + 1

    # -----------------------------
    # Build candidates (FREE spots)
    # -----------------------------
    candidates = []
    for rank_item in ranked_list:
        s = spots_map.get(rank_item["id"])
        if not s or s.get("status") != "FREE":
            continue

        # ── Target cost (walk-to-elevator OR drive-to-exit) ─────────────────
        if is_elevator:
            if is_inst:
                # Per-instance: use the walk distance to this specific elevator target
                target_cost = float(rank_item.get("elevator_cost_by_instance", {}).get(inst_target_id, float("inf")))
                # Build target_info from the targets list
                t_obj = next((t for t in targets if t.get("id") == inst_target_id), None)
                target_info = {
                    "id":    inst_target_id,
                    "type":  t_obj.get("type", "elevator") if t_obj else "elevator",
                    "label": t_obj.get("label", inst_target_id) if t_obj else inst_target_id,
                    "cost":  target_cost,
                } if t_obj else None
            elif is_group:
                # "elevator_group_<key>" — use the group best cost
                target_cost = float(rank_item.get("group_costs_by_key", {}).get(group_key, float("inf")))
                target_info = rank_item.get("best_elevator_by_group", {}).get(group_key)
            elif is_specific_target:
                # "elevator_<subtype>" — exact subtype
                subtype     = target_type[len("elevator_"):]
                target_cost = float(rank_item.get("elevator_costs_by_subtype", {}).get(subtype, float("inf")))
                target_info = rank_item.get("best_elevator_by_subtype", {}).get(subtype)
            else:
                # "elevator" — global nearest
                target_cost = float(rank_item.get("elevator_cost", float("inf")))
                target_info = rank_item.get("best_elevator")
        else:
            if is_specific_target:
                exit_id     = target_type[len("exit_"):]
                # Use euclidean distance as target_cost for exit candidates.
                # This gives smooth concentric-ring ordering with no road-
                # topology gaps.  Fall back to drive-time cost if missing
                # (e.g. old cached offline data without euclid field).
                euclid = rank_item.get("euclid_dist_by_exit", {}).get(exit_id)
                if euclid is not None:
                    target_cost = float(euclid)
                else:
                    target_cost = float(rank_item.get("exit_costs", {}).get(exit_id, float("inf")))
                target_info = rank_item.get("best_exit_by_id", {}).get(exit_id)
            else:
                target_cost = float(rank_item.get("exit_cost", float("inf")))
                target_info = rank_item.get("best_exit")

        if target_cost == float("inf"):
            continue

        # ---- Drive time from entrance (real-time override optional) ----
        if real_time_dists:
            # runtime reassign case: we already ran Dijkstra from current nearest node
            drive_time = float("inf")
            for ap in s.get("access", []):
                d = float(real_time_dists.get(ap["node"], float("inf")))
                if d < drive_time:
                    drive_time = d
            if drive_time == float("inf"):
                continue
        else:
            drive_time = float(s.get("drive_time", {}).get(entrance_id, float("inf")))
            if drive_time == float("inf"):
                continue

        # ---- Load ----
        load = 0
        if target_info:
            load = int(load_by_target.get(target_info.get("id", ""), 0))

        candidates.append({
            "spot": s,
            "target_cost": target_cost,
            "drive_time": drive_time,
            "load": load,
            "target_info": target_info,
        })

    if not candidates:
        return None

    # ============================================================
    # ELEVATOR logic — four-step distance-first + floor-aware algorithm
    # See module docstring for full explanation of each step.
    # ============================================================
    if is_elevator:
        # ── Resolve per-subtype window and EPS ──────────────────────────────
        eps_map    = p.get("floor_walk_eps_by_subtype", {})
        window_map = p.get("distance_window_by_subtype", {})

        if is_group:
            _fallback      = min(eps_map.values()) if eps_map else FLOOR_EPS_FALLBACK
            floor_eps      = eps_map.get(group_key, _fallback)
            subtype_window = window_map.get(group_key, DISTANCE_WINDOW_M)
        elif is_specific_target:
            subtype_key    = target_type[len("elevator_"):]
            _fallback      = min(eps_map.values()) if eps_map else FLOOR_EPS_FALLBACK
            floor_eps      = eps_map.get(subtype_key, _fallback)
            subtype_window = window_map.get(subtype_key, DISTANCE_WINDOW_M)
        else:
            _fallback      = min(eps_map.values()) if eps_map else FLOOR_EPS_FALLBACK
            floor_eps      = _fallback
            subtype_window = DISTANCE_WINDOW_M

        min_target_cost = min(c["target_cost"] for c in candidates)

        # ── Step 1: Candidate window (per-subtype) ───────────────────────────
        good = [c for c in candidates if c["target_cost"] <= min_target_cost + subtype_window]
        if not good:
            good = candidates[:1]

        # ── Step 2: Floor filter ─────────────────────────────────────────────
        # Restrict pool to the lowest floor F where
        #   min_walk[F] <= min_walk[higher floors] + floor_eps
        # Because floor_eps == subtype_window, F0 stays preferred as long as
        # any F0 spot remains inside the candidate window.
        floors_in_pool = sorted(set(int(c["spot"].get("floor", 0)) for c in good))
        for preferred_floor in floors_in_pool:
            min_walk_pref = min(
                c["target_cost"] for c in good
                if int(c["spot"].get("floor", 0)) == preferred_floor
            )
            min_walk_higher = min(
                (c["target_cost"] for c in good
                 if int(c["spot"].get("floor", 0)) > preferred_floor),
                default=float("inf"),
            )
            if min_walk_pref <= min_walk_higher + floor_eps:
                filtered = [c for c in good
                            if int(c["spot"].get("floor", 0)) == preferred_floor]
                if filtered:
                    good = filtered
                break
        # If no floor passes, all floors remain in the pool.

        # ── Step 3: Distance-first sort, drive-time as same-row tie-breaker ──
        # Primary: target_cost ASC (closest to elevator wins).
        # Secondary: drive_time ASC (among equal-walk spots, faster drive wins).
        # No cross-row drive-time switching: drivers expect concentric-ring order.
        good.sort(key=lambda c: (c["target_cost"], c["drive_time"]))
        current = good[0]

        # ── Step 4: Close-bucket tie-break ───────────────────────────────────
        close_bucket = [c for c in good
                        if abs(c["target_cost"] - current["target_cost"]) <= DIST_EQUAL_EPS_M]

        # Floor first (safety net), then drive_time
        close_bucket.sort(key=lambda c: (int(c["spot"].get("floor", 0)), c["drive_time"]))
        best = close_bucket[0]

        # Geometric tie-break when drive times are also almost equal
        if abs(best["drive_time"] - current["drive_time"]) <= TIME_EQUAL_EPS_S:
            close_time = [c for c in close_bucket
                          if abs(c["drive_time"] - best["drive_time"]) <= TIME_EQUAL_EPS_S]
            close_time.sort(key=lambda c: (
                _tie_key_for_close_candidates(c, entrance_id),
                c["spot"]["id"],
            ))
            best = close_time[0]

    # ============================================================
    # EXIT logic — euclidean proximity sort with F0 preference
    # See module docstring for rationale.
    # ============================================================
    else:
        # Primary:   floor ASC (F0 before F1 — exit_cost via reverse-Dijkstra
        #            already includes ramp penalty so F1 spots are naturally
        #            further in drive-to-exit; but euclidean doesn't encode
        #            floor, so we enforce F0 preference explicitly).
        # Secondary: target_cost ASC = euclidean distance to exit node.
        # Tertiary:  congestion load (spread vehicles across aisles).
        # Quaternary: drive_time ASC as final tie-breaker.
        candidates.sort(key=lambda c: (
            int(c["spot"].get("floor", 0)),
            c["target_cost"],
            c["load"],
            c["drive_time"],
        ))
        best = candidates[0]

    if not best:
        return None

    spot = best["spot"]
    if best.get("target_info"):
        spot["_chosen_target"] = best["target_info"]
    return spot