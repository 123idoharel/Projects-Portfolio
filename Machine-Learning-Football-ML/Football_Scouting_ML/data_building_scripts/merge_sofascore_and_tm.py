import pandas as pd
import numpy as np
import time

# =====================================================================
# 1. FILE CONFIGURATION
# =====================================================================
DB_FILE = "FINAL_DATABASE_POST_1983.csv"
VALUATIONS_FILE = "player_valuations_ALL_FINAL.csv"
OUTPUT_DB_FILE = "FINAL_DATABASE_WITH_VALUATIONS.csv"
DIAGNOSTICS_FILE = "valuations_missing_diagnostics.csv"

# =====================================================================
# 2. HELPER FUNCTIONS
# =====================================================================
def parse_season_to_anchors(season_str):
    """
    מתרגם מחרוזת עונה לתאריכי עוגן (התחלה וסיום)
    חסין לכל סוגי הפורמטים: 23/24, 2023/2024, 2023-24, 2023.0 וכו'.
    """
    s = str(season_str).strip()
    try:
        if '/' in s or '-' in s:
            delim = '/' if '/' in s else '-'
            p1 = s.split(delim)[0].strip()
            year = int(p1)
            # אם השנה נכתבה כ-2 ספרות (למשל 23), נהפוך ל-2023
            if year < 100:
                year += 2000
            return pd.Timestamp(year, 7, 1), pd.Timestamp(year + 1, 6, 30)
        else:
            # עונה קלנדרית (float מטפל במקרים של '2023.0')
            year = int(float(s))
            if year < 100:
                year += 2000
            return pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 31)
    except:
        return pd.NaT, pd.NaT

def get_valuation(anchor_date, player_vals, anchor_type="START"):
    """
    מוצא את השווי הקרוב ביותר לפי לוגיקה א-סימטרית:
    START: 5 חודשים אחורה עד 7 חודשים קדימה.
    END: 5 חודשים אחורה עד 5 חודשים קדימה.
    גיבוי: עד שנתיים (730 יום) אחורה.
    """
    if player_vals.empty or pd.isna(anchor_date):
        return np.nan, pd.NaT, np.nan, pd.NaT, np.nan
    
    # חישוב הפער בימים (שלילי = בעבר, חיובי = בעתיד)
    deltas = (player_vals['date'] - anchor_date).dt.total_seconds() / 86400
    
    # הגדרת גבולות החלון המותרים לפי סוג העוגן
    if anchor_type == "START":
        min_days, max_days = -150, 210  # -5 months to +7 months
    else:
        min_days, max_days = -150, 150  # -5 months to +5 months
        
    # מציאת הערך הכללי הכי קרוב (ללא גבולות) רק לטובת הדיאגנוסטיקה
    abs_deltas = deltas.abs()
    nearest_idx = abs_deltas.idxmin()
    alt_v = player_vals.loc[nearest_idx, 'market_value']
    alt_d = player_vals.loc[nearest_idx, 'date']
    alt_diff = abs_deltas[nearest_idx]

    # 1. חיפוש בתוך חלון הזמן המותר
    in_window = player_vals[(deltas >= min_days) & (deltas <= max_days)]
    
    if not in_window.empty:
        # בתוך החלון, נמצא את זה שהמרחק המוחלט שלו הוא הקטן ביותר מנקודת העוגן
        window_abs_deltas = (in_window['date'] - anchor_date).dt.total_seconds().abs()
        best_idx = window_abs_deltas.idxmin()
        closest_diff = window_abs_deltas[best_idx]
        return in_window.loc[best_idx, 'market_value'], in_window.loc[best_idx, 'date'], alt_v, alt_d, closest_diff
    
    # 2. גיבוי (Fallback): חיפוש רק אחורה בזמן, עד שנתיים (730 ימים)
    past_vals = player_vals[deltas < min_days] # רק מה שהיה לפני תחילת החלון המותר
    if not past_vals.empty:
        last_known_idx = past_vals['date'].idxmax() # התאריך המאוחר ביותר בעבר
        last_known_date = past_vals.loc[last_known_idx, 'date']
        last_known_val = past_vals.loc[last_known_idx, 'market_value']
        past_diff_days = (anchor_date - last_known_date).days
        
        if past_diff_days <= 730: # הורחב לשנתיים!
            return last_known_val, last_known_date, alt_v, alt_d, past_diff_days
            
    # שום דבר לא נמצא בשנתיים האחרונות ולא בחלון הקרוב
    return np.nan, pd.NaT, alt_v, alt_d, alt_diff

