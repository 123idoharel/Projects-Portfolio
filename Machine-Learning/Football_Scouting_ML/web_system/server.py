#!/usr/bin/env python3
"""
SCOUT ML — FastAPI Backend
─────────────────────────────────────────────────────────────────────────────
Loads the full player JSON once into RAM on startup.
All filtering and sorting happens in-memory (fast for ~5k players).
The frontend only ever downloads the slice it needs.

Usage:
    python server.py                          # uses final_players_db.json
    DATA_PATH=my_data.json python server.py
    python server.py --data my_data.json --images ./photos --port 8000
"""

import argparse
import json
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

# ── FastAPI imports ───────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, Query, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except ImportError:
    print("Missing dependencies. Run:  pip install fastapi uvicorn[standard]")
    sys.exit(1)

# ── CLI args ──────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Scout ML API server")
parser.add_argument("--data",   default=os.getenv("DATA_PATH",   "final_players_db.json"), help="Path to player JSON file")
parser.add_argument("--images", default=os.getenv("IMAGES_DIR",  "player_images"),         help="Path to player images directory")
parser.add_argument("--port",   default=int(os.getenv("PORT", 8000)), type=int,             help="Port to listen on")
parser.add_argument("--host",   default="0.0.0.0",                                          help="Host to bind to")
args, _ = parser.parse_known_args()

DATA_PATH  = Path(args.data)
IMAGES_DIR = Path(args.images)

# ── Load data for all pitch areas ─────────────────────────────────────────────
# Attack's JSON is the primary one (specified via --data, defaults to
# final_players_db.json). Other areas (midfield, defense, gk) are discovered
# automatically from sibling files named final_players_db_<area>.json in the
# same directory as the primary file. Each area is normalized and held in
# memory in DB_BY_AREA so the API can serve any area via ?area=<id>.
print(f"[Scout ML] Loading primary data: {DATA_PATH} ...", flush=True)
if not DATA_PATH.exists():
    print(f"[Scout ML] ERROR: {DATA_PATH} not found. Set --data or DATA_PATH env var.")
    sys.exit(1)

