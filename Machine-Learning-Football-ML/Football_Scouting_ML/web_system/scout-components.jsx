// ─── SCOUT ML — Shared Components ────────────────────────────────────────────
const { useState, useEffect, useRef, useMemo } = React;

// ── Logo ──────────────────────────────────────────────────────────────────────
function ScoutLogo({ size = 36 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
      <circle cx="24" cy="24" r="22" stroke="#00c896" strokeWidth="1.5" opacity="0.3"/>
      <polygon points="24,8 28.5,14 24,20 19.5,14" fill="#00c896" opacity="0.9"/>
      <polygon points="24,20 29.5,22.5 31,29 24,31 17,29 18.5,22.5" fill="#00c896" opacity="0.55"/>
      <polygon points="17,29 18.5,22.5 24,20 19.5,14 11,17" fill="none" stroke="#00c896" strokeWidth="1" opacity="0.5"/>
      <polygon points="31,29 29.5,22.5 24,20 28.5,14 37,17" fill="none" stroke="#00c896" strokeWidth="1" opacity="0.5"/>
      <polygon points="17,29 24,31 31,29 33,36 24,40 15,36" fill="none" stroke="#00c896" strokeWidth="1" opacity="0.4"/>
      <circle cx="24" cy="8"  r="2" fill="#00c896"/>
      <circle cx="11" cy="17" r="1.5" fill="#00c896" opacity="0.7"/>
      <circle cx="37" cy="17" r="1.5" fill="#00c896" opacity="0.7"/>
      <circle cx="15" cy="36" r="1.5" fill="#00c896" opacity="0.6"/>
      <circle cx="33" cy="36" r="1.5" fill="#00c896" opacity="0.6"/>
      <line x1="11" y1="17" x2="6"  y2="12" stroke="#00c896" strokeWidth="0.8" opacity="0.4"/>
      <line x1="37" y1="17" x2="42" y2="12" stroke="#00c896" strokeWidth="0.8" opacity="0.4"/>
      <line x1="15" y1="36" x2="10" y2="42" stroke="#00c896" strokeWidth="0.8" opacity="0.3"/>
      <line x1="33" y1="36" x2="38" y2="42" stroke="#00c896" strokeWidth="0.8" opacity="0.3"/>
      <circle cx="6"  cy="12" r="1" fill="#00c896" opacity="0.5"/>
      <circle cx="42" cy="12" r="1" fill="#00c896" opacity="0.5"/>
    </svg>
  );
}

