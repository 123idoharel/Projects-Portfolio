"""
floor_selection.py — Canonical Spot Selection Algorithm v8
===========================================================

Used by:
  • /api/assign_direct  — real driver path (automatic floor selection)
  • assign_and_build_route — simulation / autonomous vehicles

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 1 — ZONE SEARCH  (current floor)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Start on the lowest eligible floor (F0, or committed_floor).

  Single instance per floor:
    best = argmin walk(spot, elevator)  among eligible FREE spots
    if walk(best) ≤ INITIAL_ZONE_RADIUS → ASSIGN immediately (stop)

  Multiple instances per floor (spiral):
    Run spiral from BASE_SPIRAL_RADIUS up to INITIAL_ZONE_RADIUS,
    checking inst-1 first (closest drive-time from entrance), then inst-2.
    First spot found within expanding ring → ASSIGN immediately (stop)

If the zone is exhausted (no eligible spot within INITIAL_ZONE_RADIUS),
→ open FLOOR COMPETITION.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 2 — FLOOR COMPETITION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Two sources of candidates compete:

  Current floor:   ALL remaining eligible FREE spots on this floor
                   each paired with their nearest elevator instance.

  Each later floor:
    Single instance  → 1 candidate: the closest eligible spot to that elevator.
    Multiple instances → 1 candidate PER instance: the closest eligible spot
                         to each elevator instance on that floor.

Score per candidate:
    score = drive_time(spot → entrance)
          + WALK_WEIGHT × walk(spot → elevator)
          + floor_depth × floor_penalty_per_level

    floor_depth = 0 for current floor, 1 for next floor, etc.
    floor_penalty_per_level = ramp_one_way_time × floor_penalty_frac (settings.json)

Lowest score wins. The winner's floor becomes committed_floor permanently.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NO-RETURN GUARANTEE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Once a spot on floor N is assigned, committed_floor = N.
Floors below N are excluded from all future calls (initial or reassignment).
The vehicle's pending_floor field is also seeded so reassign_from_current
inherits the same commitment without any additional state machinery.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DISABLED SPOTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Spots with spot_type == 'disabled' are excluded unless has_disability=True.
Disabled spots are placed nearest each elevator, so they win the zone search
whenever has_disability=True and remain available.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REASSIGNMENT HELPERS  (unchanged from v7)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_select_best_spot_on_floor(...)       — used by reassign_from_current
_resolve_floor_options_base_radius()  — spiral base for reassignment

Public API
──────────
  resolve_initial_zone_radius(targets, spots) → (zone_r, base_r)
  select_spot_auto(target_type, entrance_id, offline, runtime,
                   has_disability, committed_floor)
                   → (spot, walk_m, target_id, assigned_floor)
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from core.config import CFG

_SPIRAL_BASE_FRAC_MULTI  = float(CFG["offline"]["spiral_base_radius_frac_multi"])
_SPIRAL_BASE_PCT_SINGLE  = float(CFG["offline"]["spiral_base_radius_pct_single"])
_SPIRAL_EXPANSION        = float(CFG["offline"]["spiral_expansion_factor"])
_WALK_TOLERANCE_FRAC     = float(CFG["offline"]["walk_tolerance_frac"])
_ZONE_FRAC_MULTI         = float(CFG["offline"]["zone_radius_frac_multi"])
_ZONE_PCT_SINGLE         = float(CFG["offline"]["zone_radius_pct_single"])
_FLOOR_COMP_WALK_WEIGHT  = float(CFG["offline"]["floor_competition_walk_weight"])
_FLOOR_PENALTY_FRAC      = float(CFG["offline"]["floor_penalty_frac"])
_COMP_RADIUS_GROWTH      = float(CFG["offline"]["comp_radius_growth_factor"])
_COMP_WALK_TOL_FRAC      = float(CFG["offline"]["comp_walk_tolerance_frac"])

ELEVATOR_TYPES = frozenset({"elevator", "escalator"})


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _edist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)


def _eff_sub(t: Dict) -> str:
    """Return the canonical group name for a target (target_group or subtype)."""
    return t.get("target_group") or t.get("subtype") or "default"


def _eligible(spot: Dict, has_disability: bool) -> bool:
    """True if spot may be assigned given the driver's disability badge status."""
    if spot.get("spot_type") == "disabled":
        return has_disability
    return True


