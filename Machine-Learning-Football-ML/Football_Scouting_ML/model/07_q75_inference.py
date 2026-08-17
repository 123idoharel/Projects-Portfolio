"""
07_q75_inference.py — Standalone q75 inference for the PEAK target.

Runs ONLY the q75 model on the inference vectors. Does not touch any of the
existing q10/q50/q90 prediction artifacts. Output goes to a separate CSV that
the merge step picks up alongside the existing predictions.

This script is fully decoupled from 07_inference.py. You can re-run it
without affecting the existing predictions, and you can skip running it
entirely if you don't want q75 in the frontend.

Pre-requisites:
  1. 04q_q75.py        (trained the q75 model + calibrator)
  2. 05q_q75_production.py  (saved the production q75 model)
  3. The same inference vectors used by 07_inference.py (already exist).

Output:
  data/processed/att_predictions/att_predictions_2425_q75.csv
  data/processed/att_predictions/att_predictions_2425_q75.parquet

Each row: tm_id, mv_at_cutoff, predicted_q75_eur, predicted_q75_log_ratio.

Usage:
    python 07_q75_inference.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import joblib
import numpy as np
import pandas as pd

# Mirrors of constants from 07_inference.py — kept local so this script is
# fully self-contained.
TRAINING_POSITIONS = {'ST', 'LW', 'RW', 'RM', 'LM'}

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


def filter_valid_players(inference):
    n_total = len(inference)
    drop_reasons = {}
    mask_nan = inference['log_mv_end'].isna()
    drop_reasons['NaN log_mv_end'] = mask_nan.sum()
    mask_zero_or_neg = (inference['log_mv_end'] <= 0) & ~mask_nan
    drop_reasons['log_mv_end <= 0 (broken/missing)'] = mask_zero_or_neg.sum()
    mv_end_eur = np.expm1(inference['log_mv_end'].fillna(-1))
    mask_too_low = (mv_end_eur > 0) & (mv_end_eur < MIN_VALID_MV_END_EUR)
    drop_reasons[f'mv_end < €{MIN_VALID_MV_END_EUR:,}'] = mask_too_low.sum()
    keep_mask = ~(mask_nan | mask_zero_or_neg | mask_too_low)
    valid = inference[keep_mask].copy().reset_index(drop=True)
    return valid, n_total - len(valid), drop_reasons


def apply_position_safety(inference):
    inference = inference.copy()
    for non_train, (new_primary, new_secondary) in POSITION_SAFETY_REMAP.items():
        mask = inference['primary_position'] == non_train
        if mask.sum() > 0:
            inference.loc[mask, 'primary_position']   = new_primary
            inference.loc[mask, 'secondary_position'] = new_secondary
    for non_train, (_, new_secondary) in POSITION_SAFETY_REMAP.items():
        mask = inference['secondary_position'] == non_train
        if mask.sum() > 0:
            inference.loc[mask, 'secondary_position'] = new_secondary
    return inference


def run_q75_inference():
    print("=" * 70)
    print("STAGE 7-Q75: STANDALONE q75 INFERENCE FOR PEAK TARGET")
    print("=" * 70)

    inference_path = setup.INFERENCE_DIR / "att_inference_2425.parquet"
    if not inference_path.exists():
        print(f"[!] Inference file not found: {inference_path}")
        print("    Build it with 07a_build_inference_vectors.py first.")
        return

    # Load the production model dict and pull only the q75 entry from it.
    production_path = setup.MODEL_DIR / "production_attacker_v1.pkl"
    production = joblib.load(production_path)
    if 'q75' not in production:
        print(f"[!] No 'q75' key in production dict at {production_path}")
        print("    Run 05q_q75_production.py first.")
        return

    q75_model = production['q75']
    print(f"[*] Loaded q75 production model ({type(q75_model).__name__})")

    # Calibrator (may be None if 04q_q75.py determined no calibration was needed)
    cal_path = setup.MODEL_DIR / "q75_calibrator.pkl"
    q75_calibrator = joblib.load(cal_path) if cal_path.exists() else None
    print(f"[*] Loaded q75 calibrator: {q75_calibrator is not None}")

    inference = pd.read_parquet(inference_path)
    print(f"[*] Loaded inference vectors: {inference.shape}")

    # Filter + position safety (same as 07_inference.py)
    inference, n_dropped, drop_reasons = filter_valid_players(inference)
    if n_dropped > 0:
        print(f"[*] Dropped {n_dropped} rows with invalid mv_end:")
        for r, n in drop_reasons.items():
            if n > 0: print(f"    - {n}: {r}")
    inference = apply_position_safety(inference)
    print(f"[*] Valid players: {len(inference)}")

    # Build feature matrix matching training schema
    drop_cols = ['tm_id', 'cutoff_year']
    if 'log_target' in inference.columns:
        drop_cols.append('log_target')
    drop_cols += [c for c in setup.RAW_EUR_TO_DROP if c in inference.columns]
    drop_cols += [c for c in setup.DATA_QUALITY_DROPS if c in inference.columns]

    X_inf = inference.drop(columns=drop_cols)
    for col in ['primary_position', 'secondary_position']:
        if col in X_inf.columns:
            X_inf[col] = pd.Categorical(X_inf[col], categories=sorted(TRAINING_POSITIONS))

    log_mv_end_values = inference['log_mv_end'].values

    # Predict + apply calibrator + compose to EUR
    print("[*] Running q75 prediction...")
    q75_ratio = q75_model.predict(X_inf)
    if q75_calibrator is not None:
        q75_ratio = q75_calibrator.transform(q75_ratio)
    q75_eur = setup.compose_prediction(q75_ratio, log_mv_end_values)

    output = pd.DataFrame({
        'tm_id':                   inference['tm_id'].values,
        'cutoff_year':             inference['cutoff_year'].values,
        'mv_at_cutoff':            np.expm1(log_mv_end_values),
        'predicted_q75_eur':       q75_eur,
        'predicted_q75_log_ratio': q75_ratio,
    })

    out_dir = setup.PREDICTIONS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path     = out_dir / "att_predictions_2425_q75.csv"
    parquet_path = out_dir / "att_predictions_2425_q75.parquet"
    output.to_csv(csv_path, index=False)
    output.to_parquet(parquet_path, index=False)

    print()
    print("=" * 70)
    print(f"Saved q75 predictions for {len(output)} players")
    print(f"  → {csv_path}")
    print(f"  → {parquet_path}")
    print(f"\nNext: re-run merge_predictions_and_history_data.py to fold q75 into core_players_db.json")


if __name__ == '__main__':
    run_q75_inference()