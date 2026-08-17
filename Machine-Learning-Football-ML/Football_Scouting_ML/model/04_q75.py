"""
04q_q75.py — Single-horizon q75 quantile training (PEAK target).

Trains the q=0.75 quantile model alongside the existing q10/q50/q90 from
04_quantiles.py. Uses the same setup, target, vectors, Optuna search, GroupKFold
splits, and isotonic calibration as the existing pipeline — only the alpha
changes from {0.10, 0.50, 0.90} to {0.75}.

Why train q75 separately: the production "optimistic" displayed to users is q90,
which represents the 90th-percentile of the model's belief distribution. For most
players that band is genuinely wide, but for elite young talent it can read as
absurd. A trained q75 gives a statistically-honest narrower band ("75th
percentile") that's more defensible as a "best-case ceiling" while still being
a calibrated quantile prediction (vs the post-hoc shrinkage in scout-data.js).

This file does NOT touch any existing artifacts. Outputs go to:
    models/best_params_q75.pkl
    models/q75_calibrator.pkl
    models/q75_oof.npy

Run AFTER 04_quantiles.py. Time: ~1 hour.

Usage:
    python 04q_q75.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import optuna
import xgboost as xgb
from sklearn.model_selection import GroupKFold
from sklearn.isotonic import IsotonicRegression
import numpy as np
import joblib

QUANTILE_LABEL = 'q75'
QUANTILE_ALPHA = 0.75
N_TRIALS = 30
N_FOLDS  = 5


def tune_quantile(q, X, y, groups):
    """Same Optuna setup as 04_quantiles.py but for the chosen single quantile."""
    def objective(trial):
        params = {
            'max_depth':         trial.suggest_int('max_depth', 4, 7),
            'learning_rate':     trial.suggest_float('learning_rate', 0.02, 0.1, log=True),
            'min_child_weight':  trial.suggest_int('min_child_weight', 5, 50),
            'subsample':         trial.suggest_float('subsample', 0.6, 1.0),
            'colsample_bytree':  trial.suggest_float('colsample_bytree', 0.5, 1.0),
            'reg_alpha':         trial.suggest_float('reg_alpha', 0.0, 5.0),
            'reg_lambda':        trial.suggest_float('reg_lambda', 1.0, 20.0),
            'n_estimators':      3000,
            'objective':         'reg:quantileerror',
            'quantile_alpha':    q,
            'enable_categorical': True,
            'random_state':      42,
            'tree_method':       'hist',
        }
        gkf = GroupKFold(n_splits=N_FOLDS)
        losses = []
        for tr, va in gkf.split(X, y, groups):
            m = xgb.XGBRegressor(**params, early_stopping_rounds=50)
            m.fit(X.iloc[tr], y.iloc[tr],
                  eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
            preds = m.predict(X.iloc[va])
            losses.append(setup.pinball_loss(y.iloc[va].values, preds, q))
        return np.mean(losses)

    study = optuna.create_study(direction='minimize')
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=True)
    return study.best_params


def train_q75():
    print("=" * 60)
    print(f"STAGE 4-Q75 — TRAINING QUANTILE MODEL ({QUANTILE_LABEL})")
    print("=" * 60)

    vectors = setup.load_vectors()
    X, y, groups = setup.split_features_target(vectors)
    print(f"Training data: {len(X)} rows × {X.shape[1]} columns\n")

    # Tune
    print(f"=== Tuning {QUANTILE_LABEL} model (q={QUANTILE_ALPHA}) ===")
    params = tune_quantile(QUANTILE_ALPHA, X, y, groups)
    params.update({
        'objective': 'reg:quantileerror', 'quantile_alpha': QUANTILE_ALPHA,
        'n_estimators': 3000, 'enable_categorical': True, 'random_state': 42,
        'tree_method': 'hist',
    })

    # OOF
    print("\nGenerating OOF predictions for calibration check...")
    gkf = GroupKFold(n_splits=N_FOLDS)
    oof = np.zeros(len(X))
    for fold, (tr, va) in enumerate(gkf.split(X, y, groups), 1):
        m = xgb.XGBRegressor(**params, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        oof[va] = m.predict(X.iloc[va])
        print(f"  fold {fold}/{N_FOLDS} done")

    # Calibration check
    print("\n" + "=" * 60)
    print("CALIBRATION CHECK")
    print("=" * 60)
    pct_below = (y.values <= oof).mean() * 100
    target_pct = QUANTILE_ALPHA * 100
    diff = pct_below - target_pct

    if abs(diff) > 3:
        print(f"  ⚠ {QUANTILE_LABEL} drift {diff:+.1f}%. Applying isotonic calibration.")
        iso = IsotonicRegression(out_of_bounds='clip')
        iso.fit(oof, y.values)
        calibrator = iso
        adjusted = iso.transform(oof)
        new_pct = (y.values <= adjusted).mean() * 100
        print(f"    post-calibration coverage: {new_pct:.1f}% (target {target_pct:.0f}%)")
    else:
        print(f"  ✓ {QUANTILE_LABEL} calibration solid (actual {pct_below:.1f}%, target {target_pct:.0f}%).")
        calibrator = None

    # Save artifacts (separate filenames, no collision with 04_quantiles.py output)
    joblib.dump(params,     setup.MODEL_DIR / "best_params_q75.pkl")
    joblib.dump(calibrator, setup.MODEL_DIR / "q75_calibrator.pkl")
    np.save(setup.MODEL_DIR / "q75_oof.npy", oof)

    print(f"\nSaved q75 artifacts to {setup.MODEL_DIR}")
    print("  - best_params_q75.pkl")
    print("  - q75_calibrator.pkl")
    print("  - q75_oof.npy")
    print("\nNext: run python 05q_q75_production.py")


if __name__ == '__main__':
    train_q75()