def _approx_drive_to_target(
    target: Dict, nav_dist_from_entrance: Dict, driving_nodes: Dict
) -> float:
    """
    Approximate drive time from entrance to elevator target.
    Uses the nearest driving node on the same floor as a proxy.
    """
    tx, ty, tf = float(target["x"]), float(target["y"]), int(target.get("floor", 0))
    best = float("inf")
    for node_id, node in driving_nodes.items():
        if int(node.get("floor", 0)) == tf:
            d = nav_dist_from_entrance.get(node_id, float("inf"))
            if d < float("inf"):
                total = d + _edist(float(node["x"]), float(node["y"]), tx, ty) * 0.3
                if total < best:
                    best = total
    return best


def _drive_time_for_spot(
    spot: Dict, entrance_id: str, nav_dist_from_entrance: Dict
) -> float:
    """Drive time from entrance to spot via its closest access node."""
    best = float("inf")
    for access_point in spot.get("access", []):
        node_id = access_point.get("node")
        if node_id is not None:
            d = nav_dist_from_entrance.get(node_id, float("inf"))
            if d < best:
                best = d
    # Fallback to precomputed offline value if nav_dists doesn't cover this spot
    if best == float("inf"):
        best = float(spot.get("drive_time", {}).get(entrance_id, float("inf")))
    return best


# ─────────────────────────────────────────────────────────────────────────────
# Zone radius computation
# ─────────────────────────────────────────────────────────────────────────────

def resolve_initial_zone_radius(
    all_targets_for_group: List[Dict],
    spots: List[Dict],
) -> Tuple[float, float]:
    """
    Compute (INITIAL_ZONE_RADIUS, BASE_SPIRAL_RADIUS) from layout geometry.

    INITIAL_ZONE_RADIUS — maximum walk distance accepted on the current floor
    before floor competition is triggered. Derived from physical inter-instance
    distance (multi) or percentile of F0 walk distances (single).

    BASE_SPIRAL_RADIUS — starting ring for the Phase 1 spiral (multi only).

    Returns (zone_radius, spiral_base_radius).
    """
    # Compute minimum distance between any two instances on the same floor
    per_floor: Dict[int, List] = {}
    for t in all_targets_for_group:
        per_floor.setdefault(int(t.get("floor", 0)), []).append(t)

    min_inter_instance_dist = float("inf")
    for inst_list in per_floor.values():
        for i, ta in enumerate(inst_list):
            for tb in inst_list[i + 1:]:
                d = _edist(float(ta["x"]), float(ta["y"]), float(tb["x"]), float(tb["y"]))
                if d < min_inter_instance_dist:
                    min_inter_instance_dist = d

    if min_inter_instance_dist < float("inf"):
        # Multi-instance: radii are fractions of half the inter-instance distance
        half = min_inter_instance_dist / 2.0
        zone_radius        = half * _ZONE_FRAC_MULTI
        spiral_base_radius = min_inter_instance_dist * _SPIRAL_BASE_FRAC_MULTI
        return zone_radius, spiral_base_radius

    # Single-instance: derive from sorted walk distances to F0 elevator
    if all_targets_for_group:
        sample_target = all_targets_for_group[0]
        f0 = int(sample_target.get("floor", 0))
        walk_dists = sorted(
            _edist(float(s["x"]), float(s["y"]),
                   float(sample_target["x"]), float(sample_target["y"]))
            for s in spots if s.get("floor") == f0
        )
        if walk_dists:
            zone_idx = max(0, int(len(walk_dists) * _ZONE_PCT_SINGLE) - 1)
            base_idx = max(0, int(len(walk_dists) * _SPIRAL_BASE_PCT_SINGLE) - 1)
            return walk_dists[zone_idx], walk_dists[base_idx] * 2.0

    return 80.0, 40.0


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _has_multiple_instances_per_floor(all_targets: List[Dict]) -> bool:
    """True if any floor has ≥ 2 elevator instances for this target group."""
    count_per_floor: Dict[int, int] = {}
    for t in all_targets:
        fl = int(t.get("floor", 0))
        count_per_floor[fl] = count_per_floor.get(fl, 0) + 1
    return any(v >= 2 for v in count_per_floor.values())


