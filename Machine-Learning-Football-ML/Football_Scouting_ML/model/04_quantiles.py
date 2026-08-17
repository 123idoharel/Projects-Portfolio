"""
04_quantiles.py — Stage 4: Train quantile models with isotonic calibration.

Trains three separate quantile models on the RATIO target:
  - Pessimistic (q=0.10): "high-confidence floor" trajectory
  - Expected    (q=0.50): median trajectory — most likely outcome
  - Optimistic  (q=0.90): "if everything clicks" upside trajectory

Each quantile is tuned separately with pinball loss as the optimization
objective. Stronger regularization than the mean model because extreme
quantiles are sensitive to outliers (n_min_child_weight 5-50 vs 1-20).

After training, runs a calibration check on OOF predictions. If actual
coverage drifts more than 3% from target quantile, fits an isotonic
regression to recalibrate. Calibrators are saved alongside params and
applied at inference time (in 07_inference.py).

Note: at inference, predicted_ratio is composed back to absolute EUR via
setup.compose_prediction(). The final output for scouts is:
  predicted_pessimistic_eur = expm1(log_mv_end + iso_q10(model_q10.predict(X)))
  predicted_expected_eur    = expm1(log_mv_end + iso_q50(model_q50.predict(X)))
  predicted_optimistic_eur  = expm1(log_mv_end + iso_q90(model_q90.predict(X)))
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

QUANTILES = {'pessimistic': 0.10, 'expected': 0.50, 'optimistic': 0.90}
N_TRIALS  = 30
N_FOLDS   = 5


def tune_quantile(q, X, y, groups):
    """Run Optuna for one quantile; returns best params dict."""
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
            'tree_method': 'hist',
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


def train_all_quantile_models():
    vectors = setup.load_vectors()
    X, y, groups = setup.split_features_target(vectors)

    quantile_params = {}
    quantile_oof    = {}

    # Tune and OOF for each quantile
    for label, q in QUANTILES.items():
        print(f"\n=== Tuning {label} model (q={q}) ===")
        params = tune_quantile(q, X, y, groups)
        params.update({
            'objective': 'reg:quantileerror', 'quantile_alpha': q,
            'n_estimators': 3000, 'enable_categorical': True, 'random_state': 42,
        })
        quantile_params[label] = params

        # Compute OOF for calibration check
        gkf = GroupKFold(n_splits=N_FOLDS)
        oof = np.zeros(len(X))
        for tr, va in gkf.split(X, y, groups):
            m = xgb.XGBRegressor(**params, early_stopping_rounds=50)
            m.fit(X.iloc[tr], y.iloc[tr],
                  eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
            oof[va] = m.predict(X.iloc[va])
        quantile_oof[label] = oof

    # Calibration check + isotonic recalibration where needed
    print("\n" + "="*60)
    print("CALIBRATION CHECK & FIX")
    print("="*60)

    calibrators = {}
    for label, q in QUANTILES.items():
        pct_below = (y.values <= quantile_oof[label]).mean() * 100
        target_pct = q * 100
        diff = pct_below - target_pct

        if abs(diff) > 3:
            print(f"  ⚠ {label} drift {diff:+.1f}%. Applying isotonic calibration.")
            iso = IsotonicRegression(out_of_bounds='clip')
            iso.fit(quantile_oof[label], y.values)
            calibrators[label] = iso

            # Verify post-calibration coverage
            adjusted = iso.transform(quantile_oof[label])
            new_pct = (y.values <= adjusted).mean() * 100
            print(f"    post-calibration coverage: {new_pct:.1f}% (target {target_pct:.0f}%)")
        else:
            print(f"  ✓ {label} calibration solid (actual {pct_below:.1f}%, target {target_pct:.0f}%).")
            calibrators[label] = None

    # 80% prediction interval coverage (pessimistic to optimistic)
    coverage_80 = ((y.values >= quantile_oof['pessimistic']) &
                   (y.values <= quantile_oof['optimistic'])).mean() * 100
    print(f"\n  80% prediction interval coverage: {coverage_80:.1f}% (target 80%)")

    joblib.dump(quantile_params, setup.MODEL_DIR / "best_params_quantiles.pkl")
    joblib.dump(calibrators,     setup.MODEL_DIR / "quantile_calibrators.pkl")
    np.savez(setup.MODEL_DIR / "quantile_oof.npz",
             pessimistic=quantile_oof['pessimistic'],
             expected=quantile_oof['expected'],
             optimistic=quantile_oof['optimistic'])
    print(f"\nSaved quantile params, calibrators, and OOF predictions to {setup.MODEL_DIR}")


if __name__ == '__main__':
    train_all_quantile_models()