"""
fix_tmid_conflicts.py — Repairs JSON entries where a single tm_id was
incorrectly shared between two different players.

The root problem: a handful of tm_ids in the attacker source data had rows
from two different Sofascore players merged together. This polluted the
JSON in three ways:
  1. metadata fields that came from season data (name, sofa_id, team,
     league, position, age, current value) — may point to the wrong player
  2. history_data — contains rows from both players
  3. models — predictions were trained on a stitched-together career

Fields that came from tm_id-keyed Transfermarkt scrapes (image, height,
foot, contract_expiry, citizenships, has_photo) are still correct because
the tm_id IS the right pointer for those.

This script:
  1. Reads conflicts_ATT_24_25_remove.csv to identify, for each conflicted
     tm_id, the OWNER row (the one player who actually has that tm_id) and
     the DELETE rows (other players' data to remove).
  2. Patches att_features_before_vectorization.csv in memory — drops rows
     where (tm_id is conflicted) AND (player id is not the owner's sofa id).
  3. Runs the same vectorize.build_all_vectors() pipeline that 07a uses.
  4. Runs the same inference flow that 07_inference.py and 07inference_mh.py
     use, producing peak / 1y / 2y predictions with all 4 quantiles each.
  5. Builds replacement JSON entries (metadata + history_data + advanced_stats
     + models). For the 5 orphan tm_ids (where NEITHER player claims the
     tm_id), deletes the entry entirely.
  6. Splices into web_system/final_players_db.json, with a .backup written
     first. All other entries (~4,758 attackers) are untouched.

Run from project root:    python fix_tmid_conflicts.py
"""
import sys
import csv
import json
import shutil
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd
import joblib
import xgboost as xgb


# ─── Path resolution (mirrors 07a's auto-discovery) ──────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
path_parts = list(SCRIPT_DIR.parts)
if 'football_scouting_project' in path_parts:
    root_idx = path_parts.index('football_scouting_project')
    PROJECT_ROOT = Path(*path_parts[:root_idx + 1])
else:
    PROJECT_ROOT = SCRIPT_DIR

# Make the same modules 07a uses importable
VECTORIZE_DIR    = PROJECT_ROOT / "EDA_Vectorization_notebooks_and_scripts_" / "Vectorization"
VECTORIZE_MH_DIR = PROJECT_ROOT / "EDA_Vectorization_notebooks_and_scripts_" / "vectorization_mh"
MODEL_DIR        = PROJECT_ROOT / "model"
MODEL_MH_DIR     = PROJECT_ROOT / "model_mh"

for p in [VECTORIZE_DIR, VECTORIZE_MH_DIR, MODEL_DIR, MODEL_MH_DIR]:
    sys.path.insert(0, str(p))


# ─── Static config ───────────────────────────────────────────────────────────
# Input is the SAME file 07a_build_inference_vectors.py reads: the raw tiered
# data BEFORE feature engineering. We run the full preprocess + vectorize
# pipeline in-memory just like 07a, so we get vectors with 24/25 rows for
# every conflicted owner tm_id.
CONFLICTS_CSV       = PROJECT_ROOT / "data" / "raw" / "conflicts_ATT_24_25_remove.csv"
TIERED_INPUT_CSV    = PROJECT_ROOT / "data" / "processed" / "att_with_tiers_for_eda.csv"
RAW_DATABASE_CSV    = PROJECT_ROOT / "data" / "raw" / "database_ATT.csv"
JSON_PATH           = PROJECT_ROOT / "web_system" / "final_players_db.json"

# Models — paths from 07_inference.py / 07inference_mh.py
PROD_MODELS_PKL     = PROJECT_ROOT / "models" / "production_attacker_v1.pkl"
PROD_CALIB_PKL      = PROJECT_ROOT / "models" / "quantile_calibrators.pkl"
PROD_Q75_CALIB_PKL  = PROJECT_ROOT / "models" / "q75_calibrator.pkl"

MH_MODELS_DIR       = PROJECT_ROOT / "models_mh"   # 1y/, 2y/ subdirs

# Position handling — same constants as 07_inference.py
TRAINING_POSITIONS  = {'ST', 'LW', 'RW', 'RM', 'LM'}
POSITION_SAFETY_REMAP = {
    'CM':  ('RM', 'LM'),
    'CAM': ('RM', 'LM'),
    'CF':  ('ST', 'LW'),
    'RB':  ('RM', 'RM'),
    'LB':  ('LM', 'LM'),
    'RWB': ('RM', 'RM'),
    'LWB': ('LM', 'LM'),
    'CB':  ('RM', 'LM'),
}

