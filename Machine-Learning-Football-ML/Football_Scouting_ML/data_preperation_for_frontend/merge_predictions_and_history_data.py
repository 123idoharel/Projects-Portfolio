import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
import json

# =====================================================================
# 1. הגדרות נתיבים ושמות קבצים
# =====================================================================
CURRENT_DIR = Path(__file__).resolve().parent
if 'football_scouting_project' in CURRENT_DIR.parts:
    root_idx = CURRENT_DIR.parts.index('football_scouting_project')
    PROJECT_ROOT = Path(*CURRENT_DIR.parts[:root_idx + 1])
else:
    PROJECT_ROOT = CURRENT_DIR.parent

DATA_DIR     = PROJECT_ROOT / "data" / "processed"
VEC_DIR      = DATA_DIR / "att_inference_vectors"
PRED_DIR     = DATA_DIR / "att_predictions"
FRONTEND_DIR = PROJECT_ROOT / "frontend_data"

# קבצי המקור המדויקים על פי הסריקה
ORIGINAL_DB_FILE = PROJECT_ROOT / "data" / "raw" / "database_ATT.csv"
VECTORS_FILE     = VEC_DIR / "att_inference_2425.csv"
PRED_MH_FILE     = PRED_DIR / "att_predictions_2425_mh.csv"
PRED_PEAK_FILE   = PRED_DIR / "att_predictions_2425.csv"

# Optional q75 prediction files (separate, decoupled pipeline).
# Built by 07_q75_inference.py and 07_q75_inference_mh.py.
# If these don't exist, q75 fields stay null — frontend falls back to
# the post-hoc shrinkage rule on q90.
PRED_PEAK_Q75_FILE = PRED_DIR / "q75" / "att_predictions_2425_q75.csv"
PRED_MH_Q75_FILE   = PRED_DIR / "q75" / "att_predictions_2425_q75_mh.csv"

# רשימת הטורנירים לפסילה בעת שליפת הליגה הנוכחית מהקובץ המקורי
TOURNAMENTS_LIST = [
    'FIFA World Cup', 'CONCACAF Gold Cup', 'UEFA European Championship', 
    'CONMEBOL Copa Libertadores', 'UEFA Europa League', 
    'UEFA Conference League', 'UEFA Champions League', 
    'Copa America', 'Africa Cup of Nations', 'AFC Asian Cup'
]

# =====================================================================
# 2. פונקציות עזר
# =====================================================================
def calculate_risk_score(pred, low, high):
    """חישוב רמת הביטחון/סיכון נטו כמספר עשרוני"""
    if not pred or pred <= 0 or pd.isna(pred): return None
    return round((high - low) / pred, 3)

def clean_nans(obj):
    """מנקה ערכי NaN כדי לייצר JSON תקין"""
    import math
    if isinstance(obj, dict): return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list): return [clean_nans(v) for v in obj]
    elif isinstance(obj, (float, np.float64, np.float32)):
        return None if math.isnan(obj) or math.isinf(obj) else float(obj)
    elif isinstance(obj, (np.int64, np.int32)): return int(obj)
    return obj

def is_forbidden_column(col_name):
    """
    בודק האם יש להסיר את העמודה.
    - מסיר לחלוטין את future_max_value
    - מסיר מילים עם target *רק* אם יש בהן גם log
    """
    col_lower = col_name.lower()
    
    if 'future_max_value' in col_lower:
        return True
        
    if 'target' in col_lower and 'log' in col_lower:
        return True
        
    return False

def fix_quantile_crossing(q75, q90):
    """
    Quantile crossing happens when q75 > q90 in some rows because each quantile
    is trained independently. Mathematically q75 should always be ≤ q90 (it's
    a less extreme bullish band). We enforce the relationship at the merge step
    by capping q75 at q90.
    Returns (q75_fixed, was_crossed_flag).
    """
    if q75 is None or pd.isna(q75): return None, False
    if q90 is None or pd.isna(q90): return q75, False
    if q75 > q90:
        return q90, True
    return q75, False

