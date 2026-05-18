/**
 * ParkingRenderer.js
 * Operator-view 2D top-down renderer — sharper visuals, better contrast, Waze-style arrow vehicle
 */

const SPOT_COLORS = {
  FREE:     { fill: '#43A047', stroke: '#2E7D32', glow: 'rgba(67,160,71,0)' },
  RESERVED: { fill: '#FB8C00', stroke: '#E65100', glow: 'rgba(251,140,0,0.25)' },
  OCCUPIED: { fill: '#E53935', stroke: '#C62828', glow: 'rgba(229,57,53,0)' },
}

const ELEVATOR_COLORS = {
  tower_a:          '#1565C0',
  tower_b:          '#7B1FA2',
  offices:          '#00897B',
  offices_a:        '#0277BD',
  offices_b:        '#6A1B9A',
  street:           '#E65100',
  mall_elevator:    '#AD1457',
  mall_escalator:   '#C84B73',
  default:          '#1976D2',
}

const EXIT_COLORS = {
  EXIT_ROTHSCHILD: '#2E7D32',
  EXIT_BEN_GURION: '#C62828',
  default:         '#7B1FA2',
}

export class ParkingRenderer {
  constructor(canvas, worldBounds) {
    this.canvas = canvas
    this.ctx    = canvas.getContext('2d')
    this.bounds = worldBounds
    this._updateTransform()
  }

  _updateTransform() {
    const { minX, minY, maxX, maxY } = this.bounds
    const W = this.canvas.width
    const H = this.canvas.height
    const ww = maxX - minX
    const wh = maxY - minY
    const scale = Math.min(W / ww, H / wh) * 0.90
    this.scale  = scale
    this.offX   = (W - ww * scale) / 2 - minX * scale
    this.offY   = (H - wh * scale) / 2 - minY * scale
  }

  resize(w, h) {
    this.canvas.width  = w
    this.canvas.height = h
    this._updateTransform()
  }

  ws(x, y)  { return [x * this.scale + this.offX, y * this.scale + this.offY] }
  sw(sx, sy) { return [(sx - this.offX) / this.scale, (sy - this.offY) / this.scale] }
  scaleV(v)  { return v * this.scale }

