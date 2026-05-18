# Smart Parking v8 — Algorithm Reference

All tunable constants are in `core/settings.json`.  
No algorithm value is hardcoded in source code.

---

## Concepts

| Term | Meaning |
|---|---|
| **target_type** | The destination the driver selects: `mall_elevator`, `office_a`, `office_b`, … One string, fixed at entry, never changed. |
| **target_instance** | One physical elevator/escalator shaft at a specific (x, y, floor). A group may have 1 or 2+ instances per floor. |
| **inst-1** | The instance with shortest drive-time from the entrance on the same floor. Checked first in all spirals. |
| **single-instance** | A group with exactly one instance per floor (common for office targets). |
| **multi-instance** | A group with two or more instances on at least one floor (common for mall elevators). |
| **zone_radius** | Maximum walk distance accepted on the current floor before floor competition opens. Identical base used by initial assignment and reassignment. |
| **floor_depth** | Number of floors above the zone-exhausted floor. 0 for current floor, 1 for the next, etc. |
| **committed_floor** | The floor assigned at initial assignment. All floors below it are permanently banned. |
| **visited_floors** | Floors fully exhausted during reassignment (append-only, never cleared). |
| **intended_floor** | The floor reassignment Step 1 searches. Equals `pending_floor` if set, else `current_floor`. |

---

## Geometry Parameters (computed once at startup)

`compute_scoring_params()` in `core/offline.py` reads the layout and derives:

```
min_inter_dist = min Euclidean distance between two instances of the same
                 group on the same floor (across all floors and groups)
half           = min_inter_dist / 2

If multi-instance pairs exist:
  zone_radius         = half × zone_radius_frac_multi        (settings: 0.90)
  local_target_radius = half × local_radius_frac_multi       (settings: 0.40)
  spiral_base         = min_inter_dist × spiral_base_radius_frac_multi (0.30)

If single-instance only (no same-floor pairs found):
  sorted walk distances from all F0 spots to their nearest elevator → walk_dists[]
  zone_radius         = walk_dists[n × zone_radius_pct_single]        (p50)
  local_target_radius = walk_dists[n × local_radius_pct_single]       (p30)
  spiral_base         = walk_dists[n × spiral_base_radius_pct_single] × 2 (p5×2)

walk_tolerance       = zone_radius × walk_tolerance_frac               (0.15)
floor_change_penalty = one_way_ramp_traversal_time × floor_change_penalty_frac (0.50)
floor_penalty_per_level = floor_change_penalty × floor_penalty_frac    (0.50)
```

These are stored in `offline["scoring_params"]` and consumed at runtime.

---

## Part 1 — Initial Assignment

Entry point: `assign_and_build_route()` → `select_spot_auto()` in `core/floor_selection.py`.

### Phase 1 — Zone Search

Start on the lowest eligible floor (F0, or `committed_floor` if set).

**Single-instance:**
```
best = argmin walk(spot, elevator)  over eligible FREE spots on this floor
if walk(best) ≤ zone_radius → ASSIGN, done
else → zone exhausted, open Phase 2
```

**Multi-instance (spiral):**
```
walk_tolerance = zone_radius × walk_tolerance_frac
sort instances by drive_time from entrance  (inst-1 first)

radius = spiral_base
while radius ≤ zone_radius:
    inst1_walk = walk(closest_free_spot, inst-1)
    for k, inst_k in enumerate(instances):
        walk_k = walk(closest_free, inst_k)
        if walk_k ≤ radius AND walk_k ≤ inst1_walk - k×walk_tolerance:
            → ASSIGN to closest_free, navigate to inst_k, done
    radius = min(radius × spiral_expansion_factor, zone_radius)

→ zone exhausted, open Phase 2
```

`walk_tolerance` is the switching hysteresis: inst-k only wins when it saves  
at least k × walk_tolerance metres of walk compared to inst-1.  
Set `walk_tolerance_frac = 0.0` for fully symmetric instance switching.

### Phase 2 — Floor Competition

Triggered when Phase 1 finds no spot within zone_radius on the starting floor.

**Candidate set:**
- **Current floor** (zone exhausted): ALL remaining eligible FREE spots.
- **Each subsequent floor**: one candidate per elevator instance (closest spot to that instance).

**Score formula:**
```
score(spot, floor) = drive_time(entrance → spot)
                   + floor_competition_walk_weight × walk(spot → nearest elevator)
                   + floor_depth × floor_penalty_per_level

floor_depth = floor - zone_exhausted_floor  (0 for current, 1 for next, …)
```

The `floor_penalty_per_level` gently discourages ascending extra floors. It equals  
one-way ramp traversal time × `floor_penalty_frac`. At default 0.5 each extra floor  
adds half a ramp traversal (~7.5 s for a 15 m ramp at 1 m/s) — noticeable across  
several floors but rarely decisive for a single floor change.

**Competition zone cap (subsequent floors only):**

Each subsequent floor's candidates are restricted by a cap radius that grows
with floor depth:
```
cap(depth) = zone_radius × comp_radius_growth_factor ^ depth
  depth=1 (next floor):   cap = zone_radius × 1.3
  depth=2 (two above):    cap = zone_radius × 1.69
  depth=3 (three above):  cap = zone_radius × 2.20  etc.
```

