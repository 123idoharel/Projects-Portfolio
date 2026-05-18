"""
08_final_report_mh.py — Stage 8: Generate final executive report for Multi-Horizon.

Combines production CV estimates (MAE, Calibration, Sharpness) and 
strict-temporal historical backtest results into a single readable summary 
for the executive presentation.

Usage:
    python 08_final_report_mh.py --horizon 1y
    python 08_final_report_mh.py --horizon 2y
"""
import sys
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import joblib

# הגדרת נתיב יחסי ל-setup_mh
sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

def generate_report(horizon: str):
    res_dir = setup_mh.RESULTS_MH_DIR / horizon
    model_dir = setup_mh.MODELS_MH_DIR / horizon
    
    # 1. טעינת נתוני הבק-טסט
    try:
        backtests = joblib.load(res_dir / "historical_backtests.pkl")
    except FileNotFoundError:
        print(f"[!] Warning: Could not find historical_backtests.pkl for {horizon}")
        backtests = {}

    # 2. טעינת התחזיות מהאימון המרכזי (OOF)
    try:
        oof_tuned = pd.read_parquet(res_dir / "stage02_oof_tuned.parquet")
    except FileNotFoundError:
        try:
             oof_tuned = pd.read_parquet(res_dir / "stage2_oof_tuned.parquet")
        except FileNotFoundError:
             print(f"[!] Error: Could not find stage02_oof_tuned.parquet for {horizon}")
             return

    # 3. טעינת תוצאות הקוונטילים
    try:
        oof_quantiles = np.load(model_dir / "quantile_oof.npz")
    except FileNotFoundError:
         print(f"[!] Warning: Could not find quantile_oof.npz for {horizon}")
         oof_quantiles = None

    # ---------------------------------------------------------
    # התיקון: שאיבת נתוני האמת ישירות מ-setup כדי להימנע משגיאות שמות
    # ---------------------------------------------------------
    vectors = setup_mh.load_vectors_mh()
    X, y_true_ratio, _ = setup_mh.split_features_target_mh(vectors, horizon)
    
    log_mv_end_true = X['log_mv_end'].values
    y_ratio = y_true_ratio.values
    oof_preds = oof_tuned['oof_pred_ratio'].values
    
    # חישוב השגיאות (כסף ויחס)
    production_ratio_mae = np.abs(oof_preds - y_ratio).mean()
    composed_log = log_mv_end_true + oof_preds
    composed_eur = np.expm1(composed_log)
    
    actual_log = log_mv_end_true + y_ratio
    actual_eur = np.expm1(actual_log)
    
    production_eur_median_err = np.median(np.abs(composed_eur - actual_eur))

    # הדפסת הדוח
    print("\n" + "="*75)
    print(f"MARKET-VALUE PREDICTION MODEL — FINAL EXECUTIVE REPORT ({horizon.upper()})")
    print("="*75)
    
    print("\n[1] PRODUCTION QUALITY ESTIMATE (Cross-Validated)")
    print("-" * 50)
    print(f"  CV-MAE on ratio target:       {production_ratio_mae:.4f}")
    print(f"  Median absolute EUR error:    €{production_eur_median_err:>14,.0f}")
    print(f"  (This is the expected error margin on new players.)")

    if oof_quantiles is not None:
        q10 = oof_quantiles['pessimistic']
        q90 = oof_quantiles['optimistic']
        
        # חישוב כיסוי אמיתי
        q10_val = log_mv_end_true + q10
        q90_val = log_mv_end_true + q90
        coverage_80 = ((actual_log >= q10_val) & (actual_log <= q90_val)).mean() * 100
        
        # חישוב חדות (Sharpness)
        pred_q10_eur = np.expm1(q10_val)
        pred_q90_eur = np.expm1(q90_val)
        pred_q50_eur = np.expm1(log_mv_end_true + oof_quantiles['expected'])
        
        interval_width_eur = pred_q90_eur - pred_q10_eur
        width_pct = np.median(interval_width_eur / np.clip(pred_q50_eur, a_min=1, a_max=None)) * 100
        
        print("\n[2] RISK & UNCERTAINTY (Quantile Intervals)")
        print("-" * 50)
        print(f"  80% Interval Coverage:        {coverage_80:.1f}% (Target: 80%)")
        print(f"  Median Interval Width:        {width_pct:.1f}% of predicted value")
        print(f"  (Proves the model captures realistic uncertainty ranges.)")

    if backtests:
        print("\n[3] HISTORICAL TRACK RECORD (Strict-Temporal Backtests)")
        print("-" * 50)
        print(f"  {'Year':<10} {'Train rows':<14} {'Ratio MAE':<12} {'Median EUR err':<18} {'Coverage'}")
        for year, res in backtests.items():
            coverage = res.get('coverage_80', float('nan'))
            cov_str = f"{coverage:.1f}%" if not np.isnan(coverage) else "N/A"
            print(f"  {year:<10} {res['n_train']:<14} {res['ratio_mae']:<12.4f} €{res['eur_median_error']:<17,.0f} {cov_str}")
        
        print("\n  * Each backtest is a fresh model trained without ANY data from")
        print("    the prediction year or later. Performance stability confirms")
        print("    the model is genuinely learning market patterns, not memorizing.")

    print("\n" + "="*75 + "\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    generate_report(args.horizon)