# =====================================================================
# 3. בניית מסד הנתונים הראשי
# =====================================================================
def build_core_database():
    print("=" * 80)
    print("🚀 STAGE 8: BUILDING CORE FRONTEND DB (STRICT SEPARATION)")
    print("=" * 80)

    print("[*] Loading datasets...")
    try:
        raw_df = pd.read_csv(ORIGINAL_DB_FILE, low_memory=False)
        vec_df = pd.read_csv(VECTORS_FILE, low_memory=False)
        p2_df  = pd.read_csv(PRED_MH_FILE)
        print(f"    ✓ Original DB loaded: {len(raw_df):,} rows")
        print(f"    ✓ Vectors loaded:     {len(vec_df):,} players")
        print(f"    ✓ MH Predictions:     {len(p2_df):,} players")
    except Exception as e:
        print(f"[!] Error loading main files: {e}")
        return

    try:
        p1_df = pd.read_csv(PRED_PEAK_FILE)
        print(f"    ✓ Peak Predictions:   {len(p1_df):,} players")
    except:
        print("    [!] Peak predictions (1) not found. Using empty structure.")
        p1_df = pd.DataFrame(columns=['tm_id'])

    # ----- Optional q75 predictions (loaded gracefully if absent) -----
    p1_q75_df = None
    p2_q75_df = None
    try:
        if PRED_PEAK_Q75_FILE.exists():
            p1_q75_df = pd.read_csv(PRED_PEAK_Q75_FILE)
            print(f"    ✓ Peak q75 Predictions: {len(p1_q75_df):,} players")
        else:
            print("    [i] Peak q75 not found — frontend will fall back to shrinkage on q90.")
    except Exception as e:
        print(f"    [!] Could not load peak q75: {e}")

    try:
        if PRED_MH_Q75_FILE.exists():
            p2_q75_df = pd.read_csv(PRED_MH_Q75_FILE)
            print(f"    ✓ MH q75 Predictions:   {len(p2_q75_df):,} players")
        else:
            print("    [i] MH q75 not found — 1y/2y will not have q75.")
    except Exception as e:
        print(f"    [!] Could not load MH q75: {e}")

    # הכנת מילונים לשליפה מהירה
    p1_dict = p1_df.set_index('tm_id').to_dict('index')
    p2_dict = p2_df.set_index('tm_id').to_dict('index')
    vec_dict = vec_df.set_index('tm_id').to_dict('index')

    # q75 lookup dicts (empty if files weren't loaded)
    p1_q75_dict = p1_q75_df.set_index('tm_id').to_dict('index') if p1_q75_df is not None else {}
    p2_q75_dict = p2_q75_df.set_index('tm_id').to_dict('index') if p2_q75_df is not None else {}

    frontend_db = {}
    valid_tm_ids = set(p2_df['tm_id'].unique())
    
    # משתני סטטיסטיקה למעקב
    stats = {
        "processed": 0,
        "missing_s24": 0,
        "fallback_mv_used": 0,
        "total_history_rows": 0,
        "missing_sofa_id": 0,
        "q75_peak_attached": 0,
        "q75_h1_attached":   0,
        "q75_h2_attached":   0,
        "q75_crossings_fixed": 0,
    }

    print(f"\n[*] Processing data for {len(valid_tm_ids)} valid players...")

    for tm_id in valid_tm_ids:
        # --- א. חילוץ מטא-דאטא מהוקטור של 24/25 ---
        player_vec = vec_dict.get(tm_id, {})
        vec_age = player_vec.get('age_at_cutoff') 
        primary_pos = player_vec.get('primary_position')
        secondary_pos = player_vec.get('secondary_position')

        # --- ב. חילוץ מטא-דאטא מהדאטא המקורי ---
        player_raw_rows = raw_df[raw_df['tm_id'] == tm_id]
        if player_raw_rows.empty: 
            continue

        # מציאת שורות עונת 24/25
        season_mask = player_raw_rows['_season_year'].astype(str).isin(['24/25', '2025', '2024/2025'])
        s24_rows = player_raw_rows[season_mask]

        current_team, current_league, sofa_id, current_mv = None, None, None, None
        player_name = str(player_raw_rows.iloc[-1].get('player', f"Player_{tm_id}"))

        if not s24_rows.empty:
            # סינון טורנירים (מוודאים שהליגה לא נמצאת ברשימת הטורנירים)
            league_only = s24_rows[~s24_rows['_league'].isin(TOURNAMENTS_LIST)]

            # אם לא נשאר כלום, ניקח מה שיש. אם יש, נעבוד רק עם הליגות המקומיות
            working_df = league_only if not league_only.empty else s24_rows
            
            # לקיחת השורה עם הכי הרבה הופעות מתוך עונת 24/25
            if 'appearances' in working_df.columns:
                best_24_row = working_df.sort_values('appearances', ascending=False).iloc[0]
            else:
                best_24_row = working_df.iloc[0]
            
            # שליפת המידע הרלוונטי על פי שמות העמודות שאיתרנו
            current_team = best_24_row.get('team')
            current_league = best_24_row.get('_league')
            sofa_id = best_24_row.get('player id')
            
            # שווי נוכחי
            if 'mv_end' in best_24_row and pd.notna(best_24_row['mv_end']) and best_24_row['mv_end'] > 0:
                current_mv = best_24_row['mv_end']
        else:
            stats["missing_s24"] += 1
        
        # גיבוי לשווי מתוך קובץ התחזיות
        if not current_mv or current_mv == 0:
            current_mv = p2_dict.get(tm_id, {}).get('mv_at_cutoff', None)
            stats["fallback_mv_used"] += 1

        if pd.isna(sofa_id):
            stats["missing_sofa_id"] += 1

        # --- ג. ארגון נתוני מודלים וחישוב מידת ביטחון כמספר ---
        p1 = p1_dict.get(tm_id, {})
        p1_q75 = p1_q75_dict.get(tm_id, {})
        peak_q75_raw = p1_q75.get('predicted_q75_eur')
        peak_q90     = p1.get('predicted_optimistic_eur')
        peak_q75_fixed, peak_crossed = fix_quantile_crossing(peak_q75_raw, peak_q90)
        if peak_crossed: stats["q75_crossings_fixed"] += 1
        if peak_q75_fixed is not None: stats["q75_peak_attached"] += 1

        peak_model = {
            "expected_eur": p1.get('predicted_expected_eur'),
            "pessimistic_eur": p1.get('predicted_pessimistic_eur'),
            "optimistic_eur": peak_q90,
            "optimistic_q75_eur": peak_q75_fixed,
            "upside_multiple": p1.get('upside_multiple'),
            "risk_score": calculate_risk_score(p1.get('predicted_expected_eur'), p1.get('predicted_pessimistic_eur'), p1.get('predicted_optimistic_eur'))
        }

        p2 = p2_dict.get(tm_id, {})
        p2_q75 = p2_q75_dict.get(tm_id, {})

        h1_q75_raw = p2_q75.get('q75_1y_eur')
        h1_q90     = p2.get('high_1y_eur')
        h1_q75_fixed, h1_crossed = fix_quantile_crossing(h1_q75_raw, h1_q90)
        if h1_crossed: stats["q75_crossings_fixed"] += 1
        if h1_q75_fixed is not None: stats["q75_h1_attached"] += 1

        h1_model = {
            "expected_eur": p2.get('pred_1y_eur'),
            "pessimistic_eur": p2.get('low_1y_eur'),
            "optimistic_eur": h1_q90,
            "optimistic_q75_eur": h1_q75_fixed,
            "upside_multiple": round(p2.get('high_1y_eur') / current_mv, 2) if current_mv and p2.get('high_1y_eur') else None,
            "risk_score": calculate_risk_score(p2.get('pred_1y_eur'), p2.get('low_1y_eur'), p2.get('high_1y_eur'))
        }

        h2_q75_raw = p2_q75.get('q75_2y_eur')
        h2_q90     = p2.get('high_2y_eur')
        h2_q75_fixed, h2_crossed = fix_quantile_crossing(h2_q75_raw, h2_q90)
        if h2_crossed: stats["q75_crossings_fixed"] += 1
        if h2_q75_fixed is not None: stats["q75_h2_attached"] += 1

        h2_model = {
            "expected_eur": p2.get('pred_2y_eur'),
            "pessimistic_eur": p2.get('low_2y_eur'),
            "optimistic_eur": h2_q90,
            "optimistic_q75_eur": h2_q75_fixed,
            "upside_multiple": p2.get('upside_multiple'),
            "risk_score": calculate_risk_score(p2.get('pred_2y_eur'), p2.get('low_2y_eur'), p2.get('high_2y_eur'))
        }

        # --- ד. היסטוריה נקייה מזליגות עתידיות ---
        history_list = []
        for _, row in player_raw_rows.sort_values('_season_year', ascending=False).iterrows():
            row_dict = row.to_dict()
            clean_row = {k: v for k, v in row_dict.items() if not is_forbidden_column(k)}
            history_list.append(clean_row)
            stats["total_history_rows"] += 1

        # --- ה. הרכבת ה-JSON הסופי ---
        frontend_db[str(tm_id)] = clean_nans({
            "metadata": {
                "tm_id": int(tm_id),
                "sofascore_id": int(sofa_id) if pd.notna(sofa_id) else None,
                "name": str(player_name),
                "age_at_cutoff": float(vec_age) if pd.notna(vec_age) else None,
                "primary_position": str(primary_pos) if pd.notna(primary_pos) else None,
                "secondary_position": str(secondary_pos) if pd.notna(secondary_pos) else None,
                "current_league": str(current_league) if pd.notna(current_league) else None,
                "current_team": str(current_team) if pd.notna(current_team) else None,
                "current_value_eur": float(current_mv) if current_mv else None
            },
            "models": {
                "peak_potential": peak_model,
                "horizon_1y": h1_model,
                "horizon_2y": h2_model
            },
            "history_data": history_list,
            "advanced_stats": player_vec 
        })
        
        stats["processed"] += 1

    # שמירה
    FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    out_file = FRONTEND_DIR / "core_players_db.json"
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(frontend_db, f, ensure_ascii=False, indent=2)

    # יצירת דוח סיכום מרשים בסיום הריצה
    try:
        file_size_mb = os.path.getsize(out_file) / (1024 * 1024)
    except:
        file_size_mb = 0

    print("\n" + "=" * 80)
    print("📊 EXECUTION STATISTICS & SUMMARY")
    print("=" * 80)
    print(f"✅ Total Players Processed:      {stats['processed']:,}")
    print(f"📚 Total History Rows Packed:    {stats['total_history_rows']:,}")
    print(f"⚠️  Players missing 24/25 data:  {stats['missing_s24']:,} (Used historical fallback)")
    print(f"🔄 Players using Fallback MV:    {stats['fallback_mv_used']:,} (Pulled from Predictions)")
    print(f"❓ Players missing Sofascore ID: {stats['missing_sofa_id']:,}")
    print("-" * 80)
    print(f"📊 q75 (Optimistic Calibrated Band):")
    print(f"     attached to peak model:      {stats['q75_peak_attached']:,}  ({stats['q75_peak_attached']/max(stats['processed'],1)*100:.1f}%)")
    print(f"     attached to 1y model:        {stats['q75_h1_attached']:,}  ({stats['q75_h1_attached']/max(stats['processed'],1)*100:.1f}%)")
    print(f"     attached to 2y model:        {stats['q75_h2_attached']:,}  ({stats['q75_h2_attached']/max(stats['processed'],1)*100:.1f}%)")
    print(f"     quantile crossings (q75>q90) fixed: {stats['q75_crossings_fixed']:,}")
    print("-" * 80)
    print(f"📁 Output File: {out_file.name}")
    print(f"💾 File Size:   {file_size_mb:.2f} MB")
    print("=" * 80)
    print("[+] BOOM! Core Database built perfectly and ready for Frontend Integration!")

if __name__ == '__main__':
    build_core_database()