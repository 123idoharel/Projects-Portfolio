"""
07_q75_inference_mh.py — Standalone q75 inference for the multi-horizon track.

Predicts q75 for both horizons (1y, 2y) using the production q75 models
trained by 05q_q75_production_mh.py. Output goes to a separate CSV that the
merge step picks up alongside the existing MH predictions.

Fully decoupled from 07inference_mh.py — re-running this never affects the
existing q10/q50/q90 MH outputs. Skip running it entirely if q75 isn't wanted
in the frontend.

Pre-requisites:
  1. 04q_q75_mh.py --horizon 1y     (and same for 2y)
  2. 05q_q75_production_mh.py --horizon 1y    (and same for 2y)
  3. Inference vectors built by 07a_build_inference_vectors_mh.py (already exist).

Output:
  data/processed/att_predictions/att_predictions_2425_q75_mh.csv

Each row: tm_id, mv_at_cutoff, q75_1y_eur, q75_2y_eur.

Usage:
    python 07_q75_inference_mh.py
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
import joblib

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))
import setup_mh

MIN_VALID_MV_END_EUR = 10_000
TRAINING_POSITIONS = ['LM', 'LW', 'RM', 'RW', 'ST']

POSITION_SAFETY_REMAP = {
    'CM':  ('RM', 'LM'),
    'CAM': ('RM', 'LM'),
    'CF':  ('ST', 'LW'),
    'RB':  ('RM', 'RM'),
    'LB':  ('LM', 'LM'),
}


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


def apply_position_safety(df):
    df = df.copy()
    for non_train, (new_p, new_s) in POSITION_SAFETY_REMAP.items():
        mask = df['primary_position'] == non_train
        if mask.any():
            df.loc[mask, 'primary_position']   = new_p
            df.loc[mask, 'secondary_position'] = new_s
    return df


def run_q75_mh_inference():
    print("=" * 70)
    print("STAGE 7-Q75 (MH): STANDALONE q75 INFERENCE — 1Y & 2Y")
    print("=" * 70)

    vec_path = setup_mh.PROJECT_ROOT / "data" / "processed" / "inference_vectors_mh" / "inference_vectors_2025_mh.parquet"
    if not vec_path.exists():
        print(f"[!] Inference vectors not found at {vec_path}")
        return

    inf_df = pd.read_parquet(vec_path)
    print(f"[*] Loaded {len(inf_df):,} players from inference vectors.")

    inf_df, n_dropped, reasons = filter_valid_players(inf_df)
    if n_dropped > 0:
        print(f"[*] Filtered {n_dropped} invalid players:")
        for r, c in reasons.items():
            if c > 0: print(f"    - {c}: {r}")
    inf_df = apply_position_safety(inf_df)
    print(f"[*] Valid scorable players: {len(inf_df):,}")

    log_mv_end_values = inf_df['log_mv_end'].values
    mv_at_cutoff = np.expm1(log_mv_end_values)

    # Build feature matrix once — same prep as 07inference_mh.py
    to_drop = ['tm_id', 'cutoff_year']
    to_drop += list(setup_mh.phase1_setup.RAW_EUR_TO_DROP)
    to_drop += list(setup_mh.phase1_setup.DATA_QUALITY_DROPS)
    X_inf = inf_df.drop(columns=[c for c in to_drop if c in inf_df.columns])

    # Align column order with the model's expected feature names. We pull the
    # 1y q75 model's feature_names as the canonical schema (same vectors for both).
    ref_model_path = setup_mh.MODELS_MH_DIR / '1y' / 'final_model_quantile_q75.json'
    if not ref_model_path.exists():
        print(f"[!] q75 production model missing at {ref_model_path}")
        print("    Run: python 05q_q75_production_mh.py --horizon 1y (and --horizon 2y)")
        return
    ref_model = xgb.XGBRegressor()
    ref_model.load_model(ref_model_path)
    X_inf = X_inf[ref_model.get_booster().feature_names]

    for col in ['primary_position', 'secondary_position']:
        X_inf[col] = pd.Categorical(X_inf[col], categories=TRAINING_POSITIONS)

    output = pd.DataFrame({'tm_id': inf_df['tm_id'].values, 'mv_at_cutoff': mv_at_cutoff})

    for horizon in setup_mh.VALID_HORIZONS:    # ['1y', '2y']
        m_dir = setup_mh.MODELS_MH_DIR / horizon
        model_path = m_dir / "final_model_quantile_q75.json"
        if not model_path.exists():
            print(f"[!] Skipping {horizon}: no q75 model at {model_path}")
            continue

        m_q75 = xgb.XGBRegressor()
        m_q75.load_model(model_path)
        cal_path = m_dir / "q75_calibrator.pkl"
        cal = joblib.load(cal_path) if cal_path.exists() else None

        print(f"[*] Predicting q75 for horizon {horizon} (calibrator: {cal is not None})...")
        r = m_q75.predict(X_inf)
        if cal is not None:
            r = cal.transform(r)
        output[f'q75_{horizon}_eur']       = np.expm1(log_mv_end_values + r)
        output[f'q75_{horizon}_log_ratio'] = r

    out_path = setup_mh.PROJECT_ROOT / "data" / "processed" / "att_predictions" / "att_predictions_2425_q75_mh.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(out_path, index=False)

    print()
    print("=" * 70)
    print(f"Saved q75 MH predictions for {len(output)} players")
    print(f"  → {out_path}")
    print(f"\nNext: re-run merge_predictions_and_history_data.py to fold q75 into core_players_db.json")


if __name__ == '__main__':
    run_q75_mh_inference()