import pandas as pd
import numpy as np
from datetime import datetime
import os
import sys
import time
import json
import random
from pathlib import Path
from playwright.sync_api import sync_playwright

# =====================================================================
# 1. FILE CONFIGURATION
# =====================================================================
DB_FILE = "FINAL_DATABASE_POST_1983.csv"
CACHE_FILE = "player_valuations.csv"
OUTPUT_FILE = "player_valuations_ALL_FINAL.csv"
FAILED_FILE = "failed_valuations.csv"
STATE_FILE = "tm_session_state.json"
CACHE_DIR = Path("tm_output/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# =====================================================================
# 2. PLAYWRIGHT API FETCHING (DIRECT API FETCH - MAX SPEED)
# =====================================================================
def fetch_ceapi_pw(page, tm_id, retries=3):
    """Fetches history using direct API calls within the trusted browser context."""
    cache = CACHE_DIR / f"v_{tm_id}.json"
    if cache.exists():
        try:
            data = json.load(open(cache))
            if data: return data
        except: pass
        cache.unlink()

    ceapi_url = f"https://www.transfermarkt.com/ceapi/marketValueDevelopment/graph/{tm_id}"

    for attempt in range(1, retries + 1):
        try:
            # 🛡️ Anti-Ban Delay: זמנים אקראיים כדי להיראות אנושיים ולהימנע מחסימה
            time.sleep(random.uniform(0.5, 1.1)) 
            
            # משיכה ישירה מתוך הקונטקסט של הדפדפן ללא טעינת דף HTML
            json_data = page.evaluate(f'''
                async () => {{
                    const response = await fetch("{ceapi_url}", {{
                        headers: {{
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json",
                            "Referer": "https://www.transfermarkt.com/x/profil/spieler/{tm_id}"
                        }}
                    }});
                    if (response.status === 429) return "RATE_LIMIT";
                    if (!response.ok) return null;
                    return await response.json();
                }}
            ''')

            if json_data == "RATE_LIMIT":
                print(" [Rate Limit Hit - Waiting 30s...] ", end="", flush=True)
                time.sleep(30 * attempt)
                continue

            if not json_data:
                return []

            # Extract logic
            raw_list = json_data.get("list", [])
            rows = []
            for item in raw_list:
                val  = item.get("y")
                date = item.get("datum_mw")
                
                if date is None and item.get("x") is not None:
                    try: date = datetime.fromtimestamp(item["x"] / 1000).strftime("%d/%m/%Y")
                    except: pass
                
                if val is None or date is None: continue
                
                try:
                    rows.append({
                        "date": str(date),
                        "market_value_in_eur": int(val),
                        "current_club_name": str(item.get("verein", "")),
                    })
                except: continue
            
            if rows:
                with open(cache, "w") as f:
                    json.dump(rows, f)
            return rows
            
        except Exception as e:
            if attempt < retries: time.sleep(10 * attempt)
            else: raise Exception(f"Browser Fetch Error: {str(e)}")
            
    return []

# =====================================================================
# 3. CORE SYNC LOGIC
# =====================================================================
def get_explicit_season_range(season_str):
    s = str(season_str).strip()
    try:
        if '/' in s: 
            parts = s.split('/')
            year_start = int("20" + parts[0]) if len(parts[0]) == 2 else int(parts[0])
            return datetime(year_start, 7, 1), datetime(year_start + 1, 6, 30)
        else: 
            year = int(float(s))
            return datetime(year, 1, 1), datetime(year, 12, 31)
    except:
        return None, None

def run_master_sync():
    is_sample = len(sys.argv) > 1 and sys.argv[1].upper() == "SAMPLE"
    
    print(f"📂 Loading Main Database: {DB_FILE}...")
    df_db = pd.read_csv(DB_FILE, low_memory=False)
    
    df_db['tm_id'] = pd.to_numeric(df_db['tm_id'], errors='coerce').fillna(-1).astype(int).astype(str)
    df_db = df_db[df_db['tm_id'] != '-1'] 
    
    id_col_in_db = 'player id' if 'player id' in df_db.columns else 'sofa_id'
    df_db['sofa_clean'] = df_db[id_col_in_db].astype(str).str.split('.').str[0]
    id_map = df_db.drop_duplicates('tm_id').set_index('tm_id')['sofa_clean'].to_dict()
    name_map = df_db.drop_duplicates('tm_id').set_index('tm_id')['player'].to_dict()
    
    season_col = '_season_year' if '_season_year' in df_db.columns else 'season'
    player_seasons_map = df_db.groupby('tm_id')[season_col].unique().to_dict()
    
    if is_sample:
        print("🧪 SAMPLE mode active: Processing 50 players...")
        sample_keys = list(player_seasons_map.keys())[:50]
        player_seasons_map = {k: player_seasons_map[k] for k in sample_keys}

    if os.path.exists(CACHE_FILE):
        print(f"📦 Loading Cache file: {CACHE_FILE}...")
        df_cache = pd.read_csv(CACHE_FILE, low_memory=False)
        df_cache['date'] = pd.to_datetime(df_cache['date'], dayfirst=True, errors='coerce')
        df_cache['player_id'] = pd.to_numeric(df_cache['player_id'], errors='coerce').fillna(-1).astype(int).astype(str)
        
        val_col_candidates = ['market_value', 'market_value_in_eur', 'value', 'marketValue']
        found_val_col = next((col for col in val_col_candidates if col in df_cache.columns), None)
        if found_val_col and found_val_col != 'market_value':
            print(f"✅ Mapped Cache column '{found_val_col}' to 'market_value'.")
            df_cache.rename(columns={found_val_col: 'market_value'}, inplace=True)
    else:
        print(f"⚠️ {CACHE_FILE} not found. Starting fresh.")
        df_cache = pd.DataFrame(columns=['player_id', 'date', 'market_value'])

    all_valid_valuations = []
    failed_players = []
    count_cache = count_web = count_failed = 0
    total_to_process = len(player_seasons_map)
    
    print(f"\n🚀 Starting processing for {total_to_process:,} players...")
    print("-" * 65)

    with sync_playwright() as p:
        print("🛡️ Launching Fast VISIBLE Browser...")
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        
        if os.path.exists(STATE_FILE):
            print("💾 Found saved session state! Using fast 3-second warmup...")
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                storage_state=STATE_FILE
            )
            warmup_wait = 3000
        else:
            print("🆕 First time running! Creating new session profile...")
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )
            warmup_wait = 30000

        page = context.new_page()
        
        # ⚡ SPEED OPTIMIZATION: Block heavy resources
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font", "stylesheet"] else route.continue_())
        
        try:
            if warmup_wait == 30000:
                print("⏳ ACTION REQUIRED: You have 30 seconds to click 'Begin' and solve the human CAPTCHA if it appears on screen!")
            
            # Park the browser on the homepage
            page.goto("https://www.transfermarkt.com", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(warmup_wait)
            
            context.storage_state(path=STATE_FILE)
            if warmup_wait == 30000:
                print("✅ Session saved! Future runs will only wait 3 seconds.")
        except Exception as e:
            print(f"⚠️ Warning during warmup: {e}")

        for i, (tm_id, seasons) in enumerate(player_seasons_map.items(), 1):
            sofa_id = id_map.get(tm_id)
            player_name = name_map.get(tm_id, "Unknown Player")
            
            if is_sample: 
                print(f"[{i:02d}/{total_to_process}] {player_name[:22]:<22} (TM: {tm_id:<7}) | ", end="", flush=True)
            
            player_in_cache = df_cache[df_cache['player_id'] == tm_id].copy()
            is_fully_covered = True
            
            if player_in_cache.empty: 
                is_fully_covered = False
            else:
                for s in seasons:
                    start_dt, end_dt = get_explicit_season_range(s)
                    if not start_dt: continue
                    match = player_in_cache[(player_in_cache['date'] >= start_dt) & (player_in_cache['date'] <= end_dt)]
                    if match.empty:
                        is_fully_covered = False
                        break
            
            current_player_df = pd.DataFrame()
            fail_reason = None

            if is_fully_covered:
                current_player_df = player_in_cache
                count_cache += 1
                if is_sample: print("✅ Fully loaded from Cache")
            else:
                if is_sample: print("🌐 Fetching via Direct API... ", end="", flush=True)
                try:
                    # DIRECT API FETCH - NO PAGE LOAD!
                    web_data = fetch_ceapi_pw(page, tm_id)
                    
                    if web_data and len(web_data) > 0:
                        current_player_df = pd.DataFrame(web_data)
                        current_player_df['date'] = pd.to_datetime(current_player_df['date'], dayfirst=True)
                        current_player_df['player_id'] = tm_id
                        if 'market_value_in_eur' in current_player_df.columns:
                            current_player_df.rename(columns={'market_value_in_eur': 'market_value'}, inplace=True)
                        count_web += 1
                        if is_sample: print("✅ Success!")
                    else:
                        fail_reason = 'No valuation data exists on Transfermarkt'
                except Exception as e:
                    fail_reason = str(e)

                if fail_reason:
                    failed_players.append({'player_name': player_name, 'sofa_id': sofa_id, 'tm_id': tm_id, 'reason': fail_reason})
                    count_failed += 1
                    if is_sample: print(f"❌ FAILED ({fail_reason})")

            if not current_player_df.empty:
                current_player_df['player_name'] = player_name
                current_player_df['sofa_id'] = sofa_id
                current_player_df['tm_id'] = tm_id
                if 'market_value' in current_player_df.columns:
                    all_valid_valuations.append(current_player_df[['player_name', 'sofa_id', 'tm_id', 'date', 'market_value']])
                else:
                    reason = 'market_value missing after fetch'
                    failed_players.append({'player_name': player_name, 'sofa_id': sofa_id, 'tm_id': tm_id, 'reason': reason})
                    count_failed += 1

            # INTERIM SAVE & FEEDBACK - כל 100 שחקנים
            if not is_sample and i % 100 == 0:
                print(f"⏳ Progress: {i}/{total_to_process} | Cache: {count_cache} | Web: {count_web} | Failed: {count_failed}")
                pd.concat(all_valid_valuations, ignore_index=True).to_csv(OUTPUT_FILE, index=False)
                pd.DataFrame(failed_players).to_csv(FAILED_FILE, index=False)

    print("-" * 65)
    total_rows_saved = 0
    if all_valid_valuations:
        df_final = pd.concat(all_valid_valuations, ignore_index=True)
        df_final.sort_values(by=['player_name', 'date'], inplace=True)
        df_final.to_csv(OUTPUT_FILE, index=False)
        total_rows_saved = len(df_final)
    
    if failed_players:
        pd.DataFrame(failed_players).to_csv(FAILED_FILE, index=False)

    print("\n=======================================================")
    print("  📊 FINAL SYNC SUMMARY")
    print("=======================================================")
    print(f"  👥 Total Unique Players Processed : {total_to_process:,}")
    print(f"  ✅ Succeeded from Cache           : {count_cache:,}")
    print(f"  🌐 Succeeded from Web (Fetched)   : {count_web:,}")
    print(f"  ❌ Failed / No Data Found         : {count_failed:,}")
    print("-------------------------------------------------------")
    print(f"  📈 Total Valuation Rows Saved     : {total_rows_saved:,}")
    print(f"  💾 Main Output File               : {OUTPUT_FILE}")
    if failed_players:
        print("=======================================================")
        for fp in failed_players[:15]:
            print(f"  ▪ {fp['player_name'][:22]:<22} (TM: {fp['tm_id']:<7}) -> {fp['reason']}")
        if len(failed_players) > 15:
            print(f"  ... and {len(failed_players) - 15} more. Check {FAILED_FILE}.")
    print("=======================================================\n")

if __name__ == "__main__":
    run_master_sync()