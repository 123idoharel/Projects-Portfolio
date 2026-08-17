"""
07a_build_inference_vectors.py — End-to-End Inference Vector Builder for 24/25.

Acts as a self-contained inference pipeline:
  1. Loads the raw tiered data (att_with_tiers_for_eda.csv) BEFORE any rows
     are dropped by previous preprocess runs.
  2. Force-injects future_max_value=1.0 for ALL current-season rows so they
     pass the production filter (which requires future_max_value > 0).
  3. Runs the same preprocess + vectorize pipeline used for training,
     in-memory, ensuring the inference vectors are structurally identical
     to the training vectors.
  4. Outputs cutoff-2025 vectors for direct use by 07_inference.py.

Player counts (expected):
  - Raw 24/25 + 2025 calendar year rows:    ~6,691 (5,413 unique players)
  - After mv_start NaN filter:              ~5,145 unique
  - After attacker filter:                  ~5,142 unique
  - After league-row requirement:           ~4,849 unique  ← FINAL OUTPUT

Player count gap explanation:
  - ~268 players lost to mv_start NaN (Transfermarkt didn't publish their
    start-of-season market value yet)
  - ~3 players lost to non-attacker filter
  - ~313 players have only tournament rows (Olympic / U-20 / international
    only) and no league rows in 24/25 — same filter as training

Position handling:
  Position remaps inside vectorize.py collapse rare categories (RB, CF, CAM)
  into the 5 canonical training categories (ST, LW, RW, RM, LM). Any
  remaining non-training categories that slip through (e.g., a CM-primary
  player) are caught defensively at inference time by 07_inference.py via
  its POSITION_SAFETY_REMAP — no action needed here.

Output: data/processed/att_inference_vectors/att_inference_2425.{parquet,csv}
"""
import sys
from pathlib import Path
import pandas as pd

# ---------------------------------------------------------------------------
# Path resolution — works regardless of where the script is invoked from
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
path_parts = list(CURRENT_DIR.parts)
if 'football_scouting_project' in path_parts:
    root_idx = path_parts.index('football_scouting_project')
    PROJECT_ROOT = Path(*path_parts[:root_idx + 1])
else:
    PROJECT_ROOT = CURRENT_DIR.parent.parent

VECTORIZE_DIR = PROJECT_ROOT / "EDA_Vectorization_notebooks_and_scripts_" / "vectorization"
if not VECTORIZE_DIR.exists():
    VECTORIZE_DIR = PROJECT_ROOT / "EDA_Vectorization_notebooks_and_scripts_"
sys.path.insert(0, str(VECTORIZE_DIR))
sys.path.insert(0, str(CURRENT_DIR))

import vectorize as v
import feature_eng_by_eda_before_shrink as prep


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CURRENT_SEASONS  = ['24/25', '2025']  # both forms appear in source data
TRAINING_POSITIONS = {'ST', 'LW', 'RW', 'RM', 'LM'}


