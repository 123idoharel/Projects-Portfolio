"""
02_tune_mh.py — Stage 2: Optuna hyperparameter tuning for Multi-Horizon models.

This version is fully aligned with Stage 3:
1. Finds best hyperparameters via Optuna.
2. Re-computes Out-Of-Fold (OOF) predictions using those parameters.
3. Saves both best_params_mean.pkl AND stage2_oof_tuned.parquet.
"""
import argparse
import joblib
import optuna
import xgboost as xgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error
import setup_mh

# Tuning configuration
N_TRIALS = 50      # Number of Optuna trials
N_FOLDS  = 5       # Number of CV folds

def objective(trial, X, y, groups):
    """One Optuna trial: pick params, run 5-fold CV, return mean MAE."""
    params = {
        'max_depth':         trial.suggest_int('max_depth', 4, 8),
        'learning_rate':     trial.suggest_float('learning_rate', 0.01, 0.1, log=True),
        'n_estimators':      3000, # Use a high number with early stopping
        'min_child_weight':  trial.suggest_int('min_child_weight', 1, 20),
        'subsample':         trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree':  trial.suggest_float('colsample_bytree', 0.5, 1.0),
        'reg_alpha':         trial.suggest_float('reg_alpha', 0.0, 5.0),
        'reg_lambda':        trial.suggest_float('reg_lambda', 1.0, 10.0),
        'tree_method':       'hist',
        'enable_categorical': True,
        'random_state':      42
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', type=str, required=True, choices=['1y', '2y'])
    args = parser.parse_args()
    horizon = args.horizon

    # הקצאת תיקיות נכונות לפי האופק
    model_dir = setup_mh.MODELS_MH_DIR / horizon
    res_dir = setup_mh.RESULTS_MH_DIR / horizon
    model_dir.mkdir(parents=True, exist_ok=True)
    res_dir.mkdir(parents=True, exist_ok=True)

    vectors = setup_mh.load_vectors_mh()
    X, y, groups = setup_mh.split_features_target_mh(vectors, horizon)

    print(f"\n{'='*60}\nTUNING {horizon.upper()} MODEL: {N_TRIALS} trials × {N_FOLDS} folds\n{'='*60}")
    
    study = optuna.create_study(direction='minimize')
    study.optimize(lambda t: objective(t, X, y, groups), n_trials=N_TRIALS)

    # 1. שמירת הפרמטרים המנצחים
    best_params = study.best_params
    best_params.update({
        'n_estimators': 3000, 'tree_method': 'hist',
        'enable_categorical': True, 'random_state': 42
    })
    
    params_path = model_dir / "best_params_mean.pkl"
    joblib.dump(best_params, params_path)
    print(f"\n✓ Saved best params to {params_path}")

    # 2. חישוב OOF סופי עבור Stage 3 (Segmented Eval)
    print(f"\nComputing final OOF predictions for {horizon.upper()} evaluation...")
    gkf = GroupKFold(n_splits=N_FOLDS)
    oof_preds = np.zeros(len(X))
    
    for fold, (tr, va) in enumerate(gkf.split(X, y, groups)):
        m = xgb.XGBRegressor(**best_params, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        oof_preds[va] = m.predict(X.iloc[va])
        print(f"  Fold {fold+1}: MAE={mean_absolute_error(y.iloc[va], oof_preds[va]):.4f}")

    # 3. שמירת קובץ ה-OOF במבנה שסקריפט 03 מצפה לו
    oof_df = pd.DataFrame({
        'tm_id':           vectors.loc[X.index, 'tm_id'].values,
        'cutoff_year':     vectors.loc[X.index, 'cutoff_year'].values,
        'oof_pred_ratio':  oof_preds
    })
    
    oof_path = res_dir / "stage2_oof_tuned.parquet"
    oof_df.to_parquet(oof_path, index=False)
    
    print(f"\n{'='*40}")
    print(f"Horizon {horizon.upper()} Complete!")
    print(f"Best CV MAE: {study.best_value:.4f}")
    print(f"Saved OOF to: {oof_path}")
    print(f"{'='*40}\n")

if __name__ == "__main__":
    run_tuning()