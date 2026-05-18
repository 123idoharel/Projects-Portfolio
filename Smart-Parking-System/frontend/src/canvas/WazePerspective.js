/**
 * WazePerspective.js  — Waze-style perspective renderer
 * Full road surface, lane markings, turn arrows, parking spot pins
 *
 * v17 fixes (mobile):
 *   • Route line now starts EXACTLY at the vehicle (chevron) instead of
 *     extending behind it / past it visually. We trim leading waypoints that
 *     are behind the vehicle and project the vehicle's current position onto
 *     the active route segment so the blue line begins at the car.
 *   • Camera tuned for narrow phone viewports: lower horizon, closer field
 *     of view, less horizontal stretch — matches Waze's feel.
 *   • Vehicle origin (used for projection) and chevron drawn position are
 *     now identical (no more 4% gap that made the route look "ahead" of car).
 *   • Smarter perspective: clamps a small floor on the depth so points just
 *     a few cm ahead don't get drawn at infinite scale.
 *   • Behind-vehicle road segments are skipped instead of being projected
 *     with broken perspective.
 */

export class WazePerspective {
  constructor(canvas) {
    this.canvas = canvas
    this.ctx    = canvas.getContext('2d')
    this._pulse = 0
  }

  // ── viewport helpers ──────────────────────────────────────────────────────

  /** Single source of truth for camera framing — used everywhere */
  _camera() {
    const W = this.canvas.width
    const H = this.canvas.height
    const isMobile = W < H

    // Mobile camera: a balanced framing — far enough to see the next turn
    // approaching, wide enough to see side roads, but not so zoomed-out that
    // turns squash onto the horizon (which was the original problem).
    const HORIZON_Y = H * (isMobile ? 0.26 : 0.58)
    const VEHICLE_Y = H * (isMobile ? 0.78 : 0.78)

    // Field of view depth: how many world units between vehicle and horizon.
    // Larger = see further ahead. 100 lets the user see ~100m of road
    // without making nearby turns look distant.
    const depthUnits = isMobile ? 100 : 60
    const DEPTH_SCALE = (VEHICLE_Y - HORIZON_Y) / depthUnits

    // Horizontal stretch: how wide a 1-unit lateral offset appears at the
    // vehicle's plane. 2.0 on mobile shows side roads without the road
    // spilling off the screen edges.
    const horizontalStretch = isMobile ? 2.0 : 3.5

    return { W, H, isMobile, HORIZON_Y, VEHICLE_Y, depthUnits, DEPTH_SCALE, horizontalStretch }
  }

  // ── coord transforms ──────────────────────────────────────────────────────

  /** World → perspective-rotated coords (vehicle always at origin, heading up) */
  transform(wx, wy, vehicle) {
    const dx = wx - vehicle.x
    const dy = wy - vehicle.y
    // rotate so vehicle heading points "up" on screen
    const angle = -(vehicle.heading ?? 0) + Math.PI / 2
    const cos = Math.cos(angle), sin = Math.sin(angle)
    const rx = dx * cos - dy * sin
    const ry = dx * sin + dy * cos

    // Waze-style perspective: horizontal compression with depth.
    // Behind the vehicle (ry < 0) we still draw without compression, but
    // those points should be filtered out by the caller before projection.
    const HORIZON = 0.012
    const persp = 1.0 / (1.0 + Math.max(ry, 0) * HORIZON)
    return [rx * persp, ry]
  }

  /** Perspective coords → canvas pixels */
  toScreen(px, py) {
    const { W, VEHICLE_Y, HORIZON_Y, DEPTH_SCALE, horizontalStretch, depthUnits } = this._camera()

    // Clamp depth so far-away points don't all collapse onto a single horizon
    // line (which made turns "stack" at the top of the screen).
    const clampedY = Math.min(py, depthUnits * 1.1)

    const sx = W * 0.5 + px * DEPTH_SCALE * horizontalStretch
    const sy = VEHICLE_Y - clampedY * DEPTH_SCALE
    return [sx, sy]
  }

  isVisible(px, py) {
    const [sx, sy] = this.toScreen(px, py)
    return sy > 0 && sy < this.canvas.height * 1.1 && Math.abs(sx - this.canvas.width / 2) < this.canvas.width * 1.2
  }

