"""
vectorize_mh.py — Multi-Horizon Vectorizer (Phase 2 extension).

CRITICAL FIX (Dual Source Strategy):
1. Features (the past) are built from the highly-curated 'att_features_before_vectorization.parquet'.
2. Future targets (the mv_end) are looked up in the raw 'att_with_tiers_for_eda.csv'.
   This prevents massive target loss caused by Phase 1 preprocessing (which intentionally 
   dropped 24/25 rows because they lack a 'future_max_value' peak).
"""
import sys
from pathlib import Path
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))

# ייבוא הלוגיקה של פאזה 1 - ודא ש-vectorize.py נמצא באותה תיקייה
import vectorize as v

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = CURRENT_DIR.parent.parent

FEATURES_PATH = PROJECT_ROOT / "data" / "processed" / "att_features_before_vectorization" / "att_features_before_vectorization.parquet"
TARGETS_PATH  = PROJECT_ROOT / "data" / "processed" / "att_with_tiers_for_eda.csv"

OUTPUT_DIR    = PROJECT_ROOT / "data" / "processed" / "att_vectors_mh"
OUTPUT_NAME   = "att_vectors_mh"

# ---------------------------------------------------------------------------
# Multi-horizon target computation (STRICT WINDOW)
# ---------------------------------------------------------------------------
HORIZONS = [1, 2, 3]

def compute_horizon_targets(df_targets: pd.DataFrame, cutoff: int) -> pd.DataFrame:
    out_cols = {}
    
    # סינון הטורנירים כדי ששווי המטרה ייקבע רק לפי עונות הליגה הרגילות
    league_rows = df_targets[df_targets['is_tournament'] == 0]
    
    max_dataset_year = df_targets['_cutoff_year'].max()

    for h in HORIZONS:
        target_cutoff_max = cutoff + h
        
        # חוק החלון הקשיח: אם החלון חורג מהנתונים הקיימים (מעבר ל-2025)
        if target_cutoff_max > max_dataset_year:
            out_cols[f'target_{h}y_log'] = pd.Series(dtype=float)
            continue
            
        target_cutoff_min = cutoff + 1
        future = league_rows[
            (league_rows['_cutoff_year'] >= target_cutoff_min) &
            (league_rows['_cutoff_year'] <= target_cutoff_max)
        ]
        
        if len(future) > 0:
            # לוקחים את השווי הגבוה ביותר בחלון הזמן המבוקש
            max_per_player = future.groupby('tm_id')['mv_end'].max()
            out_cols[f'target_{h}y_log'] = max_per_player.apply(
                lambda x: np.log1p(x) if pd.notna(x) and x > 0 else np.nan
            )
        else:
            out_cols[f'target_{h}y_log'] = pd.Series(dtype=float)

    return pd.DataFrame(out_cols)

def attach_horizon_targets(vec: pd.DataFrame, df_targets: pd.DataFrame, cutoff: int) -> pd.DataFrame:
    horizon_targets = compute_horizon_targets(df_targets, cutoff)
    for h in HORIZONS:
        col = f'target_{h}y_log'
        if col in horizon_targets.columns:
            vec[col] = vec['tm_id'].map(horizon_targets[col])
        else:
            vec[col] = np.nan
    return vec

# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def build_all_vectors_mh(df_features: pd.DataFrame, df_targets: pd.DataFrame) -> pd.DataFrame:
    block_b_cols = v.block_b_columns(df_features)
    parts = []

    for cutoff in v.EMIT_CUTOFFS:
        print(f"  cutoff {cutoff}...")
        
        # בונים את הפיצ'רים מהדאטא המסונן
        vec = v.build_vectors_for_cutoff(df_features, cutoff, block_b_cols)
        if len(vec) == 0:
            continue
            
        # מוסיפים את המטרות מהדאטא הגולמי
        vec = attach_horizon_targets(vec, df_targets, cutoff)
        
        diag = {h: int(vec[f'target_{h}y_log'].notna().sum()) for h in HORIZONS}
        print(f"    {len(vec)} vectors, {vec.shape[1]} cols, horizon valid targets: {diag}")
        parts.append(vec)

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

def validate(df: pd.DataFrame, max_dataset_year: int) -> None:
    assert set(df['cutoff_year'].unique()).issubset(set(v.EMIT_CUTOFFS)), \
        "Unexpected cutoff years found."
    assert df['log_target'].notna().all(), "Some rows have NaN log_target (peak)"

    for cy in sorted(df['cutoff_year'].unique()):
        sub = df[df['cutoff_year'] == cy]
        for h in HORIZONS:
            n_valid = sub[f'target_{h}y_log'].notna().sum()
            if cy + h > max_dataset_year:
                assert n_valid == 0, \
                    f"STRICT CHECK FAILED: cutoff={cy}, horizon={h}y should be empty."

def main() -> None:
    print("=" * 70)
    print("MULTI-HORIZON VECTORIZER (Dual Source Mode)")
    print("=" * 70)
    
    # --- 1. טעינת הפיצ'רים ---
    print(f"Loading Features from: {FEATURES_PATH.name}")
    df_features = pd.read_parquet(FEATURES_PATH)
    df_features['_cutoff_year'] = df_features['_season_year'].map(v.SEASON_TO_CUTOFF).astype('Int64')
    
    # --- 2. טעינת המטרות (עם תיקון הטורנירים) ---
    print(f"Loading Targets from: {TARGETS_PATH.name}")
    df_targets = pd.read_csv(TARGETS_PATH)
    
    season_col = '_season_year' if '_season_year' in df_targets.columns else 'season'
    df_targets['_cutoff_year'] = df_targets[season_col].map(v.SEASON_TO_CUTOFF).astype('Int64')
    
    # הוספת עמודת is_tournament החסרה בקובץ ה-EDA
    TOURNAMENT_COMPETITIONS = {
        'UEFA Champions League', 'UEFA Europa League', 'UEFA Conference League',
        'UEFA European Championship', 'FIFA World Cup',
        'CONMEBOL Copa Libertadores', 'CONCACAF Gold Cup',
    }
    df_targets['is_tournament'] = df_targets['_league'].isin(TOURNAMENT_COMPETITIONS).astype(int)
    
    max_dataset_year = df_targets['_cutoff_year'].max()
    
    # --- 3. בניית הוקטורים ---
    print("\nBuilding vectors...")
    vectors = build_all_vectors_mh(df_features, df_targets)
    print(f"\nFinal shape: {vectors.shape}")
    
    # --- 4. בדיקות תקינות ושמירה ---
    print("\nValidating output...")
    validate(vectors, max_dataset_year)
    print("  ✓ Strict Validation passed!")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"{OUTPUT_NAME}.parquet"
    csv_path     = OUTPUT_DIR / f"{OUTPUT_NAME}.csv"
    
    vectors.to_parquet(parquet_path, index=False)
    vectors.to_csv(csv_path, index=False)
    
    print(f"\nSaved SUCCESS:")
    print(f"  [PARQUET]: {parquet_path.relative_to(PROJECT_ROOT)}")
    print(f"  [CSV]:     {csv_path.relative_to(PROJECT_ROOT)}")

if __name__ == '__main__':
    main()