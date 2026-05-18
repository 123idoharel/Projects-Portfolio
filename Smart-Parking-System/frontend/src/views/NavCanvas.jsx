/**
 * NavCanvas.jsx — Driver Navigation Canvas
 *
 * Renders the Waze-style perspective view seen by the driver while navigating
 * to their assigned parking spot.
 *
 * v17 changes (mobile smoothness):
 *   • Vehicle position and heading are now interpolated locally at 60fps
 *     using critically-damped lerp. The server still drives at 20fps but the
 *     camera follows smoothly the way Waze does on a phone.
 *   • Heading uses shortest-arc slerp to avoid 359° → 1° camera spins.
 *   • The interpolated state is what we feed to WazePerspective.transform(),
 *     so the route, roads, target pin and chevron all stay perfectly in sync.
 */
import { useEffect, useRef } from 'react'
import { WazePerspective } from '../canvas/WazePerspective.js'

// Tuning constants for the interpolation. Higher = snappier, lower = smoother.
const POSITION_LERP = 0.18   // ~3 frames to close 50% of the gap @ 60fps
const HEADING_LERP  = 0.12   // headings turn slower so it feels natural

function shortestAngleDiff(target, current) {
  let d = (target - current) % (2 * Math.PI)
  if (d >  Math.PI) d -= 2 * Math.PI
  if (d < -Math.PI) d += 2 * Math.PI
  return d
}

export default function NavCanvas({ layout, spots, userVehicle }) {
  const canvasRef  = useRef(null)
  const perspRef   = useRef(null)
  const animRef    = useRef(null)
  const targetRef  = useRef(userVehicle)            // latest from server
  const displayRef = useRef(null)                   // smoothly-interpolated copy used for drawing
  const spotsRef   = useRef(spots)

  // Keep latest server snapshot in a ref. We don't trigger re-renders on
  // every server frame — the rAF loop reads from the ref instead.
  targetRef.current = userVehicle
  spotsRef.current  = spots

  // Initialise / reset the display state when the vehicle (id) changes
  useEffect(() => {
    if (!userVehicle) { displayRef.current = null; return }
    if (!displayRef.current || displayRef.current.id !== userVehicle.id) {
      displayRef.current = { ...userVehicle }
    }
  }, [userVehicle?.id])

  useEffect(() => {
    if (!layout || !canvasRef.current) return
    const canvas = canvasRef.current

    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect()
      canvas.width  = Math.round(rect?.width  || 400)
      canvas.height = Math.round(rect?.height || 320)
    }

    resize()
    perspRef.current = new WazePerspective(canvas)

    const ro = new ResizeObserver(resize)
    ro.observe(canvas.parentElement)

    const render = () => {
      const p = perspRef.current
      const target  = targetRef.current
      let display   = displayRef.current

      if (!p || !target) { animRef.current = requestAnimationFrame(render); return }

      // Initialise display from target the first time we have data
      if (!display) {
        display = { ...target }
        displayRef.current = display
      }

      // Smooth position when DRIVING; otherwise snap immediately.
      if (target.status === 'DRIVING') {
        display.x += (target.x - display.x) * POSITION_LERP
        display.y += (target.y - display.y) * POSITION_LERP

        // Shortest-arc heading interpolation
        const targetHeading = target.heading ?? display.heading ?? 0
        const da = shortestAngleDiff(targetHeading, display.heading ?? 0)
        display.heading = ((display.heading ?? 0) + da * HEADING_LERP + 4 * Math.PI) % (2 * Math.PI)
      } else {
        display.x = target.x
        display.y = target.y
        display.heading = target.heading ?? 0
      }

      // Always copy through the latest non-positional fields so HUD stays
      // accurate even mid-interpolation.
      display.floor              = target.floor
      display.status             = target.status
      display.assigned_spot      = target.assigned_spot
      display.assigned_target_info = target.assigned_target_info
      display.route_remaining    = target.route_remaining
      display.instruction        = target.instruction
      display.distance_to_spot   = target.distance_to_spot
      display.kind               = target.kind
      display.id                 = target.id

      const v      = display
      const floor  = v.floor ?? 0
      const route  = v.route_remaining || []
      const instr  = v.instruction || {}
      const dist   = v.distance_to_spot || 0
      const spotId = v.assigned_spot || ''
      const isRecalc = v.status === 'RECALCULATING'

      // Visual speed indicator — parking-lot pace
      const speedMps = 2.2

      p.drawBackground()
      p.drawRoads(layout.edges, layout.nodes, floor, v)
      p.drawRoute(route, floor, v)

      // target spot pin
      if (v.assigned_spot) {
        const s = spotsRef.current[v.assigned_spot]
        if (s && s.floor === floor) {
          p.drawTargetSpot(s.x, s.y, floor, v)
        }
      }

      p.drawUserCar()

      // overlays (drawn in screen space, on top)
      if (isRecalc) {
        p.drawRecalculating()
      } else if (instr.direction) {
        p.drawTurnArrow(instr.direction, dist, instr)
      }

      if (dist > 0 && spotId) {
        p.drawDistanceBar(dist, spotId)
      }

      p.drawSpeedIndicator(speedMps)

      animRef.current = requestAnimationFrame(render)
    }

    animRef.current = requestAnimationFrame(render)

    return () => {
      cancelAnimationFrame(animRef.current)
      ro.disconnect()
    }
  }, [layout])

  return (
    <canvas
      ref={canvasRef}
      style={{ width: '100%', height: '100%', display: 'block' }}
    />
  )
}