def _load_raw_entries(path: Path) -> list:
    """Read a player JSON file and return the raw entries as a list."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return list(raw.values()) if isinstance(raw, dict) else raw

RAW_BY_AREA: dict = {"attack": _load_raw_entries(DATA_PATH)}

# Discover sibling area files
_data_dir = DATA_PATH.parent
for area_id in ("midfield", "defense", "gk"):
    candidate = _data_dir / f"final_players_db_{area_id}.json"
    if candidate.exists():
        try:
            RAW_BY_AREA[area_id] = _load_raw_entries(candidate)
            print(f"[Scout ML] Discovered {area_id}: {candidate} ({len(RAW_BY_AREA[area_id])} raw entries)", flush=True)
        except Exception as e:
            print(f"[Scout ML] Skipping {candidate}: {e}", flush=True)

# ── Normalize player ──────────────────────────────────────────────────────────
def map_model(x: Optional[dict]) -> Optional[dict]:
    if not x:
        return None
    return {
        "base":    x.get("expected_eur"),
        "opt":     x.get("optimistic_eur"),
        "opt_q75": x.get("optimistic_q75_eur"),
        "pes":     x.get("pessimistic_eur"),
        "upside":  x.get("upside_multiple"),
        "risk":    x.get("risk_score"),
    }

def normalize(raw: dict) -> Optional[dict]:
    m   = raw.get("metadata", {})
    mdl = raw.get("models", {})
    if not m.get("tm_id"):
        return None
    # Skip entries with no name. These are tm_ids whose Transfermarkt
    # profile-page scrape returned models + value but no descriptive
    # metadata. Showing them as a sea of "?" rows is noise; skip at load.
    name = m.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        return None

    history = sorted(
        raw.get("history_data", []),
        key=lambda s: s.get("_season_year", ""),
        reverse=True,
    )

    return {
        "id":                m.get("tm_id"),
        "sofascore_id":      m.get("sofascore_id"),
        "name":              name,
        "age":               m.get("age_at_cutoff", 0),
        "position":          m.get("primary_position", "?"),
        "secondaryPosition": m.get("secondary_position"),
        "club":              m.get("current_team", "?"),
        "league":            m.get("current_league", "?"),
        "valueEur":          m.get("current_value_eur", 0),
        "height":            m.get("height"),
        "foot":              m.get("foot"),
        "contractExpiry":    m.get("contract_expiry"),
        "citizenships":      m.get("citizenships", []),
        "has_photo":         m.get("has_photo", False),
        "predictions": {
            "peak":    map_model(mdl.get("peak_potential")),
            "next1yr": map_model(mdl.get("horizon_1y")),
            "next2yr": map_model(mdl.get("horizon_2y")),
        },
        "history":       history,
        "advancedStats": raw.get("advanced_stats", {}),
    }

# Normalize each area's raw entries, keep skip counts for the boot summary
DB_BY_AREA: dict = {}
SKIP_BY_AREA: dict = {}
for area_id, entries in RAW_BY_AREA.items():
    normalized = [p for p in (normalize(e) for e in entries) if p]
    DB_BY_AREA[area_id]   = normalized
    SKIP_BY_AREA[area_id] = len(entries) - len(normalized)

# Boot summary — one line per area for terminal visibility
print(f"\n[Scout ML] Per-area summary:", flush=True)
for area_id, players in DB_BY_AREA.items():
    raw_n = len(RAW_BY_AREA[area_id])
    skipped = SKIP_BY_AREA[area_id]
    print(f"  {area_id:<10} {len(players):>6,} loaded · {skipped:>5,} skipped (no name) · {raw_n:>6,} raw", flush=True)
print("", flush=True)

# Back-compat alias: a lot of older API code references PLAYERS directly,
# meaning the attack roster. Keep that pointing at attack so we don't have
# to rewire every reference.
PLAYERS: List[dict] = DB_BY_AREA["attack"]

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Scout ML API",
    description="Football intelligence platform backend",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── /api/meta — filter options + data ranges ──────────────────────────────────
@lru_cache(maxsize=8)
def _build_meta(area: str = "attack") -> dict:
    roster = DB_BY_AREA.get(area, [])
    positions     = sorted({p["position"] for p in roster if p["position"] and p["position"] != "?"})
    leagues       = sorted({p["league"]   for p in roster if p["league"]   and p["league"]   != "?"})
    nationalities = sorted({c for p in roster for c in (p.get("citizenships") or [])})
    values        = [p["valueEur"] for p in roster if p["valueEur"]]
    peaks         = [p["predictions"]["peak"]["base"]
                     for p in roster
                     if (p["predictions"].get("peak") or {}).get("base")]
    ages          = [p["age"] for p in roster if p["age"]]
    teams_by_league: dict = {}
    for p in roster:
        lg = p.get("league")
        tm = p.get("club")
        if lg and lg != "?" and tm and tm != "?":
            teams_by_league.setdefault(lg, set()).add(tm)
    teams_by_league = {lg: sorted(s) for lg, s in teams_by_league.items()}
    # Data-driven reference scale for optimistic shrinkage. Only used by
    # the Attack area; other areas don't apply shrinkage. Still computed
    # per-area for completeness so a future area-specific tuning is easy.
    opt_ref = 50e6
    if peaks:
        sp = sorted(peaks)
        p95 = sp[min(len(sp) - 1, int(len(sp) * 0.95))]
        opt_ref = 3.0 * p95
    return {
        "area":            area,
        "total":           len(roster),
        "skipped":         SKIP_BY_AREA.get(area, 0),
        "raw_total":       len(RAW_BY_AREA.get(area, [])),
        "positions":       positions,
        "leagues":         leagues,
        "teams_by_league": teams_by_league,
        "nationalities":   nationalities,
        "value_range":     [min(values, default=0), max(values, default=0)],
        "peak_range":      [min(peaks,  default=0), max(peaks,  default=0)],
        "age_range":       [min(ages,   default=0), max(ages,   default=0)],
        "opt_ref_scale_eur": opt_ref,
        "available_areas": sorted(DB_BY_AREA.keys()),
    }

@app.get("/api/meta")
def get_meta(area: str = "attack"):
    if area not in DB_BY_AREA:
        raise HTTPException(status_code=404, detail=f"Area '{area}' not loaded")
    return _build_meta(area)

# ── /api/players — filtered & sorted list ────────────────────────────────────
@app.get("/api/players")
def search_players(
    area:          str             = Query("attack", description="Pitch area: attack | midfield | defense | gk"),
    q:             Optional[str]   = Query(None,  description="Name / club search"),
    positions:     Optional[str]   = Query(None,  description="Comma-separated positions"),
    leagues:       Optional[str]   = Query(None,  description="Comma-separated leagues"),
    teams:         Optional[str]   = Query(None,  description="Comma-separated team names"),
    nationalities: Optional[str]   = Query(None,  description="Comma-separated citizenships"),
    age_min:       Optional[float] = Query(None),
    age_max:       Optional[float] = Query(None),
    value_min:     Optional[float] = Query(None,  description="EUR"),
    value_max:     Optional[float] = Query(None,  description="EUR"),
    peak_min:      Optional[float] = Query(None,  description="EUR"),
    peak_max:      Optional[float] = Query(None,  description="EUR"),
    contract_max_years: Optional[float] = Query(None, description="Max years remaining from 2026-05-01"),
    sort_by:       str             = Query("peak", description="name|age|current|next1yr|peak|upside|peak12|peakCareer|optimistic|expectedUpside|optimisticUpside|trend|rawOpt|rawQ75"),
    sort_dir:      int             = Query(-1,     description="-1 desc, 1 asc"),
    system:        str             = Query("raw",  description="raw or calibrated — controls peak filter/sort behavior"),
    limit:         int             = Query(200,   ge=1, le=500),
    offset:        int             = Query(0,     ge=0),
):
    if area not in DB_BY_AREA:
        raise HTTPException(status_code=404, detail=f"Area '{area}' not loaded")
    roster = DB_BY_AREA[area]
    is_attack_area = (area == "attack")

    pos_set = {x.strip() for x in positions.split(",")}     if positions     else set()
    lea_set = {x.strip() for x in leagues.split(",")}       if leagues       else set()
    team_set= {x.strip() for x in teams.split(",")}         if teams         else set()
    nat_set = {x.strip() for x in nationalities.split(",")} if nationalities else set()
    q_low   = q.lower().strip() if q else None

    def grad_weight(gap_pct: float) -> float:
        """Mirror of gradWeightForGap() in scout-data.js."""
        if gap_pct <= 0.15: return 0.50
        if gap_pct <= 0.30: return 0.65
        if gap_pct <= 0.50: return 0.85
        return 1.00

    def calibrated_career_base(p: dict) -> float:
        """Mirror of calibratedPeaks().career in scout-data.js.
        Decline guard: when peak.base < cur × 0.95 (long-term model says
        past peak), career is pinned at cur. Tolerates missing horizon_1y /
        horizon_2y blocks (other pitch areas may only ship peak_potential)."""
        peak_blk = p["predictions"].get("peak")    or {}
        h1_blk   = p["predictions"].get("next1yr") or {}
        h2_blk   = p["predictions"].get("next2yr") or {}
        peak = peak_blk.get("base")
        h1   = h1_blk.get("base")
        h2   = h2_blk.get("base")
        cur  = p.get("valueEur") or 0
        if peak is None: return 0
        # When horizons are absent, no blend — peak.base alone with floor + guard
        if h1 is None and h2 is None:
            blended = peak
        else:
            short_raw = max(v for v in [h1, h2] if v is not None)
            if peak >= short_raw:
                blended = peak
            else:
                gap = (short_raw - peak) / peak if peak else 0
                w_pk = grad_weight(gap)
                blended = w_pk * peak + (1 - w_pk) * short_raw
        career = max(blended, cur)
        TREND_DECLINE_PCT = 0.05
        if cur > 0 and peak < cur * (1 - TREND_DECLINE_PCT):
            career = cur
        return career

    def calibrated_short_term(p: dict) -> float:
        """Returns 0 when horizons are missing (no meaningful 1-2y peak to display)."""
        peak_blk = p["predictions"].get("peak")    or {}
        h1_blk   = p["predictions"].get("next1yr") or {}
        h2_blk   = p["predictions"].get("next2yr") or {}
        h1 = h1_blk.get("base")
        h2 = h2_blk.get("base")
        if h1 is None and h2 is None: return 0
        cur = p.get("valueEur") or 0
        career = calibrated_career_base(p)
        short_raw = max(v for v in [h1, h2] if v is not None)
        return max(min(short_raw, career), cur)

    def smoothed_optimistic(p: dict) -> float:
        """Mirror of smoothedOptimistic() in scout-data.js — combined ratio +
        absolute-gap shrinkage on q90. Only used by the Attack area."""
        peak_blk = p["predictions"].get("peak") or {}
        base = peak_blk.get("base")
        opt  = peak_blk.get("opt")
        if opt is None: return 0
        if base is None or base <= 0 or opt <= base: return opt
        r = opt / base
        g = opt - base
        R = _build_meta(area).get("opt_ref_scale_eur") or 50e6
        k = 1.0 / (1.0 + 0.2 * math.log(r) + 0.7 * math.log(1 + g / R))
        blended = base * (r ** k)
        career = calibrated_career_base(p)
        if career: blended = max(blended, career)
        return blended

    def calibrated_optimistic(p: dict) -> float:
        """min(q75, ceiling) floored at calibrated career.
        Ceiling = smoothed q90 for attack (shrinkage applies),
                  raw q90    for other areas (no shrinkage).
        Mirror of calibratedOptimistic() in scout-data.js."""
        peak_blk = p["predictions"].get("peak") or {}
        q75      = peak_blk.get("opt_q75")
        raw_opt  = peak_blk.get("opt")
        career   = calibrated_career_base(p)

        if is_attack_area:
            ceiling = smoothed_optimistic(p)
        else:
            ceiling = raw_opt
            if ceiling is not None and career:
                ceiling = max(ceiling, career)

        if q75 is None: return ceiling or 0
        if not ceiling or ceiling <= 0:
            return max(q75, career) if career else q75

        out = min(q75, ceiling)
        if career: out = max(out, career)
        return out

    def passes(p: dict) -> bool:
        if pos_set and p["position"] not in pos_set:
            return False
        if lea_set and p["league"] not in lea_set:
            return False
        if team_set and p.get("club") not in team_set:
            return False
        if nat_set and not any(c in nat_set for c in (p.get("citizenships") or [])):
            return False
        if age_min is not None and p["age"] < age_min:
            return False
        if age_max is not None and p["age"] > age_max:
            return False
        if value_min is not None and p["valueEur"] < value_min:
            return False
        if value_max is not None and p["valueEur"] > value_max:
            return False
        # Peak filter respects the active system: calibrated uses the calibrated
        # career, raw uses raw peak.base. This keeps the slider consistent with
        # what the user sees in the table.
        if system == "calibrated":
            pb = calibrated_career_base(p)
        else:
            pb = (p["predictions"].get("peak") or {}).get("base") or 0
        if peak_min is not None and pb < peak_min:
            return False
        if peak_max is not None and pb > peak_max:
            return False
        if contract_max_years is not None:
            from datetime import datetime
            expiry = p.get("contractExpiry")
            if not expiry:
                return False
            cutoff = datetime(2026, 5, 1)
            try:
                exp_dt = datetime.strptime(expiry, "%b %d, %Y")
                if (exp_dt - cutoff).days / 365.25 > contract_max_years:
                    return False
            except (ValueError, TypeError):
                return False
        if q_low and q_low not in p["name"].lower() and q_low not in p["club"].lower():
            return False
        return True

    def sort_key(p: dict):
        peak_blk = p["predictions"].get("peak")    or {}
        n1_blk   = p["predictions"].get("next1yr") or {}
        pb  = peak_blk.get("base") or 0
        n1  = n1_blk.get("base")   or 0
        ups = (pb - p["valueEur"]) / p["valueEur"] if p["valueEur"] else 0
        cur = p.get("valueEur") or 0
        if sort_by == "name":   return p["name"]
        # ── Calibrated-mode keys ──
        if sort_by == "peakCareer": return calibrated_career_base(p)
        if sort_by == "peak12":     return calibrated_short_term(p)
        if sort_by == "expectedUpside":
            cb = calibrated_career_base(p)
            return (cb / cur) if (cur and cb) else 0
        if sort_by == "trend":
            # Mirror of unifiedTrend() in scout-data.js. Returns signed pct
            # so declines sort below rises in normal sort order.
            cb = calibrated_career_base(p)
            if not (cur and cb): return 0
            exp_pct = (cb - cur) / cur
            if exp_pct >= 0.05: return exp_pct
            peak_b = peak_blk.get("base")
            if peak_b is None: return 0
            peak_pct = (peak_b - cur) / cur
            if peak_pct < -0.05: return peak_pct
            return 0
        if sort_by == "optimisticUpside":
            co = calibrated_optimistic(p)
            return (co / cur) if (cur and co) else 0
        if sort_by == "optimistic":
            return calibrated_optimistic(p) if system == "calibrated" else (peak_blk.get("opt") or 0)
        # ── Raw-mode keys ──
        if sort_by == "rawOpt":  return peak_blk.get("opt")     or 0
        if sort_by == "rawQ75":  return peak_blk.get("opt_q75") or 0
        keys = {"age": p["age"], "current": p["valueEur"],
                "next1yr": n1, "peak": pb, "upside": ups}
        return keys.get(sort_by, 0)

    results = [p for p in roster if passes(p)]
    results.sort(key=sort_key, reverse=(sort_dir == -1))

    total  = len(results)
    page   = results[offset: offset + limit]

    return {"total": total, "count": len(page), "offset": offset, "players": page}

# ── /api/players/{tm_id} — full player detail ─────────────────────────────────
@app.get("/api/players/{tm_id}")
def get_player(tm_id: int, area: Optional[str] = None):
    # If area specified, look in that roster. Else scan all areas (tm_id is
    # globally unique in TransferMarkt; falling back to global search makes
    # links work regardless of which area is currently active).
    rosters = [DB_BY_AREA[area]] if area and area in DB_BY_AREA else list(DB_BY_AREA.values())
    for roster in rosters:
        for p in roster:
            if p["id"] == tm_id:
                return p
    raise HTTPException(status_code=404, detail="Player not found")

# ── /images/{filename} — serve player photos ──────────────────────────────────
# Two variants:
#   /images/<file>             → looks in IMAGES_DIR/<file>            (legacy / flat)
#   /images/<area>/<file>      → looks in IMAGES_DIR/<area>/<file>     (per-area subfolder)
# The frontend picks the URL form based on the currently loaded pitch area,
# so teammates can keep their photos in dedicated subfolders without tm_id
# collisions across areas.
@app.get("/images/{filename}")
def get_image(filename: str):
    if IMAGES_DIR.exists():
        path = IMAGES_DIR / filename
        if path.exists():
            return FileResponse(str(path))
    raise HTTPException(status_code=404, detail="Image not found")

@app.get("/images/{area}/{filename}")
def get_image_in_area(area: str, filename: str):
    # Restrict the area subdir to alphanumeric+underscore so this can't be
    # turned into an arbitrary filesystem traversal.
    if not area.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid area")
    if IMAGES_DIR.exists():
        path = IMAGES_DIR / area / filename
        if path.exists():
            return FileResponse(str(path))
    raise HTTPException(status_code=404, detail="Image not found")

# ── / — serve frontend ────────────────────────────────────────────────────────
@app.get("/")
def serve_index():
    if Path("scout.html").exists():
        return FileResponse("scout.html")
    raise HTTPException(status_code=404, detail="scout.html not found")

# Serve companion JS/JSX files
for static_file in ["scout-data.js", "scout-components.jsx", "scout-visuals.jsx"]:
    _f = static_file  # capture for closure
    @app.get(f"/{_f}")
    def _serve_static(f=_f):
        p = Path(f)
        if p.exists():
            return FileResponse(str(p))
        raise HTTPException(status_code=404, detail=f"{f} not found")

# Serve per-area player database JSONs. The FastAPI server's main DB is
# loaded at startup (Attack), but for the other pitch areas the frontend
# fetches their JSON directly via this static route. Restricted to filenames
# matching `final_players_db_<area>.json` and `final_players_db.json` so
# arbitrary disk reads aren't exposed.
@app.get("/final_players_db_{area}.json")
def serve_area_db(area: str):
    # Allow alphanumeric + underscore area names only.
    if not area.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid area name")
    fname = f"final_players_db_{area}.json"
    p = Path(fname)
    if p.exists():
        return FileResponse(str(p), media_type="application/json")
    raise HTTPException(status_code=404, detail=f"{fname} not found in working directory")

@app.get("/final_players_db.json")
def serve_attack_db():
    p = Path("final_players_db.json")
    if p.exists():
        return FileResponse(str(p), media_type="application/json")
    raise HTTPException(status_code=404, detail="final_players_db.json not found")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[Scout ML] Starting on http://{args.host}:{args.port}", flush=True)
    print(f"[Scout ML] Open http://localhost:{args.port}/ in your browser", flush=True)
    if IMAGES_DIR.exists():
        print(f"[Scout ML] Serving images from {IMAGES_DIR}", flush=True)
    else:
        print(f"[Scout ML] Images dir '{IMAGES_DIR}' not found — photos will not load", flush=True)
    uvicorn.run(app, host=args.host, port=args.port)