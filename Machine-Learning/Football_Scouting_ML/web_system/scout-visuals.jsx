// ─── SCOUT ML — Visual Overlays (Raw Data + Visual Analysis) ─────────────────
// Loaded after scout-components.jsx. All components exported to window at bottom.
const { useState, useEffect, useMemo } = React;

// ── Small action button (used inside CollapsibleSection actions) ──────────────
function SectionActionBtn({ label, color, onClick }) {
  const [hov, setHov] = useState(false);
  const ac = color || 'var(--accent2)';
  return (
    <button onClick={onClick}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{ background: hov ? `${ac}18` : 'transparent', border: `1px solid ${hov ? ac : 'var(--border)'}`, color: hov ? ac : 'var(--text3)', borderRadius: 6, padding: '3px 10px', fontSize: 10, fontWeight: 700, cursor: 'pointer', fontFamily: 'var(--font-ui)', letterSpacing: '0.07em', transition: 'all .15s', whiteSpace: 'nowrap' }}>
      {label}
    </button>
  );
}

// ── Overlay shell ─────────────────────────────────────────────────────────────
function OverlayShell({ title, subtitle, onClose, children }) {
  useEffect(() => {
    const fn = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', fn);
    return () => window.removeEventListener('keydown', fn);
  }, [onClose]);
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'var(--bg)', zIndex: 2000, display: 'flex', flexDirection: 'column' }}>
      <div style={{ height: 54, background: 'var(--surface)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', padding: '0 24px', gap: 16, flexShrink: 0 }}>
        <button onClick={onClose}
          style={{ background: 'var(--surface3)', border: '1px solid var(--border)', color: 'var(--text2)', borderRadius: 8, padding: '6px 14px', fontSize: 12, fontWeight: 700, cursor: 'pointer', fontFamily: 'var(--font-ui)', transition: 'all .15s' }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.color = 'var(--accent)'; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text2)'; }}>
          ← Back
        </button>
        <div style={{ width: 1, height: 24, background: 'var(--border)' }}/>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.015em' }}>{title}</div>
          {subtitle && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 1 }}>{subtitle}</div>}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '28px 40px' }}>
        {children}
      </div>
    </div>
  );
}

// ── SVG: Grouped vertical bar chart ──────────────────────────────────────────
// series: [{key, label, color}]  data: [{label, values:{key:number}}]
function SvgGroupedBars({ title, data, series }) {
  if (!data || data.length === 0) return null;
  const W = 600, H = 220, PAD = { t: 32, r: 20, b: 44, l: 40 };
  const iW = W - PAD.l - PAD.r, iH = H - PAD.t - PAD.b;
  const maxVal = Math.max(...data.flatMap(d => series.map(s => d.values[s.key] || 0))) * 1.18 || 1;
  const groupW = iW / data.length;
  const barW   = (groupW * 0.72) / series.length;
  const xB     = (i, j) => PAD.l + groupW * i + groupW * 0.14 + barW * j;
  const yS     = v => PAD.t + iH - (v / maxVal) * iH;
  const base   = PAD.t + iH;
  const ticks  = [0, 0.25, 0.5, 0.75, 1];
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      {title && <text x={W / 2} y={16} textAnchor="middle" fill="#dde3f0" fontSize="12" fontWeight="700" fontFamily="Plus Jakarta Sans">{title}</text>}
      {ticks.map((t, i) => {
        const v = maxVal * t, y = yS(v);
        return <g key={i}>
          <line x1={PAD.l} y1={y} x2={W - PAD.r} y2={y} stroke="#1e2636" strokeWidth="1"/>
          <text x={PAD.l - 4} y={y + 4} textAnchor="end" fill="#5a6480" fontSize="9" fontFamily="IBM Plex Mono">{Math.round(v)}</text>
        </g>;
      })}
      {data.map((d, i) => (
        <g key={i}>
          {series.map((s, j) => {
            const v = d.values[s.key] || 0;
            const h = (v / maxVal) * iH;
            return <g key={j}>
              <rect x={xB(i,j)} y={base - h} width={Math.max(barW - 1.5, 1)} height={h} fill={s.color} rx="2" opacity="0.85"/>
              {h > 12 && <text x={xB(i,j) + barW/2 - 0.75} y={base - h - 3} textAnchor="middle" fill={s.color} fontSize="9" fontFamily="IBM Plex Mono">{v}</text>}
            </g>;
          })}
          <text x={PAD.l + groupW * i + groupW / 2} y={H - 4} textAnchor="middle" fill="#7a8499" fontSize="10" fontFamily="Plus Jakarta Sans">{d.label}</text>
        </g>
      ))}
      {/* Legend */}
      {series.map((s, i) => (
        <g key={i}>
          <rect x={PAD.l + i * 90} y={H - 18} width="10" height="8" fill={s.color} rx="2"/>
          <text x={PAD.l + i * 90 + 14} y={H - 11} fill="#7a8499" fontSize="10" fontFamily="Plus Jakarta Sans">{s.label}</text>
        </g>
      ))}
    </svg>
  );
}

