# Smart Parking — Algorithm Reference

Covers the two algorithms that decide where a car parks:

| Algorithm | Entry point | File |
|---|---|---|
| **Initial assignment** | `select_spot_auto()` | `core/floor_selection.py` |
| **Reassignment** (spot stolen mid-drive) | `reassign_from_current()` | `core/simulation.py` |

Both consume geometry parameters computed at startup by `core/offline.py` and
tunables from `core/settings.json`.

> **Scope note.** Every algorithm *tuning* value lives in `settings.json`. A few
> physical constants are hardcoded on purpose because they describe the world
> rather than the policy: `WALK_SPEED_MPS = 1.2` and `SPOT_CONNECT_RADIUS = 30.0`
> in `core/pedestrian.py`, the sensor debounce thresholds in
> `core/adapters/sensor_adapter.py`, `TURN_THRESHOLD = 8.0` in `server.py`, and
> the interpolation alphas in the frontend.

---

## Concepts

| Term | Meaning |
|---|---|
| **target_group** | The destination the driver selects — `mall_elevator`, `office_a`, `office_b`, … Resolved from a target's `target_group`, falling back to `subtype`, falling back to `"default"`. Fixed at entry, never changed. |
| **target_instance** | One physical elevator/escalator shaft at a specific (x, y, floor). A group may have 1 or 2+ instances per floor. |
| **inst-1** | The instance with the shortest approximate drive time from the entrance on that floor. Checked first in every spiral. |
| **single-instance** | A group with exactly one instance per floor (typical for office targets). |
| **multi-instance** | A group with two or more instances on **at least one** floor (typical for mall elevators). Determined by `_has_multiple_instances_per_floor()` and applied to the whole group. |
| **zone_radius** | Maximum walk distance accepted on the current floor before floor competition opens. |
| **floor_depth** | `floor − zone_exhausted_floor`. 0 for the current floor, 1 for the next, etc. |
| **eligible spot** | `status == "FREE"` and (`spot_type != "disabled"` or `has_disability=True`). |
| **visited_floors** | Floors fully exhausted during reassignment (append-only, never cleared). Reassignment state, on the vehicle. |
| **pending_floor** | A floor reassignment committed to but the vehicle has not physically reached yet. Cleared on arrival. |
| **intended_floor** | The floor reassignment Step 1 searches. See the resolution rules in Part 2. |
| **committed_floor** | An **optional parameter** of `select_spot_auto()`: floors strictly below it are excluded. See the note under Phase 2. |

---

## Geometry Parameters

Two different functions produce geometry, and they are easy to confuse.

### A. Per-request, in `floor_selection.resolve_initial_zone_radius()`

Called on **every** initial assignment, for the requested target group only:

```
min_inter_dist = min Euclidean distance between two instances of THIS group
                 on the SAME floor (over all floors)

If such a pair exists  (multi-instance):
    half               = min_inter_dist / 2
    zone_radius        = half           × zone_radius_frac_multi         (0.90)
    spiral_base_radius = min_inter_dist × spiral_base_radius_frac_multi  (0.30)

Else (single-instance): take the first target of the group on its floor,
    walk_dists = sorted Euclidean distances from every spot on that floor
                 to that target
    zone_idx   = max(0, int(n × zone_radius_pct_single) − 1)          (p50)
    base_idx   = max(0, int(n × spiral_base_radius_pct_single) − 1)   (p5)
    zone_radius        = walk_dists[zone_idx]
    spiral_base_radius = walk_dists[base_idx] × 2

Absolute fallback (no targets): (80.0, 40.0)
```

Note that `walk_dists` here is built from **all** spots on the floor, not only
free ones, so `zone_radius` is stable regardless of occupancy.

### B. At startup, in `offline.compute_offline()` / `compute_scoring_params()`

Stored in `offline["scoring_params"]` and consumed mainly by **reassignment**
and by the legacy `scoring.py` fallback:

```
local_target_radius     = half × local_radius_frac_multi   (0.40)   [multi]
                        = walk_dists[int(n × 0.30)]                 [single]
target_zone_radius      = half × zone_radius_frac_multi    (0.90)   [multi]
                        = walk_dists[int(n × 0.50)]                 [single]
walk_tolerance          = target_zone_radius × walk_tolerance_frac  (0.15)
floor_change_penalty    = one_way_ramp_traversal_time × floor_change_penalty_frac (0.50)
floor_penalty_per_level = floor_change_penalty × floor_penalty_frac (0.50)
floor_diagonal          = Euclidean diagonal of the floor bounding box
distance_window_by_subtype[sub] = floor_walk_eps_by_subtype[sub]
                        = walk[row_N] − walk[row_0], N = n_rows (4)
time_save_min_s         = 999999.0   ← cross-row drive-time switching disabled
```