For single-instance floors, only the closest spot within the cap qualifies.
For multi-instance floors, a spiral from `spiral_base` up to the cap selects
one representative (using `comp_walk_tolerance_frac` for more symmetric
instance switching than Phase 1's `walk_tolerance_frac`).

If a spot is found within the cap on a floor → that floor is the representative
and scanning stops (no deeper floors are checked).
If no spot is within the cap → fallback: absolute closest per instance enters
the pool without stopping the scan, so deeper floors can still compete.

Set `comp_radius_growth_factor = 9999` to disable the cap entirely.

Lowest score wins. The winner's floor becomes `committed_floor` (no-return).

---

## Part 2 — Reassignment

Entry point: `reassign_from_current()` in `core/simulation.py`.  
Called when a reserved spot is stolen or the vehicle is displaced.

### Step 1 — Zone Search on intended_floor

Zone radius expands per completed floor change:
```
zone = zone_radius × floor_change_expansion^n
         where n = len(visited_floors) = floor changes made so far
```

At n=0 the zone equals the initial assignment zone exactly.  
At n=1 it is ×1.8 (vehicle tries harder to stay on the new floor).

**Single-instance:**
```
ZONE = zone_radius × floor_change_expansion^n
if walk(closest_free, elevator) ≤ ZONE → ASSIGN, done
else → open Step 2
```

**Multi-instance (spiral, same structure as Phase 1):**
```
MULTI_ZONE = zone_radius × floor_change_expansion^n
local_r = local_target_radius
while local_r ≤ MULTI_ZONE:
    inst1_walk = walk(closest_free, inst-1)
    for k, inst_k:
        walk_k = walk(closest_free, inst_k)
        if walk_k ≤ local_r AND walk_k ≤ inst1_walk - k×walk_tolerance:
            → ASSIGN, done
    local_r = min(local_r × spiral_expansion_factor, MULTI_ZONE)

fallback: closest spot to any instance within MULTI_ZONE
```

### Step 2 — Global Score (zone exhausted on floor E)

Mark E as visited (permanent). Candidate set:

| Source | Spots |
|---|---|
| Floor E | ALL eligible FREE spots (always present in every pass) |
| Each other floor | Single best spot (closest walk to nearest elevator, drive tiebreak) |

**Score formula:**
```
score(spot) = drive_time(vehicle_position → spot)
            + walk_weight × walk(spot → nearest elevator)
            + max(0, spot_floor - E) × floor_penalty_per_level
```

`drive_time` is from the vehicle's *current position* (not entrance).  
Floors below E get `floor_depth = 0` (Pass 3 last resort — already costly via drive time).

**Three passes** (stop at first that finds a winner):
```
Pass 1: Floor E + unvisited floors ≥ E   (no regression, no revisit)
Pass 2: Floor E + all floors ≥ E         (revisit ok, no regression)
Pass 3: Floor E + all floors             (last resort — garage nearly full)
```

If winner on floor N ≠ E → `pending_floor = N`. Vehicle committed to N, E locked forever.

### Step 3 — Legacy Fallback

`choose_best_spot()` with offline rankings. Only reached when the garage is  
essentially full above the vehicle's committed floor.

---

## Parameter Reference

All parameters are in `core/settings.json`. Change and restart the server.

### `offline` section (geometry, baked in at startup)

| Parameter | Default | Effect |
|---|---|---|
| `zone_radius_frac_multi` | 0.90 | Competition threshold — multi. **Raise** to stay on current floor longer. |
| `zone_radius_pct_single` | 0.50 | Competition threshold — single (50th percentile of F0 walks). |
| `local_radius_frac_multi` | 0.40 | Spiral inner ring — multi. |
| `local_radius_pct_single` | 0.30 | Spiral inner ring — single. |
| `spiral_base_radius_frac_multi` | 0.30 | Spiral absolute floor — multi. |
| `spiral_base_radius_pct_single` | 0.05 | Spiral absolute floor — single. |
| `spiral_expansion_factor` | 1.5 | Ring growth per spiral step. **Lower** for more symmetric instance fill. |
| `walk_tolerance_frac` | 0.15 | Instance-switching hysteresis. **Lower toward 0** for symmetric switching. |
| `floor_competition_walk_weight` | 3.0 | Walk weight in Phase 2 / Step 2 competition. |
| `floor_penalty_frac` | 0.5 | Extra score per floor above current, as fraction of ramp traversal time. |
| `floor_change_penalty_frac` | 0.50 | Ramp-time fraction used to compute `floor_penalty_per_level`. |
| `comp_radius_growth_factor` | 1.3 | Competition cap growth per floor depth (see Phase 2 cap below). Set to 9999 to disable. |
| `comp_walk_tolerance_frac` | 0.1 | Walk tolerance for competition spiral instance-switching (lower = more symmetric). |

### `runtime` section (used every call)

| Parameter | Default | Effect |
|---|---|---|
| `walk_weight` | 5.0 | Walk weight in reassignment Step 2 global scoring. |
| `floor_change_expansion` | 1.8 | Zone radius multiplier per completed floor change in Step 1. |
