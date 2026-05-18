"""
fetch_sofascore_extra_leagues.py
=================================
Fetches Sofascore player season stats for 4 leagues NOT included in
fetch_sofascore_all.py:
  - Belgium Pro League        (tournament_id=38)
  - Brazil Série A            (tournament_id=325)
  - Austria Bundesliga        (tournament_id=45)
  - Czech First League        (tournament_id=172)

Season range: 2017/18 – 2024/25
  Note: Brazil uses calendar years (2017–2024) since its league runs Jan–Dec.

Approach (same as fetch_sofascore_israel.py — confirmed working):
  1. Patch comps.yaml with league name → tournament_id
  2. Inject hardcoded season IDs into ScraperFC's internal dict
     (bypasses get_valid_seasons() which gets blocked without Chrome)
  3. Scrape per season, per league
  4. Save one CSV per league + combined + null/log stats

Output files (sofascore_output/):
  sofascore_extra_leagues.csv           all 4 leagues combined
  sofascore_belgium_pro_league.csv
  sofascore_brazil_serie_a.csv
  sofascore_austria_bundesliga.csv
  sofascore_czech_first_league.csv
  sofascore_extra_leagues_log.csv       per (league, season) status
  sofascore_extra_null_by_column.csv
  sofascore_extra_null_by_season.csv

INSTALL: pip install ScraperFC
RUN:     python fetch_sofascore_extra_leagues.py
         Chrome opens automatically — do NOT close it.
PARALLEL: Safe to run in a separate VS Code terminal alongside other scripts.
"""

import time
import yaml
import importlib.resources
import pandas as pd
from pathlib import Path
import ScraperFC as sfc

OUTPUT_DIR   = Path("sofascore_output")
OUTPUT_DIR.mkdir(exist_ok=True)
ACCUMULATION = "total"
DELAY        = 3

# ── League definitions with hardcoded season IDs ───────────────────────────────
# Season IDs come from the Sofascore internal API pattern.
# Hardcoding bypasses get_valid_seasons() which gets blocked without a session.
# If a season ID is wrong, the scrape will return empty and log it — no crash.

LEAGUES = {
    "Brazil Serie A": {
        "tournament_id": 325,
        "seasons": {
            "2017": 16562,
            "2018": 18418,
            "2019": 23883,
            "20/21": 30571,   # ✅ תיקון חשוב
            "2021": 36985,
            "2022": 42438,
            "2023": 48982,
            "2024": 58766,
            "2025": 65761,   # ⚠️ זמני (ראה הסבר למטה)
        },
        "output_file": "final_sofascore_brazil_serie_a.csv",
    }
}

# ── Helpers (identical to fetch_sofascore_israel.py) ───────────────────────────

def find_comps_yaml() -> Path:
    try:
        pkg_path = Path(importlib.resources.files("ScraperFC")._path)
    except AttributeError:
        import ScraperFC
        pkg_path = Path(ScraperFC.__file__).parent
    for candidate in [pkg_path / "comps.yaml", pkg_path.parent / "comps.yaml"]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"comps.yaml not found near {pkg_path}")


def patch_comps_yaml(league_name: str, tournament_id: int):
    yaml_path = find_comps_yaml()
    with open(yaml_path, "r", encoding="utf-8") as f:
        comps = yaml.safe_load(f)
    sample = next(iter(comps.values()))
    entry  = {k: None for k in sample.keys()}
    entry["SOFASCORE"] = tournament_id
    comps[league_name] = entry
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(comps, f, allow_unicode=True, sort_keys=True)
    print(f"  patched: '{league_name}' → SOFASCORE={tournament_id}")


def inject_seasons(scraper, league_name: str, seasons: dict) -> bool:
    # First try known attribute names
    for attr in ["comps", "_comps", "league_stats", "_league_stats"]:
        obj = getattr(scraper, attr, None)
        if obj and isinstance(obj, dict) and league_name in obj:
            if isinstance(obj[league_name], dict):
                obj[league_name]["seasons"] = seasons
                print(f"    injected {len(seasons)} seasons into scraper.{attr}['{league_name}']")
                return True

    # Fallback: walk ALL attributes looking for the leagues dict
    # (identified by containing "Argentina" as a key — same as comps.yaml)
    for attr_name in dir(scraper):
        if attr_name.startswith("_"):
            continue
        try:
            val = getattr(scraper, attr_name)
            if isinstance(val, dict) and len(val) > 5:
                for league_key in list(val.keys()):
                    if "Argentina" in str(league_key):
                        if league_name not in val:
                            val[league_name] = {}
                        if isinstance(val[league_name], dict):
                            val[league_name]["seasons"] = seasons
                        print(f"    injected {len(seasons)} seasons into scraper.{attr_name}['{league_name}'] (fallback)")
                        return True
        except Exception:
            continue

    print(f"    could not inject seasons (will try anyway)")
    return False


