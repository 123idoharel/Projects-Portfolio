/**
 * FloorCanvas.jsx — Per-Floor Top-Down Map
 *
 * Renders a single floor of the parking facility as a 2D top-down canvas.
 * Used by OperatorView (one FloorCanvas per floor).
 *
 * Rendering pipeline
 * ------------------
 * 1. ParkingRenderer draws the static layer: road markings, spot rectangles
 *    (colour-coded FREE/RESERVED/OCCUPIED), elevators, exits.
 * 2. VehicleLayer interpolates vehicle positions at 60 fps between the 20 fps
 *    server updates, then draws vehicle arrows on top.
 * 3. requestAnimationFrame drives the loop — the canvas redraws every frame
 *    even when no new server data has arrived.
 *
 * Props
 * -----
 * floor    : int — which floor to render
 * layout   : {nodes, edges, spots, targets}
 * spots    : dict id → {status, …} (live)
 * vehicles : dict id → {x, y, floor, heading, status, …} (live)
 */
import { useEffect, useRef, useState } from 'react'
import { ParkingRenderer, computeWorldBounds } from '../canvas/ParkingRenderer.js'
import { VehicleLayer } from '../canvas/VehicleLayer.js'

const vehicleLayerMap = {}

export default function FloorCanvas({ floor, layout, spots, vehicles, onSpotClick, tooltipHint }) {
  const canvasRef   = useRef(null)
  const rendererRef = useRef(null)
  const animRef     = useRef(null)
  const vehicleRef  = useRef(null)
  const spotsRef    = useRef(spots)

  const [tooltip, setTooltip] = useState(null)

  spotsRef.current = spots

  useEffect(() => {
    if (!vehicleRef.current) return
    vehicleRef.current.updateFromFrame(Object.values(vehicles))
  }, [vehicles])

  useEffect(() => {
    if (!layout || !canvasRef.current) return
    const canvas = canvasRef.current
    const bounds = computeWorldBounds(layout.nodes, spots, layout.targets, floor)

    if (!vehicleLayerMap[floor]) vehicleLayerMap[floor] = new VehicleLayer()
    vehicleRef.current = vehicleLayerMap[floor]

    const resizeCanvas = () => {
      const rect = canvas.parentElement.getBoundingClientRect()
      canvas.width  = rect.width  || 900
      canvas.height = rect.height || 560
      if (rendererRef.current) rendererRef.current.resize(canvas.width, canvas.height)
    }

    resizeCanvas()
    const r = new ParkingRenderer(canvas, bounds)
    rendererRef.current = r

    const ro = new ResizeObserver(resizeCanvas)
    ro.observe(canvas.parentElement)

    const getSpotAtMouse = (e) => {
      const rect = canvas.getBoundingClientRect()
      const scaleX = canvas.width  / rect.width
      const scaleY = canvas.height / rect.height
      const mx = (e.clientX - rect.left) * scaleX
      const my = (e.clientY - rect.top)  * scaleY
      const renderer = rendererRef.current
      if (!renderer) return null

      const [wx, wy] = renderer.sw(mx, my)
      const HIT_R = 9 / renderer.scale

      let closest = null, closestD = HIT_R
      for (const s of Object.values(spotsRef.current)) {
        if (s.floor !== floor) continue
        const d = Math.sqrt((s.x - wx) ** 2 + (s.y - wy) ** 2)
        if (d < closestD) { closestD = d; closest = s }
      }
      return closest
    }

    const onMouseMove = (e) => {
      const s = getSpotAtMouse(e)
      if (s) {
        const rect = canvas.getBoundingClientRect()
        setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top - 38, spot: s })
        canvas.style.cursor = 'pointer'
      } else {
        setTooltip(null)
        canvas.style.cursor = 'default'
      }
    }

    const onMouseLeave = () => { setTooltip(null); canvas.style.cursor = 'default' }

    const onClick = (e) => {
      const s = getSpotAtMouse(e)
      if (s && onSpotClick) onSpotClick(s.id)
    }

    canvas.addEventListener('mousemove', onMouseMove)
    canvas.addEventListener('mouseleave', onMouseLeave)
    canvas.addEventListener('click', onClick)

    const render = () => {
      if (!rendererRef.current) return
      const renderer = rendererRef.current
      const vl = vehicleRef.current

      vl.interpolate()
      renderer.clear()
      renderer.drawRoads(layout.nodes, layout.edges, floor)
      renderer.drawSpots(spotsRef.current, floor)
      renderer.drawElevators(layout.targets, floor)
      renderer.drawExits(layout.targets, layout.nodes, floor)
      renderer.drawEntrances(layout.entrances, layout.nodes, floor)
      renderer.drawRamps(layout.nodes, floor)

      for (const v of vl.getDisplay()) {
        if (v.floor === floor && v.status === 'DRIVING')
          renderer.drawVehicleRoute(v.route_remaining, 0, floor)
      }
      for (const v of vl.getDisplay()) {
        if (v.assigned_spot && v.status === 'DRIVING') {
          const s = spotsRef.current[v.assigned_spot]
          // Draw target marker on the spot's floor, not the vehicle's floor.
          // A vehicle may be on floor 0 driving to a reserved spot on floor 1 —
          // the target should appear on floor 1 so the operator can see it.
          if (s && s.floor === floor) renderer.drawAssignedSpot(s.x, s.y)
        }
      }
      for (const v of vl.getDisplay()) {
        if (v.floor !== floor || v.status === 'PARKED' || v.status === 'LEFT') continue
        renderer.drawVehicle(v.x, v.y, v.heading ?? 0, v.id,
          v.kind === 'USER' || v.id === 'user_car_1')
      }

      animRef.current = requestAnimationFrame(render)
    }

    animRef.current = requestAnimationFrame(render)

    return () => {
      cancelAnimationFrame(animRef.current)
      ro.disconnect()
      canvas.removeEventListener('mousemove', onMouseMove)
      canvas.removeEventListener('mouseleave', onMouseLeave)
      canvas.removeEventListener('click', onClick)
    }
  }, [layout, floor])

  const STATUS_LABEL = { FREE: 'פנוי', RESERVED: 'שמור ← רכב נוסע אליה', OCCUPIED: 'תפוס' }
  const STATUS_COLOR = { FREE: '#2E7D32', RESERVED: '#E65100', OCCUPIED: '#c62828' }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />

      {tooltip && (
        <div style={{
          position: 'absolute',
          left: Math.min(tooltip.x + 14, (canvasRef.current?.offsetWidth || 900) - 160),
          top: Math.max(tooltip.y, 4),
          background: 'rgba(15,17,30,0.94)',
          backdropFilter: 'blur(10px)',
          border: `1.5px solid ${STATUS_COLOR[tooltip.spot.status] || '#555'}66`,
          borderRadius: 10,
          padding: '8px 14px',
          pointerEvents: 'none',
          zIndex: 20,
          minWidth: 120,
          boxShadow: '0 6px 24px rgba(0,0,0,0.4)',
        }}>
          <div style={{ fontWeight: 800, fontSize: 15, color: '#fff', letterSpacing: '-0.2px' }}>
            {tooltip.spot.id}
          </div>
          <div style={{ fontSize: 12, fontWeight: 600, color: STATUS_COLOR[tooltip.spot.status], marginTop: 2 }}>
            {STATUS_LABEL[tooltip.spot.status] || tooltip.spot.status}
          </div>
          {tooltip.spot.spot_type === 'disabled' && (
            <div style={{ fontSize: 11, fontWeight: 700, color: '#90CAF9', marginTop: 3 }}>
              ♿ מקום לנכים
            </div>
          )}
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', marginTop: 3 }}>
            קומה {tooltip.spot.floor}
          </div>
          {onSpotClick && tooltip.spot.status !== 'FREE' && (
            <div style={{ fontSize: 10, color: '#FF9800', marginTop: 4, fontWeight: 600 }}>
              {tooltipHint || '🖱 לחץ לגנוב חניה'}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
