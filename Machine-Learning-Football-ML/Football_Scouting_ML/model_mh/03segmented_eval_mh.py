"""
03_segmented_eval_mh.py — Stage 3: Per-horizon segmented evaluation.

Reads horizon-specific OOF predictions and reports MAE by:
  - Age bucket
  - Cutoff year
  - League tier
  - Has-history
  - Position
  - Cross-tab: cutoff_year × age_bucket

Usage:
    python 03_segmented_eval_mh.py --horizon 1y
    python 03_segmented_eval_mh.py --horizon 2y
"""
import sys
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

# הגדרת נתיב יחסי ל-setup_mh
sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

def segmented_evaluation(horizon: str):
    print("=" * 60)
    print(f"STAGE 3 — SEGMENTED EVAL FOR HORIZON {horizon.upper()}")
    print("=" * 60)

    res_dir = setup_mh.RESULTS_MH_DIR / horizon
    oof_path = res_dir / "stage2_oof_tuned.parquet"

    if not oof_path.exists():
         raise FileNotFoundError(f"OOF file not found at {oof_path}. Did you run Stage 2?")

    vectors = setup_mh.load_vectors_mh()
    oof = pd.read_parquet(oof_path)

    # מיזוג תחזיות ה-OOF חזרה לנתוני המקור לפי שחקן ושנה
    df = vectors.merge(
        oof[['tm_id', 'cutoff_year', 'oof_pred_ratio']],
        on=['tm_id', 'cutoff_year'], how='inner'
    )

    target_col = setup_mh.HORIZON_TO_TARGET[horizon]
    
    # חישובי שגיאה (Ratio)
    df['y_ratio']         = df[target_col] - df['log_mv_end']
    df['ratio_error']     = df['oof_pred_ratio'] - df['y_ratio']
    df['ratio_abs_error'] = df['ratio_error'].abs()

    # המרה לערכים כספיים (EUR) לטובת פרשנות אינטואיטיבית
    df['predicted_log_target'] = df['log_mv_end'] + df['oof_pred_ratio']
    df['predicted_eur']        = np.expm1(df['predicted_log_target'])
    df['actual_eur']           = np.expm1(df[target_col])
    df['eur_abs_error']        = (df['predicted_eur'] - df['actual_eur']).abs()

    # חלוקה לקבוצות גיל
    df['age_bucket'] = pd.cut(
        df['age_at_cutoff'], bins=[0, 21, 25, 29, 100],
        labels=['17-21', '22-25', '26-29', '30+']
    )

    overall_ratio_mae      = df['ratio_abs_error'].mean()
    overall_eur_median_err = df['eur_abs_error'].median()

    print(f"\nOVERALL (horizon={horizon}):")
    print(f"  Ratio MAE:                    {overall_ratio_mae:.4f}")
    print(f"  Median absolute EUR error:    €{overall_eur_median_err:>14,.0f}")

    def print_breakdown(title, group_col):
        print("\n" + "=" * 60)
        print(title)
        print("=" * 60)
        print(f"  {'Group':<14} {'Ratio MAE':<12} {'EUR median err':<18} {'n'}")
        
        # שימוש ב-observed=False כדי למנוע אזהרות ב-Pandas חדש
        for grp, sub in df.groupby(group_col, observed=False):
            if len(sub) == 0: continue
            r = sub['ratio_abs_error'].mean()
            e = sub['eur_abs_error'].median()
            print(f"  {str(grp):<14} {r:<12.4f} €{e:>14,.0f}    {len(sub)}")

    print_breakdown("MAE BY AGE BUCKET",       'age_bucket')
    print_breakdown("MAE BY CUTOFF YEAR",      'cutoff_year')
    print_breakdown("MAE BY LEAGUE TIER",      'league_tier_at_cutoff')
    print_breakdown("MAE BY HAS-HISTORY",      'has_history')
    print_breakdown("MAE BY PRIMARY POSITION", 'primary_position')

    print("\n" + "=" * 70)
    print(f"RATIO MAE — CUTOFF YEAR × AGE BUCKET (horizon={horizon})")
    print("=" * 70)
    pivot_ratio = df.pivot_table(
        values='ratio_abs_error',
        index='cutoff_year', columns='age_bucket',
        aggfunc='mean', observed=False
    )
    print(pivot_ratio.round(3).to_string())

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    segmented_evaluation(args.horizon)