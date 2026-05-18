/**
 * OperatorView.jsx — Operator Dashboard
 *
 * The operator's control panel. Shows a live top-down map of all floors,
 * real-time statistics, an event log, and manual controls for the simulation.
 *
 * Layout
 * ------
 * Top bar   : 5 metric cards (Free / Reserved / Occupied / Driving / Occupancy %)
 * Main area : per-floor FloorCanvas components with 60 fps smooth vehicle movement
 * Sidebar   : layout selector, scenario picker, speed slider, vehicle controls
 * Bottom    : scrollable event log (last 50 events)
 *
 * Props
 * -----
 * layout, spots, vehicles, stats, eventLog  ← from useParking()
 * scenarioName, speed                       ← current sim state
 * loadLayout, spawnVehicle, stealSpot,      ← action callbacks
 * freeSpot, removeVehicle, resetSim,
 * setSpeed
 */
import { useState, useEffect } from 'react'
import FloorCanvas from './FloorCanvas.jsx'
import { api } from '../api/parkingApi.js'

function StatCard({ value, label, color }) {
  return (
    <div style={{
      background: '#fff',
      border: `1px solid ${color}33`,
      borderRadius: 12,
      padding: '12px 16px',
      textAlign: 'center',
      flex: 1,
      minWidth: 90,
      boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
    }}>
      <div style={{ fontSize: 24, fontWeight: 800, color }}>{value}</div>
      <div style={{ fontSize: 11, color: '#888', marginTop: 2, fontWeight: 500 }}>{label}</div>
    </div>
  )
}

function EventLog({ events }) {
  const typeColors = { entry: '#2E7D32', exit: '#E65100', steal: '#c62828', remove: '#757575', info: '#1565C0' }
  return (
    <div style={{ maxHeight: 260, overflowY: 'auto' }}>
      {(!events || events.length === 0) && (
        <div style={{ color: '#bbb', fontSize: 13, padding: '10px 0', textAlign: 'center' }}>
          אין אירועים
        </div>
      )}
      {(events || []).map((e, i) => (
        <div key={i} style={{
          display: 'flex', gap: 8, alignItems: 'flex-start',
          padding: '5px 0',
          borderBottom: '1px solid #F0F2F8',
          fontSize: 13,
        }}>
          <span style={{ color: typeColors[e.type] || '#333', minWidth: 6, marginTop: 3 }}>●</span>
          <span style={{ color: '#aaa', flexShrink: 0 }}>{e.time}</span>
          <span style={{ color: '#444' }}>{e.msg}</span>
        </div>
      ))}
    </div>
  )
}

// ── Operator floor selection overlay ─────────────────────────────────────────
function OperatorFloorOverlay({ floorOptions, onSelect, onClose }) {
  const fmtFloorHe = (f) => f < 0 ? `קומה ${Math.abs(f)} תת קרקעית` : `קומה ${f}`
  const fmtWalk = (m) => m < 100 ? `${Math.round(m)} מ'` : `${(m/1000).toFixed(1)} ק"מ`

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 2000, direction: 'rtl',
    }} onClick={onClose}>
      <div style={{
        background: '#fff', borderRadius: 20, width: 420, maxWidth: '96vw',
        maxHeight: '80vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)', padding: '24px',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ fontWeight: 800, fontSize: 18, color: '#2D2A3E', marginBottom: 16 }}>
          🅿️ בחר קומה לרכב החדש
        </div>
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {floorOptions.length === 0 && (
            <div style={{ color: '#aaa', textAlign: 'center', padding: '24px 0' }}>אין חניות פנויות</div>
          )}
          {floorOptions.map((opt, i) => (
            <div key={opt.floor} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '12px 14px', borderRadius: 12, marginBottom: 8,
              background: i === 0 ? 'rgba(108,92,231,0.07)' : '#F8F8FC',
              border: i === 0 ? '1.5px solid rgba(108,92,231,0.3)' : '1px solid #E8E8F0',
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: 15, color: '#2D2A3E' }}>חניה {opt.spot_id}</div>
                <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>
                  {fmtFloorHe(opt.floor)} · 🚶 {fmtWalk(opt.walk_m)} · 🟢 {opt.free_count} פנויות
                </div>
              </div>
              <button onClick={() => onSelect(opt)} style={{
                background: i === 0 ? '#6C5CE7' : '#E8E6FF',
                color: i === 0 ? '#fff' : '#6C5CE7',
                border: 'none', borderRadius: 8, padding: '8px 16px',
                fontWeight: 700, fontSize: 13, cursor: 'pointer',
                fontFamily: 'Rubik,sans-serif',
              }}>בחר</button>
            </div>
          ))}
        </div>
        <button onClick={onClose} style={{
          marginTop: 14, background: '#F0EFF8', color: '#6C5CE7',
          border: 'none', borderRadius: 10, padding: '10px', fontWeight: 700,
          fontSize: 14, cursor: 'pointer', fontFamily: 'Rubik,sans-serif',
        }}>ביטול</button>
      </div>
    </div>
  )
}



