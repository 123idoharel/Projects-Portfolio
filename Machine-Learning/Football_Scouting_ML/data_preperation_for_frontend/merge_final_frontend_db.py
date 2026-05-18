import sys
import os
import json
from pathlib import Path

# =====================================================================
# 1. Path configuration
# =====================================================================
CURRENT_DIR = Path(__file__).resolve().parent
if 'football_scouting_project' in CURRENT_DIR.parts:
    root_idx = CURRENT_DIR.parts.index('football_scouting_project')
    PROJECT_ROOT = Path(*CURRENT_DIR.parts[:root_idx + 1])
else:
    PROJECT_ROOT = CURRENT_DIR.parent

FRONTEND_DIR        = PROJECT_ROOT / "frontend_data"
EXTRA_DIR           = PROJECT_ROOT / "extra_per_player_data_fetch"
IMAGES_DIR          = PROJECT_ROOT / "web_system" / "player_images"
WEB_SYSTEM_DIR      = PROJECT_ROOT / "web_system"

CORE_DB_FILE        = FRONTEND_DIR / "core_players_db.json"
EXTRA_DB_FILE       = EXTRA_DIR / "extra_details.json"
CITIZENSHIP_DB_FILE = EXTRA_DIR / "citizenship_details.json"
FINAL_OUT_FILE      = FRONTEND_DIR / "final_players_db.json"
# Second copy written next to server.py so the running server picks it up directly.
WEB_SYSTEM_OUT_FILE = WEB_SYSTEM_DIR / "final_players_db.json"

# Fields that count as "real" data when checking whether the scrape succeeded.
EXTRA_REAL_FIELDS = ("height", "foot", "contract_expiry")


# =====================================================================
# 2. Helpers
# =====================================================================
def has_real_extra(rec: dict) -> bool:
    """True if the extra_details record contains at least one non-null field."""
    return any(rec.get(k) not in (None, "", [], {}) for k in EXTRA_REAL_FIELDS)


def has_real_citizenship(rec: dict) -> bool:
    """True if the citizenship record contains at least one country."""
    cits = rec.get("citizenships")
    return bool(cits) and len(cits) > 0


def dedupe_preserve_order(seq):
    """Remove duplicates while keeping first-seen order."""
    seen = set()
    out = []
    for x in seq or []:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def key_overlap_check(name_a: str, dict_a: dict, name_b: str, dict_b: dict):
    """Sanity-check key overlap between two dicts; warn loudly on zero overlap."""
    if not dict_a or not dict_b:
        return
    overlap = len(set(dict_a.keys()) & set(dict_b.keys()))
    smaller = min(len(dict_a), len(dict_b))
    pct = (overlap / smaller * 100) if smaller else 0
    print(f"    ✓ Key overlap {name_a} ∩ {name_b}: {overlap:,} / {smaller:,} ({pct:.1f}%)")
    if overlap == 0:
        # zero overlap is almost always a key-format bug (str vs int)
        sample_a = next(iter(dict_a.keys()))
        sample_b = next(iter(dict_b.keys()))
        raise RuntimeError(
            f"Zero key overlap between {name_a} and {name_b}. "
            f"Sample {name_a} key: {sample_a!r} ({type(sample_a).__name__}); "
            f"sample {name_b} key: {sample_b!r} ({type(sample_b).__name__}). "
            f"Likely a string-vs-int key mismatch upstream."
        )