def safe_year_end(yr: str) -> int:
    try:
        s = yr.strip()
        if "/" in s:
            right = s.split("/")[-1].strip()
            n = int(right)
            return (2000 + n) if n < 50 else (1900 + n)
        return int(s)
    except Exception:
        return 0


def null_stats(df: pd.DataFrame, meta_set: set) -> pd.DataFrame:
    rows = []
    for col in [c for c in df.columns if c not in meta_set]:
        total  = len(df)
        n_null = int(df[col].isna().sum())
        rows.append({
            "column":   col,
            "null_pct": round(n_null / total * 100, 1) if total else None,
            "n_null":   n_null,
            "n_valid":  total - n_null,
            "total":    total,
        })
    return (pd.DataFrame(rows)
            .sort_values("null_pct", ascending=False)
            .reset_index(drop=True))


def null_by_season(df: pd.DataFrame, meta_set: set) -> pd.DataFrame:
    stat_cols = [c for c in df.columns if c not in meta_set]
    rows = []
    for season in sorted(df["_season_year"].unique(), key=safe_year_end):
        sub   = df[df["_season_year"] == season]
        total = len(sub)
        for col in stat_cols:
            n_null = int(sub[col].isna().sum())
            rows.append({
                "league":    sub["_league"].iloc[0] if "_league" in sub.columns else "",
                "season":    season,
                "column":    col,
                "null_pct":  round(n_null / total * 100, 1) if total else None,
                "n_null":    n_null,
                "n_valid":   total - n_null,
                "n_players": total,
            })
    return pd.DataFrame(rows)


