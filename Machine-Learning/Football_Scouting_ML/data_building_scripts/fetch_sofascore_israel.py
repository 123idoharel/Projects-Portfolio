"""
fetch_sofascore_israel.py
=========================
Fetches Israeli Premier League player season stats using ScraperFC.
Same library, same output format as fetch_sofascore_all.py.

THE FIX:
  get_valid_seasons() makes a plain HTTP request to Sofascore (no Chrome),
  which gets blocked. We bypass it entirely by:
    1. Hardcoding the season IDs directly into comps.yaml
    2. Calling scrape_player_league_stats() with the year string as-is

INSTALL: pip install ScraperFC
RUN:     python fetch_sofascore_israel.py
         Chrome opens automatically — do NOT close it.

OUTPUT (sofascore_output/):
  sofascore_israel_full.csv          all seasons combined (reference)
  sofascore_israel_2023_2025.csv     seasons 23/24 + 24/25  ← rich data
  sofascore_israel_pre2021.csv       seasons 17/18–20/21    ← sparse data
  sofascore_israel_log.csv           per-season scrape status
  sofascore_israel_null_by_column.csv
  sofascore_israel_null_by_season.csv
  sofascore_israel_column_comparison.csv  vs sofascore_top9_final.csv
"""

import time
import yaml
import importlib.resources
import pandas as pd
from pathlib import Path
import ScraperFC as sfc

# ── CONFIG ────────────────────────────────────────────────────────────────────
LEAGUE_NAME   = "Israeli Premier League"
TOURNAMENT_ID = 266

SEASONS = {
    "17/18": 17008,
    "18/19": 18596,
    "19/20": 23776,
    "20/21": 29415,
    "21/22": 37236,
    "22/23": 42273,
    "23/24": 52760,
    "24/25": 63814,
}

# Split definition
SEASONS_RICH   = {"23/24", "24/25"}          # full data
SEASONS_SPARSE = {"17/18", "18/19", "19/20", "20/21", "21/22", "22/23"}  # sparse

# Path to your top9 reference file for column comparison
# Update this if the file lives somewhere else
TOP9_CSV = Path("sofascore_output") / "sofascore_top9_final.csv"

ACCUMULATION = "total"
DELAY        = 3
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = Path("sofascore_output")
OUTPUT_DIR.mkdir(exist_ok=True)


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


def patch_comps_yaml():
    yaml_path = find_comps_yaml()
    with open(yaml_path, "r", encoding="utf-8") as f:
        comps = yaml.safe_load(f)
    sample_entry = next(iter(comps.values()))
    new_entry = {k: None for k in sample_entry.keys()}
    new_entry["SOFASCORE"] = TOURNAMENT_ID
    comps[LEAGUE_NAME] = new_entry
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(comps, f, allow_unicode=True, sort_keys=True)
    print(f"  comps.yaml patched: '{LEAGUE_NAME}' -> SOFASCORE={TOURNAMENT_ID}")
    print(f"  File: {yaml_path}")


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
    """Return per-column null stats for stat columns only."""
    rows = []
    for col in [c for c in df.columns if c not in meta_set]:
        total   = len(df)
        n_null  = int(df[col].isna().sum())
        rows.append({
            "column":   col,
            "null_pct": round(n_null / total * 100, 1) if total > 0 else None,
            "n_null":   n_null,
            "n_valid":  total - n_null,
            "total":    total,
        })
    return (pd.DataFrame(rows)
            .sort_values("null_pct", ascending=False)
            .reset_index(drop=True))


def season_null_stats(df: pd.DataFrame, meta_set: set) -> pd.DataFrame:
    """Return per-season × per-column null stats."""
    stat_cols = [c for c in df.columns if c not in meta_set]
    rows = []
    for season in sorted(df["_season_year"].unique(), key=safe_year_end):
        sub   = df[df["_season_year"] == season]
        total = len(sub)
        for col in stat_cols:
            n_null = int(sub[col].isna().sum())
            rows.append({
                "season":    season,
                "column":    col,
                "null_pct":  round(n_null / total * 100, 1) if total > 0 else None,
                "n_null":    n_null,
                "n_valid":   total - n_null,
                "n_players": total,
            })
    return pd.DataFrame(rows)


