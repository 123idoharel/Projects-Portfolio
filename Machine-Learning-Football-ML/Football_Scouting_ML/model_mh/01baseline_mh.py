"""
01_baseline_mh.py — Diagnostic baseline for a specific horizon.
Usage: python 01_baseline_mh.py --horizon 1y
"""
import argparse
import xgboost as xgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error
import setup_mh

def run_baseline():
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', type=str, required=True, choices=['1y', '2y'])
    args = parser.parse_args()
    horizon = args.horizon

    print(f"\n{'='*60}\nBASELINE AUDIT FOR HORIZON: {horizon.upper()}\n{'='*60}")
    
    # 1. טעינת הנתונים דרך ה-Setup המאושר שלנו
    vectors = setup_mh.load_vectors_mh()
    X, y, groups = setup_mh.split_features_target_mh(vectors, horizon)

    # 2. חלוקה לקבוצות (כדי שאותו שחקן לא יהיה גם באימון וגם במבחן באותו חיתוך)
    gkf = GroupKFold(n_splits=5)
    oof_preds = np.zeros(len(y))
    
    # 3. אימון מהיר על פרמטרים התחלתיים
    for fold, (tr, va) in enumerate(gkf.split(X, y, groups)):
        model = xgb.XGBRegressor(
            enable_categorical=True, 
            tree_method='hist',
            random_state=42
        )
        model.fit(X.iloc[tr], y.iloc[tr])
        oof_preds[va] = model.predict(X.iloc[va])
        
        fold_mae = mean_absolute_error(y.iloc[va], oof_preds[va])
        print(f"  Fold {fold+1}: MAE = {fold_mae:.4f}")

    # 4. התוצאה הסופית
    print(f"\n{'='*30}")
    print(f"CV MAE ({horizon.upper()}): {mean_absolute_error(y, oof_preds):.4f}")
    print(f"{'='*30}\n")

if __name__ == "__main__":
    run_baseline()