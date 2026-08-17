"""
04_quantiles_mh.py — Stage 4: Per-horizon quantile model training.

Trains 3 quantile models (q=0.10, 0.50, 0.90) for the chosen horizon and
verifies coverage. If coverage drifts more than 3% from target, fits an
isotonic calibrator.

Usage:
    python 04_quantiles_mh.py --horizon 1y
    python 04_quantiles_mh.py --horizon 2y

Outputs:
    models_mh/{horizon}/best_params_quantiles.pkl
    models_mh/{horizon}/quantile_calibrators.pkl
    models_mh/{horizon}/quantile_oof.npz

Time: ~3 hours per horizon (30 trials × 3 quantiles × 5 folds).
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

# הגדרת נתיב יחסי ל-setup_mh
sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

QUANTILES = {'pessimistic': 0.10, 'expected': 0.50, 'optimistic': 0.90}
N_TRIALS  = 30
N_FOLDS   = 5

def pinball_loss(y_true, y_pred, quantile):
    """
    חישוב Pinball Loss המותאם ללמידה בגישת קוונטילים.
    מקפיד ששגיאה בכיוון הלא רצוי תקבל קנס גבוה יותר.
    """
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

def train_all_quantile_models(horizon: str):
    print("=" * 60)
    print(f"STAGE 4 — QUANTILE TRAINING FOR HORIZON {horizon.upper()}")
    print("=" * 60)

    # 1. טעינת הנתונים דרך פונקציית הנתב שלנו
    vectors = setup_mh.load_vectors_mh()
    X, y, groups = setup_mh.split_features_target_mh(vectors, horizon)

    quantile_params = {}
    quantile_oof    = {}

    # 2. אימון (Tuning) לכל קוונטיל בנפרד
    for label, q in QUANTILES.items():
        print(f"\n=== Tuning {label} (q={q}, horizon={horizon}) ===")
        params = tune_quantile(q, X, y, groups)
        params.update({
            'objective': 'reg:quantileerror', 'quantile_alpha': q,
            'n_estimators': 3000, 'enable_categorical': True,
            'random_state': 42, 'tree_method': 'hist',
        })
        quantile_params[label] = params

        gkf = GroupKFold(n_splits=N_FOLDS)
        oof = np.zeros(len(X))
        for tr, va in gkf.split(X, y, groups):
            m = xgb.XGBRegressor(**params, early_stopping_rounds=50)
            m.fit(X.iloc[tr], y.iloc[tr],
                  eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
            oof[va] = m.predict(X.iloc[va])
        quantile_oof[label] = oof

    # 3. בדיקת כיול (Calibration Check)
    print("\n" + "=" * 60)
    print(f"CALIBRATION CHECK (horizon={horizon})")
    print("=" * 60)

    calibrators = {}
    for label, q in QUANTILES.items():
        pct_below = (y.values <= quantile_oof[label]).mean() * 100
        target_pct = q * 100
        diff = pct_below - target_pct
        
        # אם יש סחיפה של מעל 3% (המטרה מתפספסת קבוע), המערכת מפעילה איזון.
        if abs(diff) > 3:
            print(f"  ⚠ {label} drift {diff:+.1f}%. Applying isotonic calibration.")
            iso = IsotonicRegression(out_of_bounds='clip')
            iso.fit(quantile_oof[label], y.values)
            calibrators[label] = iso
            adjusted = iso.transform(quantile_oof[label])
            new_pct = (y.values <= adjusted).mean() * 100
            print(f"    post-calibration coverage: {new_pct:.1f}% (target {target_pct:.0f}%)")
        else:
            print(f"  ✓ {label} calibration solid (actual {pct_below:.1f}%, target {target_pct:.0f}%).")
            calibrators[label] = None

    # חישוב אחוז הכיסוי הכולל (כמה שחקנים באמת נפלו בטווח ה-80%)
    coverage_80 = ((y.values >= quantile_oof['pessimistic']) &
                   (y.values <= quantile_oof['optimistic'])).mean() * 100
    print(f"\n  80% prediction interval coverage: {coverage_80:.1f}% (target 80%)")

    # 4. שמירה
    model_dir = setup_mh.MODELS_MH_DIR / horizon
    model_dir.mkdir(parents=True, exist_ok=True)
    
    joblib.dump(quantile_params, model_dir / "best_params_quantiles.pkl")
    joblib.dump(calibrators,     model_dir / "quantile_calibrators.pkl")
    np.savez(model_dir / "quantile_oof.npz",
             pessimistic=quantile_oof['pessimistic'],
             expected=quantile_oof['expected'],
             optimistic=quantile_oof['optimistic'])
             
    print(f"\nSaved quantile artifacts to {model_dir}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    train_all_quantile_models(args.horizon)