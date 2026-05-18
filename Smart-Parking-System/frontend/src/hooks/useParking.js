/**
 * useParking.js — Central State Hook
 *
 * The single source of truth for all parking data in the React app.
 * Combines WebSocket real-time updates with REST calls for actions.
 *
 * State managed here
 * ------------------
 * layout    : facility nodes, edges, spots, entrances, targets (loaded once)
 * spots     : dict id → {id, x, y, floor, status} — updated via WS delta frames
 * vehicles  : dict id → {id, x, y, floor, heading, status, route, instruction}
 * stats     : {free, reserved, occupied, total, driving, occupancy_pct}
 * eventLog  : last 50 system events (arrivals, thefts, reroutes, …)
 *
 * Data flow
 * ---------
 * 1. On mount: GET /api/layout → initialise layout + spots map
 * 2. WebSocket /ws/state → onMessage fires on every server frame (20 fps):
 *      frame.type === 'full'  → full spot list (on reconnect)
 *      frame.spots_delta      → only changed spots
 *      frame.vehicles         → complete vehicle list every frame
 *      frame.stats / event_log → replace in place
 * 3. Actions (load, spawn, assign, steal, free, remove, reset, setSpeed)
 *    call the REST API directly via api.* helpers from parkingApi.js.
 *
 * Consumed by
 * -----------
 * App.jsx → passed as props to OperatorView and DriverView
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useWebSocket } from './useWebSocket.js'
import { api } from '../api/parkingApi.js'

export function useParking() {
  const [layout, setLayout]       = useState(null)
  const [spots, setSpots]         = useState({})       // id → spot
  const [vehicles, setVehicles]   = useState({})       // id → vehicle
  const [stats, setStats]         = useState({ free: 0, reserved: 0, occupied: 0, total: 0, driving: 0, occupancy_pct: 0 })
  const [eventLog, setEventLog]   = useState([])
  const [scenarioName, setScenarioName] = useState('Demo')
  const [speed, setSpeedState]    = useState(3)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)

  // Load layout once
  useEffect(() => {
    api.getLayout()
      .then(data => {
        setLayout(data)
        // init spots map from initial data
        const m = {}
        data.spots_initial?.forEach(s => { m[s.id] = s })
        setSpots(m)
        setLoading(false)
      })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  // WebSocket handler
  useWebSocket(useCallback((frame) => {
    // Full state on reconnect
    if (frame.type === 'full' && frame.spots) {
      const m = {}
      frame.spots.forEach(s => { m[s.id] = s })
      setSpots(m)
    }

    // Delta spots
    if (frame.spots_delta?.length) {
      setSpots(prev => {
        const next = { ...prev }
        frame.spots_delta.forEach(s => {
          next[s.id] = { ...(next[s.id] || {}), ...s }
        })
        return next
      })
    }

    // Vehicles
    if (frame.vehicles) {
      const m = {}
      frame.vehicles.forEach(v => { m[v.id] = v })
      setVehicles(m)
    }

    if (frame.stats) setStats(frame.stats)
    if (frame.event_log) setEventLog(frame.event_log)
    if (frame.scenario_name) setScenarioName(frame.scenario_name)
  }, []))

  // Actions
  const loadLayout = useCallback(async (layoutPath, scenario) => {
    setLoading(true)
    try {
      await api.load(layoutPath, scenario)
      const data = await api.getLayout()
      setLayout(data)
      const m = {}
      data.spots_initial?.forEach(s => { m[s.id] = s })
      setSpots(m)
      setVehicles({})
      setScenarioName(scenario || 'Demo')
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const spawnVehicle = useCallback(async (vid, targetType, entranceId, preferredSpotId, targetInstanceId, hasDisability = false) => {
    return api.spawn(vid, targetType, entranceId, preferredSpotId, targetInstanceId, hasDisability)
  }, [])

  const assignUser = useCallback(async (targetType, entranceId, preferredSpotId, targetInstanceId) => {
    return api.assign(targetType, entranceId, preferredSpotId, targetInstanceId)
  }, [])

  const stealSpot = useCallback(async (spotId) => {
    return api.steal(spotId)
  }, [])

  const freeSpot = useCallback(async (spotId) => {
    return api.free(spotId)
  }, [])

  const removeVehicle = useCallback(async (vid) => {
    return api.remove(vid)
  }, [])

  const resetSim = useCallback(async (layoutPath, scenario) => {
    setLoading(true)
    try {
      await api.reset(layoutPath, scenario)
      const data = await api.getLayout()
      setLayout(data)
      const m = {}
      data.spots_initial?.forEach(s => { m[s.id] = s })
      setSpots(m)
      setVehicles({})
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const setSpeed = useCallback(async (s) => {
    setSpeedState(s)
    return api.speed(s)
  }, [])

  return {
    layout, spots, vehicles, stats, eventLog,
    scenarioName, speed, loading, error,
    loadLayout, spawnVehicle, assignUser,
    stealSpot, freeSpot, removeVehicle,
    resetSim, setSpeed,
  }
}
