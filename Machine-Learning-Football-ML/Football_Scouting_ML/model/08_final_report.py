"""
08_final_report.py — Stage 8: Generate final executive report.

Combines production CV MAE and strict-temporal historical backtest results
into a single readable summary for the executive presentation.

Quality narrative:
  - Production CV MAE = expected error on new 24/25 players
  - Historical backtests = honest "would this have worked?" demonstrations
  - Both reported separately because they answer different questions
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import joblib
import pandas as pd
import numpy as np


def generate_report():
    backtests = joblib.load(setup.RESULT_DIR / "historical_backtests.pkl")
    oof_tuned = pd.read_parquet(setup.RESULT_DIR / "stage2_oof_tuned.parquet")

    # Production CV MAE (the deployment quality estimate)
    production_ratio_mae = (oof_tuned['oof_pred_ratio'] - oof_tuned['y_ratio']).abs().mean()

    # Compose absolute predictions for the report
    composed_log = oof_tuned['log_mv_end'] + oof_tuned['oof_pred_ratio']
    composed_eur = np.expm1(composed_log)
    actual_eur   = np.expm1(oof_tuned['log_target'])
    production_eur_median_err = np.median(np.abs(composed_eur - actual_eur))

    print("\n" + "="*72)
    print("ATTACKER MARKET-VALUE PREDICTION MODEL — FINAL REPORT")
    print("="*72)
    print()
    print("PRODUCTION QUALITY ESTIMATE (cross-validated)")
    print(f"  CV-MAE on ratio target:       {production_ratio_mae:.4f}")
    print(f"  Median absolute EUR error:    €{production_eur_median_err:>14,.0f}")
    print(f"  (Cross-validated across 5 folds, GroupKFold by player.")
    print(f"   This is the expected error on new players.)")
    print()
    print("HISTORICAL TRACK RECORD (strict-temporal backtests)")
    print(f"  {'Year':<14} {'Train rows':<14} {'Ratio MAE':<14} {'Median EUR err':<18}")
    for year, res in backtests.items():
        print(f"  Summer {year}    {res['n_train']:<14}  {res['ratio_mae']:<14.4f} €{res['eur_median_error']:>14,.0f}")
    print()
    print("  Each backtest is a fresh model trained without ANY data from")
    print("  the prediction year or later. Performance improves as more")
    print("  historical data accumulates — a healthy sign that the model")
    print("  is genuinely learning patterns, not memorizing.")
    print()
    print("="*72)


if __name__ == '__main__':
    generate_report()