def _spiral_within_zone(
    eligible_free_spots: List[Dict],
    floor_targets: List[Dict],
    zone_radius: float,
    spiral_base_radius: float,
    nav_dist_from_entrance: Dict,
    driving_nodes: Dict,
) -> Optional[Tuple[Dict, float, str]]:
    """
    Run the spiral from spiral_base_radius up to zone_radius.

    Instances are tried in drive-time order (inst-1 first = closest to entrance).
    Returns (spot, walk_m, target_id) when a spot is found, else None.

    Instance switching uses the same WALK_TOLERANCE guard as reassignment Step 1:
    inst-k wins only if its walk is within the ring AND saves at least
    k × walk_tolerance metres compared to inst-1's best walk. This is the same
    hysteresis that prevents constant switching near the midpoint.
    Tuned by walk_tolerance_frac in settings.json:
      0.0 → any ring-member wins immediately (most symmetric)
      0.20 → inst-2 must save 20% of zone_radius to win (default — some stickiness to inst-1)
    """
    targets_by_drive_time = sorted(
        floor_targets,
        key=lambda t: _approx_drive_to_target(t, nav_dist_from_entrance, driving_nodes),
    )
    walk_tolerance = zone_radius * _WALK_TOLERANCE_FRAC

    radius = spiral_base_radius
    while radius <= zone_radius * 1.001:
        # Inst-1's closest walk at this moment — used as baseline for switching guard
        t0 = targets_by_drive_time[0]
        t0x, t0y = float(t0["x"]), float(t0["y"])
        inst1_closest = min(
            eligible_free_spots,
            key=lambda s: _edist(float(s["x"]), float(s["y"]), t0x, t0y),
            default=None,
        )
        inst1_walk = (
            _edist(float(inst1_closest["x"]), float(inst1_closest["y"]), t0x, t0y)
            if inst1_closest else float("inf")
        )

        for k, target in enumerate(targets_by_drive_time):
            tx, ty = float(target["x"]), float(target["y"])
            closest = min(
                eligible_free_spots,
                key=lambda s: _edist(float(s["x"]), float(s["y"]), tx, ty),
                default=None,
            )
            if closest is None:
                continue
            walk = _edist(float(closest["x"]), float(closest["y"]), tx, ty)
            # Qualifies when: within ring AND saves k×tolerance vs inst-1
            # For k=0 (inst-1 itself): condition reduces to walk <= radius (always wins)
            if walk <= radius and walk <= inst1_walk - k * walk_tolerance:
                return closest, walk, target["id"]
        if radius >= zone_radius:
            break
        radius = min(radius * _SPIRAL_EXPANSION, zone_radius)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_within_cap(
    eligible_free_spots: List[Dict],
    floor_targets: List[Dict],
    nav_dist_from_entrance: Dict,
    driving_nodes: Dict,
    is_multi: bool,
    cap: float,
    spiral_base_radius: float,
) -> Optional[Tuple[Dict, float, str]]:
    """
    Try to find a single spot within the cap radius on one floor.

    Single instance:
        Returns (spot, walk, tid) for the closest spot to the elevator,
        provided walk ≤ cap. Tiebreak: drive_time from entrance.

    Multi-instance:
        Runs the same spiral as Phase 1, bounded by cap and using
        comp_walk_tolerance_frac (lower = more symmetric instance switching).
        Returns the first spot found within the spiral, or None.

    Returns None if no eligible spot is within cap on this floor.
    """
    if not eligible_free_spots or not floor_targets:
        return None

    if not is_multi or len(floor_targets) == 1:
        t = floor_targets[0]
        tx, ty = float(t["x"]), float(t["y"])
        # Closest spot; tiebreak on drive_time
        best = min(
            eligible_free_spots,
            key=lambda s: (
                _edist(float(s["x"]), float(s["y"]), tx, ty),
                _drive_time_for_spot(s, None, nav_dist_from_entrance),
            ),
        )
        walk = _edist(float(best["x"]), float(best["y"]), tx, ty)
        return (best, walk, t["id"]) if walk <= cap else None

    # Multi-instance spiral up to cap
    targets_sorted = sorted(
        floor_targets,
        key=lambda t: _approx_drive_to_target(t, nav_dist_from_entrance, driving_nodes),
    )
    walk_tolerance = cap * _COMP_WALK_TOL_FRAC

    radius = spiral_base_radius
    while radius <= cap * 1.001:
        t0 = targets_sorted[0]
        t0x, t0y = float(t0["x"]), float(t0["y"])
        inst1_closest = min(
            eligible_free_spots,
            key=lambda s: _edist(float(s["x"]), float(s["y"]), t0x, t0y),
            default=None,
        )
        inst1_walk = (
            _edist(float(inst1_closest["x"]), float(inst1_closest["y"]), t0x, t0y)
            if inst1_closest else float("inf")
        )
        for k, target in enumerate(targets_sorted):
            tx, ty = float(target["x"]), float(target["y"])
            closest = min(
                eligible_free_spots,
                key=lambda s: _edist(float(s["x"]), float(s["y"]), tx, ty),
                default=None,
            )
            if closest is None:
                continue
            walk = _edist(float(closest["x"]), float(closest["y"]), tx, ty)
            if walk <= radius and walk <= inst1_walk - k * walk_tolerance and walk <= cap:
                return (closest, walk, target["id"])
        if radius >= cap:
            break
        radius = min(radius * _SPIRAL_EXPANSION, cap)
    return None


