"""
fix_bad_tm_data_v2.py
======================
Includes WAF Cookie bypass and better debugging prints.
"""

import pandas as pd
import requests
import re
import time
from unicodedata import normalize as unorm

INPUT_FILE = "sofascore_serbia_russian_leagues_combined.csv"
OUTPUT_FILE = "sofascore_serbia_russian_leagues_combined_FIXED.csv"
MIN_BIRTH_YEAR = 1985

BROWSER_COOKIES = {
    "aws-waf-token": "",
}

TM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_session = None

def get_session():
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(TM_HEADERS)
        for name, val in BROWSER_COOKIES.items():
            if val.strip():
                s.cookies.set(name, val.strip(), domain="www.transfermarkt.com")
        
        try:
            r = s.get("https://www.transfermarkt.com", timeout=15)
            if r.status_code in (403, 405, 429):
                print(f"\n *** WAF BLOCKED ({r.status_code}) — paste fresh aws-waf-token ***")
                tok = input(" aws-waf-token: ").strip()
                if tok:
                    s.cookies.set("aws-waf-token", tok, domain="www.transfermarkt.com")
                    BROWSER_COOKIES["aws-waf-token"] = tok
        except Exception:
            pass
        _session = s
    return _session

def handle_waf(r):
    """Check if blocked during a request and prompt for token."""
    if r.status_code in (403, 405, 429):
        print(f"\n [BLOCKED {r.status_code}!] Paste fresh aws-waf-token:")
        tok = input(" aws-waf-token: ").strip()
        if tok:
            session = get_session()
            session.cookies.set("aws-waf-token", tok, domain="www.transfermarkt.com")
            BROWSER_COOKIES["aws-waf-token"] = tok
            return True
    return False

def norm(s) -> str:
    if pd.isna(s) or s is None: return ""
    return unorm("NFKD", str(s).lower().strip()).encode("ascii", "ignore").decode().strip()

def char_sim(a: str, b: str, n: int = 3) -> float:
    a, b = norm(a), norm(b)
    if not a or not b: return 0.0
    ga = set(a[i:i + n] for i in range(len(a) - n + 1)) if len(a) >= n else {a}
    gb = set(b[i:i + n] for i in range(len(b) - n + 1)) if len(b) >= n else {b}
    if not ga or not gb: return 0.0
    return len(ga & gb) / max(len(ga), len(gb))

def sub_pos_to_fifa(raw: str) -> str:
    key = norm(raw)
    if "winger" in key: return "RW" if "right" in key else "LW" if "left" in key else "LW"
    if "wing-back" in key: return "RB" if "right" in key else "LB" if "left" in key else "LB"
    if "midfield" in key: return "RM" if "right" in key else "LM" if "left" in key else "CAM" if "attacking" in key else "CDM" if "defensive" in key else "CM"
    if "back" in key: return "RB" if "right" in key else "LB" if "left" in key else "CB"
    if "forward" in key or "striker" in key: return "ST"
    if "goalkeeper" in key: return "GK"
    return ""

def get_profile_data(tm_id, session):
    url = f"https://www.transfermarkt.com/x/profil/spieler/{tm_id}"
    try:
        time.sleep(1.5)
        r = session.get(url, timeout=15)
        if handle_waf(r): 
            r = session.get(url, timeout=15) # retry after token
            
        if r.status_code != 200: return None, None
        
        pos, by = "", None
        
        # --- חילוץ העמדה (עם גיבוי) ---
        m_pos = re.search(r'Position:\s*"\s*<span[^>]*class="[^"]*data-header__content[^"]*"[^>]*>\s*([^<]+?)\s*</span>', r.text, re.IGNORECASE)
        if not m_pos:
            m_pos = re.search(r'Position:\s*</span>\s*<span[^>]*>([^<]+)</span>', r.text, re.IGNORECASE)
        if m_pos: pos = sub_pos_to_fifa(m_pos.group(1).strip())
        
        # --- חילוץ שנת לידה (חסין תקלות!) ---
        # 1. ניסיון ראשון: התגית החדשה
        m_by = re.search(r'itemprop=["\']birthDate["\'][^>]*content=["\']([^"\']+)["\']', r.text)
        if m_by:
            m = re.search(r"\b(19\d{2}|20\d{2})\b", m_by.group(1))
            if m: by = int(m.group(1))
            
        # 2. גיבוי: הפורמט מהסקריפט המקורי שלך
        if by is None:
            m_fallback = re.search(r'Date of birth.*?(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2})\b', r.text, re.IGNORECASE | re.DOTALL)
            if m_fallback:
                m = re.search(r"\b(19\d{2}|20\d{2})\b", m_fallback.group(1))
                if m: by = int(m.group(1))
                
        # 3. גיבוי אגרסיבי אחרון: חיפוש 4 ספרות ליד המילה "birth"
        if by is None:
            m_aggro = re.search(r'Date of birth/Age:.*?(\b19\d{2}|\b20\d{2})\b', r.text, re.IGNORECASE | re.DOTALL)
            if m_aggro:
                by = int(m_aggro.group(1))
                
        return pos, by
    except Exception:
        return None, None

