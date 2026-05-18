"""
fetch_sofascore_all.py
======================
Fetches player season stats from Sofascore for ALL supported leagues
(except the 4 excluded ones below). NO column dropping.

EXCLUDED (as requested):
  - Argentina Copa de la Liga Profesional
  - FIFA Womens World Cup
  - USA USL League 1
  - USA USL Leauge 2

SEASON RANGE:
  - Domestic leagues: 2017/18 - 2024/25
  - Tournaments (UCL, World Cup etc.): ALL available seasons

OUTPUT:
  sofascore_output/sofascore_all.csv       main file
  sofascore_output/sofascore_all_log.csv   per (league,season) status

INSTALL:  pip install ScraperFC
RUN:      python fetch_sofascore_all.py
RUNTIME:  ~4-6 hours. Chrome opens automatically, do NOT close it.
"""

import time
import pandas as pd
from pathlib import Path
import ScraperFC as sfc

OUTPUT_DIR = Path("sofascore_output")
OUTPUT_DIR.mkdir(exist_ok=True)

ALL_LEAGUES = [
    # Top-9 domestic
    "England Premier League",
    "Spain La Liga",
    "Germany Bundesliga",
    "Italy Serie A",
    "France Ligue 1",
    "Turkiye Super Lig",
    "Netherlands Eredivisie",
    "Portugal Primeira Liga",
    "USA MLS",
    # Extra domestic
    "Argentina Liga Profesional",
    "Bulgaria Parva Liga",
    "England EFL Championship",
    "France Ligue 2",
    "Germany 2.Bundesliga",
    "Italy Serie B",
    "Mexico Liga MX Apertura",
    "Mexico Liga MX Clausura",
    "Peru Liga 1",
    "Portugal Liga Portugal 2",
    "Saudi Arabia Pro League",
    "Spain La Liga 2",
    "Ukraine Premier League",
    "USA USL championship",
    # Tournaments (all seasons)
    "CONCACAF Gold Cup",
    "CONMEBOL Copa Libertadores",
    "FIFA World Cup",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Conference League",
    "UEFA European Championship",
]

TOURNAMENT_LEAGUES = {
    "CONCACAF Gold Cup",
    "CONMEBOL Copa Libertadores",
    "FIFA World Cup",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Conference League",
    "UEFA European Championship",
}

MIN_END_YEAR = 2018
MAX_END_YEAR = 2025
ACCUMULATION = "total"
DELAY        = 3


def year_end(year_str: str) -> int:
    s = year_str.strip()
    if "/" in s:
        right = s.split("/")[-1].strip()
        if len(right) == 2:
            n = int(right)
            return (2000 + n) if n < 50 else (1900 + n)
        return int(right)
    return int(s)


def safe_year_end(yr: str) -> int:
    try:
        return year_end(yr)
    except Exception:
        return 0