function BlockSpotModal({ spots, onBlock, onClose }) {
  const [step,  setStep]  = useState('floor')
  const [floor, setFloor] = useState(null)
  const [row,   setRow]   = useState(null)

  const allSpots = Object.values(spots)
  const floors   = [...new Set(allSpots.map(s => s.floor))].sort((a,b) => a - b)
  const rows     = floor !== null
    ? [...new Set(allSpots.filter(s => s.floor === floor).map(s => s.id.split('-')[1]?.[0]).filter(Boolean))].sort()
    : []
  const spotsInRow = (floor !== null && row)
    ? allSpots.filter(s => {
        const p = s.id.split('-')
        return s.floor === floor && p[1]?.[0] === row
      }).sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }))
    : []

  const pill = (active, color = '#1565C0') => ({
    padding: '8px 16px', borderRadius: 20, fontSize: 13, fontWeight: 700,
    cursor: 'pointer', border: 'none', fontFamily: 'Rubik,sans-serif',
    background: active ? color : '#F0F2FA',
    color: active ? '#fff' : '#2D2A3E',
    transition: 'all 0.15s',
  })

  const statusColor = (status) => {
    if (status === 'OCCUPIED') return '#c62828'
    if (status === 'RESERVED') return '#E65100'
    return '#2E7D32'
  }

  const statusLabel = (status) => {
    if (status === 'OCCUPIED') return '🔴'
    if (status === 'RESERVED') return '🟡'
    return '🟢'
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }} onClick={onClose}>
      <div style={{
        background: '#fff', borderRadius: 16, width: 360, maxWidth: '92vw',
        padding: '24px 20px 20px', boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
        direction: 'rtl',
      }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ fontWeight: 800, fontSize: 17, color: '#2D2A3E' }}>🚫 חסום חניה</div>
          <button onClick={onClose} style={{ background: '#F4F3FA', border: 'none', borderRadius: '50%', width: 30, height: 30, cursor: 'pointer', fontSize: 13, color: '#888', fontWeight: 700 }}>✕</button>
        </div>

        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 14, fontSize: 12, color: '#9B99B0' }}>
          <span onClick={() => { setStep('floor'); setFloor(null); setRow(null) }}
            style={{ cursor: step !== 'floor' ? 'pointer' : 'default', color: step !== 'floor' ? '#1565C0' : '#9B99B0', fontWeight: 600 }}>
            {floor !== null ? `קומה ${floor}` : 'קומה'}
          </span>
          {floor !== null && <><span>›</span>
          <span onClick={() => { if (step === 'spot') { setStep('row'); setRow(null) } }}
            style={{ cursor: step === 'spot' ? 'pointer' : 'default', color: step === 'spot' ? '#1565C0' : '#9B99B0', fontWeight: 600 }}>
            {row || 'שורה'}
          </span></>}
          {row && <><span>›</span><span style={{ color: '#9B99B0', fontWeight: 600 }}>חניה</span></>}
        </div>

        {/* Step: floor */}
        {step === 'floor' && (
          <>
            <div style={{ fontSize: 13, color: '#7B7A8E', marginBottom: 12 }}>באיזו קומה?</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {floors.map(f => (
                <button key={f} style={pill(floor === f)} onClick={() => { setFloor(f); setRow(null); setStep('row') }}>
                  {f === 0 ? 'קרקע (0)' : `קומה ${f}`}
                </button>
              ))}
            </div>
          </>
        )}

        {/* Step: row */}
        {step === 'row' && (
          <>
            <div style={{ fontSize: 13, color: '#7B7A8E', marginBottom: 12 }}>באיזו שורה?</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {rows.map(r => (
                <button key={r} style={pill(row === r)} onClick={() => { setRow(r); setStep('spot') }}>
                  שורה {r}
                </button>
              ))}
            </div>
          </>
        )}

        {/* Step: spot */}
        {step === 'spot' && (
          <>
            <div style={{ fontSize: 13, color: '#7B7A8E', marginBottom: 12 }}>בחר חניה לחסימה:</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, maxHeight: 200, overflowY: 'auto' }}>
              {spotsInRow.map(sp => (
                <button key={sp.id}
                  style={{
                    ...pill(false, statusColor(sp.status)),
                    background: '#F8F8FB',
                    border: `2px solid ${statusColor(sp.status)}`,
                    color: statusColor(sp.status),
                    display: 'flex', alignItems: 'center', gap: 4,
                  }}
                  onClick={() => { onBlock(sp.id); onClose() }}
                >
                  {statusLabel(sp.status)} {sp.id.split('-')[1]}
                </button>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: 11, color: '#9B99B0' }}>
              🟢 פנוי · 🟡 שמור · 🔴 תפוס — ניתן לחסום כל חניה
            </div>
          </>
        )}
      </div>
    </div>
  )
}


