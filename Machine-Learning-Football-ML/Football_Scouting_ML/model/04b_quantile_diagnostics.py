"""
04b_quantile_diagnostics.py — Stage 4b: Verify quantile intervals are meaningful.

Calibration alone isn't enough. A well-calibrated model could still produce
intervals so wide they're useless. We need to check SHARPNESS too:

  - Interval width in EUR per segment
  - Whether width varies sensibly with uncertainty
    (wider for young players, narrower for old; wider for unknown players)
  - Whether the q10-q90 range is a meaningful fraction of the predicted value

Run after 04_quantiles.py has trained quantile models and saved OOF arrays.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import numpy as np
import pandas as pd


def quantile_diagnostics():
    vectors = setup.load_vectors()
    X, y, _ = setup.split_features_target(vectors)

    # Reattach the data we need for analysis
    valid_mask = (vectors['log_target'] - vectors['log_mv_end']).notna() & \
                 (~np.isinf(vectors['log_target'] - vectors['log_mv_end']))
    df = vectors.loc[valid_mask].reset_index(drop=True).copy()

    # Load saved OOF predictions
    oof_data = np.load(setup.MODEL_DIR / "quantile_oof.npz")
    df['ratio_q10'] = oof_data['pessimistic']
    df['ratio_q50'] = oof_data['expected']
    df['ratio_q90'] = oof_data['optimistic']

    # Compose to EUR
    df['pred_q10_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q10'])
    df['pred_q50_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q50'])
    df['pred_q90_eur'] = np.expm1(df['log_mv_end'] + df['ratio_q90'])
    df['actual_eur']   = np.expm1(df['log_target'])
    df['mv_end_eur']   = np.expm1(df['log_mv_end'])

    # Interval width metrics
    df['interval_width_eur']     = df['pred_q90_eur'] - df['pred_q10_eur']
    df['interval_width_ratio']   = df['ratio_q90'] - df['ratio_q10']  # in log space
    df['width_pct_of_median']    = df['interval_width_eur'] / df['pred_q50_eur'].clip(lower=1)
    df['width_pct_of_current']   = df['interval_width_eur'] / df['mv_end_eur'].clip(lower=1)

    df['age_bucket'] = pd.cut(
        df['age_at_cutoff'],
        bins=[0, 21, 25, 29, 100],
        labels=['17-21', '22-25', '26-29', '30+'],
    )

    print("="*72)
    print("OVERALL CALIBRATION (already verified in Stage 4, repeated for context)")
    print("="*72)
    pct_below_q10 = (df['log_target'] <= (df['log_mv_end'] + df['ratio_q10'])).mean() * 100
    pct_below_q50 = (df['log_target'] <= (df['log_mv_end'] + df['ratio_q50'])).mean() * 100
    pct_below_q90 = (df['log_target'] <= (df['log_mv_end'] + df['ratio_q90'])).mean() * 100
    coverage_80   = (((df['log_target'] >= (df['log_mv_end'] + df['ratio_q10'])) &
                      (df['log_target'] <= (df['log_mv_end'] + df['ratio_q90'])))).mean() * 100
    print(f"  q10 coverage: {pct_below_q10:.1f}% (target 10%)")
    print(f"  q50 coverage: {pct_below_q50:.1f}% (target 50%)")
    print(f"  q90 coverage: {pct_below_q90:.1f}% (target 90%)")
    print(f"  80% interval coverage: {coverage_80:.1f}% (target 80%)")

    print("\n" + "="*72)
    print("SHARPNESS — overall interval widths")
    print("="*72)
    print(f"  Mean interval width (ratio space, log scale): {df['interval_width_ratio'].mean():.3f}")
    print(f"  Median interval width in EUR:                 €{df['interval_width_eur'].median():>14,.0f}")
    print(f"  Median width as % of median prediction:       {df['width_pct_of_median'].median()*100:.1f}%")
    print(f"  Median width as % of current value:           {df['width_pct_of_current'].median()*100:.1f}%")
    print()
    print("  INTERPRETATION:")
    print("    - 'width as % of median': how wide is the band relative to the central forecast?")
    print("      Healthy values: 100-200% (intervals span a useful range, not 1000% wide)")
    print("    - 'width as % of current value': how much does the model think the player")
    print("      could deviate from current value? Higher = more uncertainty")

    # Distribution of widths
    print("\n  Distribution of interval width (% of median prediction):")
    for q, label in [(0.10, 'p10'), (0.25, 'p25'), (0.50, 'p50'),
                     (0.75, 'p75'), (0.90, 'p90')]:
        v = df['width_pct_of_median'].quantile(q)
        print(f"    {label}: {v*100:.0f}%")

    print("\n" + "="*72)
    print("INTERVAL WIDTH BY AGE BUCKET (sharpness should vary with uncertainty)")
    print("="*72)
    print(f"  {'Age':<10} {'Width (ratio)':<16} {'Width EUR median':<22} {'Width % of mv_end'}")
    for grp, sub in df.groupby('age_bucket', observed=True):
        wr = sub['interval_width_ratio'].mean()
        we = sub['interval_width_eur'].median()
        wp = sub['width_pct_of_current'].median() * 100
        print(f"  {str(grp):<10} {wr:<16.3f} €{we:>14,.0f}        {wp:>5.0f}%")
    print()
    print("  Expected: 17-21 should have WIDEST intervals (most uncertainty),")
    print("            30+ should have NARROWEST (more predictable).")

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
    print()
    print("  Expected: cutoff 2020 (5-year future) wider than cutoff 2024 (1-year future).")

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
    print()
    print("  Expected: 'no history' players should have WIDER intervals (more uncertainty).")

    # Detect inverted intervals (problematic)
    inverted = (df['ratio_q10'] > df['ratio_q90']).sum()
    if inverted > 0:
        print(f"\n⚠ WARNING: {inverted} players have q10 > q90 (inverted intervals).")
        print("  This is rare but indicates quantile crossings — usually solvable")
        print("  by adding constraints or post-hoc isotonic adjustment.")
    else:
        print("\n✓ No inverted intervals detected (q10 <= q90 for all players).")


if __name__ == '__main__':
    quantile_diagnostics()