// ── Chip ──────────────────────────────────────────────────────────────────────
function Chip({ label, color }) {
  return (
    <span style={{ background: color ? `${color}18` : 'var(--surface3)', border: `1px solid ${color ? `${color}35` : 'var(--border)'}`, color: color || 'var(--text2)', borderRadius: 6, padding: '3px 10px', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>
      {label}
    </span>
  );
}

// ── Searchable Dropdown ───────────────────────────────────────────────────────
function SearchableSelect({ label, options, selected, onChange, multi = true }) {
  const [open, setOpen]   = useState(false);
  const [query, setQuery] = useState('');
  const ref               = useRef();

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const filtered = options.filter(o => o.toLowerCase().includes(query.toLowerCase()));
  const isAny    = selected.length === 0;
  const toggle   = (opt) => {
    if (multi) onChange(selected.includes(opt) ? selected.filter(v => v !== opt) : [...selected, opt]);
    else { onChange(selected[0] === opt ? [] : [opt]); setOpen(false); }
  };
  const displayLabel = isAny ? `Any ${label}` : multi && selected.length > 1 ? `${selected.length} selected` : selected[0];

  return (
    <div ref={ref} style={{ position: 'relative', marginBottom: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text3)', marginBottom: 7 }}>{label}</div>
      <button onClick={() => { setOpen(o => !o); setQuery(''); }}
        style={{ width: '100%', background: 'var(--surface2)', border: `1px solid ${open ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 8, padding: '8px 12px', color: isAny ? 'var(--text3)' : 'var(--text)', fontSize: 13, fontWeight: 500, cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', transition: 'border-color 0.15s', textAlign: 'left', fontFamily: 'var(--font-ui)' }}>
        <span>{displayLabel}</span>
        <span style={{ color: 'var(--text3)', fontSize: 10, marginLeft: 8 }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div style={{ position: 'absolute', left: 0, right: 0, top: '100%', marginTop: 4, background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 10, zIndex: 200, overflow: 'hidden', boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
          <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border2)' }}>
            <input autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="Search…"
              style={{ width: '100%', background: 'var(--surface3)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 10px', color: 'var(--text)', fontSize: 12, outline: 'none', fontFamily: 'var(--font-ui)' }}/>
          </div>
          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            <div onClick={() => { onChange([]); if (!multi) setOpen(false); }}
              style={{ padding: '8px 14px', fontSize: 12, color: isAny ? 'var(--accent)' : 'var(--text2)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--surface3)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              <span style={{ width: 14, height: 14, borderRadius: 3, border: `1.5px solid ${isAny ? 'var(--accent)' : 'var(--border)'}`, background: isAny ? 'var(--accent)' : 'transparent', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9 }}>{isAny && '✓'}</span>
              Any {label}
            </div>
            {filtered.map(opt => {
              const active = selected.includes(opt);
              return (
                <div key={opt} onClick={() => toggle(opt)}
                  style={{ padding: '8px 14px', fontSize: 12, color: active ? 'var(--accent)' : 'var(--text)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}
                  onMouseEnter={e => e.currentTarget.style.background = active ? 'rgba(0,200,150,.1)' : 'var(--surface3)'}
                  onMouseLeave={e => e.currentTarget.style.background = active ? 'rgba(0,200,150,.06)' : 'transparent'}>
                  <span style={{ width: 14, height: 14, borderRadius: 3, border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border)'}`, background: active ? 'var(--accent)' : 'transparent', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9 }}>{active && '✓'}</span>
                  {opt}
                </div>
              );
            })}
            {filtered.length === 0 && <div style={{ padding: '10px 14px', fontSize: 12, color: 'var(--text3)' }}>No results</div>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Range Filter ──────────────────────────────────────────────────────────────
function RangeFilter({ label, min, max, step = 1, value, onChange, format, showBest, onBest, bestActive, bestLabel }) {
  const fmt  = format || (v => v);
  const pctL = (value[0] - min) / (max - min) * 100;
  const pctR = (value[1] - min) / (max - min) * 100;
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text3)' }}>{label}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {showBest && (
            <button onClick={onBest} style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em', padding: '2px 8px', borderRadius: 5, border: `1px solid ${bestActive ? 'var(--accent)' : 'var(--border)'}`, background: bestActive ? 'rgba(0,200,150,.1)' : 'transparent', color: bestActive ? 'var(--accent)' : 'var(--text3)', cursor: 'pointer' }}>BEST</button>
          )}
          <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, color: 'var(--text2)' }}>{fmt(value[0])} – {fmt(value[1])}</span>
        </div>
      </div>
      {bestActive ? (
        <div style={{ height: 20, display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--accent)', background: 'rgba(0,200,150,.08)', border: '1px solid rgba(0,200,150,.2)', borderRadius: 6, padding: '3px 10px', fontWeight: 600 }}>✓ {bestLabel || 'Top tier only'}</span>
        </div>
      ) : (
        <div style={{ position: 'relative', height: 20, display: 'flex', alignItems: 'center' }}>
          <div style={{ position: 'absolute', left: 0, right: 0, height: 3, background: 'var(--surface3)', borderRadius: 2 }}/>
          <div style={{ position: 'absolute', left: `${pctL}%`, right: `${100 - pctR}%`, height: 3, background: 'var(--accent2)', borderRadius: 2, opacity: 0.8 }}/>
          <input type="range" min={min} max={max} step={step} value={value[0]}
            onChange={e => { const v = +e.target.value; if (v <= value[1]) onChange([v, value[1]]); }}
            style={{ position: 'absolute', width: '100%', background: 'transparent', zIndex: 2 }}/>
          <input type="range" min={min} max={max} step={step} value={value[1]}
            onChange={e => { const v = +e.target.value; if (v >= value[0]) onChange([value[0], v]); }}
            style={{ position: 'absolute', width: '100%', background: 'transparent', zIndex: 2 }}/>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Components below are used ONLY by the Calibrated system. The Raw system
// keeps using RangeFilter / the original PlayerRow with no new components.
// ─────────────────────────────────────────────────────────────────────────────

// ── Min / Max numeric input filter (two boxes: From / To) ─────────────────────
function MinMaxFilter({ label, value, onChange, suffix, step = 0.5, min = 0 }) {
  const [lo, hi] = value;
  const cell = (val, idx, placeholder) => (
    <div style={{ flex: 1, position: 'relative' }}>
      <input
        type="number"
        value={val == null ? '' : val}
        min={min}
        step={step}
        placeholder={placeholder}
        onChange={e => {
          const raw = e.target.value;
          const next = raw === '' ? null : Number(raw);
          const newPair = [...value];
          newPair[idx] = next;
          onChange(newPair);
        }}
        style={{
          width: '100%',
          background: 'var(--surface2)',
          border: '1px solid var(--border)',
          borderRadius: 7,
          padding: suffix ? '7px 26px 7px 10px' : '7px 10px',
          color: 'var(--text)',
          fontSize: 12,
          fontFamily: 'var(--font-data)',
          outline: 'none',
        }}
      />
      {suffix && (
        <span style={{
          position: 'absolute', right: 9, top: '50%', transform: 'translateY(-50%)',
          fontSize: 11, color: 'var(--text3)', pointerEvents: 'none',
          fontFamily: 'var(--font-data)',
        }}>{suffix}</span>
      )}
    </div>
  );
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text3)', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {cell(lo, 0, 'From')}
        <span style={{ color: 'var(--text3)', fontSize: 11 }}>—</span>
        {cell(hi, 1, 'To')}
      </div>
    </div>
  );
}

// ── Key Drivers strip ────────────────────────────────────────────────────────
// Position-aware "Key Trends for the Model" panel for the profile page.
// Two dimensions of selection:
//
//   1. Competition tabs:
//      Domestic League / Club Tournament / International Tournament
//
//   2. Comparison mode toggle:
//      vs Prior Season  (default) — last season vs the immediately prior
//                                   season in this competition (when that
//                                   prior season has enough minutes), else
//                                   silent fallback to prior-seasons average.
//      vs Career Best              — last season vs the player's best-ever
//                                   prior season for each metric.
//
// Categories with no significantly-changed metrics (≥5%) are hidden. A
// metric's visibility is decided by whichever mode shows the bigger swing,
// so the set of metrics stays stable when the user toggles modes.
function KeyDrivers({ history, position }) {
  const [comp, setComp] = useState('domestic');
  const [mode, setMode] = useState('prior');   // 'prior' | 'best'

  // computeKeyDrivers + COMPETITION_LABELS are globals from scout-data.js
  const result = computeKeyDrivers(history || [], position, comp);

  // Decide whether each tab has ANY rows for this player at all. Tabs with
  // zero rows period (vs zero in last-season) get a subtler disabled look so
  // the user knows there's truly no data, not just a recent-season gap.
  const tabAvailability = ['domestic', 'club_tournament', 'international'].reduce((acc, t) => {
    const anyRows = (history || []).some(r => competitionType(r._league) === t);
    acc[t] = anyRows;
    return acc;
  }, {});

  // Color the delta cell:
  //   |Δ| 5-20%   → blue (positive) or orange (negative)
  //   |Δ| > 20%   → green (positive) or red (negative)
  // Positive/negative directions account for higherIsBetter (e.g. goals
  // conceded — lower is better).
  const colorForDelta = (pct, higherIsBetter) => {
    if (pct == null) return 'var(--text3)';
    const abs = Math.abs(pct);
    if (abs < 5) return 'var(--text3)';
    const isGood = (pct > 0) === higherIsBetter;
    if (abs >= 20) return isGood ? 'var(--positive)' : 'var(--negative)';
    return isGood ? '#7eb0ff' : '#f5a623';
  };

  // Suppress the whole panel if the player has NO history rows at all
  // across any competition.
  const anyHistory = (history || []).length > 0;
  if (!anyHistory) return null;

  // Tournament name extra line (only relevant for club/international tabs)
  const tournamentName = result.tournamentName;

  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border2)',
      borderRadius: 12, padding: '16px 18px', marginTop: 14,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text3)' }}>
          Key Trends for the Model
        </div>
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>
          {mode === 'prior'
            ? 'Last season vs prior season · only metrics with ≥5% change'
            : 'Last season vs career best · only metrics with ≥5% change'}
        </div>
      </div>

      {/* Tab row: competition selector (left) + mode toggle (right) */}
      <div style={{ display: 'flex', gap: 14, marginTop: 10, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {['domestic', 'club_tournament', 'international'].map(t => {
            const isActive = t === comp;
            const isAvailable = tabAvailability[t];
            return (
              <button
                key={t}
                onClick={() => setComp(t)}
                disabled={!isAvailable}
                title={isAvailable ? `View ${COMPETITION_LABELS[t]} performance change` : 'No matches in this competition for this player'}
                style={{
                  background:  isActive ? 'var(--accent2)' : 'var(--surface3)',
                  color:       isActive ? '#fff' : (isAvailable ? 'var(--text2)' : 'var(--text3)'),
                  border:      `1px solid ${isActive ? 'var(--accent2)' : 'var(--border)'}`,
                  borderRadius: 6, padding: '5px 12px',
                  fontSize: 11, fontWeight: 700, letterSpacing: '0.03em',
                  cursor: isAvailable ? 'pointer' : 'not-allowed',
                  opacity: isAvailable ? 1 : 0.45,
                  fontFamily: 'var(--font-ui)', transition: 'all .12s',
                }}>
                {COMPETITION_LABELS[t]}
              </button>
            );
          })}
        </div>
        {/* Mode toggle: vs Prior Season / vs Career Best */}
        <div style={{ display: 'flex', gap: 0, border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          {[
            { id: 'prior', label: 'vs Prior Season' },
            { id: 'best',  label: 'vs Career Best'  },
          ].map((opt, i) => {
            const isActive = mode === opt.id;
            return (
              <button
                key={opt.id}
                onClick={() => setMode(opt.id)}
                style={{
                  background:  isActive ? 'var(--accent2)' : 'var(--surface3)',
                  color:       isActive ? '#fff' : 'var(--text2)',
                  border:      'none',
                  borderLeft:  i === 0 ? 'none' : '1px solid var(--border)',
                  padding:     '5px 12px',
                  fontSize:    11, fontWeight: 700, letterSpacing: '0.03em',
                  cursor:      'pointer',
                  fontFamily:  'var(--font-ui)', transition: 'all .12s',
                }}>
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Context header line — one line between tabs and category sections.
          Communicates two things in one place:
            • For Club/International tabs: which specific tournament.
            • For Prior-Season mode: which team/league the comparison is against.
          When in "vs Career Best" mode we suppress the team/league line since
          the comparison is per-metric career-best (no single peer season). */}
      {(() => {
        const lines = [];
        // Tournament: line for non-domestic tabs
        if (tournamentName) {
          lines.push(
            <span key="t">
              <span style={{ color: 'var(--text3)' }}>Tournament: </span>
              <span style={{ fontWeight: 600 }}>{tournamentName}</span>
            </span>
          );
        }
        // Comparison context — only relevant in prior-season mode
        if (mode === 'prior' && result.priorContext) {
          if (result.priorContext.source === 'prior_season') {
            const ctxBits = [
              result.priorContext.season,
              result.priorContext.team,
              result.priorContext.league,
            ].filter(Boolean).join(' · ');
            lines.push(
              <span key="c">
                <span style={{ color: 'var(--text3)' }}>Compared to: </span>
                <span style={{ fontWeight: 600 }}>{ctxBits}</span>
              </span>
            );
          } else if (result.priorContext.source === 'avg') {
            lines.push(
              <span key="c">
                <span style={{ color: 'var(--text3)' }}>Compared to: </span>
                <span style={{ fontWeight: 600 }}>prior-seasons average</span>
              </span>
            );
          }
        }
        if (mode === 'best') {
          lines.push(
            <span key="c">
              <span style={{ color: 'var(--text3)' }}>Compared to: </span>
              <span style={{ fontWeight: 600 }}>career-best season for each metric</span>
            </span>
          );
        }
        if (lines.length === 0) return null;
        return (
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 14, fontFamily: 'var(--font-ui)', display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            {lines}
          </div>
        );
      })()}

      {/* Body — either an empty-state message or the categorized rows */}
      {!result.hasData ? (
        <div style={{
          padding: '20px 16px', textAlign: 'center', color: 'var(--text3)',
          fontSize: 12, background: 'var(--surface2)', border: '1px dashed var(--border)',
          borderRadius: 8,
        }}>
          {result.reason === 'no_last_season'
            ? `Player did not participate in ${COMPETITION_LABELS[comp].toLowerCase()} last season.`
            : result.reason === 'insufficient_last_season_minutes'
            ? `Insufficient ${COMPETITION_LABELS[comp].toLowerCase()} minutes last season (${result.lastSeasonMinutes ?? 0} min) — comparison not shown to avoid noise.`
            : `No ${COMPETITION_LABELS[comp].toLowerCase()} appearances on record.`
          }
        </div>
      ) : result.categories.length === 0 ? (
        <div style={{
          padding: '16px', textAlign: 'center', color: 'var(--text3)',
          fontSize: 12, background: 'var(--surface2)', border: '1px dashed var(--border)',
          borderRadius: 8,
        }}>
          No metrics changed by 5% or more vs prior seasons in this competition.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {result.categories.map((cat, ci) => (
            <div key={ci}>
              <div style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '.08em',
                textTransform: 'uppercase', color: 'var(--text2)', marginBottom: 8,
              }}>
                {cat.title}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
                {cat.rows.map((r, i) => {
                  // Pick which baseline to display based on the toggle
                  const baseline = mode === 'best' ? r.careerBest    : r.priorBaseline;
                  const deltaPct = mode === 'best' ? r.bestDeltaPct  : r.priorDeltaPct;

                  // Build the "vs X" label under the cell
                  let baselineLabel;
                  if (baseline == null) {
                    baselineLabel = 'no prior seasons';
                  } else if (mode === 'best') {
                    baselineLabel = `best ${r.fmt(baseline)}`;
                  } else if (r.priorSource === 'prior_season' && r.priorMeta) {
                    baselineLabel = `prior ${r.priorMeta.season} · ${r.fmt(baseline)}`;
                  } else {
                    baselineLabel = `avg ${r.fmt(baseline)}`;
                  }

                  const deltaColor = colorForDelta(deltaPct, r.higherIsBetter);
                  const arrow = deltaPct == null ? '' : (deltaPct >= 0 ? '↑' : '↓');

                  return (
                    <div key={i} style={{
                      background: 'var(--surface2)', border: '1px solid var(--border)',
                      borderRadius: 8, padding: '10px 12px',
                    }}>
                      <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase', marginBottom: 6 }}>
                        {r.label}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                        <span style={{ fontFamily: 'var(--font-data)', fontSize: 17, fontWeight: 700, color: 'var(--text)' }}>
                          {r.fmt(r.last)}
                        </span>
                        {deltaPct != null && Math.abs(deltaPct) >= 1 && (
                          <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, fontWeight: 700, color: deltaColor, whiteSpace: 'nowrap' }}>
                            {arrow} {Math.abs(deltaPct).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4, fontFamily: 'var(--font-data)' }}>
                        {baselineLabel}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tier Standouts ────────────────────────────────────────────────────────────
// Competition-aware peer comparison. Three tabs:
//   Domestic League         — uses precomputed *_tier_z from advanced_stats
//                              (peer = same league tier)
//   Club Tournament         — on-the-fly z-score vs cohort of all loaded
//                              players who appeared in the same tournament
//                              last season (e.g. UCL)
//   International Tournament — same but for World Cup / Euro / etc.
//
// Threshold z ≥ 1.0 across all tabs. Position-aware (GK gets a different
// metric set than outfield). Tabs the player has no rows in are disabled.
function TierStandouts({ player, advancedStats, position, league, allPlayers }) {
  const [tab, setTab] = useState('domestic');

  // Tab availability — same logic as Key Trends: only enable tabs the player
  // has any history rows for.
  const tabAvailability = ['domestic', 'club_tournament', 'international'].reduce((acc, t) => {
    const anyRows = (player?.history || []).some(r => competitionType(r._league) === t);
    acc[t] = anyRows;
    return acc;
  }, {});

  // All three tabs now go through computeCompetitionTierStandouts so the
  // computation logic is uniform regardless of which JSON we loaded. The
  // domestic path filters the cohort to same-tier players; the tournament
  // paths use everyone who appeared in the same tournament. This also
  // sidesteps the schema differences across teammate JSONs (the attacker
  // pipeline ships *_tier_z columns but midfield doesn't).
  const r = computeCompetitionTierStandouts(player, allPlayers || [], tab, league);
  const result = { rows: r.rows, available: tabAvailability[tab], reason: r.reason };
  const peerLabel = r.peerGroup;

  // Visual color for z-score: deeper green as z rises
  const colorForZ = (z) => {
    if (z >= 2.0) return 'var(--positive)';
    if (z >= 1.5) return '#34d399';
    return '#7eb0ff';
  };

  // Human-friendly percentile estimate from z (assumes normal distribution).
  const topPctLabel = (z) => {
    if (z >= 2.5) return 'top 0.6%';
    if (z >= 2.0) return 'top 2.5%';
    if (z >= 1.5) return 'top 7%';
    if (z >= 1.0) return 'top 16%';
    return null;
  };

  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border2)',
      borderRadius: 12, padding: '16px 18px', marginTop: 14,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.1em', textTransform: 'uppercase', color: 'var(--text3)' }}>
          Tier Standouts
        </div>
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>
          Metrics where the player ranks notably above their peer group
        </div>
      </div>

      {/* Competition selector tabs */}
      <div style={{ display: 'flex', gap: 6, marginTop: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        {['domestic', 'club_tournament', 'international'].map(t => {
          const isActive = t === tab;
          const isAvailable = tabAvailability[t];
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              disabled={!isAvailable}
              title={isAvailable ? `View ${COMPETITION_LABELS[t]} peer comparison` : 'No matches in this competition for this player'}
              style={{
                background:  isActive ? 'var(--accent2)' : 'var(--surface3)',
                color:       isActive ? '#fff' : (isAvailable ? 'var(--text2)' : 'var(--text3)'),
                border:      `1px solid ${isActive ? 'var(--accent2)' : 'var(--border)'}`,
                borderRadius: 6, padding: '5px 12px',
                fontSize: 11, fontWeight: 700, letterSpacing: '0.03em',
                cursor: isAvailable ? 'pointer' : 'not-allowed',
                opacity: isAvailable ? 1 : 0.45,
                fontFamily: 'var(--font-ui)', transition: 'all .12s',
              }}>
              {COMPETITION_LABELS[t]}
            </button>
          );
        })}
      </div>

      {/* Peer-group line */}
      {peerLabel && (
        <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 14, fontFamily: 'var(--font-ui)' }}>
          <span style={{ color: 'var(--text3)' }}>Peer group: </span>
          <span style={{ fontWeight: 600 }}>{peerLabel}</span>
        </div>
      )}

      {/* Body */}
      {!result.available || result.reason === 'no_rows' ? (
        <div style={{
          padding: '16px', textAlign: 'center', color: 'var(--text3)',
          fontSize: 12, background: 'var(--surface2)', border: '1px dashed var(--border)',
          borderRadius: 8,
        }}>
          No {COMPETITION_LABELS[tab].toLowerCase()} appearances on record.
        </div>
      ) : result.reason === 'no_last_season' ? (
        <div style={{
          padding: '16px', textAlign: 'center', color: 'var(--text3)',
          fontSize: 12, background: 'var(--surface2)', border: '1px dashed var(--border)',
          borderRadius: 8,
        }}>
          Player did not participate in {COMPETITION_LABELS[tab].toLowerCase()} last season.
        </div>
      ) : result.reason === 'insufficient_last_season_minutes' ? (
        <div style={{
          padding: '16px', textAlign: 'center', color: 'var(--text3)',
          fontSize: 12, background: 'var(--surface2)', border: '1px dashed var(--border)',
          borderRadius: 8,
        }}>
          Insufficient {COMPETITION_LABELS[tab].toLowerCase()} minutes last season — peer comparison not shown.
        </div>
      ) : result.rows.length === 0 ? (
        <div style={{
          padding: '16px', textAlign: 'center', color: 'var(--text3)',
          fontSize: 12, background: 'var(--surface2)', border: '1px dashed var(--border)',
          borderRadius: 8,
        }}>
          No metrics stand out above the peer-group average for this player.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
          {result.rows.map((r, i) => {
            const zColor = colorForZ(r.z);
            return (
              <div key={i} style={{
                background: 'var(--surface2)', border: '1px solid var(--border)',
                borderRadius: 8, padding: '10px 12px',
              }}>
                <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, letterSpacing: '.04em', textTransform: 'uppercase', marginBottom: 6 }}>
                  {r.label}
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontFamily: 'var(--font-data)', fontSize: 17, fontWeight: 700, color: 'var(--text)' }}>
                    {r.value != null ? r.fmt(r.value) : '—'}
                  </span>
                  <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, fontWeight: 700, color: zColor, whiteSpace: 'nowrap' }}>
                    {topPctLabel(r.z)}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4, fontFamily: 'var(--font-data)' }}>
                  z-score {r.z.toFixed(2)}{r.cohortSize ? ` · ${r.cohortSize.toLocaleString()} peers` : ''}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Risk Pill (label only, no number) ────────────────────────────────────────
function RiskPill({ score }) {
  const bucket = riskBucket(score);
  if (!bucket) return <span style={{ color: 'var(--text3)', fontFamily: 'var(--font-data)', fontSize: 12 }}>—</span>;
  return (
    <span style={{
      display: 'inline-block',
      fontSize: 10, fontWeight: 700, letterSpacing: '.04em', textTransform: 'uppercase',
      color: bucket.color, background: `${bucket.color}1a`, border: `1px solid ${bucket.color}40`,
      borderRadius: 5, padding: '2px 8px', whiteSpace: 'nowrap',
    }}>{bucket.label}</span>
  );
}

// ── Short-term Trend cell ────────────────────────────────────────────────────
// Shows ↑ X% (green) or ↓ X% (red) when the calibrated 1-2Y peak diverges
// from the current value by more than ±5%. Empty otherwise. Communicates
// near-term direction, complementary to the career peak columns.
function ValueTrendCell({ predictions, valueEur }) {
  const trend = valueTrend(predictions, valueEur);
  if (!trend) {
    return <span style={{ color: 'var(--text3)', fontFamily: 'var(--font-data)', fontSize: 12 }}>—</span>;
  }
  const pctNum = trend.pct * 100;
  const isUp   = pctNum > 0;
  const arrow  = isUp ? '↑' : '↓';
  const color  = isUp ? 'var(--positive)' : 'var(--negative)';
  return (
    <span style={{ fontFamily: 'var(--font-data)', fontSize: 13, fontWeight: 700, color, whiteSpace: 'nowrap' }}>
      {arrow} {Math.abs(pctNum).toFixed(0)}%
    </span>
  );
}

// ── Calibrated PlayerRow (9 columns, calibrated system only) ─────────────────
//   rank │ player │ pos │ age │ value │ expected peak │ trend │ optimistic peak │ opt.upside │ risk
//
// Trend column unifies the old separate Short-Term + Exp.Up columns:
//   • If displayed career is ≥+5% above cur     → ↑ X% (the Exp.Up signal)
//   • Else if peak.base is ≤−5% below cur (decline guard fired)
//                                                → ↓ Y% (the legacy Short-Term signal)
//   • Else                                       → '—'
function PlayerRowCalibrated({ player, rank, onClick, serverMode }) {
  const [hov, setHov] = useState(false);
  const { career } = calibratedPeaks(player.predictions, player.valueEur);
  const peakOpt    = calibratedOptimistic(player.predictions, player.valueEur);
  const peakRisk   = player.predictions?.peak?.risk;
  const cur        = player.valueEur || 0;

  const trend      = valueTrend(player.predictions, player.valueEur);   // {pct, isDecline} or null

  // For attack: single Opt.Peak column (the calibrated min(q75, smoothed_q90))
  // with Opt.Up keyed off Opt.Peak.
  //
  // For non-attack: separate Q75 and Q90 columns (raw quantiles, no merging),
  // with Q90.Up keyed off the raw q90. This lets a scout see both bounds
  // explicitly so the user can decide for themselves how to weigh them
  // before any future merging decision is made.
  const area = (typeof window !== 'undefined' && window.__SCOUT_AREA) || 'attack';
  const isAttack = area === 'attack';
  const peakQ75 = player.predictions?.peak?.opt_q75;
  const peakQ90 = player.predictions?.peak?.opt;

  // Upside reference depends on area:
  //   attack    → vs Opt.Peak (the calibrated optimistic shown in column 8)
  //   non-attack → vs Q90 (the raw upper bound shown in the dedicated column)
  const upsideRef = isAttack ? peakOpt : peakQ90;
  const optUp = (upsideRef && cur) ? (upsideRef / cur - 1) * 100 : null;

  // Photos saved on disk by tm_id (player.id, set by normalizePlayer).
  // Attack uses the flat /images/<tm_id>.jpg URL (no subdir). Other areas
  // use /images/<area>/<tm_id>.jpg so teammates' photo sets stay isolated.
  // onError hides the image gracefully when the file isn't there (initials
  // fall through as placeholder).
  const _area = (typeof window !== 'undefined' && window.__SCOUT_AREA) || 'attack';
  const serverPhotoUrl = player.has_photo
    ? (_area === 'attack' ? `/images/${player.id}.jpg` : `/images/${_area}/${player.id}.jpg`)
    : null;

  const fmtUp = (v) => {
    if (v == null) return '—';
    const sign = v >= 0 ? '+' : '';
    return `${sign}${v.toFixed(0)}%`;
  };
  const upColor = (v) => {
    if (v == null) return 'var(--text3)';
    if (v < 0)   return 'var(--negative)';
    if (v < 25)  return 'var(--text2)';
    if (v < 100) return 'var(--accent2)';
    return 'var(--positive)';
  };

  // Trend cell rendering — arrow + signed %, color by direction
  const renderTrend = () => {
    if (!trend) return <span style={{ color: 'var(--text3)', fontFamily: 'var(--font-data)', fontSize: 12 }}>—</span>;
    const pctNum = trend.pct * 100;
    const isUp   = !trend.isDecline;
    const arrow  = isUp ? '↑' : '↓';
    const color  = isUp ? upColor(pctNum) : 'var(--negative)';
    return (
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, fontWeight: 700, color, whiteSpace: 'nowrap' }}>
        {arrow} {Math.abs(pctNum).toFixed(0)}%
      </span>
    );
  };

  // Grid template:
  //   attack:     10 cols  (rank + 9 data: Player, Pos, Age, Value, Exp.Peak, Trend, Opt.Peak, Opt.Up, Opt.Risk)
  //   non-attack: 11 cols  (rank + 10 data: Player, Pos, Age, Value, Exp.Peak, Trend, Q75, Q90, Q90.Up, Opt.Risk)
  const gridCols = isAttack
    ? '34px 1fr 56px 48px 96px 104px 80px 104px 76px 96px'
    : '34px 1fr 56px 48px 96px 104px 80px 92px 92px 76px 96px';

  return (
    <div onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ display: 'grid',
               gridTemplateColumns: gridCols,
               alignItems: 'center', padding: '0 16px', height: 54,
               borderBottom: '1px solid var(--border2)', cursor: 'pointer',
               background: hov ? 'var(--surface2)' : 'transparent',
               transition: 'background 0.12s' }}>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, color: 'var(--text3)' }}>#{rank}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, overflow: 'hidden' }}>
        <div style={{ width: 30, height: 30, borderRadius: 8, background: 'var(--surface3)', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontFamily: 'var(--font-data)', fontWeight: 600, color: 'var(--text3)', flexShrink: 0 }}>
          {serverPhotoUrl
            ? <img src={serverPhotoUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={e => { e.currentTarget.style.display = 'none'; }}/>
            : player.name.split(' ').map(w => w[0]).join('').slice(0, 2)
          }
        </div>
        <div style={{ overflow: 'hidden' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{player.name}</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{player.club}</div>
        </div>
      </div>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, color: 'var(--text2)', background: 'var(--surface3)', borderRadius: 5, padding: '2px 6px', justifySelf: 'start' }}>{player.position}</span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--text2)' }}>{player.age}</span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--text)' }}>{fmtEur(cur)}</span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}
            title="Expected Career Peak (calibrated central forecast)">
        {fmtEur(career)}
      </span>
      {renderTrend()}
      {isAttack ? (
        <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: '#00c896', fontWeight: 600 }}
              title="Optimistic Career Peak — min(q75, smoothed q90), floored at career">
          {fmtEur(peakOpt)}
        </span>
      ) : (
        <>
          <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--accent2)', fontWeight: 600 }}
                title="Q75 — the model's 75th-percentile forecast for career peak (raw, no smoothing)">
            {fmtEur(peakQ75)}
          </span>
          <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: '#00c896', fontWeight: 600 }}
                title="Q90 — the model's 90th-percentile forecast for career peak (raw, no smoothing, no q75 cap)">
            {fmtEur(peakQ90)}
          </span>
        </>
      )}
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, fontWeight: 600, color: upColor(optUp) }}
            title={isAttack
              ? "Optimistic Upside — Optimistic Career Peak / Current Value"
              : "Q90 Upside — raw Q90 / Current Value"}>
        {fmtUp(optUp)}
      </span>
      <RiskPill score={peakRisk}/>
    </div>
  );
}

