/**
 * parkingApi.js — REST API Client v8
 *
 * Thin wrappers around fetch() for all HTTP endpoints.
 *
 * New in v8:
 *   api.assignDirect(target_group, entrance_id, has_disability)
 *     POST /api/assign_direct — fully automatic spot selection for real drivers
 *   api.getTargetGroups()
 *     GET  /api/target_groups — returns { mall, offices } for destination screen
 */
const BASE = '/api'

async function post(path, body) {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(err.detail || r.statusText)
  }
  return r.json()
}

async function get(path) {
  const r = await fetch(BASE + path)
  if (!r.ok) throw new Error(r.statusText)
  return r.json()
}

export const api = {
  // Layout & state
  getLayouts:      ()  => get('/layouts'),
  getScenarios:    ()  => get('/scenarios'),
  getLayout:       ()  => get('/layout'),
  getState:        ()  => get('/state'),
  getTargetGroups: ()  => get('/target_groups'),

  // v8 driver endpoint — replaces floorOptions + assign for real drivers
  assignDirect: (target_group, entrance_id, has_disability) =>
    post('/assign_direct', {
      target_group,
      entrance_id:    entrance_id    || '',
      has_disability: !!has_disability,
    }),

  // Operator / simulation endpoints (unchanged)
  floorOptions: (target_type, entrance_id) =>
    get(`/floor_options?target_type=${encodeURIComponent(target_type)}&entrance_id=${encodeURIComponent(entrance_id || '')}`),

  load:   (layout_path, scenario_name) => post('/load', { layout_path, scenario_name }),
  spawn:  (vid, target_type, entrance_id, preferred_spot_id, target_instance_id, has_disability = false) =>
    post('/spawn', { vid, target_type, entrance_id, preferred_spot_id, target_instance_id, has_disability }),
  assign: (target_type, entrance_id, preferred_spot_id, target_instance_id) =>
    post('/assign', {
      target_type, entrance_id,
      preferred_spot_id:  preferred_spot_id  || null,
      target_instance_id: target_instance_id || null,
    }),
  steal:  (spot_id) => post('/steal',  { spot_id }),
  free:   (spot_id) => post('/free',   { spot_id: spot_id || null }),
  remove: (vid)     => post('/remove', { vid }),
  reset:  (layout_path, scenario_name) => post('/reset', { layout_path, scenario_name }),
  speed:  (speed)   => post('/speed',  { speed }),
}