def main():
    print("=" * 75)
    print("STAGE 7A: END-TO-END INFERENCE VECTOR BUILDER (24/25)")
    print("=" * 75)

    INPUT_PATH    = PROJECT_ROOT / "data" / "processed" / "att_with_tiers_for_eda.csv"
    prep.RAW_PATH = PROJECT_ROOT / "data" / "raw" / "database_ATT.csv"
    OUTPUT_DIR    = PROJECT_ROOT / "data" / "processed" / "att_inference_vectors"
    OUTPUT_NAME   = "att_inference_2425"

    print(f"\nLoading raw tiered data: {INPUT_PATH.name}")
    df = pd.read_csv(INPUT_PATH)
    print(f"  shape: {df.shape}")

    # Diagnostic: 24/25 raw counts before any pipeline runs
    pre_pipeline_2425 = df[df['_season_year'].isin(CURRENT_SEASONS)]
    print(f"\n  Raw 24/25 + 2025 rows:    {len(pre_pipeline_2425)}")
    print(f"  Unique tm_id in 24/25:    {pre_pipeline_2425['tm_id'].nunique()}")

    print("\n[1/5] Attaching _league from raw data...")
    df = prep.attach_league_from_raw(df)

    print("\n[2/5] Injecting placeholder future_max_value=1.0 for current-season rows...")
    mask_current = df['_season_year'].isin(CURRENT_SEASONS)
    n_injected = mask_current.sum()
    df.loc[mask_current, 'future_max_value'] = 1.0
    print(f"      Force-set future_max_value=1.0 for {n_injected} rows in {CURRENT_SEASONS}")

    print("\n[3/5] Running preprocessing pipeline in-memory...")
    df = prep.apply_row_filters(df)
    df = prep.drop_unused_columns(df)
    df = prep.build_features(df)
    df = prep.add_tournament_flags(df)
    print(f"      After preprocess: {df.shape}")

    print("\n[4/5] Building vectors (cutoff 2025 ONLY)...")
    v.EMIT_CUTOFFS = [2025]
    inference_vec = v.build_all_vectors(df)
    print(f"      Built {len(inference_vec)} player vectors × {inference_vec.shape[1]} columns")

    # Drop the placeholder log_target — it was just to pass the filter
    if 'log_target' in inference_vec.columns:
        inference_vec = inference_vec.drop(columns=['log_target'])
        print(f"      Dropped placeholder log_target column → {inference_vec.shape[1]} columns")

    # ---- Validation ----
    print("\n[5/5] Validating output structure...")
    issues = []

    # Check key columns exist (needed by 07_inference.py)
    required_cols = ['tm_id', 'cutoff_year', 'log_mv_end', 'primary_position', 'secondary_position']
    missing = [c for c in required_cols if c not in inference_vec.columns]
    if missing:
        issues.append(f"Missing required columns: {missing}")

    # Check position categories
    primary_set   = set(inference_vec['primary_position'].dropna().unique())
    secondary_set = set(inference_vec['secondary_position'].dropna().unique())
    unexpected_primary   = primary_set - TRAINING_POSITIONS
    unexpected_secondary = secondary_set - TRAINING_POSITIONS

    if unexpected_primary:
        print(f"      Note: primary_position has non-training values: {unexpected_primary}")
        print("            These will be remapped at inference by 07_inference.py")
    if unexpected_secondary:
        print(f"      Note: secondary_position has non-training values: {unexpected_secondary}")
        print("            These will be remapped at inference by 07_inference.py")

    if not (unexpected_primary or unexpected_secondary):
        print("      ✓ All position categories match training")

    if issues:
        print(f"\n      ⚠ ISSUES FOUND: {issues}")
        print("        Review before running 07_inference.py")

    # ---- Statistics ----
    print("\n" + "=" * 50)
    print("DETAILED VECTOR STATISTICS (CUTOFF 2025)")
    print("=" * 50)
    total = len(inference_vec)
    print(f"Total vectors:         {total}")
    print(f"Total columns:         {inference_vec.shape[1]}")
    print(f"Unique tm_id:          {inference_vec['tm_id'].nunique()}")

    pos_counts = inference_vec['primary_position'].value_counts()
    print("\nPrimary position breakdown:")
    for pos, n in pos_counts.items():
        pct = n / total * 100
        flag = "" if pos in TRAINING_POSITIONS else "  ← will be remapped at inference"
        print(f"  {pos:5}: {n:>4} players ({pct:>5.1f}%){flag}")

    print(f"\nAge range: {inference_vec['age_at_cutoff'].min():.0f} - {inference_vec['age_at_cutoff'].max():.0f}")
    print("=" * 50)

    # ---- Save ----
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"{OUTPUT_NAME}.parquet"
    csv_path     = OUTPUT_DIR / f"{OUTPUT_NAME}.csv"
    inference_vec.to_parquet(parquet_path, index=False)
    inference_vec.to_csv(csv_path, index=False)
    print(f"\nSaved: {parquet_path.relative_to(PROJECT_ROOT)}")
    print(f"Saved: {csv_path.relative_to(PROJECT_ROOT)}")
    print(f"\n→ Now run: python 07_inference.py")


if __name__ == '__main__':
    main()