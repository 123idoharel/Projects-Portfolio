"""
build_extra_combined.py
========================
Builds sofascore_extra_leagues_combined.csv from all extra league files.
Adds: player_positions | birth_year | age_in_season | tm_id

FIXED VERSION:
- TM ID matching now uses the same smart cascade logic as
  new_build_tm_valuations_complete.py
- TM search cache stores ONLY successful matches (never failures / empty)
- Position + birth year scraping follows add_positions.py logic
- One TM profile request can provide BOTH position and birth year

RUN:
  python build_extra_combined.py sample
  python build_extra_combined.py
"""

import re
import time
import json
import sys
from pathlib import Path
from unicodedata import normalize as unorm
from collections import Counter

import pandas as pd
import requests


SAMPLE_MODE = len(sys.argv) > 1 and sys.argv[1] == "sample"
SAMPLE_N = 30

# ── Input/output paths ────────────────────────────────────────────────────────
INPUT_FILES = [
    "sofascore_poland_ekstraklasa.csv",
    "sofascore_scotland_premiership.csv",
    "sofascore_switzerland_super_league.csv",
    "sofascore_colombia_primera_a.csv",
    "sofascore_denmark_superliga.csv",
    "sofascore_croatia_hnl.csv",
    "sofascore_norway_eliteserien.csv",
    "sofascore_romania_superliga.csv",
    "sofascore_russia_premier_league.csv",
    "sofascore_serbia_superliga.csv",
    "sofascore_sweden_allsvenskan.csv"
    # add more here as needed
]

FIFA_FILE = "fifa_fbref_merged.csv"
TM_FILE = "players.csv"
INDEX_FILE = "players_index_ALL.csv"
ANOTHER_FILE = "another_mapping_file.csv"
FBREF_MAP_FILE = "fbref_to_tm_mapping.csv"

OUTPUT_FILE = "sofascore_extra_leagues_combined.csv"
NEW_INDEX_FILE = "new_players_tm_index.csv"
NO_TMID_FILE = "no_tm_id_extra.csv"
SEARCH_CACHE_FILE = "tm_search_cache_extra.json"
PROFILE_CACHE_FILE = "profile_cache_extra.json"   # {player: {"pos":..., "born":...}}

DELAY_SEARCH = 2.0
DELAY_PROFILE = 1.5
SESSION_REFRESH = 80

# ── Paste fresh cookies when needed ───────────────────────────────────────────
BROWSER_COOKIES = {
    "aws-waf-token": "",
    "cuukie": "",
}

TM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.transfermarkt.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

TM_TO_FIFA = {
    "goalkeeper": "GK",
    "centre-back": "CB",
    "left-back": "LB",
    "right-back": "RB",
    "left wing-back": "LB",
    "right wing-back": "RB",
    "sweeper": "CB",
    "libero": "CB",
    "defensive midfield": "CDM",
    "central midfield": "CM",
    "attacking midfield": "CAM",
    "left midfield": "LM",
    "right midfield": "RM",
    "left winger": "LW",
    "right winger": "RW",
    "winger": "LW",
    "second striker": "CAM",
    "centre-forward": "ST",
    "striker": "ST",
    "forward": "ST",
}

BROAD_TO_FIFA = {
    "goalkeeper": "GK",
    "defender": "CB",
    "midfield": "CM",
    "midfielder": "CM",
    "attack": "ST",
    "attacker": "ST",
    "forward": "ST",
    "missing": "",
}

_ARABIC_CONNECTORS = {"al", "el", "bin", "bint", "abu", "abd", "bou", "ould", "de"}


# ── Generic helpers ───────────────────────────────────────────────────────────
def norm(s) -> str:
    if pd.isna(s) or s is None:
        return ""
    return (
        unorm("NFKD", str(s).lower().strip())
        .encode("ascii", "ignore")
        .decode()
        .strip()
    )


def norm_nat(s) -> str:
    return norm(s)[:5]


def extract_birth_year(raw) -> int | None:
    if pd.isna(raw) or not str(raw).strip():
        return None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", str(raw))
    return int(m.group(1)) if m else None


def season_end_year(s) -> int | None:
    try:
        s = str(s).strip()
        if "/" in s:
            right = s.split("/")[-1].strip()
            n = int(right)
            return 2000 + n if n < 50 else 1900 + n
        yr = int(s)
        return yr if 1990 < yr < 2030 else None
    except Exception:
        return None


def sub_pos_to_fifa(raw: str) -> str:
    key = norm(raw)

    # 🔥 הכי חשוב – winger קודם
    if "winger" in key:
        if "right" in key:
            return "RW"
        if "left" in key:
            return "LW"

    # wing-back
    if "wing-back" in key:
        if "right" in key:
            return "RB"
        if "left" in key:
            return "LB"

    # midfield
    if "midfield" in key:
        if "right" in key:
            return "RM"
        if "left" in key:
            return "LM"
        if "attacking" in key:
            return "CAM"
        if "defensive" in key:
            return "CDM"
        return "CM"

    # defence
    if "back" in key:
        if "right" in key:
            return "RB"
        if "left" in key:
            return "LB"
        return "CB"

    # striker / forward
    if "forward" in key or "striker" in key:
        return "ST"

    return ""


def extract_tm_id(url) -> str | None:
    if pd.isna(url) or not isinstance(url, str):
        return None
    m = re.search(r"/spieler/(\d+)", url)
    return m.group(1) if m else None


def last_name(s) -> str:
    p = norm(s).split()
    return p[-1] if p else ""


def first_token(s) -> str:
    p = norm(s).split()
    return p[0] if p else ""