# =====================================================================
# 3. Merge function
# =====================================================================
def merge_final_database():
    print("=" * 80)
    print("🧬 STAGE 9: THE GRAND MERGE (CORE + EXTRA + CITIZENSHIPS + PHOTOS)")
    print("=" * 80)

    # ---- 1. Load Core DB ----
    print(f"[*] Loading Core DB: {CORE_DB_FILE.name}...")
    try:
        with open(CORE_DB_FILE, 'r', encoding='utf-8') as f:
            core_db = json.load(f)
        print(f"    ✓ Loaded {len(core_db):,} players from Core.")
    except Exception as e:
        print(f"[!] Error loading Core DB: {e}")
        return

    # ---- 2. Load extra details (height/foot/contract) ----
    print(f"[*] Loading Extra Details: {EXTRA_DB_FILE.name}...")
    try:
        with open(EXTRA_DB_FILE, 'r', encoding='utf-8') as f:
            extra_db = json.load(f)
        print(f"    ✓ Loaded {len(extra_db):,} records from Extra Details.")
    except Exception as e:
        print(f"    [!] Extra Details file not found. Error: {e}")
        extra_db = {}

    # ---- 3. Load citizenship data ----
    print(f"[*] Loading Citizenship Details: {CITIZENSHIP_DB_FILE.name}...")
    try:
        with open(CITIZENSHIP_DB_FILE, 'r', encoding='utf-8') as f:
            citizenship_db = json.load(f)
        print(f"    ✓ Loaded {len(citizenship_db):,} records from Citizenship Details.")
    except Exception as e:
        print(f"    [!] Citizenship file not found. Error: {e}")
        citizenship_db = {}

    # ---- 4. Pre-flight sanity checks ----
    print("\n[*] Pre-flight sanity checks...")
    key_overlap_check("core", core_db, "extra", extra_db)
    key_overlap_check("core", core_db, "citizenship", citizenship_db)

    # Pre-list available image files once instead of stat()-ing per player
    if IMAGES_DIR.exists():
        existing_images = {p.stem for p in IMAGES_DIR.glob("*.jpg")}
        print(f"    ✓ Image directory: {len(existing_images):,} jpg files in {IMAGES_DIR}")
    else:
        existing_images = set()
        print(f"    [!] Image directory not found at {IMAGES_DIR} — has_photo will be False for all.")

    # ---- 5. Main merge loop ----
    print("\n[*] Merging all datasets...")
    stats = {
        "extra_present":       0,  # tm_id exists in extra_db (any value, even all-null)
        "extra_real_data":     0,  # tm_id exists AND has at least one non-null field
        "citizenship_present": 0,
        "citizenship_real":    0,
        "photos_found":        0,
        "photos_missing":      0,
    }

    for tm_id, player_data in core_db.items():
        extra_info = extra_db.get(tm_id, {})
        cit_info   = citizenship_db.get(tm_id, {})

        if extra_info:
            stats["extra_present"] += 1
            if has_real_extra(extra_info):
                stats["extra_real_data"] += 1

        if cit_info:
            stats["citizenship_present"] += 1
            if has_real_citizenship(cit_info):
                stats["citizenship_real"] += 1

        # Image existence — using the pre-loaded set for speed
        has_photo = tm_id in existing_images
        if has_photo:
            stats["photos_found"] += 1
        else:
            stats["photos_missing"] += 1

        # Inject metadata. Missing fields stay as None / [] — the frontend
        # short-circuits with `&&` so chips for empty fields just don't render.
        player_data['metadata']['height']          = extra_info.get('height')
        player_data['metadata']['foot']            = extra_info.get('foot')
        player_data['metadata']['contract_expiry'] = extra_info.get('contract_expiry')
        player_data['metadata']['citizenships']    = dedupe_preserve_order(
            cit_info.get('citizenships', [])
        )
        player_data['metadata']['has_photo']       = has_photo

    # ---- 6. Save final file (minified) ----
    print(f"\n[*] Saving Final Database to: {FINAL_OUT_FILE.name}...")
    FINAL_OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(FINAL_OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(core_db, f, ensure_ascii=False, separators=(',', ':'))

    # Also write a copy next to server.py so the running server picks it up directly.
    if WEB_SYSTEM_DIR.exists():
        print(f"[*] Mirroring to web_system: {WEB_SYSTEM_OUT_FILE}")
        with open(WEB_SYSTEM_OUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(core_db, f, ensure_ascii=False, separators=(',', ':'))
    else:
        print(f"    [!] web_system directory not found at {WEB_SYSTEM_DIR} — skipping mirror copy.")

    # ---- 7. Validate the file we just wrote ----
    print("[*] Validating final JSON...")
    try:
        with open(FINAL_OUT_FILE, 'r', encoding='utf-8') as f:
            reloaded = json.load(f)
        if len(reloaded) != len(core_db):
            raise ValueError(f"Reload count mismatch: wrote {len(core_db)}, read {len(reloaded)}")
        # Spot-check a few records to make sure nothing weird (NaN-as-string, etc.) snuck in
        sample_ids = list(reloaded.keys())[:3]
        for sid in sample_ids:
            md = reloaded[sid].get('metadata', {})
            if md.get('tm_id') is None:
                raise ValueError(f"Player {sid} has no tm_id in metadata")
        print(f"    ✓ Validated: {len(reloaded):,} players, JSON parses cleanly.")
    except Exception as e:
        print(f"    [!] VALIDATION FAILED: {e}")
        return

    # ---- 8. Summary report ----
    try:
        file_size_mb = os.path.getsize(FINAL_OUT_FILE) / (1024 * 1024)
    except Exception:
        file_size_mb = 0

    total = len(core_db)
    print("\n" + "=" * 80)
    print("🏆 FINAL GRAND MERGE COMPLETE!")
    print("=" * 80)
    print(f"✅ Total Players in Final DB:     {total:,}")
    print()
    print(f"🧬 Extra Details (height/foot/contract):")
    print(f"     records present in extra_db: {stats['extra_present']:,}  ({stats['extra_present']/total*100:.1f}%)")
    print(f"     records with real data:      {stats['extra_real_data']:,}  ({stats['extra_real_data']/total*100:.1f}%)")
    print()
    print(f"🌍 Citizenships:")
    print(f"     records present:             {stats['citizenship_present']:,}  ({stats['citizenship_present']/total*100:.1f}%)")
    print(f"     records with ≥1 country:     {stats['citizenship_real']:,}  ({stats['citizenship_real']/total*100:.1f}%)")
    print()
    print(f"📸 Player Photos:")
    print(f"     found:                       {stats['photos_found']:,}  ({stats['photos_found']/total*100:.1f}%)")
    print(f"     missing:                     {stats['photos_missing']:,}  ({stats['photos_missing']/total*100:.1f}%)")
    print("-" * 80)
    print(f"📁 Output File: {FINAL_OUT_FILE}")
    print(f"💾 Minified File Size: {file_size_mb:.2f} MB")
    print("=" * 80)
    print("🚀 THE BACKEND DATA IS 100% READY FOR THE FRONTEND!")


if __name__ == '__main__':
    merge_final_database()