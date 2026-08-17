"""
05_production.py — Stage 5: Train final production models on FULL dataset.

Trains 4 models with locked hyperparameters from Stages 2 and 4:
  - Mean / point-estimate model (best_params_mean.pkl)
  - Pessimistic q=0.10 model
  - Expected     q=0.50 model
  - Optimistic   q=0.90 model

CRITICAL: n_estimators handling
  Tuning (Stage 2/4) used early stopping to find the optimal tree count per
  fold. The saved hyperparameters have n_estimators=3000 as a CEILING, not
  the actual count used. If we naively train production with n_estimators=3000
  and no early stopping, the model will train all 3000 trees and likely
  overfit.

  Solution: do an internal 80/20 split BEFORE the final fit, with early
  stopping on the 20%. Use the mean best_iteration from a 3-fold check to
  determine the right n_estimators for production. Then refit on 100% data
  using that fixed count.

  This is the standard "production-ready" XGBoost workflow.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import numpy as np
import joblib
import xgboost as xgb
from sklearn.model_selection import GroupKFold


def determine_optimal_n_trees(X, y, groups, params, n_check_folds=3):
    """
    Run a quick CV check with early stopping to determine the optimal
    n_estimators. Returns the mean best_iteration across folds, plus 10% buffer.
    """
    params_check = {**params}
    params_check['n_estimators'] = 3000  # ceiling, early stopping decides actual

    gkf = GroupKFold(n_splits=n_check_folds)
    best_iters = []
    for tr, va in gkf.split(X, y, groups):
        m = xgb.XGBRegressor(**params_check, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        best_iters.append(m.best_iteration)

    mean_best = int(np.mean(best_iters))
    # +10% buffer because production trains on ~17% MORE data than the CV folds
    buffered = int(mean_best * 1.1)
    return buffered, best_iters


def train_production_models():
    vectors = setup.load_vectors()
    X, y, groups = setup.split_features_target(vectors)

    print(f"Training final production models on {len(X)} rows...\n")

    best_params_mean      = joblib.load(setup.MODEL_DIR / "best_params_mean.pkl")
    best_params_quantiles = joblib.load(setup.MODEL_DIR / "best_params_quantiles.pkl")

    production = {}
    optimal_iters = {}

    # ----- Mean model -----
    print("=== Mean model ===")
    print("  Determining optimal n_estimators via 3-fold CV check...")
    n_trees, fold_iters = determine_optimal_n_trees(X, y, groups, best_params_mean)
    print(f"  Per-fold best_iteration: {fold_iters}")
    print(f"  Mean: {int(np.mean(fold_iters))}, with +10% buffer: {n_trees}")

    params_final = {**best_params_mean}
    params_final['n_estimators'] = n_trees
    params_final.pop('early_stopping_rounds', None)
    print(f"  Training final on full data with n_estimators={n_trees}...")
    production['mean'] = xgb.XGBRegressor(**params_final)
    production['mean'].fit(X, y)
    optimal_iters['mean'] = n_trees

    # ----- Quantile models -----
    for label, params in best_params_quantiles.items():
        print(f"\n=== {label} model ===")
        print(f"  Determining optimal n_estimators via 3-fold CV check...")
        n_trees, fold_iters = determine_optimal_n_trees(X, y, groups, params)
        print(f"  Per-fold best_iteration: {fold_iters}")
        print(f"  Mean: {int(np.mean(fold_iters))}, with +10% buffer: {n_trees}")

        params_final = {**params}
        params_final['n_estimators'] = n_trees
        params_final['tree_method']  = 'hist'  # speed
        params_final.pop('early_stopping_rounds', None)
        print(f"  Training final on full data with n_estimators={n_trees}...")
        production[label] = xgb.XGBRegressor(**params_final)
        production[label].fit(X, y)
        optimal_iters[label] = n_trees

    # Save artifacts
    joblib.dump(production, setup.MODEL_DIR / "production_attacker_v1.pkl")
    joblib.dump(optimal_iters, setup.MODEL_DIR / "production_optimal_iters.pkl")

    print(f"\n{'='*60}")
    print(f"Saved 4 production models to {setup.MODEL_DIR / 'production_attacker_v1.pkl'}")
    print(f"Optimal n_estimators per model:")
    for label, n in optimal_iters.items():
        print(f"  {label}: {n}")


if __name__ == '__main__':
    train_production_models()