/**
 * VehicleLayer.js
 * Decouples server update rate (20fps) from render rate (60fps).
 * Uses lerp for position and slerp for heading → butter-smooth like Waze.
 */

const LERP_ALPHA   = 0.85   // position smoothing (higher = snappier)
const ANGLE_ALPHA  = 0.90   // heading smoothing

function angleDiff(target, current) {
  let d = ((target - current) % (2 * Math.PI))
  if (d > Math.PI)  d -= 2 * Math.PI
  if (d < -Math.PI) d += 2 * Math.PI
  return d
}

export class VehicleLayer {
  constructor() {
    this.targets  = {}   // latest from server
    this.display  = {}   // interpolated (what we draw)
  }

  /** Call from WS handler — update server-authoritative positions */
  updateFromFrame(vehicles) {
    vehicles.forEach(v => {
      this.targets[v.id] = v
      if (!this.display[v.id]) {
        // first time: snap to exact position
        this.display[v.id] = { ...v }
      }
      if (v.status !== 'DRIVING') {
        // snap immediately when not moving
        this.display[v.id] = { ...this.display[v.id], ...v }
      }
    })

    // remove vehicles that disappeared
    const ids = new Set(vehicles.map(v => v.id))
    for (const id of Object.keys(this.targets)) {
      if (!ids.has(id)) {
        delete this.targets[id]
        delete this.display[id]
      }
    }
  }

  /** Call every requestAnimationFrame (60fps) — advances interpolation */
  interpolate() {
    for (const id of Object.keys(this.targets)) {
      const t = this.targets[id]
      const d = this.display[id]
      if (!d || !t) continue

      if (t.status !== 'DRIVING') continue

      // lerp position
      d.x += (t.x - d.x) * LERP_ALPHA
      d.y += (t.y - d.y) * LERP_ALPHA

      // slerp heading
      const da = angleDiff(t.heading, d.heading)
      d.heading = (d.heading + da * ANGLE_ALPHA + 4 * Math.PI) % (2 * Math.PI)

      // always sync non-position fields immediately (spot assignment, route, status, instruction)
      d.floor            = t.floor
      d.status           = t.status
      d.assigned_spot    = t.assigned_spot
      d.route_remaining  = t.route_remaining
      d.instruction      = t.instruction
      d.distance_to_spot = t.distance_to_spot
      d.assigned_target_info = t.assigned_target_info
      d.kind             = t.kind
    }
  }

  /** Returns display state for rendering */
  getDisplay() {
    return Object.values(this.display)
  }

  getDisplayById(id) {
    return this.display[id]
  }
}
