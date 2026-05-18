"""
05q_q75_production.py — Train final q75 production model on FULL dataset.

Reads best_params_q75.pkl, runs internal CV check to find optimal n_estimators
(same logic as 05_production.py), then fits on 100% of the training data.

Adds the resulting model to the existing production_attacker_v1.pkl dict
under the key 'q75' — does NOT overwrite or affect the existing
mean/pessimistic/expected/optimistic models. Old code that loads the dict
and accesses ['mean'], ['pessimistic'] etc. continues to work unchanged.
The new q75 model is available as production['q75'] for code that wants it.

Usage:
    python 05q_q75_production.py
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
    params_check = {**params, 'n_estimators': 3000}
    gkf = GroupKFold(n_splits=n_check_folds)
    best_iters = []
    for tr, va in gkf.split(X, y, groups):
        m = xgb.XGBRegressor(**params_check, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        best_iters.append(m.best_iteration)
    mean_best = int(np.mean(best_iters))
    return int(mean_best * 1.1), best_iters


def train_q75_production():
    vectors = setup.load_vectors()
    X, y, groups = setup.split_features_target(vectors)

    print(f"Training q75 production model on {len(X)} rows...\n")
    best_params_q75 = joblib.load(setup.MODEL_DIR / "best_params_q75.pkl")

    print("=== q75 model ===")
    print("  Determining optimal n_estimators via 3-fold CV check...")
    n_trees, fold_iters = determine_optimal_n_trees(X, y, groups, best_params_q75)
    print(f"  Per-fold best_iteration: {fold_iters}")
    print(f"  Mean: {int(np.mean(fold_iters))}, with +10% buffer: {n_trees}")

    params_final = {**best_params_q75, 'n_estimators': n_trees, 'tree_method': 'hist'}
    params_final.pop('early_stopping_rounds', None)
    print(f"  Training final on full data with n_estimators={n_trees}...")
    q75_model = xgb.XGBRegressor(**params_final)
    q75_model.fit(X, y)

    # Load existing production dict and add q75 (no destruction of existing keys)
    prod_path = setup.MODEL_DIR / "production_attacker_v1.pkl"
    if prod_path.exists():
        production = joblib.load(prod_path)
        print(f"\n  Existing production dict has keys: {list(production.keys())}")
    else:
        production = {}
        print(f"\n  No existing production dict found, creating new one")

    production['q75'] = q75_model
    joblib.dump(production, prod_path)
    print(f"  Updated production dict now has keys: {list(production.keys())}")

    # Append to optimal_iters log
    iters_path = setup.MODEL_DIR / "production_optimal_iters.pkl"
    if iters_path.exists():
        optimal_iters = joblib.load(iters_path)
    else:
        optimal_iters = {}
    optimal_iters['q75'] = n_trees
    joblib.dump(optimal_iters, iters_path)

    print(f"\n{'='*60}")
    print(f"q75 model added to {prod_path}")
    print(f"q75 n_estimators: {n_trees}")
    print(f"\nNext: update 07_inference.py to apply q75 model + calibrator.")
    print(f"      See the patch instructions in q75_inference_patch.md")


if __name__ == '__main__':
    train_q75_production()