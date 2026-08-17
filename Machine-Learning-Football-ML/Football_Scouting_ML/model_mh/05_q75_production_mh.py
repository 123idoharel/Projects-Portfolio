"""
05q_q75_production_mh.py — Train final q75 production model for MH track.

Same logic as 05_production_mh.py for the q75 quantile only.

Usage:
    python 05q_q75_production_mh.py --horizon 1y
    python 05q_q75_production_mh.py --horizon 2y

Output:
    models_mh/{horizon}/final_model_quantile_q75.json
    models_mh/{horizon}/production_optimal_iters.pkl   (updated)
"""
import sys
import argparse
from pathlib import Path
import numpy as np
import joblib
import xgboost as xgb
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).parent))
import setup_mh


def determine_optimal_n_trees(X, y, groups, params, n_check_folds=3):
    params_check = {**params, 'n_estimators': 3000,
                    'tree_method': 'hist', 'enable_categorical': True}
    gkf = GroupKFold(n_splits=n_check_folds)
    best_iters = []
    for tr, va in gkf.split(X, y, groups):
        m = xgb.XGBRegressor(**params_check, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        best_iters.append(m.best_iteration)
    mean_best = int(np.mean(best_iters))
    return int(mean_best * 1.1), best_iters


def train_q75_production(horizon: str):
    print(f"\n{'='*60}\nSTAGE 5-Q75 (MH) — q75 PRODUCTION FOR HORIZON {horizon.upper()}\n{'='*60}")

    vectors = setup_mh.load_vectors_mh()
    X, y, groups = setup_mh.split_features_target_mh(vectors, horizon)
    print(f"Training final q75 model on {len(X)} rows...\n")

    model_dir = setup_mh.MODELS_MH_DIR / horizon
    best_params_q75 = joblib.load(model_dir / "best_params_q75.pkl")

    print("=== q75 model ===")
    print("  Determining optimal n_estimators via 3-fold CV check...")
    q_params = {**best_params_q75,
                'objective': 'reg:quantileerror', 'quantile_alpha': 0.75}
    n_trees, fold_iters = determine_optimal_n_trees(X, y, groups, q_params)
    print(f"  Per-fold best_iteration: {fold_iters}")
    print(f"  Mean: {int(np.mean(fold_iters))}, with +10% buffer: {n_trees}")

    params_final = {**q_params, 'n_estimators': n_trees,
                    'tree_method': 'hist', 'enable_categorical': True}
    params_final.pop('early_stopping_rounds', None)

    print(f"  Training final on full data with n_estimators={n_trees}...")
    q_model = xgb.XGBRegressor(**params_final)
    q_model.fit(X, y)
    q_model.save_model(model_dir / "final_model_quantile_q75.json")

    iters_path = model_dir / "production_optimal_iters.pkl"
    if iters_path.exists():
        optimal_iters = joblib.load(iters_path)
    else:
        optimal_iters = {}
    optimal_iters['q75'] = n_trees
    joblib.dump(optimal_iters, iters_path)

    print(f"\n{'='*60}")
    print(f"q75 model saved to {model_dir / 'final_model_quantile_q75.json'}")
    print(f"q75 n_estimators: {n_trees}")
    print(f"\nNext: load this in 07inference_mh.py via the patch instructions.")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    train_q75_production(args.horizon)