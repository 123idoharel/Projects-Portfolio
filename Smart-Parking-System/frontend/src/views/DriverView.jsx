/**
 * DriverView.jsx — v8 simplified driver experience
 *
 * Flow:
 *   init      → loading / check saved spot
 *   choose    → DestinationScreen: "קניון" or "משרדים"
 *   offices   → OfficePicker: only shown when multiple office groups exist
 *   badge     → BadgeModal: "האם ברשותך תו נכה?"
 *   nav       → NavigatingScreen (Waze-style driving)
 *   parked    → ParkedScreen (success)
 *   findcar   → FindMyCarScreen (pedestrian navigation back)
 *
 * Key changes from v7:
 *   • No floor selection — algorithm picks floor automatically
 *   • No FloorSelectOverlay
 *   • /api/assign_direct replaces /api/floor_options + /api/assign
 *   • /api/target_groups drives the destination buttons dynamically
 *   • Disability badge question replaces floor selection
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import NavCanvas from './NavCanvas.jsx'
import FindMyCarScreen from './FindMyCarScreen.jsx'
import { api } from '../api/parkingApi.js'

// ─────────────────────────────────────────────────────────────────────────────
// Color palette
// ─────────────────────────────────────────────────────────────────────────────
const CHOOSE_BG = `
  radial-gradient(ellipse at 20% 20%, rgba(244,138,115,0.18) 0%, transparent 55%),
  radial-gradient(ellipse at 80% 10%, rgba(228,91,115,0.13) 0%, transparent 50%),
  radial-gradient(ellipse at 60% 85%, rgba(156,139,224,0.14) 0%, transparent 50%),
  linear-gradient(160deg, #FDF6F0 0%, #F5EEF8 50%, #EEF2FB 100%)
`

const C = {
  mallFrom:    '#796bb0',
  mallTo:      '#7468c5',
  officeFrom:  '#7197e1',
  officeTo:    '#4d6dc5',
  accentFrom:  '#F48A73',
  accentTo:    '#E45B73',
  confirm:     '#6C5CE7',
  cancelBg:    '#F0EFF8',
  cancelText:  '#6C5CE7',
}

// ─────────────────────────────────────────────────────────────────────────────
// Session storage helpers (unchanged from v7)
// ─────────────────────────────────────────────────────────────────────────────
const SAVED_SPOT_KEY  = 'saved_parking_spot_v4'
const SESSION_FLAG    = 'parking_session_active'
const SERVER_TOKEN_KEY = 'parking_server_token'

const _sessionId = (() => {
  let id = sessionStorage.getItem('_parking_tab_id')
  if (!id) { id = Date.now().toString(36); sessionStorage.setItem('_parking_tab_id', id) }
  return id
})()

const saveSpot = d => {
  try { sessionStorage.setItem(SAVED_SPOT_KEY, JSON.stringify({ ...d, _tabId: _sessionId })) } catch {}
}
const saveSpotPersist = d => {
  const payload = { ...d, _away: true }
  try {
    sessionStorage.setItem(SAVED_SPOT_KEY, JSON.stringify({ ...payload, _tabId: _sessionId }))
    localStorage.setItem(SAVED_SPOT_KEY, JSON.stringify(payload))
  } catch {}
}
const clearSpot = () => {
  try { sessionStorage.removeItem(SAVED_SPOT_KEY); localStorage.removeItem(SAVED_SPOT_KEY) } catch {}
}
const _clean = d => {
  const { _tabId, _away, ...rest } = d
  return Object.keys(rest).length > 0 ? rest : null
}
const loadSpot = async () => {
  try {
    const tokenResp = await fetch('/api/server_token').then(r => r.json()).catch(() => null)
    if (tokenResp?.token) {
      const storedToken = localStorage.getItem(SERVER_TOKEN_KEY)
      if (storedToken !== tokenResp.token) {
        sessionStorage.removeItem(SAVED_SPOT_KEY)
        localStorage.removeItem(SAVED_SPOT_KEY)
        localStorage.setItem(SERVER_TOKEN_KEY, tokenResp.token)
        return null
      }
    }
    const s = sessionStorage.getItem(SAVED_SPOT_KEY)
    if (s) { const d = JSON.parse(s); if (d._tabId === _sessionId) return _clean(d) }
    const l = localStorage.getItem(SAVED_SPOT_KEY)
    if (l) { const d = JSON.parse(l); if (d._away === true) return _clean(d) }
    return null
  } catch { return null }
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function resolveManualToSystemId(manual, spots) {
  if (!manual || !spots) return null
  const { floor, row, spot } = manual
  if (!floor && floor !== 0) return null
  const rowUp   = (row || '').toUpperCase().trim()
  const spotNum = (spot || '').trim().replace(/^0+/, '')
  for (const s of Object.values(spots)) {
    const parts = s.id.split('-')
    if (parts.length !== 2) continue
    const sFloor = parts[0].replace('F', '')
    const sRow   = parts[1][0]
    const sNum   = parts[1].slice(1).replace(/^0+/, '')
    if (String(sFloor) === String(floor) && sRow === rowUp && sNum === spotNum) return s.id
  }
  if (rowUp) {
    const cands = Object.values(spots).filter(s => {
      const p = s.id.split('-')
      return p.length === 2 && s.floor === Number(floor) && p[1][0] === rowUp
    })
    if (cands.length === 1) return cands[0].id
  }
  return null
}

// ─────────────────────────────────────────────────────────────────────────────
// OfficePicker — shown only when multiple office groups exist
// ─────────────────────────────────────────────────────────────────────────────
function OfficePicker({ offices, onSelect, onBack }) {
  return (
    <div style={{ minHeight:'100%', background: CHOOSE_BG, display:'flex', alignItems:'flex-start', justifyContent:'center' }}>
      <div style={{ maxWidth:420, width:'100%', padding:'48px 24px 32px', direction:'rtl', textAlign:'center' }}>

        <button
          onClick={onBack}
          style={{ position:'absolute', top:18, right:20, background:'transparent', border:'none',
            fontSize:22, cursor:'pointer', color:'#7B7A8E', lineHeight:1 }}
        >←</button>

        <div style={{ width:62, height:62, background:`linear-gradient(135deg,${C.officeFrom},${C.officeTo})`, borderRadius:'50%',
          display:'inline-flex', alignItems:'center', justifyContent:'center', marginBottom:16,
          boxShadow:'0 6px 20px rgba(77,109,197,0.25)', fontSize:28 }}>🏢</div>

        <div style={{ fontWeight:800, fontSize:28, color:'#2D2A3E', letterSpacing:'-0.5px', marginBottom:6 }}>
          לאיזה מגדל?
        </div>
        <div style={{ fontWeight:500, fontSize:17, color:'#7B7A8E', marginBottom:30 }}>
          בחר את יעד המשרדים שלך
        </div>

        {offices.map(o => (
          <div key={o.id} style={{ marginBottom:12 }}>
            <div
              onClick={() => onSelect(o)}
              style={{
                display:'flex', alignItems:'center', gap:12, padding:'0 20px',
                height:72, borderRadius:14,
                background:`linear-gradient(118deg,${C.officeFrom},${C.officeTo})`,
                color:'#fff', fontWeight:700, fontSize:16,
                boxShadow:'0 4px 14px rgba(77,109,197,0.25)', cursor:'pointer', userSelect:'none',
              }}
              onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
              onMouseUp={e => e.currentTarget.style.transform='scale(1)'}
            >
              <div style={{ width:40, height:40, flexShrink:0, background:'rgba(255,255,255,0.18)',
                borderRadius:10, display:'flex', alignItems:'center', justifyContent:'center', fontSize:20 }}>
                {o.icon}
              </div>
              <div style={{ flex:1, textAlign:'right' }}>{o.label}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// BadgeModal — disability badge question (overlay)
// ─────────────────────────────────────────────────────────────────────────────
function BadgeModal({ onAnswer }) {
  return (
    <div style={{
      position:'fixed', inset:0, background:'rgba(0,0,0,0.48)',
      display:'flex', alignItems:'center', justifyContent:'center',
      zIndex:1000, direction:'rtl',
    }}>
      <div style={{
        background:'#fff', borderRadius:22, width:340, maxWidth:'92vw',
        padding:'28px 24px 24px', boxShadow:'0 20px 60px rgba(0,0,0,0.28)',
        textAlign:'center', direction:'rtl',
      }}>
        <div style={{ fontSize:42, marginBottom:12 }}>♿</div>
        <div style={{ fontWeight:800, fontSize:19, color:'#2D2A3E', marginBottom:8 }}>
          האם ברשותך תו נכה?
        </div>
        <div style={{ fontSize:14, color:'#7B7A8E', marginBottom:24, lineHeight:1.5 }}>
          עם תו נכה נוכל להקצות לך חניה מיוחדת הקרובה ביותר ליעד
        </div>

        <div style={{ display:'flex', gap:12 }}>
          <button
            onClick={() => onAnswer(true)}
            style={{
              flex:1, padding:'14px 0', borderRadius:12,
              background:`linear-gradient(135deg,${C.confirm},#5849c4)`,
              color:'#fff', border:'none', fontSize:15, fontWeight:700,
              cursor:'pointer', fontFamily:'Rubik,sans-serif',
              boxShadow:'0 4px 14px rgba(108,92,231,0.35)',
            }}
            onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
            onMouseUp={e => e.currentTarget.style.transform='scale(1)'}
          >
            ✓ כן
          </button>
          <button
            onClick={() => onAnswer(false)}
            style={{
              flex:1, padding:'14px 0', borderRadius:12,
              background:C.cancelBg, color:C.cancelText,
              border:'none', fontSize:15, fontWeight:700,
              cursor:'pointer', fontFamily:'Rubik,sans-serif',
            }}
            onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
            onMouseUp={e => e.currentTarget.style.transform='scale(1)'}
          >
            לא
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// DestinationScreen — Step 1: "איפה תרצה לחנות היום?"
// ─────────────────────────────────────────────────────────────────────────────
function DestinationScreen({ targetGroups, onPickMall, onPickOffices, loading, error }) {
  const { mall = [], offices = [] } = targetGroups || {}

  const mallItems     = mall.filter(m => !m.group.includes('escalator'))
  const escalatorItems = mall.filter(m => m.group.includes('escalator'))
  const hasOffices    = offices.length > 0

  return (
    <div style={{ minHeight:'100%', background: CHOOSE_BG, display:'flex', alignItems:'flex-start', justifyContent:'center', position:'relative' }}>
      <div style={{ maxWidth:420, width:'100%', padding:'48px 24px 32px', direction:'rtl', textAlign:'center' }}>

        {/* Welcome icon */}
        <div style={{
          width:62, height:62,
          background:`linear-gradient(135deg,${C.accentFrom},${C.accentTo})`,
          borderRadius:'50%', display:'inline-flex', alignItems:'center', justifyContent:'center',
          marginBottom:16, boxShadow:'0 6px 20px rgba(200,64,64,0.25)', fontSize:28,
        }}>🅿️</div>

        <div style={{ fontWeight:800, fontSize:34, color:'#2D2A3E', letterSpacing:'-0.5px', marginBottom:6 }}>
          ברוך הבא
        </div>
        <div style={{ fontWeight:500, fontSize:18, color:'#7B7A8E', marginBottom:32 }}>
          איפה תרצה לחנות היום?
        </div>

        {error && (
          <div style={{ background:'rgba(244,67,54,0.08)', border:'1px solid rgba(244,67,54,0.3)',
            borderRadius:10, padding:'10px 16px', marginBottom:16, color:'#c62828', fontSize:14 }}>
            {error}
          </div>
        )}

        {loading
          ? <div style={{ color:'#9B99B0', fontSize:16, padding:30 }}>מחפש חניה...</div>
          : (
            <>
              {/* Mall button */}
              {mallItems.map(item => (
                <div key={item.id} style={{ marginBottom:12 }}>
                  <div
                    onClick={() => onPickMall(item)}
                    style={{
                      display:'flex', alignItems:'center', gap:14, padding:'0 20px',
                      height:76, borderRadius:16,
                      background:`linear-gradient(118deg,${C.mallFrom},${C.mallTo})`,
                      color:'#fff', fontWeight:700, fontSize:17,
                      boxShadow:'0 4px 16px rgba(116,104,197,0.30)', cursor:'pointer', userSelect:'none',
                    }}
                    onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
                    onMouseUp={e => e.currentTarget.style.transform='scale(1)'}
                  >
                    <div style={{ width:44, height:44, flexShrink:0, background:'rgba(255,255,255,0.18)',
                      borderRadius:11, display:'flex', alignItems:'center', justifyContent:'center', fontSize:22 }}>
                      {item.icon}
                    </div>
                    <div style={{ flex:1, textAlign:'right' }}>קניון</div>
                  </div>
                </div>
              ))}

              {/* Escalator */}
              {escalatorItems.map(item => (
                <div key={item.id} style={{ marginBottom:12 }}>
                  <div
                    onClick={() => onPickMall(item)}
                    style={{
                      display:'flex', alignItems:'center', gap:14, padding:'0 20px',
                      height:68, borderRadius:14,
                      background:`linear-gradient(118deg,${C.accentFrom},${C.accentTo})`,
                      color:'#fff', fontWeight:700, fontSize:15,
                      boxShadow:'0 3px 12px rgba(228,91,115,0.22)', cursor:'pointer', userSelect:'none',
                    }}
                    onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
                    onMouseUp={e => e.currentTarget.style.transform='scale(1)'}
                  >
                    <div style={{ width:40, height:40, flexShrink:0, background:'rgba(255,255,255,0.18)',
                      borderRadius:10, display:'flex', alignItems:'center', justifyContent:'center', fontSize:20 }}>
                      {item.icon}
                    </div>
                    <div style={{ flex:1, textAlign:'right' }}>{item.label}</div>
                  </div>
                </div>
              ))}

              {/* Offices button */}
              {hasOffices && (
                <div style={{ marginBottom:12 }}>
                  <div
                    onClick={() => onPickOffices()}
                    style={{
                      display:'flex', alignItems:'center', gap:14, padding:'0 20px',
                      height:76, borderRadius:16,
                      background:`linear-gradient(118deg,${C.officeFrom},${C.officeTo})`,
                      color:'#fff', fontWeight:700, fontSize:17,
                      boxShadow:'0 4px 16px rgba(77,109,197,0.28)', cursor:'pointer', userSelect:'none',
                    }}
                    onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
                    onMouseUp={e => e.currentTarget.style.transform='scale(1)'}
                  >
                    <div style={{ width:44, height:44, flexShrink:0, background:'rgba(255,255,255,0.18)',
                      borderRadius:11, display:'flex', alignItems:'center', justifyContent:'center', fontSize:22 }}>
                      🏢
                    </div>
                    <div style={{ flex:1, textAlign:'right' }}>משרדים</div>
                  </div>
                </div>
              )}
            </>
          )
        }

        <div style={{ marginTop:32, fontSize:12, color:'#C0BECC' }}>Smart Parking System</div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// SpotBadge — shown in the nav top bar