There is **no** `zone_radius` or `spiral_base` key in `scoring_params`. The keys
are `target_zone_radius` and `local_target_radius`. Measured on the default
layout (`azrieli_mall_large`): `target_zone_radius = 100.3`,
`local_target_radius = 44.6`, `walk_tolerance = 15.1`,
`floor_change_penalty = 15.0`, `floor_penalty_per_level = 7.5`,
`floor_diagonal = 603.4`.

---

## Part 1 — Initial Assignment

Entry: `POST /api/assign_direct` → `assign_and_build_route()` →
`select_spot_auto()` in `core/floor_selection.py`.

Simulation vehicles spawned via `POST /api/spawn` take the same path, so the
operator view is a faithful mirror of real driver behaviour.

**Accessibility.** Spots with `spot_type == "disabled"` are excluded from every
candidate pool unless `has_disability=True`. Because disabled spots are placed
nearest each elevator in the shipped layouts, they win the zone search
immediately whenever a badge is declared and one is still free.

### Phase 1 — Zone Search

Iterate eligible floors ascending (`floor >= committed_floor` if one was
passed, else from the lowest floor with elevators of this group). Skip any
floor with **no eligible free spots at all** — that floor never becomes the
zone-exhausted floor. Stop at the first floor that has eligible spots.

**Single-instance:**
```
best = argmin (walk(spot, elevator), drive_time(entrance → spot))
       over eligible FREE spots on this floor
if walk(best) ≤ zone_radius → ASSIGN, done
else → zone exhausted on this floor, open Phase 2
```

**Multi-instance (spiral):**
```
walk_tolerance = zone_radius × walk_tolerance_frac
sort instances on this floor by approximate drive time from entrance (inst-1 first)

radius = spiral_base_radius
while radius ≤ zone_radius × 1.001:
    inst1_walk = walk(closest eligible spot to inst-1, inst-1)
    for k, inst_k in enumerate(instances):
        walk_k = walk(closest eligible spot to inst_k, inst_k)
        if walk_k ≤ radius AND walk_k ≤ inst1_walk − k × walk_tolerance:
            → ASSIGN that spot, navigate to inst_k, done
    if radius ≥ zone_radius: break
    radius = min(radius × spiral_expansion_factor, zone_radius)

→ zone exhausted, open Phase 2
```

For `k = 0` the guard reduces to `walk ≤ radius`, so inst-1 always wins when it
has a spot inside the ring. `walk_tolerance` is the switching hysteresis:
inst-k only wins when it saves at least `k × walk_tolerance` metres of walk
compared with inst-1. Set `walk_tolerance_frac = 0.0` for fully symmetric
instance switching.

### Phase 2 — Floor Competition

Triggered when Phase 1 finds no eligible spot within `zone_radius` on the
starting floor. That floor is recorded as `zone_exhausted_floor`.

**Candidate set:**
- **Current (zone-exhausted) floor** — ALL remaining eligible FREE spots, each
  paired with its nearest instance on that floor.
- **Each subsequent floor** — one representative, chosen by the cap logic below.

**Score:**
```
score(spot, floor) = drive_time(entrance → spot)
                   + floor_competition_walk_weight × walk(spot → its instance)
                   + floor_depth × floor_penalty_per_level

floor_depth = floor − zone_exhausted_floor   (0 for the current floor)
```

`floor_penalty_per_level` gently discourages ascending. It equals one-way ramp
traversal time × `floor_penalty_frac`. On the default layout that is 7.5 s per
floor — noticeable across several floors, rarely decisive for one.

**Competition zone cap (subsequent floors only):**

```
cap(depth) = zone_radius × comp_radius_growth_factor ^ depth
  depth = 1 (next floor):  cap = zone_radius × 1.30
  depth = 2 (two above):   cap = zone_radius × 1.69
  depth = 3 (three above): cap = zone_radius × 2.20   …
```

For single-instance floors, the closest spot within the cap qualifies (drive
time as tie-break). For multi-instance floors, a spiral from
`spiral_base_radius` up to the cap selects one representative, using
`comp_walk_tolerance_frac` (0.1) instead of `walk_tolerance_frac` for more
symmetric instance switching.

- If a spot is found within the cap on a floor → that floor contributes its
  representative and **the scan stops** (deeper floors are not examined).