def strict_tm_search(player_name, session):
    nn = norm(player_name)
    url = "https://www.transfermarkt.com/schnellsuche/ergebnis/schnellsuche"
    
    try:
        time.sleep(2)
        r = session.get(url, params={"query": player_name, "Kat": "spieler"}, timeout=15)
        if handle_waf(r):
            r = session.get(url, params={"query": player_name, "Kat": "spieler"}, timeout=15)
            
        if r.status_code != 200: return None, None, None, f"HTTP {r.status_code}"
        
        entries = re.findall(r'href="/[^"]+/profil/spieler/(\d+)"[^>]*>\s*([^<]+)<', r.text)
        if not entries: return None, None, None, "No search results"
        
        reason = "Results found, but didn't match criteria"
        for tm_id, found_name in entries[:10]: # Increased to top 10
            sim = char_sim(nn, found_name)
            if sim >= 0.75:
                pos, birth_year = get_profile_data(tm_id, session)
                if birth_year is None:
                    reason = "Profile found, missing birth year"
                    continue
                if birth_year >= MIN_BIRTH_YEAR:
                    return tm_id, pos, birth_year, "OK"
                else:
                    reason = f"Found, but retired/too old (Born: {birth_year})"
                    
        return None, None, None, reason
    except requests.exceptions.Timeout:
        return None, None, None, "Timeout"
    except Exception as e:
        return None, None, None, f"Error: {e}"

def main():
    print("=" * 60)
    print(" 🛠️  TM DATA FIXER SCRIPT V2 (WITH WAF BYPASS)")
    print("=" * 60)

    try:
        df = pd.read_csv(INPUT_FILE, low_memory=False)
    except FileNotFoundError:
        print(f"Error: {INPUT_FILE} not found.")
        return

    print("\nScanning for bad data...")
    valid_tm_df = df[df['tm_id'].notna() & (df['tm_id'] != "")]
    id_counts = valid_tm_df.groupby('tm_id')['player'].nunique()
    duplicate_ids = id_counts[id_counts > 1].index.tolist()
    
    players_with_dupes = df[df['tm_id'].isin(duplicate_ids)]['player'].unique().tolist()
    players_too_old = df[df['birth_year'] < MIN_BIRTH_YEAR]['player'].unique().tolist()
    players_missing_id = df[df['tm_id'].isna() | (df['tm_id'] == "")]['player'].unique().tolist()
    
    players_to_fix = list(set(players_with_dupes + players_too_old + players_missing_id))
    
    print(f" 🚨 Duplicate ID issues: {len(players_with_dupes)} players")
    print(f" 👴 Too old (pre-{MIN_BIRTH_YEAR}): {len(players_too_old)} players")
    print(f" 👻 Missing IDs: {len(players_missing_id)} players")
    print(f" 🎯 TOTAL UNIQUE PLAYERS TO FIX: {len(players_to_fix)}")
    
    if not players_to_fix:
        print("\n✅ Data looks clean! No fixing needed.")
        return

    print("\nInitializing strict web search...")
    session = get_session()
    
    fixes_applied = 0
    updates_dict = {}

    for i, player in enumerate(players_to_fix, 1):
        print(f" [{i}/{len(players_to_fix)}] {player:<25} ... ", end="", flush=True)
        
        tm_id, pos, birth_year, reason = strict_tm_search(player, session)
        
        if tm_id:
            if pos == "goalkeeper": pos = "GK"
            updates_dict[player] = {
                'tm_id': tm_id,
                'player_positions': pos,
                'birth_year': birth_year
            }
            fixes_applied += 1
            print(f"✅ Found! ID: {tm_id}, Born: {birth_year}, Pos: {pos or 'GK'}")
        else:
            updates_dict[player] = {'tm_id': None, 'birth_year': None, 'player_positions': None}
            print(f"❌ Cleared ({reason})")

    print("\nApplying updates to the database...")
    for player, data in updates_dict.items():
        mask = df['player'] == player
        df.loc[mask, 'tm_id'] = data['tm_id']
        df.loc[mask, 'birth_year'] = data['birth_year']
        if 'player_positions' in data:
            df.loc[mask, 'player_positions'] = data['player_positions']

    def season_end_year(s):
        try:
            s = str(s).strip()
            if "/" in s:
                n = int(s.split("/")[-1].strip())
                return 2000 + n if n < 50 else 1900 + n
            yr = int(s)
            return yr if 1990 < yr < 2030 else None
        except: return None

    df["_end_yr"] = df["_season_year"].apply(season_end_year)
    df["age_in_season"] = (df["_end_yr"] - df["birth_year"])
    df.drop(columns=["_end_yr"], inplace=True)

    print("Mapping remaining empty positions to 'GK'...")
    mask_empty_pos = (df['player_positions'].isna() | (df['player_positions'] == ""))
    mask_has_id = df['tm_id'].notna() & (df['tm_id'] != "")
    df.loc[mask_empty_pos & mask_has_id, 'player_positions'] = "GK"

    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n🎉 DONE! Fixed {fixes_applied} profiles.")
    print(f"Saved cleaned data to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()