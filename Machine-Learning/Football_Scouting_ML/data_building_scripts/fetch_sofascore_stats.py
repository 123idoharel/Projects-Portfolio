"""
fetch_sofascore_stats.py
========================
Fetches player season statistics from Sofascore via ScraperFC.

HOW IT WORKS (from actual source code):
  1. get_valid_seasons(league) → calls Sofascore API to get {year_str: season_id}
     year_str format is e.g. "2023/2024", "2022/2023" etc.
  2. scrape_player_league_stats(year, league, accumulation) → calls:
     https://api.sofascore.com/api/v1/unique-tournament/{league_id}/season/{season_id}/statistics
     Returns one row per player with 110 stat columns + player/team identity.
  3. A Chrome window opens (Botasaurus anti-bot bypass). Do not close it.

LEAGUES AVAILABLE (from your Step 1 output):
  ✅ England Premier League
  ✅ Spain La Liga
  ✅ Germany Bundesliga
  ✅ Italy Serie A
  ✅ France Ligue 1
  ✅ Turkiye Super Lig
  ✅ Netherlands Eredivisie
  ✅ Portugal Primeira Liga
  ✅ USA MLS
  ❌ Belgium — NOT supported by ScraperFC Sofascore

YEAR FORMAT: whatever get_valid_seasons() returns (e.g. "2023/2024")
  We filter to keep only seasons that overlap with 2017/18–2024/25.

OUTPUT:
  sofascore_output/sofascore_stats.csv   — all leagues, all available seasons
  sofascore_output/valid_seasons.csv     — log of which (league, year) pairs were found

COLUMNS (110 stat fields + metadata):
  player, player id, team, team id,
  _league, _season_year,
  accurateChippedPasses, accurateCrosses, accurateCrossesPercentage,
  accurateFinalThirdPasses, accurateLongBalls, accurateLongBallsPercentage,
  accurateOppositionHalfPasses, accurateOwnHalfPasses, accuratePasses,
  accuratePassesPercentage, aerialDuelsWon, aerialDuelsWonPercentage,
  aerialLost, appearances, assists, attemptPenaltyMiss, attemptPenaltyPost,
  attemptPenaltyTarget, ballRecovery, bigChancesCreated, bigChancesMissed,
  blockedShots, cleanSheet, clearances, countRating, crossesNotClaimed,
  directRedCards, dispossessed, dribbledPast, duelLost, errorLeadToGoal,
  errorLeadToShot, expectedAssists, expectedGoals, fouls, freeKickGoal,
  goalConversionPercentage, goalKicks, goals, goalsAssistsSum, goalsConceded,
  goalsConcededInsideTheBox, goalsConcededOutsideTheBox, goalsFromInsideTheBox,
  goalsFromOutsideTheBox, goalsPrevented, groundDuelsWon, groundDuelsWonPercentage,
  headedGoals, highClaims, hitWoodwork, inaccuratePasses, interceptions,
  keyPasses, leftFootGoals, matchesStarted, minutesPlayed, offsides,
  outfielderBlocks, ownGoals, passToAssist, penaltiesTaken, penaltyConceded,
  penaltyConversion, penaltyFaced, penaltyGoals, penaltySave, penaltyWon,
  possessionLost, possessionWonAttThird, punches, rating, redCards,
  rightFootGoals, runsOut, savedShotsFromInsideTheBox, savedShotsFromOutsideTheBox,
  saves, savesCaught, savesParried, scoringFrequency, setPieceConversion,
  shotFromSetPiece, shotsFromInsideTheBox, shotsFromOutsideTheBox, shotsOffTarget,
  shotsOnTarget, successfulDribbles, successfulDribblesPercentage, successfulRunsOut,
  tackles, tacklesWon, tacklesWonPercentage, totalAttemptAssist, totalChippedPasses,
  totalContest, totalCross, totalDuelsWon, totalDuelsWonPercentage, totalLongBalls,
  totalOppositionHalfPasses, totalOwnHalfPasses, totalPasses, totalRating,
  totalShots, totwAppearances, touches, wasFouled, yellowCards, yellowRedCards

  Columns with >10% missing across the full dataset are DROPPED automatically.

INSTALL:  pip install ScraperFC
RUN:      python fetch_sofascore_stats.py
RUNTIME:  ~2–4 hours first run (Chrome opens per call, Sofascore rate-limits)
"""