def compare_columns(israel_df: pd.DataFrame, top9_path: Path,
                    meta_set: set) -> pd.DataFrame:
    """
    Compare stat columns between the Israeli dataset (rich seasons only)
    and the top9 reference file. Returns a tidy comparison DataFrame.
    """
    if not top9_path.exists():
        print(f"\n  WARNING: top9 file not found at {top9_path}")
        print(f"  Place sofascore_top9_final.csv in sofascore_output/ and re-run.")
        return pd.DataFrame()

    top9_cols   = set(pd.read_csv(top9_path, nrows=0).columns)
    israel_cols = set(israel_df.columns)

    # Remove meta columns from both sides
    top9_stat   = top9_cols   - meta_set
    israel_stat = israel_cols - meta_set

    in_both        = sorted(top9_stat & israel_stat)
    only_in_top9   = sorted(top9_stat - israel_stat)
    only_in_israel = sorted(israel_stat - top9_stat)

    rows = (
        [{"column": c, "status": "in_both"}        for c in in_both]
      + [{"column": c, "status": "only_in_top9"}   for c in only_in_top9]
      + [{"column": c, "status": "only_in_israel"} for c in only_in_israel]
    )
    comp_df = pd.DataFrame(rows).sort_values(["status", "column"]).reset_index(drop=True)

    # Print summary
    print(f"\n  Column comparison (Israel rich seasons vs top9 file):")
    print(f"    Shared columns      : {len(in_both)}")
    print(f"    Only in top9        : {len(only_in_top9)}")
    print(f"    Only in Israel      : {len(only_in_israel)}")

    if only_in_top9:
        print(f"\n  Columns in top9 but MISSING from Israel (you lose these):")
        for c in only_in_top9:
            print(f"    - {c}")

    if only_in_israel:
        print(f"\n  Columns in Israel but NOT in top9 (bonus columns):")
        for c in only_in_israel:
            print(f"    + {c}")

    return comp_df


