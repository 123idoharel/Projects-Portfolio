"""
07a_build_inference_vectors_mh.py — גרסה מעודכנת הכוללת תיקון עמדות CM ומחיקה בטוחה של מטרות.
מייצר וקטורים לשחקני 24/25, מתקן עמדות לא תואמות ושומר על כל השחקנים לחיזוי.
"""
import sys
from pathlib import Path
import pandas as pd

# ---------------------------------------------------------------------------
# לוגיקת נתיבים מקורית
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
path_parts = list(CURRENT_DIR.parts)
if 'football_scouting_project' in path_parts:
    root_idx = path_parts.index('football_scouting_project')
    PROJECT_ROOT = Path(*path_parts[:root_idx + 1])
else:
    PROJECT_ROOT = CURRENT_DIR.parent.parent

# הוספת תיקיית המודלים ל-Path
VECTORIZE_DIR = PROJECT_ROOT / "model_mh"
sys.path.insert(0, str(VECTORIZE_DIR))

import vectorize as v
import copy_only_feature_eng_by_eda_before_shrink as prep

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CURRENT_SEASONS  = ['24/25', '2025']

def main():
    print("=" * 75)
    print("STAGE 7A: MULTI-HORIZON INFERENCE VECTOR BUILDER (24/25)")
    print("=" * 75)

    INPUT_PATH    = PROJECT_ROOT / "data" / "processed" / "att_with_tiers_for_eda.csv"
    prep.RAW_PATH = PROJECT_ROOT / "data" / "raw" / "database_ATT.csv"
    OUTPUT_DIR    = PROJECT_ROOT / "data" / "processed" / "inference_vectors_mh"
    OUTPUT_NAME   = "inference_vectors_2025_mh"

    print(f"\nLoading raw tiered data: {INPUT_PATH.name}")
    df = pd.read_csv(INPUT_PATH)

    print("\n[1/5] Attaching _league from raw data...")
    df = prep.attach_league_from_raw(df)

    print("\n[2/5] Injecting placeholder future_max_value=1.0 for current-season rows...")
    mask_current = df['_season_year'].isin(CURRENT_SEASONS)
    df.loc[mask_current, 'future_max_value'] = 1.0
    print(f"      Force-set placeholder target for {mask_current.sum()} rows")

    print("\n[3/5] Running preprocessing pipeline in-memory...")
    df = prep.apply_row_filters(df)
    df = prep.drop_unused_columns(df)
    df = prep.build_features(df)
    df = prep.add_tournament_flags(df)

    print("\n[4/5] Building vectors (cutoff 2025 ONLY)...")
    v.EMIT_CUTOFFS = [2025]
    inference_vec = v.build_all_vectors(df)
    
    # --- תיקון קריטי: מחיקה מפורשת של עמודות יעד בלבד (מניעת פגיעה בפיצ'רי shotsOnTarget) ---
    explicit_targets_to_drop = [
        'log_target', 'target_1y_log', 'target_2y_log', 'target_3y_log', 'future_max_value'
    ]
    target_cols = [c for c in explicit_targets_to_drop if c in inference_vec.columns]
    inference_vec = inference_vec.drop(columns=target_cols)

    # --- שלב תיקון שחקני CM (Remapping) ---
    # אם העמדה הראשית היא CM, נחליף אותה במשנית. אם המשנית היא CM, נחליף אותה בראשית.
    mask_cm_primary = (inference_vec['primary_position'] == 'CM')
    cm_count = mask_cm_primary.sum()
    
    if cm_count > 0:
        # תיקון עמדה ראשית לפי משנית
        inference_vec.loc[mask_cm_primary, 'primary_position'] = inference_vec.loc[mask_cm_primary, 'secondary_position']
        
        # וידוא שגם העמדה המשנית לא נשארת CM (שיהיו אחידות)
        mask_cm_secondary = (inference_vec['secondary_position'] == 'CM')
        inference_vec.loc[mask_cm_secondary, 'secondary_position'] = inference_vec.loc[mask_cm_secondary, 'primary_position']
    
    print(f"[5/5] Cleanup: Repaired {cm_count} players with CM positions (remapped to attacking roles).")
    print(f"      ✓ Total {len(inference_vec)} vectors ready. Zero players removed.")

    # ---- Statistics ----
    print("\n" + "=" * 50)
    print("DETAILED VECTOR STATISTICS (FINAL CLEANED & REPAIRED SET)")
    print("=" * 50)
    total = len(inference_vec)
    print(f"Total vectors:         {total}")
    print(f"Total columns:         {inference_vec.shape[1]}")
    print(f"Unique tm_id:          {inference_vec['tm_id'].nunique()}")

    pos_counts = inference_vec['primary_position'].value_counts()
    print("\nPrimary position breakdown:")
    for pos, n in pos_counts.items():
        pct = n / total * 100
        print(f"  {pos:5}: {n:>4} players ({pct:>5.1f}%)")
    print("=" * 50)

    # ---- Save ----
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"{OUTPUT_NAME}.parquet"
    csv_path     = OUTPUT_DIR / f"{OUTPUT_NAME}.csv"
    
    inference_vec.to_parquet(parquet_path, index=False)
    inference_vec.to_csv(csv_path, index=False)
    
    print(f"\nSaved successfully to: {OUTPUT_DIR.name}")
    print(f"→ Now run: python 07inference_mh.py")

if __name__ == '__main__':
    main()