"""
04b_quantile_diagnostics_mh.py — Stage 4b: Verify quantile intervals are meaningful.

Calibration alone isn't enough. A well-calibrated model could still produce
intervals so wide they're useless. We need to check SHARPNESS too:

  - Interval width in EUR per segment
  - Whether width varies sensibly with uncertainty
    (wider for young players, narrower for old; wider for unknown players)

Run after 04_quantiles_mh.py has trained quantile models and saved OOF arrays.

Usage:
    python 04b_quantile_diagnostics_mh.py --horizon 1y
    python 04b_quantile_diagnostics_mh.py --horizon 2y
"""
import sys
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

# הגדרת נתיב יחסי ל-setup_mh
sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

def quantile_diagnostics(horizon: str):
    print(f"\n{'='*72}\nSTAGE 4B — QUANTILE DIAGNOSTICS FOR HORIZON {horizon.upper()}\n{'='*72}")

    vectors = setup_mh.load_vectors_mh()
    target_col = setup_mh.HORIZON_TO_TARGET[horizon]

    # סינון הנתונים הרלוונטיים (כמו בשלב האימון)
    # סינון הנתונים - מסונכרן בדיוק עם מה שהמודל אימן
    X, _, _ = setup_mh.split_features_target_mh(vectors, horizon)
    df = vectors.loc[X.index].reset_index(drop=True).copy()

    # טעינת קבצי ה-OOF של הקוונטילים (נוצרו ב-04)
    model_dir = setup_mh.MODELS_MH_DIR / horizon
    oof_path = model_dir / "quantile_oof.npz"
    
    if not oof_path.exists():
        raise FileNotFoundError(f"Missing {oof_path}. Run 04_quantiles_mh.py first.")

    oof_data = np.load(oof_path)
    df['ratio_q10'] = oof_data['pessimistic']
    df['ratio_q50'] = oof_data['expected']
    df['ratio_q90'] = oof_data['optimistic']

    # המרה מ-Ratio ל-EUR כספי
    df['pred_q10_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q10'])
    df['pred_q50_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q50'])
    df['pred_q90_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q90'])
    df['actual_eur']   = np.expm1(df[target_col])
    df['mv_end_eur']   = np.expm1(df['log_mv_end'])

    # חישוב רוחב המרווח (Sharpness) - ההפרש בין האופטימי לפסימי
    df['interval_width_eur']     = df['pred_q90_eur'] - df['pred_q10_eur']
    df['interval_width_ratio']   = df['ratio_q90'] - df['ratio_q10']
    df['width_pct_of_median']    = df['interval_width_eur'] / df['pred_q50_eur'].clip(lower=1)
    df['width_pct_of_current']   = df['interval_width_eur'] / df['mv_end_eur'].clip(lower=1)

    df['age_bucket'] = pd.cut(
        df['age_at_cutoff'],
        bins=[0, 21, 25, 29, 100],
        labels=['17-21', '22-25', '26-29', '30+'],
    )

    print("\n" + "="*72)
    print("OVERALL CALIBRATION (Did the models hit their probability targets?)")
    print("="*72)
    pct_below_q10 = (df[target_col] <= (df['log_mv_end'] + df['ratio_q10'])).mean() * 100
    pct_below_q50 = (df[target_col] <= (df['log_mv_end'] + df['ratio_q50'])).mean() * 100
    pct_below_q90 = (df[target_col] <= (df['log_mv_end'] + df['ratio_q90'])).mean() * 100
    coverage_80   = (((df[target_col] >= (df['log_mv_end'] + df['ratio_q10'])) &
                      (df[target_col] <= (df['log_mv_end'] + df['ratio_q90'])))).mean() * 100
    print(f"  q10 coverage: {pct_below_q10:.1f}% (target 10%)")
    print(f"  q50 coverage: {pct_below_q50:.1f}% (target 50%)")
    print(f"  q90 coverage: {pct_below_q90:.1f}% (target 90%)")
    print(f"  80% interval coverage: {coverage_80:.1f}% (target 80%)")

    print("\n" + "="*72)
    print("SHARPNESS — OVERALL INTERVAL WIDTHS")
    print("="*72)
    print(f"  Mean interval width (ratio log scale):  {df['interval_width_ratio'].mean():.3f}")
    print(f"  Median interval width in EUR:           €{df['interval_width_eur'].median():>14,.0f}")
    print(f"  Median width as % of median prediction: {df['width_pct_of_median'].median()*100:.1f}%")
    print(f"  Median width as % of current value:     {df['width_pct_of_current'].median()*100:.1f}%")

    print("\n" + "="*72)
    print("INTERVAL WIDTH BY AGE BUCKET (Sharpness vs Uncertainty)")
    print("="*72)
    print(f"  {'Age':<10} {'Width (ratio)':<16} {'Width EUR median':<22} {'Width % of mv_end'}")
    for grp, sub in df.groupby('age_bucket', observed=True):
        wr = sub['interval_width_ratio'].mean()
        we = sub['interval_width_eur'].median()
        wp = sub['width_pct_of_current'].median() * 100
        print(f"  {str(grp):<10} {wr:<16.3f} €{we:>14,.0f}        {wp:>5.0f}%")
    print("\n  Expected behavior: Younger players (17-21) should have WIDER intervals than older players.")

    print("\n" + "="*72)
    print("INTERVAL WIDTH BY CUTOFF YEAR")
    print("="*72)
    print(f"  {'Year':<10} {'Width (ratio)':<16} {'Width EUR median':<22} {'Width % of mv_end'}")
    for cy in sorted(df['cutoff_year'].unique()):
        sub = df[df['cutoff_year'] == cy]
        wr = sub['interval_width_ratio'].mean()
        we = sub['interval_width_eur'].median()
        wp = sub['width_pct_of_current'].median() * 100
        print(f"  {cy:<10} {wr:<16.3f} €{we:>14,.0f}        {wp:>5.0f}%")

    print("\n" + "="*72)
    print("INTERVAL WIDTH BY HAS-HISTORY")
    print("="*72)
    print(f"  {'Group':<14} {'Width (ratio)':<16} {'Width EUR median':<22} {'Width % of mv_end'}")
    for h in [0, 1]:
        sub = df[df['has_history'] == h]
        label = "no history" if h == 0 else "has history"
        wr = sub['interval_width_ratio'].mean()
        we = sub['interval_width_eur'].median()
        wp = sub['width_pct_of_current'].median() * 100
        print(f"  {label:<14} {wr:<16.3f} €{we:>14,.0f}        {wp:>5.0f}%")
    print("\n  Expected behavior: Players with 'no history' should have WIDER intervals.")

    inverted = (df['ratio_q10'] > df['ratio_q90']).sum()
    if inverted > 0:
        print(f"\n[!] WARNING: {inverted} players have q10 > q90 (inverted intervals).")
    else:
        print("\n[✓] No inverted intervals detected (q10 <= q90 for all players).")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    quantile_diagnostics(args.horizon)