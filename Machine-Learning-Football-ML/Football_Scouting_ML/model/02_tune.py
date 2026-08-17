"""
02_tune_mean.py — Stage 2: Optuna hyperparameter tuning for the mean model.

Trains many candidate configurations of XGBRegressor on 5-fold GroupKFold
splits, each evaluated by pinball-equivalent MAE on the RATIO target.

Outputs:
  - models/best_params_mean.pkl — winning hyperparameters
  - results/stage2_oof_tuned.parquet — OOF predictions with best params

Time budget: ~2 hours for 50 trials. You can reduce N_TRIALS to 30 if needed
(slightly worse final MAE but ~40% faster).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import optuna
import xgboost as xgb
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error
import numpy as np
import joblib
import pandas as pd

# Tuning configuration
N_TRIALS = 50      # number of Optuna trials
N_FOLDS  = 5       # number of CV folds


def objective(trial, X, y, groups):
    """One Optuna trial: pick params, run 5-fold CV, return mean MAE."""
    params = {
        'max_depth':         trial.suggest_int('max_depth', 4, 8),
        'learning_rate':     trial.suggest_float('learning_rate', 0.02, 0.1, log=True),
        'min_child_weight':  trial.suggest_int('min_child_weight', 1, 20),
        'subsample':         trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree':  trial.suggest_float('colsample_bytree', 0.5, 1.0),
        'reg_alpha':         trial.suggest_float('reg_alpha', 0.0, 5.0),
        'reg_lambda':        trial.suggest_float('reg_lambda', 1.0, 10.0),
        'n_estimators':      3000,
        'eval_metric':       'mae',
        'enable_categorical': True,
        'random_state':      42,
    }

    gkf = GroupKFold(n_splits=N_FOLDS)
    fold_maes = []
    for tr, va in gkf.split(X, y, groups):
        m = xgb.XGBRegressor(**params, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        preds = m.predict(X.iloc[va])
        fold_maes.append(mean_absolute_error(y.iloc[va], preds))
    return np.mean(fold_maes)


def run_tuning():
    vectors = setup.load_vectors()
    X, y, groups = setup.split_features_target(vectors)

    print(f"\nTuning XGBRegressor over {N_TRIALS} trials × {N_FOLDS} folds...")
    print(f"Target: log-ratio (log_target - log_mv_end)")
    print(f"Optimization metric: MAE on ratio\n")

    study = optuna.create_study(direction='minimize')
    study.optimize(
        lambda trial: objective(trial, X, y, groups),
        n_trials=N_TRIALS,
        show_progress_bar=True,
    )

    best_params = study.best_params
    best_params.update({
        'n_estimators': 3000, 'eval_metric': 'mae',
        'enable_categorical': True, 'random_state': 42,
    })
    print(f"\n{'='*60}")
    print(f"Best CV MAE: {study.best_value:.4f}")
    print(f"{'='*60}")
    print(f"Best params: {best_params}")

    # Recompute OOF with the winning params (for downstream Stage 3)
    print(f"\nComputing final OOF predictions with best params...")
    gkf = GroupKFold(n_splits=N_FOLDS)
    oof_preds = np.zeros(len(X))
    for fold, (tr, va) in enumerate(gkf.split(X, y, groups)):
        m = xgb.XGBRegressor(**best_params, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        oof_preds[va] = m.predict(X.iloc[va])
        print(f"  Fold {fold+1}: MAE={mean_absolute_error(y.iloc[va], oof_preds[va]):.4f}")

    # Save artifacts
    joblib.dump(best_params, setup.MODEL_DIR / "best_params_mean.pkl")

    # Save OOF aligned with the original vectors (so Stage 3 can join on tm_id+cutoff)
    valid = vectors[vectors['log_target'].notna() & 
                    (vectors['log_target'] - vectors['log_mv_end']).notna() &
                    (~np.isinf(vectors['log_target'] - vectors['log_mv_end']))]
    oof_df = pd.DataFrame({
        'tm_id':           valid['tm_id'].values,
        'cutoff_year':     valid['cutoff_year'].values,
        'log_target':      valid['log_target'].values,
        'log_mv_end':      valid['log_mv_end'].values,
        'y_ratio':         y.values,
        'oof_pred_ratio':  oof_preds,
    })
    oof_df.to_parquet(setup.RESULT_DIR / "stage2_oof_tuned.parquet", index=False)

    final_mae = mean_absolute_error(y, oof_preds)
    print(f"\nFinal MAE (production estimate): {final_mae:.4f}")
    print(f"Saved best params to {setup.MODEL_DIR / 'best_params_mean.pkl'}")
    print(f"Saved OOF predictions to {setup.RESULT_DIR / 'stage2_oof_tuned.parquet'}")


if __name__ == '__main__':
    run_tuning()