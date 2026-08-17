import pandas as pd
import os
import time
import random
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

# =====================================================================
# 1. הגדרות נתיבים ותצורה
# =====================================================================
EXTRA_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXTRA_DIR.parent
PREDICTIONS_FILE = PROJECT_ROOT / "data" / "processed" / "att_predictions" / "att_predictions_2425.csv"
OUTPUT_FILE = EXTRA_DIR / "extra_details.json"
STATE_FILE = PROJECT_ROOT / "images" / "tm_session_state.json" # שימוש ב-Session הקיים

# =====================================================================
# 2. פונקציות ניקוי ועיבוד
# =====================================================================
def clean_height(raw_text):
    if not raw_text or "N/A" in raw_text: return None
    match = re.search(r'(\d+)[.,](\d+)', raw_text)
    return float(f"{match.group(1)}.{match.group(2)}") if match else None

def clean_foot(raw_text):
    if not raw_text or "N/A" in raw_text: return None
    text = raw_text.strip().lower()
    if 'right' in text: return 'Right'
    if 'left' in text: return 'Left'
    if 'both' in text: return 'Both'
    return raw_text.strip()

def clean_contract(raw_text):
    if not raw_text or "N/A" in raw_text or "-" in raw_text: return None
    return raw_text.strip()

# =====================================================================
# 3. לוגיקת הסריקה (Scraping)
# =====================================================================
def run_extra_details_fetcher():
    print("="*85)
    print("🔍 PLAYER EXTRA DETAILS FETCH SYSTEM (Height, Foot, Contract)")
    print("="*85)

    if not PREDICTIONS_FILE.exists():
        print(f"[!] Error: Predictions file not found at {PREDICTIONS_FILE}")
        return

    # טעינת המזהים
    df = pd.read_csv(PREDICTIONS_FILE)
    player_ids = df['tm_id'].dropna().astype(float).astype(int).astype(str).unique().tolist()
    total_players = len(player_ids)
    
    # טעינת בסיס נתונים קיים
    details_db = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            details_db = json.load(f)
        print(f"[*] Loaded existing DB with {len(details_db)} players. Skipping them...")

    with sync_playwright() as p:
        print("[*] Launching browser...")
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=STATE_FILE if STATE_FILE.exists() else None)
        page = context.new_page()
        
        # חסימת משאבים כבדים לטעינה מהירה
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["media", "image", "font", "stylesheet"] else route.continue_())


        print(f"[*] Entering Transfermarkt...")
        page.goto("https://www.transfermarkt.com", wait_until="domcontentloaded")
        
        # 1. נותן לך 25 שניות לפתור את ה-CAPTCHA ברוגע
        print("⏳ ממתין 25 שניות כדי לאפשר לך לפתור את ה-CAPTCHA ידנית...")
        page.wait_for_timeout(25000) 
        
        # 2. שומר את ה-Session מיד אחרי שפתרת! זה החלק החשוב כדי שהאתר יזכור אותך.
        context.storage_state(path=STATE_FILE)
        print("✅ שמרתי את הגישה, ממשיך בסריקה...")

        for i, tm_id in enumerate(player_ids, 1):
            # בודק אם השחקן קיים ב-DB
            if tm_id in details_db:
                saved_data = details_db[tm_id]
                # מוודא שלפחות אחד מהשדות מכיל מידע ממשי שאינו None
                if any(value is not None for value in saved_data.values()):
                    continue

            print(f"[{i}/{total_players}] TM_ID: {tm_id:7} | ", end="", flush=True)
            
            player_data = {"height": None, "foot": None, "contract_expiry": None}
            
            try:
                url = f"https://www.transfermarkt.com/player/profil/spieler/{tm_id}"
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                
                # שליפת נתונים באמצעות Selectors גמישים
                fields = {
                    "height": "span:has-text('Height:') + span",
                    "foot": "span:has-text('Foot:') + span",
                    "contract_expiry": "span:has-text('Contract expires:') + span"
                }
                
                results = []
                for key, selector in fields.items():
                    element = page.locator(selector)
                    if element.count() > 0:
                        raw_text = element.first.inner_text()
                        if key == "height": player_data[key] = clean_height(raw_text)
                        elif key == "foot": player_data[key] = clean_foot(raw_text)
                        elif key == "contract_expiry": player_data[key] = clean_contract(raw_text)
                        
                        if player_data[key]: results.append(key)
                
                details_db[tm_id] = player_data
                
                if results:
                    print(f"✅ Found: {', '.join(results)}")
                else:
                    print("⚠️ No data found (Set as NULL)")

            except Exception as e:
                print(f"❌ Error: {str(e)[:30]}")
                details_db[tm_id] = player_data # שמירה כריקים למקרה של קריסה

            # השהייה אקראית למניעת חסימה
            time.sleep(random.uniform(1.2, 2.8))

            # שמירה כל 25 שחקנים
            if i % 25 == 0:
                with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                    json.dump(details_db, f, indent=2)
                context.storage_state(path=STATE_FILE)

        # שמירה סופית
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(details_db, f, indent=2)
        
        print("\n" + "="*85)
        print(f"🏁 FINISHED! Total Players in DB: {len(details_db)}")
        print(f"📁 File saved at: {OUTPUT_FILE}")
        print("="*85)

if __name__ == "__main__":
    run_extra_details_fetcher()