- If no spot is within the cap → fall back to the absolute closest spot per
  instance on that floor. Those candidates enter the pool **without** stopping
  the scan, so deeper floors can still compete.

Set `comp_radius_growth_factor = 9999` to disable the cap entirely.

Lowest score wins.

> **Implementation note on `committed_floor`.** `select_spot_auto()` accepts a
> `committed_floor` argument and honours it, but `assign_and_build_route()` in
> `core/simulation.py` deliberately does **not** pass it and does not store the
> winner's floor on the vehicle (see the comment at
> `simulation.py :: assign_and_build_route`). Initial assignment therefore has
> no persistent no-return commitment today. The no-return guarantee is enforced
> entirely by `visited_floors` and `pending_floor` during **reassignment**
> (Part 2). If you want the commitment to apply from the first assignment,
> store the returned floor on the vehicle and pass it back in.

---

## Part 2 — Reassignment

Entry point: `reassign_from_current()` in `core/simulation.py`. Called when a
reserved spot is taken by someone else — from the operator's `POST /api/steal`,
from an automatic theft event in the `סימולציה מלאה` scenario, or from a real
sensor reporting the spot occupied (`_on_sensor_change` in `server.py`).

Before the route is cleared, `_find_forward_node()` captures the node the
vehicle is already heading toward, so the new route continues forward instead
of U-turning.

### Resolving `intended_floor`

Priority order, highest first:

1. **`pending_floor`** is set and the vehicle has **not** arrived
   (`current_floor != pending_floor`) → `intended_floor = pending_floor`.
2. **`pending_floor`** is set and the vehicle **has** arrived → clear
   `pending_floor`, `intended_floor = current_floor`.
3. `original_target_floor` is not in `visited_floors` **and**
   `current_floor < original_target_floor` → `intended_floor =
   original_target_floor` (finish climbing to the floor the driver was
   originally sent to).
4. Otherwise → `intended_floor = current_floor`.

### Banned floors

A floor may never be assigned if either holds:

1. it is in `visited_floors` (append-only), or
2. `pending_floor` was set on entry and the floor is strictly below it.

These two conditions are the complete definition. Even Pass 3 below cannot
break them.

### Step 1 — Zone Search on `intended_floor`

Skipped entirely if `intended_floor` is banned.

The zone expands per completed floor change:
```
ZONE = target_zone_radius × floor_change_expansion ^ n
       where n = len(visited_floors)
```
At `n = 0` the zone equals the initial-assignment zone geometry. At `n = 1` it
is ×1.8 — the vehicle tries progressively harder to stay on each new floor it
reaches.

**Single-instance:**
```
if walk(closest eligible free spot, elevator) ≤ ZONE → ASSIGN, done
else → open Step 2
```

**Multi-instance (spiral, same structure as Phase 1):**
```
local_r = local_target_radius
while local_r ≤ ZONE:
    inst1_walk = walk(closest free spot, inst-1)
    for k, inst_k:
        walk_k = walk(closest free spot, inst_k)
        if walk_k ≤ local_r AND walk_k ≤ inst1_walk − k × walk_tolerance:
            → ASSIGN, done
    local_r = min(local_r × spiral_expansion_factor, ZONE)

fallback: closest spot to any instance within ZONE
```

Here `walk_tolerance` comes from `scoring_params` (already
`target_zone_radius × 0.15`), not recomputed from the expanded ZONE.

### Step 2 — Global Score (zone exhausted on floor E)

`E = intended_floor`. Append E to `visited_floors` (permanent).

| Source | Spots contributed |
|---|---|
| Floor E | ALL free spots — present in **every** pass |
| Each other floor | One spot: minimum walk to the nearest instance, drive time as tie-break |

**Score:**
```
score(spot) = drive_time(vehicle current position → spot)
            + walk_weight × walk(spot → nearest instance on its floor)
            + max(0, spot_floor − E) × floor_penalty_per_level
```

`drive_time` is measured from the vehicle's **current position**, not the
entrance. Floors below E get `floor_depth = 0` — they are already implicitly
expensive through the drive time.

**Three passes**, stopping at the first that produces a winner. `banned_floors`
is subtracted from all three:
```
Pass 1: E + unvisited floors > E    (no regression, no revisit)
Pass 2: E + all floors ≥ E          (revisit ok, no regression)
Pass 3: E + all floors              (last resort — garage nearly full)
```

If the winner is on floor N ≠ E → `pending_floor = N`; the vehicle is committed
to N and E is locked forever. If the winner is on E → `pending_floor` is
cleared and the vehicle keeps filling E naturally.

