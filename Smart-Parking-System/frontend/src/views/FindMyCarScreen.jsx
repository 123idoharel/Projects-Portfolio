/**
 * FindMyCarScreen.jsx
 *
 * Pedestrian navigation from current location (entry point) back to parked car.
 *
 * Works for BOTH:
 *   savedSpot.systemSpotId  → full pedestrian routing on graph
 *   savedSpot.manual only   → show manual info card (no routing)
 *
 * UX flow:
 *   1. User sees map with their car pinned
 *   2. Bottom sheet: "מאיפה אתה יוצא?" → pick elevator/entrance
 *   3. Route animates on map with green chevrons
 *   4. Tab toggle: Map ↔ Step-by-step instructions
 *   5. "החלף נקודת יציאה" to recalculate
 */

import { useState, useEffect, useRef, useCallback } from 'react'

// ─────────────────────────────────────────────────────────────────────────────
// Design tokens
// ─────────────────────────────────────────────────────────────────────────────
const C = {
  bg:          '#0f1320',
  surface:     '#141824',
  card:        'rgba(255,255,255,0.04)',
  border:      'rgba(255,255,255,0.08)',
  road:        '#27304a',
  roadSheen:   '#30405e',
  spot:        'rgba(80,100,140,0.25)',
  route:       '#00C853',
  routeGlow:   'rgba(0,200,83,0.20)',
  routeCore:   'rgba(180,255,190,0.55)',
  pin:         '#43A047',
  pinLight:    '#81C784',
  entry:       '#1E88E5',
  text:        '#E8EAF6',
  textMid:     'rgba(232,234,246,0.6)',
  muted:       '#546E7A',
  accent:      '#A5D6A7',
  danger:      '#EF9A9A',
  blue:        '#90CAF9',
}

const font = 'Rubik,system-ui,sans-serif'

// ─────────────────────────────────────────────────────────────────────────────
// Utils
// ─────────────────────────────────────────────────────────────────────────────
function formatDist(m) {
  return m >= 950 ? `${(m/1000).toFixed(1)} ק"מ` : `${Math.round(m)} מ'`
}
function formatTime(mins) {
  if (mins < 1) return 'פחות מדקה'
  return `${Math.round(mins)} דק'`
}