  // ── background ────────────────────────────────────────────────────────────

  drawBackground() {
    const ctx = this.ctx
    const { W, H, HORIZON_Y } = this._camera()

    // ceiling / parking structure
    const ceiling = ctx.createLinearGradient(0, 0, 0, HORIZON_Y)
    ceiling.addColorStop(0, '#0e1218')
    ceiling.addColorStop(0.7, '#141922')
    ceiling.addColorStop(1, '#1c2535')
    ctx.fillStyle = ceiling
    ctx.fillRect(0, 0, W, HORIZON_Y)

    // ground / road surface
    const ground = ctx.createLinearGradient(0, HORIZON_Y, 0, H)
    ground.addColorStop(0, '#1a2235')
    ground.addColorStop(0.3, '#1e2840')
    ground.addColorStop(1, '#141c2e')
    ctx.fillStyle = ground
    ctx.fillRect(0, HORIZON_Y, W, H - HORIZON_Y)

    // soft horizon glow
    const glow = ctx.createLinearGradient(0, HORIZON_Y - 20, 0, HORIZON_Y + 20)
    glow.addColorStop(0, 'rgba(60,100,180,0)')
    glow.addColorStop(0.5, 'rgba(60,100,180,0.08)')
    glow.addColorStop(1, 'rgba(60,100,180,0)')
    ctx.fillStyle = glow
    ctx.fillRect(0, HORIZON_Y - 20, W, 40)

    // ceiling structural lines (parking garage feel)
    ctx.strokeStyle = 'rgba(255,255,255,0.04)'
    ctx.lineWidth = 1
    for (let i = 0; i < 5; i++) {
      const y = HORIZON_Y * (i / 5) * 0.7
      ctx.beginPath()
      ctx.moveTo(0, y); ctx.lineTo(W, y)
      ctx.stroke()
    }
  }

  // ── roads ─────────────────────────────────────────────────────────────────