function FreeSpotModal({ spots, onFree, onClose }) {
  const [step,  setStep]  = useState('floor')
  const [floor, setFloor] = useState(null)
  const [row,   setRow]   = useState(null)

  const allSpots = Object.values(spots)
  const floors   = [...new Set(allSpots.map(s => s.floor))].sort((a,b) => a - b)
  const rows     = floor !== null
    ? [...new Set(allSpots.filter(s => s.floor === floor).map(s => s.id.split('-')[1]?.[0]).filter(Boolean))].sort()
    : []
  const spotsInRow = (floor !== null && row)
    ? allSpots.filter(s => {
        const p = s.id.split('-')
        return s.floor === floor && p[1]?.[0] === row
      }).sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }))
    : []

  const pill = (active, color = '#1565C0') => ({
    padding: '8px 16px', borderRadius: 20, fontSize: 13, fontWeight: 700,
    cursor: 'pointer', border: 'none', fontFamily: 'Rubik,sans-serif',
    background: active ? color : '#F0F2FA',
    color: active ? '#fff' : '#2D2A3E',
    transition: 'all 0.15s',
  })

  const statusColor = (status) => {
    if (status === 'OCCUPIED') return '#c62828'
    if (status === 'RESERVED') return '#E65100'
    return '#2E7D32'
  }

  const statusLabel = (status) => {
    if (status === 'OCCUPIED') return '🔴'
    if (status === 'RESERVED') return '🟡'
    return '🟢'
  }

  const isAlreadyFree = (status) => status === 'FREE'

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }} onClick={onClose}>
      <div style={{
        background: '#fff', borderRadius: 16, width: 360, maxWidth: '92vw',
        padding: '24px 20px 20px', boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
        direction: 'rtl',
      }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ fontWeight: 800, fontSize: 17, color: '#2D2A3E' }}>🟢 שחרר חניה</div>
          <button onClick={onClose} style={{ background: '#F4F3FA', border: 'none', borderRadius: '50%', width: 30, height: 30, cursor: 'pointer', fontSize: 13, color: '#888', fontWeight: 700 }}>✕</button>
        </div>

        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 14, fontSize: 12, color: '#9B99B0' }}>
          <span onClick={() => { setStep('floor'); setFloor(null); setRow(null) }}
            style={{ cursor: step !== 'floor' ? 'pointer' : 'default', color: step !== 'floor' ? '#2E7D32' : '#9B99B0', fontWeight: 600 }}>
            {floor !== null ? `קומה ${floor}` : 'קומה'}
          </span>
          {floor !== null && <><span>›</span>
          <span onClick={() => { if (step === 'spot') { setStep('row'); setRow(null) } }}
            style={{ cursor: step === 'spot' ? 'pointer' : 'default', color: step === 'spot' ? '#2E7D32' : '#9B99B0', fontWeight: 600 }}>
            {row || 'שורה'}
          </span></>}
          {row && <><span>›</span><span style={{ color: '#9B99B0', fontWeight: 600 }}>חניה</span></>}
        </div>

        {/* Step: floor */}
        {step === 'floor' && (
          <>
            <div style={{ fontSize: 13, color: '#7B7A8E', marginBottom: 12 }}>באיזו קומה?</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {floors.map(f => (
                <button key={f} style={pill(floor === f, '#2E7D32')} onClick={() => { setFloor(f); setRow(null); setStep('row') }}>
                  {f === 0 ? 'קרקע (0)' : `קומה ${f}`}
                </button>
              ))}
            </div>
          </>
        )}

        {/* Step: row */}
        {step === 'row' && (
          <>
            <div style={{ fontSize: 13, color: '#7B7A8E', marginBottom: 12 }}>באיזו שורה?</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {rows.map(r => (
                <button key={r} style={pill(row === r, '#2E7D32')} onClick={() => { setRow(r); setStep('spot') }}>
                  שורה {r}
                </button>
              ))}
            </div>
          </>
        )}

        {/* Step: spot */}
        {step === 'spot' && (
          <>
            <div style={{ fontSize: 13, color: '#7B7A8E', marginBottom: 12 }}>בחר חניה לשחרור:</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, maxHeight: 200, overflowY: 'auto' }}>
              {spotsInRow.map(sp => {
                const free = isAlreadyFree(sp.status)
                return (
                  <button key={sp.id}
                    disabled={free}
                    style={{
                      ...pill(false, statusColor(sp.status)),
                      background: free ? '#F0F2FA' : '#F8F8FB',
                      border: `2px solid ${free ? '#ccc' : statusColor(sp.status)}`,
                      color: free ? '#bbb' : statusColor(sp.status),
                      display: 'flex', alignItems: 'center', gap: 4,
                      cursor: free ? 'not-allowed' : 'pointer',
                      opacity: free ? 0.5 : 1,
                    }}
                    onClick={() => { if (!free) { onFree(sp.id); onClose() } }}
                  >
                    {statusLabel(sp.status)} {sp.id.split('-')[1]}
                  </button>
                )
              })}
            </div>
            <div style={{ marginTop: 10, fontSize: 11, color: '#9B99B0' }}>
              🔴 תפוס · 🟡 שמור — ניתן לשחרר · 🟢 פנוי — לא ניתן לשחרר
            </div>
          </>
        )}
      </div>
    </div>
  )
}


