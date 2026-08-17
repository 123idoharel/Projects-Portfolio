import pandas as pd
import numpy as np

# =====================================================================
# CONFIGURATION
# =====================================================================
INPUT_FILE = "FINAL_DATABASE_WITH_VALUATIONS.csv"
OUTPUT_FILE = "FINAL_DATABASE_IMPUTED.csv"

def main():
    print("📂 Loading the merged database...")
    df = pd.read_csv(INPUT_FILE, low_memory=False)
    
    initial_rows = len(df)
    
    # מציאת עמודת המזהה הנכונה (למקרה שהיא באותיות גדולות או קטנות)
    tm_id_col = 'tm_id' if 'tm_id' in df.columns else 'TM_ID'
    
    print("🔍 Analyzing missing data patterns...")
    # בדיקה באילו שורות יש חוסרים
    df['row_has_nan'] = df[['mv_start', 'mv_end']].isna().any(axis=1)
    
    # ספירת חוסרים פר שחקן
    nan_counts = df.groupby(tm_id_col)['row_has_nan'].sum()
    
    # ספירת עונות (שורות) פר שחקן
    season_counts = df.groupby(tm_id_col).size()
    
    # === הלוגיקה שלך ===
    # שחקנים עם בדיוק שורה אחת פגומה, ולפחות 3 עונות בדאטא
    target_players = nan_counts[(nan_counts == 1) & (season_counts >= 3)].index
    
    print(f"🎯 Found {len(target_players):,} high-value players with exactly 1 missing value and 3+ seasons!")
    
    # מוסיפים עמודה שתסמן למודל שלך בעתיד שהערך הזה שוחזר מלאכותית (Best Practice)
    df['is_imputed'] = False
    
    imputed_count = 0
    
    print("🛠️ Imputing missing values (Intra-Season Copy)...")
    # מעבר רק על השחקנים שעמדו בתנאי
    mask = df[tm_id_col].isin(target_players)
    
    for idx, row in df[mask].iterrows():
        # אם חסר התחלה, מעתיקים מהסוף
        if pd.isna(row['mv_start']) and pd.notna(row['mv_end']):
            df.at[idx, 'mv_start'] = row['mv_end']
            df.at[idx, 'mv_start_date'] = row['mv_end_date'] # מעתיקים גם תאריך
            df.at[idx, 'is_imputed'] = True
            imputed_count += 1
            
        # אם חסר סיום, מעתיקים מההתחלה
        elif pd.isna(row['mv_end']) and pd.notna(row['mv_start']):
            df.at[idx, 'mv_end'] = row['mv_start']
            df.at[idx, 'mv_end_date'] = row['mv_start_date']
            df.at[idx, 'is_imputed'] = True
            imputed_count += 1

    # ניקוי עמודת העזר
    df.drop(columns=['row_has_nan'], inplace=True)
    
    # שמירה לקובץ הסופי
    df.to_csv(OUTPUT_FILE, index=False)
    
    # =================================================================
    # STATS UPDATE
    # =================================================================
    print("\n=======================================================")
    print("  ✨ IMPUTATION RESULTS")
    print("=======================================================")
    print(f"  ▪ Target Players Identified : {len(target_players):,}")
    print(f"  ▪ Total Values Imputed      : {imputed_count:,}")
    print("-------------------------------------------------------")
    
    # חישוב הסטטוס החדש
    df['has_nan_now'] = df[['mv_start', 'mv_end']].isna().any(axis=1)
    new_nan_counts = df.groupby(tm_id_col)['has_nan_now'].sum()
    perfect_players = (new_nan_counts == 0).sum()
    total_players = len(new_nan_counts)
    
    print(f"  📈 NEW Perfect Players (0 NaNs): {perfect_players:,} ({round(perfect_players/total_players*100, 1)}%)")
    print("=======================================================")
    print(f"  💾 Saved highly enriched database to: {OUTPUT_FILE}")
    
if __name__ == "__main__":
    main()