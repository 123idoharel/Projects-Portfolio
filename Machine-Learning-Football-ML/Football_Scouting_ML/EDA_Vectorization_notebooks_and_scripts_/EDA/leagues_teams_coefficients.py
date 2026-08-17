import pandas as pd
import os

# --- נתיבים (הנתיבים המעודכנים שלך) ---
ATT_DATA_PATH = '../../data/raw/database_ATT.csv'
LEAGUE_TIERS_PATH = '../../data/league_and_team_coefficients/league_strength.csv'
TEAM_TIERS_PATH = '../../data/league_and_team_coefficients/team_tiers.csv'
PROCESSED_DATA_PATH = '../../data/processed/att_with_tiers_for_eda.csv'

def apply_tiers_with_exact_ordering():
    print("Loading datasets...")
    df_att = pd.read_csv(ATT_DATA_PATH)
    df_league = pd.read_csv(LEAGUE_TIERS_PATH)
    df_team = pd.read_csv(TEAM_TIERS_PATH)
    
    total_original = len(df_att)
    print(f"Total Attacker Records: {total_original}")
    
    # שמירת סדר העמודות המקורי לצורך שחזור המיקום
    original_columns = list(df_att.columns)
    
    # --- 1. מיזוג דירוג ליגות (League Tier) ---
    league_subset = df_league[['league', 'tier']].rename(columns={'league': '_league', 'tier': 'league_tier'})
    df_att = pd.merge(df_att, league_subset, on='_league', how='left')
    
    # --- 2. מיזוג דירוג קבוצות (Team Tier) ---
    # כאן אנחנו ממזגים גם לפי הליגה וגם לפי הקבוצה כמו שסיכמנו
    team_subset = df_team[['_league', 'team', 'team_tier']]
    df_att = pd.merge(df_att, team_subset, on=['_league', 'team'], how='left')
    
    # --- 3. סידור עמודות מחדש (החלפת המקור ב-Tier באותו המיקום בדיוק) ---
    final_column_order = []
    for col in original_columns:
        if col == '_league':
            final_column_order.append('league_tier')
        elif col == 'team':
            final_column_order.append('team_tier')
        else:
            final_column_order.append(col)
            
    # סידור ה-DF לפי הרשימה החדשה - זה אוטומטית מעיף את _league ו-team הישנים
    df_att = df_att[final_column_order]
    
    # --- 4. הצגת סטטיסטיקה לאימות ---
    league_matches = df_att['league_tier'].notna().sum()
    team_matches = df_att['team_tier'].notna().sum()
    
    print("-" * 30)
    print(f"Matching Stats for {total_original} records:")
    print(f"League Match Success: {league_matches}/{total_original} ({(league_matches/total_original)*100:.2f}%)")
    print(f"Team Match Success:   {team_matches}/{total_original} ({(team_matches/total_original)*100:.2f}%)")
    print("-" * 30)
    
    # --- 5. שמירה ---
    os.makedirs(os.path.dirname(PROCESSED_DATA_PATH), exist_ok=True)
    df_att.to_csv(PROCESSED_DATA_PATH, index=False)
    
    print(f"\n✅ Process completed exactly as requested. No fillna applied.")
    print(f"✅ Replaced 'team' and '_league' with 'team_tier' and 'league_tier' at their EXACT original positions.")
    print(f"✅ Data saved to: {PROCESSED_DATA_PATH}")
    
    return df_att

if __name__ == "__main__":
    df_eda = apply_tiers_with_exact_ordering()