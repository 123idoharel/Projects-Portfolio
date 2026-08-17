"""
07_inference.py — Stage 7: Live inference on 24/25 players.

Loads production models and applies them to inference vectors for cutoff 2025.

Pre-inference safety steps:
  1. Filter rows with invalid mv_end (NaN or 0/negative) — these have
     broken or missing market-value data and cannot be scored meaningfully.
     A player with mv_end=0 isn't worth €0; it means Transfermarkt didn't
     publish their end-of-season value and there's no defensible baseline
     for predictions.
  2. Apply categorical safety remap: any position values not seen during
     training are remapped to the closest training-data category.
  3. Drop the same runtime columns as setup.py (RAW_EUR_TO_DROP, DATA_QUALITY_DROPS).
  4. Cast position columns to category dtype matching XGBoost's expectation.

Output: data/processed/att_predictions/att_predictions_2425.{csv,parquet}
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import joblib
import numpy as np
import pandas as pd

# Position categories that the model saw during training.
TRAINING_POSITIONS = {'ST', 'LW', 'RW', 'RM', 'LM'}

# Safety remap for any non-training position labels in inference.
# Mirrors vectorize.py's primary_remaps but applied defensively at inference.
POSITION_SAFETY_REMAP = {
    'CM':  ('RM', 'LM'),   # central mid → midfielder family
    'CAM': ('RM', 'LM'),
    'CF':  ('ST', 'LW'),
    'RB':  ('RM', 'RM'),
    'LB':  ('LM', 'LM'),
    'RWB': ('RM', 'RM'),
    'LWB': ('LM', 'LM'),
    'CB':  ('RM', 'LM'),
}

# Minimum mv_end (in EUR) for a player to be scoreable.
# €10k is the floor — anything lower is almost certainly broken data.
MIN_VALID_MV_END_EUR = 10_000


def filter_valid_players(inference):
    """
    Drop rows with invalid mv_end. Returns (filtered_df, n_dropped, drop_reasons).
    """
    n_total = len(inference)
    drop_reasons = {}

    # Reason 1: NaN log_mv_end
    mask_nan = inference['log_mv_end'].isna()
    drop_reasons['NaN log_mv_end'] = mask_nan.sum()

    # Reason 2: log_mv_end <= 0 means mv_end <= 1 EUR (broken)
    mask_zero_or_neg = (inference['log_mv_end'] <= 0) & ~mask_nan
    drop_reasons['log_mv_end <= 0 (broken/missing)'] = mask_zero_or_neg.sum()

    # Reason 3: mv_end below threshold (extremely unlikely real value)
    mv_end_eur = np.expm1(inference['log_mv_end'].fillna(-1))
    mask_too_low = (mv_end_eur > 0) & (mv_end_eur < MIN_VALID_MV_END_EUR)
    drop_reasons[f'mv_end < €{MIN_VALID_MV_END_EUR:,}'] = mask_too_low.sum()

    keep_mask = ~(mask_nan | mask_zero_or_neg | mask_too_low)
    valid = inference[keep_mask].copy().reset_index(drop=True)
    n_dropped = n_total - len(valid)

    return valid, n_dropped, drop_reasons


def apply_position_safety(inference):
    """Remap any position labels that don't exist in training."""
    inference = inference.copy()

    for non_train, (new_primary, new_secondary) in POSITION_SAFETY_REMAP.items():
        mask = inference['primary_position'] == non_train
        n = mask.sum()
        if n > 0:
            print(f"  Remapping {n} player(s) with primary='{non_train}' → '{new_primary}', '{new_secondary}'")
            inference.loc[mask, 'primary_position']   = new_primary
            inference.loc[mask, 'secondary_position'] = new_secondary

    for non_train, (_, new_secondary) in POSITION_SAFETY_REMAP.items():
        mask = inference['secondary_position'] == non_train
        n = mask.sum()
        if n > 0:
            print(f"  Remapping {n} player(s) with secondary='{non_train}' → '{new_secondary}'")
            inference.loc[mask, 'secondary_position'] = new_secondary

    unexpected_primary = set(inference['primary_position'].dropna().unique()) - TRAINING_POSITIONS
    unexpected_secondary = set(inference['secondary_position'].dropna().unique()) - TRAINING_POSITIONS
    if unexpected_primary:
        raise ValueError(f"Inference still has unmapped primary positions: {unexpected_primary}")
    if unexpected_secondary:
        raise ValueError(f"Inference still has unmapped secondary positions: {unexpected_secondary}")
    return inference


