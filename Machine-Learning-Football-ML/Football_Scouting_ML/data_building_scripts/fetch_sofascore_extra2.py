"""
fetch_sofascore_extra2.py
===========================
Fetches Sofascore player season stats for 6 leagues.

Already done (skipped):
  - Russia Premier League  (sofascore_russia_premier_league.csv)
  - Sweden Allsvenskan     (sofascore_sweden_allsvenskan.csv)

To fetch:
  - Serbia Prva Liga       (tournament_id=721)   ← NOT 52 (Turkey) or 210 (Superliga)
  - Romania Superliga      (tournament_id=152)
  - Croatia HNL            (tournament_id=170)
  - Norway Eliteserien     (tournament_id=20)    ← calendar years 2017-2024

IMPORTANT - Norway:
  ScraperFC has "Norway Eliteserien" hardcoded with ONLY old seasons (11/12 etc).
  Fix: register it under a slightly different name "Norway Eliteserien 2" so
  ScraperFC treats it as a new league (no hardcoded year restriction),
  then rename back in the output file.

Run from scrapFc folder:
  python fetch_sofascore_extra2.py
  Chrome opens automatically - do NOT close it.

Output (sofascore_output/):
  sofascore_serbia_prva_liga.csv
  sofascore_romania_superliga.csv
  sofascore_croatia_hnl.csv
  sofascore_norway_eliteserien.csv
  sofascore_extra2_log.csv
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

# Already completed — skip these
SKIP_DONE = True
DONE_FILES = {
    "Russia Premier League": OUTPUT_DIR / "sofascore_russia_premier_league.csv",
    "Sweden Allsvenskan":    OUTPUT_DIR / "sofascore_sweden_allsvenskan.csv",
    "Romania Superliga":     OUTPUT_DIR / "sofascore_romania_superliga.csv",
    "Croatia HNL":           OUTPUT_DIR / "sofascore_croatia_hnl.csv",
    "Norway Eliteserien":    OUTPUT_DIR / "sofascore_norway_eliteserien.csv",
}

# Norway is registered under "Norway Eliteserien 2" to bypass ScraperFC's
# hardcoded validator for "Norway Eliteserien" (which only knows old seasons).
# The output file and _league column will be renamed to "Norway Eliteserien".
# Norway uses the real name now that seasons are written to comps.yaml
NORWAY_SCRAPER_NAME = "Norway Eliteserien"
NORWAY_DISPLAY_NAME = "Norway Eliteserien"

LEAGUES = {
    # "Serbia SuperLiga" is the name ScraperFC knows internally.
    # Its internal tournament_id already points to the Serbian Superliga.
    # We only need to inject the correct season IDs (from unique-tournament/210).
    # The display name is set to "Serbia Superliga" in the output.
    "Serbia SuperLiga": {
        "tournament_id": 52,   # ScraperFC internal id (not the URL unique-tournament id)
        "seasons": {
            "17/18": 13440, "18/19": 17445, "19/20": 23779, "20/21": 28237,
            "21/22": 37148, "22/23": 42260, "23/24": 53417, "24/25": 61448,
        },
        "output_file": "sofascore_serbia_superliga.csv",
        "display_name": "Serbia Superliga",
    },
    "Romania Superliga": {
        "tournament_id": 152,
        "seasons": {
            "17/18": 13535, "18/19": 17678, "19/20": 24051, "20/21": 29376,
            "21/22": 37234, "22/23": 42576, "23/24": 52541, "24/25": 62837,
        },
        "output_file": "sofascore_romania_superliga.csv",
        "display_name": "Romania Superliga",
    },
    "Croatia HNL": {
        "tournament_id": 170,
        "seasons": {
            "17/18": 13517, "18/19": 17456, "19/20": 23778, "20/21": 29241,
            "21/22": 37053, "22/23": 42138, "23/24": 52147, "24/25": 61243,
        },
        "output_file": "sofascore_croatia_hnl.csv",
        "display_name": "Croatia HNL",
    },
    NORWAY_SCRAPER_NAME: {
        "tournament_id": 20,
        "seasons": {
            "2017": 12783, "2018": 15752, "2019": 19977, "2020": 26799,
            "2021": 35403, "2022": 40405, "2023": 47806, "2024": 57322,
        },
        "output_file": "sofascore_norway_eliteserien.csv",
        "display_name": NORWAY_DISPLAY_NAME,
    },
    # These are included in LEAGUES so patch_comps_yaml runs for them,
    # but they will be skipped in the scraping loop.
    "Russia Premier League": {
        "tournament_id": 203,
        "seasons": {},
        "output_file": "sofascore_russia_premier_league.csv",
        "display_name": "Russia Premier League",
    },
    "Sweden Allsvenskan": {
        "tournament_id": 41,
        "seasons": {},
        "output_file": "sofascore_sweden_allsvenskan.csv",
        "display_name": "Sweden Allsvenskan",
    },
}


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


def patch_comps_yaml(league_name: str, tournament_id: int, seasons: dict = None):
    """
    Patch comps.yaml with league name, tournament_id, and optionally seasons.
    Writing seasons directly into comps.yaml means ScraperFC reads them at
    init time — no injection needed, bypasses get_valid_seasons() entirely.
    """
    yaml_path = find_comps_yaml()
    with open(yaml_path, "r", encoding="utf-8") as f:
        comps = yaml.safe_load(f)
    sample = next(iter(comps.values()))
    entry  = {k: None for k in sample.keys()}
    entry["SOFASCORE"] = tournament_id
    if seasons:
        entry["seasons"] = seasons
    comps[league_name] = entry
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(comps, f, allow_unicode=True, sort_keys=True)
    seasons_note = f" + {len(seasons)} seasons" if seasons else ""
    print(f"  patched: '{league_name}' -> SOFASCORE={tournament_id}{seasons_note}")


def inject_seasons(scraper, league_name: str, seasons: dict) -> bool:
    for attr in ["comps", "_comps", "league_stats", "_league_stats"]:
        obj = getattr(scraper, attr, None)
        if obj and isinstance(obj, dict) and league_name in obj:
            if isinstance(obj[league_name], dict):
                obj[league_name]["seasons"] = seasons
                print(f"    injected into scraper.{attr}['{league_name}']")
                return True
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
                        print(f"    injected into scraper.{attr_name}"
                              f"['{league_name}'] (fallback)")
                        return True
        except Exception:
            continue
    print(f"    could not inject seasons (will try direct scrape anyway)")
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


def scrape_one_season(scraper, league_name, year_str, seasons):
    kwargs = dict(
        year=year_str,
        league=league_name,
        accumulation=ACCUMULATION,
        selected_positions=["Goalkeepers", "Defenders", "Midfielders", "Forwards"],
    )
    try:
        return scraper.scrape_player_league_stats(**kwargs), None
    except KeyError as e:
        print(f"\n      KeyError {e} — re-injecting...", end="", flush=True)
        inject_seasons(scraper, league_name, seasons)
        try:
            return scraper.scrape_player_league_stats(**kwargs), None
        except Exception as e2:
            return None, str(e2)[:120]
    except Exception as e:
        err = str(e)
        if "not a valid league" in err:
            print(f"\n      InvalidLeague — re-injecting...", end="", flush=True)
            inject_seasons(scraper, league_name, seasons)
            try:
                return scraper.scrape_player_league_stats(**kwargs), None
            except Exception as e2:
                return None, str(e2)[:120]
        return None, err[:120]


def main():
    print("=" * 65)
    print("  Sofascore - Serbia Superliga (tid=210)")
    print("  (Romania/Croatia/Norway/Russia/Sweden all skipped - already done)")
    print("=" * 65)

    print("\n[1] Patching comps.yaml (including season IDs)...")
    for name, cfg in LEAGUES.items():
        # Write seasons directly into comps.yaml so ScraperFC reads them at init
        # This bypasses the need for injection and get_valid_seasons()
        patch_comps_yaml(name, cfg["tournament_id"],
                         seasons=cfg["seasons"] if cfg["seasons"] else None)

    print("\n[2] Initialising ScraperFC (Chrome opens now)...")
    scraper = sfc.Sofascore()

    print("\n[3] Injecting season IDs...")
    for name, cfg in LEAGUES.items():
        if cfg["seasons"]:
            print(f"  {name}:")
            inject_seasons(scraper, name, cfg["seasons"])

    all_log    = []
    per_league = {name: [] for name in LEAGUES}

    print("\n[4] Scraping...")
    for league_name, cfg in LEAGUES.items():
        display = cfg["display_name"]

        # Skip already-done leagues
        if SKIP_DONE and league_name in DONE_FILES:
            done_path = DONE_FILES[league_name]
            if done_path.exists():
                _df = pd.read_csv(done_path, low_memory=False)
                per_league[league_name] = [_df]
                print(f"\n  {display}: SKIPPED "
                      f"({len(_df):,} rows from {done_path.name})")
                continue

        if not cfg["seasons"]:
            continue

        seasons = cfg["seasons"]
        print(f"\n{'─'*65}")
        print(f"  {display}  (tid={cfg['tournament_id']}, "
              f"{len(seasons)} seasons, scraping as '{league_name}')")

        for year_str in sorted(seasons.keys(), key=safe_year_end):
            sid = seasons[year_str]
            print(f"    {year_str} (sid={sid}) ... ", end="", flush=True)

            df, err = scrape_one_season(scraper, league_name, year_str, seasons)

            if err:
                print(f"ERROR: {err}")
                all_log.append({"league": display, "season": year_str,
                                "season_id": sid, "status": f"error: {err[:80]}",
                                "n_players": 0, "n_cols": 0})
            elif df is None or len(df) == 0:
                print("empty")
                all_log.append({"league": display, "season": year_str,
                                "season_id": sid, "status": "empty",
                                "n_players": 0, "n_cols": 0})
            else:
                # Use display name for _league column
                df["_league"]      = display
                df["_season_year"] = year_str
                per_league[league_name].append(df)
                all_log.append({"league": display, "season": year_str,
                                "season_id": sid, "status": "ok",
                                "n_players": len(df), "n_cols": len(df.columns)})
                print(f"{len(df)} players, {len(df.columns)} cols")
                time.sleep(DELAY)

            pd.DataFrame(all_log).to_csv(
                OUTPUT_DIR / "sofascore_extra2_log.csv", index=False)

    META     = ["_league", "_season_year", "player", "player id", "team", "team id"]
    META_SET = set(META)

    print(f"\n{'='*65}")
    print("  SAVING:")
    for league_name, dfs in per_league.items():
        cfg = LEAGUES[league_name]
        display = cfg["display_name"]
        if not dfs:
            print(f"  {display}: no data")
            continue
        ldf       = pd.concat(dfs, ignore_index=True)
        meta_here = [c for c in META if c in ldf.columns]
        stat_here = [c for c in ldf.columns if c not in META_SET]
        ldf       = ldf[meta_here + stat_here]
        out       = OUTPUT_DIR / cfg["output_file"]
        ldf.to_csv(out, index=False)
        uniq = ldf["player"].nunique() if "player" in ldf.columns else "?"
        print(f"  {display:<32} {len(ldf):>6,} rows | "
              f"{ldf['_season_year'].nunique()} seasons | {uniq} players")

    pd.DataFrame(all_log).to_csv(
        OUTPUT_DIR / "sofascore_extra2_log.csv", index=False)

    log_df = pd.DataFrame(all_log)
    print(f"\n  Result per league:")
    for league_name, cfg in LEAGUES.items():
        display = cfg["display_name"]
        if SKIP_DONE and league_name in DONE_FILES and DONE_FILES[league_name].exists():
            print(f"    {display:<32} SKIPPED")
            continue
        if not cfg["seasons"]:
            continue
        sub    = log_df[log_df["league"] == display]
        ok     = (sub["status"] == "ok").sum()
        total  = len(sub)
        failed = [r["season"] for _, r in sub.iterrows() if r["status"] != "ok"]
        print(f"    {display:<32} {ok}/{total} OK"
              + (f"  | failed: {failed}" if failed else ""))

    print(f"\n{'='*65}\nDone.")


if __name__ == "__main__":
    main()