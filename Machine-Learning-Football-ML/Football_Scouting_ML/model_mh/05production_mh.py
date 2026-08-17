"""
05_production_mh.py — Stage 5: Train final production models on FULL dataset.

Trains 4 models per horizon (Mean, q10, q50, q90) with locked hyperparameters.
Uses an internal CV check to determine the optimal number of trees (n_estimators)
before fitting on 100% of the data.

Usage:
    python 05_production_mh.py --horizon 1y
    python 05_production_mh.py --horizon 2y
"""
import sys
import argparse
from pathlib import Path
import numpy as np
import joblib
import xgboost as xgb
from sklearn.model_selection import GroupKFold

# הגדרת נתיב יחסי ל-setup_mh
sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

def determine_optimal_n_trees(X, y, groups, params, n_check_folds=3):
    """
    מריץ בדיקה מהירה עם חלוקה פנימית ועצירה מוקדמת כדי למצוא כמה עצים
    המודל באמת צריך. מחזיר את הממוצע + 10% מקדם ביטחון.
    """
    params_check = {**params}
    params_check['n_estimators'] = 3000  # תקרה, אבל הוא יעצור מוקדם
    params_check['tree_method'] = 'hist'
    params_check['enable_categorical'] = True

    gkf = GroupKFold(n_splits=n_check_folds)
    best_iters = []
    
    for tr, va in gkf.split(X, y, groups):
        m = xgb.XGBRegressor(**params_check, early_stopping_rounds=50)
        m.fit(X.iloc[tr], y.iloc[tr],
              eval_set=[(X.iloc[va], y.iloc[va])], verbose=False)
        best_iters.append(m.best_iteration)

    mean_best = int(np.mean(best_iters))
    # תוספת של 10% כיוון שבייצור המודל מתאמן על 100% מהנתונים במקום על חלקי אימון
    buffered_n_trees = int(mean_best * 1.1)
    return buffered_n_trees, best_iters

def train_production_models(horizon: str):
    print(f"\n{'='*60}\nSTAGE 5: TRAINING PRODUCTION MODELS FOR HORIZON {horizon.upper()}\n{'='*60}")
    
    vectors = setup_mh.load_vectors_mh()
    X, y, groups = setup_mh.split_features_target_mh(vectors, horizon)
    print(f"Training final production models on {len(X)} rows...\n")

    model_dir = setup_mh.MODELS_MH_DIR / horizon
    
    best_params_mean      = joblib.load(model_dir / "best_params_mean.pkl")
    best_params_quantiles = joblib.load(model_dir / "best_params_quantiles.pkl")

    optimal_iters = {}

    # ---------------------------------------------------------
    # 1. אימון מודל הממוצע (Mean model)
    # ---------------------------------------------------------
    print("=== Mean model ===")
    print("  Determining optimal n_estimators via 3-fold CV check...")
    n_trees, fold_iters = determine_optimal_n_trees(X, y, groups, best_params_mean)
    print(f"  Per-fold best_iteration: {fold_iters}")
    print(f"  Mean: {int(np.mean(fold_iters))}, with +10% buffer: {n_trees}")

    params_final = {**best_params_mean}
    params_final.update({
        'n_estimators': n_trees,
        'tree_method': 'hist',
        'enable_categorical': True
    })
    
    # מוחקים בטיחותית את early_stopping כדי שהמודל ירוץ עד הסוף
    params_final.pop('early_stopping_rounds', None) 
    
    print(f"  Training final on full data with n_estimators={n_trees}...")
    mean_model = xgb.XGBRegressor(**params_final)
    mean_model.fit(X, y)
    mean_model.save_model(model_dir / "final_model_mean.json")
    optimal_iters['mean'] = n_trees

    # ---------------------------------------------------------
    # 2. אימון מודלי הקוונטילים
    # ---------------------------------------------------------
    for label, params in best_params_quantiles.items():
        print(f"\n=== {label.capitalize()} Quantile ===")
        print(f"  Determining optimal n_estimators via 3-fold CV check...")
        
        # מוודאים שפרמטרי הקוונטיל יושבים נכון גם בבדיקה
# מוודאים שפרמטרי הקוונטיל יושבים נכון גם בבדיקה
        quantiles_dict = {'pessimistic': 0.10, 'expected': 0.50, 'optimistic': 0.90}
        q_params = {**params, 'objective': 'reg:quantileerror', 'quantile_alpha': quantiles_dict[label]}
                
        n_trees, fold_iters = determine_optimal_n_trees(X, y, groups, q_params)
        print(f"  Per-fold best_iteration: {fold_iters}")
        print(f"  Mean: {int(np.mean(fold_iters))}, with +10% buffer: {n_trees}")

        params_final = {**q_params}
        params_final.update({
            'n_estimators': n_trees,
            'tree_method': 'hist',
            'enable_categorical': True
        })
        params_final.pop('early_stopping_rounds', None)
        
        print(f"  Training final on full data with n_estimators={n_trees}...")
        q_model = xgb.XGBRegressor(**params_final)
        q_model.fit(X, y)
        q_model.save_model(model_dir / f"final_model_quantile_{label}.json")
        optimal_iters[label] = n_trees

    # שמירת יומן עזר עם מספר העצים לתיעוד
    joblib.dump(optimal_iters, model_dir / "production_optimal_iters.pkl")

    print(f"\n{'='*60}")
    print(f"Saved 4 final production models to {model_dir}")
    print(f"Optimal n_estimators locked:")
    for label, n in optimal_iters.items():
        print(f"  {label}: {n} trees")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    train_production_models(args.horizon)