MIN_VALID_MV_END_EUR = 10_000
CURRENT_SEASONS = ['24/25', '2025']
CUTOFF_YEAR = 2025


# ─── Step 1: Parse conflicts CSV ─────────────────────────────────────────────
def parse_conflicts(csv_path):
    """Returns (owner_by_tmid, orphan_tmids, all_conflicted_tmids).

    owner_by_tmid     — dict{tm_id: {sofa_player_id, player_name}} for tm_ids
                        with a 'correct' row
    orphan_tmids      — list of tm_ids where NO row is marked 'correct'
                        (delete entirely from JSON)
    all_conflicted    — set of every tm_id in the conflicts CSV
    """
    rows_by_tmid = defaultdict(list)
    with open(csv_path, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            rows_by_tmid[int(r['tm_id'])].append(r)

    owner_by_tmid = {}
    orphan_tmids = []
    for tm_id, rows in rows_by_tmid.items():
        owner_rows = [r for r in rows if r['correct'].strip().lower() == 'correct']
        if len(owner_rows) == 0:
            orphan_tmids.append(tm_id)
        elif len(owner_rows) > 1:
            print(f"  [!] tm_id={tm_id} has {len(owner_rows)} 'correct' rows — using first")
            o = owner_rows[0]
            owner_by_tmid[tm_id] = {
                'sofa_player_id': int(o['sofa_player_id']),
                'player_name':    o['player'],
                'team':           o['team'],
                'league':         o['league'],
                'birth_year':     int(o['birth_year']),
            }
        else:
            o = owner_rows[0]
            owner_by_tmid[tm_id] = {
                'sofa_player_id': int(o['sofa_player_id']),
                'player_name':    o['player'],
                'team':           o['team'],
                'league':         o['league'],
                'birth_year':     int(o['birth_year']),
            }
    return owner_by_tmid, orphan_tmids, set(rows_by_tmid.keys())


# (The Step 2 "patch feature CSV" helper used to live here. It's been
#  replaced by patch_raw_df, which operates on the raw tiered DataFrame
#  AFTER attach_league_from_raw — see run_full_pipeline below.)


# ─── Step 3: Pipeline runner (mirrors 07a end-to-end) ────────────────────────
def patch_raw_df(raw_df, owner_by_tmid):
    """Drop rows where (tm_id is conflicted) AND (player id != owner's sofa id).

    Called AFTER attach_league_from_raw so the row-count alignment that
    attach_league_from_raw depends on is preserved up to that point.

    Returns (patched_df, drops_per_tmid).
    """
    drops = {}
    keep_mask = pd.Series(True, index=raw_df.index)
    sofa_col = 'player id'

    if sofa_col not in raw_df.columns:
        raise KeyError(
            f"Expected column '{sofa_col}' in raw tiered CSV; "
            f"found columns: {list(raw_df.columns)[:20]}..."
        )

    for tm_id, owner in owner_by_tmid.items():
        owner_sofa = owner['sofa_player_id']
        in_conflict = (raw_df['tm_id'] == tm_id)
        wrong_sofa  = in_conflict & (raw_df[sofa_col] != owner_sofa)
        n_dropped   = int(wrong_sofa.sum())
        drops[tm_id] = n_dropped
        keep_mask &= ~wrong_sofa

    patched = raw_df[keep_mask].copy().reset_index(drop=True)
    return patched, drops


def run_full_pipeline(raw_df, owner_by_tmid, mh=False):
    """End-to-end: attach _league → patch → rest of pipeline → vectorize.

    Returns (raw_patched_df, engineered_df, vectors_df, drops):
      raw_patched_df — raw stats per season, AFTER attaching _league and
                        dropping polluted rows but BEFORE build_features.
                        This is the source for the JSON's history_data block.
      engineered_df  — post-feature-engineering rows (one per tm_id × season).
                        Used as the input to vectorize.
      vectors_df     — one row per tm_id at cutoff 2025. Carries the
                        cont_*, hist_*, current_*_vs_hist_*, *_tier_z
                        aggregates. This is the source for the JSON's
                        advanced_stats block and the input to inference.
      drops          — dict[tm_id → number of polluting rows dropped].
    """
    if mh:
        sys.path.insert(0, str(VECTORIZE_MH_DIR))
        import vectorize as v
        import copy_only_feature_eng_by_eda_before_shrink as prep
    else:
        sys.path.insert(0, str(VECTORIZE_DIR))
        import vectorize as v
        import feature_eng_by_eda_before_shrink as prep

    prep.RAW_PATH = RAW_DATABASE_CSV

    df = raw_df.copy()

    # 1) Attach _league FIRST — positional alignment requires full row count
    df = prep.attach_league_from_raw(df)

    # Also attach `team` (team name string) from the raw database — the
    # tier-merge step that produces att_with_tiers_for_eda.csv drops the
    # team-name column in favor of team_tier / team id. The frontend's
    # history_data display reads `team`, so we restore it here using the
    # same positional alignment trick attach_league_from_raw uses.
    if 'team' not in df.columns:
        raw_for_team = pd.read_csv(RAW_DATABASE_CSV, usecols=['tm_id', 'team'])
        if len(raw_for_team) == len(df) and (raw_for_team['tm_id'].values == df['tm_id'].values).all():
            df['team'] = raw_for_team['team'].values

    # 2) NOW drop the polluted rows — patch happens AFTER _league is attached
    df, drops = patch_raw_df(df, owner_by_tmid)

    # ──────────────────────────────────────────────────────────────────────
    # Capture the raw-stat-level DataFrame here, BEFORE build_features
    # runs. This is what goes into `history_data` in the JSON — the original
    # merge pipeline puts the raw Sofascore per-season stats here, NOT the
    # engineered features. Each row has columns like goals, assists,
    # expectedGoals, cleanSheet, accuratePassesPercentage etc. — the things
    # the frontend reads directly.
    # ──────────────────────────────────────────────────────────────────────
    raw_patched_df = df.copy()

    # 3) Inject placeholder target for current-season rows
    mask_current = df['_season_year'].isin(CURRENT_SEASONS)
    df.loc[mask_current, 'future_max_value'] = 1.0

    # 4) Rest of preprocess (feature engineering)
    df = prep.apply_row_filters(df)
    df = prep.drop_unused_columns(df)
    df = prep.build_features(df)
    df = prep.add_tournament_flags(df)

    engineered_df = df

    # 5) Vectorize (per-tm_id at cutoff 2025) — these vectors carry the
    # cont_*, hist_*, current_*_vs_hist_*, *_tier_z aggregates the frontend
    # reads from advanced_stats.
    v.EMIT_CUTOFFS = [CUTOFF_YEAR]
    vectors = v.build_all_vectors(engineered_df)

    # Drop placeholder targets
    for col in ['log_target', 'target_1y_log', 'target_2y_log', 'target_3y_log', 'future_max_value']:
        if col in vectors.columns:
            vectors = vectors.drop(columns=col)

    # CM remap (same as 07a_mh, and safe for SH)
    if 'primary_position' in vectors.columns:
        mask_cm = vectors['primary_position'] == 'CM'
        if mask_cm.any():
            vectors.loc[mask_cm, 'primary_position']   = vectors.loc[mask_cm, 'secondary_position']
            mask_sec_cm = vectors['secondary_position'] == 'CM'
            vectors.loc[mask_sec_cm, 'secondary_position'] = vectors.loc[mask_sec_cm, 'primary_position']

    return raw_patched_df, engineered_df, vectors, drops


# ─── Step 4: Run inference (peak + 1y + 2y) ──────────────────────────────────
def apply_position_safety(df):
    """Same as 07_inference.apply_position_safety."""
    df = df.copy()
    for non_train, (new_p, new_s) in POSITION_SAFETY_REMAP.items():
        mask = df['primary_position'] == non_train
        if mask.any():
            df.loc[mask, 'primary_position']   = new_p
            df.loc[mask, 'secondary_position'] = new_s
    for non_train, (_, new_s) in POSITION_SAFETY_REMAP.items():
        mask = df['secondary_position'] == non_train
        if mask.any():
            df.loc[mask, 'secondary_position'] = new_s
    return df


def filter_valid_for_inference(df):
    """Same gate as 07_inference.filter_valid_players."""
    mask_nan = df['log_mv_end'].isna()
    mask_zero = (df['log_mv_end'] <= 0) & ~mask_nan
    mv_eur = np.expm1(df['log_mv_end'].fillna(-1))
    mask_low = (mv_eur > 0) & (mv_eur < MIN_VALID_MV_END_EUR)
    keep = ~(mask_nan | mask_zero | mask_low)
    return df[keep].copy().reset_index(drop=True)


def run_peak_inference(vectors):
    """Mirror of 07_inference.run_inference, returns DataFrame with
    predicted_pessimistic_eur, predicted_expected_eur, predicted_optimistic_eur,
    predicted_q75_eur, mv_at_cutoff, upside_multiple — keyed by tm_id."""
    import setup as setup_mod

    df = filter_valid_for_inference(vectors)
    df = apply_position_safety(df)

    production = joblib.load(PROD_MODELS_PKL)
    calibrators = joblib.load(PROD_CALIB_PKL)
    q75_calibrator = joblib.load(PROD_Q75_CALIB_PKL) if PROD_Q75_CALIB_PKL.exists() else None

    drop_cols = ['tm_id', 'cutoff_year']
    if 'log_target' in df.columns:
        drop_cols.append('log_target')
    drop_cols += [c for c in setup_mod.RAW_EUR_TO_DROP if c in df.columns]
    drop_cols += [c for c in setup_mod.DATA_QUALITY_DROPS if c in df.columns]
    X = df.drop(columns=drop_cols)

    for col in ['primary_position', 'secondary_position']:
        if col in X.columns:
            X[col] = pd.Categorical(X[col], categories=sorted(TRAINING_POSITIONS))

    log_mv_end_values = df['log_mv_end'].values
    out = pd.DataFrame({
        'tm_id':        df['tm_id'].astype(int),
        'mv_at_cutoff': np.expm1(log_mv_end_values),
    })

    for label, model in production.items():
        # Align column order to the model's feature_names if available
        try:
            booster = model.get_booster()
            feature_names = booster.feature_names
            if feature_names:
                X_aligned = X[[c for c in feature_names if c in X.columns]]
                if list(X_aligned.columns) != list(feature_names):
                    # Fill missing with NaN (shouldn't happen on a clean vector)
                    for c in feature_names:
                        if c not in X_aligned.columns:
                            X_aligned[c] = np.nan
                    X_aligned = X_aligned[feature_names]
                ratio = model.predict(X_aligned)
            else:
                ratio = model.predict(X)
        except Exception:
            ratio = model.predict(X)

        # Apply calibration where present
        if label in calibrators and calibrators[label] is not None:
            ratio = calibrators[label].transform(ratio)
        elif label == 'q75' and q75_calibrator is not None:
            ratio = q75_calibrator.transform(ratio)

        out[f'predicted_{label}_eur'] = setup_mod.compose_prediction(ratio, log_mv_end_values)

    # Compute upside_multiple from optimistic / cur (07_inference.py convention)
    if 'predicted_optimistic_eur' in out.columns:
        out['upside_multiple'] = out['predicted_optimistic_eur'] / out['mv_at_cutoff']

    return out


def run_mh_inference(vectors):
    """Mirror of 07inference_mh.run_mh_inference. Returns DataFrame with
    pred_<h>_eur, low_<h>_eur, high_<h>_eur, q75_<h>_eur for h in [1y, 2y]."""
    import setup_mh

    df = filter_valid_for_inference(vectors)
    df = apply_position_safety(df)

    log_mv_end_values = df['log_mv_end'].values
    mv_at_cutoff = np.expm1(log_mv_end_values)

    to_drop = ['tm_id', 'cutoff_year']
    to_drop += [c for c in setup_mh.phase1_setup.RAW_EUR_TO_DROP if c in df.columns]
    to_drop += [c for c in setup_mh.phase1_setup.DATA_QUALITY_DROPS if c in df.columns]
    X = df.drop(columns=[c for c in to_drop if c in df.columns])

    # Use a reference model to align column order
    ref_path = setup_mh.MODELS_MH_DIR / '1y' / 'final_model_mean.json'
    temp = xgb.XGBRegressor()
    temp.load_model(str(ref_path))
    feature_names = temp.get_booster().feature_names
    if feature_names:
        for c in feature_names:
            if c not in X.columns:
                X[c] = np.nan
        X = X[feature_names]

    for col in ['primary_position', 'secondary_position']:
        if col in X.columns:
            X[col] = pd.Categorical(X[col], categories=sorted(TRAINING_POSITIONS))

    out = pd.DataFrame({'tm_id': df['tm_id'].astype(int), 'mv_at_cutoff': mv_at_cutoff})

    for horizon in setup_mh.VALID_HORIZONS:   # ['1y', '2y']
        m_dir = setup_mh.MODELS_MH_DIR / horizon
        m_mean = xgb.XGBRegressor(); m_mean.load_model(str(m_dir / 'final_model_mean.json'))
        m_low  = xgb.XGBRegressor(); m_low.load_model(str(m_dir / 'final_model_quantile_pessimistic.json'))
        m_high = xgb.XGBRegressor(); m_high.load_model(str(m_dir / 'final_model_quantile_optimistic.json'))

        # q75 booster — file pattern is final_model_quantile_q75.json
        q75_path = m_dir / 'final_model_quantile_q75.json'
        m_q75 = xgb.XGBRegressor(); m_q75.load_model(str(q75_path))

        calib   = joblib.load(m_dir / 'quantile_calibrators.pkl')
        q75_cal_path = m_dir / 'q75_calibrator.pkl'
        q75_calib = joblib.load(q75_cal_path) if q75_cal_path.exists() else None

        r_mean = m_mean.predict(X)
        r_low  = m_low.predict(X)
        r_high = m_high.predict(X)
        r_q75  = m_q75.predict(X)

        if calib.get('pessimistic'): r_low = calib['pessimistic'].transform(r_low)
        if calib.get('optimistic'):  r_high = calib['optimistic'].transform(r_high)
        if q75_calib is not None:    r_q75  = q75_calib.transform(r_q75)

        out[f'pred_{horizon}_eur'] = np.expm1(log_mv_end_values + r_mean)
        out[f'low_{horizon}_eur']  = np.expm1(log_mv_end_values + r_low)
        out[f'high_{horizon}_eur'] = np.expm1(log_mv_end_values + r_high)
        out[f'q75_{horizon}_eur']  = np.expm1(log_mv_end_values + r_q75)

    return out


# ─── Step 5: Build the model-block predictions matching JSON schema ──────────
def build_model_blocks_for_tmid(tm_id, peak_df, mh_df):
    """Pack predictions into the JSON schema:
       models.peak_potential.{expected_eur, pessimistic_eur, optimistic_eur,
                              optimistic_q75_eur, upside_multiple, risk_score}
       models.horizon_1y / horizon_2y: same shape.
    """
    pk_row = peak_df[peak_df['tm_id'] == tm_id]
    mh_row = mh_df[mh_df['tm_id'] == tm_id]
    if pk_row.empty:
        return None
    pk = pk_row.iloc[0]

    def safe(label, key):
        col = f'predicted_{key}_eur'
        return float(pk[col]) if col in pk_row.columns and pd.notna(pk.get(col)) else None

    peak_block = {
        'expected_eur':       safe('expected', 'expected'),
        'pessimistic_eur':    safe('pessimistic', 'pessimistic'),
        'optimistic_eur':     safe('optimistic', 'optimistic'),
        'optimistic_q75_eur': safe('q75', 'q75'),
        'upside_multiple':    float(pk['upside_multiple']) if 'upside_multiple' in pk_row.columns and pd.notna(pk.get('upside_multiple')) else None,
    }
    # risk_score (same formula as the rest of the codebase: (opt - pes) / base)
    if peak_block['expected_eur'] and peak_block['expected_eur'] > 0:
        opt, pes = peak_block['optimistic_eur'], peak_block['pessimistic_eur']
        if opt is not None and pes is not None:
            peak_block['risk_score'] = (opt - pes) / peak_block['expected_eur']

    blocks = {'peak_potential': peak_block}

    if not mh_row.empty:
        mh = mh_row.iloc[0]
        for h, h_key in [('1y', 'horizon_1y'), ('2y', 'horizon_2y')]:
            blocks[h_key] = {
                'expected_eur':       float(mh[f'pred_{h}_eur'])   if pd.notna(mh.get(f'pred_{h}_eur'))   else None,
                'pessimistic_eur':    float(mh[f'low_{h}_eur'])    if pd.notna(mh.get(f'low_{h}_eur'))    else None,
                'optimistic_eur':     float(mh[f'high_{h}_eur'])   if pd.notna(mh.get(f'high_{h}_eur'))   else None,
                'optimistic_q75_eur': float(mh[f'q75_{h}_eur'])    if pd.notna(mh.get(f'q75_{h}_eur'))    else None,
            }
            base = blocks[h_key]['expected_eur']
            cur  = float(mh['mv_at_cutoff']) if pd.notna(mh.get('mv_at_cutoff')) else None
            if base and cur and cur > 0:
                blocks[h_key]['upside_multiple'] = base / cur
            opt, pes = blocks[h_key]['optimistic_eur'], blocks[h_key]['pessimistic_eur']
            if base and opt is not None and pes is not None and base > 0:
                blocks[h_key]['risk_score'] = (opt - pes) / base
    return blocks


# ─── Step 6: Build history_data + advanced_stats from patched feature CSV ────
# Columns that go into history_data (per-season rows).
# Looking at one existing JSON entry's history_data, the keys are exactly the
# raw stat names from the feature CSV (camelCase Sofascore-style + _season_year
# + _league + age_in_season + team + mv_start / mv_end + minutesPlayed etc.).
HISTORY_PASSTHROUGH_COLS = None  # we copy ALL columns from the row; the merge
                                 # script writes them straight through.

# Columns that get STRIPPED out of the advanced_stats block before saving.
# advanced_stats holds engineered features and a few raw rate stats; it
# should NOT carry pure season-context fields like team / _league / minutes.
# Looking at an existing entry's advanced_stats it has 314 keys. We pass
# through everything except the placeholder/target columns.
ADVANCED_STATS_DROP = {
    'log_target', 'future_max_value',  # placeholders injected for inference
    'mv_start_date', 'mv_end_date',    # date strings, kept in history_data only
}


def _row_to_jsonable(row):
    """Convert a pandas Series to a dict where NaN → None and numpy types → Python."""
    out = {}
    for k, v in row.items():
        if pd.isna(v):
            out[k] = None
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating,)):
            out[k] = float(v)
        elif isinstance(v, (np.bool_,)):
            out[k] = bool(v)
        else:
            out[k] = v
    return out


