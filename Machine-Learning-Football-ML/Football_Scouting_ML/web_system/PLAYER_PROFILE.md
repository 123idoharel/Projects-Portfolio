# Player Profile — What You're Looking At

This document walks through every section of the player profile page in
order, explaining what it shows, where the numbers come from, and how each
section helps you understand or interrogate the ML model's forecast.

The profile is organized so the model's prediction comes first, then layers
of evidence drill down to explain why the model is making that prediction.

---

## 1. Header

The top strip shows the player's name, photo (when available), club, league,
nationality, and a compact set of chips: position, age, current market
value, height, foot, and contract expiry.

The top-right shows the headline forecast at-a-glance: the **Career Peak
Forecast** value with an **upside %** badge.

**What this tells you about the model:** the single number the model is
most confident in is this Career Peak (q50, central forecast). Everything
below the header exists to explain or contextualize this number.

---

## 2. ML Model Predictions

This is the central forecast card. The layout has two parts:

### Career Peak card (left, 60%)

- Big number: **calibrated Career Peak base** (the model's q50 forecast,
  with two safety rules applied)
- Pills: **Optimistic** (calibrated upper band) and **Pessimistic** (lower
  band)
- A horizontal range bar with the upside multiplier and risk value

**The two safety rules applied to the displayed Career Peak:**

1. **Floor at current value.** A career-peak forecast is the maximum a
   player is expected to be worth at any point from now on; it can never
   be below the current market value. If the model's raw q50 sits below
   `cur`, the display pins to `cur`.

2. **Decline guard.** When the raw q50 is more than 5% below `cur`, we
   treat that as the model saying "this player has peaked already." The
   panel changes to the Past Peak state (see below).

The raw model outputs (q10 / q50 / q75 / q90) are still in the data; only
the *displayed* numbers are clamped.

### Near-Term Outlook panel (right, 40%)

A small companion panel with one of three states, computed from the same
peak signal so the panel can never contradict the main card:

- **Already at career peak** (red) — `peak.base < cur × 0.95`. Shows the
  raw `peak.base` and the negative % vs cur. The model thinks the player
  has peaked already.
- **Near career peak** (green) — career projection is within 15% of `cur`.
  The player is essentially at their projected ceiling now.
- **Building toward peak** (blue) — career projection is more than 15%
  above `cur`. The player has growth ahead.

For attackers, the gap is computed against the 1-2 year horizon model when
available (more precise). For other pitch areas the proxy is the gap
between career projection and current value. The user-facing wording is
identical regardless.

**What this tells you about the model:** the panel labels the player's
*trajectory state* in plain English so a scout doesn't have to interpret
the bands. A red panel is a sell signal; green is an at-ceiling signal;
blue is a growth signal.

---

## 3. Season Statistics (collapsible, closed by default)

The full per-season stat sheet, with a season selector at the top so the
user can switch between any season the player has played. The stats are
pulled directly from `history_data` rows (Sofascore-style aggregate stats:
goals, assists, key passes, dribbles, pass accuracy, tackles, etc.).

**What this tells you about the model:** this is the raw evidence the
model trained on. Every column shown here is part of what the model used
to derive its forecast.

---

## 4. Advanced Metrics (collapsible, closed by default)

A pure current-season snapshot of engineered features grouped by category
(Attacking Output, Shooting, Chance Creation, Carrying & Threat, Defending,
Performance). All values are current-season per-90 normalized.

Important: this section deliberately does **NOT** show a delta vs prior
seasons. Delta comparisons live in Key Trends (below) where the user can
also pick the competition and comparison mode. Keeping Advanced Metrics
as a static snapshot avoids visual duplication.

**What this tells you about the model:** these are the engineered features
the pipeline computes after raw aggregation. Things like xG-per-90,
big-chances-created-per-90, and other rate stats normalized by playing time.
The model receives these as inputs.

---

## 5. Key Trends for the Model

This is the central explainability panel. It surfaces metrics where the
player's performance changed significantly between last season and a
chosen baseline.

### Competition tabs

Three tabs select which slice of `history_data` to analyze:

- **Domestic League** (default) — domestic league rows (Premier League,
  La Liga, MLS, EFL Championship, etc.)
- **Club Tournament** — continental club competitions (Champions League,
  Europa League, Conference League, Copa Libertadores, Copa Sudamericana)
- **International Tournament** — national-team competitions (World Cup,
  European Championship, Copa America, Gold Cup, AFCON, Nations League)

Tabs the player has zero rows for are disabled with a greyed-out look.

### Tournament participation floor