def _absolute_best_per_instance(
    eligible_free_spots: List[Dict],
    floor_targets: List[Dict],
    nav_dist_from_entrance: Dict,
) -> List[Tuple[Dict, float, str]]:
    """
    Fallback: one candidate per elevator instance — the closest spot to each
    instance (no cap restriction). Tiebreak: drive_time from entrance.

    Used when a floor has no spot within its cap radius. The floor still
    contributes to the competition pool; its candidates just come from the
    absolute closest spots rather than the capped spiral.
    """
    result = []
    for t in floor_targets:
        tx, ty = float(t["x"]), float(t["y"])
        best = min(
            eligible_free_spots,
            key=lambda s: (
                _edist(float(s["x"]), float(s["y"]), tx, ty),
                _drive_time_for_spot(s, None, nav_dist_from_entrance),
            ),
            default=None,
        )
        if best is None:
            continue
        walk = _edist(float(best["x"]), float(best["y"]), tx, ty)
        result.append((best, walk, t["id"]))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main auto-assignment entry point
# ─────────────────────────────────────────────────────────────────────────────

def select_spot_auto(
    target_type: str,
    entrance_id: str,
    offline: Dict[str, Any],
    runtime: Dict[str, Any],
    has_disability: bool = False,
    committed_floor: Optional[int] = None,
) -> Tuple[Optional[Dict], float, Optional[str], Optional[int]]:
    """
    Automatically select the best spot across all floors. No user floor input.

    Parameters
    ----------
    target_type     : elevator group name, e.g. 'mall_elevator', 'office_a',
                      or prefixed form 'elevator_mall_elevator' (stripped internally)
    entrance_id     : entrance node ID (driving graph)
    offline         : offline data (targets, driving_nodes, nav_dists, spots, ...)
    runtime         : live state (spots with current statuses, vehicles)
    has_disability  : when True, spots with spot_type='disabled' are eligible
    committed_floor : floors strictly below this value are excluded permanently
                      (no-return guarantee — pass vehicle's committed_floor here)

    Returns
    -------
    (spot, walk_m, chosen_target_id, assigned_floor)
    Returns (None, inf, None, None) when no spot is available.
    """
    spots             = runtime["spots"]
    targets           = offline["targets"]
    driving_nodes     = offline["driving_nodes"]
    nav_dist_from_ent = offline.get("nav_dists", {}).get(entrance_id, {})

    # ── Resolve target group name ─────────────────────────────────────────────
    group_name = target_type
    for prefix in ("elevator_group_", "elevator_inst_", "elevator_"):
        if group_name.startswith(prefix):
            group_name = group_name[len(prefix):]
            break

    if target_type.startswith("elevator_inst_"):
        inst_id = target_type[len("elevator_inst_"):]
        t_obj = next((t for t in targets if t.get("id") == inst_id), None)
        if t_obj:
            group_name = _eff_sub(t_obj)

    group_targets = [
        t for t in targets
        if t.get("type") in ELEVATOR_TYPES and _eff_sub(t) == group_name
    ]
    if not group_targets:
        return None, float("inf"), None, None

    zone_radius, spiral_base = resolve_initial_zone_radius(group_targets, spots)
    is_multi = _has_multiple_instances_per_floor(group_targets)

    all_floors = sorted({int(t.get("floor", 0)) for t in group_targets})

    # Apply no-return commitment
    min_floor       = committed_floor if committed_floor is not None else all_floors[0]
    eligible_floors = [f for f in all_floors if f >= min_floor]
    if not eligible_floors:
        return None, float("inf"), None, None

    # ── Phase 1: zone search on the first floor with eligible free spots ──────
    zone_exhausted_floor: Optional[int] = None

    for floor in eligible_floors:
        free_on_floor = [
            s for s in spots
            if int(s.get("floor", 0)) == floor
            and s.get("status") == "FREE"
            and _eligible(s, has_disability)
        ]
        if not free_on_floor:
            continue  # floor empty — proceed to next

        floor_targets = [
            t for t in group_targets if int(t.get("floor", 0)) == floor
        ]
        if not floor_targets:
            continue

        if is_multi:
            result = _spiral_within_zone(
                free_on_floor, floor_targets,
                zone_radius, spiral_base,
                nav_dist_from_ent, driving_nodes,
            )
            if result is not None:
                spot, walk, target_id = result
                return spot, walk, target_id, floor
        else:
            t = floor_targets[0]
            tx, ty = float(t["x"]), float(t["y"])
            # Primary key: walk distance. Tiebreak: drive_time from entrance.
            best = min(
                free_on_floor,
                key=lambda s: (
                    _edist(float(s["x"]), float(s["y"]), tx, ty),
                    _drive_time_for_spot(s, entrance_id, nav_dist_from_ent),
                ),
            )
            walk = _edist(float(best["x"]), float(best["y"]), tx, ty)
            if walk <= zone_radius:
                return best, walk, t["id"], floor

        # Zone exhausted on this floor — record it and move to competition
        zone_exhausted_floor = floor
        break

    if zone_exhausted_floor is None:
        # No floor had any eligible free spots at all
        return None, float("inf"), None, None

    # ── Phase 2: floor competition ────────────────────────────────────────────
    # Current floor (zone exhausted): ALL remaining eligible spots, each paired
    # with their nearest elevator instance on this floor.
    # Each later floor: one candidate per elevator instance on that floor.
    #
    # Score formula:
    #   score = drive_time(entrance→spot)
    #         + FLOOR_COMP_WALK_WEIGHT × walk(spot→elevator)
    #         + floor_depth × floor_penalty_per_level
    #
    # floor_depth = floor - zone_exhausted_floor (0 for current floor).
    # floor_penalty_per_level = ramp_one_way_time × floor_penalty_frac.
    # The penalty is applied ONLY to subsequent floors (floor_depth > 0).
    # It gently discourages ascending extra floors when a good current-floor
    # spot is available, without overriding the drive_time + walk signal.

    sp_params              = offline.get("scoring_params", {})
    floor_penalty_per_lvl  = float(sp_params.get("floor_penalty_per_level") or 0.0)

    best_score  = float("inf")
    best_result: Tuple[Optional[Dict], float, Optional[str], Optional[int]] = (
        None, float("inf"), None, None
    )

    def _competition_score(spot: Dict, walk: float, floor_depth: int = 0) -> float:
        drive_t = _drive_time_for_spot(spot, entrance_id, nav_dist_from_ent)
        return (drive_t
                + _FLOOR_COMP_WALK_WEIGHT * walk
                + floor_depth * floor_penalty_per_lvl)

    # Current floor — ALL remaining spots as candidates
    cur_free = [
        s for s in spots
        if int(s.get("floor", 0)) == zone_exhausted_floor
        and s.get("status") == "FREE"
        and _eligible(s, has_disability)
    ]
    cur_targets = [
        t for t in group_targets
        if int(t.get("floor", 0)) == zone_exhausted_floor
    ]
    for spot in cur_free:
        if cur_targets:
            # Pair each spot with its nearest target on this floor
            nearest_target = min(
                cur_targets,
                key=lambda t: _edist(
                    float(spot["x"]), float(spot["y"]),
                    float(t["x"]), float(t["y"]),
                ),
            )
            walk = _edist(
                float(spot["x"]), float(spot["y"]),
                float(nearest_target["x"]), float(nearest_target["y"]),
            )
            target_id = nearest_target["id"]
        else:
            walk, target_id = float("inf"), None

        score = _competition_score(spot, walk)
        if score < best_score:
            best_score  = score
            best_result = (spot, walk, target_id, zone_exhausted_floor)

    # Later floors — capped zone logic with graceful fallback.
    #
    # For each subsequent floor (ascending depth 1, 2, 3, …):
    #
    #   cap(depth) = zone_radius × comp_radius_growth_factor^depth
    #     depth=1 (next floor):   cap = zone_radius × 1.3
    #     depth=2 (two above):    cap = zone_radius × 1.69
    #     depth=3 (three above):  cap = zone_radius × 2.20  etc.
    #
    #   Step A — try cap:
    #     Single: closest spot within cap (tiebreak: drive_time from entrance).
    #     Multi:  spiral from spiral_base up to cap (comp_walk_tolerance_frac
    #             for more symmetric instance switching).
    #
    #   If Step A succeeds (spot within cap found):
    #     → This spot is the floor's candidate. Mark this floor as "found".
    #       STOP scanning deeper floors — no need to look further.
    #
    #   If Step A fails (no spot within cap):
    #     → Fallback: take absolute closest per instance (no cap, tiebreak drive_time).
    #       These fallback candidates enter the competition pool but do NOT
    #       stop the scan — continue to the next floor.
    #
    # All collected candidates (capped winner + uncapped fallbacks) compete
    # simultaneously by score. The highest-scoring one wins regardless of origin.
    #
    # Effect: the competition naturally prefers the nearest floor where a spot
    # is within the cap. Deeper floors with only far spots can still win, but
    # only if their score (drive_time + walk + floor_penalty) beats everything
    # else in the pool.

    for floor in eligible_floors:
        if floor <= zone_exhausted_floor:
            continue
        free_on_floor = [
            s for s in spots
            if int(s.get("floor", 0)) == floor
            and s.get("status") == "FREE"
            and _eligible(s, has_disability)
        ]
        if not free_on_floor:
            continue
        floor_targets = [
            t for t in group_targets if int(t.get("floor", 0)) == floor
        ]
        if not floor_targets:
            continue

        floor_depth = floor - zone_exhausted_floor  # 1 for next floor, 2 for two up…
        # Cap grows from the first subsequent floor:
        # depth=1 (next floor):   cap = zone_radius × growth^1
        # depth=2 (two above):    cap = zone_radius × growth^2
        # depth=3 (three above):  cap = zone_radius × growth^3
        cap = zone_radius * (_COMP_RADIUS_GROWTH ** floor_depth)

        # Step A: try to find a spot within this floor's cap
        capped = _find_within_cap(
            free_on_floor, floor_targets,
            nav_dist_from_ent, driving_nodes, is_multi,
            cap, spiral_base,
        )

        if capped is not None:
            # Found a spot within cap — this is the floor's representative.
            spot, walk, target_id = capped
            score = _competition_score(spot, walk, floor_depth)
            if score < best_score:
                best_score  = score
                best_result = (spot, walk, target_id, floor)
            # Cap found on this floor → stop scanning deeper floors
            break

        # Step A failed — no spot within cap on this floor.
        # Take absolute closest per instance as fallback candidates.
        for spot, walk, target_id in _absolute_best_per_instance(
            free_on_floor, floor_targets, nav_dist_from_ent,
        ):
            score = _competition_score(spot, walk, floor_depth)
            if score < best_score:
                best_score  = score
                best_result = (spot, walk, target_id, floor)
        # Continue scanning deeper floors (no break)

    return best_result