def token_sim(a: str, b: str) -> float:
    ta, tb = set(norm(a).split()), set(norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def char_sim(a: str, b: str, n: int = 3) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    ga = set(a[i:i + n] for i in range(len(a) - n + 1)) if len(a) >= n else {a}
    gb = set(b[i:i + n] for i in range(len(b) - n + 1)) if len(b) >= n else {b}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / max(len(ga), len(gb))


def best_sim(a: str, b: str) -> float:
    return max(token_sim(a, b), char_sim(a, b))


def name_variants(player_name: str) -> list[str]:
    nn = norm(player_name)
    tokens = nn.split()
    variants = set()

    if "-" in nn:
        variants.add(nn.replace("-", " "))
        variants.add(" ".join(t.split("-")[-1] for t in tokens))

    if len(tokens) >= 3:
        variants.add(f"{tokens[0]} {tokens[-1]}")

    if len(tokens) >= 2:
        variants.add(tokens[-1])
        variants.add(tokens[0])

    if len(tokens) == 2:
        variants.add(f"{tokens[1]} {tokens[0]}")

    filtered = [t for t in tokens if t not in _ARABIC_CONNECTORS]
    if len(filtered) < len(tokens) and len(filtered) >= 1:
        variants.add(" ".join(filtered))
        if len(filtered) >= 2:
            variants.add(filtered[-1])
            variants.add(f"{filtered[0]} {filtered[-1]}")

    if len(tokens) >= 4:
        for i in range(len(tokens) - 1):
            variants.add(f"{tokens[i]} {tokens[i+1]}")

    variants.discard(nn)
    variants.discard("")
    return list(variants)


def load_json_dict(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.load(open(p, "r", encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_success_only(cache: dict, path: str):
    clean = {}
    for k, v in cache.items():
        if isinstance(v, dict):
            if any(x not in (None, "", [], {}) for x in v.values()):
                clean[k] = v
        elif v not in (None, "", [], {}, "NOT_FOUND"):
            clean[k] = v
    json.dump(clean, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ── TM session ────────────────────────────────────────────────────────────────
_session = None
_session_calls = 0


def get_session(force_refresh: bool = False):
    global _session, _session_calls

    if _session is None or force_refresh or _session_calls >= SESSION_REFRESH:
        s = requests.Session()
        s.headers.update(TM_HEADERS)

        for name, val in BROWSER_COOKIES.items():
            if val.strip():
                s.cookies.set(name, val.strip(), domain="www.transfermarkt.com")

        try:
            r = s.get("https://www.transfermarkt.com", timeout=20)
            if r.status_code in (403, 405):
                print(f"\n  *** WAF BLOCKED ({r.status_code}) — paste fresh token ***")
                try:
                    tok = input("  aws-waf-token: ").strip()
                    if tok:
                        s.cookies.set("aws-waf-token", tok, domain="www.transfermarkt.com")
                        BROWSER_COOKIES["aws-waf-token"] = tok
                        r = s.get("https://www.transfermarkt.com", timeout=20)
                except (EOFError, KeyboardInterrupt):
                    time.sleep(5)

            time.sleep(1.2)
            s.get("https://www.transfermarkt.com/lionel-messi/profil/spieler/28003", timeout=15)
            time.sleep(0.8)
            print(f" [session={r.status_code}]", end="", flush=True)
        except Exception as e:
            print(f" [session warning: {e}]", end="", flush=True)

        _session = s
        _session_calls = 0

    _session_calls += 1
    return _session


# ── Load input data ───────────────────────────────────────────────────────────
def load_extra_league_players():
    frames = []
    for fname in INPUT_FILES:
        if not Path(fname).exists():
            print(f"  MISSING (skip): {fname}")
            continue
        df = pd.read_csv(fname, low_memory=False)
        frames.append(df)
        print(f"  {fname}: {len(df):,} rows, {df['player'].nunique():,} players")

    if not frames:
        raise FileNotFoundError("No input files found")

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = (
        combined
        .drop_duplicates(subset=["player", "_league", "_season_year"])
        .reset_index(drop=True)
    )

    players = sorted(combined["player"].dropna().unique())

    sofa_pid = {}
    if "player id" in combined.columns:
        sofa_pid = (
            combined.groupby("player")["player id"]
            .first()
            .dropna()
            .apply(lambda x: str(int(x)))
            .to_dict()
        )

    # metadata for smart matching
    meta = {}
    for p in players:
        meta[p] = {
            "player_name": p,
            "sofascore_id": sofa_pid.get(p, ""),
            "nationality": "",
            "age_min": None,
            "age_max": None,
            "height_cm": None,
        }

    # enrich from fifa if available
    if Path(FIFA_FILE).exists():
        fifa_cols = pd.read_csv(FIFA_FILE, nrows=0).columns.tolist()
        usecols = [c for c in ["player", "nationality_name", "age_fifa"] if c in fifa_cols]
        if usecols:
            fifa = pd.read_csv(FIFA_FILE, low_memory=False, usecols=usecols)
            if "player" in fifa.columns:
                grouped = fifa.groupby("player", as_index=False).agg(
                    nationality=("nationality_name", "first") if "nationality_name" in fifa.columns else ("player", "first"),
                    age_min=("age_fifa", "min") if "age_fifa" in fifa.columns else ("player", "first"),
                    age_max=("age_fifa", "max") if "age_fifa" in fifa.columns else ("player", "first"),
                )
                for _, row in grouped.iterrows():
                    p = row["player"]
                    if p in meta:
                        if "nationality" in row and pd.notna(row["nationality"]):
                            meta[p]["nationality"] = row["nationality"]
                        if "age_min" in row and pd.notna(row["age_min"]):
                            meta[p]["age_min"] = row["age_min"]
                        if "age_max" in row and pd.notna(row["age_max"]):
                            meta[p]["age_max"] = row["age_max"]

    players_df = pd.DataFrame(list(meta.values()))
    players_df["norm_name"] = players_df["player_name"].apply(norm)
    players_df["_last"] = players_df["player_name"].apply(last_name)
    players_df["_first_tok"] = players_df["player_name"].apply(first_token)

    def est_birth(row):
        if pd.notna(row.get("age_min")) and pd.notna(row.get("age_max")):
            return int(round(2025 - (float(row["age_min"]) + float(row["age_max"])) / 2))
        return None

    players_df["_est_birth"] = players_df.apply(est_birth, axis=1)
    players_df["_nat5"] = players_df["nationality"].apply(norm_nat)

    return combined, players, sofa_pid, players_df


# ── Load mappings for smart TM ID matching ────────────────────────────────────
def load_mappings():
    m_another_exact = {}
    another_df = pd.DataFrame()
    sofa_id_map = {}

    if Path(ANOTHER_FILE).exists():
        anoth = None
        for enc in ["utf-8", "latin-1", "cp1252"]:
            try:
                anoth = pd.read_csv(ANOTHER_FILE, low_memory=False, encoding=enc)
                break
            except Exception:
                continue

        if anoth is not None:
            name_col = "name" if "name" in anoth.columns else None
            id_col = next((c for c in anoth.columns if "transfermark" in c.lower()), None)
            dob_col = "date_of_birth" if "date_of_birth" in anoth.columns else None
            nat_col = "nationality" if "nationality" in anoth.columns else None
            ht_col = "height_cm" if "height_cm" in anoth.columns else None

            if name_col and id_col:
                anoth["_id_num"] = pd.to_numeric(anoth[id_col], errors="coerce")
                anoth["tm_id"] = anoth["_id_num"].apply(
                    lambda x: str(int(x)) if pd.notna(x) and x > 0 else None
                )
                anoth = anoth[anoth["tm_id"].notna()].copy()
                anoth["norm_name"] = anoth[name_col].apply(norm)
                anoth["_last"] = anoth["norm_name"].apply(last_name)
                anoth["_first_tok"] = anoth["norm_name"].apply(first_token)
                anoth["birth_year"] = (
                    pd.to_datetime(anoth[dob_col], errors="coerce").dt.year
                    if dob_col else None
                )
                anoth["norm_nat"] = anoth[nat_col].apply(norm_nat) if nat_col else ""
                anoth["height"] = pd.to_numeric(anoth[ht_col], errors="coerce") if ht_col else None

                m_another_exact = (
                    anoth.drop_duplicates("norm_name")
                    .set_index("norm_name")["tm_id"]
                    .to_dict()
                )
                another_df = anoth[
                    ["norm_name", "tm_id", "_last", "_first_tok", "birth_year", "norm_nat", "height"]
                ].copy()

                sofa_id_col = next((c for c in anoth.columns if "sofascore" in c.lower()), None)
                if sofa_id_col:
                    raw = anoth[anoth[sofa_id_col].notna()].copy()
                    raw["_sk"] = pd.to_numeric(raw[sofa_id_col], errors="coerce")
                    raw = raw[raw["_sk"].notna()]
                    sofa_id_map = {str(int(k)): v for k, v in zip(raw["_sk"], raw["tm_id"])}

                print(f"  another_mapping_file.csv: {len(m_another_exact):,} exact | sofa_id_map={len(sofa_id_map):,}")
            else:
                print("  another_mapping_file.csv: WARNING — relevant columns not identified")
    else:
        print("  another_mapping_file.csv: NOT FOUND")

    m_fbref_exact = {}
    if Path(FBREF_MAP_FILE).exists():
        fbref = pd.read_csv(FBREF_MAP_FILE, low_memory=False, encoding="latin-1")
        fbref["tm_id"] = fbref["UrlTmarkt"].apply(extract_tm_id)
        fbref["norm_name"] = fbref["PlayerFBref"].apply(norm)
        m_fbref_exact = (
            fbref[fbref["tm_id"].notna()]
            .drop_duplicates("norm_name")
            .set_index("norm_name")["tm_id"]
            .to_dict()
        )
        print(f"  fbref_to_tm_mapping.csv: {len(m_fbref_exact):,} exact")
    else:
        print("  fbref_to_tm_mapping.csv: NOT FOUND")

    m_players_exact = {}
    pcsv = pd.DataFrame()
    if Path(TM_FILE).exists():
        pcsv = pd.read_csv(TM_FILE, low_memory=False, encoding="utf-8")
        pcsv["tm_id"] = pcsv["player_id"].astype(str)
        pcsv["norm_name"] = pcsv["name"].apply(norm)
        pcsv["_last"] = pcsv["norm_name"].apply(last_name)
        pcsv["_first_tok"] = pcsv["norm_name"].apply(first_token)
        pcsv["birth_year"] = pd.to_datetime(pcsv["date_of_birth"], errors="coerce").dt.year
        pcsv["norm_nat"] = pcsv["country_of_citizenship"].apply(norm_nat)
        pcsv["height"] = pd.to_numeric(pcsv["height_in_cm"], errors="coerce")
        m_players_exact = (
            pcsv.drop_duplicates("norm_name")
            .set_index("norm_name")["tm_id"]
            .to_dict()
        )
        print(f"  players.csv: {len(m_players_exact):,} exact")
    else:
        print("  players.csv: NOT FOUND")

    return m_another_exact, another_df, sofa_id_map, m_fbref_exact, m_players_exact, pcsv


# ── Smart static matching ─────────────────────────────────────────────────────
def _best(cands: pd.DataFrame, nn: str, min_sim: float):
    if len(cands) == 0:
        return None, 0.0
    sims = cands["norm_name"].apply(lambda n: best_sim(nn, n))
    best_idx = sims.idxmax()
    best_s = float(sims[best_idx])
    if best_s < min_sim:
        return None, 0.0
    return cands.loc[best_idx, "tm_id"], best_s


def find_tm_id(row, m_another_exact, another_df, sofa_id_map,
               m_fbref_exact, m_players_exact, pcsv):
    nn = row["norm_name"]
    last = row["_last"]
    ftok = row["_first_tok"]
    est_birth = row.get("_est_birth")
    nat5 = row.get("_nat5", "")

    # Step 1-3: exact
    if nn in m_another_exact:
        return m_another_exact[nn], "exact_another"
    if nn in m_fbref_exact:
        return m_fbref_exact[nn], "exact_fbref"
    if nn in m_players_exact:
        return m_players_exact[nn], "exact_players"

    def af_cands(last_filter=True, nat_filter=True, dob_tol=None, ht_tol=None):
        if len(another_df) == 0:
            return another_df
        mask = pd.Series(True, index=another_df.index)
        if last_filter and last:
            mask &= (another_df["_last"] == last)
        if nat_filter and nat5:
            mask &= another_df["norm_nat"].str.startswith(nat5, na=False)
        if dob_tol is not None and est_birth:
            mask &= another_df["birth_year"].between(est_birth - dob_tol, est_birth + dob_tol)
        if ht_tol is not None:
            h = row.get("height_cm") or row.get("height")
            if h:
                mask &= another_df["height"].between(float(h) - ht_tol, float(h) + ht_tol)
        return another_df[mask]

    def pc_cands(last_filter=True, nat_filter=True, dob_tol=None, ht_tol=None):
        if len(pcsv) == 0:
            return pcsv
        mask = pd.Series(True, index=pcsv.index)
        if last_filter and last:
            mask &= (pcsv["_last"] == last)
        if nat_filter and nat5:
            mask &= pcsv["norm_nat"].str.startswith(nat5, na=False)
        if dob_tol is not None and est_birth:
            mask &= pcsv["birth_year"].between(est_birth - dob_tol, est_birth + dob_tol)
        if ht_tol is not None:
            h = row.get("height_cm") or row.get("height")
            if h:
                mask &= pcsv["height"].between(float(h) - ht_tol, float(h) + ht_tol)
        return pcsv[mask]

    # Step 4
    if last and nat5 and est_birth:
        c = af_cands(nat_filter=True, dob_tol=1)
        if len(c) == 1:
            return c.iloc[0]["tm_id"], "another:last+nat+dob1"
        t, s = _best(c, nn, 0.5)
        if t:
            return t, f"another:last+nat+dob1+sim{s:.2f}"

    # Step 5
    if last and nat5 and est_birth:
        c = pc_cands(nat_filter=True, dob_tol=1)
        if len(c) == 1:
            return c.iloc[0]["tm_id"], "players:last+nat+dob1"
        t, s = _best(c, nn, 0.5)
        if t:
            return t, f"players:last+nat+dob1+sim{s:.2f}"

    # Step 6
    c = af_cands(nat_filter=False, dob_tol=1, ht_tol=2)
    if len(c) == 1:
        return c.iloc[0]["tm_id"], "another:last+dob+ht"
    t, s = _best(c, nn, 0.6)
    if t:
        return t, f"another:last+dob+ht+sim{s:.2f}"

    # Step 7
    c = pc_cands(nat_filter=False, dob_tol=1, ht_tol=2)
    if len(c) == 1:
        return c.iloc[0]["tm_id"], "players:last+dob+ht"
    t, s = _best(c, nn, 0.6)
    if t:
        return t, f"players:last+dob+ht+sim{s:.2f}"

    # Step 8
    if last and nat5:
        c = af_cands(nat_filter=True, dob_tol=2)
        if len(c) == 1:
            return c.iloc[0]["tm_id"], "another:last+nat+dob2"
        t, s = _best(c, nn, 0.5)
        if t:
            return t, f"another:last+nat+dob2+sim{s:.2f}"

        c = pc_cands(nat_filter=True, dob_tol=2)
        if len(c) == 1:
            return c.iloc[0]["tm_id"], "players:last+nat+dob2"
        t, s = _best(c, nn, 0.5)
        if t:
            return t, f"players:last+nat+dob2+sim{s:.2f}"

    # Step 9
    if last and nat5:
        c = af_cands(nat_filter=True, dob_tol=None)
        if len(c) == 1:
            return c.iloc[0]["tm_id"], "another:last+nat"
        t, s = _best(c, nn, 0.7)
        if t:
            return t, f"another:last+nat+sim{s:.2f}"

        c = pc_cands(nat_filter=True, dob_tol=None)
        if len(c) == 1:
            return c.iloc[0]["tm_id"], "players:last+nat"
        t, s = _best(c, nn, 0.7)
        if t:
            return t, f"players:last+nat+sim{s:.2f}"

    # Step 10
    if ftok and nat5 and est_birth and len(pcsv) > 0:
        c = pcsv[
            (pcsv["_first_tok"] == ftok) &
            (pcsv["norm_nat"].str.startswith(nat5, na=False)) &
            (pcsv["birth_year"].between(est_birth - 2, est_birth + 2))
        ]
        if len(c) == 1:
            return c.iloc[0]["tm_id"], "players:first+nat+dob2"
        t, s = _best(c, nn, 0.6)
        if t:
            return t, f"players:first+nat+dob2+sim{s:.2f}"

    # Step 11
    if len(pcsv) > 0:
        mask11 = pd.Series(True, index=pcsv.index)
        if nat5:
            mask11 &= pcsv["norm_nat"].str.startswith(nat5, na=False)
        if est_birth:
            mask11 &= pcsv["birth_year"].between(est_birth - 3, est_birth + 3)
        t, s = _best(pcsv[mask11], nn, 0.75)
        if t:
            return t, f"players:fuzzy_sim{s:.2f}"

    # Step 12 name-only high sim
    if (not nat5 or not est_birth) and last:
        if len(another_df) > 0:
            c12a = another_df[another_df["_last"] == last]
            if len(c12a) == 0 and ftok:
                c12a = another_df[another_df["_first_tok"] == ftok]
            t, s = _best(c12a, nn, 0.90)
            if t:
                return t, f"another:name_only_sim{s:.2f}"

        if len(pcsv) > 0:
            c12b = pcsv[pcsv["_last"] == last]
            if len(c12b) == 0 and ftok:
                c12b = pcsv[pcsv["_first_tok"] == ftok]
            t, s = _best(c12b, nn, 0.90)
            if t:
                return t, f"players:name_only_sim{s:.2f}"

    # Step 13 sofascore bridge
    sofa_pid = str(row.get("sofascore_id", "") or "")
    if sofa_pid and sofa_pid in sofa_id_map:
        return sofa_id_map[sofa_pid], "sofascore_id_bridge"

    # Step 14 variants
    if nat5 or est_birth:
        _mask_a = pd.Series(True, index=another_df.index) if len(another_df) > 0 else pd.Series(dtype=bool)
        if nat5 and len(_mask_a):
            _mask_a &= another_df["norm_nat"].str.startswith(nat5, na=False)
        if est_birth and len(_mask_a):
            _mask_a &= another_df["birth_year"].between(est_birth - 2, est_birth + 2)
        _var_c_another = another_df[_mask_a] if len(_mask_a) > 0 else pd.DataFrame()

        _mask_p = pd.Series(True, index=pcsv.index) if len(pcsv) > 0 else pd.Series(dtype=bool)
        if nat5 and len(_mask_p):
            _mask_p &= pcsv["norm_nat"].str.startswith(nat5, na=False)
        if est_birth and len(_mask_p):
            _mask_p &= pcsv["birth_year"].between(est_birth - 2, est_birth + 2)
        _var_c_pcsv = pcsv[_mask_p] if len(_mask_p) > 0 else pd.DataFrame()
    else:
        _var_c_another = pd.DataFrame()
        _var_c_pcsv = pd.DataFrame()

    for variant_nn in name_variants(row["player_name"]):
        if variant_nn in m_another_exact:
            return m_another_exact[variant_nn], f"variant_another:{variant_nn}"
        if variant_nn in m_fbref_exact:
            return m_fbref_exact[variant_nn], f"variant_fbref:{variant_nn}"
        if variant_nn in m_players_exact:
            return m_players_exact[variant_nn], f"variant_players:{variant_nn}"
        if len(_var_c_another) > 0:
            t, s = _best(_var_c_another, variant_nn, 0.75)
            if t:
                return t, f"variant+fuzzy_another:{variant_nn}+sim{s:.2f}"
        if len(_var_c_pcsv) > 0:
            t, s = _best(_var_c_pcsv, variant_nn, 0.75)
            if t:
                return t, f"variant+fuzzy_players:{variant_nn}+sim{s:.2f}"

    return None, "not_found"


# ── TM web search fallback ────────────────────────────────────────────────────
def _tm_search_one(query: str, nn: str, pcsv, nat5: str, est_birth, sim_floor: float, retries: int = 2):
    for attempt in range(1, retries + 1):
        try:
            time.sleep(DELAY_SEARCH)
            r = get_session().get(
                "https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche",
                params={"query": query, "Kat": "spieler"},
                timeout=20,
            )
            if r.status_code == 429:
                time.sleep(30 * attempt)
                continue
            if r.status_code != 200:
                return None, None

            entries = re.findall(
                r'href="/[^"]+/profil/spieler/(\d+)"[^>]*>\s*([^<]+)<',
                r.text,
            )

            best_id, best_sim_val, best_label = None, 0.0, ""

            for tm_id, found_name in entries[:10]:
                s = best_sim(nn, norm(found_name))
                if s < 0.35:
                    continue

                confirmed = False
                mr = pcsv[pcsv["tm_id"] == tm_id] if len(pcsv) > 0 else pd.DataFrame()
                if len(mr) > 0:
                    row = mr.iloc[0]
                    nat_ok = (not nat5 or norm(str(row.get("norm_nat", ""))).startswith(nat5))
                    age_ok = (
                        est_birth is None or
                        pd.isna(row.get("birth_year")) or
                        abs(int(row["birth_year"]) - est_birth) <= 3
                    )
                    confirmed = nat_ok and age_ok
                else:
                    confirmed = s >= sim_floor

                if confirmed and s > best_sim_val:
                    best_id, best_sim_val = tm_id, s
                    best_label = f"web_sim{s:.2f}[q={query}]"

            if best_id and best_sim_val >= (0.40 if (nat5 or est_birth) else sim_floor):
                return best_id, best_label

            return None, None

        except requests.exceptions.Timeout:
            if attempt < retries:
                time.sleep(10 * attempt)
            else:
                return None, None
        except Exception:
            return None, None
    return None, None


def tm_web_search(player_name, pcsv, nat5="", est_birth=None, retries=2):
    nn = norm(player_name)
    tokens = nn.split()
    sim_threshold = 0.40 if (nat5 or est_birth) else 0.55

    queries = [player_name]
    if len(tokens) >= 3:
        queries.append(f"{tokens[0]} {tokens[-1]}")
    if len(tokens) >= 2:
        queries.append(tokens[-1])
        queries.append(tokens[0])
    if len(tokens) >= 4:
        for i in range(len(tokens) - 1):
            queries.append(f"{tokens[i]} {tokens[i+1]}")

    seen = set()
    queries = [q for q in queries if q not in seen and not seen.add(q)]

    for query in queries:
        tm_id, method = _tm_search_one(query, nn, pcsv, nat5, est_birth, sim_threshold, retries)
        if tm_id:
            return tm_id, method

    return None, "no_match"


# ── Profile scrape for position + birth year ─────────────────────────────────
def scrape_profile(tm_id: str, verbose: bool = False):
    url = f"https://www.transfermarkt.com/x/profil/spieler/{tm_id}"
    pos = ""
    by = None

    try:
        time.sleep(DELAY_PROFILE)
        r = get_session().get(url, timeout=20)

        if verbose:
            print(f"\n      [status={r.status_code}, url={url}]", end="", flush=True)

        if r.status_code != 200:
            return pos, by

        html = r.text


        pos = ""

        # 🔥 1. structure החדש (כמו בתמונה שלך)
        m = re.search(
            r'Position:\s*"\s*<span[^>]*class="[^"]*data-header__content[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
            html,
            re.IGNORECASE
        )
        if m:
            raw = m.group(1).strip()
            if raw.lower() not in ["midfield", "attack", "defence"]:
                pos = sub_pos_to_fifa(raw)

        # 🔥 2. fallback לגרסה הישנה
        if not pos:
            m2 = re.search(
                r'Position:\s*</span>\s*<span[^>]*>([^<]+)</span>',
                html,
                re.IGNORECASE
            )
            if m2:
                raw = m2.group(1).strip()
                pos = sub_pos_to_fifa(raw)

        # 🔥 3. jobTitle (קריטי לשוערים!)
        if not pos:
            m3 = re.search(
                r'itemprop=["\']jobTitle["\'][^>]*>\s*([^<]+?)\s*<',
                html,
                re.IGNORECASE
            )
            if m3:
                raw = m3.group(1).strip()
                pos = sub_pos_to_fifa(raw)

        # 🔥 4. fallback נוסף (למקרים מוזרים)
        if not pos:
            m4 = re.search(
                r'data-header__content[^>]*>\s*([^<]+?)\s*</span>',
                html,
                re.IGNORECASE
            )
            if m4:
                raw = m4.group(1).strip()
                pos = sub_pos_to_fifa(raw)



        # birth year
        m_by = re.search(r'itemprop=["\']birthDate["\'][^>]*content=["\']([^"\']+)["\']', html)
        if not m_by:
            m_by = re.search(
                r'Date of birth.*?(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
                r'[a-z]* \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2})\b',
                html, re.IGNORECASE | re.DOTALL
            )
        if m_by:
            raw_date = m_by.group(1).strip()
            by = extract_birth_year(raw_date)
            if verbose:
                print(f"\n      [birth: '{raw_date}' → {by}]", end="", flush=True)

        if verbose and by is None:
            print("\n      [birth: not found]", end="", flush=True)

    except Exception as e:
        if verbose:
            print(f"\n      [error: {e}]", end="", flush=True)

    return pos, by


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  BUILD EXTRA LEAGUES COMBINED")
    print(f"  Mode: {'SAMPLE' if SAMPLE_MODE else 'FULL RUN'}")
    print("=" * 65)

    # Phase 1
    print("\n" + "─" * 65)
    print("  PHASE 1: Loading data files")
    print("─" * 65)

    combined, players, sofa_pid, players_df = load_extra_league_players()
    print(f"\n  Combined: {len(combined):,} rows | {len(players):,} unique players")
    print(f"  Players with sofascore ID: {len(sofa_pid):,}")

    # Phase 2
    print("\n" + "─" * 65)
    print("  PHASE 2: Building TM ID mapping")
    print("─" * 65)

    m_another_exact, another_df, sofa_id_map, m_fbref_exact, m_players_exact, pcsv = load_mappings()

    player_to_tmid = {}
    tmid_source = {}

    # from index file first
    sofa_id_to_tmid = {}
    name_to_tmid = {}
    if Path(INDEX_FILE).exists():
        idx = pd.read_csv(INDEX_FILE, low_memory=False)
        idx["tm_id"] = idx["tm_id"].astype(str).str.strip()
        idx = idx[~idx["tm_id"].isin(["", "nan"])]

        if "sofascore_id" in idx.columns:
            for _, row in idx.iterrows():
                sid = str(row.get("sofascore_id", "")).strip().split(".")[0]
                if sid and sid != "nan":
                    sofa_id_to_tmid[sid] = row["tm_id"]

        for _, row in idx.iterrows():
            for col in ["original_player_name", "player_name"]:
                val = str(row.get(col, "")).strip()
                if val and val != "nan":
                    name_to_tmid[val] = row["tm_id"]

        print(f"  players_index_ALL.csv: {len(sofa_id_to_tmid):,} by sofascore_id, {len(name_to_tmid):,} by name")
    else:
        print("  players_index_ALL.csv: NOT FOUND")

    # Step A
    n_a = 0
    for player in players:
        sid = sofa_pid.get(player, "")
        if sid and sid in sofa_id_to_tmid:
            player_to_tmid[player] = sofa_id_to_tmid[sid]
            tmid_source[player] = "A_sofascore_id"
            n_a += 1
    print(f"\n  Step A (sofascore_id → index): {n_a:,}")

    # Step B
    n_b = 0
    for player in players:
        if player in player_to_tmid:
            continue
        if player in name_to_tmid:
            player_to_tmid[player] = name_to_tmid[player]
            tmid_source[player] = "B_name_index"
            n_b += 1
    print(f"  Step B (name → index):         {n_b:,}")

    # Step C
    n_c = 0
    players_name_to_id = {str(r["name"]): str(r["player_id"]) for _, r in pcsv[["name", "player_id"]].dropna().iterrows()} if len(pcsv) > 0 else {}
    for player in players:
        if player in player_to_tmid:
            continue
        if player in players_name_to_id:
            player_to_tmid[player] = players_name_to_id[player]
            tmid_source[player] = "C_players_csv"
            n_c += 1
    print(f"  Step C (name → players.csv):   {n_c:,}")

    # Smart static cascade
    remaining = [p for p in players if p not in player_to_tmid]
    n_static = 0
    for _, row in players_df[players_df["player_name"].isin(remaining)].iterrows():
        tm_id, method = find_tm_id(
            row,
            m_another_exact, another_df, sofa_id_map,
            m_fbref_exact, m_players_exact, pcsv
        )
        if tm_id:
            player_to_tmid[row["player_name"]] = tm_id
            tmid_source[row["player_name"]] = method
            n_static += 1
    print(f"  Step D (smart static cascade): {n_static:,}")

    # Web search fallback with success-only cache
    remaining = [p for p in players if p not in player_to_tmid]
    print(f"\n  After A+B+C+D: {len(player_to_tmid):,} matched, {len(remaining):,} need TM web search")

    search_cache = load_json_dict(SEARCH_CACHE_FILE)
    print(f"  Search cache (success-only): {len(search_cache):,}")

    n_from_cache = 0
    still_need = []
    for player in remaining:
        cached = search_cache.get(player)
        if cached:
            player_to_tmid[player] = cached
            tmid_source[player] = "E_search_cache"
            n_from_cache += 1
        else:
            still_need.append(player)

    print(f"  From search cache: {n_from_cache:,} | Still need search: {len(still_need):,}")

    if SAMPLE_MODE:
        still_need = still_need[:SAMPLE_N]
        print(f"  SAMPLE MODE: only searching {len(still_need)} players")

    if still_need:
        print(f"\n  Step E: TM web search ({len(still_need):,} players)")
        print("  Initializing TM session...", end="")
        get_session(force_refresh=True)
        print()

        n_found_search = 0
        n_not_found = 0

        try:
            subset = players_df[players_df["player_name"].isin(still_need)]
            for i, (_, row) in enumerate(subset.iterrows(), 1):
                player = row["player_name"]
                print(f"  [{i:>4}/{len(subset)}] {player:<35} ...", end="", flush=True)

                tm_id, method = tm_web_search(
                    row["player_name"],
                    pcsv,
                    row.get("_nat5", ""),
                    row.get("_est_birth"),
                )

                if tm_id:
                    player_to_tmid[player] = tm_id
                    tmid_source[player] = method
                    search_cache[player] = tm_id   # success only
                    n_found_search += 1
                    print(f" found: {tm_id} ({method})")
                else:
                    n_not_found += 1
                    print(" not found")

                if i % 50 == 0:
                    save_success_only(search_cache, SEARCH_CACHE_FILE)
                    print(f"  [search cache saved at {i}]")

        except KeyboardInterrupt:
            print("\n  Interrupted — saving success-only search cache...")
            save_success_only(search_cache, SEARCH_CACHE_FILE)
            sys.exit(0)

        save_success_only(search_cache, SEARCH_CACHE_FILE)
        print(f"\n  Step E done: found={n_found_search}, not found={n_not_found}")

    n_matched = len(player_to_tmid)
    n_missing = len(players) - n_matched
    print(f"\n  TM ID mapping TOTAL: {n_matched:,} / {len(players):,} ({n_matched/len(players)*100:.1f}%)")
    print(f"  No TM ID found: {n_missing:,} ({n_missing/len(players)*100:.1f}%)")
    for src, cnt in sorted(Counter(tmid_source.values()).items(), key=lambda x: (-x[1], x[0])):
        print(f"    {src}: {cnt:,}")

    # Phase 3
    print("\n" + "─" * 65)
    print("  PHASE 3: Position + birth year")
    print("─" * 65)

    fifa_pos = {}
    fifa_born = {}
    if Path(FIFA_FILE).exists():
        cols = pd.read_csv(FIFA_FILE, nrows=0).columns.tolist()
        pos_col = "player_positions" if "player_positions" in cols else None
        born_cols = [c for c in ["born_fbref", "born_fifa", "dob", "birth_date"] if c in cols]
        usecols = [c for c in ["player", pos_col] + born_cols if c]
        fifa = pd.read_csv(FIFA_FILE, low_memory=False, usecols=usecols)

        if pos_col and pos_col in fifa.columns:
            fifa_pos = fifa.groupby("player")[pos_col].first().dropna().to_dict()

        for _, row in fifa.iterrows():
            p = row["player"]
            if p not in fifa_born:
                for bc in born_cols:
                    by = extract_birth_year(row.get(bc))
                    if by:
                        fifa_born[p] = by
                        break

        print(f"  FIFA: {len(fifa_pos):,} positions | {len(fifa_born):,} birth years")
    else:
        print("  FIFA file not found")

    tm_pos = {}
    tm_born = {}
    if len(pcsv) > 0:
        n_sub, n_broad = 0, 0
        for _, row in pcsv.iterrows():
            name = str(row["name"])
            mapped = sub_pos_to_fifa(str(row.get("sub_position", "")))
            if mapped:
                tm_pos[name] = mapped
                n_sub += 1
            else:
                mapped = sub_pos_to_fifa(str(row.get("position", "")))
                if mapped:
                    tm_pos[name] = mapped
                    n_broad += 1

            by = extract_birth_year(row.get("date_of_birth"))
            if by and name not in tm_born:
                tm_born[name] = by

        print(f"  players.csv: {len(tm_pos):,} positions (sub={n_sub:,}, broad={n_broad:,}) | {len(tm_born):,} birth years")

    profile_cache = {}
    print(f"  Profile cache: {len(profile_cache):,} entries")

    pos_map = {}
    born_map = {}
    need_web = []

    n_pos_src = {"fifa": 0, "tm_csv": 0, "cache": 0}
    n_born_src = {"fifa": 0, "tm_csv": 0, "cache": 0}

    for player in players:
        c = profile_cache.get(player, {})
        if not isinstance(c, dict):
            c = {}

        if player in fifa_pos:
            pos_map[player] = str(fifa_pos[player])
            n_pos_src["fifa"] += 1
        elif player in tm_pos:
            pos_map[player] = tm_pos[player]
            n_pos_src["tm_csv"] += 1
        

        if player in fifa_born:
            born_map[player] = fifa_born[player]
            n_born_src["fifa"] += 1
        elif player in tm_born:
            born_map[player] = tm_born[player]
            n_born_src["tm_csv"] += 1
       

        if (player not in pos_map or player not in born_map) and player in player_to_tmid:
            need_web.append(player)

    print(f"\n  Position assigned: {len(pos_map):,}/{len(players):,}")
    print(f"    fifa={n_pos_src['fifa']:,}, tm_csv={n_pos_src['tm_csv']:,}, cache={n_pos_src['cache']:,}")
    print(f"  Birth year assigned: {len(born_map):,}/{len(players):,}")
    print(f"    fifa={n_born_src['fifa']:,}, tm_csv={n_born_src['tm_csv']:,}, cache={n_born_src['cache']:,}")
    print(f"  Need TM profile scrape: {len(need_web):,}")

    to_scrape = need_web[:SAMPLE_N] if SAMPLE_MODE else need_web

    if to_scrape:
        print(f"\n  Scraping {len(to_scrape):,} TM profiles...")
        print("  Initializing TM session...", end="")
        get_session()
        print()

        ok_pos = 0
        ok_born = 0

        try:
            for i, player in enumerate(to_scrape, 1):
                tm_id = player_to_tmid[player]
                need_p = player not in pos_map
                need_b = player not in born_map

                print(f"  [{i:>4}/{len(to_scrape)}] {player:<35} (tm={tm_id}) ...", end="", flush=True)
                pos, born = scrape_profile(tm_id, verbose=SAMPLE_MODE)

                c = profile_cache.get(player, {})
                if not isinstance(c, dict):
                    c = {}

                if pos:
                    c["pos"] = pos
                if born:
                    c["born"] = born
                if c:
                    profile_cache[player] = c

                if pos and need_p:
                    pos_map[player] = pos
                    ok_pos += 1
                if born and need_b:
                    born_map[player] = born
                    ok_born += 1

                print(f" pos={pos or '?'}, born={born or '?'}")

                if i % 100 == 0:
                    save_success_only(profile_cache, PROFILE_CACHE_FILE)
                    print(f"  [profile cache saved at {i}]")

        except KeyboardInterrupt:
            print("\n  Interrupted — saving profile cache...")
            save_success_only(profile_cache, PROFILE_CACHE_FILE)
            sys.exit(0)

        save_success_only(profile_cache, PROFILE_CACHE_FILE)
        print(f"  Profile cache saved: {len(profile_cache):,} entries")
        print(f"  Pos found: {ok_pos:,} | Born found: {ok_born:,}")

    # Phase 4
    print("\n" + "─" * 65)
    print("  PHASE 4: Computing age_in_season")
    print("─" * 65)

    combined["player_positions"] = combined["player"].map(pos_map).fillna("")
    combined["birth_year"] = combined["player"].map(born_map)
    combined["tm_id"] = combined["player"].map(player_to_tmid)

    combined["_end_yr"] = combined["_season_year"].apply(season_end_year)
    combined["age_in_season"] = (
        (combined["_end_yr"] - combined["birth_year"])
        .where(combined["birth_year"].notna() & combined["_end_yr"].notna())
        .apply(lambda x: int(x) if pd.notna(x) else None)
    )
    combined.drop(columns=["_end_yr"], inplace=True)

    cols = list(combined.columns)
    new_cols = ["player_positions", "birth_year", "age_in_season", "tm_id"]
    for c in new_cols:
        if c in cols:
            cols.remove(c)
    ins = cols.index("player") + 1
    cols[ins:ins] = new_cols
    combined = combined[cols].sort_values(["_league", "_season_year", "player"]).reset_index(drop=True)

    # Phase 5
    print("\n" + "─" * 65)
    print("  PHASE 5: Saving outputs")
    print("─" * 65)

    combined.to_csv(OUTPUT_FILE, index=False)
    mb = Path(OUTPUT_FILE).stat().st_size / 1024 / 1024
    print(f"  {OUTPUT_FILE}: {len(combined):,} rows ({mb:.1f} MB)")

    new_idx = [
        {
            "player_name": p,
            "original_player_name": p,
            "tm_id": player_to_tmid[p],
            "sofascore_id": sofa_pid.get(p, ""),
            "match_method": tmid_source.get(p, "")
        }
        for p in players
        if p in player_to_tmid and (
            tmid_source.get(p, "").startswith("web_")
            or tmid_source.get(p, "").startswith("variant")
            or tmid_source.get(p, "").startswith("players:")
            or tmid_source.get(p, "").startswith("another:")
            or tmid_source.get(p, "") == "sofascore_id_bridge"
            or tmid_source.get(p, "") == "E_search_cache"
        )
    ]
    pd.DataFrame(new_idx).to_csv(NEW_INDEX_FILE, index=False)
    print(f"  {NEW_INDEX_FILE}: {len(new_idx):,} players")

    no_id = [
        {
            "player": p,
            "sofascore_id": sofa_pid.get(p, ""),
            "has_pos": p in pos_map,
            "has_born": p in born_map
        }
        for p in players if p not in player_to_tmid
    ]
    pd.DataFrame(no_id).to_csv(NO_TMID_FILE, index=False)
    print(f"  {NO_TMID_FILE}: {len(no_id):,} players")

    n_pos = (combined["player_positions"] != "").sum()
    n_born = combined["birth_year"].notna().sum()
    n_age = combined["age_in_season"].notna().sum()
    n_tmid = combined["tm_id"].notna().sum()
    total = len(combined)

    print(f"\n  {'Metric':<30} {'Rows':>8}  {'%':>6}")
    print(f"  {'-'*48}")
    print(f"  {'tm_id present':<30} {n_tmid:>8,}  {n_tmid/total*100:>5.1f}%")
    print(f"  {'player_positions':<30} {n_pos:>8,}  {n_pos/total*100:>5.1f}%")
    print(f"  {'birth_year':<30} {n_born:>8,}  {n_born/total*100:>5.1f}%")
    print(f"  {'age_in_season':<30} {n_age:>8,}  {n_age/total*100:>5.1f}%")

    if n_age:
        ages = combined["age_in_season"].dropna()
        print(f"\n  Age: min={int(ages.min())}, max={int(ages.max())}, mean={ages.mean():.1f}")

    pos_dist = Counter(
        p.strip()
        for v in combined["player_positions"].dropna()
        for p in str(v).split(",")
        if p.strip()
    )
    print("\n  Position distribution:")
    for pos, cnt in pos_dist.most_common():
        print(f"    {pos:<6} {cnt:>6,}")

    print(f"\n{'='*65}")
    print("Done.")


if __name__ == "__main__":
    main()