// ── Season Stats Table (with category carousel) ───────────────────────────────
function SeasonStatsTable({ seasonData }) {
  const [catIdx, setCatIdx] = useState(0);
  const total = SEASON_STAT_CATEGORIES.length;
  const cat   = SEASON_STAT_CATEGORIES[catIdx];

  const getVal = (stat) => {
    if (stat.fn) {
      const v = stat.fn(seasonData);
      return v != null ? v : '—';
    }
    const v = seasonData[stat.key];
    if (v == null) return '—';
    if (stat.fmt) return stat.fmt(v);
    return typeof v === 'number' ? (Number.isInteger(v) ? v : +v.toFixed(2)) : v;
  };

  const navBtn = (dir, label) => (
    <button onClick={() => setCatIdx(i => (i + dir + total) % total)}
      style={{ background: 'var(--surface3)', border: '1px solid var(--border)', color: 'var(--text2)', borderRadius: 7, width: 28, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontFamily: 'var(--font-ui)', flexShrink: 0, transition: 'all .15s' }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent2)'; e.currentTarget.style.color = 'var(--accent2)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text2)'; }}>
      {label}
    </button>
  );

  return (
    <div>
      {/* Category nav */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        {navBtn(-1, '←')}
        <div style={{ flex: 1, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {SEASON_STAT_CATEGORIES.map((c, i) => (
            <button key={c.label} onClick={() => setCatIdx(i)}
              style={{ background: i === catIdx ? 'var(--accent2)' : 'var(--surface3)', border: `1px solid ${i === catIdx ? 'var(--accent2)' : 'var(--border)'}`, color: i === catIdx ? '#fff' : 'var(--text3)', borderRadius: 6, padding: '4px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer', letterSpacing: '0.05em', transition: 'all .15s', fontFamily: 'var(--font-ui)' }}>
              {c.label}
            </button>
          ))}
        </div>
        {navBtn(1, '→')}
      </div>
      {/* Stat grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 8 }}>
        {cat.stats.map(stat => (
          <div key={stat.label} style={{ background: 'var(--surface)', border: '1px solid var(--border2)', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--font-data)', fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 4, lineHeight: 1 }}>{getVal(stat)}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', lineHeight: 1.3 }}>{stat.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Advanced Metrics Panel ────────────────────────────────────────────────────
// Pure current-season snapshot of engineered features grouped by category.
// Deltas-vs-history live in the Key Drivers section below — keeping them
// out here avoids visual duplication and gives each section a clear job:
//   Advanced Metrics → "what is the player doing right now"
//   Key Drivers      → "what changed vs prior seasons"
function AdvancedMetricsPanel({ advStats }) {
  const groups = [...new Set(ADV_DISPLAY_STATS.map(s => s.group))];
  const groupColors = {
    'Attacking Output': 'var(--accent)',
    'Shooting':         'var(--accent2)',
    'Chance Creation':  '#f5a623',
    'Carrying & Threat':'#c084fc',
    'Defending':        '#60a5fa',
    'Performance':      '#34d399',
  };

  return (
    <div>
      {groups.map(group => {
        const groupStats = ADV_DISPLAY_STATS.filter(s => s.group === group);
        const accent     = groupColors[group] || 'var(--accent2)';
        return (
          <div key={group} style={{ marginBottom: 22 }}>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: accent, marginBottom: 10, opacity: 0.85 }}>{group}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
              {groupStats.map(stat => {
                const raw = advStats[stat.key];
                const val = raw != null ? (stat.fmt ? stat.fmt(raw) : raw) : '—';
                return (
                  <div key={stat.label} style={{ background: 'var(--surface)', border: '1px solid var(--border2)', borderRadius: 8, padding: '11px 13px' }}>
                    <div style={{ fontFamily: 'var(--font-data)', fontSize: 17, fontWeight: 600, color: accent, marginBottom: 4, lineHeight: 1 }}>{val}</div>
                    <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.05em', lineHeight: 1.3 }}>{stat.label}</div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Prediction Chart ──────────────────────────────────────────────────────────
function PredictionChart({ player }) {
  const W = 560, H = 210, PAD = { t: 16, r: 20, b: 40, l: 72 };
  const preds = player.predictions;
  const pts = [
    { label: 'Now',         base: player.valueEur, opt: player.valueEur, pes: player.valueEur },
    preds.next1yr ? { label: '+1 Season',  base: preds.next1yr.base, opt: preds.next1yr.opt, pes: preds.next1yr.pes } : null,
    preds.next2yr ? { label: '+2 Seasons', base: preds.next2yr.base, opt: preds.next2yr.opt, pes: preds.next2yr.pes } : null,
    preds.peak    ? { label: 'Peak',       base: preds.peak.base,    opt: preds.peak.opt,    pes: preds.peak.pes    } : null,
  ].filter(Boolean);

  if (pts.length < 2) return <div style={{ padding: 20, color: 'var(--text3)', fontSize: 13, textAlign: 'center' }}>No prediction data</div>;

  const maxVal = Math.max(...pts.map(p => p.opt)) * 1.15;
  const iW = W - PAD.l - PAD.r, iH = H - PAD.t - PAD.b;
  const xS = (i) => PAD.l + (i / (pts.length - 1)) * iW;
  const yS = (v) => PAD.t + iH - (v / maxVal) * iH;
  const mkPath = (key) => pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${xS(i).toFixed(1)},${yS(p[key]).toFixed(1)}`).join(' ');
  const area   = [...pts.map((p,i) => `${i===0?'M':'L'}${xS(i).toFixed(1)},${yS(p.opt).toFixed(1)}`),
                  ...[...pts].reverse().map((p,i) => `L${xS(pts.length-1-i).toFixed(1)},${yS(p.pes).toFixed(1)}`), 'Z'].join(' ');

  const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => maxVal * t);

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="ag" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#00c896" stopOpacity="0.05"/>
          <stop offset="100%" stopColor="#00c896" stopOpacity="0.18"/>
        </linearGradient>
      </defs>
      {ticks.map((v, i) => {
        const y = yS(v);
        return (
          <g key={i}>
            <line x1={PAD.l} y1={y} x2={W-PAD.r} y2={y} stroke="#1e2636" strokeWidth="1"/>
            <text x={PAD.l-5} y={y+4} textAnchor="end" fill="#5a6480" fontSize="9.5" fontFamily="IBM Plex Mono">{fmtEur(v)}</text>
          </g>
        );
      })}
      <path d={area} fill="url(#ag)"/>
      <path d={mkPath('opt')} fill="none" stroke="#00c896" strokeWidth="1.2" strokeDasharray="4 3" opacity="0.5"/>
      <path d={mkPath('pes')} fill="none" stroke="#ff5c5c" strokeWidth="1.2" strokeDasharray="4 3" opacity="0.5"/>
      <path d={mkPath('base')} fill="none" stroke="#00c896" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={xS(i)} cy={yS(p.base)} r="4.5" fill="#00c896" stroke="#090c11" strokeWidth="2"/>
          <text x={xS(i)} y={H - PAD.b + 16} textAnchor="middle" fill="#7a8499" fontSize="11" fontFamily="Plus Jakarta Sans">{p.label}</text>
        </g>
      ))}
      <rect x={PAD.l} y={H-8} width="14" height="2" fill="#00c896" rx="1"/>
      <text x={PAD.l+18} y={H-4} fill="#7a8499" fontSize="10" fontFamily="Plus Jakarta Sans">Base</text>
      <line x1={PAD.l+54} y1={H-7} x2={PAD.l+68} y2={H-7} stroke="#00c896" strokeDasharray="3 2" opacity="0.6"/>
      <text x={PAD.l+72} y={H-4} fill="#7a8499" fontSize="10" fontFamily="Plus Jakarta Sans">Optimistic</text>
      <line x1={PAD.l+144} y1={H-7} x2={PAD.l+158} y2={H-7} stroke="#ff5c5c" strokeDasharray="3 2" opacity="0.6"/>
      <text x={PAD.l+162} y={H-4} fill="#7a8499" fontSize="10" fontFamily="Plus Jakarta Sans">Pessimistic</text>
    </svg>
  );
}

// ── Model Card ────────────────────────────────────────────────────────────────
function ModelCard({ title, sublabel, data, accent }) {
  if (!data) return (
    <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 12, padding: '20px', flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <span style={{ fontSize: 12, color: 'var(--text3)' }}>No data</span>
    </div>
  );
  const range = data.opt - data.pes;
  const pct   = range > 0 ? ((data.base - data.pes) / range * 100) : 50;
  const ac    = accent || '#4d8fff';
  return (
    <div style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 12, padding: '20px 20px 16px', flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text3)', marginBottom: 4 }}>{sublabel}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 18 }}>{title}</div>
      <div style={{ textAlign: 'center', marginBottom: 14 }}>
        <div style={{ fontFamily: 'var(--font-data)', fontSize: 28, fontWeight: 600, color: ac, lineHeight: 1, letterSpacing: '-0.02em' }}>{fmtEur(data.base)}</div>
        <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 5, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase' }}>Base Case</div>
      </div>
      {data.upside != null && (
        <div style={{ textAlign: 'center', marginBottom: 10 }}>
          <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--accent3)' }}>×{data.upside.toFixed(2)} upside</span>
          {data.risk != null && <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--text3)', marginLeft: 10 }}>risk {data.risk.toFixed(3)}</span>}
        </div>
      )}
      <div style={{ height: 3, background: 'var(--surface3)', borderRadius: 2, marginBottom: 12, position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${pct}%`, background: ac, borderRadius: 2, opacity: 0.7 }}/>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
        <div style={{ background: 'rgba(0,200,150,.07)', border: '1px solid rgba(0,200,150,.18)', borderRadius: 7, padding: '7px 10px', flex: 1, textAlign: 'center' }}>
          <div style={{ fontFamily: 'var(--font-data)', fontSize: 12, fontWeight: 600, color: '#00c896' }}>{fmtEur(data.opt)}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Optimistic</div>
        </div>
        {data.q75 != null && (
          <div style={{ background: 'rgba(126,176,255,.07)', border: '1px solid rgba(126,176,255,.22)', borderRadius: 7, padding: '7px 10px', flex: 1, textAlign: 'center' }}>
            <div style={{ fontFamily: 'var(--font-data)', fontSize: 12, fontWeight: 600, color: '#7eb0ff' }}>{fmtEur(data.q75)}</div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Q75</div>
          </div>
        )}
        <div style={{ background: 'rgba(255,92,92,.07)', border: '1px solid rgba(255,92,92,.18)', borderRadius: 7, padding: '7px 10px', flex: 1, textAlign: 'center' }}>
          <div style={{ fontFamily: 'var(--font-data)', fontSize: 12, fontWeight: 600, color: '#ff5c5c' }}>{fmtEur(data.pes)}</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Pessimistic</div>
        </div>
      </div>
    </div>
  );
}

// ── Collapsible Section ───────────────────────────────────────────────────────
function CollapsibleSection({ title, badge, defaultOpen, children, actions }) {
  const [open, setOpen] = useState(defaultOpen || false);
  return (
    <div style={{ borderTop: '1px solid var(--border2)', marginTop: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <button onClick={() => setOpen(o => !o)}
          style={{ flex: 1, background: 'none', border: 'none', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 0', fontFamily: 'var(--font-ui)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{title}</span>
            {badge && <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: 'var(--accent)', background: 'rgba(0,200,150,.08)', border: '1px solid rgba(0,200,150,.2)', borderRadius: 5, padding: '2px 8px' }}>{badge}</span>}
          </div>
          <span style={{ color: 'var(--text3)', fontSize: 11, display: 'inline-block', transition: 'transform 0.2s', transform: open ? 'rotate(180deg)' : 'rotate(0deg)' }}>▼</span>
        </button>
        {actions && (
          <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 6, paddingLeft: 10, flexShrink: 0 }}>
            {actions}
          </div>
        )}
      </div>
      {open && <div style={{ paddingBottom: 20 }}>{children}</div>}
    </div>
  );
}

// ── Player Row (RAW system, 9 columns including q75) ─────────────────────────
function PlayerRow({ player, rank, onClick, serverMode }) {
  const [hov, setHov] = useState(false);
  const peakBase  = player.predictions?.peak?.base;
  const peakOpt   = player.predictions?.peak?.opt;       // raw q90 (untouched)
  const peakQ75   = player.predictions?.peak?.opt_q75;   // raw q75 from merge
  const upside    = peakBase && player.valueEur ? ((peakBase - player.valueEur) / player.valueEur * 100).toFixed(0) : null;
  const upsideCol = upside > 150 ? '#00c896' : upside > 60 ? '#4d8fff' : 'var(--text2)';
  // Photos saved on disk by tm_id (player.id, set by normalizePlayer).
  // Attack uses the flat /images/<tm_id>.jpg URL (no subdir). Other areas
  // use /images/<area>/<tm_id>.jpg so teammates' photo sets stay isolated.
  // onError hides the image gracefully when the file isn't there (initials
  // fall through as placeholder).
  const _area = (typeof window !== 'undefined' && window.__SCOUT_AREA) || 'attack';
  const serverPhotoUrl = player.has_photo
    ? (_area === 'attack' ? `/images/${player.id}.jpg` : `/images/${_area}/${player.id}.jpg`)
    : null;

  return (
    <div onClick={onClick} onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ display: 'grid', gridTemplateColumns: '36px 1fr 60px 60px 92px 92px 96px 96px 96px 80px', alignItems: 'center', padding: '0 18px', height: 54, borderBottom: '1px solid var(--border2)', cursor: 'pointer', background: hov ? 'var(--surface2)' : 'transparent', transition: 'background 0.12s' }}>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, color: 'var(--text3)' }}>#{rank}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, overflow: 'hidden' }}>
        <div style={{ width: 30, height: 30, borderRadius: 8, background: 'var(--surface3)', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontFamily: 'var(--font-data)', fontWeight: 600, color: 'var(--text3)', flexShrink: 0 }}>
          {serverPhotoUrl
            ? <img src={serverPhotoUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={e => { e.currentTarget.style.display = 'none'; }}/>
            : player.name.split(' ').map(w => w[0]).join('').slice(0, 2)
          }
        </div>
        <div style={{ overflow: 'hidden' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{player.name}</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{player.club}</div>
        </div>
      </div>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 11, color: 'var(--text2)', background: 'var(--surface3)', borderRadius: 5, padding: '2px 6px', justifySelf: 'start' }}>{player.position}</span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--text2)' }}>{player.age}</span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--text)' }}>{fmtEur(player.valueEur)}</span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: '#4d8fff' }}>{fmtEur(player.predictions?.next1yr?.base)}</span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}
            title="Peak (Expected) — raw model output">
        {fmtEur(peakBase)}
      </span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: '#00c896' }}
            title="Optimistic — raw q90 model output (untouched)">
        {fmtEur(peakOpt)}
      </span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: '#7eb0ff', fontWeight: 600 }}
            title="Q75 — raw 75th-percentile from the trained q75 pipeline (capped at q90)">
        {fmtEur(peakQ75)}
      </span>
      <span style={{ fontFamily: 'var(--font-data)', fontSize: 12, color: upsideCol, fontWeight: 600 }}>{upside != null ? `+${upside}%` : '—'}</span>
    </div>
  );
}

// Export all to window
Object.assign(window, {
  ScoutLogo, Chip, SearchableSelect, RangeFilter,
  // New components used only by the Calibrated system:
  MinMaxFilter, RiskPill, ValueTrendCell, PlayerRowCalibrated,
  // Existing:
  SeasonStatsTable, AdvancedMetricsPanel,
  PredictionChart, ModelCard, CollapsibleSection, PlayerRow,
  // Explainability panels:
  KeyDrivers, TierStandouts,
});