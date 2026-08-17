// ─── SCOUT ML — Data Helpers & Constants ─────────────────────────────────────

// ── EUR Formatter ─────────────────────────────────────────────────────────────
function fmtEur(eur, compact) {
  if (eur == null || eur === 0) return '—';
  if (eur >= 1_000_000) {
    const m = eur / 1_000_000;
    const disp = m >= 100 ? Math.round(m) : m >= 10 ? m.toFixed(1) : m.toFixed(2);
    return `€${disp}M`;
  }
  if (eur >= 1_000) return `€${Math.round(eur / 1000)}k`;
  return `€${Math.round(eur)}`;
}

// ── Player normalizer (VJSON → internal) ──────────────────────────────────────
function normalizePlayer(raw) {
  if (!raw || !raw.metadata) return null;
  const m   = raw.metadata;
  const mdl = raw.models || {};

  // Drop entries with no name. These are typically tm_ids whose Transfermarkt
  // profile-page scrape failed — they have model predictions and a tm_id but
  // no descriptive metadata (no name, club, league, position). Displaying them
  // as a sea of "?" rows is noise. Skipping at normalize time keeps them out
  // of the search list, sort orders, and filter facets.
  if (!m.name || typeof m.name !== 'string' || !m.name.trim()) return null;

  // Canonical risk score = (q90 − q10) / q50. Recomputed here from raw
  // quantiles regardless of what was stored in the JSON, so the formula is
  // identical across all pitch areas. (Some teammates used different formulas
  // — e.g. midfield JSON had risk_score = (opt − pes) / (2 × base). Ignoring
  // the stored value avoids inconsistency in the risk pill.)
  const canonicalRisk = (x) => {
    if (!x) return null;
    const base = x.expected_eur, opt = x.optimistic_eur, pes = x.pessimistic_eur;
    if (base == null || opt == null || pes == null || base <= 0) return x.risk_score ?? null;
    return (opt - pes) / base;
  };

  const mapM = (x) => x ? {
    base:    x.expected_eur,
    opt:     x.optimistic_eur,
    opt_q75: x.optimistic_q75_eur,    // present when q75 pipeline ran
    pes:     x.pessimistic_eur,
    upside:  x.upside_multiple,
    risk:    canonicalRisk(x),
  } : null;

  // Sort history newest first
  const history = (raw.history_data || []).slice().sort((a, b) =>
    b._season_year.localeCompare(a._season_year)
  );

  return {
    id:                m.tm_id,
    sofascore_id:      m.sofascore_id,
    name:              m.name || '?',
    age:               m.age_at_cutoff || 0,
    position:          m.primary_position || '?',
    secondaryPosition: m.secondary_position,
    club:              m.current_team || '?',
    league:            m.current_league || '?',
    valueEur:          m.current_value_eur || 0,
    height:            m.height,
    foot:              m.foot,
    contractExpiry:    m.contract_expiry,
    citizenships:      m.citizenships || [],
    has_photo:         m.has_photo || false,
    predictions: {
      peak:   mapM(mdl.peak_potential),
      next1yr: mapM(mdl.horizon_1y),
      next2yr: mapM(mdl.horizon_2y),
    },
    history,
    advancedStats: raw.advanced_stats || {},
  };
}