### Step 3 — Legacy Fallback

`choose_best_spot()` from `core/scoring.py`, using the offline ranking tables.
Only reached when Steps 1 and 2 both come back empty.

---

## Parameter Reference

All parameters are in `core/settings.json`. Change them and restart the server.
If you change anything in the `offline` section you must also delete the
matching `data/offline_*.pkl`, because `scoring_params` is baked into the
cached pickle.

### `offline` — geometry, computed once at startup

| Parameter | Default | Effect |
|---|---|---|
| `driving_speed_mps.main` | 2.0 | Edge weight = `length_m / speed` on main roads. |
| `driving_speed_mps.aisle` | 1.5 | Same, for aisles. |
| `driving_speed_mps.ramp` | 1.0 | Same, for ramps. Also drives `floor_change_penalty`. |
| `spot_maneuver_sec_per_meter` | 0.6 | Extra cost for the last-metre approach into a spot. |
| `window_diagonal_factor` | 0.08 | Global candidate-window fallback = floor diagonal × this. |
| `window_min_m` / `window_max_m` | 20 / 100 | Clamps for that fallback. |
| `n_rows` | 4 | Walk-distance rows spanned by the per-subtype window and floor EPS. |
| `zone_radius_frac_multi` | 0.90 | Competition threshold — multi. **Raise** to stay on the current floor longer. |
| `zone_radius_pct_single` | 0.50 | Competition threshold — single (p50 of floor walk distances). |
| `local_radius_frac_multi` | 0.40 | Reassignment spiral inner ring — multi. |
| `local_radius_pct_single` | 0.30 | Reassignment spiral inner ring — single. |
| `spiral_base_radius_frac_multi` | 0.30 | Initial-assignment spiral start ring — multi (× `min_inter_dist`). |
| `spiral_base_radius_pct_single` | 0.05 | Initial-assignment spiral start ring — single (p5 × 2). |
| `spiral_expansion_factor` | 1.5 | Ring growth per spiral step. **Lower** for more symmetric instance fill. |
| `walk_tolerance_frac` | 0.15 | Instance-switching hysteresis. **Lower toward 0** for symmetric switching. |
| `floor_competition_walk_weight` | 3.0 | Walk weight in Phase 2 competition. |
| `floor_change_penalty_frac` | 0.50 | Ramp-time fraction → `floor_change_penalty`. |
| `floor_penalty_frac` | 0.50 | `floor_change_penalty` fraction → `floor_penalty_per_level`. |
| `comp_radius_growth_factor` | 1.3 | Phase 2 cap growth per floor depth. Set to 9999 to disable. |
| `comp_walk_tolerance_frac` | 0.1 | Walk tolerance for the Phase 2 competition spiral. |

> **Known doc drift in `settings.json`.** The `_doc_comp_radius` comment inside
> `settings.json` describes the cap as
> `zone_radius × comp_radius_growth_factor^(depth-1)`. The code in
> `floor_selection.py` uses `^depth`. The code is authoritative; the comment
> should be corrected.

### `runtime` — read on every call

| Parameter | Default | Effect |
|---|---|---|
| `default_vehicle_speed` | 2.2 | Fallback vehicle speed (m/s). Note: `server.py::_spawn_vehicle` writes `speed_mps = 3.0` on the vehicle directly, which takes precedence for spawned vehicles. |
| `walk_weight` | 5.0 | Walk weight in reassignment Step 2 scoring. |
| `floor_change_expansion` | 1.8 | Zone multiplier per completed floor change in Step 1. |

### `selection` — legacy `choose_best_spot()` fallback only

| Parameter | Default | Effect |
|---|---|---|
| `distance_window_m` | 20.0 | Global candidate-window fallback when no per-subtype value exists. |
| `distance_equal_eps_m` | 1.0 | Walk distances within this are treated as equal. |
| `time_equal_eps_s` | 2.0 | Drive times within this are treated as equal. |
| `time_save_min_s` | 999999.0 | Minimum time saving for a cross-row switch. Effectively **disables** the switch — `compute_scoring_params()` also hardcodes 999999.0. |
| `time_save_frac` | 0.2 | Fraction of current drive time for significance. Inert while `time_save_min_s` is infinite. |

### `ui`

| Parameter | Default | Effect |
|---|---|---|
| `default_weights` | distance 1.0 · drive_time 0.5 · load 2.0 | Weights passed to the legacy scorer. |
| `max_event_log` | 50 | Event-log ring size on the server. |