// ─────────────────────────────────────────────────────────────────────────────
// Canvas map renderer
// ─────────────────────────────────────────────────────────────────────────────
function renderMap(canvas, { spots, layout, floor, route, targetSpot, entryPt, walkerPos, anim, topReserved = 0, bottomReserved = 0 }) {
  if (!canvas || !spots) return
  const ctx = canvas.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  const W = canvas.width / dpr
  const H = canvas.height / dpr
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  const floorSpots = Object.values(spots).filter(s => s.floor === floor)
  if (!floorSpots.length) { ctx.fillStyle = C.bg; ctx.fillRect(0,0,W,H); return }

  // ── World bounds ─────────────────────────────────────────────────────────
  const allNodes = layout?.nodes ? Object.values(layout.nodes).filter(n => n.floor === floor) : []
  const xs = [...floorSpots.map(s => s.x), ...allNodes.map(n => n.x)]
  const ys = [...floorSpots.map(s => s.y), ...allNodes.map(n => n.y)]
  if (route) route.filter(p => p.floor === floor).forEach(p => { xs.push(p.x); ys.push(p.y) })

  const PAD  = 10
  const minX = Math.min(...xs) - PAD, maxX = Math.max(...xs) + PAD
  const minY = Math.min(...ys) - PAD, maxY = Math.max(...ys) + PAD
  
  // מתחשבים גם בשטח העליון (הוראות) וגם בשטח התחתון (הבר השחור)
  const availableH = Math.max(10, H - topReserved - bottomReserved)
  const sc   = Math.min(W / (maxX - minX), availableH / (maxY - minY)) * 0.97
  const offX = (W - (maxX - minX) * sc) / 2 - minX * sc
  const offY = topReserved + (availableH - (maxY - minY) * sc) / 2 - minY * sc
  const ws   = (x, y) => [x * sc + offX, y * sc + offY]

  // ── Element sizes — pixel-based with sc floor ─────────────────────────────
  // The layout is ~390 wide × 135 tall world units. At typical canvas sizes
  // sc ≈ 0.85–1.2px/unit, so naive sc-multiplied widths would be <3px.
  // Fixed px minimums ensure everything is legible regardless of canvas size.
  const ROAD_W_MAIN  = Math.max(9,  sc * 3.2)   // main driving lanes
  const ROAD_W_AISLE = Math.max(6,  sc * 2.0)   // aisles (narrower)
  const SPOT_W       = Math.max(5,  sc * 1.4)   // spot half-width  (→ 10px+ wide)
  const SPOT_H       = Math.max(3,  sc * 0.9)   // spot half-height (→ 6px+ tall)
  const SPOT_R       = 1.5                       // corner radius (fixed)

  // ── Background ────────────────────────────────────────────────────────────
  ctx.fillStyle = C.bg
  ctx.fillRect(0, 0, W, H)

  // ── Roads ─────────────────────────────────────────────────────────────────
  if (layout?.edges && layout?.nodes) {
    for (const e of layout.edges) {
      const a = layout.nodes[e.from], b = layout.nodes[e.to]
      if (!a || !b || a.floor !== floor || b.floor !== floor) continue
      const [ax, ay] = ws(a.x, a.y), [bx, by] = ws(b.x, b.y)
      const isAisle = e.type === 'aisle'
      const ow = isAisle ? ROAD_W_AISLE : ROAD_W_MAIN
      const iw = ow * 0.65

      // shadow
      ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(bx,by)
      ctx.strokeStyle = 'rgba(0,0,0,0.45)'; ctx.lineWidth = ow + 2; ctx.lineCap = 'round'; ctx.stroke()
      // surface
      ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(bx,by)
      ctx.strokeStyle = C.road; ctx.lineWidth = ow; ctx.stroke()
      // sheen
      ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(bx,by)
      ctx.strokeStyle = C.roadSheen; ctx.lineWidth = iw; ctx.stroke()
      // centre dash (main roads only, skip if too narrow to see)
      if (!isAisle && ow > 5) {
        ctx.beginPath(); ctx.moveTo(ax,ay); ctx.lineTo(bx,by)
        ctx.strokeStyle = 'rgba(255,255,255,0.07)'; ctx.lineWidth = 1
        ctx.setLineDash([sc * 2.5, sc * 5]); ctx.stroke(); ctx.setLineDash([])
      }
    }
  }

  // ── All spots ─────────────────────────────────────────────────────────────
  for (const s of floorSpots) {
    const [sx, sy] = ws(s.x, s.y)
    if (targetSpot && s.id === targetSpot.id) continue
    ctx.beginPath(); ctx.roundRect(sx - SPOT_W, sy - SPOT_H, SPOT_W * 2, SPOT_H * 2, SPOT_R)
    ctx.fillStyle = C.spot; ctx.fill()
  }

  // ── Route drawing ─────────────────────────────────────────────────────────
  //
  // Two modes:
  //
  // A) No walkerPos (before "הפעל"): draw full route in green as a preview.
  //
  // B) walkerPos available: split the route at the walker's position.
  //    - PAST  (behind walker): dim grey, fading out — already walked
  //    - FUTURE (ahead):        bright green — still to go
  //
  //    Split point: find which segment walkerPos sits on by projecting it
  //    onto each segment (not just nearest waypoint). This gives a
  //    sub-waypoint split so the boundary moves continuously with the
  //    walker, not in discrete jumps. No animation ticker needed.
  //
  // walkerPos comes from /api/position/{session_id} — same for sim and BLE.
  const allRpts = route ? route.filter(p => p.floor === floor) : []

  const drawPath = (pts, width, style) => {
    if (pts.length < 2) return
    ctx.beginPath()
    pts.forEach((p, i) => {
      const [x, y] = ws(p.x, p.y)
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.strokeStyle = style; ctx.lineWidth = width
    ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke()
  }

  if (allRpts.length >= 2 && walkerPos && walkerPos.floor === floor) {
    // ── Find the split point: project walkerPos onto each segment ──────────
    // This finds the closest point ON the polyline (not just nearest node),
    // giving a continuous split as the walker moves along a segment.
    let bestSegIdx = 0, bestFrac = 0, bestDist = Infinity
    for (let i = 0; i < allRpts.length - 1; i++) {
      const a = allRpts[i], b = allRpts[i + 1]
      const abx = b.x - a.x, aby = b.y - a.y
      const len2 = abx * abx + aby * aby
      if (len2 < 0.0001) continue
      // frac ∈ [0,1]: how far along segment the closest point is
      const frac = Math.max(0, Math.min(1,
        ((walkerPos.x - a.x) * abx + (walkerPos.y - a.y) * aby) / len2
      ))
      const px = a.x + frac * abx, py = a.y + frac * aby
      const d = Math.hypot(walkerPos.x - px, walkerPos.y - py)
      if (d < bestDist) { bestDist = d; bestSegIdx = i; bestFrac = frac }
    }

    // split point in world coords
    const sa = allRpts[bestSegIdx], sb = allRpts[bestSegIdx + 1]
    const splitPt = {
      x: sa.x + bestFrac * (sb.x - sa.x),
      y: sa.y + bestFrac * (sb.y - sa.y),
      floor,
    }

    // past = start … splitPt  (dim)
    const pastPts   = [...allRpts.slice(0, bestSegIdx + 1), splitPt]
    // future = splitPt … end  (bright)
    const futurePts = [splitPt, ...allRpts.slice(bestSegIdx + 1)]

    // Draw past: dim grey, thin
    drawPath(pastPts, 3, 'rgba(255,255,255,0.15)')

    // Draw future: full green
    drawPath(futurePts, 14, C.routeGlow)
    drawPath(futurePts,  4, C.route)
    drawPath(futurePts,  1.5, C.routeCore)

  } else if (allRpts.length >= 2) {
    // Preview: full route in green (no walker yet)
    drawPath(allRpts, 14, C.routeGlow)
    drawPath(allRpts,  4, C.route)
    drawPath(allRpts,  1.5, C.routeCore)
  }

  // Target spot highlight + pin
  if (targetSpot && targetSpot.floor === floor) {
    const [tx,ty] = ws(targetSpot.x, targetSpot.y)
    const pulse = 0.5 + 0.5*Math.sin(anim * Math.PI * 2.5)

    // Halo rings
    for (let i = 3; i >= 1; i--) {
      ctx.beginPath(); ctx.arc(tx, ty, (8+i*7)*(sc/10), 0, Math.PI*2)
      ctx.strokeStyle = `rgba(67,160,71,${0.10*pulse/i})`; ctx.lineWidth=2; ctx.stroke()
    }

    // Spot rect (highlighted)
    ctx.beginPath(); ctx.roundRect(tx-6,ty-4.5,12,9,2)
    ctx.fillStyle = C.pin; ctx.fill()
    ctx.strokeStyle='rgba(255,255,255,0.9)'; ctx.lineWidth=1.5; ctx.stroke()

    // Pin stem
    const pr = 11
    ctx.beginPath()
    ctx.arc(tx, ty-pr*1.8, pr, Math.PI*1.1, Math.PI*1.9)
    ctx.lineTo(tx, ty-4)
    ctx.closePath()
    const pinG = ctx.createLinearGradient(tx,ty-pr*3,tx,ty-4)
    pinG.addColorStop(0, '#81C784'); pinG.addColorStop(1, '#2E7D32')
    ctx.fillStyle = pinG; ctx.fill()
    ctx.strokeStyle='rgba(255,255,255,0.85)'; ctx.lineWidth=1.5; ctx.stroke()

    // Car on pin
    ctx.font = `${Math.max(8,pr*0.95)}px sans-serif`
    ctx.textAlign='center'; ctx.textBaseline='middle'
    ctx.fillText('🚗', tx, ty-pr*1.8)

    // Label
    ctx.font = `700 ${Math.max(9,Math.round(sc*1.2))}px ${font}`
    ctx.textAlign='center'; ctx.textBaseline='bottom'
    ctx.shadowColor='rgba(0,0,0,0.9)'; ctx.shadowBlur=8
    ctx.fillStyle='#fff'; ctx.fillText(targetSpot.id, tx, ty-pr*3-4)
    ctx.shadowBlur=0
  }

  // Entry point marker (where user started — shown only when not navigating)
  if (entryPt && !walkerPos) {
    const [ex,ey] = ws(entryPt.x, entryPt.y)
    ctx.beginPath(); ctx.arc(ex,ey, 8,0,Math.PI*2)
    ctx.fillStyle=C.entry; ctx.fill()
    ctx.strokeStyle='rgba(255,255,255,0.9)'; ctx.lineWidth=2; ctx.stroke()
    ctx.font=`bold 9px sans-serif`; ctx.textAlign='center'; ctx.textBaseline='middle'
    ctx.fillStyle='#fff'; ctx.fillText('📍',ex,ey)
  }

  // Walker position marker — shown during active navigation
  // Replace with real position from positioning hardware when available
  if (walkerPos && walkerPos.floor === floor) {
    const [wx,wy] = ws(walkerPos.x, walkerPos.y)
    const pulse = 0.5 + 0.5 * Math.sin(anim * Math.PI * 4)

    // Accuracy ring (outer)
    ctx.beginPath(); ctx.arc(wx, wy, 18, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(33,150,243,${0.10 * pulse})`; ctx.fill()

    // Blue dot
    ctx.beginPath(); ctx.arc(wx, wy, 8, 0, Math.PI * 2)
    const walkerGrad = ctx.createRadialGradient(wx,wy,0, wx,wy,8)
    walkerGrad.addColorStop(0, '#64B5F6')
    walkerGrad.addColorStop(1, '#1565C0')
    ctx.fillStyle = walkerGrad; ctx.fill()
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.5; ctx.stroke()

    // Heading arrow (pointing along route direction)
    if (walkerPos.heading != null) {
      ctx.save()
      ctx.translate(wx, wy)
      ctx.rotate(walkerPos.heading)
      ctx.beginPath()
      ctx.moveTo(0, -12); ctx.lineTo(4, -6); ctx.lineTo(-4, -6)
      ctx.closePath()
      ctx.fillStyle = '#90CAF9'; ctx.fill()
      ctx.restore()
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// EntryPointPicker  (bottom-sheet content)
// ─────────────────────────────────────────────────────────────────────────────
function EntryPointPicker({ entryPoints, selected, loading, error, onSelect }) {
  const floors = [...new Set(entryPoints.map(e => e.floor))].sort()

  return (
    <div style={{ direction:'rtl' }}>
      <div style={{ fontSize:16, fontWeight:800, color:C.text, marginBottom:4 }}>מאיפה אתה יוצא עכשיו?</div>
      <div style={{ fontSize:13, color:C.muted, marginBottom:18 }}>בחר מעלית או כניסה שמולה אתה עומד</div>

      {error && <div style={{ color:C.danger, fontSize:13, marginBottom:12 }}>{error}</div>}
      {loading && <div style={{ color:C.muted, fontSize:13, marginBottom:12 }}>מחשב מסלול...</div>}

      {floors.map(fl => (
        <div key={fl} style={{ marginBottom:16 }}>
          <div style={{ fontSize:11, fontWeight:700, color:C.muted, textTransform:'uppercase', letterSpacing:1, marginBottom:8 }}>
            {fl === 0 ? '▼ קומת קרקע' : `▼ קומה ${fl}`}
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {entryPoints.filter(e => e.floor === fl).map(ep => {
              const isSelected = selected?.id === ep.id
              return (
                <button key={ep.id} onClick={() => onSelect(ep)} style={{
                  display:'flex', alignItems:'center', gap:12,
                  padding:'12px 16px', borderRadius:14,
                  background: isSelected ? 'rgba(33,150,243,0.18)' : C.card,
                  border: `1.5px solid ${isSelected ? 'rgba(33,150,243,0.5)' : C.border}`,
                  cursor:'pointer', fontFamily:font, textAlign:'right',
                  transition:'all 0.15s',
                }}>
                  <div style={{ width:36, height:36, borderRadius:10, background: isSelected ? 'rgba(33,150,243,0.3)' : 'rgba(255,255,255,0.06)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:18, flexShrink:0 }}>
                    {ep.type === 'escalator' ? '🪜' : ep.type === 'elevator' ? '🛗' : '🚶'}
                  </div>
                  <div style={{ flex:1 }}>
                    <div style={{ fontWeight:700, fontSize:14, color: isSelected ? C.blue : C.text }}>{ep.label}</div>
                    <div style={{ fontSize:11, color:C.muted, marginTop:2 }}>
                      {ep.type === 'escalator' ? 'מדרגות נעות' : ep.type === 'elevator' ? 'מעלית' : 'כניסה'} · {fl === 0 ? 'קרקע' : `קומה ${fl}`}
                    </div>
                  </div>
                  {isSelected && <div style={{ color:'#64B5F6', fontSize:18 }}>✓</div>}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// InstructionsList
// ─────────────────────────────────────────────────────────────────────────────
function InstructionsList({ instructions, totalMeters, walkMinutes, onChangeEntry }) {
  return (
    <div style={{ direction:'rtl' }}>
      {/* Summary strip */}
      <div style={{ display:'flex', gap:0, marginBottom:16, background:'rgba(0,200,83,0.07)', borderRadius:14, overflow:'hidden', border:`1px solid rgba(0,200,83,0.18)` }}>
        <div style={{ flex:1, padding:'14px 0', textAlign:'center', borderLeft:`1px solid rgba(0,200,83,0.12)` }}>
          <div style={{ fontSize:20, fontWeight:900, color:C.accent }}>{formatDist(totalMeters)}</div>
          <div style={{ fontSize:11, color:C.muted, marginTop:2 }}>מרחק</div>
        </div>
        <div style={{ flex:1, padding:'14px 0', textAlign:'center' }}>
          <div style={{ fontSize:20, fontWeight:900, color:C.accent }}>{formatTime(walkMinutes)}</div>
          <div style={{ fontSize:11, color:C.muted, marginTop:2 }}>זמן הליכה</div>
        </div>
      </div>

      {/* Steps */}
      {instructions.map((instr, i) => (
        <div key={i} style={{
          display:'flex', alignItems:'center', gap:12,
          padding:'10px 14px', marginBottom:4,
          background: instr.icon === '🎯' ? 'rgba(0,200,83,0.08)' : 'rgba(255,255,255,0.025)',
          borderRadius:10,
          border: `1px solid ${instr.icon === '🎯' ? 'rgba(0,200,83,0.2)' : 'transparent'}`,
        }}>
          <div style={{ width:32, height:32, borderRadius:8, background:'rgba(255,255,255,0.04)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:16, flexShrink:0 }}>
            {instr.icon}
          </div>
          <div style={{ flex:1 }}>
            <div style={{ fontSize:14, color: instr.icon === '🎯' ? C.accent : C.text, fontWeight: instr.icon === '🎯' ? 700 : 400 }}>
              {instr.text}
            </div>
          </div>
          {instr.distance_m > 0 && (
            <div style={{ fontSize:12, color:C.muted, flexShrink:0 }}>{instr.distance_m}מ'</div>
          )}
        </div>
      ))}

      <button onClick={onChangeEntry} style={{ width:'100%', marginTop:16, padding:'12px', borderRadius:12, background:C.card, border:`1px solid ${C.border}`, color:C.muted, fontSize:13, fontWeight:600, cursor:'pointer', fontFamily:font }}>
        🔄 החלף נקודת יציאה
      </button>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// usePositionSource — pedestrian position abstraction layer
//
// Polls GET /api/position/{sessionId} every POLL_MS milliseconds.
// The server returns a PositionSample computed by whatever adapter is active:
//
//   TODAY:  ServerSimulatedPedestrianPositionAdapter
//           — server advances the walker along the route mathematically,
//             writes position to its internal dict, returns it here.
//
//   FUTURE: BlePositionAdapter (swap in server.py — ONE LINE)
//           — phone POSTs BLE RSSI scans to /api/ble_scan, server trilaterates,
//             stores position, returns it here.
//
// This file never changes when switching to real hardware.
// The only change is in server.py: ped_position_adapter = BlePositionAdapter(...)
// ─────────────────────────────────────────────────────────────────────────────

// הקטנו עומס רשת בנייד מ-50 ל-200. מספיק חלקה להולך רגל, ולא ייחסם ע"י הדפדפן בנייד
const POLL_MS = 200 

function usePositionSource({ sessionId, waypoints, active }) {
  const [position, setPosition] = useState(null)

  useEffect(() => {
    if (!active || !waypoints?.length) { setPosition(null); return }
    const wp0 = waypoints[0]
    setPosition({ x: wp0.x, y: wp0.y, floor: wp0.floor, distFromStart: 0, source: 'init' })
  }, [active, waypoints])

  useEffect(() => {
    if (!active || !sessionId) return
    let cancelled = false
    let inFlight  = false

    const pollOnce = async () => {
      if (cancelled || inFlight) return
      inFlight = true
      try {
        const res  = await fetch(`/api/position/${sessionId}?t=${Date.now()}&r=${Math.random()}`, {
          cache: 'no-store',
          headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' }
        })
        const data = await res.json()
        if (cancelled) return
        if (data?.position) {
          setPosition({
            x:             data.position.x,
            y:             data.position.y,
            floor:         data.position.floor,
            heading:       data.position.heading ?? null,
            distFromStart: data.position.distFromStart ?? 0,
            source:        data.position.source ?? 'simulated',
          })
        }
      } catch { /* network blip */ }
      finally { inFlight = false }
    }

    pollOnce() // immediate first poll
    const interval = setInterval(pollOnce, POLL_MS)
    return () => { cancelled = true; clearInterval(interval) }
  }, [active, sessionId])

  return position
}


// ─────────────────────────────────────────────────────────────────────────────
// usePedestrianNav — computes current instruction index from position
// Works with both sim and real positions
// ─────────────────────────────────────────────────────────────────────────────
function usePedestrianNav({ position, waypoints, instructions }) {
  const [stepIdx, setStepIdx] = useState(0)

  useEffect(() => {
    if (!position || !waypoints?.length || !instructions?.length) return

    // Find which waypoint we're closest to
    let closestWpIdx = 0, closestD = Infinity
    for (let i = 0; i < waypoints.length; i++) {
      const d = Math.hypot(waypoints[i].x - position.x, waypoints[i].y - position.y)
      if (d < closestD) { closestD = d; closestWpIdx = i }
    }

    // Map waypoint index → instruction index
    // Instructions are turn-based, each covering a segment of waypoints.
    // We approximate: instruction i covers waypoints[i..i+stride]
    // A more accurate mapping would require storing wp ranges per instruction.
    // For now: use distFromStart against cumulative instruction distances.
    let cumDist = 0
    let instrIdx = 0
    for (let i = 0; i < instructions.length - 1; i++) {
      cumDist += instructions[i].distance_m || 0
      if (position.distFromStart < cumDist) { instrIdx = i; break }
      instrIdx = i + 1
    }
    setStepIdx(Math.min(instrIdx, instructions.length - 1))
  }, [position?.distFromStart])

  return stepIdx
}


// ─────────────────────────────────────────────────────────────────────────────
// PedestrianNavOverlay — full navigation HUD
// Consumes position from usePositionSource (sim today, real tomorrow)
// ─────────────────────────────────────────────────────────────────────────────
function PedestrianNavOverlay({ position, waypoints, instructions, totalMeters, onStop }) {
  // position is polled by the parent component and passed down.
  // This avoids a duplicate fetch and ensures map + HUD are always in sync.
  const stepIdx = usePedestrianNav({ position, waypoints, instructions })

  const instr    = instructions[stepIdx] || {}
  const isLast   = stepIdx >= instructions.length - 1
  const progress = instructions.length > 1 ? stepIdx / (instructions.length - 1) : 1

  // Remaining distance
  const remainingM = Math.max(0, totalMeters - (position?.distFromStart || 0))

  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 20,
      display: 'flex', flexDirection: 'column',
      pointerEvents: 'none',
    }}>
      {/* Top instruction card */}
      <div style={{
        margin: '12px 12px 0',
        background: 'linear-gradient(135deg,rgba(14,20,40,0.97),rgba(20,28,50,0.97))',
        backdropFilter: 'blur(12px)',
        borderRadius: 20,
        border: `1px solid rgba(0,200,83,0.25)`,
        overflow: 'hidden',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        pointerEvents: 'auto',
      }}>
        {/* Progress bar */}
        <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', position: 'relative' }}>
          <div style={{ position:'absolute', left:0, top:0, height:'100%', width:`${progress*100}%`,
                        background: C.route, borderRadius:2, transition:'width 0.5s ease' }} />
        </div>

        <div style={{ padding: '16px 18px', direction: 'rtl' }}>
          <div style={{ fontSize: 11, color: C.muted, marginBottom: 8, fontWeight: 600, display:'flex', alignItems:'center', gap:8 }}>
            <span>שלב {stepIdx + 1} מתוך {instructions.length}</span>
            {remainingM > 2 && <span style={{ color: C.accent }}>· נותרו {formatDist(remainingM)}</span>}
            {position?.source === 'sim' && <span style={{ color:'rgba(255,200,80,0.6)', fontSize:10 }}>● סימ'</span>}
          </div>

          {/* Current instruction */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{
              width:52, height:52, borderRadius:14, fontSize:26, flexShrink:0,
              background: isLast ? 'rgba(0,200,83,0.2)' : 'rgba(255,255,255,0.07)',
              border: `1px solid ${isLast ? 'rgba(0,200,83,0.4)' : 'rgba(255,255,255,0.08)'}`,
              display:'flex', alignItems:'center', justifyContent:'center',
            }}>
              {instr.icon || '⬆️'}
            </div>
            <div style={{ flex:1 }}>
              <div style={{ fontSize:18, fontWeight:900, color: isLast ? C.accent : C.text, lineHeight:1.25 }}>
                {instr.text}
              </div>
              {instr.distance_m > 0 && (
                <div style={{ fontSize:13, color:C.muted, marginTop:3 }}>{instr.distance_m} מטר</div>
              )}
            </div>
          </div>
        </div>

        {/* Next action preview — "בעוד 45מ' → פנה ימינה" */}
        {!isLast && instr.next_action_text && (
          <div style={{
            padding:'9px 18px 11px', borderTop:'1px solid rgba(255,255,255,0.06)',
            display:'flex', alignItems:'center', gap:10, direction:'rtl',
            background:'rgba(255,255,255,0.02)',
          }}>
            <span style={{ fontSize:13, color:C.muted, flexShrink:0 }}>הבא:</span>
            <span style={{ fontSize:14, color:C.textMid, fontWeight:600 }}>
              {instr.next_action_icon} {instr.next_action_text}
            </span>
            {instr.dist_to_next_m > 0 && (
              <span style={{ marginRight:'auto', fontSize:12, color:'rgba(165,214,167,0.7)', fontWeight:700, flexShrink:0 }}>
                בעוד {instr.dist_to_next_m}מ'
              </span>
            )}
          </div>
        )}
      </div>

      {/* Arrived button or Stop button */}
      {isLast ? (
        <div style={{ margin:'auto 12px 40px', display:'flex', pointerEvents:'auto', direction:'rtl' }}>
          <button onClick={onStop} style={{
            flex:1, height:52, borderRadius:16,
            background:'linear-gradient(135deg,#43A047,#2E7D32)',
            border:'none', color:'#fff', fontSize:16, fontWeight:900,
            cursor:'pointer', fontFamily:font,
            boxShadow:'0 6px 20px rgba(46,125,50,0.45)',
          }}>🎯 הגעתי לרכב!</button>
        </div>
      ) : (
        <div style={{ position:'absolute', bottom: 70, right: 16, pointerEvents:'auto' }}>
          <button onClick={onStop} style={{
            background:'rgba(20,28,50,0.85)',
            border:`1px solid rgba(244,67,54,0.3)`,
            borderRadius:24, padding:'10px 16px', color:'#EF9A9A',
            fontSize:13, fontWeight:700, cursor:'pointer', fontFamily:font,
            backdropFilter:'blur(8px)', boxShadow:'0 4px 12px rgba(0,0,0,0.2)'
          }}>✕ בטל ניווט</button>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// ManualOnlyView — when we only have manual text, no system spot
// ─────────────────────────────────────────────────────────────────────────────
function ManualOnlyView({ manual, onBack }) {
  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', background:C.bg, direction:'rtl' }}>
      <NavHeader onBack={onBack} title="🚗 מצא את הרכב שלך" subtitle="מיקום ידני" />
      <div style={{ flex:1, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', padding:'32px 28px', textAlign:'center' }}>
        <div style={{ fontSize:64, marginBottom:24 }}>🅿️</div>
        <div style={{ fontSize:16, color:C.textMid, marginBottom:20 }}>הרכב שלך חנוי ב:</div>
        <div style={{ background:'rgba(255,255,255,0.05)', border:`1px solid ${C.border}`, borderRadius:20, padding:'24px 40px', marginBottom:28 }}>
          {manual?.floor!==undefined && manual?.floor!=='' && (
            <div style={{ marginBottom:10 }}>
              <div style={{ fontSize:11, color:C.muted, marginBottom:4 }}>קומה</div>
              <div style={{ fontSize:28, fontWeight:900, color:C.blue }}>{manual.floor}</div>
            </div>
          )}
          {manual?.row && (
            <div style={{ marginBottom:10 }}>
              <div style={{ fontSize:11, color:C.muted, marginBottom:4 }}>שורה</div>
              <div style={{ fontSize:28, fontWeight:900, color:'#FFD54F' }}>{manual.row.toUpperCase()}</div>
            </div>
          )}
          {manual?.spot && (
            <div>
              <div style={{ fontSize:11, color:C.muted, marginBottom:4 }}>מקום</div>
              <div style={{ fontSize:28, fontWeight:900, color:C.accent }}>{manual.spot}</div>
            </div>
          )}
          {!manual?.floor && !manual?.row && !manual?.spot && (
            <div style={{ color:C.muted, fontSize:15 }}>מיקום לא נשמר</div>
          )}
        </div>
        <div style={{ fontSize:13, color:C.muted }}>💡 עקוב אחר השלטים בחניון כדי להגיע לרכב</div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// NavHeader (shared)
// ─────────────────────────────────────────────────────────────────────────────
function NavHeader({ onBack, title, subtitle }) {
  return (
    <div style={{ padding:'14px 16px', display:'flex', alignItems:'center', gap:12, borderBottom:`1px solid ${C.border}`, background:'rgba(14,18,40,0.98)', direction:'rtl', flexShrink:0 }}>
      <button onClick={onBack} style={{ background:'rgba(255,255,255,0.07)', border:'none', borderRadius:10, padding:'8px 14px', color:C.blue, cursor:'pointer', fontSize:15, flexShrink:0 }}>←</button>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontWeight:800, fontSize:16, color:'#fff', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{title}</div>
        {subtitle && <div style={{ fontSize:12, color:C.blue, marginTop:2 }}>{subtitle}</div>}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main FindMyCarScreen
// ─────────────────────────────────────────────────────────────────────────────
export default function FindMyCarScreen({ savedSpot, layout, spots, onBack }) {
  const systemSpotId  = savedSpot?.systemSpotId
  const manualSpot    = savedSpot?.manual
  const targetSpot    = systemSpotId ? spots[systemSpotId] : null

  const [entryPoints, setEntryPoints] = useState([])
  const [selected, setSelected]       = useState(null)   // chosen entry point object
  const [routeData, setRouteData]     = useState(null)   // {waypoints, total_meters, walk_minutes, instructions}
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const [tab, setTab]                 = useState('map')  // 'map' | 'steps'
  const [showPicker, setShowPicker]   = useState(true)
  const [navActive, setNavActive]     = useState(false)  // dynamic step-by-step nav
  const [walkerPos, setWalkerPos]     = useState(null)   // {x,y,floor,heading?,source}
  const [anim, setAnim]               = useState(0)

  const canvasRef  = useRef(null)
  const animRef    = useRef(null)
  const resizeRef  = useRef(null)

  // If no system spot — show manual fallback
  if (!systemSpotId) {
    return <ManualOnlyView manual={manualSpot} onBack={onBack} />
  }

  const floor = targetSpot?.floor ?? 0
  const displayFloor = (routeData?.waypoints?.[0]?.floor ?? floor)

  // Load entry points
  useEffect(() => {
    fetch('/api/ped_entry_points')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setEntryPoints(d.entry_points || []) })
      .catch(() => {})
  }, [])

  // Animation
  useEffect(() => {
    const tick = () => { setAnim(a => (a + 0.02) % 100); animRef.current = requestAnimationFrame(tick) }
    animRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(animRef.current)
  }, [])

  // Compute route
  // Session ID is generated once per Find My Car session.
  // It ties this browser tab to its server-side position simulation (or real BLE fix).
  // Passed to /api/walk_route so the server starts advancing the position immediately.
  const sessionIdRef = useRef(`ped_${Date.now()}_${Math.random().toString(36).slice(2,7)}`)

  const computeRoute = useCallback(async (ep) => {
    setLoading(true); setError(null); setRouteData(null)
    try {
      const res = await fetch('/api/walk_route', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          from_id:    ep.id,
          spot_id:    systemSpotId,
          session_id: sessionIdRef.current,   // starts server-side position sim
        }),
      })
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'לא נמצא מסלול') }
      const data = await res.json()
      setRouteData(data); setShowPicker(false); setTab('map')
    } catch(e) { setError(e.message) }
    finally { setLoading(false) }
  }, [systemSpotId])

  // ── Position polling ──────────────────────────────────────────────────────
  //
  // Starts ONLY when navActive=true (user pressed "הפעל").
  // Before that, walkerPos stays null so no blue dot is shown and the full
  // route line is visible.
  //
  // ── HOW THIS MAPS TO REAL HARDWARE ────────────────────────────────────────
  // TODAY (simulation):
  //   When navActive becomes true, the server already has the walk route
  //   registered (from /api/walk_route). advance_all() in simulation_loop
  //   immediately starts moving the session. We just start polling here.
  //
  // REAL BLE (future, zero frontend changes needed):
  //   Same polling useEffect, same endpoint.
  //   The phone SDK starts sending RSSI scans to /api/ble_scan when navActive.
  //   Server trilaterates and stores in BlePositionAdapter._positions.
  //   This useEffect reads it — identical code.
  //
  // REAL UWB / camera:
  //   Infrastructure pushes to /api/vehicle_position (or a new /api/ped_position).
  //   Same endpoint shape, same polling here.
  useEffect(() => {
    if (!navActive || !routeData) {
      setWalkerPos(null)   // reset when nav is stopped or route changes
      return
    }
    const sid = sessionIdRef.current
    if (!sid) return

    const waypoints = routeData.waypoints || []
    if (waypoints.length < 1) return

    let cancelled    = false
    let inFlight     = false
    let lastResumeAt = 0
    let lastSrvDist  = null
    let stuckSince   = Date.now()

    // ── Client-side dead-reckoning ────────────────────────────────────────
    // We always run a local walking simulation so the dot moves smoothly the
    // instant the user presses הפעל — even if the server hasn't started yet
    // or is slow to respond. When server positions arrive, we gently sync
    // local distance to the server distance.
    //
    // This is exactly how Waze/Google Maps work: the GPS arrives at 1Hz but
    // the dead-reckoning gives you 60fps motion.
    const WALK_SPEED_MPS = 1.4 * 3.0   // match server: WALK_SPEED * state.speed
    let localDist = 0                  // current dead-reckoned distance from start
    let lastTickT = performance.now()

    // Pre-compute cumulative distances for fast distance → position lookup
    const cumDist = [0]
    for (let i = 1; i < waypoints.length; i++) {
      const a = waypoints[i - 1], b = waypoints[i]
      cumDist.push(cumDist[i - 1] + Math.hypot(b.x - a.x, b.y - a.y))
    }
    const totalDist = cumDist[cumDist.length - 1]

    // Convert a distance-from-start into a {x, y, floor, heading} pose
    const distToPose = (d) => {
      d = Math.max(0, Math.min(d, totalDist))
      // Find segment containing d
      let i = 1
      while (i < cumDist.length && cumDist[i] < d) i++
      i = Math.min(i, waypoints.length - 1)
      const a = waypoints[i - 1], b = waypoints[i]
      const segLen = Math.max(0.001, cumDist[i] - cumDist[i - 1])
      const t = Math.max(0, Math.min(1, (d - cumDist[i - 1]) / segLen))
      return {
        x:             a.x + (b.x - a.x) * t,
        y:             a.y + (b.y - a.y) * t,
        floor:         a.floor,
        heading:       Math.atan2(b.y - a.y, b.x - a.x),
        distFromStart: d,
        source:        'local',
      }
    }

    // Always emit an initial pose at waypoint 0 so the dot appears immediately
    setWalkerPos(distToPose(0))

    // Local rAF loop that advances localDist using wall-clock dt
    let rafId = null
    const tickLocal = (now) => {
      if (cancelled) return
      const dt = Math.min(0.1, (now - lastTickT) / 1000)
      lastTickT = now
      localDist = Math.min(totalDist, localDist + WALK_SPEED_MPS * dt)
      setWalkerPos(distToPose(localDist))
      rafId = requestAnimationFrame(tickLocal)
    }
    rafId = requestAnimationFrame(tickLocal)

    // ── Server resume + sync ─────────────────────────────────────────────
    const fireStartNav = () => {
      lastResumeAt = Date.now()
      fetch('/api/start_navigation', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      }).catch(() => {})
    }
    fireStartNav()

    // Polling: when server position arrives, sync local distance gently
    // (prevents the walker from teleporting on each poll).
    const pollOnce = async () => {
      if (cancelled || inFlight) return
      inFlight = true
      try {
        const res  = await fetch(`/api/position/${sid}?t=${Date.now()}&r=${Math.random()}`, {
          cache: 'no-store',
          headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' }
        })
        const data = await res.json()
        if (cancelled) return
        if (data?.position && typeof data.position.distFromStart === 'number') {
          const srvDist = data.position.distFromStart
          // Soft sync: pull local distance 30% toward server distance per poll.
          // If they're far apart (>3m), snap immediately to avoid lingering drift.
          if (Math.abs(srvDist - localDist) > 3) {
            localDist = srvDist
          } else {
            localDist += (srvDist - localDist) * 0.3
          }
          // Track server stuck-state to retrigger resume if needed
          const moved = lastSrvDist == null || Math.abs(srvDist - lastSrvDist) > 0.05
          if (moved) { lastSrvDist = srvDist; stuckSince = Date.now() }
          else if (Date.now() - stuckSince > 800 && Date.now() - lastResumeAt > 800) {
            fireStartNav()
          }
        }
      } catch { /* offline/blip — local sim keeps the walker moving */ }
      finally { inFlight = false }
    }

    pollOnce()
    const interval = setInterval(pollOnce, 200)

    return () => {
      cancelled = true
      clearInterval(interval)
      if (rafId) cancelAnimationFrame(rafId)
    }
  }, [navActive, routeData])

  const handleSelect = ep => { setSelected(ep); computeRoute(ep) }

  // Resize observer for canvas
  // Sharp canvas: match CSS size × devicePixelRatio
  const resizeCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const parent = canvas.parentElement
    if (!parent) return
    const r = parent.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const w = Math.round(r.width) || 400
    const h = Math.round(r.height) || 360
    // Always update — tab switch can invalidate the context transform
    canvas.width  = w * dpr
    canvas.height = h * dpr
    canvas.style.width  = w + 'px'
    canvas.style.height = h + 'px'
    // DPR scale is applied per-frame in renderMap via setTransform
  }, [])

  useEffect(() => {
    resizeCanvas()
    const canvas = canvasRef.current
    if (!canvas) return
    const ro = new ResizeObserver(() => {
      resizeCanvas()
    })
    ro.observe(canvas.parentElement || canvas)
    resizeRef.current = ro
    return () => ro.disconnect()
  }, [resizeCanvas])

  // Draw map
  // Draw map
  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return
    if (!canvas.width) { canvas.width = 400; canvas.height = 360 }

    // entry point world coords from first waypoint (if route loaded)
    let entryPtCoords = null
    if (routeData?.waypoints?.length) {
      const first = routeData.waypoints[0]
      if (first && first.floor === displayFloor) entryPtCoords = first
    }

    // מחשבים כמה שטח תחתון להשאיר ריק לפי מצב ה-UI כרגע
    let bottomPad = 0
    if (showPicker) bottomPad = Math.min((canvas.height / (window.devicePixelRatio || 1)) * 0.45, 300) // תפריט בחירת יציאה
    else if (navActive) bottomPad = 80 // הקטנו כי עכשיו יש רק כפתור ביטול קטן
    else if (routeData) bottomPad = 80 // הבר השחור של תקציר המסלול

    renderMap(canvas, {
      spots, layout, floor: displayFloor,
      route: routeData?.waypoints || null,
      targetSpot: targetSpot?.floor === displayFloor ? targetSpot : null,
      entryPt: entryPtCoords,
      walkerPos: walkerPos?.floor === displayFloor ? walkerPos : null,
      anim,
      topReserved: navActive ? 170 : 0,
      bottomReserved: bottomPad, // מעבירים את המרווח התחתון המחושב
    })
  }, [spots, layout, displayFloor, routeData, targetSpot, walkerPos, anim, tab, navActive, showPicker])

  const subtitle = targetSpot
    ? `חניה ${targetSpot.id} · קומה ${targetSpot.floor}`
    : `חניה ${systemSpotId}`

  return (
    <div style={{ display:'flex', flexDirection:'column', height:'100%', background:C.bg, direction:'rtl' }}>
      <NavHeader onBack={onBack} title="🚗 מצא את הרכב שלך" subtitle={subtitle} />

      {/* Tab bar — visible only after route loaded */}
      {routeData && (
        <div style={{ display:'flex', background:C.surface, borderBottom:`1px solid ${C.border}`, flexShrink:0 }}>
          {[['map','🗺 מפה'],['steps','📋 הוראות']].map(([t,label]) => (
            <button key={t} onClick={() => setTab(t)} style={{
              flex:1, padding:'10px 0', background:'transparent', border:'none',
              borderBottom: tab===t ? '2px solid #43A047' : '2px solid transparent',
              color: tab===t ? C.accent : C.muted,
              fontWeight: tab===t ? 700 : 500, fontSize:13,
              cursor:'pointer', fontFamily:font,
            }}>{label}</button>
          ))}
        </div>
      )}

      {/* MAP tab — always mounted, hidden when on steps tab to preserve canvas state */}
      <div style={{ flex:1, position:'relative', minHeight:0, display: tab === 'map' ? 'flex' : 'none', flexDirection:'column' }}>
        {/* Aspect-ratio wrapper: layout is ~390×140 world units (≈2.8:1).
            Constraining the canvas to this ratio maximises sc and keeps
            spots/roads crisp — no wasted blank space above/below. */}
        <div style={{ flex:1, position:'relative', minHeight:0, overflow:'hidden' }}>
          {/* Canvas — never unmounted so ResizeObserver and transform stay valid */}
          <canvas ref={canvasRef} style={{ width:'100%', height:'100%', display:'block' }} />
          {/* Floor indicator when multi-floor route */}
          {targetSpot && targetSpot.floor > 0 && (
            <div style={{ position:'absolute', top:10, left:10, background:'rgba(14,18,40,0.88)', borderRadius:10, padding:'5px 12px', fontSize:12, color:C.blue, fontWeight:700 }}>
              קומה {displayFloor}
            </div>
          )}
        </div>{/* end aspect-ratio wrapper */}

          {/* Picker sheet */}
          {showPicker && (
            <div style={{
              position:'absolute', bottom:0, left:0, right:0,
              background:'linear-gradient(0deg,rgba(15,19,32,0.98) 85%,transparent)',
              padding:'20px 20px 48px', maxHeight:'65%', overflowY:'auto',
            }}>
              <EntryPointPicker
                entryPoints={entryPoints}
                selected={selected}
                loading={loading}
                error={error}
                onSelect={handleSelect}
              />
            </div>
          )}

          {/* Route summary chip after route loaded */}
          {/* תפריט ההפעלה - הפך לווידג'ט צף וקומפקטי בצד ימין למטה */}
          {routeData && !showPicker && !navActive && (
            <div style={{
              position:'absolute', bottom: 70, right: 16,
              display:'flex', flexDirection:'column', alignItems:'flex-end', gap:10,
            }}>
              <div style={{
                background:'rgba(14,18,36,0.95)', backdropFilter:'blur(10px)',
                borderRadius:20, padding:'10px 16px',
                border:`1px solid rgba(0,200,83,0.3)`,
                display:'flex', alignItems:'center', gap:14,
                boxShadow:'0 8px 24px rgba(0,0,0,0.3)'
              }}>
                <div style={{ textAlign:'right' }}>
                  <div style={{ fontWeight:800, fontSize:15, color:C.accent }}>
                    {formatDist(routeData.total_meters)} · {formatTime(routeData.walk_minutes)}
                  </div>
                  <div style={{ fontSize:11, color:C.muted, marginTop:2 }}>{selected?.label}</div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    // Flip the UI INSTANTLY so the user sees the navigation
                    // overlay appear the moment they tap the button — even on
                    // a slow mobile network. The fetch is fire-and-forget; we
                    // also retry once from the polling loop if the server hasn't
                    // started moving the walker after a second.
                    setNavActive(true)
                    fetch('/api/start_navigation', {
                      method: 'POST',
                      cache: 'no-store',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ session_id: sessionIdRef.current }),
                    }).catch(() => { /* retried by the poll loop */ })
                  }}
                  style={{
                    background:'linear-gradient(135deg,#43A047,#2E7D32)',
                    borderRadius:14, padding:'12px 20px', color:'#fff',
                    fontSize:15, fontWeight:800, border:'none', cursor:'pointer',
                    boxShadow:'0 4px 12px rgba(46,125,50,0.4)', fontFamily:font,
                    // Force the touch target to behave like a real button on iOS.
                    WebkitTapHighlightColor:'transparent', touchAction:'manipulation',
                    minWidth:90,
                  }}>
                  ▶ הפעל
                </button>
              </div>
              <button onClick={() => setShowPicker(true)}
                style={{
                  background:'rgba(255,255,255,0.08)', borderRadius:16, padding:'8px 16px',
                  border:`1px solid rgba(255,255,255,0.15)`, color:'#E8EAF6',
                  fontSize:12, fontWeight:600, cursor:'pointer', fontFamily:font
                }}>
                🔄 שנה נקודת יציאה
              </button>
            </div>
          )}

          {loading && !showPicker && (
            <div style={{ position:'absolute', top:'50%', left:'50%', transform:'translate(-50%,-50%)', background:'rgba(14,18,32,0.9)', borderRadius:12, padding:'14px 24px', color:C.muted, fontSize:14 }}>
              מחשב מסלול...
            </div>
          )}

          {/* Dynamic navigation overlay */}
          {navActive && routeData && (
            <PedestrianNavOverlay
              position={walkerPos}
              waypoints={routeData.waypoints}
              instructions={routeData.instructions}
              totalMeters={routeData.total_meters}
              onStop={() => { 
                setNavActive(false)
                setShowPicker(true) }}
            />
          )}
        </div>

      {/* STEPS tab */}
      {tab === 'steps' && routeData && (
        <div style={{ flex:1, overflowY:'auto', padding:'16px 16px 28px' }}>
          <InstructionsList
            instructions={routeData.instructions}
            totalMeters={routeData.total_meters}
            walkMinutes={routeData.walk_minutes}
            onChangeEntry={() => { setShowPicker(true); setTab('map') }}
          />
        </div>
      )}
    </div>
  )
}