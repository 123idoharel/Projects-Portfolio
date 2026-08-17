"""
explore_scraperfc.py
====================
Run this BEFORE building the full pipeline.
It tells you exactly:
  1. All valid Sofascore league names
  2. All valid years per league
  3. Exact column names returned
  4. Row count per call
  5. Sample data rows

Run with: python explore_scraperfc.py
"""

import ScraperFC as sfc
import pandas as pd

scraper = sfc.Sofascore()

# ─────────────────────────────────────────────
# STEP 1: Get all valid Sofascore league names
# ─────────────────────────────────────────────
print("=" * 60)
print("STEP 1: Valid Sofascore league names")
print("=" * 60)
try:
    # Passing a fake league name triggers the error message
    # that lists all valid leagues
    scraper.scrape_player_league_stats(year="2024", league="SHOW_ME_LEAGUES")
except Exception as e:
    print(e)

input("\nPress Enter to continue to Step 2...")

# ─────────────────────────────────────────────
# STEP 2: Get valid years for specific leagues
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 2: Valid years per league")
print("=" * 60)

# Paste the league names you saw in Step 1 output here
# These are guesses — the error in Step 1 gives you the real names
LEAGUES_TO_CHECK = [
    "EPL",
    "La Liga",
    "Bundesliga",
    "Serie A",
    "Ligue 1",
    "Turkish Super Lig",
    "Eredivisie",
    "Jupiler Pro League",
    "Primeira Liga",
    "MLS",
]

for league in LEAGUES_TO_CHECK:
    try:
        seasons = scraper.get_season_ids(league)
        print(f"\n  {league}:")
        for year_name, year_id in seasons.items():
            print(f"    year={year_name!r}  id={year_id}")
    except Exception as e:
        print(f"\n  {league}: NOT AVAILABLE — {e}")

input("\nPress Enter to continue to Step 3...")

# ─────────────────────────────────────────────
# STEP 3: Fetch ONE league/season, inspect output
# ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("STEP 3: Sample fetch — EPL 2023/24")
print("(A Chrome window will open — do not close it)")
print("=" * 60)

try:
    df = scraper.scrape_player_league_stats(
        year="2024",           # 2024 = season ending in 2024 = 2023/24
        league="EPL",          # adjust if Step 1 showed a different name
        accumulation="total",  # season totals
        selected_positions=["Goalkeepers", "Defenders", "Midfielders", "Forwards"]
    )

    print(f"\nShape:   {df.shape}  ({df.shape[0]} players, {df.shape[1]} columns)")
    print(f"\nColumns ({len(df.columns)}):")
    for col in df.columns:
        sample_val = df[col].dropna().iloc[0] if df[col].notna().any() else "all NaN"
        null_pct   = df[col].isna().mean() * 100
        print(f"  {col:<35} sample={sample_val!r:<20} nulls={null_pct:.0f}%")

    print("\nFirst 5 rows:")
    print(df.head(5).to_string())

    df.to_csv("sample_output.csv", index=False)
    print("\nSaved sample to: sample_output.csv")

except Exception as e:
    print(f"Failed: {e}")

print("\nDone. Send me the output and I will write the full script.")