# ─────────────────────────────────────────────────────────────────────────────
# Reassignment helpers — used by reassign_from_current in simulation.py
# Unchanged from v7; not involved in the initial assignment flow.
# ─────────────────────────────────────────────────────────────────────────────

def _select_best_spot_on_floor(
    floor: int,
    free_on_floor: List[Dict],
    floor_targets: List[Dict],
    entrance_id: str,
    nav_dist_from_entrance: Dict,
    driving_nodes: Dict,
    spiral_base_radius: float,
) -> Tuple[Optional[Dict], float, Optional[str]]:
    """
    Select the best FREE spot on one floor for the reassignment algorithm.

    Single target  → closest walk, drive_time tiebreak.
    Multiple targets → spiral expansion from spiral_base_radius.
    Fallback: absolute closest to any target.

    Returns (spot, walk_m, target_id) or (None, inf, None).
    """
    if not free_on_floor or not floor_targets:
        return None, float("inf"), None

    if len(floor_targets) == 1:
        t = floor_targets[0]
        tx, ty = float(t["x"]), float(t["y"])
        scored = sorted(
            (
                _edist(float(s["x"]), float(s["y"]), tx, ty),
                float(s.get("drive_time", {}).get(entrance_id, float("inf"))),
                s["id"],
                s,
            )
            for s in free_on_floor
        )
        if scored:
            walk, _, _, spot = scored[0]
            return spot, walk, t["id"]
        return None, float("inf"), None

    # Multiple targets — spiral
    targets_sorted = sorted(
        floor_targets,
        key=lambda t: _approx_drive_to_target(t, nav_dist_from_entrance, driving_nodes),
    )
    fl_xs = [float(s["x"]) for s in free_on_floor]
    fl_ys = [float(s["y"]) for s in free_on_floor]
    floor_diag = (
        math.sqrt((max(fl_xs) - min(fl_xs)) ** 2 + (max(fl_ys) - min(fl_ys)) ** 2)
        if len(free_on_floor) > 1 else spiral_base_radius
    )

    best_spot, best_walk, best_tid = None, float("inf"), None
    found = False
    radius = spiral_base_radius
    while radius <= floor_diag * 1.001:
        for t in targets_sorted:
            tx, ty = float(t["x"]), float(t["y"])
            closest = min(
                free_on_floor,
                key=lambda s: _edist(float(s["x"]), float(s["y"]), tx, ty),
                default=None,
            )
            if closest is None:
                continue
            walk = _edist(float(closest["x"]), float(closest["y"]), tx, ty)
            if walk <= radius:
                best_spot, best_walk, best_tid = closest, walk, t["id"]
                found = True
                break
        if found:
            break
        radius *= _SPIRAL_EXPANSION

    if not found:
        for t in targets_sorted:
            tx, ty = float(t["x"]), float(t["y"])
            closest = min(
                free_on_floor,
                key=lambda s: _edist(float(s["x"]), float(s["y"]), tx, ty),
                default=None,
            )
            if closest is not None:
                walk = _edist(float(closest["x"]), float(closest["y"]), tx, ty)
                if walk < best_walk:
                    best_walk, best_spot, best_tid = walk, closest, t["id"]

    return best_spot, best_walk, best_tid


