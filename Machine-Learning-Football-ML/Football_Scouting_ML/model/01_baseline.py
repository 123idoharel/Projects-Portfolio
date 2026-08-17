"""
01_baseline.py — Stage 1: Diagnostic baseline with audit.

Trains a 5-fold GroupKFold baseline with default hyperparameters.
Outputs:
  - 5-fold MAE on the RATIO target
  - Top-20 feature importances
  - Acceptance check tailored to ratio-target prediction
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error, r2_score
import xgboost as xgb
import numpy as np
import pandas as pd


def run_baseline():
    # 1. Load data
    vectors = setup.load_vectors()

    # 2. Quick data quality audit
    print("="*60)
    print("DATA QUALITY AUDIT")
    print("="*60)
    y_ratio_check = vectors['log_target'] - vectors['log_mv_end']
    nans = y_ratio_check.isna().sum()
    infs = np.isinf(y_ratio_check).sum()
    print(f"Total rows in file:      {len(vectors)}")
    print(f"Rows with NaN in ratio:  {nans}")
    print(f"Rows with Inf in ratio:  {infs}")
    print("="*60 + "\n")

    # 3. Split (cleaning happens inside setup.py)
    X, y, groups = setup.split_features_target(vectors)

    print(f"\nStarting training with {len(X)} valid vectors...")
    print(f"Unique players: {groups.nunique()}\n")

    # 4. 5-fold GroupKFold cross-validation
    gkf = GroupKFold(n_splits=5)
    oof_preds = np.zeros(len(X))
    fold_maes = []
    fold_models = []

    for fold, (tr_idx, va_idx) in enumerate(gkf.split(X, y, groups)):
        model = xgb.XGBRegressor(
            n_estimators=2000, max_depth=6, learning_rate=0.05,
            early_stopping_rounds=50, enable_categorical=True,
            eval_metric='mae', random_state=42,
        )
        model.fit(X.iloc[tr_idx], y.iloc[tr_idx],
                  eval_set=[(X.iloc[va_idx], y.iloc[va_idx])],
                  verbose=False)

        oof_preds[va_idx] = model.predict(X.iloc[va_idx])
        fold_mae = mean_absolute_error(y.iloc[va_idx], oof_preds[va_idx])
        fold_maes.append(fold_mae)
        fold_models.append(model)
        print(f"  Fold {fold+1}: MAE={fold_mae:.4f}")

    # 5. Summary
    cv_mae = np.mean(fold_maes)
    print(f"\nBaseline 5-fold MAE (on Ratio target): {cv_mae:.4f} ± {np.std(fold_maes):.4f}")
    print(f"Overall R²: {r2_score(y, oof_preds):.4f}")

    # 6. Feature importance
    importance = pd.DataFrame({
        'feature': X.columns,
        'importance': fold_models[-1].feature_importances_,
    }).sort_values('importance', ascending=False)

    print("\nTop 20 features (Trajectory Prediction):")
    print(importance.head(20).to_string(index=False))

    # Save
    importance.to_csv(setup.RESULT_DIR / "stage1_feature_importance.csv", index=False)

    # 7. Acceptance check — TAILORED FOR RATIO TARGET
    # Different from absolute-target prediction. For trajectory, we expect
    # the model to lean on age, market position, and breakout signals.
    expected_ratio_features = {
        'age_at_cutoff', 'age_penalty',           # age effects (trajectory)
        'log_mv_end', 'log_mv_start',             # baseline volatility conditioner
        'young_top_club', 'young_top_league',     # breakout signals
        'mv_surge_flag', 'breakout_flag',         # market momentum
        'log_mv_change_season',                   # in-season trajectory
        'modern_forward_score',                   # quality signal
        'rating', 'rating_residual',              # performance vs expected
    }
    top10 = set(importance.head(10)['feature'])
    top20 = set(importance.head(20)['feature'])
    matches_top10 = expected_ratio_features & top10
    matches_top20 = expected_ratio_features & top20

    print(f"\nAcceptance Check (Ratio Target):")
    print(f"  Expected trajectory-relevant features in top-10: {len(matches_top10)}/{len(expected_ratio_features)}")
    print(f"  Expected trajectory-relevant features in top-20: {len(matches_top20)}/{len(expected_ratio_features)}")
    print(f"  Found in top-10: {sorted(matches_top10)}")

    if len(matches_top10) >= 4:
        print("✓ Feature set behaves as expected. Proceed to Stage 2.")
    elif len(matches_top20) >= 6:
        print("✓ Feature set is reasonable (most signals are in top-20). Proceed to Stage 2.")
    else:
        print("⚠ WARNING: Few expected features found. Investigate before tuning.")


if __name__ == '__main__':
    run_baseline()