  clear() {
    const ctx = this.ctx
    const W = this.canvas.width, H = this.canvas.height
    // Rich dark gradient background
    const bg = ctx.createLinearGradient(0, 0, 0, H)
    bg.addColorStop(0, '#141824')
    bg.addColorStop(1, '#0f1320')
    ctx.fillStyle = bg
    ctx.fillRect(0, 0, W, H)

    // Subtle grid
    ctx.strokeStyle = 'rgba(255,255,255,0.022)'
    ctx.lineWidth = 1
    const step = 40
    for (let x = 0; x < W; x += step) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke()
    }
    for (let y = 0; y < H; y += step) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke()
    }
  }

  drawRoads(nodes, edges, floor) {
    const ctx = this.ctx
    const fn = Object.values(nodes).filter(n => n.floor === floor)
    if (!fn.length) return

    for (const e of edges) {
      const a = nodes[e.from], b = nodes[e.to]
      if (!a || !b || a.floor !== floor || b.floor !== floor) continue

      const [ax, ay] = this.ws(a.x, a.y)
      const [bx, by] = this.ws(b.x, b.y)

      const isAisle = e.type === 'aisle'
      // Clamp road pixel width so it never overwhelms spots in large layouts
      const outerW  = Math.min(this.scaleV(isAisle ? 13 : 18), isAisle ? 8 : 12)
      const innerW  = Math.min(this.scaleV(isAisle ? 9  : 13), isAisle ? 5 : 8)

      // deep shadow
      ctx.beginPath()
      ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
      ctx.strokeStyle = 'rgba(0,0,0,0.55)'
      ctx.lineWidth   = outerW + 3
      ctx.lineCap     = 'round'
      ctx.stroke()

      // road surface
      ctx.beginPath()
      ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
      ctx.strokeStyle = isAisle ? '#27304a' : '#2e3a58'
      ctx.lineWidth   = outerW
      ctx.stroke()

      // lighter surface strip (sheen)
      ctx.beginPath()
      ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
      ctx.strokeStyle = isAisle ? '#303d5e' : '#374770'
      ctx.lineWidth   = innerW
      ctx.stroke()

      // yellow edge kerb lines
      ctx.beginPath()
      ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
      ctx.strokeStyle = 'rgba(255,220,50,0.20)'
      ctx.lineWidth   = Math.max(1, this.scaleV(0.5))
      ctx.setLineDash([])
      ctx.stroke()

      // white center dashes for main roads
      if (!isAisle) {
        ctx.beginPath()
        ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
        ctx.strokeStyle = 'rgba(255,255,255,0.10)'
        ctx.lineWidth   = Math.max(0.8, this.scaleV(0.4))
        ctx.setLineDash([this.scaleV(4), this.scaleV(7)])
        ctx.stroke()
        ctx.setLineDash([])
      }
    }
  }

  drawSpots(spotsMap, floor) {
    const ctx = this.ctx
    // Clamp spot pixel size so spots stay visible in large zoomed-out layouts
    const W = Math.max(4, Math.min(this.scaleV(7.5), 14))
    const H = Math.max(3, Math.min(this.scaleV(5.5), 10))
    const R = Math.max(1, this.scaleV(1))

    for (const s of Object.values(spotsMap)) {
      if (s.floor !== floor) continue
      const [sx, sy] = this.ws(s.x, s.y)
      const col = SPOT_COLORS[s.status] || SPOT_COLORS.FREE

      // reserved spots get a subtle glow
      if (s.status === 'RESERVED') {
        const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, W * 1.4)
        g.addColorStop(0, col.glow)
        g.addColorStop(1, 'transparent')
        ctx.fillStyle = g
        ctx.fillRect(sx - W * 1.5, sy - W * 1.5, W * 3, W * 3)
      }

      // thin dark outline for depth
      ctx.beginPath()
      ctx.roundRect(sx - W/2 - 1, sy - H/2 - 1, W + 2, H + 2, R + 1)
      ctx.fillStyle = 'rgba(0,0,0,0.45)'
      ctx.fill()

      // spot body
      ctx.beginPath()
      ctx.roundRect(sx - W/2, sy - H/2, W, H, R)
      ctx.fillStyle   = col.fill
      ctx.fill()
      ctx.strokeStyle = col.stroke
      ctx.lineWidth   = Math.max(1, this.scaleV(0.8))
      ctx.stroke()

      // inner highlight strip (top edge)
      ctx.beginPath()
      ctx.roundRect(sx - W/2 + 1.5, sy - H/2 + 1.5, W - 3, H * 0.3, 1)
      ctx.fillStyle = 'rgba(255,255,255,0.18)'
      ctx.fill()

      // label
      const fontSize = Math.max(5, Math.min(this.scaleV(4.2), 9))
      if (fontSize >= 5.5) {
        const label = s.id.includes('-') ? s.id.split('-').pop() : s.id.slice(-3)
        ctx.fillStyle    = 'rgba(255,255,255,0.92)'
        ctx.font         = `700 ${fontSize}px Rubik,sans-serif`
        ctx.textAlign    = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(label, sx, sy)
      }

      // Disabled spot badge: small blue dot in the corner
      if (s.spot_type === 'disabled') {
        const br = Math.max(2, Math.min(this.scaleV(2.2), 5))
        ctx.beginPath()
        ctx.arc(sx + W/2 - br - 1, sy - H/2 + br + 1, br, 0, 2 * Math.PI)
        ctx.fillStyle = '#2196F3'
        ctx.fill()
        ctx.strokeStyle = 'rgba(255,255,255,0.9)'
        ctx.lineWidth = 0.8
        ctx.stroke()
      }
    }
  }

  drawElevators(targets, floor) {
    const ctx = this.ctx
    const elevators = targets.filter(t => (t.type === 'elevator' || t.type === 'escalator') && t.floor === floor)

    for (const t of elevators) {
      const [tx, ty] = this.ws(t.x, t.y)
      const color = ELEVATOR_COLORS[t.subtype] || ELEVATOR_COLORS.default
      const r = Math.max(10, Math.min(this.scaleV(11), 22))

      // glow
      const grad = ctx.createRadialGradient(tx, ty, 0, tx, ty, r * 2.5)
      grad.addColorStop(0, color + '55')
      grad.addColorStop(1, 'transparent')
      ctx.fillStyle = grad
      ctx.fillRect(tx - r*2.5, ty - r*2.5, r*5, r*5)

      // shadow
      ctx.beginPath()
      ctx.roundRect(tx - r + 2, ty - r + 2, r*2, r*2, 5)
      ctx.fillStyle = 'rgba(0,0,0,0.4)'
      ctx.fill()

      // square icon
      ctx.beginPath()
      ctx.roundRect(tx - r, ty - r, r*2, r*2, 5)
      ctx.fillStyle   = color
      ctx.fill()
      ctx.strokeStyle = 'rgba(255,255,255,0.7)'
      ctx.lineWidth   = 1.5
      ctx.stroke()

      // emoji
      ctx.font = `${Math.max(10, r * 0.95)}px sans-serif`
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(t.type === 'escalator' ? '🪜' : '🛗', tx, ty)

      // label below — white text with subtle background for legibility
      const label = t.label || t.subtype || (t.type === 'escalator' ? 'מדרגות נעות' : 'מעלית')
      const fontSize = Math.max(8, this.scaleV(4.8))
      ctx.font = `700 ${fontSize}px Rubik,sans-serif`
      const labelW = ctx.measureText(label).width
      const labelX = tx - labelW / 2 - 4
      const labelY = ty + r + 3
      // pill background
      ctx.beginPath()
      if (ctx.roundRect) ctx.roundRect(labelX, labelY, labelW + 8, fontSize + 6, 4)
      else ctx.rect(labelX, labelY, labelW + 8, fontSize + 6)
      ctx.fillStyle = 'rgba(10,14,28,0.82)'
      ctx.fill()
      // text
      ctx.fillStyle    = '#fff'
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'top'
      ctx.fillText(label, tx, labelY + 3)
    }
  }

  drawExits(targets, nodes, floor) {
    const ctx = this.ctx

    for (const t of targets) {
      if (t.type !== 'exit') continue
      const node = nodes[t.drive_node]
      if (!node || node.floor !== floor) continue

      const [nx, ny] = this.ws(node.x, node.y)
      const color = EXIT_COLORS[t.id] || EXIT_COLORS.default
      const r = this.scaleV(13)

      // shadow
      ctx.beginPath()
      ctx.roundRect(nx - r + 2, ny - r + 2, r*2, r*2, 5)
      ctx.fillStyle = 'rgba(0,0,0,0.35)'
      ctx.fill()

      // dashed rect
      ctx.beginPath()
      ctx.roundRect(nx - r, ny - r, r*2, r*2, 5)
      ctx.fillStyle   = color + '22'
      ctx.fill()
      ctx.strokeStyle = color
      ctx.lineWidth   = 2
      ctx.setLineDash([this.scaleV(3), this.scaleV(2)])
      ctx.stroke()
      ctx.setLineDash([])

      // arrow marker
      ctx.fillStyle = color
      ctx.font      = `${Math.max(12, r)}px sans-serif`
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText('🚗', nx, ny)

      // label
      ctx.fillStyle    = color
      ctx.font         = `700 ${Math.max(7, this.scaleV(4.5))}px Rubik`
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'top'
      ctx.fillText(t.label || t.id, nx, ny + r + 4)
    }
  }

  drawEntrances(entrances, nodes, floor) {
    if (!entrances || !nodes) return
    const ctx = this.ctx

    for (const eid of entrances) {
      const node = nodes[eid]
      if (!node || node.floor !== floor) continue

      const [nx, ny] = this.ws(node.x, node.y)
      const r = this.scaleV(13)

      // shadow
      ctx.beginPath()
      ctx.roundRect(nx - r + 2, ny - r + 2, r*2, r*2, 5)
      ctx.fillStyle = 'rgba(0,0,0,0.35)'
      ctx.fill()

      // dashed rect
      ctx.beginPath()
      ctx.roundRect(nx - r, ny - r, r*2, r*2, 5)
      ctx.fillStyle   = 'rgba(33,150,243,0.15)'
      ctx.fill()
      ctx.strokeStyle = '#2196F3'
      ctx.lineWidth   = 2
      ctx.setLineDash([this.scaleV(3), this.scaleV(2)])
      ctx.stroke()
      ctx.setLineDash([])

      // arrow
      ctx.fillStyle    = '#2196F3'
      ctx.font         = `${Math.max(12, r)}px sans-serif`
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText('⬇️', nx, ny)

      // label
      ctx.fillStyle    = '#64B5F6'
      ctx.font         = `700 ${Math.max(7, this.scaleV(4.5))}px Rubik`
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'top'
      ctx.fillText(eid.replace('ENT_', '').replace(/_/g,' '), nx, ny + r + 4)
    }
  }

  drawRamps(nodes, floor) {
    const ctx = this.ctx
    const ramps = Object.values(nodes).filter(n => n.type === 'ramp' && n.floor === floor)

    for (const n of ramps) {
      const [nx, ny] = this.ws(n.x, n.y)
      const r = Math.max(8, Math.min(this.scaleV(10), 18))

      ctx.save()
      ctx.translate(nx, ny)
      ctx.rotate(Math.PI / 4)
      ctx.beginPath()
      ctx.rect(-r, -r, r*2, r*2)
      ctx.fillStyle   = 'rgba(255,193,7,0.15)'
      ctx.fill()
      ctx.strokeStyle = '#FFC107'
      ctx.lineWidth   = 1.5
      ctx.stroke()
      ctx.restore()

      ctx.font = `${Math.max(10, r)}px sans-serif`
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(n.subtype === 'up' ? '⬆' : '⬇', nx, ny)
    }
  }

  drawVehicleRoute(route, routeI, floor) {
    const ctx = this.ctx
    if (!route || route.length < 2) return

    const pts = route.filter(p => p[2] === floor)
    if (pts.length < 2) return

    // glow
    ctx.beginPath()
    let first = true
    for (const p of pts) {
      const [sx, sy] = this.ws(p[0], p[1])
      if (first) { ctx.moveTo(sx, sy); first = false }
      else ctx.lineTo(sx, sy)
    }
    ctx.strokeStyle = 'rgba(33,150,243,0.22)'
    ctx.lineWidth   = Math.min(this.scaleV(10), 8)
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.stroke()

    // route line
    ctx.beginPath()
    first = true
    for (const p of pts) {
      const [sx, sy] = this.ws(p[0], p[1])
      if (first) { ctx.moveTo(sx, sy); first = false }
      else ctx.lineTo(sx, sy)
    }
    ctx.strokeStyle = '#1E88E5'
    ctx.lineWidth   = this.scaleV(2.5)
    ctx.stroke()

    // bright core
    ctx.beginPath()
    first = true
    for (const p of pts) {
      const [sx, sy] = this.ws(p[0], p[1])
      if (first) { ctx.moveTo(sx, sy); first = false }
      else ctx.lineTo(sx, sy)
    }
    ctx.strokeStyle = 'rgba(144,202,249,0.5)'
    ctx.lineWidth   = this.scaleV(0.8)
    ctx.stroke()
  }

  /** Draw Waze-style arrow vehicle */
  drawVehicle(x, y, heading, id, isUser = false) {
    const ctx = this.ctx
    const [sx, sy] = this.ws(x, y)
    const r = this.scaleV(isUser ? 9 : 7)

    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(heading)

    // glow halo
    const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, r * 2.8)
    grad.addColorStop(0, isUser ? 'rgba(33,150,243,0.55)' : 'rgba(0,200,220,0.4)')
    grad.addColorStop(1, 'transparent')
    ctx.fillStyle = grad
    ctx.beginPath()
    ctx.arc(0, 0, r * 2.8, 0, Math.PI * 2)
    ctx.fill()

    // shadow
    ctx.beginPath()
    ctx.arc(r * 0.15, r * 0.2, r * 0.85, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(0,0,0,0.45)'
    ctx.fill()

    // ── Waze-style arrow shape ──
    const color    = isUser ? '#1E88E5' : '#00ACC1'
    const colorTop = isUser ? '#64B5F6' : '#4DD0E1'

    // arrow body: teardrop / shield shape pointing up (heading direction)
    ctx.beginPath()
    ctx.moveTo(0, -r * 1.2)                                     // tip (front)
    ctx.bezierCurveTo( r * 0.9, -r * 0.1,  r * 0.9, r * 0.7, 0, r * 0.75) // right curve
    ctx.bezierCurveTo(-r * 0.9, r * 0.7, -r * 0.9, -r * 0.1, 0, -r * 1.2) // left curve
    ctx.closePath()

    // gradient fill — lighter at tip (front)
    const bodyGrad = ctx.createLinearGradient(0, -r * 1.2, 0, r * 0.75)
    bodyGrad.addColorStop(0, colorTop)
    bodyGrad.addColorStop(0.5, color)
    bodyGrad.addColorStop(1, color + 'cc')
    ctx.fillStyle   = bodyGrad
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.75)'
    ctx.lineWidth   = Math.max(0.8, r * 0.12)
    ctx.stroke()

    // inner highlight (small bright wedge near tip)
    ctx.beginPath()
    ctx.moveTo(0, -r * 1.0)
    ctx.bezierCurveTo( r * 0.35, -r * 0.35, r * 0.35, r * 0.05, 0, r * 0.1)
    ctx.bezierCurveTo(-r * 0.35, r * 0.05, -r * 0.35, -r * 0.35, 0, -r * 1.0)
    ctx.fillStyle = 'rgba(255,255,255,0.20)'
    ctx.fill()

    // dot at center (driver position)
    ctx.beginPath()
    ctx.arc(0, r * 0.1, r * 0.22, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(255,255,255,0.7)'
    ctx.fill()

    ctx.restore()

    // label below vehicle
    const label = id.slice(0, 6)
    ctx.fillStyle    = isUser ? '#90CAF9' : '#80DEEA'
    ctx.font         = `700 ${Math.max(7, this.scaleV(4))}px Rubik,sans-serif`
    ctx.textAlign    = 'center'
    ctx.textBaseline = 'top'
    ctx.fillText(label, sx, sy + r + 3)
  }

  drawAssignedSpot(spotX, spotY) {
    const ctx = this.ctx
    const [sx, sy] = this.ws(spotX, spotY)
    const r = this.scaleV(9)

    // outer pulse ring
    ctx.beginPath()
    ctx.arc(sx, sy, r * 1.6, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(76,175,80,0.35)'
    ctx.lineWidth   = 2
    ctx.stroke()

    // inner ring
    ctx.beginPath()
    ctx.arc(sx, sy, r * 1.1, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(76,175,80,0.7)'
    ctx.lineWidth   = 1.5
    ctx.stroke()

    ctx.font         = `${Math.max(12, r * 1.1)}px sans-serif`
    ctx.textAlign    = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('🏁', sx, sy)
  }
}

export function computeWorldBounds(nodes, spots, targets, floor) {
  const xs = [], ys = []

  for (const n of Object.values(nodes)) {
    if (n.floor === floor) { xs.push(n.x); ys.push(n.y) }
  }
  for (const s of Object.values(spots)) {
    if (s.floor === floor) { xs.push(s.x); ys.push(s.y) }
  }
  for (const t of (targets || [])) {
    if ('x' in t && (t.floor === floor || t.floor === undefined)) { xs.push(t.x); ys.push(t.y) }
  }

  if (!xs.length) return { minX: 0, minY: 0, maxX: 100, maxY: 100 }

  const PAD = 20
  return {
    minX: Math.min(...xs) - PAD,
    minY: Math.min(...ys) - PAD,
    maxX: Math.max(...xs) + PAD,
    maxY: Math.max(...ys) + PAD,
  }
}