# =====================================================================
# 3. MAIN SCRIPT
# =====================================================================
def main():
    print(f"📂 Loading Databases...")
    df_db = pd.read_csv(DB_FILE, low_memory=False)
    df_val = pd.read_csv(VALUATIONS_FILE, low_memory=False)
    
    # --- מיפוי עמודות חסין שגיאות (Bulletproof Column Renaming) ---
    col_mapping = {}
    for col in df_db.columns:
        col_lower = col.strip().lower()
        if col_lower == 'tm_id':
            col_mapping[col] = 'tm_id'
        elif col_lower in ['_season_year', 'season']:
            col_mapping[col] = 'season'
            
    if col_mapping:
        df_db.rename(columns=col_mapping, inplace=True)
        print(f"🔧 Mapped original columns to working names: {col_mapping}")
    # --------------------------------------------------------------
        
    # נרמול מזהים (מוודא שכולם מספרים שלמים)
    df_db['tm_id'] = pd.to_numeric(df_db['tm_id'], errors='coerce').fillna(-1).astype(int)
    df_val['tm_id'] = pd.to_numeric(df_val['tm_id'], errors='coerce').fillna(-1).astype(int)
    
    # תיקון הפורמט המעורב בתאריכים מקובץ ה-TM
    df_val['date'] = pd.to_datetime(df_val['date'], format='mixed', dayfirst=True, errors='coerce')
    
    valid_tm_ids = df_val['tm_id'].unique()
    
    # סינון ה-DB (נפתרים משחקנים בלי שווי כלל)
    initial_rows = len(df_db)
    df_db = df_db[df_db['tm_id'].isin(valid_tm_ids)].copy()
    print(f"🧹 Filtered DB: Kept {len(df_db):,} rows out of {initial_rows:,} (Removed players without valuation data).")
    
    print("📈 Calculating Max Career Values...")
    max_vals = df_val.groupby('tm_id')['market_value'].max().rename('max_career_value')
    df_db = df_db.merge(max_vals, on='tm_id', how='left')
    
    print("⚓ Parsing seasons to anchor dates...")
    anchors = df_db['season'].apply(parse_season_to_anchors)
    df_db['anchor_start'] = [a[0] for a in anchors]
    df_db['anchor_end'] = [a[1] for a in anchors]
    
    print("🔄 Matching valuations to seasons (this might take a few minutes)...")
    start_time = time.time()
    
    # אתחול העמודות החדשות
    df_db['mv_start'] = np.nan
    df_db['mv_start_date'] = pd.NaT
    df_db['mv_end'] = np.nan
    df_db['mv_end_date'] = pd.NaT
    
    diagnostics = []
    # הפיכת קובץ השווי למילון מהיר (מפתח = tm_id, ערך = כל השווים שלו)
    grouped_val = dict(tuple(df_val.groupby('tm_id')))
    total_rows_to_process = len(df_db)
    
    # מעבר על ה-DB למילוי השווים לכל שורה
    for i, row in enumerate(df_db.itertuples()):
        tm_id = row.tm_id
        idx = row.Index
        
        if i > 0 and i % 25000 == 0:
            print(f"   ⏳ Processed {i:,} / {total_rows_to_process:,} rows...")
            
        player_name = getattr(row, 'player', getattr(row, 'player_name', str(tm_id)))
        season = row.season
        
        player_vals = grouped_val.get(tm_id, pd.DataFrame())
        
        # 1. חיפוש שווי תחילת עונה (מעבירים "START")
        v_s, d_s, alt_v_s, alt_d_s, diff_s = get_valuation(row.anchor_start, player_vals, anchor_type="START")
        df_db.at[idx, 'mv_start'] = v_s
        df_db.at[idx, 'mv_start_date'] = d_s
        
        if pd.isna(v_s) and not pd.isna(row.anchor_start):
            diagnostics.append({
                'tm_id': tm_id, 'player': player_name, 'season': season,
                'anchor_type': 'START', 'anchor_date': row.anchor_start,
                'closest_alternative_value': alt_v_s, 'closest_alternative_date': alt_d_s,
                'distance_days': diff_s
            })
            
        # 2. חיפוש שווי סוף עונה (מעבירים "END")
        v_e, d_e, alt_v_e, alt_d_e, diff_e = get_valuation(row.anchor_end, player_vals, anchor_type="END")
        df_db.at[idx, 'mv_end'] = v_e
        df_db.at[idx, 'mv_end_date'] = d_e
        
        if pd.isna(v_e) and not pd.isna(row.anchor_end):
            diagnostics.append({
                'tm_id': tm_id, 'player': player_name, 'season': season,
                'anchor_type': 'END', 'anchor_date': row.anchor_end,
                'closest_alternative_value': alt_v_e, 'closest_alternative_date': alt_d_e,
                'distance_days': diff_e
            })

    # =================================================================
    # חוק הרציפות (Continuity Rule)
    # =================================================================
    print("🔗 Applying Season Continuity Rule...")
    df_db.sort_values(by=['tm_id', 'anchor_start'], inplace=True)
    df_db.reset_index(drop=True, inplace=True)
    
    for i in range(1, len(df_db)):
        if df_db.at[i, 'tm_id'] == df_db.at[i-1, 'tm_id']:
            gap_days = (df_db.at[i, 'anchor_start'] - df_db.at[i-1, 'anchor_end']).days
            if pd.notna(gap_days) and gap_days < 185:
                df_db.at[i, 'mv_start'] = df_db.at[i-1, 'mv_end']
                df_db.at[i, 'mv_start_date'] = df_db.at[i-1, 'mv_end_date']

    print(f"✅ Matching complete in {round(time.time() - start_time, 1)} seconds.")

    # ניקוי עמודות עזר
    df_db.drop(columns=['anchor_start', 'anchor_end'], inplace=True)
    
    # הפיכת השמות חזרה לשמות המקוריים (TM_ID וכו') כדי לשמור על תאימות
    reverse_mapping = {v: k for k, v in col_mapping.items()}
    df_db.rename(columns=reverse_mapping, inplace=True)
    
    # שמירה
    df_db.to_csv(OUTPUT_DB_FILE, index=False)
    
    if diagnostics:
        pd.DataFrame(diagnostics).to_csv(DIAGNOSTICS_FILE, index=False)

    # =================================================================
    # דוח סטטיסטיקה
    # =================================================================
    total_rows = len(df_db)
    nan_start_rows = df_db['mv_start'].isna().sum()
    nan_end_rows = df_db['mv_end'].isna().sum()
    rows_with_any_nan = df_db[['mv_start', 'mv_end']].isna().any(axis=1).sum()
    
    actual_tm_id_col = reverse_mapping.get('tm_id', 'tm_id')
    df_db['has_nan'] = df_db[['mv_start', 'mv_end']].isna().any(axis=1)
    player_nan_counts = df_db.groupby(actual_tm_id_col)['has_nan'].sum()
    
    perfect_players = (player_nan_counts == 0).sum()
    one_nan_players = (player_nan_counts == 1).sum()
    total_players = len(player_nan_counts)
    
    print("\n=======================================================")
    print("  📊 MERGE STATISTICS & DATA QUALITY REPORT")
    print("=======================================================")
    print(f"  📁 Data Shape:")
    print(f"     ▪ Unique Players Analyzed : {total_players:,}")
    print(f"     ▪ Total Seasons (Rows)    : {total_rows:,}")
    print("-------------------------------------------------------")
    print(f"  ⚠️ Missing Values (NaNs):")
    print(f"     ▪ Rows with NaN at Start  : {nan_start_rows:,} ({round(nan_start_rows/total_rows*100, 1)}%)")
    print(f"     ▪ Rows with NaN at End    : {nan_end_rows:,} ({round(nan_end_rows/total_rows*100, 1)}%)")
    print(f"     ▪ Total Rows with ANY NaN : {rows_with_any_nan:,} ({round(rows_with_any_nan/total_rows*100, 1)}%)")
    print("-------------------------------------------------------")
    print(f"  👤 Player Quality Distribution:")
    print(f"     ▪ PERFECT Players (0 NaNs): {perfect_players:,} ({round(perfect_players/total_players*100, 1)}%)")
    print(f"     ▪ Players with 1 NaN Row  : {one_nan_players:,} ({round(one_nan_players/total_players*100, 1)}%)")
    print(f"     ▪ Players with 2+ NaNs    : {total_players - perfect_players - one_nan_players:,}")
    print("=======================================================")
    print(f"  💾 Final Merged DB saved to  : {OUTPUT_DB_FILE}")
    if diagnostics:
        print(f"  🛠️ Diagnostics log saved to  : {DIAGNOSTICS_FILE}")
    print("=======================================================\n")

if __name__ == "__main__":
    main()