export default function OperatorView({
  layout, spots, vehicles, stats, eventLog,
  scenarioName, speed,
  loadLayout, spawnVehicle, stealSpot, freeSpot,
  removeVehicle, resetSim, setSpeed,
}) {
  const [layouts, setLayouts]         = useState([])
  const [scenarios, setScenarios]     = useState({})
  const [selLayout, setSelLayout]     = useState('')
  const [selScenario, setSelScenario] = useState(scenarioName || 'Demo')
  const [localSpeed, setLocalSpeed]   = useState(speed || 3)

  // spawn form
  const [spawnVid, setSpawnVid]     = useState(`V${Date.now()}`)
  const [spawnTarget, setSpawnTarget] = useState('')
  const [spawnEntrance, setSpawnEntrance] = useState('')
  const [spawnError, setSpawnError]   = useState(null)

  // steal form
  const [stealSpotId, setStealSpotId] = useState('')

  // free-mode form
  const [freeTargetSpotId, setFreeTargetSpotId] = useState('')

  // block spot modal
  const [blockModal, setBlockModal] = useState(false)
  const [blockFloor, setBlockFloor] = useState(null)
  const [blockRow,   setBlockRow]   = useState(null)

  // free
  const [freeModal, setFreeModal] = useState(false)
  // remove form
  const [removeVid, setRemoveVid] = useState('')

  // load layouts + scenarios on mount
  useEffect(() => {
    api.getLayouts().then(ls => {
      setLayouts(ls)
      if (ls.length) setSelLayout(ls[0].path)
    })
    api.getScenarios().then(sc => setScenarios(sc))
  }, [])

  useEffect(() => { setSelScenario(scenarioName) }, [scenarioName])
  useEffect(() => { setLocalSpeed(speed) }, [speed])

  // Flatten target_options for operator spawn — include entrance + generic elevator
  const targets = (() => {
    // Only show specific elevator/escalator subtypes (not generic 'elevator' or non-elevator types).
    // This removes the generic "closest elevator" option and any non-elevator types.
    const raw = layout?.target_options?.filter(t =>
      t.id !== 'exit' &&
      t.id !== 'entrance' &&
      t.id !== 'elevator' &&       // remove generic "closest elevator"
      (t.type === 'elevator' || t.type === 'escalator' || t.subtype)
    ) || []
    const flat = []
    for (const t of raw) {
      if (t.type === 'group' && t.children?.length) {
        for (const child of t.children) {
          flat.push({ ...child, label: child.label })
        }
      } else {
        flat.push(t)
      }
    }
    return flat
  })()
  const entrances = layout?.entrances || []
  const floors = layout?.floors || [0]
  const defaultEntrance = layout?.meta?.default_entrance || entrances[0] || ''

  const freeSpots = Object.values(spots).filter(s => s.status === 'FREE')
  const resSpots  = Object.values(spots).filter(s => s.status === 'RESERVED')
  const allSpots  = Object.values(spots)
  const vids      = Object.keys(vehicles).filter(id => id !== 'user_car_1')

  const isDemo     = selScenario === 'Demo'           || scenarioName === 'Demo'
  const isFreeMode = selScenario === 'ניהול ידני 80%' || scenarioName === 'ניהול ידני 80%'
  const showControls = scenarios[scenarioName]?.show_controls ?? true

  // v8: spawn via api.spawn (clean path through _spawn_vehicle).
  // has_disability is passed as extra field — /api/spawn accepts it via SpawnRequest.
  const [spawnHasDisability, setSpawnHasDisability] = useState(false)

  const handleSpawnClick = async () => {
    setSpawnError(null)
    const tid = spawnTarget || targets[0]?.id
    const eid = spawnEntrance || defaultEntrance || entrances[0]
    if (!tid || !eid) { setSpawnError('בחר יעד וכניסה'); return }
    const vid = spawnVid || `V${Date.now()}`
    try {
      await spawnVehicle(vid, tid, eid, null, null, spawnHasDisability)
      setSpawnVid(`V${Date.now()}`)
    } catch(e) {
      setSpawnError(e.message)
    }
  }

  const handleReset = async () => {
    await resetSim(selLayout || layout?.meta?.name, selScenario)
  }

  const handleLoad = async () => {
    await loadLayout(selLayout, selScenario)
  }

  const handleSpeed = async (v) => {
    setLocalSpeed(v)
    await setSpeed(v)
  }

  const s = (label, children) => (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#9B99B0', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
        {label}
      </div>
      {children}
    </div>
  )

  const btn = (label, onClick, color = '#2196F3', disabled = false) => (
    <button onClick={onClick} disabled={disabled} style={{
      background: disabled ? '#E0E4F0' : color,
      color: disabled ? '#aaa' : '#fff', border: 'none', borderRadius: 8,
      padding: '8px 14px', fontSize: 13, fontWeight: 600,
      cursor: disabled ? 'not-allowed' : 'pointer',
      fontFamily: 'Rubik,sans-serif',
      width: '100%', marginBottom: 6,
      opacity: disabled ? 0.6 : 1,
      transition: 'opacity 0.15s',
    }}>{label}</button>
  )

  const sel = (value, onChange, options) => (
    <select value={value} onChange={e => onChange(e.target.value)} style={{
      width: '100%', background: '#F5F6FA',
      color: '#2D2A3E', border: '1px solid #D8DCF0',
      borderRadius: 8, padding: '7px 10px', fontSize: 13,
      fontFamily: 'Rubik,sans-serif', marginBottom: 6, outline: 'none',
    }}>
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )

  const inp = (value, onChange, placeholder) => (
    <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
      style={{
        width: '100%', background: '#F5F6FA',
        color: '#2D2A3E', border: '1px solid #D8DCF0',
        borderRadius: 8, padding: '7px 10px', fontSize: 13,
        fontFamily: 'Rubik,sans-serif', marginBottom: 6, outline: 'none',
        boxSizing: 'border-box',
      }}
    />
  )

  return (
    <div style={{ display: 'flex', height: '100%', direction: 'rtl', background: '#F0F2F8' }}>

      {/* ── Sidebar ── */}
      <div style={{
        width: 260, flexShrink: 0,
        background: '#fff',
        borderLeft: '1px solid #E0E4F0',
        padding: '16px 14px',
        overflowY: 'auto',
        display: 'flex', flexDirection: 'column', gap: 4,
        boxShadow: '-2px 0 12px rgba(0,0,0,0.04)',
      }}>
        <div style={{ fontWeight: 800, fontSize: 16, color: '#2D2A3E', marginBottom: 14 }}>
          ⚙️ הגדרות
        </div>

        {/* Layout */}
        {s('בחר מגרש', <>
          {sel(selLayout, setSelLayout, layouts.map(l => ({ value: l.path, label: l.name })))}
          {sel(selScenario, setSelScenario, Object.keys(scenarios).map(k => ({
            value: k, label: `${k} – ${scenarios[k]?.description || ''}`,
          })))}
          {btn('🔃 טען', handleLoad, '#1565C0')}
        </>)}

        {/* Speed */}
        {s('מהירות סימולציה', <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input type="range" min={1} max={5} step={0.5} value={localSpeed}
              onChange={e => handleSpeed(parseFloat(e.target.value))}
              style={{ flex: 1, accentColor: '#2196F3' }}
            />
            <span style={{ color: '#fff', fontSize: 14, minWidth: 20 }}>{localSpeed}x</span>
          </div>
        </>)}

        {/* Controls */}
        {showControls && s('🎮 פקדים', <>
          {entrances.length > 1 && sel(spawnEntrance || entrances[0], setSpawnEntrance,
            entrances.map(e => ({ value: e, label: e.replace('ENT_','').replace(/_/g,' ') }))
          )}
          {sel(spawnTarget || targets[0]?.id || '', setSpawnTarget,
            targets.map(t => ({ value: t.id, label: t.label }))
          )}
          {inp(spawnVid, setSpawnVid, 'מזהה רכב')}
          <div onClick={() => setSpawnHasDisability(v => !v)}
            style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8, cursor:'pointer', userSelect:'none' }}>
            <div style={{ width:18, height:18, borderRadius:4, border:'2px solid #6A1B9A',
              background: spawnHasDisability ? '#6A1B9A' : 'transparent',
              display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
              {spawnHasDisability && <span style={{ color:'#fff', fontSize:11, lineHeight:1 }}>✓</span>}
            </div>
            <span style={{ fontSize:12, color:'#6A1B9A', fontWeight:600 }}>♿ תו נכה — כולל חניות נכים</span>
          </div>
          {btn('➕ הוסף רכב', handleSpawnClick, '#2E7D32')}
          {spawnError && <div style={{ color: '#f44336', fontSize: 12, marginBottom: 6 }}>{spawnError}</div>}
        </>)}

        {/* Steal — includes RESERVED spots (vehicles currently driving to them) */}
        {(isDemo || isFreeMode) && s('🚧 גנוב חניה', <>
          <div style={{ fontSize: 11, color: '#E65100', marginBottom: 4 }}>
            כולל חניות שרכב נוסע אליהן כרגע
          </div>
          {sel(stealSpotId || resSpots[0]?.id || '', setStealSpotId,
            [...resSpots, ...freeSpots].slice(0, 40).map(sp => ({
              value: sp.id,
              label: sp.status === 'RESERVED'
                ? `${sp.id} ← נוסע אליה`
                : sp.id
            }))
          )}
          {btn('🚧 גנוב', () => stealSpot(stealSpotId || resSpots[0]?.id), '#E65100',
            resSpots.length === 0 && freeSpots.length === 0)}
        </>)}

        {/* Block any spot */}
        {s('🚫 חסום חניה', <>
          <div style={{ fontSize: 11, color: '#7B7A8E', marginBottom: 6 }}>
            סמן חניה כתפוסה ידנית בכל קומה
          </div>
          {btn('🚫 בחר חניה לחסימה', () => setBlockModal(true), '#6A1B9A')}
        </>)}

        {s('🟢 שחרר חניה', <>
          <div style={{ fontSize: 11, color: '#7B7A8E', marginBottom: 6 }}>
            שחרר חניה תפוסה ידנית בכל קומה
          </div>
          {btn('🟢 בחר חניה לשחרור', () => setFreeModal(true), '#2E7D32')}
        </>)}


        {/* Remove vehicle */}
        {vids.length > 0 && s('❌ הסר רכב', <>
          {sel(removeVid || vids[0], setRemoveVid, vids.map(v => ({ value: v, label: v })))}
          {btn('❌ הסר', () => removeVehicle(removeVid || vids[0]), '#c62828')}
        </>)}

        {/* Reset */}
        <div style={{ marginTop: 'auto', paddingTop: 12 }}>
          {btn('🔄 אפס סימולציה', handleReset, '#546E7A')}
        </div>
      </div>

      {/* ── Main area ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{
          padding: '14px 20px 10px',
          borderBottom: '1px solid #E0E4F0',
          background: '#fff',
          boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
        }}>
          <div style={{ fontWeight: 800, fontSize: 18, color: '#2D2A3E', marginBottom: 10 }}>
            🖥️ {layout?.meta?.name || 'חנייון'} – {scenarioName}
          </div>

          {/* Stats */}
          <div style={{ display: 'flex', gap: 8 }}>
            <StatCard value={stats.free}               label="🟢 פנוי"    color="#2E7D32" />
            <StatCard value={stats.reserved}            label="🟡 שמור"   color="#E65100" />
            <StatCard value={stats.occupied}            label="🔴 תפוס"   color="#c62828" />
            <StatCard value={stats.driving}             label="🚗 נוסעים" color="#1565C0" />
            <StatCard value={`${stats.occupancy_pct}%`} label="📊 תפוסה" color="#6A1B9A" />
          </div>
        </div>

        {/* Floor canvases */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', gap: 2, background: '#E8EBF5' }}>
          {floors.map(fl => (
            <div key={fl} style={{
              flex: 1, position: 'relative',
              display: 'flex', flexDirection: 'column',
              background: '#1a1f2e',
              margin: 8, borderRadius: 12,
              overflow: 'hidden',
              boxShadow: '0 2px 12px rgba(0,0,0,0.15)',
            }}>
              <div style={{
                padding: '8px 14px',
                fontSize: 13, fontWeight: 700, color: 'rgba(255,255,255,0.6)',
                borderBottom: '1px solid rgba(255,255,255,0.08)',
                background: 'rgba(0,0,0,0.2)',
              }}>קומה {fl}</div>
              <div style={{ flex: 1, minHeight: 0 }}>
                {layout && (
                  <FloorCanvas
                    floor={fl}
                    layout={layout}
                    spots={spots}
                    vehicles={vehicles}
                    onSpotClick={
                      isFreeMode
                        ? (spotId) => {
                            const sp = spots[spotId]
                            if (sp && sp.status === 'OCCUPIED') freeSpot(spotId)
                          }
                        : isDemo
                          ? (spotId) => setStealSpotId(spotId)
                          : undefined
                    }
                    tooltipHint={isFreeMode ? '🖱 לחץ לשחרר חניה' : undefined}
                  />
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Event log */}
        <div style={{
          maxHeight: 140, borderTop: '1px solid #E0E4F0',
          background: '#fff', padding: '10px 16px',
          overflowY: 'auto',
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#aaa', marginBottom: 6, textTransform: 'uppercase' }}>
            לוג אירועים
          </div>
          <EventLog events={eventLog} />
        </div>
      </div>

      {/* Block spot modal */}
      {blockModal && (
        <BlockSpotModal
          spots={spots}
          onBlock={(spotId) => stealSpot(spotId)}
          onClose={() => setBlockModal(false)}
        />
      )}

      {freeModal && (
        <FreeSpotModal
          spots={spots}
          onFree={(spotId) => freeSpot(spotId)}
          onClose={() => setFreeModal(false)}
        />
      )}
    </div>
  )
}
