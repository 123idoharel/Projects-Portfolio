"""
04bq_q75_diagnostics.py — Diagnostics for the new q75 interval.

Compares the new tighter interval (q10 to q75) against the original 
wide interval (q10 to q90) to verify we achieved a more realistic 
"optimistic" ceiling for the frontend.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import numpy as np
import pandas as pd

def q75_diagnostics():
    print("="*75)
    print("STAGE 4B-Q75 — DIAGNOSTICS & COMPARISON (PEAK TARGET)")
    print("="*75)

    vectors = setup.load_vectors()
    X, y, _ = setup.split_features_target(vectors)

    valid_mask = (vectors['log_target'] - vectors['log_mv_end']).notna() & \
                 (~np.isinf(vectors['log_target'] - vectors['log_mv_end']))
    df = vectors.loc[valid_mask].reset_index(drop=True).copy()

    # 1. טעינת התחזיות המקוריות (q10, q50, q90)
    orig_oof_path = setup.MODEL_DIR / "quantile_oof.npz"
    if not orig_oof_path.exists():
        print(f"[!] Missing {orig_oof_path}. Run original 04_quantiles.py first.")
        return
    orig_oof = np.load(orig_oof_path)
    df['ratio_q10'] = orig_oof['pessimistic']
    df['ratio_q50'] = orig_oof['expected']
    df['ratio_q90'] = orig_oof['optimistic']

    # 2. טעינת תחזית ה-q75 החדשה
    q75_oof_path = setup.MODEL_DIR / "q75_oof.npy"
    if not q75_oof_path.exists():
        print(f"[!] Missing {q75_oof_path}. Run 04q_q75.py first.")
        return
    df['ratio_q75'] = np.load(q75_oof_path)

    # 3. המרה ל-EUR כדי לבדוק "Sharpness" כספי
    df['pred_q10_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q10'])
    df['pred_q50_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q50'])
    df['pred_q75_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q75'])
    df['pred_q90_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q90'])
    df['actual_eur']   = np.expm1(df['log_target'])

    # 4. השוואת מרווחים (Interval Widths)
    df['width_original_eur'] = df['pred_q90_eur'] - df['pred_q10_eur']
    df['width_new_q75_eur']  = df['pred_q75_eur'] - df['pred_q10_eur']
    
    # חישוב בכמה אחוזים המרווח התכווץ
    df['shrinkage_pct'] = (1 - (df['width_new_q75_eur'] / df['width_original_eur'])) * 100

    print("\n[>] COVERAGE CHECK (Is q75 statistically honest?)")
    print("-" * 50)
    pct_below_q75 = (df['log_target'] <= (df['log_mv_end'] + df['ratio_q75'])).mean() * 100
    print(f"  Actual players falling below q75 prediction: {pct_below_q75:.1f}% (Target: 75.0%)")

    print("\n[>] SHARPNESS COMPARISON (Did we get a tighter band?)")
    print("-" * 50)
    print(f"  Median Interval Width (Original q10->q90): €{df['width_original_eur'].median():>12,.0f}")
    print(f"  Median Interval Width (New q10->q75):      €{df['width_new_q75_eur'].median():>12,.0f}")
    print(f"  => Average reduction in interval width:    {df['shrinkage_pct'].median():.1f}%")

    # חלוקה לפי קבוצות גיל (כדי לראות את ההשפעה על צעירים מול מבוגרים)
    df['age_bucket'] = pd.cut(df['age_at_cutoff'], bins=[0, 21, 25, 29, 100], labels=['17-21', '22-25', '26-29', '30+'])
    
    print("\n[>] INTERVAL REDUCTION BY AGE BUCKET")
    print("-" * 50)
    print(f"  {'Age':<10} {'Original Width':<18} {'New q75 Width':<18} {'Reduction'}")
    for grp, sub in df.groupby('age_bucket', observed=True):
        orig_med = sub['width_original_eur'].median()
        new_med  = sub['width_new_q75_eur'].median()
        shrink   = sub['shrinkage_pct'].median()
        print(f"  {str(grp):<10} €{orig_med:<16,.0f} €{new_med:<16,.0f} {shrink:.1f}%")

    # בדיקת היגיון בסיסית - האם q75 חצה את ה-q90 בטעות?
    inverted = (df['ratio_q75'] > df['ratio_q90']).sum()
    if inverted > 0:
        print(f"\n[!] WARNING: {inverted} players have q75 > q90 (Quantile Crossing detected!)")
    else:
        print("\n[✓] Logical consistency verified: q75 is strictly <= q90 for all players.")

if __name__ == '__main__':
    q75_diagnostics()