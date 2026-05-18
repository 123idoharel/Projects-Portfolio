"""
07_historical_backtests_mh.py — Stage 7: Strict-temporal historical backtests.

For each historical year, train fresh models that NEVER saw any data from
that year or later. This produces an honest "what would the system have
predicted if deployed at that time?" demonstration.

Supports both 1Y and 2Y horizons automatically.
Uses production optimal n_estimators saved in Stage 5.

Usage:
    python 07_historical_backtests_mh.py --horizon 1y
    python 07_historical_backtests_mh.py --horizon 2y
"""
import sys
import argparse
from pathlib import Path
import joblib
import xgboost as xgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

# הגדרת נתיב יחסי ל-setup_mh
sys.path.insert(0, str(Path(__file__).parent))
import setup_mh

def historical_backtest(horizon: str):
    vectors = setup_mh.load_vectors_mh()
    X, y, _ = setup_mh.split_features_target_mh(vectors, horizon)
    target_col = setup_mh.HORIZON_TO_TARGET[horizon]

    # חילוץ מחדש של שנת החיתוך והשווי כדי לחלק את הנתונים בזמן
    valid_idx = X.index
    valid_vectors = vectors.loc[valid_idx].reset_index(drop=True)
    X = X.reset_index(drop=True)
    y = y.reset_index(drop=True)

    model_dir = setup_mh.MODELS_MH_DIR / horizon
    
    best_params_mean      = joblib.load(model_dir / "best_params_mean.pkl")
    best_params_quantiles = joblib.load(model_dir / "best_params_quantiles.pkl")
    optimal_iters         = joblib.load(model_dir / "production_optimal_iters.pkl")

    backtests = {}

    # מציאת השנים שאפשר לבחון. 
    # עבור 1Y יש לנו נתונים עד 2024. עבור 2Y יש רק עד 2023.
    available_years = sorted(valid_vectors['cutoff_year'].unique())
    backtest_years = [y for y in available_years if y >= 2022]

    for target_year in backtest_years:
        # אימון רק על שנים ישנות יותר
        train_years = [c for c in available_years if c < target_year]
        if not train_years:
            continue
            
        train_mask  = valid_vectors['cutoff_year'].isin(train_years)
        val_mask    = valid_vectors['cutoff_year'] == target_year

        if val_mask.sum() == 0:
            continue

        print(f"\n=== Backtest Summer {target_year} (Horizon: {horizon.upper()}) ===")
        print(f"  Train cutoffs: {train_years} (n={train_mask.sum()} players)")
        print(f"  Val cutoff:    {target_year}    (n={val_mask.sum()} players)")

        models      = {}
        preds_ratio = {}

        # 1. מודל הממוצע (Mean model)
        params_final = {**best_params_mean}
        params_final.update({
            'n_estimators': optimal_iters['mean'],
            'tree_method': 'hist',
            'enable_categorical': True
        })
        params_final.pop('early_stopping_rounds', None)
        
        models['mean'] = xgb.XGBRegressor(**params_final)
        models['mean'].fit(X[train_mask], y[train_mask])
        preds_ratio['mean'] = models['mean'].predict(X[val_mask])

        # 2. מודלי הקוונטילים (Quantile models)
        quantiles_dict = {'pessimistic': 0.10, 'expected': 0.50, 'optimistic': 0.90}
        for label, params in best_params_quantiles.items():
            params_final = {**params}
            params_final.update({
                'n_estimators': optimal_iters[label],
                'tree_method': 'hist',
                'enable_categorical': True,
                'objective': 'reg:quantileerror',
                'quantile_alpha': quantiles_dict[label]
            })
            params_final.pop('early_stopping_rounds', None)
            
            models[label] = xgb.XGBRegressor(**params_final)
            models[label].fit(X[train_mask], y[train_mask])
            preds_ratio[label] = models[label].predict(X[val_mask])

        # 3. הערכת ביצועים
        log_mv_end_val = valid_vectors.loc[val_mask, 'log_mv_end'].values
        actuals_ratio  = y[val_mask].values
        actuals_eur    = np.expm1(valid_vectors.loc[val_mask, target_col].values)

        ratio_mae    = mean_absolute_error(actuals_ratio, preds_ratio['mean'])
        composed_log = log_mv_end_val + preds_ratio['mean']
        composed_eur = np.expm1(composed_log)
        eur_median   = np.median(np.abs(composed_eur - actuals_eur))
        
        # בדיקת כיסוי קוונטילים על הנתונים "העתידיים"
        q10_eur = np.expm1(log_mv_end_val + preds_ratio['pessimistic'])
        q90_eur = np.expm1(log_mv_end_val + preds_ratio['optimistic'])
        coverage = ((actuals_eur >= q10_eur) & (actuals_eur <= q90_eur)).mean() * 100

        print(f"  Ratio MAE:       {ratio_mae:.4f}")
        print(f"  Median EUR err:  €{eur_median:>14,.0f}")
        print(f"  80% Coverage:    {coverage:.1f}%")

        backtests[target_year] = {
            'tm_id':                     valid_vectors.loc[val_mask, 'tm_id'].values,
            'mv_at_cutoff':              np.expm1(log_mv_end_val),
            'predicted_mean_eur':        composed_eur,
            'predicted_pessimistic_eur': q10_eur,
            'predicted_expected_eur':    np.expm1(log_mv_end_val + preds_ratio['expected']),
            'predicted_optimistic_eur':  q90_eur,
            'actual_eur':                actuals_eur,
            'ratio_mae':                 ratio_mae,
            'eur_median_error':          eur_median,
            'coverage_80':               coverage,
            'n_train':                   int(train_mask.sum()),
        }

    res_dir = setup_mh.RESULTS_MH_DIR / horizon
    res_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(backtests, res_dir / "historical_backtests.pkl")

    print("\n" + "="*75)
    print(f"HISTORICAL BACKTEST SUMMARY ({horizon.upper()})")
    print("="*75)
    print(f"  {'Year':<10} {'Train rows':<14} {'Ratio MAE':<14} {'Median EUR err':<18} {'Coverage'}")
    for year, res in backtests.items():
        print(f"  {year:<10} {res['n_train']:<14} {res['ratio_mae']:<14.4f} €{res['eur_median_error']:<17,.0f} {res['coverage_80']:.1f}%")
    print(f"\n  Saved to {res_dir.name}/historical_backtests.pkl")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizon', required=True, choices=setup_mh.VALID_HORIZONS)
    args = parser.parse_args()
    historical_backtest(args.horizon)