"""
06_historical_backtests.py — Stage 6: Strict-temporal historical backtests.

For each historical year, train fresh models that NEVER saw any data from
that year or later. This produces an honest "what would the system have
predicted if deployed at that time?" demonstration.

Trains 3 backtest sets: summer 2022, summer 2023, summer 2024.
Each uses identical hyperparameters to the production model — only the
training data window differs.

n_estimators handling: same approach as 05_production.py — uses the
production_optimal_iters.pkl saved by Stage 5 to set the right tree count.
This ensures backtest models are sized appropriately even though they have
less training data.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import setup

import joblib
import xgboost as xgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error


def historical_backtest():
    vectors = setup.load_vectors()
    X, y, _ = setup.split_features_target(vectors)

    # Reattach cutoff_year and log_mv_end for masking and prediction composition
    valid_idx = X.index
    valid_vectors = vectors.loc[valid_idx].reset_index(drop=True)
    X = X.reset_index(drop=True)
    y = y.reset_index(drop=True)

    best_params_mean      = joblib.load(setup.MODEL_DIR / "best_params_mean.pkl")
    best_params_quantiles = joblib.load(setup.MODEL_DIR / "best_params_quantiles.pkl")
    optimal_iters         = joblib.load(setup.MODEL_DIR / "production_optimal_iters.pkl")

    backtests = {}

    for target_year in [2022, 2023, 2024]:
        train_years = [c for c in [2020, 2021, 2022, 2023] if c < target_year]
        train_mask  = valid_vectors['cutoff_year'].isin(train_years)
        val_mask    = valid_vectors['cutoff_year'] == target_year

        print(f"\n=== Backtest summer {target_year} ===")
        print(f"  Train cutoffs: {train_years} (n={train_mask.sum()})")
        print(f"  Val cutoff:    {target_year}    (n={val_mask.sum()})")

        models      = {}
        preds_ratio = {}

        # Mean model
        params_final = {**best_params_mean}
        params_final['n_estimators'] = optimal_iters['mean']
        params_final.pop('early_stopping_rounds', None)
        models['mean'] = xgb.XGBRegressor(**params_final)
        models['mean'].fit(X[train_mask], y[train_mask])
        preds_ratio['mean'] = models['mean'].predict(X[val_mask])

        # Quantile models
        for label, params in best_params_quantiles.items():
            params_final = {**params}
            params_final['n_estimators'] = optimal_iters[label]
            params_final['tree_method']  = 'hist'
            params_final.pop('early_stopping_rounds', None)
            models[label] = xgb.XGBRegressor(**params_final)
            models[label].fit(X[train_mask], y[train_mask])
            preds_ratio[label] = models[label].predict(X[val_mask])

        log_mv_end_val = valid_vectors.loc[val_mask, 'log_mv_end'].values
        actuals_ratio  = y[val_mask].values
        actuals_eur    = np.expm1(valid_vectors.loc[val_mask, 'log_target'].values)

        ratio_mae    = mean_absolute_error(actuals_ratio, preds_ratio['mean'])
        composed_log = log_mv_end_val + preds_ratio['mean']
        composed_eur = np.expm1(composed_log)
        eur_mae      = mean_absolute_error(actuals_eur, composed_eur)
        eur_median   = np.median(np.abs(composed_eur - actuals_eur))

        print(f"  MAE on ratio: {ratio_mae:.4f}")
        print(f"  MAE in EUR:   €{eur_mae:>14,.0f}")
        print(f"  Median EUR error: €{eur_median:>14,.0f}")

        backtests[target_year] = {
            'tm_id':                     valid_vectors.loc[val_mask, 'tm_id'].values,
            'mv_at_cutoff':              np.expm1(valid_vectors.loc[val_mask, 'log_mv_end'].values),
            'predicted_mean_eur':        np.expm1(log_mv_end_val + preds_ratio['mean']),
            'predicted_pessimistic_eur': np.expm1(log_mv_end_val + preds_ratio['pessimistic']),
            'predicted_expected_eur':    np.expm1(log_mv_end_val + preds_ratio['expected']),
            'predicted_optimistic_eur':  np.expm1(log_mv_end_val + preds_ratio['optimistic']),
            'actual_eur':                actuals_eur,
            'ratio_mae':                 ratio_mae,
            'eur_mae':                   eur_mae,
            'eur_median_error':          eur_median,
            'n_train':                   int(train_mask.sum()),
        }

    joblib.dump(backtests, setup.RESULT_DIR / "historical_backtests.pkl")

    print("\n" + "="*72)
    print("HISTORICAL BACKTEST SUMMARY")
    print("="*72)
    print(f"  {'Year':<14} {'Train rows':<14} {'Ratio MAE':<14} {'Median EUR err':<18}")
    for year, res in backtests.items():
        print(f"  Summer {year}    {res['n_train']:<14}  {res['ratio_mae']:<14.4f} €{res['eur_median_error']:>14,.0f}")
    print(f"\n  Saved to {setup.RESULT_DIR / 'historical_backtests.pkl'}")


if __name__ == '__main__':
    historical_backtest()