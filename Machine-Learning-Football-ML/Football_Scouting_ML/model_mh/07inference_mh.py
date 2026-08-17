import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xgboost as xgb
import joblib

# ---------------------------------------------------------------------------
# הגדרות נתיבים
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))
import setup_mh

MIN_VALID_MV_END_EUR = 10_000
TRAINING_POSITIONS = ['LM', 'LW', 'RM', 'RW', 'ST'] 

# מילון בטיחות לעמדות "לא תקניות" (כמו CM שצץ לנו בוקטוריזציה)
POSITION_SAFETY_REMAP = {
    'CM':  ('RM', 'LM'),
    'CAM': ('RM', 'LM'),
    'CF':  ('ST', 'LW'),
    'RB':  ('RM', 'RM'),
    'LB':  ('LM', 'LM'),
}

def filter_valid_players(inference):
    """מסנן שחקנים עם נתוני שווי שוק שבורים/חסרים (מונע אנומליות)"""
    n_total = len(inference)
    drop_reasons = {}

    mask_nan = inference['log_mv_end'].isna()
    drop_reasons['NaN log_mv_end'] = mask_nan.sum()

    mask_zero_or_neg = (inference['log_mv_end'] <= 0) & ~mask_nan
    drop_reasons['log_mv_end <= 0 (broken/missing)'] = mask_zero_or_neg.sum()

    mv_end_eur = np.expm1(inference['log_mv_end'].fillna(-1))
    mask_too_low = (mv_end_eur > 0) & (mv_end_eur < MIN_VALID_MV_END_EUR)
    drop_reasons[f'mv_end < €{MIN_VALID_MV_END_EUR:,}'] = mask_too_low.sum()

    keep_mask = ~(mask_nan | mask_zero_or_neg | mask_too_low)
    valid = inference[keep_mask].copy().reset_index(drop=True)
    return valid, n_total - len(valid), drop_reasons

def apply_position_safety(df):
    """מתקן עמדות לא מוכרות ומדפיס הודעה אם בוצע שינוי"""
    df = df.copy()
    for non_train, (new_p, new_s) in POSITION_SAFETY_REMAP.items():
        mask = df['primary_position'] == non_train
        if mask.any():
            print(f"  [!] Remapping {mask.sum()} player(s) with primary='{non_train}' -> '{new_p}', '{new_s}'")
            df.loc[mask, 'primary_position'] = new_p
            df.loc[mask, 'secondary_position'] = new_s
    return df

def run_mh_inference():
    print("\n" + "="*95)
    print("STAGE 7: MULTI-HORIZON INFERENCE (1Y & 2Y) - PRODUCTION READY")
    print("="*95)

    try:
        # 1. טעינה
        vec_path = setup_mh.PROJECT_ROOT / "data" / "processed" / "inference_vectors_mh" / "inference_vectors_2025_mh.parquet"
        inf_df = pd.read_parquet(vec_path)
        print(f"[*] Loaded {len(inf_df):,} players from vectors.")

        # 2. ניקוי וסינון (עם פירוט בפלט)
        inf_df, n_dropped, reasons = filter_valid_players(inf_df)
        if n_dropped > 0:
            print(f"[*] Filtered {n_dropped} players with missing/broken 24/25 market data:")
            for reason, count in reasons.items():
                if count > 0: print(f"    - {count} players due to: {reason}")
        
        inf_df = apply_position_safety(inf_df)
        print(f"[*] Final scorable players: {len(inf_df):,}")

        # 3. הכנת המטריצה
        log_mv_end_values = inf_df['log_mv_end'].values
        mv_at_cutoff = np.expm1(log_mv_end_values)
        
        to_drop = ['tm_id', 'cutoff_year']
        to_drop += [c for c in setup_mh.phase1_setup.RAW_EUR_TO_DROP]
        to_drop += [c for c in setup_mh.phase1_setup.DATA_QUALITY_DROPS]
        X_inf = inf_df.drop(columns=[c for c in to_drop if c in inf_df.columns])

        # יישור עמודות מול המודל
        temp_m = xgb.XGBRegressor(); temp_m.load_model(setup_mh.MODELS_MH_DIR / '1y' / 'final_model_mean.json')
        X_inf = X_inf[temp_m.get_booster().feature_names]

        for col in ['primary_position', 'secondary_position']:
            X_inf[col] = pd.Categorical(X_inf[col], categories=TRAINING_POSITIONS)

        print("[*] Feature alignment complete. Ready for prediction.")

        output = pd.DataFrame({'tm_id': inf_df['tm_id'], 'mv_at_cutoff': mv_at_cutoff})

        # 4. חיזוי וכיול
        for horizon in setup_mh.VALID_HORIZONS:
            print(f"[>] Predicting {horizon.upper()}...")
            m_dir = setup_mh.MODELS_MH_DIR / horizon
            
            # טעינת מודלים וכיולים
            m_mean = xgb.XGBRegressor(); m_mean.load_model(m_dir / "final_model_mean.json")
            m_low  = xgb.XGBRegressor(); m_low.load_model(m_dir / "final_model_quantile_pessimistic.json")
            m_high = xgb.XGBRegressor(); m_high.load_model(m_dir / "final_model_quantile_optimistic.json")
            
            calibrators = joblib.load(m_dir / "quantile_calibrators.pkl")

            # חיזוי
            r_mean = m_mean.predict(X_inf)
            r_low  = m_low.predict(X_inf)
            r_high = m_high.predict(X_inf)

            # הפעלת הכיול האיזוטוני
            if calibrators.get('pessimistic'): r_low = calibrators['pessimistic'].transform(r_low)
            if calibrators.get('optimistic'):  r_high = calibrators['optimistic'].transform(r_high)

            # המרה ליורו
            output[f'pred_{horizon}_eur'] = np.expm1(log_mv_end_values + r_mean)
            output[f'low_{horizon}_eur']  = np.expm1(log_mv_end_values + r_low)
            output[f'high_{horizon}_eur'] = np.expm1(log_mv_end_values + r_high)
            output[f'growth_{horizon}_pct'] = (output[f'pred_{horizon}_eur'] / output['mv_at_cutoff'] - 1) * 100

        # 5. עיבוד דוח סופי ותצוגה
        output['upside_multiple'] = output['high_2y_eur'] / output['mv_at_cutoff']
        
        # סינון לתצוגה בלבד (שחקנים מעל מיליון יורו)
        display_report = output[output['mv_at_cutoff'] >= 1_000_000].sort_values('upside_multiple', ascending=False)

        show_cols = ['tm_id', 'mv_at_cutoff', 'pred_1y_eur', 'pred_2y_eur', 'growth_2y_pct', 'upside_multiple']
        print(f"\nTop 20 Scouting Targets (Current MV >= €1M):")
        print(display_report.head(20)[show_cols].to_string(index=False, float_format=lambda x: f"{x:,.0f}" if abs(x) > 100 else f"{x:.2f}"))

        # שמירה - שומרים את הכל (output) ולא רק את ה-report המסונן
        out_path = setup_mh.PROJECT_ROOT / "data" / "processed" / "att_predictions" / "att_predictions_2425_mh.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(out_path, index=False)
        
        # הדפסת סטטיסטיקה
        print(f"\n" + "-"*30)
        print(f"INFERENCE STATISTICS:")
        print(f"  Total players saved:    {len(output):,}")
        print(f"  Players >= €1M (shown): {len(display_report):,}")
        print(f"  Output saved to:        {out_path.name}")
        print("-"*30)

    except Exception as e:
        print(f"[!] Critical Error: {str(e)}")

if __name__ == '__main__':
    run_mh_inference()