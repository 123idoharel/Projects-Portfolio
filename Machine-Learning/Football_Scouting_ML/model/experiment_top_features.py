"""
experiment_top50.py — Ablation Study: Does pruning features improve the model?
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import GroupKFold
from sklearn.metrics import mean_absolute_error

def run_experiment():
    print("="*60)
    print("EXPERIMENT: TOP 50 FEATURES vs ALL (Ablation Study)")
    print("="*60)
    
    # 1. טעינת הנתונים
    vectors = setup.load_vectors()
    X, y, groups = setup.split_features_target(vectors)
    
    # 2. אימון מודל מהיר כדי להוציא את רשימת החשיבות
    print("Training full model to determine feature importance...")
    base_model = xgb.XGBRegressor(
        n_estimators=1000, learning_rate=0.05, max_depth=6,
        enable_categorical=True, random_state=42, tree_method='hist'
    )
    base_model.fit(X, y)
    
    # 3. מציאת הטופ 50
    importance = base_model.feature_importances_
    top_indices = np.argsort(importance)[::-1][:150]
    top_features = X.columns[top_indices]
    
    print("\nTop 10 features selected:")
    print(top_features[:10].tolist())
    
    # 4. חיתוך הדאטא
    X_pruned = X[top_features]
    print(f"\nEvaluating with {X_pruned.shape[1]} features...")
    
    # 5. הערכת המודל החתוך (5 Folds)
    gkf = GroupKFold(n_splits=5)
    fold_maes = []
    
    for tr_idx, va_idx in gkf.split(X_pruned, y, groups):
        model = xgb.XGBRegressor(
            n_estimators=1000, learning_rate=0.05, max_depth=6,
            enable_categorical=True, random_state=42, tree_method='hist'
        )
        model.fit(X_pruned.iloc[tr_idx], y.iloc[tr_idx], verbose=False)
        preds = model.predict(X_pruned.iloc[va_idx])
        fold_maes.append(mean_absolute_error(y.iloc[va_idx], preds))
        
    pruned_mae = np.mean(fold_maes)
    
    print("\n--- RESULTS ---")
    print(f"Original Baseline MAE (311 features): ~0.5028")
    print(f"Pruned MAE (50 features): {pruned_mae:.4f}")
    
    if pruned_mae <= 0.5028:
        print("\nCONCLUSION: Pruning helps or doesn't hurt. Consider feature selection.")
    else:
        print("\nCONCLUSION: The model NEEDS the extra features. Do NOT prune.")

if __name__ == '__main__':
    run_experiment()