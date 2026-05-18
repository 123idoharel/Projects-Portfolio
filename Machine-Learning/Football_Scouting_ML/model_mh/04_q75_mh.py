"""
04q_q75_mh.py — Multi-horizon q75 quantile training (1y or 2y).

Same idea as 04q_q75.py but for the multi-horizon track. Trains q=0.75 model
for the chosen horizon, with calibration check, alongside the existing
quantile artifacts.

Usage:
    python 04q_q75_mh.py --horizon 1y
    python 04q_q75_mh.py --horizon 2y

Outputs:
    models_mh/{horizon}/best_params_q75.pkl
    models_mh/{horizon}/q75_calibrator.pkl
    models_mh/{horizon}/q75_oof.npy

Time: ~1 hour per horizon.
"""
import sys
import argparse
from pathlib import Path
import optuna
import xgboost as xgb
from sklearn.model_selection import GroupKFold
from sklearn.isotonic import IsotonicRegression
import numpy as np
import joblib

sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

QUANTILE_LABEL = 'q75'
QUANTILE_ALPHA = 0.75
N_TRIALS = 30
N_FOLDS  = 5


def pinball_loss(y_true, y_pred, quantile):
    err = y_true - y_pred
    return np.mean(np.maximum(quantile * err, (quantile - 1) * err))


def tune_quantile(q, X, y, groups):
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
            losses.append(pinball_loss(y.iloc[va].values, preds, q))
        return np.mean(losses)

    study = optuna.create_study(direction='minimize')
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    return study.best_params


def train_q75(horizon: str):
    print("=" * 60)
    print(f"STAGE 4-Q75 (MH) — TRAINING q75 FOR HORIZON {horizon.upper()}")
    print("=" * 60)

    vectors = setup_mh.load_vectors_mh()
    X, y, groups = setup_mh.split_features_target_mh(vectors, horizon)
    print(f"Training data: {len(X)} rows × {X.shape[1]} columns\n")

    print(f"=== Tuning {QUANTILE_LABEL} (q={QUANTILE_ALPHA}, horizon={horizon}) ===")
    params = tune_quantile(QUANTILE_ALPHA, X, y, groups)
    params.update({
        'objective': 'reg:quantileerror', 'quantile_alpha': QUANTILE_ALPHA,
        'n_estimators': 3000, 'enable_categorical': True,
        'random_state': 42, 'tree_method': 'hist',
    })

    print("\nGenerating OOF predictions for calibration check...")
    gkf = GroupKFold(n_splits=N_FOLDS)
    oof = np.zeros(len(X))
    for fold, (tr, va) in enumerate(gkf.split(X, y, groups), 1):
        m = xgb.XGBRegressor(**params, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        oof[va] = m.predict(X.iloc[va])
        print(f"  fold {fold}/{N_FOLDS} done")

    print("\n" + "=" * 60)
    print(f"CALIBRATION CHECK (horizon={horizon})")
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

    model_dir = setup_mh.MODELS_MH_DIR / horizon
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(params,     model_dir / "best_params_q75.pkl")
    joblib.dump(calibrator, model_dir / "q75_calibrator.pkl")
    np.save(model_dir / "q75_oof.npy", oof)

    print(f"\nSaved q75 artifacts to {model_dir}")
    print("\nNext: python 05q_q75_production_mh.py --horizon", horizon)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    train_q75(args.horizon)