def scrape_one_season(scraper, league_name, year_str, seasons):
    """Scrape one season. On KeyError, re-injects seasons and retries once."""
    kwargs = dict(
        year=year_str,
        league=league_name,
        accumulation=ACCUMULATION,
        selected_positions=["Goalkeepers", "Defenders", "Midfielders", "Forwards"],
    )
    try:
        return scraper.scrape_player_league_stats(**kwargs), None
    except KeyError as e:
        print(f"\n      KeyError {e} — re-injecting and retrying...", end="", flush=True)
        inject_seasons(scraper, league_name, seasons)  # now uses fallback walk
        try:
            return scraper.scrape_player_league_stats(**kwargs), None
        except Exception as e2:
            return None, str(e2)[:120]
    except Exception as e:
        # Also catch InvalidLeagueException (raised as plain Exception by ScraperFC)
        err = str(e)
        if "not a valid league" in err:
            # Re-inject and retry — the validation check reads from the same dict
            print(f"\n      InvalidLeague — re-injecting and retrying...", end="", flush=True)
            inject_seasons(scraper, league_name, seasons)
            try:
                return scraper.scrape_player_league_stats(**kwargs), None
            except Exception as e2:
                return None, str(e2)[:120]
        return None, err[:120]


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  Sofascore — Belgium / Brazil / Austria / Czech Republic")
    print("  Seasons 2017/18 – 2024/25")
    print("=" * 65)

    print("\n[1] Patching comps.yaml...")
    for name, cfg in LEAGUES.items():
        patch_comps_yaml(name, cfg["tournament_id"])

    print("\n[2] Initialising ScraperFC (Chrome opens now)...")
    scraper = sfc.Sofascore()

    print("\n[3] Injecting season IDs...")
    for name, cfg in LEAGUES.items():
        print(f"  {name}:")
        inject_seasons(scraper, name, cfg["seasons"])

    all_log    = []
    per_league = {name: [] for name in LEAGUES}

    print("\n[4] Scraping...")
    for league_name, cfg in LEAGUES.items():
        seasons = cfg["seasons"]
        print(f"\n{'─'*65}")
        print(f"  {league_name}  (tid={cfg['tournament_id']}, {len(seasons)} seasons)")

        for year_str in sorted(seasons.keys(), key=safe_year_end):
            sid = seasons[year_str]
            print(f"    {year_str} (sid={sid}) ... ", end="", flush=True)

            df, err = scrape_one_season(scraper, league_name, year_str, seasons)

            if err:
                print(f"ERROR: {err}")
                all_log.append({"league": league_name, "season": year_str,
                                "season_id": sid, "status": f"error: {err[:80]}",
                                "n_players": 0, "n_cols": 0})
            elif df is None or len(df) == 0:
                print("empty")
                all_log.append({"league": league_name, "season": year_str,
                                "season_id": sid, "status": "empty",
                                "n_players": 0, "n_cols": 0})
            else:
                df["_league"]      = league_name
                df["_season_year"] = year_str
                per_league[league_name].append(df)
                all_log.append({"league": league_name, "season": year_str,
                                "season_id": sid, "status": "ok",
                                "n_players": len(df), "n_cols": len(df.columns)})
                print(f"{len(df)} players, {len(df.columns)} cols")
                time.sleep(DELAY)

            # Save log after every season (crash safety)
            pd.DataFrame(all_log).to_csv(
                OUTPUT_DIR / "sofascore_extra_leagues_log.csv", index=False)

    # ── Save outputs ───────────────────────────────────────────────────────────
    META     = ["_league", "_season_year", "player", "player id", "team", "team id"]
    META_SET = set(META)

    all_frames = []
    print(f"\n{'='*65}")
    print("  SAVING:")

    for league_name, dfs in per_league.items():
        if not dfs:
            print(f"  {league_name}: no data")
            continue
        ldf      = pd.concat(dfs, ignore_index=True)
        meta_here = [c for c in META if c in ldf.columns]
        stat_here = [c for c in ldf.columns if c not in META_SET]
        ldf       = ldf[meta_here + stat_here]
        out       = OUTPUT_DIR / LEAGUES[league_name]["output_file"]
        ldf.to_csv(out, index=False)
        all_frames.append(ldf)
        uniq = ldf["player"].nunique() if "player" in ldf.columns else "?"
        print(f"  {league_name:<28} {len(ldf):>6,} rows | "
              f"{ldf['_season_year'].nunique()} seasons | {uniq} unique players")
        print(f"    seasons: {sorted(ldf['_season_year'].unique(), key=safe_year_end)}")

    if not all_frames:
        print("\n  No data to combine.")
        return

    combined = pd.concat(all_frames, ignore_index=True)
    meta_c   = [c for c in META if c in combined.columns]
    stat_c   = [c for c in combined.columns if c not in META_SET]
    combined = combined[meta_c + stat_c]
    combined.to_csv(OUTPUT_DIR / "sofascore_extra_leagues.csv", index=False)
    print(f"\n  Combined: {len(combined):,} rows across {combined['_league'].nunique()} leagues")

    # Null stats
    null_stats(combined, META_SET).to_csv(
        OUTPUT_DIR / "sofascore_extra_null_by_column.csv", index=False)
    null_by_season(combined, META_SET).to_csv(
        OUTPUT_DIR / "sofascore_extra_null_by_season.csv", index=False)

    # ── Final summary ──────────────────────────────────────────────────────────
    log_df = pd.DataFrame(all_log)
    log_df.to_csv(OUTPUT_DIR / "sofascore_extra_leagues_log.csv", index=False)

    print(f"\n{'─'*65}")
    print("  Result per league:")
    for league_name in LEAGUES:
        sub    = log_df[log_df["league"] == league_name]
        ok     = (sub["status"] == "ok").sum()
        total  = len(sub)
        failed = [r["season"] for _, r in sub.iterrows() if r["status"] != "ok"]
        print(f"    {league_name:<28} {ok}/{total} OK"
              + (f"  | failed: {failed}" if failed else ""))

    print(f"\n  Players per season (combined view):")
    if "player" in combined.columns:
        pps = (combined.groupby(["_league","_season_year"])["player"]
               .count().reset_index()
               .rename(columns={"player":"n_players"}))
        print(pps.sort_values(["_league","_season_year"]).to_string(index=False))

    print(f"\n{'='*65}\nDone.")


if __name__ == "__main__":
    main()