// ─────────────────────────────────────────────────────────────────────────────
function SpotBadge({ spotLabel }) {
  if (!spotLabel) return null
  return (
    <div style={{
      position:'absolute', top: 35, left:'50%', transform:'translateX(-50%)',
      //position:'absolute', bottom:24, left:'50%', transform:'translateX(-50%)',
      background:'rgba(20,28,50,0.92)', backdropFilter:'blur(8px)',
      border:'1px solid rgba(76,175,80,0.4)', borderRadius:24,
      padding:'8px 20px', textAlign:'center', whiteSpace:'nowrap',
      boxShadow:'0 4px 16px rgba(0,0,0,0.3)',
    }}>
      <div style={{ fontSize:11, color:'rgba(200,230,201,0.7)', fontWeight:600, marginBottom:2 }}>החניה שלך</div>
      <div style={{ fontSize:17, fontWeight:900, color:'#C8E6C9', letterSpacing:0.5 }}>🅿️ {spotLabel}</div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// ManualSpotModal (unchanged from v7)
// ─────────────────────────────────────────────────────────────────────────────
function ManualSpotModal({ spots, onConfirm, onSkip, onCancel }) {
  const [step, setStep] = useState('floor')
  const [floor, setFloor] = useState(null)
  const [row, setRow]     = useState(null)
  const [num, setNum]     = useState(null)

  const floors  = [...new Set(Object.values(spots).map(s => s.floor))].sort()
  const rows    = floor !== null
    ? [...new Set(Object.values(spots).filter(s => s.floor === floor).map(s => s.id.split('-')[1]?.[0]).filter(Boolean))].sort()
    : []
  const numbers = (floor !== null && row)
    ? Object.values(spots).filter(s => {
        const p = s.id.split('-'); return s.floor === floor && p[1]?.[0] === row
      }).map(s => ({ id: s.id, num: s.id.split('-')[1]?.slice(1) || '' }))
        .sort((a, b) => a.num.localeCompare(b.num, undefined, { numeric: true }))
    : []

  const pillBase = {
    padding:'10px 18px', borderRadius:24, fontSize:15, fontWeight:700,
    cursor:'pointer', fontFamily:'Rubik,sans-serif', border:'none',
    transition:'all 0.15s', userSelect:'none',
  }
  const pill = (active) => ({
    ...pillBase,
    background: active ? 'rgba(33,150,243,0.9)' : 'rgba(255,255,255,0.08)',
    color: active ? '#fff' : 'rgba(255,255,255,0.75)',
    boxShadow: active ? '0 4px 14px rgba(33,150,243,0.4)' : 'none',
  })

  const stepLabel = { floor:'באיזו קומה?', row:'באיזו שורה?', spot:'מהו מספר החניה?' }
  const handleFloor = f => { setFloor(f); setRow(null); setNum(null); setStep('row') }
  const handleRow   = r => { setRow(r);   setNum(null); setStep('spot') }
  const handleSpot  = s => { setNum(s.id); setStep('confirm') }
  const summary = num ? Object.values(spots).find(s => s.id === num) : null

  return (
    <div style={{ position:'fixed', inset:0, zIndex:100, background:'rgba(8,12,24,0.72)',
      backdropFilter:'blur(6px)', display:'flex', alignItems:'flex-end', justifyContent:'center' }}
      onClick={onCancel}>
      <div style={{ width:'100%', maxWidth:480,
        background:'linear-gradient(160deg,#181f35 0%,#111827 100%)',
        borderRadius:'28px 28px 0 0', padding:'28px 24px 40px',
        direction:'rtl', border:'1px solid rgba(255,255,255,0.07)', borderBottom:'none' }}
        onClick={e => e.stopPropagation()}>
        <div style={{ width:40, height:4, background:'rgba(255,255,255,0.15)', borderRadius:2, margin:'0 auto 20px' }} />
        <div style={{ fontSize:20, fontWeight:800, color:'#fff', marginBottom:4 }}>📍 איפה חנית?</div>
        <div style={{ fontSize:13, color:'rgba(255,255,255,0.45)', marginBottom:24 }}>
          בחר את מיקום החניה שלך כדי שנוכל להוביל אותך אליה בחזרה
        </div>
        {(step==='row'||step==='spot'||step==='confirm') && (
          <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:20 }}>
            <span onClick={() => setStep('floor')} style={{ fontSize:13, color:'#64B5F6', cursor:'pointer', fontWeight:600 }}>קומה {floor}</span>
            {(step==='spot'||step==='confirm') && (
              <><span style={{ color:'rgba(255,255,255,0.25)' }}>›</span>
              <span onClick={() => setStep('row')} style={{ fontSize:13, color:'#64B5F6', cursor:'pointer', fontWeight:600 }}>שורה {row}</span></>
            )}
            {step==='confirm' && (
              <><span style={{ color:'rgba(255,255,255,0.25)' }}>›</span>
              <span style={{ fontSize:13, color:'#A5D6A7', fontWeight:600 }}>{num}</span></>
            )}
          </div>
        )}
        {step !== 'confirm' && (
          <>
            <div style={{ fontSize:14, color:'rgba(255,255,255,0.55)', marginBottom:14 }}>{stepLabel[step]}</div>
            <div style={{ display:'flex', flexWrap:'wrap', gap:10, marginBottom:24 }}>
              {step==='floor' && floors.map(f => (
                <button key={f} style={pill(floor===f)} onClick={() => handleFloor(f)}>
                  {f===0 ? 'קרקע (0)' : `קומה ${f}`}
                </button>
              ))}
              {step==='row' && rows.map(r => (
                <button key={r} style={pill(row===r)} onClick={() => handleRow(r)}>שורה {r}</button>
              ))}
              {step==='spot' && numbers.map(s => (
                <button key={s.id} style={{ ...pill(num===s.id), minWidth:54, padding:'10px 12px' }} onClick={() => handleSpot(s)}>
                  {s.num}
                </button>
              ))}
            </div>
          </>
        )}
        {step==='confirm' && summary && (
          <div style={{ marginBottom:24 }}>
            <div style={{ background:'rgba(67,160,71,0.12)', border:'1px solid rgba(67,160,71,0.3)',
              borderRadius:16, padding:'20px 24px', textAlign:'center', marginBottom:16 }}>
              <div style={{ fontSize:13, color:'rgba(255,255,255,0.5)', marginBottom:8 }}>הרכב שלך נמצא בחניה</div>
              <div style={{ fontSize:28, fontWeight:900, color:'#A5D6A7', letterSpacing:1 }}>{summary.id}</div>
              <div style={{ fontSize:13, color:'rgba(255,255,255,0.4)', marginTop:6 }}>
                קומה {summary.floor} · שורה {summary.id.split('-')[1]?.[0]} · מקום {summary.id.split('-')[1]?.slice(1)}
              </div>
            </div>
            <button onClick={() => onConfirm({ systemSpotId:summary.id, manual:{
              floor:String(summary.floor), row:summary.id.split('-')[1]?.[0], spot:summary.id.split('-')[1]?.slice(1)
            }})}
              style={{ width:'100%', padding:'15px', borderRadius:14,
                background:'linear-gradient(135deg,#43A047,#2E7D32)', color:'#fff', border:'none',
                fontSize:16, fontWeight:700, cursor:'pointer', fontFamily:'Rubik,sans-serif',
                boxShadow:'0 4px 14px rgba(46,125,50,0.3)', marginBottom:10 }}>
              ✅ שמור מיקום וסיים
            </button>
            <button onClick={() => setStep('spot')} style={{ width:'100%', padding:'11px', borderRadius:14,
              background:'transparent', color:'rgba(255,255,255,0.45)',
              border:'1px solid rgba(255,255,255,0.1)', fontSize:13, fontWeight:600,
              cursor:'pointer', fontFamily:'Rubik,sans-serif' }}>
              ← תיקון
            </button>
          </div>
        )}
        <div style={{ display:'flex', gap:10 }}>
          <button onClick={onSkip} style={{ flex:1, padding:'12px', borderRadius:12,
            background:'rgba(255,255,255,0.05)', color:'rgba(255,255,255,0.4)',
            border:'1px solid rgba(255,255,255,0.08)', fontSize:13, fontWeight:600,
            cursor:'pointer', fontFamily:'Rubik,sans-serif' }}>
            סיים בלי לשמור
          </button>
          <button onClick={onCancel} style={{ flex:1, padding:'12px', borderRadius:12,
            background:'transparent', color:'rgba(255,255,255,0.35)',
            border:'1px solid rgba(255,255,255,0.07)', fontSize:13,
            cursor:'pointer', fontFamily:'Rubik,sans-serif' }}>
            חזור לניווט
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// NavigatingScreen (unchanged logic from v7; spotLabel added to display)
// ─────────────────────────────────────────────────────────────────────────────
function NavigatingScreen({ userVehicle, layout, spots, onCancel, spotLabel }) {
  const displayVehicle = userVehicle
  const spotId   = displayVehicle?.assigned_spot || '---'
  const targetInfo = displayVehicle?.assigned_target_info
  const isRecalc = !userVehicle?.assigned_spot

  return (
    <div style={{ position:'relative', width:'100%', height:'100%', background:'#0e1218', overflow:'hidden' }}>
      <NavCanvas layout={layout} spots={spots} userVehicle={displayVehicle} />

      {/* יעד וקומה - מוצמדים למעלה מימין */}
      <div style={{ 
        position:'absolute', top:20, right:16, 
        display:'flex', flexDirection: 'column', alignItems:'flex-start', gap:8,
        direction:'rtl', pointerEvents:'none' 
      }}>
        {targetInfo && (
          <div style={{ background:'rgba(20,28,50,0.82)', backdropFilter:'blur(8px)',
            border:'1px solid rgba(255,255,255,0.1)', borderRadius:16, padding:'6px 12px',
            fontSize:12, fontWeight:700, color:'#90CAF9', alignSelf:'flex-start' }}>
            {targetInfo.type === 'escalator' ? '🪜' : '🛗'} {targetInfo.label || targetInfo.id}
          </div>
        )}
        
        {(() => {
          const vFloor  = displayVehicle?.floor ?? 0
          const spotObj = spotId !== '---' ? spots[spotId] : null
          const tFloor  = spotObj != null ? spotObj.floor : null
          if (tFloor != null && tFloor !== vFloor) {
            const fl = tFloor === 0 ? 'קומת קרקע' : `קומה ${tFloor}`
            return (
              <div style={{ background:'rgba(255,152,0,0.82)', backdropFilter:'blur(8px)',
                border:'1px solid rgba(255,200,50,0.4)', borderRadius:16, padding:'6px 12px',
                fontSize:12, fontWeight:700, color:'#fff', alignSelf:'flex-start' }}>⬆️ {fl}</div>
            )
          }
          return null
        })()}
      </div>

      {/* כפתור ביטול בלבד - קטן, עדין ומרוחק מהמרכז */}
      <div style={{ position:'absolute', bottom: 140, right:12,
        display:'flex', flexDirection:'column', gap:8 }}>
        <button onClick={onCancel}
          style={{ background:'rgba(20,28,50,0.88)', border:'1px solid rgba(255,255,255,0.15)',
            borderRadius:16, padding:'8px 16px', color:'rgba(255,255,255,0.7)', fontSize:12,
            fontWeight:600, cursor:'pointer', fontFamily:'Rubik,sans-serif', backdropFilter:'blur(8px)' }}>
          ✕ ביטול נסיעה
        </button>
      </div>
    </div>
  )
}
// ─────────────────────────────────────────────────────────────────────────────
// ParkedScreen (unchanged from v7)
// ─────────────────────────────────────────────────────────────────────────────
function ParkedScreen({ savedSpot, onNewSession, onFindMyCar }) {
  const sid     = savedSpot?.systemSpotId
  const manual  = savedSpot?.manual
  const isEmpty = !sid && !manual

  let title = 'חנית בהצלחה!'
  let spotDisplay = null
  let subline = null

  if (sid) {
    spotDisplay = sid
    if (manual) subline = `קומה ${manual.floor} · שורה ${manual.row} · מקום ${manual.spot}`
  } else if (manual) {
    title = 'הניווט הסתיים'
    spotDisplay = [
      manual.floor && `קומה ${manual.floor}`,
      manual.row   && `שורה ${manual.row}`,
      manual.spot  && `מקום ${manual.spot}`,
    ].filter(Boolean).join(' · ') || null
  }

  const canNavigate = !!sid

  return (
    <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center',
      width:'100%', direction:'rtl', textAlign:'center', padding:'40px 28px' }}>
      <div style={{ width:80, height:80, borderRadius:22,
        background:'linear-gradient(135deg,#66BB6A,#2E7D32)',
        display:'flex', alignItems:'center', justifyContent:'center',
        fontSize:40, marginBottom:20, boxShadow:'0 8px 24px rgba(46,125,50,0.28)' }}>✅</div>

      <div style={{ fontWeight:800, fontSize:28, color:'#2E7D32', marginBottom:4 }}>{title}</div>
      <div style={{ fontSize:14, color:'#9B99B0', marginBottom:16 }}>
        {isEmpty ? 'המיקום לא נשמר' : 'הרכב שלך נמצא:'}
      </div>

      {spotDisplay && (
        <div style={{ background:'rgba(46,125,50,0.07)', border:'1.5px solid rgba(46,125,50,0.2)',
          borderRadius:16, padding:'16px 32px', marginBottom:10, width:'100%', maxWidth:320 }}>
          <div style={{ fontWeight:900, fontSize:26, color:'#2D2A3E', letterSpacing:0.5 }}>{spotDisplay}</div>
          {subline && <div style={{ fontSize:12, color:'#888', marginTop:4 }}>{subline}</div>}
        </div>
      )}

      <div style={{ width:'100%', maxWidth:320, marginTop:spotDisplay ? 16 : 8 }}>
        <button onClick={onFindMyCar}
          style={{ width:'100%', padding:'15px', borderRadius:14,
            background: canNavigate ? 'linear-gradient(135deg,#1E88E5,#1565C0)' : 'linear-gradient(135deg,#78909C,#546E7A)',
            color:'#fff', border:'none', fontSize:16, fontWeight:700, cursor:'pointer',
            fontFamily:'Rubik,sans-serif',
            boxShadow: canNavigate ? '0 4px 14px rgba(21,101,192,0.3)' : 'none', marginBottom:12 }}
          onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
          onMouseUp={e => e.currentTarget.style.transform='scale(1)'}>
          {canNavigate ? '🗺 הובל אותי לרכב' : '🗺 הצג מפה'}
        </button>
        <button onClick={onNewSession}
          style={{ width:'100%', padding:'13px', borderRadius:14, background:'transparent',
            color:'#9B99B0', border:'1.5px solid #E0E4F0', fontSize:15, fontWeight:600,
            cursor:'pointer', fontFamily:'Rubik,sans-serif' }}
          onMouseDown={e => e.currentTarget.style.transform='scale(0.97)'}
          onMouseUp={e => e.currentTarget.style.transform='scale(1)'}>
          🔄 הזמנה חדשה
        </button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main DriverView
// ─────────────────────────────────────────────────────────────────────────────
export default function DriverView({ layout, spots, vehicles }) {
  const [mode, setMode]                 = useState('init')
  const [savedSpot, setSavedSpot]       = useState(null)
  const [targetGroups, setTargetGroups] = useState({ mall:[], offices:[] })
  const [pendingGroup, setPendingGroup] = useState(null)  // selected group before badge
  const [spotLabel, setSpotLabel]       = useState(null)  // "קומה 0 · B06"
  const [loading, setLoading]           = useState(false)
  const [error, setError]               = useState(null)

  const USER_ID     = 'user_car_1'
  const userVehicle = vehicles[USER_ID] || null
  const cleanedUp   = useRef(false)
  const defaultEnt  = layout?.meta?.default_entrance || layout?.entrances?.[0] || ''

  // ── Mount: check server token, restore session, load target groups ─────────
  useEffect(() => {
    if (cleanedUp.current) return
    cleanedUp.current = true
    const init = async () => {
      // Check saved spot
      const saved = await loadSpot()
      if (saved) { setSavedSpot(saved); setMode('parked'); return }

      // Load target groups for the destination screen
      try {
        const data = await fetch('/api/target_groups').then(r => r.json())
        setTargetGroups(data)
      } catch {}

      setMode('choose')
      fetch('/api/clean_session', { method:'POST' }).catch(() => {})
    }
    init()
  }, [])

  // ── Server → UI state transitions ─────────────────────────────────────────
  useEffect(() => {
    if (!userVehicle) return
    if (userVehicle.status === 'DRIVING' && mode === 'badge') setMode('nav')
    if (userVehicle.status === 'PARKED'  && mode === 'nav') {
      if (NavigatingScreen._modalOpenRef?.current) return
      const d = { systemSpotId: userVehicle.assigned_spot }
      setSavedSpot(d); saveSpotPersist(d); setMode('parked')
    }
  }, [userVehicle?.status])

  // ── Step 1: user picks "קניון" or "משרדים" ────────────────────────────────
  const handlePickMall = useCallback((item) => {
    setError(null)
    setPendingGroup(item.group)
    setMode('badge')
  }, [])

  const handlePickOffices = useCallback(() => {
    const { offices } = targetGroups
    if (offices.length === 1) {
      // Only one office type — skip sub-picker
      setPendingGroup(offices[0].group)
      setMode('badge')
    } else {
      setMode('offices')
    }
  }, [targetGroups])

  const handlePickOffice = useCallback((item) => {
    setPendingGroup(item.group)
    setMode('badge')
  }, [])

  // ── Step 2 (optional): office sub-picker → already sets pendingGroup ───────

  // ── Step 3: badge answer → call assign_direct ─────────────────────────────
  const handleBadgeAnswer = useCallback(async (hasDisability) => {
    if (!pendingGroup) return
    setLoading(true); setError(null)
    try {
      const resp = await fetch('/api/assign_direct', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          target_group:   pendingGroup,
          entrance_id:    defaultEnt,
          has_disability: hasDisability,
        }),
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err.detail || 'לא נמצאה חניה פנויה')
      }
      const data = await resp.json()
      if (data.spot_label) setSpotLabel(data.spot_label)
      setMode('nav')
    } catch (e) {
      setError(e.message || 'שגיאה בחיפוש חניה')
      setMode('choose')
    } finally {
      setLoading(false)
    }
  }, [pendingGroup, defaultEnt])

  // ── Parked elsewhere ──────────────────────────────────────────────────────
  const handleParkedElsewhere = useCallback(async (data) => {
    const reservedSpotId = userVehicle?.assigned_spot
    if (reservedSpotId) {
      try { await fetch('/api/free', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ spot_id: reservedSpotId }) }) } catch {}
    }
    try { await fetch('/api/remove', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ vid: USER_ID }) }) } catch {}
    if (data?.systemSpotId) {
      try { await fetch('/api/occupy_manual', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ spot_id: data.systemSpotId }) }) } catch {}
    }
    const d = data || {}
    setSavedSpot(d); saveSpotPersist(d); setMode('parked')
  }, [userVehicle])

  const handleCancel = useCallback(async () => {
    const sid = userVehicle?.assigned_spot
    if (sid) {
      try { await fetch('/api/free', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ spot_id: sid }) }) } catch {}
    }
    try { await fetch('/api/remove', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ vid: USER_ID }) }) } catch {}
    setSpotLabel(null)
    setMode('choose')
  }, [userVehicle])

  const handleNewSession = useCallback(async () => {
    clearSpot(); setSavedSpot(null); setSpotLabel(null)
    try { await fetch('/api/remove', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ vid: USER_ID }) }) } catch {}
    setMode('choose')
  }, [])

  // ── Render ─────────────────────────────────────────────────────────────────
  if (mode === 'init') return <div style={{ height:'100%', background: CHOOSE_BG }} />

  if (mode === 'choose') {
    return (
      <div style={{ height:'100%', overflowY:'auto', position:'relative' }}>
        <DestinationScreen
          targetGroups={targetGroups}
          onPickMall={handlePickMall}
          onPickOffices={handlePickOffices}
          loading={loading}
          error={error}
        />
      </div>
    )
  }

  if (mode === 'offices') {
    return (
      <div style={{ height:'100%', overflowY:'auto', position:'relative' }}>
        <OfficePicker
          offices={targetGroups.offices}
          onSelect={handlePickOffice}
          onBack={() => setMode('choose')}
        />
      </div>
    )
  }

  if (mode === 'badge') {
    return (
      <div style={{ height:'100%', background: CHOOSE_BG, position:'relative' }}>
        {loading && (
          <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center',
            justifyContent:'center', zIndex:200, background:'rgba(253,246,240,0.85)' }}>
            <div style={{ textAlign:'center' }}>
              <div style={{ fontSize:40, marginBottom:12 }}>🔍</div>
              <div style={{ fontSize:16, fontWeight:700, color:'#2D2A3E' }}>מחפש את החניה הטובה ביותר...</div>
            </div>
          </div>
        )}
        <BadgeModal onAnswer={handleBadgeAnswer} />
      </div>
    )
  }

  if (mode === 'nav' && userVehicle) {
    return (
      <NavigatingScreen
        userVehicle={userVehicle}
        layout={layout}
        spots={spots}
        userId={USER_ID}
        spotLabel={spotLabel}
        onParkedElsewhere={handleParkedElsewhere}
        onCancel={handleCancel}
      />
    )
  }

  if (mode === 'findcar') {
    return (
      <FindMyCarScreen
        savedSpot={savedSpot}
        layout={layout}
        spots={spots}
        onBack={() => setMode('parked')}
      />
    )
  }

  if (mode === 'parked') {
    return (
      <div style={{ height:'100%', background: CHOOSE_BG, display:'flex', alignItems:'center' }}>
        <ParkedScreen
          savedSpot={savedSpot}
          onNewSession={handleNewSession}
          onFindMyCar={() => setMode('findcar')}
        />
      </div>
    )
  }

  // Fallback
  return <div style={{ height:'100%', background: CHOOSE_BG }} />
}
