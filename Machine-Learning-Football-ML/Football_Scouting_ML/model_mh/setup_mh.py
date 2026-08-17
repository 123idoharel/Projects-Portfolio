"""
setup_mh.py — Multi-Horizon Configuration and Routing.

Inherits paths and helpers from Phase 1 setup.
Focuses strictly on providing clean data for training 1y and 2y models.
"""
import sys
import numpy as np
import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate Phase 1 setup module and inherit
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "model"))
import setup as phase1_setup

# ---------------------------------------------------------------------------
# Phase 2 paths
# ---------------------------------------------------------------------------
DATA_DIR_MH         = PROJECT_ROOT / "data" / "processed" / "att_vectors_mh"
MODELS_MH_DIR       = PROJECT_ROOT / "models_mh"
RESULTS_MH_DIR      = PROJECT_ROOT / "results_mh"

# יצירת התיקיות אם הן לא קיימות
for p in [DATA_DIR_MH, MODELS_MH_DIR, RESULTS_MH_DIR]:
    p.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Horizon configuration
# ---------------------------------------------------------------------------
VALID_HORIZONS = ['1y', '2y']

HORIZON_TO_TARGET = {
    '1y': 'target_1y_log',
    '2y': 'target_2y_log'
}

def load_vectors_mh():
    """Load the multi-horizon vectors file."""
    path = DATA_DIR_MH / "att_vectors_mh.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Multi-horizon vectors not found at {path}")
    return pd.read_parquet(path)

def split_features_target_mh(vectors, horizon: str):
    """
    Split vectors for training. Returns ONLY what the model needs: X, y, groups.
    """
    target_col = HORIZON_TO_TARGET.get(horizon)
    if not target_col:
        raise ValueError(f"Invalid horizon '{horizon}'.")

    # 1. יצירת מטרת האימון (יחס צמיחה)
    y_ratio = vectors[target_col] - vectors['log_mv_end']
    
    # 2. סינון שורות חסרות (מוריד שחקנים מעונות שאין להן נתונים עתידיים לטווח הזה)
    valid_mask = y_ratio.notna() & (~np.isinf(y_ratio))
    
    y_ratio = y_ratio[valid_mask]
    valid_vectors = vectors.loc[valid_mask]
    groups = valid_vectors['tm_id']

    # 3. חסימת זליגת מידע - הסרת כל מטרות העתיד מהפיצ'רים
    drop_cols = [
        'tm_id', 'cutoff_year', 'log_target', 
        'target_1y_log', 'target_2y_log', 'target_3y_log', 'future_max_value'
    ]
    drop_cols += [c for c in phase1_setup.RAW_EUR_TO_DROP if c in vectors.columns]
    drop_cols += [c for c in phase1_setup.DATA_QUALITY_DROPS if c in vectors.columns]
    
    X = valid_vectors.drop(columns=[c for c in drop_cols if c in valid_vectors.columns])

    # 4. הגדרת עמודות קטגוריאליות עבור XGBoost
    for col in ['primary_position', 'secondary_position']:
        if col in X.columns:
            X[col] = X[col].astype('category')

    return X, y_ratio, groups


# ---------------------------------------------------------------------------
# Sanity check & Terminal Output (מופעל רק כשמריצים ישירות)
# ---------------------------------------------------------------------------
def print_paths():
    print("=" * 70)
    print("SETUP MH - CONFIGURATION CHECK")
    print("=" * 70)
    print(f"PROJECT_ROOT:       {PROJECT_ROOT}")
    print(f"DATA_DIR_MH:        {DATA_DIR_MH}  exists={DATA_DIR_MH.exists()}")
    print(f"  └─ vectors file exists: {(DATA_DIR_MH / 'att_vectors_mh.parquet').exists()}")
    print(f"MODELS_MH_DIR:      {MODELS_MH_DIR}  exists={MODELS_MH_DIR.exists()}")
    print(f"RESULTS_MH_DIR:     {RESULTS_MH_DIR}  exists={RESULTS_MH_DIR.exists()}")
    print(f"\nValid horizons: {VALID_HORIZONS}")
    print(f"Horizon Target Map: {HORIZON_TO_TARGET}")

if __name__ == '__main__':
    print_paths()
    print("\n" + "=" * 70)
    print("TESTING DATA EXTRACTION (1Y HORIZON)")
    print("=" * 70)
    
    try:
        vecs = load_vectors_mh()
        total_rows = len(vecs)
        print(f"Successfully loaded vectors: {total_rows} total rows.")
        
        X, y, g = split_features_target_mh(vecs, '1y')
        valid_rows = len(y)
        
        print("\n[SUCCESS] Extraction completed cleanly!")
        print(f"  - Original rows: {total_rows}")
        print(f"  - Rows retained for 1Y model: {valid_rows}")
        print(f"  - Rows dropped (NaN targets): {total_rows - valid_rows}")
        print(f"  - Feature columns (X.shape): {X.shape[1]}")
        print(f"  - y_ratio mean: {y.mean():.4f}")
        
    except Exception as e:
        print(f"\n[ERROR] Failed extraction test: {e}")