def main():
    print("=" * 65)
    print("  Sofascore — ALL leagues, ALL columns, no dropping")
    print("=" * 65)
    print(f"  Leagues: {len(ALL_LEAGUES)} | Seasons: 2017/18-2024/25")
    print("  Chrome opens automatically. Do NOT close it.\n")

    scraper = sfc.Sofascore()
    all_dfs = []
    log     = []

    for league in ALL_LEAGUES:
        print(f"\n{'─'*65}")
        print(f"  LEAGUE: {league}")

        try:
            valid_seasons = scraper.get_valid_seasons(league)
            print(f"  Available: {list(valid_seasons.keys())}")
        except Exception as e:
            print(f"  ERROR getting seasons: {e}")
            log.append({"league": league, "season": "N/A",
                        "status": f"error_seasons: {str(e)[:80]}",
                        "n_players": 0, "n_cols": 0})
            continue

        target = {yr: sid for yr, sid in valid_seasons.items()
                  if MIN_END_YEAR <= year_end(yr) <= MAX_END_YEAR}
        if not target:
            print(f"  No seasons in 2017/18-2024/25. Skipping.")
            log.append({"league": league, "season": "N/A",
                        "status": "no_seasons_in_range",
                        "n_players": 0, "n_cols": 0})
            continue
        print(f"  Target: {sorted(target.keys(), key=safe_year_end)}")

        for year_str in sorted(target.keys(), key=safe_year_end):
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
                    print("empty")
                    log.append({"league": league, "season": year_str,
                                "status": "empty", "n_players": 0,
                                "n_cols": 0})
                    continue

                df["_league"]      = league
                df["_season_year"] = year_str
                all_dfs.append(df)
                log.append({"league": league, "season": year_str,
                            "status": "ok", "n_players": len(df),
                            "n_cols": len(df.columns)})
                print(f"{len(df)} players, {len(df.columns)} cols")
                time.sleep(DELAY)

            except Exception as e:
                err = str(e)
                print(f"ERROR: {err[:100]}")
                log.append({"league": league, "season": year_str,
                            "status": f"error: {err[:80]}",
                            "n_players": 0, "n_cols": 0})

        # Save log after every league (so you don't lose progress on crash)
        pd.DataFrame(log).to_csv(
            OUTPUT_DIR / "sofascore_all_log.csv", index=False)

    if not all_dfs:
        print("\nNo data fetched.")
        return

    # Combine
    combined = pd.concat(all_dfs, ignore_index=True)

    # Metadata columns first
    meta = ["_league", "_season_year", "player", "player id", "team", "team id"]
    meta = [c for c in meta if c in combined.columns]
    stat = [c for c in combined.columns if c not in meta]
    combined = combined[meta + stat]

    # Quick null summary for key columns
    print(f"\n  Null % across full dataset:")
    for c in ["expectedGoals", "expectedAssists", "ballRecovery",
              "rating", "goals", "minutesPlayed"]:
        if c in combined.columns:
            pct = combined[c].isna().mean() * 100
            n   = combined[c].notna().sum()
            print(f"    {c:<30} {pct:.0f}% null  ({n:,} non-null values)")

    # xG/xA/ballRecovery per season (top-9 only)
    top9_mask = combined["_league"].isin([
        "England Premier League", "Spain La Liga", "Germany Bundesliga",
        "Italy Serie A", "France Ligue 1", "Turkiye Super Lig",
        "Netherlands Eredivisie", "Portugal Primeira Liga", "USA MLS"
    ])
    top9 = combined[top9_mask]
    print(f"\n  xG / xA / ballRecovery null % by season (top-9 leagues):")
    print(f"  {'Season':<12} {'xG':>22} {'xA':>22} {'ballRecovery':>14}")
    print(f"  {'─'*74}")
    for yr in sorted(top9["_season_year"].unique(), key=safe_year_end):
        sub = top9[top9["_season_year"] == yr]
        def np(col):
            if col not in combined.columns: return "N/A"
            p = sub[col].isna().mean() * 100
            n = sub[col].notna().sum()
            return f"{p:.0f}% ({n} vals)"
        print(f"  {yr:<12} {np('expectedGoals'):>22} "
              f"{np('expectedAssists'):>22} {np('ballRecovery'):>14}")

    # ── Per-column null % log: top-9 vs rest ─────────────────
    TOP9 = {
        "England Premier League", "Spain La Liga", "Germany Bundesliga",
        "Italy Serie A", "France Ligue 1", "Turkiye Super Lig",
        "Netherlands Eredivisie", "Portugal Primeira Liga", "USA MLS"
    }
    top9_mask = combined["_league"].isin(TOP9)
    df_top9   = combined[top9_mask]
    df_rest   = combined[~top9_mask]

    meta_cols = {"_league", "_season_year", "player", "player id",
                 "team", "team id"}
    stat_cols = [c for c in combined.columns if c not in meta_cols]

    null_rows = []
    for col in stat_cols:
        row = {"column": col}
        for label, df_sub in [("top9", df_top9), ("rest", df_rest)]:
            if len(df_sub) == 0:
                row[f"null_pct_{label}"]   = None
                row[f"non_null_n_{label}"] = 0
            else:
                null_pct = df_sub[col].isna().mean() * 100
                non_null = int(df_sub[col].notna().sum())
                row[f"null_pct_{label}"]   = round(null_pct, 1)
                row[f"non_null_n_{label}"] = non_null
        null_rows.append(row)

    null_df = pd.DataFrame(null_rows).sort_values("null_pct_top9")
    null_log_path = OUTPUT_DIR / "sofascore_column_null_stats.csv"
    null_df.to_csv(null_log_path, index=False)

    print(f"\n  Column null % — top-9 vs rest:")
    print(f"  {'Column':<40} {'top9 null%':>12} {'top9 n':>10} "
          f"{'rest null%':>12} {'rest n':>10}")
    print(f"  {'-'*88}")
    for _, r in null_df.iterrows():
        print(f"  {r['column']:<40} "
              f"{str(r['null_pct_top9'])+'%':>12} "
              f"{int(r['non_null_n_top9']):>10,} "
              f"{str(r['null_pct_rest'])+'%':>12} "
              f"{int(r['non_null_n_rest']):>10,}")

    # ── Save ──────────────────────────────────────────────────
    out = OUTPUT_DIR / "sofascore_all.csv"
    combined.to_csv(out, index=False)
    pd.DataFrame(log).to_csv(OUTPUT_DIR / "sofascore_all_log.csv", index=False)

    print(f"\n{'='*65}")
    print(f"  OUTPUT:   {out}")
    print(f"  NULL LOG: {null_log_path}")
    print(f"  Rows:     {len(combined):,}")
    print(f"  Cols:     {len(combined.columns)}")
    print(f"\n  Rows per league:")
    summary = (combined.groupby("_league")
               .agg(rows=("player","count"),
                    seasons=("_season_year","nunique"))
               .sort_values("rows", ascending=False))
    print(summary.to_string())
    print(f"{'='*65}\nDone.")


if __name__ == "__main__":
    main()