  drawRoads(edges, nodes, floor, vehicle) {
    const ctx = this.ctx

    // sort back-to-front for correct overdraw
    const visible = []
    for (const e of edges) {
      const a = nodes[e.from], b = nodes[e.to]
      if (!a || !b || a.floor !== floor || b.floor !== floor) continue
      const [apx, apy] = this.transform(a.x, a.y, vehicle)
      const [bpx, bpy] = this.transform(b.x, b.y, vehicle)
      // Skip segments that are entirely behind the vehicle.
      if (apy < -2 && bpy < -2) continue
      const avgY = (apy + bpy) / 2
      visible.push({ e, apx, apy, bpx, bpy, avgY })
    }
    visible.sort((a, b) => b.avgY - a.avgY)  // far first

    for (const { e, apx, apy, bpx, bpy } of visible) {
      // Clip endpoints that are behind the camera so the perspective stays sane.
      const A = this._clipBehind(apx, apy, bpx, bpy)
      if (!A) continue
      const [ax1, ay1, bx1, by1] = A
      const [ax, ay] = this.toScreen(ax1, ay1)
      const [bx, by] = this.toScreen(bx1, by1)

      const isMain = e.type !== 'aisle'
      const roadW  = isMain ? 28 : 18

      // perspective width scaling (use the nearer endpoint)
      const nearY  = Math.max(ay1, by1)
      const scale  = Math.max(0.2, Math.min(1.0, nearY / 50))
      const w      = roadW * scale

      // road shadow
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
      ctx.strokeStyle = 'rgba(0,0,0,0.5)'
      ctx.lineWidth   = w + 4
      ctx.lineCap     = 'round'
      ctx.stroke()

      // road surface
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
      ctx.strokeStyle = isMain ? '#2c3550' : '#252e45'
      ctx.lineWidth   = w
      ctx.stroke()

      // road edge lines
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
      ctx.strokeStyle = 'rgba(255,200,50,0.18)'
      ctx.lineWidth   = Math.max(0.5, w * 0.06)
      ctx.stroke()

      // center dashes for main roads
      if (isMain && w > 6) {
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by)
        ctx.strokeStyle = 'rgba(255,255,255,0.12)'
        ctx.lineWidth   = Math.max(0.5, w * 0.04)
        ctx.setLineDash([12 * scale, 16 * scale])
        ctx.stroke()
        ctx.setLineDash([])
      }
    }
  }

  /**
   * Clip a segment so it never crosses ry = 0 (behind the camera).
   * Returns null if the whole segment is behind. Otherwise returns
   * [ax, ay, bx, by] with the behind-end pulled to the camera plane.
   */
  _clipBehind(apx, apy, bpx, bpy) {
    const NEAR = 0.5
    if (apy >= NEAR && bpy >= NEAR) return [apx, apy, bpx, bpy]
    if (apy < NEAR && bpy < NEAR) return null
    // Linear interpolate to the NEAR plane
    if (apy < NEAR) {
      const t = (NEAR - apy) / (bpy - apy)
      return [apx + t * (bpx - apx), NEAR, bpx, bpy]
    } else {
      const t = (NEAR - bpy) / (apy - bpy)
      return [apx, apy, bpx + t * (apx - bpx), NEAR]
    }
  }

  // ── route ─────────────────────────────────────────────────────────────────

  /**
   * Draw the navigation route in vehicle-relative perspective.
   *
   * The route comes from the server starting at route[ri] (the last waypoint
   * the vehicle passed). Without trimming, the line visibly extends BEHIND the
   * vehicle and through it on screen — making turns look like they happen far
   * past the vehicle. We project the vehicle position onto the first segment
   * and use that as the actual starting point of the rendered line.
   */
  drawRoute(route, floor, vehicle) {
    const ctx = this.ctx
    if (!route || route.length < 2) return

    // 1. Filter to current floor only (no floor-jumping segments)
    const pts = route.filter(p => p[2] === floor)
    if (pts.length < 2) return

    // 2. Convert all to perspective-space (vehicle-local)
    const persp = pts.map(p => {
      const [px, py] = this.transform(p[0], p[1], vehicle)
      return [px, py]
    })

    // 3. Trim leading waypoints that are behind the vehicle so the line
    //    starts AT the chevron and goes forward only.
    let startIdx = 0
    while (startIdx < persp.length - 1 && persp[startIdx + 1][1] <= 0.3) {
      startIdx++
    }

    let trimmed = persp.slice(startIdx)
    if (trimmed.length < 2) return

    // 4. Always anchor the line at the vehicle (origin) so the route visibly
    //    starts at the chevron with no gap. We replace the first waypoint
    //    when it's still behind/below the vehicle, otherwise prepend the
    //    vehicle position so the line drawn starts at the car and goes to
    //    the first ahead waypoint.
    if (trimmed[0][1] <= 0.5) {
      trimmed = [[0, 0.01], ...trimmed.slice(1)]
    } else {
      trimmed = [[0, 0.01], ...trimmed]
    }

    // 5. Project everything to screen. We use raw projection here (without
    //    the depth-clamp from toScreen) so straight roads stay straight visually.
    const { W, VEHICLE_Y, DEPTH_SCALE, horizontalStretch, depthUnits } = this._camera()
    const screenPts = trimmed.map(([px, py]) => {
      const clampedY = Math.min(py, depthUnits * 1.1)
      const sx = W * 0.5 + px * DEPTH_SCALE * horizontalStretch
      const sy = VEHICLE_Y - clampedY * DEPTH_SCALE
      return [sx, sy]
    })

    // outer glow
    ctx.beginPath()
    screenPts.forEach(([sx, sy], i) =>
      i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy))
    ctx.strokeStyle = 'rgba(33,150,243,0.2)'
    ctx.lineWidth   = 22
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.stroke()

    // main route line
    ctx.beginPath()
    screenPts.forEach(([sx, sy], i) =>
      i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy))
    ctx.strokeStyle = '#1E88E5'
    ctx.lineWidth   = 9
    ctx.stroke()

    // bright core
    ctx.beginPath()
    screenPts.forEach(([sx, sy], i) =>
      i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy))
    ctx.strokeStyle = 'rgba(144,202,249,0.6)'
    ctx.lineWidth   = 3
    ctx.stroke()

    // animated direction chevrons along route
    this._pulse = (this._pulse + 0.02) % 1
    let traveled = 0
    const CHEVRON_SPACING = 60
    const offset = this._pulse * CHEVRON_SPACING

    for (let i = 1; i < screenPts.length; i++) {
      const [x1, y1] = screenPts[i - 1]
      const [x2, y2] = screenPts[i]
      const segLen = Math.hypot(x2 - x1, y2 - y1)
      const angle  = Math.atan2(y2 - y1, x2 - x1)

      let t = ((offset - traveled) % CHEVRON_SPACING)
      while (t < segLen) {
        if (t >= 0) {
          const cx = x1 + (t / segLen) * (x2 - x1)
          const cy = y1 + (t / segLen) * (y2 - y1)
          this._drawChevron(cx, cy, angle)
        }
        t += CHEVRON_SPACING
      }
      traveled += segLen
    }
  }

  _drawChevron(cx, cy, angle) {
    const ctx = this.ctx
    const s = 7
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(angle)
    ctx.beginPath()
    ctx.moveTo(-s, -s * 0.6)
    ctx.lineTo(0,  0)
    ctx.lineTo(-s,  s * 0.6)
    ctx.strokeStyle = 'rgba(255,255,255,0.7)'
    ctx.lineWidth   = 2
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.stroke()
    ctx.restore()
  }

  // ── target spot pin ───────────────────────────────────────────────────────

  drawTargetSpot(spotX, spotY, floor, vehicle) {
    const ctx = this.ctx
    const [px, py] = this.transform(spotX, spotY, vehicle)
    if (py < 0) return
    const [sx, sy] = this.toScreen(px, py)

    const scale = Math.max(0.3, Math.min(1.2, py / 40))
    const r = 18 * scale

    // shadow
    ctx.beginPath()
    ctx.ellipse(sx, sy + r * 1.1, r * 0.5, r * 0.2, 0, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(0,0,0,0.4)'
    ctx.fill()

    // pin body
    ctx.beginPath()
    ctx.arc(sx, sy - r, r, Math.PI, 0)
    ctx.lineTo(sx, sy)
    ctx.closePath()
    const pinGrad = ctx.createRadialGradient(sx - r * 0.3, sy - r * 1.3, 0, sx, sy - r, r)
    pinGrad.addColorStop(0, '#81C784')
    pinGrad.addColorStop(1, '#2E7D32')
    ctx.fillStyle = pinGrad
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.8)'
    ctx.lineWidth = 1.5
    ctx.stroke()

    // P letter
    ctx.fillStyle = '#fff'
    ctx.font = `bold ${Math.round(r * 0.9)}px Rubik,sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText('P', sx, sy - r)
  }

  // ── user car — clean Waze-style chevron arrow ─────────────────────────────

  drawUserCar() {
    const ctx = this.ctx
    const { W, VEHICLE_Y, isMobile } = this._camera()
    const cx = W / 2
    // CRITICAL: use the same Y as toScreen(0, 0) so the route line lands
    // exactly at the chevron, not 4% of screen above/below it.
    const cy = VEHICLE_Y

    // soft ground glow
    const halo = ctx.createRadialGradient(cx, cy, 0, cx, cy, 44)
    halo.addColorStop(0,   'rgba(33,150,243,0.30)')
    halo.addColorStop(0.5, 'rgba(33,150,243,0.10)')
    halo.addColorStop(1,   'transparent')
    ctx.fillStyle = halo
    ctx.beginPath()
    ctx.arc(cx, cy, 44, 0, Math.PI * 2)
    ctx.fill()

    ctx.save()
    ctx.translate(cx, cy)

    // ── Waze chevron: two thick strokes forming a V pointing up ──
    const S = isMobile ? 16 : 22
    ctx.translate(0, S * 0.6);

    // drop shadow
    ctx.save()
    ctx.beginPath()
    ctx.moveTo(-S, S * 0.5)
    ctx.lineTo(0, -S * 0.65)
    ctx.lineTo(S,  S * 0.5)
    ctx.strokeStyle = 'rgba(0,0,0,0.45)'
    ctx.lineWidth   = 10
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.stroke()
    ctx.restore()

    // outer stroke (dark blue border)
    ctx.beginPath()
    ctx.moveTo(-S, S * 0.5)
    ctx.lineTo(0, -S * 0.65)
    ctx.lineTo(S,  S * 0.5)
    ctx.strokeStyle = '#0D47A1'
    ctx.lineWidth   = 13
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.stroke()

    // main chevron fill stroke (bright blue)
    ctx.beginPath()
    ctx.moveTo(-S, S * 0.5)
    ctx.lineTo(0, -S * 0.65)
    ctx.lineTo(S,  S * 0.5)
    ctx.strokeStyle = '#42A5F5'
    ctx.lineWidth   = 8
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.stroke()

    // inner highlight (white core)
    ctx.beginPath()
    ctx.moveTo(-S * 0.55, S * 0.3)
    ctx.lineTo(0, -S * 0.4)
    ctx.lineTo(S * 0.55, S * 0.3)
    ctx.strokeStyle = 'rgba(255,255,255,0.75)'
    ctx.lineWidth   = 3
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'
    ctx.stroke()

    ctx.restore()
  }

  // ── turn arrow overlay (drawn on top of canvas, NOT in 3D space) ──────────

  drawTurnArrow(direction, distanceM, instr) {
    const ctx = this.ctx
    const isMobile = this.canvas.width < this.canvas.height

    const BOX_X = 12
    const BOX_Y = 12
    const BOX_W = isMobile ? 96 : 134
    const MAIN_H = isMobile ? 76 : 102
    const hasNext = instr && instr.next_turn && instr.distance_to_next > 0

    const drawCard = (x, y, w, h, radius) => {
      ctx.beginPath()
      if (ctx.roundRect) ctx.roundRect(x, y, w, h, radius)
      else ctx.rect(x, y, w, h)
    }

    ctx.save()
    ctx.shadowColor = 'rgba(0,0,0,0.3)'
    ctx.shadowBlur  = 10
    drawCard(BOX_X, BOX_Y, BOX_W, MAIN_H, 16)
    ctx.fillStyle = 'rgba(14,20,40,0.75)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'
    ctx.lineWidth = 1
    ctx.stroke()
    ctx.restore()

    const cx = BOX_X + BOX_W / 2
    const cy = BOX_Y + (isMobile ? 32 : 44)

    this._drawDirectionArrow(ctx, cx, cy, direction, isMobile ? 22 : 28)

    const dist = instr?.distance_to_next ?? distanceM
    const distText = dist >= 1000
      ? `${(dist / 1000).toFixed(1)} ק"מ`
      : `${Math.round(dist)} מ'`

    ctx.fillStyle = '#ffffff'
    ctx.font = `800 ${isMobile ? 18 : 21}px Rubik,sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillText(distText, cx, BOX_Y + (isMobile ? 50 : 70))

    if (hasNext) {
      const NEXT_H = isMobile ? 30 : 38
      drawCard(BOX_X, BOX_Y + MAIN_H - 4, BOX_W, NEXT_H, [0, 0, 12, 12])
      ctx.fillStyle = 'rgba(255,255,255,0.15)'
      ctx.fill()

      const nextIcon = instr.next_turn === 'right' ? '↱' : '↰'
      const nextDistText = instr.distance_to_next >= 1000
        ? `${(instr.distance_to_next/1000).toFixed(1)}ק"מ`
        : `${instr.distance_to_next}מ'`

      ctx.fillStyle = '#C8E6C9'
      ctx.font = `600 ${isMobile ? 10 : 11}px Rubik,sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(`${nextIcon} בעוד ${nextDistText}`, cx, BOX_Y + MAIN_H - 4 + NEXT_H / 2)
    }
  }

  _drawDirectionArrow(ctx, cx, cy, direction, S = 28) {
    ctx.save()
    ctx.translate(cx, cy)

    ctx.strokeStyle = '#fff'
    ctx.lineWidth   = S >= 28 ? 5 : 4
    ctx.lineCap     = 'round'
    ctx.lineJoin    = 'round'

    if (direction === 'straight') {
      ctx.beginPath()
      ctx.moveTo(0, S * 0.6)
      ctx.lineTo(0, -S * 0.4)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(-S * 0.4, -S * 0.1)
      ctx.lineTo(0, -S * 0.6)
      ctx.lineTo( S * 0.4, -S * 0.1)
      ctx.stroke()
    } else if (direction === 'left') {
      ctx.beginPath()
      ctx.moveTo(S * 0.3, S * 0.5)
      ctx.lineTo(S * 0.3, -S * 0.1)
      ctx.bezierCurveTo(S * 0.3, -S * 0.6, -S * 0.5, -S * 0.6, -S * 0.5, -S * 0.1)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(-S * 0.1, -S * 0.5)
      ctx.lineTo(-S * 0.6, -S * 0.1)
      ctx.lineTo(-S * 0.2,  S * 0.2)
      ctx.stroke()
    } else if (direction === 'right') {
      ctx.beginPath()
      ctx.moveTo(-S * 0.3, S * 0.5)
      ctx.lineTo(-S * 0.3, -S * 0.1)
      ctx.bezierCurveTo(-S * 0.3, -S * 0.6, S * 0.5, -S * 0.6, S * 0.5, -S * 0.1)
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo( S * 0.1, -S * 0.5)
      ctx.lineTo( S * 0.6, -S * 0.1)
      ctx.lineTo( S * 0.2,  S * 0.2)
      ctx.stroke()
    } else if (direction === 'arrived') {
      ctx.strokeStyle = '#4CAF50'
      ctx.beginPath()
      ctx.moveTo(-S * 0.5, 0)
      ctx.lineTo(-S * 0.1, S * 0.45)
      ctx.lineTo( S * 0.55, -S * 0.45)
      ctx.stroke()
    }
    ctx.restore()
  }

  // ── speed indicator (bottom left) ────────────────────────────────────────

  drawSpeedIndicator(speedMps) {
    const ctx = this.ctx
    const W = this.canvas.width
    const H = this.canvas.height
    const kmh = Math.round(speedMps * 3.6)

    const R = 24
    const cx = R + 14
    const cy = H - R - 65

    ctx.save()
    ctx.shadowColor = 'rgba(0,0,0,0.4)'
    ctx.shadowBlur  = 10
    ctx.beginPath()
    ctx.arc(cx, cy, R, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(20,28,50,0.88)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'
    ctx.lineWidth   = 1.5
    ctx.stroke()
    ctx.restore()

    ctx.fillStyle = '#fff'
    ctx.font       = `800 18px Rubik,sans-serif`
    ctx.textAlign  = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(kmh, cx, cy - 4)

    ctx.fillStyle   = 'rgba(255,255,255,0.45)'
    ctx.font         = `500 9px Rubik,sans-serif`
    ctx.fillText('קמ"ש', cx, cy + 13)
  }
  // ── next waypoint distance (bottom center) ───────────────────────────────

  drawDistanceBar(distanceM, spotId) {
    const ctx = this.ctx
    const W = this.canvas.width
    const H = this.canvas.height

    const BAR_W = Math.min(260, W * 0.75)
    const BAR_H = 42
    const bx = (W - BAR_W) / 2
    const by = H - BAR_H - 65

    ctx.save()
    ctx.shadowColor = 'rgba(0,0,0,0.3)'
    ctx.shadowBlur  = 8
    ctx.beginPath()
    if (ctx.roundRect) ctx.roundRect(bx, by, BAR_W, BAR_H, 22)
    else ctx.rect(bx, by, BAR_W, BAR_H)
    ctx.fillStyle = 'rgba(20,28,50,0.88)'
    ctx.fill()
    ctx.restore()

    const distText = distanceM >= 1000
      ? `${(distanceM / 1000).toFixed(1)} ק"מ לחניה`
      : `${Math.round(distanceM)} מ' לחניה`

    ctx.fillStyle    = '#90CAF9'
    ctx.font         = `700 15px Rubik,sans-serif`
    ctx.textAlign    = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(`🏁  ${distText}  ·  ${spotId}`, W / 2, by + BAR_H / 2)
  }

  // ── recalculating banner ──────────────────────────────────────────────────

  drawRecalculating() {
    const ctx = this.ctx
    const W = this.canvas.width
    const alpha = 0.5 + 0.5 * Math.sin(Date.now() / 300)

    ctx.fillStyle = `rgba(244,67,54,${alpha * 0.85})`
    ctx.font       = `800 18px Rubik,sans-serif`
    ctx.textAlign  = 'center'
    ctx.textBaseline = 'middle'

    ctx.save()
    ctx.shadowColor = 'rgba(244,67,54,0.8)'
    ctx.shadowBlur  = 20
    ctx.fillText('⟳ מחשב מסלול מחדש...', W / 2, 28)
    ctx.restore()
  }
}