def build_history_and_advanced(raw_patched_df, vectors_df, tm_id):
    """Returns (history_data, advanced_stats, current_season_meta) for one tm_id.

    Schema of the JSON blocks matches the original merge pipeline:
      - history_data  ← raw_patched_df: per-season Sofascore stats rows
                        (raw columns like goals, assists, expectedGoals,
                        cleanSheet, accuratePassesPercentage etc.). No
                        engineered features in here.
      - advanced_stats ← vectors_df: the cutoff-2025 vector for this tm_id,
                        carrying cont_*, hist_*, current_*_vs_hist_*,
                        *_tier_z, *_p90_shrunk etc. — the aggregates the
                        frontend reads for Tier Standouts + Key Trends.
      - current_season_meta — pulled from the owner's 24/25 raw row, with
                        most-minutes league row preferred.
    """
    # All raw rows for this tm_id, sorted newest-first
    sub = raw_patched_df[raw_patched_df['tm_id'] == tm_id].copy()
    if sub.empty:
        return [], {}, None
    sub = sub.sort_values('_season_year', ascending=False).reset_index(drop=True)

    # history_data — full pass-through of raw per-season rows. Drop
    # placeholder/intermediate columns that shouldn't be exposed to the
    # frontend (future_max_value was injected as 1.0 for current season).
    history_data = []
    for _, row in sub.iterrows():
        d = _row_to_jsonable(row)
        d.pop('future_max_value', None)
        history_data.append(d)

    # advanced_stats — the cutoff-2025 vector row for this tm_id. This is
    # where cont_*, hist_*, current_*_vs_hist_*, *_tier_z live.
    vec_rows = vectors_df[vectors_df['tm_id'] == tm_id]
    advanced_stats = {}
    if not vec_rows.empty:
        advanced_stats = _row_to_jsonable(vec_rows.iloc[0])
        # Strip placeholders / index columns that shouldn't appear in advanced_stats
        for c in ('log_target', 'future_max_value', 'target_1y_log', 'target_2y_log', 'target_3y_log'):
            advanced_stats.pop(c, None)

    # current_season_meta — prefer 24/25 league row, fall back to 2025
    # calendar row, fall back to newest row
    cur_rows = sub[sub['_season_year'].isin(CURRENT_SEASONS)]
    pref = cur_rows[cur_rows['_season_year'] == '24/25']
    if not pref.empty:
        pref = pref.sort_values('minutesPlayed', ascending=False)
        r = pref.iloc[0]
    elif not cur_rows.empty:
        r = cur_rows.iloc[0]
    else:
        r = sub.iloc[0]

    current_meta = {
        'name':              r.get('player'),
        'sofascore_id':      int(r['player id']) if pd.notna(r.get('player id')) else None,
        'current_team':      r.get('team'),
        'current_league':    r.get('_league'),
        'primary_position':  r.get('primary_position'),
        'secondary_position':r.get('secondary_position'),
        'age_at_cutoff':     float(r['age_in_season']) if pd.notna(r.get('age_in_season')) else None,
        'current_value_eur': float(r['mv_end']) if pd.notna(r.get('mv_end')) else None,
    }

    return history_data, advanced_stats, current_meta