For Club Tournament and International tabs, a player who played fewer than
270 minutes (≈ 3 full matches) in last season's competition is treated as
"did not really participate." The tab shows an empty state ("Insufficient
[competition] minutes last season — comparison not shown to avoid noise.")
rather than per-90 comparisons computed from a 41-minute sample. The
Domestic tab never applies this floor — the domestic league is the
player's primary season.

### Comparison mode toggle

Right side of the tab bar: **vs Prior Season** (default) or **vs Career
Best**.

- **vs Prior Season** — compare last season's value to the immediately
  prior season's value in the same competition. If the immediately prior
  season had fewer than 270 minutes (for per-90 metrics) the comparison
  silently falls back to the multi-season average of all prior seasons.
  The header line tells the user which one is being used.
- **vs Career Best** — compare to the best-ever prior season for each
  metric. For "higher-is-better" metrics this is the max prior value; for
  "lower-is-better" (like goals conceded) it's the min.

### Header context line

Between the tabs and the categories, a single line tells the user the
context of the comparison:

```
Tournament: UEFA Champions League     Compared to: 23/24 · Barcelona · Spain La Liga
```

When in `vs Prior Season` mode and a specific prior season is available,
the team + league shown there is the one the player was at *during the
prior season*. This makes mid-career team or league changes visible — if a
player went Dortmund → Real Madrid, you'll see "Compared to: 22/23 ·
Borussia Dortmund · Germany Bundesliga" so you understand the comparison
context.

When the comparison falls back to multi-season average, the line says
"Compared to: prior-seasons average."

In `vs Career Best` mode it says "Compared to: career-best season for
each metric."

### Position-aware categories

Categories are tailored per pitch area:

- **GK**: Shot Stopping · Distribution · Workload
- **DEF**: Tackling & Pressing · Aerial · Distribution · Goal Threat ·
  Workload
- **MID**: Passing & Progression · Defensive Work · Goal Threat · Workload
- **ATT**: Goal Threat · Shot Creation · Possession & Dribbling · Workload

A defender's panel will surface tackles, aerial duels, recoveries; an
attacker's panel surfaces shots, xG, key passes, dribbles. Position group
is auto-derived from the player's primary position.

### Significance filter

Only metrics with `|delta| ≥ 5%` are shown. Quiet metrics drop out
silently so the user only sees what changed. Categories with no significant
metrics are hidden too.

### Pairing rule (Goals + Assists)

The raw season totals **Goals** and **Assists** are paired with their
per-90 rate cousins:

- **Goals** is paired with `Goals/90` and `xG/90` (in Goal Threat)
- **Assists** is paired with `Assists/90` and `xA/90` (in Shot Creation)

When a per-90 partner clears the 5% bar, the raw total cell also shows,
even if its own delta is small. This way the volume context always travels
with the rate context. A scout sees both "Yamal scored 9 goals in La Liga
last season" and "that's a 38% jump in Goals/90" in one place.

### Empty states

- **No appearances** in this competition → "No [competition] appearances
  on record."
- **No rows in last season** but rows in prior seasons → "Player did not
  participate in [competition] last season."
- **< 270 min in last season** (tournament tabs only) → "Insufficient
  [competition] minutes last season — comparison not shown to avoid noise."
- **Had rows but no metrics changed ≥ 5%** → "No metrics changed by 5% or
  more vs prior seasons in this competition."

### Why this matters for understanding the model

Key Trends bridges the model's forecast and the underlying evidence. If
the model is forecasting strong upside, you should be able to see why:
goals up, xG up, key passes up. If the model is flagging decline, you
should see goals down, minutes down, rating down.

When the explanation is reassuring (Yamal: +91% shots, +169% assists in
domestic, +171% goals/90 in UCL), the forecast becomes trustworthy. When
the explanation is *missing* — model says huge upside but no metric
changed — that's a signal to check the player's age + value trajectory
more skeptically.

---

## 6. Tier Standouts

A separate panel asking a different question from Key Trends: instead of
"what changed for this player," it asks "where does this player stand
versus their peer group?"

### Competition tabs

Same three tabs as Key Trends: **Domestic League** / **Club Tournament**
/ **International Tournament**. The peer group differs per tab.

### Peer group definitions

- **Domestic League** — same-tier players in domestic competition. The
  player's tier is derived from a frontend `LEAGUE_TIER_MAP` lookup table:
  - Tier 1: Premier League, La Liga, Serie A, Bundesliga, Ligue 1
  - Tier 2: Eredivisie, Liga Portugal, Belgian Pro League, Turkiye Super Lig
  - Tier 3: EFL Championship, MLS, Argentina Liga, German 2.Bundesliga, etc.
  - Tier 4: Italian Serie B, French Ligue 2, Israeli Premier League,
    Saudi Pro League, etc.
  - Tier 5: lower divisions globally
  
  So Yamal (Spain La Liga = Tier 1) is compared to all Tier 1 domestic
  players in the loaded roster. Pedri (also Tier 1 La Liga) is compared
  to the same peer group.

- **Club Tournament** — players who appeared in the same tournament(s)
  last season. The peer group is the entire tournament cohort. Yamal's
  UCL last season is compared against all UCL participants regardless of
  their domestic league. UCL is a self-selecting peer group of elite
  players.

- **International Tournament** — players who appeared in the same
  tournament last season. Yamal at Euro 2024 is compared to other Euro
  2024 participants.

### Is the comparison position-aware?

**No, the cohort is not filtered by position.** The cohort is "all players
in the same competition (and tier, for domestic)." However, the metric
*set* shown is position-aware:

- GK gets only Rating (the other metrics like Goals/90 wouldn't make sense)
- DEF gets Rating, Goals, Assists, Assists/90, xA/90, Key Passes/90
- MID/ATT get the full offensive set

So a center-back's Tier Standouts won't surface "Goals/90 — top 7%"
because Goals/90 isn't in the DEF list to begin with. But the cohort he's
compared against includes attackers and midfielders too. This is honest:
if a defender is in the top 16% of their league tier for assists, that's
genuinely above the tier-average assists value regardless of position.

**If you want position-relative comparison**, that's a future enhancement
(filter cohort to players in the same position group). Current behavior:
metrics are position-relevant, cohorts are competition-wide.

### Z-score threshold

A metric is surfaced only if the player is at `z ≥ 1.0` above the cohort
mean. That's roughly the top 16% of the cohort. Labels convert z-scores
to friendly percentile bands:

- z ≥ 1.0 → top 16%
- z ≥ 1.5 → top 7%
- z ≥ 2.0 → top 2.5%
- z ≥ 2.5 → top 0.6%

Each cell shows the value, the percentile band, the actual z-score, and
the cohort size ("z-score 2.77 · 1,657 peers"). The cohort size matters:
a z-score of 2.0 against 50 peers is less reliable than against 1,000.

### Tournament participation floor (same 270-min rule)

For tournament tabs, if the player played fewer than 270 minutes in last
season's tournament, the tab shows "Insufficient [competition] minutes
last season — peer comparison not shown." Same minutes floor as Key
Trends.

### Empty states

- **No appearances** in this competition → "No [competition] appearances
  on record."
- **< 270 min last season** → "Insufficient [competition] minutes last
  season — peer comparison not shown."
- **No metric stands out** at z ≥ 1.0 → "No metrics stand out above the
  peer-group average for this player." (This is the case for a typical
  Tier-1 player who's average for their tier — no shame, just no
  standouts.)

### Why this matters for understanding the model

Tier Standouts validates the model's forecast against peer context. If
the model is predicting elite ceiling for a young player, the Tier
Standouts panel should typically show standout metrics against the
player's tier or the tournaments they play in. If the model says "huge
upside" but Tier Standouts says "no standouts," that's a signal worth
investigating — the model might be over-extrapolating from raw stats
that look impressive but are tier-typical.

---

## 7. Market Value History

The historical market value chart at the bottom of the profile. Each
season is shown as one or two points (start + end), labeled with the EUR
value and the player's age. The highest career-best season is highlighted
green; the lowest is amber; others are blue.

### Forecast extension

To the right of the historical line, a dashed continuation shows two
forecast anchors:

- **Peak** (green) — the calibrated Career Peak base value (q50)
- **Q75** (cyan-blue) — the calibrated Q75 upper band

Both are floored at the current value so the forecast can never imply a
career peak below where the player is right now. A vertical dashed
divider separates history from forecast.

### Why this matters for understanding the model

This single chart shows the player's actual value trajectory against the
model's projected trajectory. If the historical line is rising steeply
and the dashed Peak extension continues the rise, the model is following
the trajectory. If the historical line is flat or falling and Peak sits
above current value, the model is predicting a turnaround — interrogate
the Key Trends panel to see if recent performance supports that.

---

## What's NOT on the profile (intentionally)

- **No "Value Trajectory" line chart** between the predictions and the
  MV history. The Career Peak card communicates the forecast; the MV
  History chart with forecast extension shows the trajectory. A dedicated
  prediction-line chart would be redundant.
- **No raw summary chip row** (Current Value · +1y · +2y · Peak). The
  Career Peak card with Optimistic/Pessimistic pills covers the same info.
- **No model internals** (feature importances, training metrics, raw
  predictions table). The profile is a scouting tool, not a model
  debugger.

---

## Section ordering — why this order

1. **Forecast first** (Career Peak + Outlook) — the user's primary
   question is "what does the model say?" Answer it immediately.
2. **Raw evidence** (Season Statistics, Advanced Metrics) — closed by
   default. There when needed but doesn't dominate the page.
3. **Change explanation** (Key Trends) — "why does the model say that?"
   Shows what changed in last season's performance.
4. **Peer context** (Tier Standouts) — "how does the player compare to
   peers?" Validates the forecast against tier and tournament context.
5. **Trajectory** (Market Value History) — "where has the player been,
   and where is the model saying they're going?" Visual closure.

The flow goes: forecast → evidence → change → peer context → trajectory.
A scout can stop at any step and have a complete-enough picture.