def _resolve_floor_options_base_radius(
    all_targets_on_any_floor: List[Dict],
    spots: List[Dict],
) -> float:
    """
    Compute BASE_SPIRAL_RADIUS for the reassignment spiral.
    Used by /api/floor_options (operator view) and reassign_from_current.
    Identical logic to resolve_initial_zone_radius's spiral_base component.
    """
    per_floor: Dict[int, List] = {}
    for t in all_targets_on_any_floor:
        per_floor.setdefault(int(t.get("floor", 0)), []).append(t)

    min_inter = float("inf")
    for inst_list in per_floor.values():
        for i, ta in enumerate(inst_list):
            for tb in inst_list[i + 1:]:
                d = _edist(
                    float(ta["x"]), float(ta["y"]),
                    float(tb["x"]), float(tb["y"]),
                )
                if d < min_inter:
                    min_inter = d

    if min_inter < float("inf"):
        return min_inter * _SPIRAL_BASE_FRAC_MULTI

    if all_targets_on_any_floor:
        sample = all_targets_on_any_floor[0]
        f0 = int(sample.get("floor", 0))
        dists = sorted(
            _edist(float(s["x"]), float(s["y"]), float(sample["x"]), float(sample["y"]))
            for s in spots if s.get("floor") == f0
        )
        if dists:
            idx = max(0, int(len(dists) * _SPIRAL_BASE_PCT_SINGLE) - 1)
            return dists[idx] * 2.0

    return 40.0
