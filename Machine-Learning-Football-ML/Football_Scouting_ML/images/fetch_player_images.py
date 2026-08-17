import pandas as pd
import os
import time
import random
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

# =====================================================================
# 1. הגדרות נתיבים ותצורה
# =====================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PREDICTIONS_FILE = PROJECT_ROOT / "data" / "processed" / "att_predictions" / "att_predictions_2425.csv"
OUTPUT_DIR = SCRIPT_DIR / "player_photos"
STATE_FILE = SCRIPT_DIR / "tm_session_state.json" # תיקון: שימוש ב-SCRIPT_DIR

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =====================================================================
# 2. פונקציות עזר
# =====================================================================
def is_real_image(response):
    """בודק אם ה-Response מכיל פורמט תמונה תקין"""
    content_type = response.headers.get('Content-Type', '')
    return 'image' in content_type.lower()

def download_image(url, save_path):
    """מוריד את התמונה מה-URL ושומר אותה רק אם היא תקינה"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        
        # בדיקה שהבקשה הצליחה ושהתוכן הוא אכן תמונה
        if resp.status_code == 200 and is_real_image(resp):
            if len(resp.content) > 500: # הגנה נוספת: תמונה אמיתית שוקלת יותר מ-500 בתים
                with open(save_path, 'wb') as handler:
                    handler.write(resp.content)
                return True
        return False
    except Exception as e:
        print(f"      [!] Download Error: {e}")
        return False

def run_image_fetcher():
    print("="*75)
    print("⚽ TRANSFERMARKT PLAYER IMAGE FETCH SYSTEM (STRICT MODE)")
    print("="*75)

    if not PREDICTIONS_FILE.exists():
        print(f"[!] Error: Predictions file not found at {PREDICTIONS_FILE}")
        return

    # טעינה עם טיפול מפורש ב-ID כדי למנוע את בעיית ה-1069512.0
    df = pd.read_csv(PREDICTIONS_FILE)
    # המרה בטוחה: מכל פורמט ל-Float (למקרה שיש NaNs), אז ל-Int, ואז ל-String
    player_ids = df['tm_id'].dropna().astype(float).astype(int).astype(str).unique().tolist()
    total_players = len(player_ids)
    
    print(f"[*] Found {total_players} players to process.")
    
    with sync_playwright() as p:
        print("[*] Launching browser...")
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        
        context = browser.new_context(storage_state=STATE_FILE if STATE_FILE.exists() else None)
        page = context.new_page()
        
        # אופטימיזציה: חוסמים פונטים ותמונות רקע (אבל משאירים תמונות כדי שה-Selector יעבוד)
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["media", "font", "stylesheet"] else route.continue_())

        print(f"[*] Warmup on Transfermarkt...")
        page.goto("https://www.transfermarkt.com", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        success_count = 0
        fail_count = 0
        skip_count = 0

        for i, tm_id in enumerate(player_ids, 1):
            save_path = OUTPUT_DIR / f"{tm_id}.jpg"

            if save_path.exists():
                skip_count += 1
                continue

            print(f"[{i}/{total_players}] TM_ID: {tm_id:7} | ", end="", flush=True)

            try:
                url = f"https://www.transfermarkt.com/player/profil/spieler/{tm_id}"
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                
                # איתור ה-Selector (נלקח מהמבנה החדש של Transfermarkt)
                img_element = page.query_selector("div.data-header__profile-container img")
                
                if img_element:
                    img_url = img_element.get_attribute("src")
                    # ניקוי פרמטרים של Crop/Size
                    clean_url = img_url.split('?')[0] if img_url else None
                    
                    # בדיקה שהתמונה אינה תמונת Placeholder גנרית (למשל תמונת צללית)
                    if clean_url and "portrait" in clean_url and "placeholder" not in clean_url.lower():
                        if download_image(clean_url, save_path):
                            print("✅ Saved.")
                            success_count += 1
                        else:
                            print("❌ Invalid content returned.")
                            fail_count += 1
                    else:
                        print("⚠️ No valid portrait found (likely placeholder).")
                        fail_count += 1
                else:
                    print("❌ Profile image selector not found.")
                    fail_count += 1

            except Exception as e:
                print(f"❌ Error: {str(e)[:40]}")
                fail_count += 1

            # השהייה אקראית למניעת חסימה
            time.sleep(random.uniform(1.5, 3.0))

            if i % 25 == 0:
                context.storage_state(path=STATE_FILE)

        context.storage_state(path=STATE_FILE) # שמירה בסוף הריצה
        print("\n" + "="*75)
        print(f"🏁 FINISHED")
        print(f"   - Success: {success_count}")
        print(f"   - Failed:  {fail_count}")
        print(f"   - Skipped: {skip_count}")
        print(f"📁 Images folder: {OUTPUT_DIR}")
        print("="*75)

if __name__ == "__main__":
    run_image_fetcher()