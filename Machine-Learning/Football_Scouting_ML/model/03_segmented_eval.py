"""
03_segmented_eval.py — Stage 3: Segmented evaluation of OOF predictions.

Reports MAE broken down by:
  - Age bucket
  - Cutoff year (temporal stability check)
  - League tier (fairness check)
  - Has-history (new players vs known players)
  - Position

ALSO reports the EUR-scale absolute MAE (composed back from ratio predictions),
which is what the executive cares about. The ratio MAE is the optimization
metric; the absolute EUR MAE is the business metric.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error


def segmented_evaluation():
    vectors = setup.load_vectors()
    oof = pd.read_parquet(setup.RESULT_DIR / "stage2_oof_tuned.parquet")

    # Merge OOF predictions back to the full vectors for segmentation
    df = vectors.merge(
        oof[['tm_id', 'cutoff_year', 'oof_pred_ratio']],
        on=['tm_id', 'cutoff_year'], how='inner',
    )

    # Compute errors on RATIO scale and on EUR scale
    df['y_ratio']           = df['log_target'] - df['log_mv_end']
    df['ratio_error']       = df['oof_pred_ratio'] - df['y_ratio']
    df['ratio_abs_error']   = df['ratio_error'].abs()

    # Compose absolute predictions
    df['predicted_log_target'] = df['log_mv_end'] + df['oof_pred_ratio']
    df['predicted_eur']        = np.expm1(df['predicted_log_target'])
    df['actual_eur']           = np.expm1(df['log_target'])
    df['eur_abs_error']        = (df['predicted_eur'] - df['actual_eur']).abs()

    overall_ratio_mae = df['ratio_abs_error'].mean()
    overall_eur_mae   = df['eur_abs_error'].mean()
    overall_eur_median_err = df['eur_abs_error'].median()

    print("="*60)
    print("OVERALL PERFORMANCE")
    print("="*60)
    print(f"  MAE on ratio target:         {overall_ratio_mae:.4f}")
    print(f"  MAE in EUR (composed):       €{overall_eur_mae:>14,.0f}")
    print(f"  Median absolute error (EUR): €{overall_eur_median_err:>14,.0f}")
    print(f"  (Median is more robust than mean for EUR errors due to skew)")

    print("\n" + "="*60)
    print("MAE BY AGE BUCKET")
    print("="*60)
    print(f"  {'Age':<10} {'Ratio MAE':<12} {'EUR median err':<18} {'n'}")
    for label, lo, hi in [('17-21', 17, 21), ('22-25', 22, 25),
                           ('26-29', 26, 29), ('30+', 30, 45)]:
        mask = df['age_at_cutoff'].between(lo, hi)
        if mask.sum() > 0:
            r = df.loc[mask, 'ratio_abs_error'].mean()
            e = df.loc[mask, 'eur_abs_error'].median()
            print(f"  {label:<10} {r:<12.4f} €{e:>14,.0f}    {mask.sum()}")

    print("\n" + "="*60)
    print("MAE BY CUTOFF YEAR (temporal stability check)")
    print("="*60)
    print(f"  {'Year':<10} {'Ratio MAE':<12} {'EUR median err':<18} {'n'}")
    for cy in sorted(df['cutoff_year'].unique()):
        mask = df['cutoff_year'] == cy
        r = df.loc[mask, 'ratio_abs_error'].mean()
        e = df.loc[mask, 'eur_abs_error'].median()
        print(f"  {cy:<10} {r:<12.4f} €{e:>14,.0f}    {mask.sum()}")

    print("\n" + "="*60)
    print("MAE BY LEAGUE TIER")
    print("="*60)
    print(f"  {'Tier':<10} {'Ratio MAE':<12} {'EUR median err':<18} {'n'}")
    for t in [1, 2, 3, 4, 5]:
        mask = df['league_tier_at_cutoff'] == t
        if mask.sum() > 0:
            r = df.loc[mask, 'ratio_abs_error'].mean()
            e = df.loc[mask, 'eur_abs_error'].median()
            print(f"  tier {t}    {r:<12.4f} €{e:>14,.0f}    {mask.sum()}")

    print("\n" + "="*60)
    print("MAE BY HAS-HISTORY")
    print("="*60)
    print(f"  {'Group':<14} {'Ratio MAE':<12} {'EUR median err':<18} {'n'}")
    for h in [0, 1]:
        mask = df['has_history'] == h
        if mask.sum() > 0:
            label = "no history" if h == 0 else "has history"
            r = df.loc[mask, 'ratio_abs_error'].mean()
            e = df.loc[mask, 'eur_abs_error'].median()
            print(f"  {label:<14} {r:<12.4f} €{e:>14,.0f}    {mask.sum()}")

    print("\n" + "="*60)
    print("MAE BY PRIMARY POSITION")
    print("="*60)
    print(f"  {'Position':<10} {'Ratio MAE':<12} {'EUR median err':<18} {'n'}")
    for pos in df['primary_position'].unique():
        mask = df['primary_position'] == pos
        r = df.loc[mask, 'ratio_abs_error'].mean()
        e = df.loc[mask, 'eur_abs_error'].median()
        print(f"  {pos:<10} {r:<12.4f} €{e:>14,.0f}    {mask.sum()}")


if __name__ == '__main__':
    segmented_evaluation()