import time
import pandas as pd
from pathlib import Path
import ScraperFC as sfc

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("sofascore_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Your 9 available leagues (Belgium not supported)
LEAGUES = [
    "England Premier League",
    "Spain La Liga",
    "Germany Bundesliga",
    "Italy Serie A",
    "France Ligue 1",
    "Turkiye Super Lig",
    "Netherlands Eredivisie",
    "Portugal Primeira Liga",
    "USA MLS",
]

# We want seasons overlapping 2017/18 to 2024/25.
# get_valid_seasons() returns strings like "2023/2024".
# We keep any year string whose END year is between 2018 and 2025.
MIN_END_YEAR = 2018   # "2017/2018" ends in 2018 → keep
MAX_END_YEAR = 2025   # "2024/2025" ends in 2025 → keep

ACCUMULATION = "total"   # season totals. Change to "per90" if preferred.

DELAY_BETWEEN_CALLS = 3  # seconds between API calls — be polite to Sofascore

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def year_end(year_str: str) -> int:
    """
    Extract the ending calendar year from ANY Sofascore season string format:
      '17/18'     → 2018   (standard short format — what Sofascore actually returns)
      '24/25'     → 2025
      '93/94'     → 1994   (handles century boundary correctly)
      '1969/1970' → 1970   (old long format for some leagues)
      '2018'      → 2018   (MLS single-year format)
    """
    s = year_str.strip()
    if "/" in s:
        right = s.split("/")[-1].strip()
        if len(right) == 2:
            # Short format: '17/18' → last two digits → 2018
            n = int(right)
            return (2000 + n) if n < 50 else (1900 + n)
        else:
            # Long format: '1969/1970' → 1970
            return int(right)
    return int(s)  # MLS: '2018' → 2018


def drop_sparse_columns(df: pd.DataFrame, threshold: float = 0.10) -> pd.DataFrame:
    """Drop columns with >threshold fraction of missing values."""
    meta_cols = {"player", "player id", "team", "team id", "_league", "_season_year"}
    stat_cols = [c for c in df.columns if c not in meta_cols]
    n = len(df)
    to_drop = [c for c in stat_cols if df[c].isna().sum() / n > threshold]
    if to_drop:
        print(f"\n  Dropping {len(to_drop)} columns with >10% missing:")
        for c in to_drop:
            print(f"    - {c}  ({df[c].isna().mean()*100:.0f}% null)")
        df = df.drop(columns=to_drop)
    return df


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Sofascore Player Season Stats — ScraperFC")
    print("=" * 65)
    print(f"\n  Leagues:       {len(LEAGUES)}")
    print(f"  Seasons:       2017/18 – 2024/25")
    print(f"  Accumulation:  {ACCUMULATION}")
    print(f"  Output dir:    {OUTPUT_DIR.absolute()}")
    print("""
  A Chrome window will open automatically — do NOT close it.
  It closes itself between calls and re-opens for the next one.
  This is Botasaurus bypassing Sofascore's anti-bot protection.
  Runtime estimate: 2–4 hours for all 9 leagues × ~8 seasons.
""")

    scraper = sfc.Sofascore()

    all_dfs = []
    season_log = []   # record what was found

    for league in LEAGUES:
        print(f"\n{'─'*65}")
        print(f"  LEAGUE: {league}")
        print(f"{'─'*65}")

        # Step 1: get valid seasons for this league
        try:
            valid_seasons = scraper.get_valid_seasons(league)
            print(f"  Available seasons: {list(valid_seasons.keys())}")
        except Exception as e:
            print(f"  ERROR getting seasons: {e}")
            continue

        # Step 2: filter to target range
        target_seasons = {
            yr: sid for yr, sid in valid_seasons.items()
            if MIN_END_YEAR <= year_end(yr) <= MAX_END_YEAR
        }

        if not target_seasons:
            print(f"  No seasons in 2017/18–2024/25 range. Skipping.")
            continue

        print(f"  Seasons in target range: {list(target_seasons.keys())}")

        # Step 3: fetch each season
        for year_str in sorted(target_seasons.keys()):
            print(f"\n    {year_str} ... ", end="", flush=True)

            try:
                df = scraper.scrape_player_league_stats(
                    year=year_str,
                    league=league,
                    accumulation=ACCUMULATION,
                    selected_positions=["Goalkeepers", "Defenders",
                                        "Midfielders", "Forwards"]
                )

                if df is None or len(df) == 0:
                    print("empty — no data returned")
                    season_log.append({
                        "league": league, "season": year_str,
                        "status": "empty", "n_players": 0
                    })
                    continue

                # Add metadata columns
                df["_league"]       = league
                df["_season_year"]  = year_str

                all_dfs.append(df)
                season_log.append({
                    "league": league, "season": year_str,
                    "status": "ok", "n_players": len(df)
                })
                print(f"{len(df)} players, {len(df.columns)} columns")

                time.sleep(DELAY_BETWEEN_CALLS)

            except Exception as e:
                err_str = str(e)
                print(f"ERROR: {err_str[:80]}")
                season_log.append({
                    "league": league, "season": year_str,
                    "status": f"error: {err_str[:60]}", "n_players": 0
                })

    # ── Save season log ──────────────────────────────────────
    log_df = pd.DataFrame(season_log)
    log_path = OUTPUT_DIR / "valid_seasons.csv"
    log_df.to_csv(log_path, index=False)
    print(f"\n\nSeason log saved → {log_path}")
    print(log_df.to_string(index=False))

    if not all_dfs:
        print("\nNo data fetched at all. Check errors above.")
        return

    # ── Combine all leagues / seasons ────────────────────────
    combined = pd.concat(all_dfs, ignore_index=True)
    print(f"\n\nCombined: {len(combined):,} player-season rows, "
          f"{len(combined.columns)} columns before cleanup")

    # ── Drop columns with >10% missing ──────────────────────
    combined = drop_sparse_columns(combined)

    # ── Reorder: metadata first ──────────────────────────────
    meta_cols = ["_league", "_season_year", "player", "player id",
                 "team", "team id"]
    meta_cols = [c for c in meta_cols if c in combined.columns]
    stat_cols = [c for c in combined.columns if c not in meta_cols]
    combined  = combined[meta_cols + stat_cols]

    # ── Save ─────────────────────────────────────────────────
    out_path = OUTPUT_DIR / "sofascore_stats.csv"
    combined.to_csv(out_path, index=False)

    print(f"\n{'='*65}")
    print(f"  OUTPUT: {out_path}")
    print(f"  Rows:   {len(combined):,}  (player × season)")
    print(f"  Cols:   {len(combined.columns)}")
    print(f"\n  Columns:")
    for c in combined.columns:
        null_pct = combined[c].isna().mean() * 100
        print(f"    {c:<45} {null_pct:.0f}% null")
    print(f"{'='*65}")
    print("\nDone.")


if __name__ == "__main__":
    main()