// ── SVG: Line chart ───────────────────────────────────────────────────────────
function SvgLine({ title, data, color, fmt }) {
  if (!data || data.length < 2) return null;
  const fmtFn = fmt || (v => v?.toFixed ? v.toFixed(2) : v);
  const W = 600, H = 190, PAD = { t: 32, r: 20, b: 36, l: 55 };
  const iW = W - PAD.l - PAD.r, iH = H - PAD.t - PAD.b;
  const vals = data.map(d => d.value).filter(v => v != null);
  if (vals.length < 2) return null;
  const minV = Math.min(...vals) * 0.9, maxV = Math.max(...vals) * 1.1;
  const range = maxV - minV || 1;
  const xS = i => PAD.l + (i / (data.length - 1)) * iW;
  const yS = v => PAD.t + iH - ((v - minV) / range) * iH;
  const path = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${xS(i).toFixed(1)},${d.value != null ? yS(d.value).toFixed(1) : yS(minV)}`).join(' ');
  const ac = color || '#00c896';
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      {title && <text x={W / 2} y={16} textAnchor="middle" fill="#dde3f0" fontSize="12" fontWeight="700" fontFamily="Plus Jakarta Sans">{title}</text>}
      {[0, 0.5, 1].map((t, i) => {
        const v = minV + range * t, y = yS(v);
        return <g key={i}>
          <line x1={PAD.l} y1={y} x2={W - PAD.r} y2={y} stroke="#1e2636" strokeWidth="1"/>
          <text x={PAD.l - 5} y={y + 4} textAnchor="end" fill="#5a6480" fontSize="9" fontFamily="IBM Plex Mono">{fmtFn(v)}</text>
        </g>;
      })}
      <path d={path} fill="none" stroke={ac} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
      {data.map((d, i) => d.value != null && (
        <g key={i}>
          <circle cx={xS(i)} cy={yS(d.value)} r="4.5" fill={ac} stroke="#090c11" strokeWidth="2"/>
          <text x={xS(i)} y={H - 4} textAnchor="middle" fill="#7a8499" fontSize="10" fontFamily="Plus Jakarta Sans">{d.label}</text>
        </g>
      ))}
    </svg>
  );
}

// ── SVG: Horizontal comparison bars (current vs historical avg) ───────────────
function SvgHorizCompare({ title, data }) {
  if (!data || data.length === 0) return null;
  const ROW = 38, W = 600, PAD_L = 170, PAD_R = 70;
  const H   = data.length * ROW + 48;
  const iW  = W - PAD_L - PAD_R;
  const mx  = Math.max(...data.flatMap(d => [d.current || 0, d.historical || 0])) * 1.15 || 1;
  const xS  = v => (v / mx) * iW;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      {title && <text x={W / 2} y={16} textAnchor="middle" fill="#dde3f0" fontSize="12" fontWeight="700" fontFamily="Plus Jakarta Sans">{title}</text>}
      <text x={PAD_L + iW * 0.3}  y={32} textAnchor="middle" fill="#4d8fff" fontSize="9" fontWeight="700">CURRENT</text>
      <text x={PAD_L + iW * 0.7}  y={32} textAnchor="middle" fill="#5a6480" fontSize="9" fontWeight="700">HIST AVG</text>
      {data.map((d, i) => {
        const y      = 40 + i * ROW;
        const cW     = xS(d.current || 0);
        const hW     = xS(d.historical || 0);
        const delta  = (d.current != null && d.historical != null) ? d.current - d.historical : null;
        const dColor = delta > 0.001 ? '#00c896' : delta < -0.001 ? '#ff5c5c' : '#5a6480';
        return (
          <g key={i}>
            <text x={PAD_L - 8} y={y + 10} textAnchor="end" fill="#8b95ad" fontSize="10" fontFamily="Plus Jakarta Sans">{d.label}</text>
            <rect x={PAD_L} y={y}     width={Math.max(cW, 0)} height={13} fill="#4d8fff" rx="2" opacity="0.8"/>
            <text x={PAD_L + cW + 3}  y={y + 10} fill="#4d8fff" fontSize="9" fontFamily="IBM Plex Mono">{d.current?.toFixed(3) ?? '—'}</text>
            <rect x={PAD_L} y={y + 17} width={Math.max(hW, 0)} height={9}  fill="#5a6480" rx="2" opacity="0.45"/>
            {delta != null && (
              <text x={W - PAD_R + 4} y={y + 10} fill={dColor} fontSize="10" fontFamily="IBM Plex Mono">{delta > 0 ? '+' : ''}{delta.toFixed(3)}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── SVG: Tier Z score bar chart (centered at 0) ───────────────────────────────
function SvgTierZ({ data }) {
  if (!data || data.length === 0) return null;
  const ROW = 36, W = 600, PAD_L = 180, PAD_R = 20;
  const H   = data.length * ROW + 56;
  const iW  = W - PAD_L - PAD_R;
  const absMax = Math.max(...data.map(d => Math.abs(d.value || 0))) * 1.2 || 1;
  const cx  = PAD_L + iW / 2;
  const bW  = v => (Math.abs(v) / absMax) * (iW / 2);
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      <text x={W / 2} y={16} textAnchor="middle" fill="#dde3f0" fontSize="12" fontWeight="700" fontFamily="Plus Jakarta Sans">Tier Z Scores (vs league peers)</text>
      <text x={cx - iW/4} y={32} textAnchor="middle" fill="#ff5c5c" fontSize="9" fontWeight="700">BELOW AVG</text>
      <text x={cx + iW/4} y={32} textAnchor="middle" fill="#00c896" fontSize="9" fontWeight="700">ABOVE AVG</text>
      <line x1={cx} y1={36} x2={cx} y2={H - 8} stroke="#252d3e" strokeWidth="1.5"/>
      {data.map((d, i) => {
        const y   = 40 + i * ROW;
        const v   = d.value || 0;
        const pos = v >= 0;
        const w   = bW(v);
        return (
          <g key={i}>
            <text x={PAD_L - 8} y={y + 11} textAnchor="end" fill="#8b95ad" fontSize="10" fontFamily="Plus Jakarta Sans">{d.label}</text>
            <rect x={pos ? cx : cx - w} y={y} width={Math.max(w, 1)} height={20} fill={pos ? '#00c896' : '#ff5c5c'} rx="2" opacity="0.75"/>
            <text x={pos ? cx + w + 4 : cx - w - 4} y={y + 13} textAnchor={pos ? 'start' : 'end'} fill={pos ? '#00c896' : '#ff5c5c'} fontSize="10" fontFamily="IBM Plex Mono">{v > 0 ? '+' : ''}{v.toFixed(2)}</text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Section label ─────────────────────────────────────────────────────────────
function SectionLabel({ label }) {
  return (
    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text3)', marginBottom: 10, marginTop: 28 }}>{label}</div>
  );
}

// ── Chart card wrapper ────────────────────────────────────────────────────────
function ChartCard({ children }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border2)', borderRadius: 12, padding: '20px 16px 12px', marginBottom: 18 }}>
      {children}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// RAW DATA OVERLAY
// ─────────────────────────────────────────────────────────────────────────────
// Shows EVERY field present in the source JSON for this player.
//   - type='season'   → wide table: rows = seasons (history_data entries),
//                       columns = every key found in any history row.
//   - type='advanced' → key/value grid of every key in advanced_stats.
//
// This is intentionally decoupled from the curated PREVIEW shown in the
// player page (which uses SEASON_STAT_CATEGORIES / ADV_DISPLAY_STATS in
// scout-data.js). To control what appears in the preview, edit those arrays.
// To control what appears in RAW — nothing to configure: it's everything.
// ─────────────────────────────────────────────────────────────────────────────

// Helper: format a raw JSON value for display (numbers truncated, null → —).
function fmtRawCell(v) {
  if (v == null || v === '') return '—';
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return v.toLocaleString();
    // keep meaningful precision for small floats, trim long ones
    if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    if (Math.abs(v) >= 1)    return (+v.toFixed(3)).toString();
    return (+v.toFixed(4)).toString();
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  return String(v);
}

// Identifier columns we want pinned to the left of the season RAW table.
const SEASON_ID_COLS = [
  '_season_year', '_league', 'team', 'player_positions',
  'age_in_season', 'appearances', 'matchesStarted', 'minutesPlayed',
];

// Group prefix → label, for advanced_stats RAW grouping
function classifyAdvKey(k) {
  if (k.startsWith('hist_'))                      return 'Historical Aggregates';
  if (k.startsWith('current_') && k.includes('_vs_hist_')) return 'Current vs Historical';
  if (k.endsWith('_p90_shrunk') || k.endsWith('_p90')) return 'Per-90 Metrics';
  if (k.endsWith('_tier_z'))                      return 'Tier-Z Scores';
  if (k.startsWith('is_') || k.endsWith('_flag') || k.endsWith('_at_cutoff')) return 'Flags & Context';
  return 'Core / Other';
}

const ADV_GROUP_ORDER = [
  'Core / Other',
  'Per-90 Metrics',
  'Tier-Z Scores',
  'Historical Aggregates',
  'Current vs Historical',
  'Flags & Context',
];

function RawDataOverlay({ type, player, onClose }) {
  const [query, setQuery]       = useState('');   // column / field search
  const [sortBy, setSortBy]     = useState(null); // season-table column sort
  const [sortDir, setSortDir]   = useState(-1);

  const history  = player.history || [];
  const advStats = player.advancedStats || {};

  // ── Build column list for season RAW: union of all keys across all rows ──
  const seasonAllCols = useMemo(() => {
    const set = new Set();
    history.forEach(s => Object.keys(s).forEach(k => set.add(k)));
    const ids   = SEASON_ID_COLS.filter(k => set.has(k));
    const rest  = [...set].filter(k => !SEASON_ID_COLS.includes(k)).sort();
    return [...ids, ...rest];
  }, [history]);

  const filteredSeasonCols = useMemo(() => {
    if (!query.trim()) return seasonAllCols;
    const q = query.toLowerCase();
    // identifier cols always visible so the table stays readable
    const ids = seasonAllCols.filter(k => SEASON_ID_COLS.includes(k));
    const matched = seasonAllCols.filter(k => !SEASON_ID_COLS.includes(k) && k.toLowerCase().includes(q));
    return [...ids, ...matched];
  }, [seasonAllCols, query]);

  const sortedRows = useMemo(() => {
    if (!sortBy) return history;
    const rows = [...history];
    rows.sort((a, b) => {
      const va = a[sortBy], vb = b[sortBy];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * sortDir;
      return String(va).localeCompare(String(vb)) * sortDir;
    });
    return rows;
  }, [history, sortBy, sortDir]);

  // ── Build advanced RAW: filter + group ──
  const advAllKeys = useMemo(() => Object.keys(advStats).sort(), [advStats]);
  const advFilteredKeys = useMemo(() => {
    if (!query.trim()) return advAllKeys;
    const q = query.toLowerCase();
    return advAllKeys.filter(k => k.toLowerCase().includes(q));
  }, [advAllKeys, query]);

  const advGrouped = useMemo(() => {
    const map = {};
    advFilteredKeys.forEach(k => {
      const g = classifyAdvKey(k);
      (map[g] = map[g] || []).push(k);
    });
    return map;
  }, [advFilteredKeys]);

  const subtitle = type === 'season'
    ? `${player.name} · Season Statistics · ${seasonAllCols.length} fields × ${history.length} seasons`
    : `${player.name} · Advanced Metrics · ${advAllKeys.length} fields`;

  const onSortClick = (col) => {
    if (sortBy === col) setSortDir(d => -d);
    else { setSortBy(col); setSortDir(-1); }
  };

  // Early-out AFTER all hooks (Rules of Hooks): nothing to show.
  if (type === 'season' && history.length === 0) {
    return (
      <OverlayShell title="Raw Data" subtitle={`${player.name} · No history available`} onClose={onClose}>
        <div style={{ padding:40, textAlign:'center', color:'var(--text3)', fontSize:13 }}>
          This player has no season history in the dataset.
        </div>
      </OverlayShell>
    );
  }

  return (
    <OverlayShell title="Raw Data" subtitle={subtitle} onClose={onClose}>

      {/* ── Search / filter bar (shared by both modes) ── */}
      <div style={{ display:'flex', alignItems:'center', gap:14, marginBottom:18, flexWrap:'wrap' }}>
        <input
          autoFocus
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder={type === 'season'
            ? `Filter columns… (${filteredSeasonCols.length}/${seasonAllCols.length})`
            : `Filter fields… (${advFilteredKeys.length}/${advAllKeys.length})`}
          style={{ background:'var(--surface2)', border:'1px solid var(--border)', borderRadius:8,
                   padding:'8px 14px', color:'var(--text)', fontSize:12, outline:'none',
                   fontFamily:'var(--font-ui)', minWidth:320, flex:'0 1 420px' }}
        />
        {query && (
          <button onClick={() => setQuery('')}
            style={{ background:'transparent', border:'1px solid var(--border)', color:'var(--text3)',
                     borderRadius:6, padding:'5px 12px', fontSize:11, cursor:'pointer', fontFamily:'var(--font-ui)' }}>
            Clear
          </button>
        )}
        <span style={{ fontSize:11, color:'var(--text3)', fontFamily:'var(--font-data)' }}>
          {type === 'season'
            ? 'Identifier columns are always pinned. Click a header to sort.'
            : 'All keys from advanced_stats, grouped by category.'}
        </span>
      </div>

      {/* ── SEASON: wide table — one row per season ── */}
      {type === 'season' && (
        <div style={{ background:'var(--surface)', border:'1px solid var(--border2)', borderRadius:10,
                      overflow:'auto', maxHeight:'calc(100vh - 200px)' }}>
          <table style={{ borderCollapse:'separate', borderSpacing:0, fontFamily:'var(--font-data)',
                          fontSize:11, color:'var(--text)', width:'max-content', minWidth:'100%' }}>
            <thead>
              <tr>
                {filteredSeasonCols.map((col, idx) => {
                  const isId  = SEASON_ID_COLS.includes(col);
                  const isFirst = idx === 0;
                  const active = sortBy === col;
                  return (
                    <th key={col} onClick={() => onSortClick(col)}
                      style={{
                        position: isFirst ? 'sticky' : (isId ? 'sticky' : 'static'),
                        left: isFirst ? 0 : undefined,
                        top: 0,
                        zIndex: isFirst ? 3 : 2,
                        background:'var(--surface2)',
                        borderBottom:'1px solid var(--border)',
                        borderRight: isId ? '1px solid var(--border2)' : '1px solid transparent',
                        padding:'10px 12px',
                        textAlign:'left',
                        whiteSpace:'nowrap',
                        fontSize:10, fontWeight:700, letterSpacing:'.05em',
                        textTransform:'uppercase',
                        color: active ? 'var(--accent)' : (isId ? 'var(--text2)' : 'var(--text3)'),
                        cursor:'pointer',
                        userSelect:'none',
                      }}>
                      {col}
                      {active && <span style={{ marginLeft:6, color:'var(--accent)' }}>{sortDir === -1 ? '↓' : '↑'}</span>}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row, ri) => (
                <tr key={ri} style={{ background: ri % 2 ? 'var(--surface)' : 'var(--bg2)' }}>
                  {filteredSeasonCols.map((col, idx) => {
                    const isFirst = idx === 0;
                    const isId    = SEASON_ID_COLS.includes(col);
                    const v       = row[col];
                    return (
                      <td key={col}
                        style={{
                          position: isFirst ? 'sticky' : 'static',
                          left: isFirst ? 0 : undefined,
                          background: isFirst ? (ri % 2 ? 'var(--surface)' : 'var(--bg2)') : 'inherit',
                          borderBottom:'1px solid var(--border2)',
                          borderRight: isId ? '1px solid var(--border2)' : 'none',
                          padding:'8px 12px',
                          whiteSpace:'nowrap',
                          color: v == null ? 'var(--text3)' : 'var(--text)',
                          fontWeight: isFirst ? 700 : 400,
                          zIndex: isFirst ? 1 : 0,
                        }}>
                        {fmtRawCell(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── ADVANCED: grouped key/value list ── */}
      {type === 'advanced' && (
        <div>
          {ADV_GROUP_ORDER.filter(g => advGrouped[g]?.length).map(group => (
            <div key={group} style={{ marginBottom:28 }}>
              <div style={{ display:'flex', alignItems:'baseline', gap:10, marginBottom:10 }}>
                <span style={{ fontSize:11, fontWeight:700, letterSpacing:'.1em', textTransform:'uppercase',
                               color:'var(--accent)', opacity:.85 }}>{group}</span>
                <span style={{ fontSize:10, color:'var(--text3)', fontFamily:'var(--font-data)' }}>
                  {advGrouped[group].length} fields
                </span>
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(320px, 1fr))', gap:6 }}>
                {advGrouped[group].map(k => (
                  <div key={k} style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline',
                                         gap:12, background:'var(--surface)', border:'1px solid var(--border2)',
                                         borderRadius:6, padding:'7px 12px' }}>
                    <span style={{ fontFamily:'var(--font-data)', fontSize:11, color:'var(--text3)',
                                   overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}
                          title={k}>{k}</span>
                    <span style={{ fontFamily:'var(--font-data)', fontSize:12, fontWeight:600,
                                   color: advStats[k] == null ? 'var(--text3)' : 'var(--accent2)',
                                   whiteSpace:'nowrap' }}>
                      {fmtRawCell(advStats[k])}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {advFilteredKeys.length === 0 && (
            <div style={{ padding:40, textAlign:'center', color:'var(--text3)', fontSize:13 }}>
              No fields match "{query}".
            </div>
          )}
        </div>
      )}
    </OverlayShell>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// VISUAL ANALYSIS OVERLAY
// ─────────────────────────────────────────────────────────────────────────────
function VisualAnalysisOverlay({ type, player, onClose }) {
  const history  = [...(player.history || [])].reverse(); // oldest first for charts
  const adv      = player.advancedStats || {};

  const subtitle = type === 'season'
    ? `${player.name} · Season History Charts`
    : `${player.name} · Advanced Metrics Charts`;

  // ── Season chart data ─────────────────────────────────────────────────────
  const gaData = useMemo(() => history.map(s => ({
    label:  s._season_year,
    values: { goals: s.goals || 0, assists: s.assists || 0 },
  })), [player]);

  const shotsData = useMemo(() => history.map(s => ({
    label:  s._season_year,
    values: { total: s.totalShots || 0, onTarget: s.shotsOnTarget || 0, goals: s.goals || 0 },
  })), [player]);

  const ratingData = useMemo(() => history.map(s => ({
    label: s._season_year, value: s.rating,
  })), [player]);

  const mvData = useMemo(() => history
    .filter(s => s.mv_end != null)
    .map(s => ({ label: s._season_year, value: s.mv_end })),
  [player]);

  // ── Advanced chart data ───────────────────────────────────────────────────
  const attackCompare = [
    { label: 'Goals /90',        current: adv.goals_p90_shrunk,              historical: adv.hist_goals_p90_shrunk_mean },
    { label: 'Assists /90',      current: adv.assists_p90_shrunk,             historical: adv.hist_assists_p90_shrunk_mean },
    { label: 'xG /90',           current: adv.expectedGoals_p90,             historical: adv.hist_expectedGoals_p90_mean },
    { label: 'xA /90',           current: adv.expectedAssists_p90,           historical: adv.hist_expectedAssists_p90_mean },
    { label: 'Big Chances /90',  current: adv.bigChancesCreated_p90_shrunk,  historical: adv.hist_bigChancesCreated_p90_shrunk_mean },
    { label: 'Key Passes /90',   current: adv.keyPasses_p90_shrunk,          historical: adv.hist_keyPasses_p90_shrunk_mean },
  ].filter(d => d.current != null);

  const shootingCompare = [
    { label: 'Shots /90',        current: adv.totalShots_p90_shrunk,                historical: adv.hist_totalShots_p90_shrunk_mean },
    { label: 'On Target /90',    current: adv.shotsOnTarget_p90_shrunk,             historical: adv.hist_shotsOnTarget_p90_shrunk_mean },
    { label: 'Inside Box /90',   current: adv.shotsFromInsideTheBox_p90_shrunk,     historical: adv.hist_shotsFromInsideTheBox_p90_shrunk_mean },
    { label: 'Dribbles /90',     current: adv.successfulDribbles_p90_shrunk,        historical: adv.hist_successfulDribbles_p90_shrunk_mean },
    { label: 'Progression /90',  current: adv.progression_p90,                     historical: adv.hist_progression_p90_mean },
    { label: 'Touches /90',      current: adv.touches_p90_shrunk ? adv.touches_p90_shrunk / 10 : null,
                                  historical: adv.hist_touches_p90_shrunk_mean ? adv.hist_touches_p90_shrunk_mean / 10 : null,
    },
  ].filter(d => d.current != null);

  const tierZData = [
    { label: 'Goals',       value: adv.goals_tier_z },
    { label: 'Assists',     value: adv.assists_tier_z },
    { label: 'Shots OT',    value: adv.shotsOnTarget_tier_z },
    { label: 'Big Chances', value: adv.bigChancesCreated_tier_z },
    { label: 'Rating',      value: adv.rating_tier_z },
  ].filter(d => d.value != null);

  return (
    <OverlayShell title="Visual Analysis" subtitle={subtitle} onClose={onClose}>

      {type === 'season' && (
        <>
          <ChartCard>
            <SvgGroupedBars
              title="Goals & Assists by Season"
              data={gaData}
              series={[
                { key: 'goals',   label: 'Goals',   color: '#00c896' },
                { key: 'assists', label: 'Assists',  color: '#4d8fff' },
              ]}
            />
          </ChartCard>
          <ChartCard>
            <SvgGroupedBars
              title="Shots Profile by Season"
              data={shotsData}
              series={[
                { key: 'total',    label: 'Total Shots',   color: '#5a6480' },
                { key: 'onTarget', label: 'On Target',     color: '#f5a623' },
                { key: 'goals',    label: 'Goals',         color: '#00c896' },
              ]}
            />
          </ChartCard>
          <ChartCard>
            <SvgLine title="Rating Trend" data={ratingData} color="#f5a623" fmt={v => v?.toFixed(2)}/>
          </ChartCard>
          {mvData.length > 1 && (
            <ChartCard>
              <SvgLine title="Market Value Progression" data={mvData} color="#4d8fff" fmt={v => fmtEur(v)}/>
            </ChartCard>
          )}
        </>
      )}

      {type === 'advanced' && (
        <>
          {attackCompare.length > 0 && (
            <ChartCard>
              <SvgHorizCompare title="Attacking Output — Current vs Career Average" data={attackCompare}/>
            </ChartCard>
          )}
          {shootingCompare.length > 0 && (
            <ChartCard>
              <SvgHorizCompare title="Shooting & Progression — Current vs Career Average" data={shootingCompare}/>
            </ChartCard>
          )}
          {tierZData.length > 0 && (
            <ChartCard>
              <SvgTierZ data={tierZData}/>
            </ChartCard>
          )}
          <ChartCard>
            <SvgHorizCompare
              title="Performance Scores — Current vs Career Average"
              data={[
                { label: 'Rating',         current: adv.rating,              historical: adv.hist_rating_mean },
                { label: 'Rating Residual',current: adv.rating_residual,     historical: adv.hist_rating_residual_mean },
                { label: 'Forward Score',  current: adv.modern_forward_score,historical: adv.hist_modern_forward_score_mean },
                { label: 'G+A vs League',  current: adv.ga_vs_league,        historical: adv.hist_ga_vs_league_weighted_mean },
              ].filter(d => d.current != null)}
            />
          </ChartCard>
        </>
      )}
    </OverlayShell>
  );
}

// ── Export to window ──────────────────────────────────────────────────────────
Object.assign(window, {
  SectionActionBtn,
  RawDataOverlay,
  VisualAnalysisOverlay,
});