// ── Seasonal stat categories (for history_data rows) ─────────────────────────
const SEASON_STAT_CATEGORIES = [
  {
    label: 'Attack',
    stats: [
      { label: 'Goals',          key: 'goals' },
      { label: 'Assists',        key: 'assists' },
      { label: 'G+A',            fn:  s => (s.goals||0) + (s.assists||0) },
      { label: 'xG',             key: 'expectedGoals',            fmt: v => v?.toFixed(2) ?? '—' },
      { label: 'xA',             key: 'expectedAssists',          fmt: v => v?.toFixed(2) ?? '—' },
      { label: 'Big Chances',    key: 'bigChancesCreated' },
      { label: 'BC Missed',      key: 'bigChancesMissed' },
      { label: 'Key Passes',     key: 'keyPasses' },
      { label: 'Conv %',         key: 'goalConversionPercentage', fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Scoring Freq',   key: 'scoringFrequency',         fmt: v => v ? Math.round(v)+"'" : '—' },
    ],
  },
  {
    label: 'Shooting',
    stats: [
      { label: 'Total Shots',    key: 'totalShots' },
      { label: 'On Target',      key: 'shotsOnTarget' },
      { label: 'Off Target',     key: 'shotsOffTarget' },
      { label: 'Blocked',        key: 'blockedShots' },
      { label: 'Inside Box',     key: 'shotsFromInsideTheBox' },
      { label: 'Outside Box',    key: 'shotsFromOutsideTheBox' },
      { label: 'Hit Woodwork',   key: 'hitWoodwork' },
      { label: 'Left Foot',      key: 'leftFootGoals' },
      { label: 'Right Foot',     key: 'rightFootGoals' },
      { label: 'Headers',        key: 'headedGoals' },
    ],
  },
  {
    label: 'Passing',
    stats: [
      { label: 'Accurate',       key: 'accuratePasses' },
      { label: 'Total',          key: 'totalPasses' },
      { label: 'Pass %',         key: 'accuratePassesPercentage',      fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Final 3rd',      key: 'accurateFinalThirdPasses' },
      { label: 'Opp Half',       key: 'accurateOppositionHalfPasses' },
      { label: 'Own Half',       key: 'accurateOwnHalfPasses' },
      { label: 'Long Balls',     key: 'accurateLongBalls' },
      { label: 'Long %',         key: 'accurateLongBallsPercentage',   fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Crosses',        key: 'accurateCrosses' },
      { label: 'Cross %',        key: 'accurateCrossesPercentage',     fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
    ],
  },
  {
    label: 'Duels',
    stats: [
      { label: 'Won',            key: 'totalDuelsWon' },
      { label: 'Duel %',         key: 'totalDuelsWonPercentage',       fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Ground Won',     key: 'groundDuelsWon' },
      { label: 'Ground %',       key: 'groundDuelsWonPercentage',      fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Aerial Won',     key: 'aerialDuelsWon' },
      { label: 'Aerial %',       key: 'aerialDuelsWonPercentage',      fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Dribbles',       key: 'successfulDribbles' },
      { label: 'Drib %',         key: 'successfulDribblesPercentage',  fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Dispossessed',   key: 'dispossessed' },
      { label: 'Dribbled Past',  key: 'dribbledPast' },
    ],
  },
  {
    label: 'Defending',
    stats: [
      { label: 'Tackles',        key: 'tackles' },
      { label: 'Tackles Won',    key: 'tacklesWon' },
      { label: 'Tackle %',       key: 'tacklesWonPercentage',          fmt: v => v != null ? v.toFixed(1)+'%' : '—' },
      { label: 'Interceptions',  key: 'interceptions' },
      { label: 'Clearances',     key: 'clearances' },
      { label: 'Ball Recovery',  key: 'ballRecovery' },
      { label: 'Fouls',          key: 'fouls' },
      { label: 'Was Fouled',     key: 'wasFouled' },
      { label: 'Penalty Won',    key: 'penaltyWon' },
    ],
  },
  {
    label: 'General',
    stats: [
      { label: 'Apps',           key: 'appearances' },
      { label: 'Started',        key: 'matchesStarted' },
      { label: 'Minutes',        key: 'minutesPlayed',   fmt: v => v?.toLocaleString() ?? '—' },
      { label: 'Rating',         key: 'rating',          fmt: v => v?.toFixed(2) ?? '—' },
      { label: 'Touches',        key: 'touches' },
      { label: 'Yellow Cards',   key: 'yellowCards' },
      { label: 'Red Cards',      key: 'redCards' },
      { label: 'Offsides',       key: 'offsides' },
      { label: 'Poss. Lost',     key: 'possessionLost' },
    ],
  },
];

// ── Advanced stat display definitions (from advanced_stats) ───────────────────
const ADV_DISPLAY_STATS = [
  // Attacking
  { group: 'Attacking Output', label: 'Goals /90',         key: 'goals_p90_shrunk',                    histKey: 'hist_goals_p90_shrunk_mean',                 fmt: v => v?.toFixed(3) },
  { group: 'Attacking Output', label: 'Assists /90',       key: 'assists_p90_shrunk',                  histKey: 'hist_assists_p90_shrunk_mean',               fmt: v => v?.toFixed(3) },
  { group: 'Attacking Output', label: 'xG /90',            key: 'expectedGoals_p90',                   histKey: 'hist_expectedGoals_p90_mean',                fmt: v => v?.toFixed(3) },
  { group: 'Attacking Output', label: 'xA /90',            key: 'expectedAssists_p90',                 histKey: 'hist_expectedAssists_p90_mean',              fmt: v => v?.toFixed(3) },
  { group: 'Attacking Output', label: 'Open Play G /90',   key: 'open_play_goals_p90_shrunk',          histKey: 'hist_open_play_goals_p90_shrunk_mean',       fmt: v => v?.toFixed(3) },
  // Shooting
  { group: 'Shooting',         label: 'Shots /90',         key: 'totalShots_p90_shrunk',               histKey: 'hist_totalShots_p90_shrunk_mean',            fmt: v => v?.toFixed(2) },
  { group: 'Shooting',         label: 'Shots OT /90',      key: 'shotsOnTarget_p90_shrunk',            histKey: 'hist_shotsOnTarget_p90_shrunk_mean',         fmt: v => v?.toFixed(2) },
  { group: 'Shooting',         label: 'Inside Box /90',    key: 'shotsFromInsideTheBox_p90_shrunk',    histKey: 'hist_shotsFromInsideTheBox_p90_shrunk_mean', fmt: v => v?.toFixed(2) },
  { group: 'Shooting',         label: 'Outside Box /90',   key: 'shotsFromOutsideTheBox_p90_shrunk',   fmt: v => v?.toFixed(2) },
  // Chance Creation
  { group: 'Chance Creation',  label: 'Big Chances /90',   key: 'bigChancesCreated_p90_shrunk',        histKey: 'hist_bigChancesCreated_p90_shrunk_mean',     fmt: v => v?.toFixed(3) },
  { group: 'Chance Creation',  label: 'Key Passes /90',    key: 'keyPasses_p90_shrunk',                histKey: 'hist_keyPasses_p90_shrunk_mean',             fmt: v => v?.toFixed(3) },
  { group: 'Chance Creation',  label: 'Attempt Assist /90',key: 'totalAttemptAssist_p90_shrunk',       fmt: v => v?.toFixed(3) },
  { group: 'Chance Creation',  label: 'Final 3rd Pass /90',key: 'accurateFinalThirdPasses_p90_shrunk', histKey: 'hist_accurateFinalThirdPasses_p90_shrunk_mean', fmt: v => v?.toFixed(2) },
  // Carrying
  { group: 'Carrying & Threat', label: 'Dribbles /90',     key: 'successfulDribbles_p90_shrunk',       histKey: 'hist_successfulDribbles_p90_shrunk_mean',    fmt: v => v?.toFixed(3) },
  { group: 'Carrying & Threat', label: 'Touches /90',      key: 'touches_p90_shrunk',                  histKey: 'hist_touches_p90_shrunk_mean',               fmt: v => v?.toFixed(1) },
  { group: 'Carrying & Threat', label: 'Progression /90',  key: 'progression_p90',                    histKey: 'hist_progression_p90_mean',                  fmt: v => v?.toFixed(2) },
  { group: 'Carrying & Threat', label: 'Involvement /90',  key: 'involvement_p90',                    fmt: v => v?.toFixed(2) },
  { group: 'Carrying & Threat', label: 'Was Fouled /90',   key: 'wasFouled_p90_shrunk',               histKey: 'hist_wasFouled_p90_shrunk_mean',             fmt: v => v?.toFixed(3) },
  // Defending
  { group: 'Defending',        label: 'Tackles /90',       key: 'tackles_p90_shrunk',                  fmt: v => v?.toFixed(2) },
  { group: 'Defending',        label: 'Interceptions /90', key: 'interceptions_p90_shrunk',            fmt: v => v?.toFixed(3) },
  { group: 'Defending',        label: 'Ball Recovery /90', key: 'ballRecovery_p90_shrunk',             fmt: v => v?.toFixed(2) },
  { group: 'Defending',        label: 'Fouls /90',         key: 'fouls_p90_shrunk',                    fmt: v => v?.toFixed(2) },
  // Ratings
  { group: 'Performance',      label: 'Match Rating',      key: 'rating',                              histKey: 'hist_rating_mean',                           fmt: v => v?.toFixed(2) },
  { group: 'Performance',      label: 'Rating Residual',   key: 'rating_residual',                    histKey: 'hist_rating_residual_mean',                  fmt: v => v?.toFixed(3) },
  { group: 'Performance',      label: 'Forward Score',     key: 'modern_forward_score',               histKey: 'hist_modern_forward_score_mean',             fmt: v => v?.toFixed(3) },
  { group: 'Performance',      label: 'G+A vs League',     key: 'ga_vs_league',                       histKey: 'hist_ga_vs_league_weighted_mean',            fmt: v => v?.toFixed(3) },
  { group: 'Performance',      label: 'Starts Rate',       key: 'starts_rate',                        fmt: v => v != null ? (v*100).toFixed(0)+'%' : '—' },
  { group: 'Performance',      label: 'Goals Tier Z',      key: 'goals_tier_z',                       fmt: v => v?.toFixed(2) },
  { group: 'Performance',      label: 'Assists Tier Z',    key: 'assists_tier_z',                     fmt: v => v?.toFixed(2) },
];

const POSITIONS_LIST       = ["GK","CB","LB","RB","DM","CM","CAM","LW","RW","ST"];
const BEST_PEAK_CUTOFF_EUR = 10_000_000; // €10M — "BEST" filter threshold

// ─────────────────────────────────────────────────────────────────────────────
// Position groups for the Key Drivers explainability strip on the profile.
// Each player's position is mapped to one of: GK | DEF | MID | ATT.
// The mapping is forgiving — secondary naming conventions are absorbed by the
// loose-prefix rules so teammate JSONs don't need exact code matching.
function positionGroup(pos) {
  if (!pos) return 'MID';   // safe default
  const p = pos.toUpperCase();
  if (p === 'GK')                          return 'GK';
  if (p.endsWith('B') || p === 'CB' || p === 'SW' || p.includes('WB')) return 'DEF';
  if (p === 'CM' || p === 'DM' || p === 'CAM' || p === 'AM' || p.endsWith('M')) return 'MID';
  return 'ATT';   // ST/CF/LW/RW/SS and unknowns default to attack
}

// Universal metric definitions reused across position groups.
const _MIN_METRIC = { label: 'Minutes', keys: ['minutesPlayed', 'minutes'], per90: false, higherIsBetter: true,  fmt: v => Math.round(v).toLocaleString() };
const _RATING     = { label: 'Rating',  keys: ['rating'],                   per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(2) };
const _GOALS      = { label: 'Goals',   keys: ['goals'],                    per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(0) };
const _ASSISTS    = { label: 'Assists', keys: ['assists'],                  per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(0) };

// ─────────────────────────────────────────────────────────────────────────────
// Position-aware Key Drivers config.
//
// Each position group maps to an ordered list of CATEGORIES. Each category
// has a title and a list of metric defs. Metric defs use the same shape as
// before (label/keys/per90/higherIsBetter/fmt). When rendered, the Key
// Drivers component:
//   1. Computes last-season vs prior-seasons-average for every metric.
//   2. Hides metrics whose |Δ| < 5% (no meaningful change).
//   3. Hides categories where all metrics were hidden.
//   4. Renders each surviving category with a section title and its metrics.
//
// The metric list per position covers what scouts actually watch for that
// role. The 5% noise threshold means rosters where stats are stable won't
// surface anything — and that's correct, because there's nothing to explain.
// ─────────────────────────────────────────────────────────────────────────────
const KEY_DRIVERS_BY_GROUP = {
  GK: [
    { title: 'Shot Stopping', metrics: [
      { label: 'Saves',          keys: ['saves'],                     per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(0) },
      { label: 'Saves %',        keys: ['savesPercentage', 'saveAccuracyPercentage'],
                                                                      per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(1) + '%' },
      { label: 'Goals Conceded/90', keys: ['goalsConcededInsideTheBox', 'goalsConceded'],
                                                                      per90: true,  higherIsBetter: false, fmt: v => v?.toFixed(2) },
      { label: 'Clean Sheets',   keys: ['cleanSheet', 'cleanSheets'], per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(0) },
    ]},
    { title: 'Distribution', metrics: [
      { label: 'Pass Acc %',     keys: ['accuratePassesPercentage', 'passAccuracy'],
                                                                      per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(1) + '%' },
      { label: 'Long Balls/90',  keys: ['accurateLongBalls'],         per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Workload', metrics: [_RATING, _MIN_METRIC] },
  ],
  DEF: [
    { title: 'Tackling & Pressing', metrics: [
      { label: 'Tackles/90',        keys: ['tackles'],                per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Interceptions/90',  keys: ['interceptions'],          per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Clearances/90',     keys: ['clearances'],             per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Blocked Shots/90',  keys: ['blockedShots'],           per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Ground Duels Won/90', keys: ['groundDuelsWon'],       per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Recoveries/90',     keys: ['ballRecovery'],           per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Aerial', metrics: [
      { label: 'Aerial Won %',      keys: ['aerialDuelsWonPercentage'], per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(1) + '%' },
      { label: 'Aerial Won/90',     keys: ['aerialDuelsWon'],         per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Distribution', metrics: [
      { label: 'Pass Acc %',        keys: ['accuratePassesPercentage', 'passAccuracy'],
                                                                      per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(1) + '%' },
      { label: 'Key Passes/90',     keys: ['keyPasses'],              per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Goal Threat', metrics: [_GOALS, _ASSISTS] },
    { title: 'Workload', metrics: [_RATING, _MIN_METRIC] },
  ],
  MID: [
    { title: 'Passing & Progression', metrics: [
      { label: 'Pass Acc %',        keys: ['accuratePassesPercentage', 'passAccuracy'],
                                                                      per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(1) + '%' },
      { label: 'Key Passes/90',     keys: ['keyPasses', 'bigChancesCreated'],
                                                                      per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Dribbles/90',       keys: ['successfulDribbles'],     per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Long Balls/90',     keys: ['accurateLongBalls'],      per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Defensive Work', metrics: [
      { label: 'Tackles/90',        keys: ['tackles'],                per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Interceptions/90',  keys: ['interceptions'],          per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Recoveries/90',     keys: ['ballRecovery'],           per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Ground Duels Won/90', keys: ['groundDuelsWon'],       per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Goal Threat', metrics: [
      _GOALS, _ASSISTS,
      { label: 'xG/90',             keys: ['expectedGoals', 'xG'],    per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'xA/90',             keys: ['expectedAssists', 'xA'],  per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Workload', metrics: [_RATING, _MIN_METRIC] },
  ],
  ATT: [
    { title: 'Goal Threat', metrics: [
      _GOALS,
      { label: 'Goals/90',          keys: ['goals'],                  per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'xG/90',             keys: ['expectedGoals', 'xG'],    per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Shots/90',          keys: ['totalShots', 'shots'],    per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Shots on Target/90', keys: ['shotsOnTarget'],         per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Shot Creation', metrics: [
      _ASSISTS,
      { label: 'Assists/90',        keys: ['assists'],                per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'xA/90',             keys: ['expectedAssists', 'xA'],  per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Key Passes/90',     keys: ['keyPasses'],              per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
    ]},
    { title: 'Possession & Dribbling', metrics: [
      { label: 'Dribbles/90',       keys: ['successfulDribbles'],     per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Ground Duels Won/90', keys: ['groundDuelsWon'],       per90: true,  higherIsBetter: true,  fmt: v => v?.toFixed(2) },
      { label: 'Pass Acc %',        keys: ['accuratePassesPercentage', 'passAccuracy'],
                                                                      per90: false, higherIsBetter: true,  fmt: v => v?.toFixed(1) + '%' },
    ]},
    { title: 'Workload', metrics: [_RATING, _MIN_METRIC] },
  ],
};

// ─────────────────────────────────────────────────────────────────────────────
// Competition classifier — categorizes each history_data row by its _league
// value into one of three buckets:
//
//   'domestic'         — domestic top-flight + lower divisions
//   'club_tournament'  — continental club competitions (Champions League etc.)
//   'international'    — national-team tournaments (World Cup, Euro, etc.)
//
// Keyword-based so it tolerates future league names from teammate JSONs.
// ─────────────────────────────────────────────────────────────────────────────
const INTL_KEYWORDS = [
  'world cup', 'european championship', 'copa america', 'gold cup',
  'africa cup of nations', 'afcon', 'asian cup', 'nations league',
];
const CLUB_TOURNAMENT_KEYWORDS = [
  'champions league', 'europa league', 'conference league',
  'copa libertadores', 'copa sudamericana',
];

function competitionType(leagueName) {
  if (!leagueName || typeof leagueName !== 'string') return 'domestic';
  const low = leagueName.toLowerCase();
  for (const kw of INTL_KEYWORDS)            if (low.includes(kw)) return 'international';
  for (const kw of CLUB_TOURNAMENT_KEYWORDS) if (low.includes(kw)) return 'club_tournament';
  return 'domestic';
}

const COMPETITION_LABELS = {
  domestic:        'Domestic League',
  club_tournament: 'Club Tournament',
  international:   'International Tournament',
};

// League → tier classification. Derived from the attacker pipeline's
// `league_tier_at_cutoff` field, which is present in attack JSONs but missing
// from midfield (and likely defense/GK once they ship). Keeping a frontend
// table means tier-aware features work uniformly across pitch areas regardless
// of which teammate JSON includes which columns.
//
// Tiers:
//   1 = top-5 European leagues
//   2 = strong secondary European leagues
//   3 = competitive but lower-spending leagues + main South-American leagues
//   4 = European second divisions, mid-tier leagues
//   5 = lower-tier leagues globally
const LEAGUE_TIER_MAP = {
  // Tier 1
  'Spain La Liga':         1,
  'Italy Serie A':         1,
  'France Ligue 1':        1,
  'England Premier League':1,
  'Germany Bundesliga':    1,
  // Tier 2
  'Turkiye Super Lig':         2,
  'Belgium Pro League':        2,
  'Netherlands Eredivisie':    2,
  'Portugal Primeira Liga':    2,
  // Tier 3
  'Argentina Liga Profesional':3,
  'USA MLS':                   3,
  'England EFL Championship':  3,
  'Spain La Liga 2':           3,
  'Brazil Serie A':            3,
  'Germany 2.Bundesliga':      3,
  'Czech First League':        3,
  'Ukraine Premier League':    3,
  'Scotland Premiership':      3,
  'Switzerland Super League':  3,
  'Austria Bundesliga':        3,
  'Denmark Superliga':         3,
  'Croatia HNL':               3,
  'Mexico Liga MX Apertura':   3,
  'Mexico Liga MX Clausura':   3,
  // Tier 4
  'Italy Serie B':         4,
  'Romania Superliga':     4,
  'Poland Ekstraklasa':    4,
  'Serbia Superliga':      4,
  'France Ligue 2':        4,
  'Russia Premier League': 4,
  'Portugal Liga Portugal 2':4,
  'Saudi Arabia Pro League':4,
  'Israeli Premier League':4,
  // Tier 5
  'USA USL championship':  5,
  'Bulgaria Parva Liga':   5,
  'Peru Liga 1':           5,
};

// Look up a player's tier from their league display name. Falls back to
// advancedStats.league_tier_at_cutoff when present, then to null.
function leagueTier(leagueName, advancedStats) {
  if (leagueName && LEAGUE_TIER_MAP[leagueName] != null) return LEAGUE_TIER_MAP[leagueName];
  const adv = advancedStats || {};
  if (typeof adv.league_tier_at_cutoff === 'number') return adv.league_tier_at_cutoff;
  if (typeof adv.league_tier === 'number')           return adv.league_tier;
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Tier Standouts — surfaces metrics where the player is notably above their
// peer-group (tier) average. Reads the precomputed *_tier_z fields from
// advanced_stats. A z-score of 1.0 means roughly the top 16% of the tier;
// 2.0 means the top 2.5%. We threshold at z ≥ 1.0 by default.
//
// Position-aware metric set — GK doesn't see goals/assists.
//
// Input:  advancedStats = player.advancedStats / advanced_stats object
//         position      = primary position string
// Output: {
//   tier:    integer 1-5 or null,
//   league:  string or null,
//   rows:    [{ label, value, z, fmt }] sorted by z descending
// }
// ─────────────────────────────────────────────────────────────────────────────
const TIER_Z_THRESHOLD = 1.0;

// Map z-score field → display config. Each entry references the metric's
// raw value field too (so we can show the actual number alongside the z).
// Position groups filter this set: GK gets the ones that make sense for
// goalkeepers, outfield gets the rest.
const TIER_Z_METRICS = [
  { zKey: 'rating_tier_z',            valueKey: 'rating',           label: 'Rating',           fmt: v => v?.toFixed(2),                        forGroups: ['GK','DEF','MID','ATT'] },
  { zKey: 'goals_tier_z',             valueKey: 'goals',            label: 'Goals',            fmt: v => Math.round(v).toString(),             forGroups:      ['DEF','MID','ATT'] },
  { zKey: 'assists_tier_z',           valueKey: 'assists',          label: 'Assists',          fmt: v => Math.round(v).toString(),             forGroups:      ['DEF','MID','ATT'] },
  { zKey: 'shotsOnTarget_tier_z',     valueKey: 'shotsOnTarget',    label: 'Shots on Target',  fmt: v => Math.round(v).toString(),             forGroups:           ['MID','ATT'] },
  { zKey: 'bigChancesCreated_tier_z', valueKey: 'bigChancesCreated',label: 'Big Chances Created', fmt: v => Math.round(v).toString(),          forGroups:           ['MID','ATT'] },
];

function computeTierStandouts(advancedStats, position, leagueDisplay) {
  if (!advancedStats) return { tier: null, league: null, rows: [] };
  const group = positionGroup(position);
  const tier  = advancedStats.league_tier_at_cutoff ?? advancedStats.league_tier ?? null;

  const rows = [];
  for (const def of TIER_Z_METRICS) {
    if (!def.forGroups.includes(group)) continue;
    const z = advancedStats[def.zKey];
    if (typeof z !== 'number' || isNaN(z)) continue;
    if (z < TIER_Z_THRESHOLD) continue;
    const value = advancedStats[def.valueKey];
    rows.push({
      label: def.label,
      value: typeof value === 'number' ? value : null,
      z,
      fmt: def.fmt,
    });
  }
  rows.sort((a, b) => b.z - a.z);
  return { tier, league: leagueDisplay || null, rows };
}

// ─────────────────────────────────────────────────────────────────────────────
// Per-competition Tier Standouts.
//
// Different question from the domestic-tier version: instead of "where does
// this player rank in their league tier," it's "where does this player rank
// among the cohort of players who also appeared in this specific competition
// last season."
//
// The cohort is players who have ≥ 1 history_data row matching the chosen
// competition slice. We compute mean + standard deviation across that cohort
// for each metric, then derive the focal player's z-score. Surface metrics
// where the focal player's z ≥ 1.0.
//
// Notes:
//   - For per-90 metrics we use minutes-weighted aggregation per player; for
//     totals (Goals / Assists) we use the season-competition sum.
//   - Cohort = players with ≥ 270 minutes in that competition (per-90 noise).
//   - For totals (Goals / Assists), include any player with ≥ 1 row in the
//     competition since "0 goals in 11 min" is still legitimately 0.
//   - Returns { peerGroup, rows, cohortSize }.
//
// Inputs:
//   player       — focal player {history, position, advancedStats, league, name}
//   allPlayers   — all loaded players (window-scoped roster)
//   competition  — 'domestic' | 'club_tournament' | 'international'
//   leagueDisplay — player's current league string (for domestic peer-group label)
// ─────────────────────────────────────────────────────────────────────────────
const COMPETITION_TIER_METRICS = [
  { label: 'Rating',                 keys: ['rating'],            per90: false, isRate: true,  fmt: v => v?.toFixed(2),            forGroups: ['GK','DEF','MID','ATT'] },
  { label: 'Goals',                  keys: ['goals'],             per90: false, isRate: false, fmt: v => Math.round(v).toString(), forGroups:      ['DEF','MID','ATT'] },
  { label: 'Assists',                keys: ['assists'],           per90: false, isRate: false, fmt: v => Math.round(v).toString(), forGroups:      ['DEF','MID','ATT'] },
  { label: 'Goals/90',               keys: ['goals'],             per90: true,  isRate: false, fmt: v => v?.toFixed(2),            forGroups:           ['MID','ATT'] },
  { label: 'Assists/90',             keys: ['assists'],           per90: true,  isRate: false, fmt: v => v?.toFixed(2),            forGroups:      ['DEF','MID','ATT'] },
  { label: 'xG/90',                  keys: ['expectedGoals','xG'],per90: true,  isRate: false, fmt: v => v?.toFixed(2),            forGroups:           ['MID','ATT'] },
  { label: 'xA/90',                  keys: ['expectedAssists','xA'], per90: true, isRate: false, fmt: v => v?.toFixed(2),          forGroups:      ['DEF','MID','ATT'] },
  { label: 'Key Passes/90',          keys: ['keyPasses'],         per90: true,  isRate: false, fmt: v => v?.toFixed(2),            forGroups:      ['DEF','MID','ATT'] },
  { label: 'Dribbles/90',            keys: ['successfulDribbles'],per90: true,  isRate: false, fmt: v => v?.toFixed(2),            forGroups:           ['MID','ATT'] },
  { label: 'Shots on Target/90',     keys: ['shotsOnTarget'],     per90: true,  isRate: false, fmt: v => v?.toFixed(2),            forGroups:           ['MID','ATT'] },
];

function computeCompetitionTierStandouts(player, allPlayers, competition, playerLeagueDisplay) {
  if (!player || !allPlayers || allPlayers.length === 0) {
    return { peerGroup: null, cohortSize: 0, rows: [] };
  }
  const group = positionGroup(player.position);

  // Step 1: figure out the last-season slice for the focal player in this competition
  const focalRowsAll = (player.history || []).filter(r => competitionType(r._league) === competition);
  if (focalRowsAll.length === 0) {
    return { peerGroup: null, cohortSize: 0, rows: [], reason: 'no_rows' };
  }
  const focalSeasonSorted = [...focalRowsAll].sort((a, b) =>
    (b._season_year || '').localeCompare(a._season_year || '')
  );
  const focalLastSeason   = focalSeasonSorted[0]._season_year;
  const focalLastRows     = focalSeasonSorted.filter(r => r._season_year === focalLastSeason);
  if (focalLastRows.length === 0) {
    return { peerGroup: null, cohortSize: 0, rows: [], reason: 'no_last_season' };
  }

  // Minutes floor for tournament participation (same as Key Trends). A
  // player with very few minutes in last season's tournament gets the
  // "did not participate" empty state instead of nonsense z-scores.
  if (competition !== 'domestic') {
    const focalLastMinutes = focalLastRows.reduce(
      (a, r) => a + (r.minutesPlayed || r.minutes || 0), 0
    );
    if (focalLastMinutes < 270) {
      return { peerGroup: null, cohortSize: 0, rows: [], reason: 'insufficient_last_season_minutes' };
    }
  }

  // Peer-group label + cohort filter
  let peerGroup;
  let cohortFilter;   // (p) => boolean — applied before the per-metric loop
  if (competition === 'domestic') {
    // For domestic, the peer group is players in the same league tier.
    // This makes "Goals (z=2.3)" meaningful: 2.3 above the average for the
    // tier the player actually competes in, not against the whole roster.
    const focalTier = leagueTier(playerLeagueDisplay, player.advancedStats);
    if (focalTier == null) {
      // No tier info available — fall back to the whole domestic cohort
      // (less precise but still informative).
      peerGroup = playerLeagueDisplay || 'Domestic';
      cohortFilter = (p) => true;
    } else {
      peerGroup = `Tier ${focalTier} · ${playerLeagueDisplay || 'Domestic'}`;
      cohortFilter = (p) => leagueTier(p.league, p.advancedStats) === focalTier;
    }
  } else {
    // Tournament: cohort is players who appeared in the same tournament(s).
    // No tier filter — the tournament itself defines the peer group.
    const tournaments = new Set(focalLastRows.map(r => r._league).filter(Boolean));
    peerGroup = Array.from(tournaments).join(' · ') || COMPETITION_LABELS[competition];
    cohortFilter = (p) => true;
  }

  // Step 2: build the cohort. For each loaded player, find their most-recent
  // season slice in this competition (match the focal player's competition,
  // not necessarily their season; we want the most recent year each player
  // appeared in this competition, which is the fairest peer).
  //
  // For per-90 metrics, the cohort player needs ≥ 270 minutes in their slice
  // to be included. For total metrics, ≥ 1 minute counts.
  const MIN_MINUTES_COHORT = 270;

  // Helper: aggregate a player's most-recent competition slice for a metric.
  const playerSliceMetric = (p, def) => {
    const rows = (p.history || []).filter(r => competitionType(r._league) === competition);
    if (rows.length === 0) return null;
    // Most recent season's rows
    const sorted = rows.sort((a, b) => (b._season_year || '').localeCompare(a._season_year || ''));
    const top = sorted[0]._season_year;
    const slice = sorted.filter(r => r._season_year === top);
    let sumVal = 0, sumMin = 0, weightedRateSum = 0, weightedRateMin = 0, foundAny = false;
    for (const r of slice) {
      let v = null;
      for (const k of def.keys) {
        if (typeof r[k] === 'number' && !isNaN(r[k])) { v = r[k]; break; }
      }
      if (v == null) continue;
      foundAny = true;
      const min = r.minutesPlayed || r.minutes || 0;
      if (def.isRate) {
        if (min > 0) { weightedRateSum += v * min; weightedRateMin += min; }
      } else if (def.per90) {
        sumVal += v; sumMin += min;
      } else {
        sumVal += v;
      }
    }
    if (!foundAny) return null;
    let value, totalMin;
    if (def.isRate) {
      if (weightedRateMin <= 0) return null;
      value = weightedRateSum / weightedRateMin;
      totalMin = weightedRateMin;
    } else if (def.per90) {
      if (sumMin <= 0) return null;
      value = (sumVal * 90) / sumMin;
      totalMin = sumMin;
    } else {
      // Use the slice's total minutes for inclusion filtering even for totals
      totalMin = slice.reduce((a, r) => a + (r.minutesPlayed || r.minutes || 0), 0);
      value = sumVal;
    }
    return { value, minutes: totalMin };
  };

  // Step 3: for each relevant metric, build cohort distribution + focal value, derive z
  const rows = [];
  for (const def of COMPETITION_TIER_METRICS) {
    if (!def.forGroups.includes(group)) continue;

    const cohortValues = [];
    let focalValue = null;

    for (const p of allPlayers) {
      const isFocal = (p === player || p.id === player.id);
      // Only the focal player and matching-cohort players are evaluated.
      // The focal player is always evaluated regardless of cohortFilter
      // (we need their value for the z computation).
      if (!isFocal && !cohortFilter(p)) continue;
      const r = playerSliceMetric(p, def);
      if (r == null) continue;
      const needsMin = def.per90 || def.isRate;
      if (needsMin && r.minutes < MIN_MINUTES_COHORT) continue;
      if (!isFocal) cohortValues.push(r.value);
      if (isFocal)  focalValue = r.value;
    }

    if (focalValue == null) continue;
    if (cohortValues.length < 5) continue;   // need a meaningful cohort

    const mean = cohortValues.reduce((a, v) => a + v, 0) / cohortValues.length;
    const variance = cohortValues.reduce((a, v) => a + (v - mean) ** 2, 0) / cohortValues.length;
    const std = Math.sqrt(variance);
    if (std === 0) continue;
    const z = (focalValue - mean) / std;
    if (z < TIER_Z_THRESHOLD) continue;

    rows.push({
      label: def.label,
      value: focalValue,
      z,
      cohortSize: cohortValues.length,
      fmt: def.fmt,
    });
  }
  rows.sort((a, b) => b.z - a.z);

  return {
    peerGroup,
    cohortSize: rows[0]?.cohortSize ?? 0,   // representative
    rows,
  };
}

// ─── MV history point builder ───────────────────────────────────────────────
// Cleans up the raw history_data into a series of chronologically-ordered
// MV points suitable for the Market Value History chart.
//
// Inputs: history rows (any order, possibly multiple per season — club AND
// national team rows, mid-season transfers split into multiple rows, etc.)
//
// Output: array of { season, age, value, kind: 'start'|'end' } points where
//   - season   = the canonical season label (e.g. "23/24")
//   - age      = age_in_season for that season's chosen row
//   - value    = mv_start (for kind='start') or mv_end (for kind='end')
//   - oldest first, ordered by the season's start date
//
// Per-season logic:
//   1. National-team rows (calendar-year format like "2024") are dropped
//      because they have the same MV as the same-season club row and
//      misorder against "YY/YY" seasons.
//   2. When multiple club rows exist for one season (mid-season transfers
//      or duplicates), pick the one with the most minutes played.
//   3. From the chosen row, emit `start` (mv_start) and `end` (mv_end) as
//      two points UNLESS they're equal — then emit just one (the end).
//   4. Across-season transitions: only emit the start of a season if it
//      meaningfully differs from the previous season's end (otherwise
//      we'd get visually redundant flat segments).
function buildMvHistoryPoints(history) {
  if (!Array.isArray(history) || history.length === 0) return [];

  // Filter to rows that have a YY/YY style season label (drops national-team
  // calendar-year rows). Also require mv_end to be present.
  const SEASON_RE = /^\d{2}\/\d{2}$/;
  const valid = history.filter(r => {
    const sy = r._season_year;
    return typeof sy === 'string' && SEASON_RE.test(sy) && r.mv_end != null;
  });
  if (valid.length === 0) return [];

  // Group by season, pick the canonical (most-minutes) row per season
  const bySeason = new Map();
  for (const r of valid) {
    const sy = r._season_year;
    const min = r.minutesPlayed || r.minutes || 0;
    const existing = bySeason.get(sy);
    if (!existing || min > (existing.minutesPlayed || existing.minutes || 0)) {
      bySeason.set(sy, r);
    }
  }

  // Sort seasons chronologically. "YY/YY" sorts cleanly lexicographically
  // (e.g. "19/20" < "20/21" < "23/24") provided we're in the same century,
  // which is always true for football careers.
  const seasonsSorted = Array.from(bySeason.keys()).sort();

  // Emit one or two points per season
  const out = [];
  let prevEnd = null;
  for (const sy of seasonsSorted) {
    const r = bySeason.get(sy);
    const age = (typeof r.age_in_season === 'number') ? r.age_in_season : null;
    const start = (r.mv_start != null) ? r.mv_start : null;
    const end   = (r.mv_end   != null) ? r.mv_end   : null;
    // Emit a "start" only if it meaningfully differs from the previous
    // season's end (avoids flat-redundant segments) AND from this season's
    // own end (single-point seasons get one dot).
    if (start != null && (prevEnd == null || Math.abs(start - prevEnd) > prevEnd * 0.01)
                       && (end == null || Math.abs(start - end) > end * 0.01)) {
      out.push({ season: sy, age, value: start, kind: 'start' });
    }
    if (end != null) {
      out.push({ season: sy, age, value: end, kind: 'end' });
      prevEnd = end;
    }
  }
  return out;
}
// ─────────────────────────────────────────────────────────────────────────────
// computeKeyDrivers(historyRows, position, competition)
//
//   historyRows: the player's history_data array (in any order)
//   position:    the player's primary_position string
//   competition: one of 'domestic' | 'club_tournament' | 'international'
//
// Returns an object:
//   {
//     competition,            // echoes the filter
//     hasData,                // false when no rows match the competition AT ALL,
//                             // OR when the player has no rows for the most
//                             // recent season in this competition
//     reason,                 // when hasData=false, why ('no_rows' | 'no_last_season')
//     categories: [
//       { title, rows: [{ label, last, baseline, deltaPct, higherIsBetter, fmt }] }
//     ]
//   }
//
// Per-metric rules:
//   - last     = value in most recent season's matching row(s)
//   - baseline = average across all prior seasons' matching rows
//   - deltaPct = (last - baseline) / |baseline| × 100
//   - rows with |deltaPct| < 5%  are hidden (not significant)
//   - rows whose last value couldn't be computed (per-90 needs minutes etc.)
//     are dropped silently
// Categories whose rows are all hidden are dropped from the output.
//
// IMPORTANT — multi-row aggregation within a competition slice:
//   When a player has multiple rows for one season in the same competition
//   (e.g. group stage + knockout legs of Champions League), totals are summed
//   and per-90 is computed from the summed totals + summed minutes. This
//   gives a fair "rate for the season's competition slice" reading.
// ─────────────────────────────────────────────────────────────────────────────
function computeKeyDrivers(historyRows, position, competition) {
  const comp = competition || 'domestic';

  if (!historyRows || historyRows.length === 0) {
    return { competition: comp, hasData: false, reason: 'no_rows', categories: [] };
  }

  // Filter to rows matching the requested competition
  const filtered = historyRows.filter(r => competitionType(r._league) === comp);
  if (filtered.length === 0) {
    return { competition: comp, hasData: false, reason: 'no_rows', categories: [] };
  }

  // Sort by season newest-first
  const sorted = [...filtered].sort((a, b) =>
    (b._season_year || '').localeCompare(a._season_year || '')
  );

  const lastSeasonYear = sorted[0]._season_year;
  // Rows that belong to the most recent season's competition slice
  const lastSeasonRows = sorted.filter(r => r._season_year === lastSeasonYear);

  // Tournament name extraction — only relevant for club/international tabs.
  // For domestic, the league is already in the player header chips. For
  // club / international, this tells the user which specific competition
  // (e.g. "UEFA Champions League") the last-season slice came from.
  let tournamentName = null;
  if (comp !== 'domestic') {
    const names = new Set(lastSeasonRows.map(r => r._league).filter(Boolean));
    if (names.size > 0) tournamentName = Array.from(names).join(' · ');
  }
  // Rows that belong to seasons BEFORE the most recent one
  const priorRows      = sorted.filter(r => r._season_year !== lastSeasonYear);

  if (lastSeasonRows.length === 0) {
    return { competition: comp, hasData: false, reason: 'no_last_season', categories: [] };
  }

  // Minutes floor for tournament participation. For Club / International tabs,
  // a player who only played a small number of minutes last season (e.g. 41 min
  // of UEL group stage) is treated as "did not really participate" since the
  // resulting per-90 comparisons would be dominated by noise. Domestic tabs
  // never apply this floor — a player's domestic league IS their main season.
  const MIN_MINUTES_LAST_SEASON_TOURNAMENT = 270;   // ~3 full matches
  if (comp !== 'domestic') {
    const lastSeasonMinutes = lastSeasonRows.reduce(
      (a, r) => a + (r.minutesPlayed || r.minutes || 0), 0
    );
    if (lastSeasonMinutes < MIN_MINUTES_LAST_SEASON_TOURNAMENT) {
      return {
        competition: comp, hasData: false,
        reason: 'insufficient_last_season_minutes',
        categories: [],
        lastSeasonMinutes,
        tournamentName,
      };
    }
  }

  // Aggregate a set of rows into one "season slice" for a single metric def.
  // For per-90 metrics, sum the totals AND minutes, then compute the rate
  // from the sums (rather than averaging per-90 across rows — that would
  // weight a 15-minute substitute equally with a 90-minute starter).
  // For non-per-90 metrics, sum totals (e.g. 3 goals in group stage +
  // 2 goals in knockout = 5 season-competition goals). Rate-style stats
  // like "Pass Acc %" use weighted-by-minutes average.
  const aggregateMetric = (rows, def) => {
    let sumVal = 0;
    let sumMin = 0;
    let weightedRateSum = 0;
    let weightedRateMin = 0;
    let foundAny = false;

    for (const r of rows) {
      let v = null;
      for (const k of def.keys) {
        if (typeof r[k] === 'number' && !isNaN(r[k])) { v = r[k]; break; }
      }
      if (v == null) continue;
      foundAny = true;
      const min = r.minutesPlayed || r.minutes || 0;

      // Heuristic: if def.fmt rounds to a percentage AND label includes '%',
      // treat as a rate (minutes-weighted). Else if per90 is true, treat as
      // a count-per-90 (sum totals + sum minutes). Else, sum totals.
      const isRate = def.label.includes('%');
      if (isRate) {
        if (min > 0) {
          weightedRateSum += v * min;
          weightedRateMin += min;
        }
      } else if (def.per90) {
        sumVal += v;
        sumMin += min;
      } else {
        sumVal += v;
      }
    }

    if (!foundAny) return null;
    const isRate = def.label.includes('%');
    if (isRate) {
      if (weightedRateMin <= 0) return null;
      return weightedRateSum / weightedRateMin;
    }
    if (def.per90) {
      if (sumMin <= 0) return null;
      return (sumVal * 90) / sumMin;
    }
    return sumVal;
  };

  // Minimum minutes for the immediately prior season to be eligible as the
  // sole baseline (instead of averaging across all prior seasons). Below
  // this, the prior season is treated as too noisy for direct comparison
  // and we fall back to the multi-season average.
  const MIN_MINUTES_PRIOR_SEASON = 270;   // ~3 full matches

  // Decide which prior season is "the immediately prior season" for this
  // competition slice. priorRows are already sorted newest-first by the
  // outer sort. Returns the newest prior season's rows + the season-year +
  // a {team, league} pair representing what dominated those rows (the row
  // with the most minutes wins the team/league display).
  const priorSeasonGroups = (() => {
    const bySeason = new Map();
    for (const r of priorRows) {
      const sy = r._season_year || '';
      if (!bySeason.has(sy)) bySeason.set(sy, []);
      bySeason.get(sy).push(r);
    }
    // Sort seasons newest-first
    const seasonKeys = Array.from(bySeason.keys()).sort((a, b) => b.localeCompare(a));
    return seasonKeys.map(sy => {
      const rows = bySeason.get(sy);
      // Total minutes for this season slice
      const totalMin = rows.reduce((a, r) => a + (r.minutesPlayed || r.minutes || 0), 0);
      // Dominant team/league: whichever row has the most minutes
      const dominant = rows.slice().sort((a, b) =>
        (b.minutesPlayed || b.minutes || 0) - (a.minutesPlayed || a.minutes || 0)
      )[0] || {};
      return {
        season: sy,
        rows,
        minutes: totalMin,
        team:    dominant.team    || null,
        league:  dominant._league || null,
      };
    });
  })();

  const immediatePrior = priorSeasonGroups[0] || null;

  // For each metric, compute three baselines:
  //   priorSeason — the immediately prior season's slice (when it has enough
  //                 minutes for this metric type). null otherwise.
  //   avg         — average across ALL prior seasons (per-season slice avg).
  //                 Per-90 / rate metrics still respect the minutes threshold
  //                 when deciding which seasons go into the avg.
  //   careerBest  — best-ever prior season for this metric (max for higher-is-
  //                 better, min for lower-is-better). Same minutes filter.
  //
  // Then we expose:
  //   priorBaseline = priorSeason if available, else avg     ← "vs Prior Season" mode default
  //   priorSource   = 'prior_season' | 'avg' | null          ← so the UI labels correctly
  //   priorMeta     = { season, team, league } for the source baseline
  //   careerBest    = always the career-best value           ← "vs Career Best" mode

  const MIN_MINUTES_FOR_RATE_BASELINE = 270;

  const computePriorBaselineSet = (def) => {
    const isRate = def.label.includes('%');
    const needsMinFilter = def.per90 || isRate;

    // priorSeason candidate
    let priorSeasonValue = null;
    let priorSeasonMeta  = null;
    if (immediatePrior) {
      const eligible = !needsMinFilter || immediatePrior.minutes >= MIN_MINUTES_PRIOR_SEASON;
      if (eligible) {
        const v = aggregateMetric(immediatePrior.rows, def);
        if (v != null) {
          priorSeasonValue = v;
          priorSeasonMeta  = {
            season: immediatePrior.season,
            team:   immediatePrior.team,
            league: immediatePrior.league,
          };
        }
      }
    }

    // Multi-season slices (always computed)
    const sliceValues = [];   // {value, minutes}
    for (const g of priorSeasonGroups) {
      const eligible = !needsMinFilter || g.minutes >= MIN_MINUTES_FOR_RATE_BASELINE;
      if (!eligible) continue;
      const v = aggregateMetric(g.rows, def);
      if (v != null) sliceValues.push({ value: v, minutes: g.minutes });
    }

    let avgValue = null;
    if (sliceValues.length > 0) {
      avgValue = sliceValues.reduce((a, s) => a + s.value, 0) / sliceValues.length;
    }

    let bestValue = null;
    if (sliceValues.length > 0) {
      const vals = sliceValues.map(s => s.value);
      bestValue = def.higherIsBetter ? Math.max(...vals) : Math.min(...vals);
    }

    // Resolve the "Prior" mode baseline
    let priorBaseline, priorSource, priorMeta;
    if (priorSeasonValue != null) {
      priorBaseline = priorSeasonValue;
      priorSource   = 'prior_season';
      priorMeta     = priorSeasonMeta;   // {season, team, league}
    } else if (avgValue != null) {
      priorBaseline = avgValue;
      priorSource   = 'avg';
      priorMeta     = null;
    } else {
      priorBaseline = null;
      priorSource   = null;
      priorMeta     = null;
    }

    return {
      priorBaseline, priorSource, priorMeta,
      careerBest:    bestValue,
    };
  };

  const SIG_THRESHOLD_PCT = 5;
  const group = positionGroup(position);
  const categoryDefs = KEY_DRIVERS_BY_GROUP[group] || KEY_DRIVERS_BY_GROUP.MID;

  // Pairing rule for raw season-total metrics:
  //   Goals (raw)   is paired with Goals/90 and xG/90 in the Goal Threat category
  //   Assists (raw) is paired with Assists/90 and xA/90 in the Shot Creation category
  // When at least one per-90 pair-partner clears the 5% significance bar,
  // we also surface the raw total even if its own delta is small. This way
  // a per-90 rate jump always travels with its volume context.
  // (Same rule used in both Prior and Best modes.)
  const PAIRING = {
    'Goals':   ['Goals/90', 'xG/90'],
    'Assists': ['Assists/90', 'xA/90'],
  };

  const categories = [];
  for (const cat of categoryDefs) {
    // First pass: compute everyone's last value + baseline + deltas. Keep
    // the per-90 metrics that clear the bar; remember raw paired rows too
    // (we'll attach them at the end if eligible).
    const significant = [];   // metrics that cleared the ≥5% bar
    const candidates  = [];   // every metric with computable lastVal
    for (const def of cat.metrics) {
      const lastVal = aggregateMetric(lastSeasonRows, def);
      if (lastVal == null) continue;

      const bs = computePriorBaselineSet(def);

      let priorDeltaPct = null;
      if (bs.priorBaseline != null && bs.priorBaseline !== 0) {
        priorDeltaPct = ((lastVal - bs.priorBaseline) / Math.abs(bs.priorBaseline)) * 100;
      }
      let bestDeltaPct = null;
      if (bs.careerBest != null && bs.careerBest !== 0) {
        bestDeltaPct = ((lastVal - bs.careerBest) / Math.abs(bs.careerBest)) * 100;
      }

      const priorAbs = priorDeltaPct != null ? Math.abs(priorDeltaPct) : 0;
      const bestAbs  = bestDeltaPct  != null ? Math.abs(bestDeltaPct)  : 0;
      const isSig    = Math.max(priorAbs, bestAbs) >= SIG_THRESHOLD_PCT;

      const row = {
        label: def.label,
        last: lastVal,
        priorBaseline: bs.priorBaseline,
        priorSource:   bs.priorSource,
        priorMeta:     bs.priorMeta,
        priorDeltaPct,
        careerBest:    bs.careerBest,
        bestDeltaPct,
        higherIsBetter: def.higherIsBetter,
        fmt: def.fmt,
      };
      candidates.push(row);
      if (isSig) significant.push(row);
    }

    // Apply pairing: for each significant per-90 metric whose label is the
    // pair-partner of a raw total, ensure the raw row is also present.
    const sigLabels = new Set(significant.map(r => r.label));
    for (const r of candidates) {
      const partners = PAIRING[r.label];
      if (!partners) continue;
      // r is a raw total (Goals or Assists). If any of its partners is sig
      // AND r itself isn't already shown, attach r to the output.
      if (sigLabels.has(r.label)) continue;
      if (partners.some(p => sigLabels.has(p))) {
        significant.push(r);
        sigLabels.add(r.label);
      }
    }

    // Preserve the original category order (raw totals should appear before
    // their per-90 partners since that's how KEY_DRIVERS_BY_GROUP is laid out).
    const orderIndex = new Map(cat.metrics.map((d, i) => [d.label, i]));
    significant.sort((a, b) => (orderIndex.get(a.label) ?? 999) - (orderIndex.get(b.label) ?? 999));

    if (significant.length > 0) categories.push({ title: cat.title, rows: significant });
  }

  // Aggregate the dominant prior-season context across all displayed rows.
  // If most rows use the immediately prior season, we surface its metadata
  // (season + team + league) as a single header line in the UI. If most fall
  // back to avg, we report 'avg' so the header line says "vs prior-seasons
  // average". Tied or mixed results favor 'prior_season' because the more
  // specific signal is the more useful one to display.
  let priorContext = null;
  const allRows = categories.flatMap(c => c.rows);
  if (allRows.length > 0) {
    const priorSeasonRows = allRows.filter(r => r.priorSource === 'prior_season' && r.priorMeta);
    const avgRows         = allRows.filter(r => r.priorSource === 'avg');
    if (priorSeasonRows.length >= avgRows.length && priorSeasonRows.length > 0) {
      // Pick the most-common (season, team, league) tuple — usually they all match.
      const counts = new Map();
      for (const r of priorSeasonRows) {
        const k = `${r.priorMeta.season}|${r.priorMeta.team || ''}|${r.priorMeta.league || ''}`;
        counts.set(k, (counts.get(k) || 0) + 1);
      }
      const [topKey] = Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0];
      const [season, team, league] = topKey.split('|');
      priorContext = { source: 'prior_season', season, team: team || null, league: league || null };
    } else if (avgRows.length > 0) {
      priorContext = { source: 'avg' };
    }
  }

  return { competition: comp, hasData: true, categories, tournamentName, priorContext };
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers used ONLY by the "Calibrated" system. The "Raw" system never touches
// these — it uses the model outputs directly without any smoothing or floors.
// ─────────────────────────────────────────────────────────────────────────────

// Risk buckets — quintile-based on the real 4,770-player distribution.
//   p20=0.99, p40=1.30, p60=1.74, p80=2.76. Each bucket holds ~20% of players.
const RISK_BUCKETS = [
  { max: 0.99,    label: 'Very Low',  color: '#00c896' },
  { max: 1.30,    label: 'Low',       color: '#34d399' },
  { max: 1.74,    label: 'Medium',    color: '#f5a623' },
  { max: 2.76,    label: 'High',      color: '#ff8a4d' },
  { max: Infinity,label: 'Very High', color: '#ff5c5c' },
];

function riskBucket(score) {
  if (score == null || isNaN(score)) return null;
  return RISK_BUCKETS.find(b => score < b.max) || RISK_BUCKETS[RISK_BUCKETS.length - 1];
}

// Graduated weighting for the peak vs short_raw inversion case.
// Small disagreement → 50/50 average. Extreme outlier → peak alone.
//   gap ≤ 15%  → w_peak = 0.50
//   gap ≤ 30%  → w_peak = 0.65
//   gap ≤ 50%  → w_peak = 0.85
//   gap > 50%  → w_peak = 1.00 (peak alone)
function gradWeightForGap(gapPct) {
  if (gapPct <= 0.15) return 0.50;
  if (gapPct <= 0.30) return 0.65;
  if (gapPct <= 0.50) return 0.85;
  return 1.00;
}

// Calibrated peak display rule (only used by the Calibrated system).
// Returns { shortTerm, career, blendedCareer } where:
//   shortTerm     = displayed "1-2Y Peak"  (capped at career, floored at cur)
//   career        = displayed "Career Peak" (blended career floored at cur,
//                   AND pinned at cur when the long-term peak model says
//                   the player is past peak — see DECLINE GUARD below)
//   blendedCareer = pre-floor smoothed value
//
// DECLINE GUARD: when peak.base < cur × (1 − 5%), the long-term model says
// the player has already peaked. Pin career at cur exactly so the display
// matches the trend column (which uses the SAME peak.base vs cur signal).
//
// The 1-2y horizons (h1/h2) are NOT used as a decline trigger here. They're
// 1-2y quantile models, occasionally produce noise like "dip then recover"
// in cases where peak.base > cur. Anchoring the decline display on peak.base
// uses the model best-suited for "is this player past peak" judgments and
// keeps trend ↔ career display perfectly synchronized.
const TREND_DECLINE_PCT = 0.05;

function calibratedPeaks(predictions, valueEur) {
  const peak = predictions?.peak?.base;
  const h1   = predictions?.next1yr?.base;
  const h2   = predictions?.next2yr?.base;
  const cur  = valueEur;

  // Without peak.base there's nothing to display.
  if (peak == null) {
    return { shortTerm: null, career: null, blendedCareer: null };
  }

  // If both horizons are absent (other pitch areas may only ship peak_potential),
  // skip the blend step entirely — career derives from peak.base alone, with
  // the same floor + decline guard applied. shortTerm has no defined value.
  let blended;
  if (h1 == null && h2 == null) {
    blended = peak;
  } else {
    const shortRaw = Math.max(h1 ?? -Infinity, h2 ?? -Infinity);
    if (peak >= shortRaw) {
      blended = peak;
    } else {
      const gapPct = (shortRaw - peak) / peak;
      const wPeak  = gradWeightForGap(gapPct);
      blended = wPeak * peak + (1 - wPeak) * shortRaw;
    }
  }

  let career = cur != null ? Math.max(blended, cur) : blended;

  // DECLINE GUARD: long-term peak model says past peak → pin display at cur
  if (cur != null && cur > 0 && peak < cur * (1 - TREND_DECLINE_PCT)) {
    career = cur;
  }

  // shortTerm only meaningful when at least one horizon is present.
  let shortTerm = null;
  if (h1 != null || h2 != null) {
    const shortRaw = Math.max(h1 ?? -Infinity, h2 ?? -Infinity);
    shortTerm = cur != null
      ? Math.max(Math.min(shortRaw, career), cur)
      : Math.min(shortRaw, career);
  }

  return { shortTerm, career, blendedCareer: blended };
}

// Optimistic / pessimistic / q75 bands for the Calibrated system's profile cards.
// Bands are merged across the contributing models, then opt is floored at the
// calibrated base so the display can never show "optimistic < base".
//   1-2Y card:  opt = max(h1.opt, h2.opt),  pes = min(h1.pes, h2.pes), q75 = max(h1.opt_q75, h2.opt_q75)
//   Career card: opt = calibratedOptimistic (shrinkage)
//                pes = peak.pes
//                q75 = q75Optimistic (capped-at-q90 q75 from the trained pipeline)
function calibratedBands(predictions, valueEur) {
  const cal = calibratedPeaks(predictions, valueEur);
  const h1 = predictions?.next1yr || {};
  const h2 = predictions?.next2yr || {};
  const pk = predictions?.peak    || {};

  // 1-2Y bands
  let shortOpt = null, shortPes = null;
  const opts = [h1.opt, h2.opt].filter(v => v != null);
  const pess = [h1.pes, h2.pes].filter(v => v != null);
  if (opts.length) shortOpt = Math.max(...opts);
  if (pess.length) shortPes = Math.min(...pess);
  if (cal.shortTerm != null && shortOpt != null) shortOpt = Math.max(shortOpt, cal.shortTerm);
  // Pessimistic must never display above the base (a few raw q10 values
  // happen to land slightly above the floored career — clamp for coherence).
  if (cal.shortTerm != null && shortPes != null) shortPes = Math.min(shortPes, cal.shortTerm);
  const shortQ75 = q75ShortTerm(predictions, valueEur);

  // Career bands
  let careerOpt = calibratedOptimistic(predictions, valueEur);
  let careerPes = pk.pes ?? null;
  if (cal.career != null && careerOpt != null) careerOpt = Math.max(careerOpt, cal.career);
  if (cal.career != null && careerPes != null) careerPes = Math.min(careerPes, cal.career);
  const careerQ75 = q75Optimistic(predictions, valueEur);

  return {
    shortTerm: { base: cal.shortTerm, opt: shortOpt, pes: shortPes, q75: shortQ75 },
    career:    { base: cal.career,    opt: careerOpt, pes: careerPes, q75: careerQ75 },
    blendedCareer: cal.blendedCareer,
  };
}

// Unified Trend signal — replaces the old separate Short-Term and Exp.Up
// columns. One number, one direction, one cell.
//
// Rule:
//   exp_pct = (career − cur) / cur            // the displayed peak's % above cur
//   if exp_pct ≥ 5%:   show ↑ X% with exp_pct (matches what Exp.Peak displays)
//   elif decline guard fired (peak.base < cur × 0.95):
//                       show ↓ Y% with (peak.base − cur) / cur (the model's actual decline magnitude)
//   else:               show '—'
//
// Why the asymmetry: career is floored at cur by design, so its % can never
// be negative — it tops out at 0% in decline cases. To surface decline
// magnitudes we have to fall back to peak.base (the un-floored signal).
// This was the entire reason the old Short-Term column existed; merging
// it into the Trend cell only when the displayed value is at the floor
// keeps both signals visible without using two columns.
//
// Returns { pct, isDecline } or null when '—' should display.
const TREND_THRESHOLD_PCT = 0.05;

function valueTrend(predictions, valueEur) {
  if (valueEur == null || valueEur === 0) return null;
  const peakBase = predictions?.peak?.base;
  if (peakBase == null) return null;
  const { career } = calibratedPeaks(predictions, valueEur);
  if (career == null) return null;

  const expPct = (career - valueEur) / valueEur;
  if (expPct >= TREND_THRESHOLD_PCT) {
    return { pct: expPct, isDecline: false };
  }
  // Within ±5% of cur (or career pinned at cur by decline guard):
  // check raw peak.base for a decline signal
  const peakPct = (peakBase - valueEur) / valueEur;
  if (peakPct < -TREND_THRESHOLD_PCT) {
    return { pct: peakPct, isDecline: true };
  }
  return null;   // truly flat — render as '—'
}

// Backwards-compat alias for any code paths that ask for unifiedTrend
const unifiedTrend = valueTrend;

// Calibrated optimistic — combined shrinkage rule.
//   k = 1 / (1 + α · ln(r) + β · ln(1 + g/R))
//   displayed_opt = base · (opt/base)^k
// where r = opt/base, g = opt - base.
//   α = 0.2 (ratio penalty), β = 0.7 (absolute-gap penalty)
//   R = data-driven scale (3 × p95 of the population's base values)
//
// Why R is data-driven: the rule needs to know what counts as "a big absolute
// jump" in this market. €100M is normal for elite players, life-changing for
// regional ones. Anchoring R to the 95th-percentile base lets the rule
// self-tune to whatever distribution of players is loaded — works equally for
// a top-leagues-only dataset (where p95 is high) or a wider dataset (where
// p95 is lower). The 3× multiplier is calibrated so R lands in the
// "near-impossible market jump" zone, where shrinkage starts dominating.
//
// Floored at calibrated career so opt is never below the displayed peak.
const OPT_SHRINK_ALPHA      = 0.2;
const OPT_SHRINK_BETA       = 0.7;
const OPT_SHRINK_REF_FACTOR = 3.0;       // R = 3 × p95(base)
const OPT_SHRINK_REF_FALLBACK = 50e6;    // used when population stat unavailable

let _OPT_SHRINK_REF_CACHED = null;       // cached after first compute

// Compute R from a population of normalized players. Called once after data
// load (see scout.html). Stores the value for use by calibratedOptimistic.
function computeOptimisticRefScale(players) {
  if (!Array.isArray(players) || players.length === 0) {
    _OPT_SHRINK_REF_CACHED = OPT_SHRINK_REF_FALLBACK;
    return _OPT_SHRINK_REF_CACHED;
  }
  const bases = [];
  for (const p of players) {
    const b = p?.predictions?.peak?.base;
    if (b != null && b > 0) bases.push(b);
  }
  if (bases.length === 0) {
    _OPT_SHRINK_REF_CACHED = OPT_SHRINK_REF_FALLBACK;
    return _OPT_SHRINK_REF_CACHED;
  }
  bases.sort((a, b) => a - b);
  const p95 = bases[Math.floor(bases.length * 0.95)];
  _OPT_SHRINK_REF_CACHED = OPT_SHRINK_REF_FACTOR * p95;
  return _OPT_SHRINK_REF_CACHED;
}

function getOptimisticRefScale() {
  // Prefer server-supplied value (server computes from its loaded data)
  if (typeof window !== 'undefined' && typeof window.__OPT_REF_FROM_SERVER === 'number'
      && window.__OPT_REF_FROM_SERVER > 0) {
    return window.__OPT_REF_FROM_SERVER;
  }
  return _OPT_SHRINK_REF_CACHED ?? OPT_SHRINK_REF_FALLBACK;
}

// ============================================================================
// Optimistic display rule — area-aware
// ============================================================================
//
// We have three possible sources of "optimistic":
//   1. q75       — trained quantile (calibrated, narrower than q90, capped at q90 by merge)
//   2. q90       — raw 90th-percentile model output (peak.opt)
//   3. smoothed  — post-hoc shrinkage on q90 using ratio + absolute-gap penalty,
//                  CALIBRATED FOR THE ATTACKER VALUE DISTRIBUTION ONLY.
//
// Per-area behavior:
//   ATTACK:                use min(q75, smoothed_q90).
//                          Smoothing was tuned for attackers whose top-end q90
//                          values produce market-implausible jumps (Yamal-class
//                          €660M ceilings). Smoothing pulls those down.
//   MIDFIELD/DEFENSE/GK:   use min(q75, raw q90).
//                          The shrinkage formula was tuned for the attacker
//                          population's value scale (R ≈ €52M from p95). Other
//                          areas have different distributions and shouldn't
//                          inherit attacker calibration. Use raw quantiles.
//
// Both rules floor the result at the displayed career peak so the optimistic
// band never sits below the displayed base.
//
// The area is read from window.__SCOUT_AREA (set by loadAreaLocally in
// scout.html). Defaults to 'attack' — so existing attacker behavior is
// preserved when this variable isn't set (e.g. server mode before any
// area switch happens).

// The smoothed q90 — combined ratio + absolute-gap shrinkage. Only used for
// the Attack area. Exposed for analytics / debugging.
function smoothedOptimistic(predictions, valueEur) {
  const base = predictions?.peak?.base;
  const opt  = predictions?.peak?.opt;
  if (opt == null) return null;
  if (base == null || base <= 0 || opt <= base) return opt;

  const r = opt / base;
  const g = opt - base;
  const R = getOptimisticRefScale();
  const k = 1.0 / (1.0 + OPT_SHRINK_ALPHA * Math.log(r)
                       + OPT_SHRINK_BETA  * Math.log(1 + g / R));
  let blended = base * Math.pow(r, k);

  const { career } = calibratedPeaks(predictions, valueEur);
  if (career != null) blended = Math.max(blended, career);
  return blended;
}

// Current area — read from window.__SCOUT_AREA (set by the page when an area
// switches). Defaults to 'attack' so existing behavior is unchanged when this
// helper has never been called.
function _currentArea() {
  if (typeof window !== 'undefined' && typeof window.__SCOUT_AREA === 'string') {
    return window.__SCOUT_AREA;
  }
  return 'attack';
}

// Final optimistic — what the table column and profile card display.
// Branches on area: smoothing for Attack, raw q90 for everyone else.
function calibratedOptimistic(predictions, valueEur) {
  const q75    = predictions?.peak?.opt_q75;
  const rawOpt = predictions?.peak?.opt;
  const { career } = calibratedPeaks(predictions, valueEur);

  // Pick the "upper ceiling" we compare q75 against.
  // Attack → smoothed q90 (shrinkage). Other areas → raw q90 unchanged.
  let ceiling;
  if (_currentArea() === 'attack') {
    ceiling = smoothedOptimistic(predictions, valueEur);
  } else {
    ceiling = rawOpt;
    if (ceiling != null && career != null) ceiling = Math.max(ceiling, career);
  }

  // No q75 → fall back to whichever ceiling we computed
  if (q75 == null) return ceiling;
  // No ceiling (degenerate input) → use q75 with floor
  if (ceiling == null || ceiling <= 0) {
    return career != null ? Math.max(q75, career) : q75;
  }

  // Take the smaller. Floor at career.
  let out = Math.min(q75, ceiling);
  if (career != null) out = Math.max(out, career);
  return out;
}

// q75 — directly from the trained q75 pipeline. The merge step already
// capped q75 at q90 (quantile-crossing fix), so this is a clean
// statistically-honest 75th-percentile band. Floored at calibrated career
// so the displayed value never sits below the displayed peak. Returns null
// if no q75 was trained / merged for this player.
function q75Optimistic(predictions, valueEur) {
  const q75 = predictions?.peak?.opt_q75;
  if (q75 == null) return null;
  const { career } = calibratedPeaks(predictions, valueEur);
  return career != null ? Math.max(q75, career) : q75;
}

// Convenience: q75 for the 1-2y window. Takes the higher of h1.opt_q75 and
// h2.opt_q75 (windows nest, so the 2y q75 should be ≥ 1y q75 — match takes
// the higher). Floored at the calibrated short-term peak.
function q75ShortTerm(predictions, valueEur) {
  const h1q = predictions?.next1yr?.opt_q75;
  const h2q = predictions?.next2yr?.opt_q75;
  const cands = [h1q, h2q].filter(v => v != null);
  if (!cands.length) return null;
  const top = Math.max(...cands);
  const { shortTerm } = calibratedPeaks(predictions, valueEur);
  return shortTerm != null ? Math.max(top, shortTerm) : top;
}

// ── Contract filter ───────────────────────────────────────────────────────────
// Reference date for "years remaining" calculation
const CONTRACT_CUTOFF_MS = new Date('2026-05-01').getTime();

function contractYearsRemaining(expiryStr) {
  if (!expiryStr) return null;
  const d = new Date(expiryStr);
  if (isNaN(d.getTime())) return null;
  return (d.getTime() - CONTRACT_CUTOFF_MS) / (365.25 * 24 * 60 * 60 * 1000);
}

// Contract filter options shown in the sidebar
// To add a new threshold, just add an entry here: { label, maxYears }
const CONTRACT_FILTER_OPTIONS = [
  { label: 'Any',   maxYears: null },
  { label: '≤ 6mo', maxYears: 0.5  },
  { label: '≤ 1yr', maxYears: 1    },
  { label: '≤ 2yr', maxYears: 2    },
  { label: '≤ 3yr', maxYears: 3    },
];

// Export everything to window so Babel scripts can access them
Object.assign(window, {
  fmtEur,
  normalizePlayer,
  POSITIONS_LIST,
  BEST_PEAK_CUTOFF_EUR,
  SEASON_STAT_CATEGORIES,
  ADV_DISPLAY_STATS,
  CONTRACT_CUTOFF_MS,
  contractYearsRemaining,
  CONTRACT_FILTER_OPTIONS,
  RISK_BUCKETS,
  riskBucket,
  gradWeightForGap,
  calibratedPeaks,
  calibratedBands,
  calibratedOptimistic,
  smoothedOptimistic,
  q75Optimistic,
  q75ShortTerm,
  computeOptimisticRefScale,
  getOptimisticRefScale,
  valueTrend,
  unifiedTrend,
  positionGroup,
  KEY_DRIVERS_BY_GROUP,
  computeKeyDrivers,
  competitionType,
  COMPETITION_LABELS,
  buildMvHistoryPoints,
  computeTierStandouts,
  computeCompetitionTierStandouts,
  TIER_Z_METRICS,
  leagueTier,
  LEAGUE_TIER_MAP,
});