def run_inference():
    inference_path = setup.INFERENCE_DIR / "att_inference_2425.parquet"
    if not inference_path.exists():
        print(f"Inference file not found: {inference_path}")
        print("Build it first with 07a_build_inference_vectors.py")
        return

    inference   = pd.read_parquet(inference_path)
    production  = joblib.load(setup.MODEL_DIR / "production_attacker_v1.pkl")
    calibrators = joblib.load(setup.MODEL_DIR / "quantile_calibrators.pkl")

    print(f"Loaded inference vectors: {inference.shape}")
    print(f"Loaded {len(production)} production models")

    # --- Step 1: Filter invalid players ---
    print("\nFiltering players with invalid mv_end (broken/missing data)...")
    inference, n_dropped, drop_reasons = filter_valid_players(inference)
    if n_dropped > 0:
        print(f"  Dropped {n_dropped} of {n_dropped + len(inference)} players:")
        for reason, n in drop_reasons.items():
            if n > 0:
                print(f"    - {n} due to: {reason}")
    print(f"  Remaining valid players: {len(inference)}")

    # --- Step 2: Position safety remap ---
    print("\nApplying position safety remap (any non-training categories)...")
    inference = apply_position_safety(inference)

    # --- Step 3: Build feature matrix matching training schema ---
    drop_cols = ['tm_id', 'cutoff_year']
    if 'log_target' in inference.columns:
        drop_cols.append('log_target')
    drop_cols += [c for c in setup.RAW_EUR_TO_DROP if c in inference.columns]
    drop_cols += [c for c in setup.DATA_QUALITY_DROPS if c in inference.columns]

    X_inf = inference.drop(columns=drop_cols)
    for col in ['primary_position', 'secondary_position']:
        if col in X_inf.columns:
            X_inf[col] = pd.Categorical(X_inf[col], categories=sorted(TRAINING_POSITIONS))

    print(f"\nFeature matrix shape: {X_inf.shape}")
    print(f"  (should match training shape: 17633 × 311)")

    log_mv_end_values = inference['log_mv_end'].values

    output = pd.DataFrame({
        'tm_id':        inference['tm_id'],
        'cutoff_year':  inference['cutoff_year'],
        'mv_at_cutoff': np.expm1(log_mv_end_values),
    })

    print("\nRunning predictions for each model...")
    for label, model in production.items():
        predicted_ratio = model.predict(X_inf)

        # Apply isotonic calibration if present (only quantile models have calibrators)
        if label in calibrators and calibrators[label] is not None:
            predicted_ratio = calibrators[label].transform(predicted_ratio)

        # Compose to absolute EUR
        predicted_eur = setup.compose_prediction(predicted_ratio, log_mv_end_values)
        output[f'predicted_{label}_eur'] = predicted_eur
        # Keep the raw log-ratio for analysis (per-player gain/loss in log space)
        output[f'predicted_{label}_log_ratio'] = predicted_ratio
        print(f"  {label}: done")

    # Upside multiple: ratio of optimistic prediction to current value
    # Now safe because all rows have mv_at_cutoff >= MIN_VALID_MV_END_EUR
    output['upside_multiple'] = output['predicted_optimistic_eur'] / output['mv_at_cutoff']

    # Save
    output.to_parquet(setup.PREDICTIONS_DIR / "att_predictions_2425.parquet", index=False)
    output.to_csv(setup.PREDICTIONS_DIR / "att_predictions_2425.csv", index=False)

    print(f"\n{'='*70}")
    print(f"Saved predictions for {len(output)} valid players")
    print(f"  → {setup.PREDICTIONS_DIR / 'att_predictions_2425.parquet'}")
    print(f"  → {setup.PREDICTIONS_DIR / 'att_predictions_2425.csv'}")
    print(f"{'='*70}")

    # Top 20 by upside_multiple — but only include players with mv >= €1M
    # to filter out cases where small denominators inflate the multiple
    show_cols = ['tm_id', 'mv_at_cutoff', 'predicted_pessimistic_eur',
                 'predicted_expected_eur', 'predicted_optimistic_eur', 'upside_multiple']

    print("\nTop 20 by upside multiple — ALL valid players:")
    top_all = output.nlargest(20, 'upside_multiple')[show_cols]
    print(top_all.to_string(index=False, float_format=lambda x: f"{x:,.0f}" if abs(x) > 100 else f"{x:.2f}"))

    # Filter to mv >= €1M for a more meaningful breakout list
    significant_mv = output[output['mv_at_cutoff'] >= 1_000_000]
    print(f"\n\nTop 20 by upside multiple — players with mv >= €1M (n={len(significant_mv)}):")
    top_sig = significant_mv.nlargest(20, 'upside_multiple')[show_cols]
    print(top_sig.to_string(index=False, float_format=lambda x: f"{x:,.0f}" if abs(x) > 100 else f"{x:.2f}"))

    # Distribution of predicted ratios for sanity check
    print(f"\n\nDistribution of predicted ratios (log-scale):")
    print(f"  pessimistic median: {output['predicted_pessimistic_log_ratio'].median():+.3f} (=> {np.exp(output['predicted_pessimistic_log_ratio'].median()):.2f}x)")
    print(f"  expected median:    {output['predicted_expected_log_ratio'].median():+.3f} (=> {np.exp(output['predicted_expected_log_ratio'].median()):.2f}x)")
    print(f"  optimistic median:  {output['predicted_optimistic_log_ratio'].median():+.3f} (=> {np.exp(output['predicted_optimistic_log_ratio'].median()):.2f}x)")


if __name__ == '__main__':
    run_inference()