"""
04bq_q75_diagnostics_mh.py — Diagnostics for the new q75 interval (MH Track).

Compares the new tighter interval (q10 to q75) against the original 
wide interval (q10 to q90) to verify we achieved a more realistic 
"optimistic" ceiling for the 1-year and 2-year horizons.

Usage:
    python 04bq_q75_diagnostics_mh.py --horizon 1y
    python 04bq_q75_diagnostics_mh.py --horizon 2y
"""
import sys
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

def q75_diagnostics_mh(horizon: str):
    print("="*75)
    print(f"STAGE 4B-Q75 (MH) — DIAGNOSTICS & COMPARISON (HORIZON: {horizon.upper()})")
    print("="*75)

    # 1. טעינת הנתונים בדיוק כפי שהמודל ראה אותם
    vectors = setup_mh.load_vectors_mh()
    target_col = setup_mh.HORIZON_TO_TARGET[horizon]
    X, _, _ = setup_mh.split_features_target_mh(vectors, horizon)
    
    # סינון הוקטורים המקוריים רק לשורות ששימשו לאימון
    df = vectors.loc[X.index].reset_index(drop=True).copy()

    model_dir = setup_mh.MODELS_MH_DIR / horizon

    # 2. טעינת התחזיות המקוריות (q10, q50, q90)
    orig_oof_path = model_dir / "quantile_oof.npz"
    if not orig_oof_path.exists():
        print(f"[!] Missing {orig_oof_path}. Run original 04_quantiles_mh.py first.")
        return
    orig_oof = np.load(orig_oof_path)
    df['ratio_q10'] = orig_oof['pessimistic']
    df['ratio_q50'] = orig_oof['expected']
    df['ratio_q90'] = orig_oof['optimistic']

    # 3. טעינת תחזית ה-q75 החדשה
    q75_oof_path = model_dir / "q75_oof.npy"
    if not q75_oof_path.exists():
        print(f"[!] Missing {q75_oof_path}. Run 04q_q75_mh_2.py first.")
        return
    df['ratio_q75'] = np.load(q75_oof_path)

    # 4. המרה ל-EUR
    df['pred_q10_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q10'])
    df['pred_q50_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q50'])
    df['pred_q75_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q75'])
    df['pred_q90_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q90'])
    df['actual_eur']   = np.expm1(df[target_col])

    # 5. חישוב מרווחים
    df['width_original_eur'] = df['pred_q90_eur'] - df['pred_q10_eur']
    df['width_new_q75_eur']  = df['pred_q75_eur'] - df['pred_q10_eur']
    df['shrinkage_pct'] = (1 - (df['width_new_q75_eur'] / df['width_original_eur'])) * 100

    print("\n[>] COVERAGE CHECK (Is q75 statistically honest?)")
    print("-" * 50)
    pct_below_q75 = (df[target_col] <= (df['log_mv_end'] + df['ratio_q75'])).mean() * 100
    print(f"  Actual players falling below q75 prediction: {pct_below_q75:.1f}% (Target: 75.0%)")

    print("\n[>] SHARPNESS COMPARISON (Did we get a tighter band?)")
    print("-" * 50)
    print(f"  Median Interval Width (Original q10->q90): €{df['width_original_eur'].median():>12,.0f}")
    print(f"  Median Interval Width (New q10->q75):      €{df['width_new_q75_eur'].median():>12,.0f}")
    print(f"  => Average reduction in interval width:    {df['shrinkage_pct'].median():.1f}%")

    # 6. בדיקה לפי קבוצות גיל
    df['age_bucket'] = pd.cut(df['age_at_cutoff'], bins=[0, 21, 25, 29, 100], labels=['17-21', '22-25', '26-29', '30+'])
    
    print("\n[>] INTERVAL REDUCTION BY AGE BUCKET")
    print("-" * 50)
    print(f"  {'Age':<10} {'Original Width':<18} {'New q75 Width':<18} {'Reduction'}")
    for grp, sub in df.groupby('age_bucket', observed=True):
        orig_med = sub['width_original_eur'].median()
        new_med  = sub['width_new_q75_eur'].median()
        shrink   = sub['shrinkage_pct'].median()
        print(f"  {str(grp):<10} €{orig_med:<16,.0f} €{new_med:<16,.0f} {shrink:.1f}%")

    inverted = (df['ratio_q75'] > df['ratio_q90']).sum()
    if inverted > 0:
        print(f"\n[!] WARNING: {inverted} players have q75 > q90 (Quantile Crossing detected!)")
    else:
        print("\n[✓] Logical consistency verified: q75 is strictly <= q90 for all players.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    q75_diagnostics_mh(args.horizon)