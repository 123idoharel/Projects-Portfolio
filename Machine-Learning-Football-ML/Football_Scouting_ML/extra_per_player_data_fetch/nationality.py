import pandas as pd
import os
import time
import random
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

# =====================================================================
# 1. הגדרות נתיבים ותצורה (קבצים נפרדים מהסקריפט הראשון!)
# =====================================================================
EXTRA_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXTRA_DIR.parent
# נתיב לקובץ ה-CSV שלך (אותו קובץ)
PREDICTIONS_FILE = PROJECT_ROOT / "data" / "processed" / "att_predictions" / "att_predictions_2425.csv"

# קבצי פלט וניהול נפרדים לריצה מקבילה!
OUTPUT_FILE = EXTRA_DIR / "citizenship_details.json"
STATE_FILE = PROJECT_ROOT / "images" / "tm_session_state_cit.json" 

# =====================================================================
# 2. לוגיקת הסריקה (Scraping)
# =====================================================================
def run_citizenship_fetcher():
    print("="*85)
    print("🌍 PLAYER CITIZENSHIP FETCH SYSTEM (Supports Multiple Countries)")
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
        
        # ספירת כמה שחקנים באמת סרוקים בהצלחה
        valid_count = sum(1 for data in details_db.values() if data.get("citizenships"))
        print(f"[*] Loaded existing DB. Valid players: {valid_count}/{len(details_db)}. Resuming...")

    with sync_playwright() as p:
        print("[*] Launching browser...")
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(storage_state=STATE_FILE if STATE_FILE.exists() else None)
        page = context.new_page()
        
        # חסימת משאבים כבדים לטעינה מהירה
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["media", "image", "font", "stylesheet"] else route.continue_())

        print(f"[*] Entering Transfermarkt...")
        try:
            page.goto("https://www.transfermarkt.com", wait_until="domcontentloaded", timeout=30000)
            
            # =================================================================
            # מנגנון טיפול ב-CAPTCHA - נותן 25 שניות ושומר את הסטטוס
            # =================================================================
            print("⏳ ממתין 25 שניות כדי לאפשר לך לפתור את ה-CAPTCHA ידנית (אם יש)...")
            page.wait_for_timeout(25000)
            
            context.storage_state(path=STATE_FILE)
            print("✅ שמרתי את הגישה (עבור אזרחויות), ממשיך בסריקה...")
            
        except Exception as e:
            print("[!] Initial load timeout, continuing anyway...")

        for i, tm_id in enumerate(player_ids, 1):
            # =========================================================
            # לוגיקת דילוג מתוקנת: קופץ רק אם יש נתון תקין ברשימה
            # =========================================================
            if tm_id in details_db:
                saved_data = details_db[tm_id]
                # מדלג רק אם המפתח קיים ויש בו לפחות מדינה אחת (הרשימה לא ריקה ולא None)
                if saved_data.get("citizenships"):
                    continue

            print(f"[{i}/{total_players}] TM_ID: {tm_id:7} | ", end="", flush=True)
            
            player_data = {"citizenships": []}
            
            try:
                url = f"https://www.transfermarkt.com/player/profil/spieler/{tm_id}"
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                
                # מציאת השדה של האזרחות
                cit_locator = page.locator("span:has-text('Citizenship:') + span")
                
                if cit_locator.count() > 0:
                    # הדרך האמינה ביותר: לשלוף את התארים (title) של תמונות הדגלים
                    flags = cit_locator.locator("img")
                    if flags.count() > 0:
                        countries = []
                        for flag_idx in range(flags.count()):
                            country_name = flags.nth(flag_idx).get_attribute("title")
                            if country_name:
                                countries.append(country_name.strip())
                        player_data["citizenships"] = countries
                    else:
                        # Fallback: אם אין דגלים, ננסה לקרוא את הטקסט ולפצל אותו
                        text = cit_locator.first.inner_text().strip()
                        if text and text != "N/A" and text != "-":
                            # מפצל לפי שורות או רווחים כפולים למקרה שיש כמה מדינות בטקסט
                            countries = [c.strip() for c in re.split(r'\n|\s{2,}', text) if c.strip()]
                            player_data["citizenships"] = countries

                details_db[tm_id] = player_data
                
                if player_data["citizenships"]:
                    print(f"✅ Found: {', '.join(player_data['citizenships'])}")
                else:
                    print("⚠️ No data found (Set as Empty List)")

            except Exception as e:
                print(f"❌ Error: {str(e)[:40]}")
                details_db[tm_id] = player_data # שמירה כרשימה ריקה למקרה של קריסה/חסימה כדי שינסה שוב אח"כ

            # השהייה אקראית מעט ארוכה יותר למניעת חסימה, במיוחד אם רץ במקביל
            time.sleep(random.uniform(1.8, 3.5))

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
    run_citizenship_fetcher()