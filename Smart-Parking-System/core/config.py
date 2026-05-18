"""
config.py — Configuration Loader
==================================

Loads settings.json from the same directory and exposes it as CFG.

All tunable algorithm parameters live in settings.json rather than being
scattered across the codebase.  Import CFG wherever a threshold or constant
is needed:

    from core.config import CFG
    factor = CFG["offline"]["spiral_expansion_factor"]   # 1.5

Settings sections (see settings.json for full inline documentation)
--------------------------------------------------------------------
selection
    Thresholds for the legacy choose_best_spot() fallback in scoring.py.
    At runtime most are overridden per-subtype by offline.compute_scoring_params().

offline
    Graph construction speeds, spot manoeuvre time, and ALL geometry-derived
    algorithm factors:
      • window_diagonal_factor, n_rows        → candidate window / floor-EPS
      • local_radius_frac_multi,
        zone_radius_frac_multi                → multi-instance zones
      • local_radius_pct_single,
        zone_radius_pct_single                → single-instance zone percentiles
      • walk_tolerance_frac                   → inter-instance switch hysteresis
      • floor_change_penalty_frac             → ramp-cost weight in Step 2 scoring
      • floor_penalty_frac                    → per-level penalty in floor competition
      • floor_competition_walk_weight         → walk weight in Phase 2 / Step 2 scoring
      • spiral_base_radius_frac_multi         → initial BASE_TARGET_RADIUS (multi)
      • spiral_base_radius_pct_single         → initial BASE_TARGET_RADIUS (single)
      • spiral_expansion_factor               → ring growth multiplier (all spirals)
      • comp_radius_growth_factor             → competition cap growth per floor depth
      • comp_walk_tolerance_frac              → competition spiral instance-switching

runtime
    Vehicle behaviour at simulation time:
      • default_vehicle_speed
      • walk_weight               → Step 2 score = drive_time + walk_weight × walk
      • floor_change_expansion    → tolerance grows by this factor per floor change

ui
    Operator UI: default_weights (legacy fallback), max_event_log.
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

def _load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

CFG = _load_config()