def main():
    print("=" * 60)
    print("  Sofascore -- Israeli Premier League")
    print("  Using ScraperFC (same as fetch_sofascore_all.py)")
    print("=" * 60)

    print("\nStep 1: Patching comps.yaml ...")
    patch_comps_yaml()

    print("\nStep 2: Initialising ScraperFC (Chrome opens now) ...")
    scraper = sfc.Sofascore()

    print("\nStep 3: Injecting season IDs (bypassing blocked API call) ...")
    injected = False
    for attr in ["comps", "_comps", "league_stats", "_league_stats"]:
        obj = getattr(scraper, attr, None)
        if obj is not None and isinstance(obj, dict):
            if LEAGUE_NAME in obj and isinstance(obj[LEAGUE_NAME], dict):
                obj[LEAGUE_NAME]["seasons"] = SEASONS
                print(f"  Injected seasons into scraper.{attr}['{LEAGUE_NAME}']")
                injected = True
                break
    if not injected:
        print("  Could not find internal seasons dict — trying direct scrape anyway.")

    all_dfs = []
    log     = []

    print("\nStep 4: Scraping player stats per season ...")
    for year_str, season_id in sorted(SEASONS.items(), key=lambda x: safe_year_end(x[0])):
        print(f"\n  {year_str} (season_id={season_id}) ... ", end="", flush=True)
        try:
            df = scraper.scrape_player_league_stats(
                year=year_str,
                league=LEAGUE_NAME,
                accumulation=ACCUMULATION,
                selected_positions=["Goalkeepers", "Defenders",
                                    "Midfielders", "Forwards"]
            )
        except KeyError as e:
            print(f"\n    KeyError {e} — trying mid-run injection ... ", end="")
            try:
                for attr_name in dir(scraper):
                    if attr_name.startswith("_"):
                        continue
                    try:
                        val = getattr(scraper, attr_name)
                        if isinstance(val, dict) and len(val) > 5:
                            for league_key in list(val.keys()):
                                if "Argentina" in str(league_key):
                                    if LEAGUE_NAME not in val:
                                        val[LEAGUE_NAME] = {}
                                    if isinstance(val[LEAGUE_NAME], dict):
                                        val[LEAGUE_NAME]["seasons"] = SEASONS
                                    break
                    except Exception:
                        continue
                df = scraper.scrape_player_league_stats(
                    year=year_str, league=LEAGUE_NAME,
                    accumulation=ACCUMULATION,
                    selected_positions=["Goalkeepers", "Defenders",
                                        "Midfielders", "Forwards"]
                )
            except Exception as e2:
                print(f"ERROR: {str(e2)[:120]}")
                log.append({"season": year_str, "season_id": season_id,
                            "status": f"error: {str(e2)[:100]}",
                            "n_players": 0, "n_cols": 0})
                pd.DataFrame(log).to_csv(OUTPUT_DIR / "sofascore_israel_log.csv", index=False)
                continue
        except Exception as e:
            print(f"ERROR: {str(e)[:120]}")
            log.append({"season": year_str, "season_id": season_id,
                        "status": f"error: {str(e)[:100]}",
                        "n_players": 0, "n_cols": 0})
            pd.DataFrame(log).to_csv(OUTPUT_DIR / "sofascore_israel_log.csv", index=False)
            continue

        if df is None or len(df) == 0:
            print("empty")
            log.append({"season": year_str, "season_id": season_id,
                        "status": "empty", "n_players": 0, "n_cols": 0})
        else:
            df["_league"]      = LEAGUE_NAME
            df["_season_year"] = year_str
            all_dfs.append(df)
            log.append({"season": year_str, "season_id": season_id,
                        "status": "ok", "n_players": len(df),
                        "n_cols": len(df.columns)})
            print(f"{len(df)} players, {len(df.columns)} cols")
            time.sleep(DELAY)

        pd.DataFrame(log).to_csv(OUTPUT_DIR / "sofascore_israel_log.csv", index=False)

    if not all_dfs:
        print("\nNo data fetched.")
        return

    # ── Combine & reorder columns ─────────────────────────────────────────────
    combined = pd.concat(all_dfs, ignore_index=True)
    meta     = ["_league", "_season_year", "player", "player id", "team", "team id"]
    meta     = [c for c in meta if c in combined.columns]
    meta_set = set(meta)
    stat     = [c for c in combined.columns if c not in meta_set]
    combined = combined[meta + stat]

    # ── Split into two files ──────────────────────────────────────────────────
    df_rich   = combined[combined["_season_year"].isin(SEASONS_RICH)].reset_index(drop=True)
    df_sparse = combined[combined["_season_year"].isin(SEASONS_SPARSE)].reset_index(drop=True)

    out_full   = OUTPUT_DIR / "sofascore_israel_full.csv"
    out_rich   = OUTPUT_DIR / "sofascore_israel_2023_2025.csv"
    out_sparse = OUTPUT_DIR / "sofascore_israel_pre2021.csv"
    log_out    = OUTPUT_DIR / "sofascore_israel_log.csv"

    combined.to_csv(out_full,   index=False)
    df_rich.to_csv(out_rich,    index=False)
    df_sparse.to_csv(out_sparse, index=False)
    pd.DataFrame(log).to_csv(log_out, index=False)

    # ── NULL stats ────────────────────────────────────────────────────────────
    null_df        = null_stats(combined, meta_set)
    season_null_df = season_null_stats(combined, meta_set)

    null_col_out    = OUTPUT_DIR / "sofascore_israel_null_by_column.csv"
    season_null_out = OUTPUT_DIR / "sofascore_israel_null_by_season.csv"
    null_df.to_csv(null_col_out,    index=False)
    season_null_df.to_csv(season_null_out, index=False)

    # ── Column comparison vs top9 ─────────────────────────────────────────────
    comp_df     = compare_columns(df_rich, TOP9_CSV, meta_set)
    comp_out    = OUTPUT_DIR / "sofascore_israel_column_comparison.csv"
    if not comp_df.empty:
        comp_df.to_csv(comp_out, index=False)

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  FILES SAVED:")
    print(f"    Full combined  : {out_full}   ({len(combined):,} rows)")
    print(f"    Rich (23-25)   : {out_rich}   ({len(df_rich):,} rows, "
          f"{df_rich['_season_year'].nunique()} seasons)")
    print(f"    Sparse (pre-21): {out_sparse}  ({len(df_sparse):,} rows, "
          f"{df_sparse['_season_year'].nunique() if len(df_sparse) > 0 else 0} seasons)")
    print(f"    Log            : {log_out}")
    print(f"    NULL/col       : {null_col_out}")
    print(f"    NULL/season    : {season_null_out}")
    if not comp_df.empty:
        print(f"    Col comparison : {comp_out}")

    print(f"\n  Players per season:")
    print(combined.groupby("_season_year")["player"].count().to_string())

    print(f"\n  NULL % per column — RICH seasons only (23/24 + 24/25):")
    null_rich = null_stats(df_rich, meta_set)
    print(f"  {'Column':<38} {'null%':>7}  {'n_valid':>8}  {'n_null':>8}")
    print(f"  {'-'*65}")
    for _, r in null_rich.iterrows():
        print(f"  {r['column']:<38} {str(r['null_pct'])+'%':>7}  "
              f"{int(r['n_valid']):>8,}  {int(r['n_null']):>8,}")

    print(f"\n  NULL % per season pivot:")
    pivot = (season_null_df
             .pivot(index="column", columns="season", values="null_pct")
             .reindex(columns=sorted(season_null_df["season"].unique(),
                                     key=safe_year_end)))
    print(pivot.to_string())
    print(f"{'='*60}\nDone.")


if __name__ == "__main__":
    main()