# ─── Main orchestrator ───────────────────────────────────────────────────────
def main():
    print("=" * 78)
    print("FIX TM_ID CONFLICTS — repairing JSON entries for 17 conflicted tm_ids")
    print("=" * 78)
    print(f"\nProject root: {PROJECT_ROOT}")

    # Sanity-check inputs
    for required in [CONFLICTS_CSV, TIERED_INPUT_CSV, RAW_DATABASE_CSV, JSON_PATH]:
        if not required.exists():
            print(f"ERROR: required file not found: {required}")
            return 1
    for required in [PROD_MODELS_PKL, PROD_CALIB_PKL]:
        if not required.exists():
            print(f"ERROR: required model file not found: {required}")
            return 1

    # ─── Step 1: parse conflicts ────────────────────────────────────────────
    print(f"\n[1/6] Parsing conflicts from {CONFLICTS_CSV.relative_to(PROJECT_ROOT)}")
    owner_by_tmid, orphan_tmids, all_conflicted = parse_conflicts(CONFLICTS_CSV)
    print(f"      Owner tm_ids (fix in place):  {len(owner_by_tmid)}")
    print(f"      Orphan tm_ids (delete):       {len(orphan_tmids)}")
    for tm_id, o in owner_by_tmid.items():
        print(f"         tm_id={tm_id:>8}  owner={o['player_name']!r}  sofa={o['sofa_player_id']}")
    for tm_id in orphan_tmids:
        print(f"         tm_id={tm_id:>8}  ORPHAN  → will be deleted from JSON")

    # ─── Step 2: load raw tiered input + run pipeline (SH) ──────────────────
    # Same input file as 07a_build_inference_vectors.py:
    #   data/processed/att_with_tiers_for_eda.csv
    # The pipeline attaches _league, then we drop polluted rows, then the
    # rest of the preprocess + vectorize runs exactly like 07a.
    print(f"\n[2/6] Loading raw tiered input: {TIERED_INPUT_CSV.relative_to(PROJECT_ROOT)}")
    raw_df = pd.read_csv(TIERED_INPUT_CSV)
    print(f"      shape: {raw_df.shape}")

    print(f"\n[3/6] Running SH pipeline (attach _league → patch → preprocess → vectorize)")
    raw_patched_sh, engineered_sh, vectors_sh, drops = run_full_pipeline(raw_df, owner_by_tmid, mh=False)
    total_dropped = sum(drops.values())
    print(f"      Dropped {total_dropped} polluting rows across {len(owner_by_tmid)} owner tm_ids")
    for tm_id, n in drops.items():
        print(f"         tm_id={tm_id:>8}  dropped {n} polluting rows  (kept owner sofa={owner_by_tmid[tm_id]['sofa_player_id']})")
    print(f"      Raw patched df: {raw_patched_sh.shape}  (source for history_data)")
    print(f"      Engineered df:  {engineered_sh.shape}  (intermediate for vectorize)")
    print(f"      Vectors:        {vectors_sh.shape}  (source for advanced_stats + inference)")

    print(f"\n      Running MH pipeline (separate vectorize for 1y/2y models)...")
    _, _, vectors_mh, _ = run_full_pipeline(raw_df, owner_by_tmid, mh=True)
    print(f"      MH vectors:    {vectors_mh.shape}")

    # Filter to ONLY the owner tm_ids — only these need re-scoring + JSON splice
    owner_tmids = list(owner_by_tmid.keys())
    vec_sh_subset = vectors_sh[vectors_sh['tm_id'].isin(owner_tmids)].copy()
    vec_mh_subset = vectors_mh[vectors_mh['tm_id'].isin(owner_tmids)].copy()
    print(f"\n      Owner subset for inference: SH={len(vec_sh_subset)}  MH={len(vec_mh_subset)}")

    # Sanity warn: any owner tm_id missing from the SH vectors?
    missing_sh = [t for t in owner_tmids if t not in set(vec_sh_subset['tm_id'])]
    if missing_sh:
        print(f"      [!] WARNING: {len(missing_sh)} owner tm_ids missing from SH vectors:")
        for t in missing_sh:
            print(f"          tm_id={t}  (likely filtered out by apply_row_filters — "
                  f"check if the owner has a 24/25 league row with valid mv_start)")

    # ─── Step 4: run inference on the owner subset ──────────────────────────
    print(f"\n[4/6] Running peak inference (single-horizon, 4 quantiles)...")
    peak_df = run_peak_inference(vec_sh_subset)
    print(f"      Peak predictions: {len(peak_df)} rows × {peak_df.shape[1]} cols")

    print(f"      Running multi-horizon inference (1y + 2y, 4 quantiles each)...")
    mh_df = run_mh_inference(vec_mh_subset)
    print(f"      MH predictions:   {len(mh_df)} rows × {mh_df.shape[1]} cols")

    # ─── Step 5: load JSON + build replacement entries ──────────────────────
    print(f"\n[5/6] Loading JSON: {JSON_PATH.relative_to(PROJECT_ROOT)}")
    with open(JSON_PATH, encoding='utf-8') as f:
        db = json.load(f)
    print(f"      Loaded {len(db)} JSON entries")

    # Make a backup
    backup_path = JSON_PATH.with_suffix(f'.json.backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    shutil.copy2(JSON_PATH, backup_path)
    print(f"      Backup written: {backup_path.relative_to(PROJECT_ROOT)}")

    # Splice
    summary = []
    for tm_id in owner_tmids:
        key = str(tm_id) if str(tm_id) in db else (tm_id if tm_id in db else None)
        if key is None:
            summary.append((tm_id, 'NOT_IN_JSON', None))
            continue

        entry = db[key]
        old_name = (entry.get('metadata') or {}).get('name')

        # Build the JSON blocks:
        #   history_data  ← raw_patched_sh (raw per-season Sofascore stats)
        #   advanced_stats ← vectors_sh (cutoff-2025 aggregate vector)
        # This matches the schema the original merge pipeline produced.
        history_data, advanced_stats, cur_meta = build_history_and_advanced(
            raw_patched_sh, vectors_sh, tm_id
        )
        models = build_model_blocks_for_tmid(tm_id, peak_df, mh_df)

        # Override season-derived metadata; leave tm_id-keyed fields alone
        if 'metadata' not in entry:
            entry['metadata'] = {}
        md = entry['metadata']
        if cur_meta:
            for k, v in cur_meta.items():
                if v is not None:
                    md[k] = v

        entry['history_data']   = history_data
        entry['advanced_stats'] = advanced_stats
        if models:
            entry['models'] = models

        new_name = md.get('name')
        summary.append((tm_id, 'FIXED', f"{old_name!r} → {new_name!r}"))

    # Drop orphans
    for tm_id in orphan_tmids:
        key = str(tm_id) if str(tm_id) in db else (tm_id if tm_id in db else None)
        if key is not None:
            old_name = (db[key].get('metadata') or {}).get('name')
            del db[key]
            summary.append((tm_id, 'DELETED', f"was {old_name!r}"))
        else:
            summary.append((tm_id, 'ORPHAN_NOT_IN_JSON', None))

    # ─── Step 6: write JSON ─────────────────────────────────────────────────
    print(f"\n[6/6] Writing patched JSON ({len(db)} entries)")
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"      Saved: {JSON_PATH.relative_to(PROJECT_ROOT)}")

    # ─── Final summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for tm_id, status, detail in summary:
        line = f"  tm_id={tm_id:>8}  {status:<22}"
        if detail:
            line += f"  {detail}"
        print(line)

    n_fixed   = sum(1 for s in summary if s[1] == 'FIXED')
    n_deleted = sum(1 for s in summary if s[1] == 'DELETED')
    n_missing = sum(1 for s in summary if 'NOT_IN_JSON' in s[1])
    print(f"\n  Total: {n_fixed} fixed, {n_deleted} deleted, {n_missing} not in JSON to begin with")
    print(f"  Backup at: {backup_path}")
    print("=" * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())