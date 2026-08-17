# Calibrated System — Calculations & Formulas

This document explains every transformation applied in the **Calibrated** display mode of Scout ML, end to end — from the raw model outputs sitting in the JSON, through every smoothing and floor-and-cap step, to the final numbers shown in the search list and the player profile.

The Calibrated mode is one of two display systems in the app. The **Raw** system shows model outputs untouched. **Calibrated** applies a series of statistical and display-friendly adjustments designed to make the numbers more defensible for scouting.

---

## 1. Inputs — what comes out of the models

Each player has three independent model blocks, each producing a calibrated quantile distribution:

| Block | Target | Source pipeline |
|---|---|---|
| `peak_potential`  | Highest market value across the full forecast window (career-peak target) | `model/` (single-horizon) |
| `horizon_1y`      | Market value 1 year ahead                                                  | `model_mh/1y/` (multi-horizon) |
| `horizon_2y`      | Market value 2 years ahead                                                  | `model_mh/2y/` (multi-horizon) |

Each block exposes four quantile predictions:

| Field | Meaning |
|---|---|
| `expected_eur`         | q50 — model's median forecast (the "central" or "expected" value) |
| `pessimistic_eur`      | q10 — 10th-percentile forecast (low-confidence floor) |
| `optimistic_eur`       | q90 — 90th-percentile forecast (high-confidence ceiling) |
| `optimistic_q75_eur`   | q75 — trained 75th-percentile band (capped at q90 by merge step) |

All four quantiles were **independently trained** (each is its own XGBoost model with `quantile_alpha` set to the target percentile) and **isotonically calibrated** so the actual coverage matches the nominal target within ~3% on held-out data.

A **risk score** is also computed at merge time on the raw quantiles: `risk_score = (q90 − q10) / q50`. This is the width of the prediction interval as a fraction of the central forecast — used for the "Opt.Risk" pill.

### Notation used throughout this document

| Symbol | Meaning |
|---|---|
| `cur` | Current market value of the player (`metadata.current_value_eur`) |
| `peak.base` | `peak_potential.expected_eur` (raw q50 of the career-peak model) |
| `peak.opt`  | `peak_potential.optimistic_eur` (raw q90) |
| `peak.q75`  | `peak_potential.optimistic_q75_eur` (raw q75, capped at q90 by merge) |
| `peak.pes`  | `peak_potential.pessimistic_eur` (raw q10) |
| `h1.base`, `h1.opt`, `h1.q75`, `h1.pes` | Same fields from `horizon_1y` |
| `h2.base`, `h2.opt`, `h2.q75`, `h2.pes` | Same fields from `horizon_2y` |
| `shortRaw`     | `max(h1.base, h2.base)` — the higher of the two short-term central forecasts |
| `R`            | Data-driven reference scale: `3 × p95(peak.base across population)` |

---

## 2. Career Peak — Expected (the "Exp.Peak" column)

This is the headline central forecast for the player's long-term value: what the model thinks the player will be worth at their career-best point.

### 2a. Graduated career-peak smoothing (handles model contradictions)

**The problem.** The `peak_potential` model targets the maximum value a player will hit at any point. When this is smaller than `max(h1.base, h2.base)` — i.e. the model thinks the 1- or 2-year horizon will exceed the long-term peak — that's a contradiction. Either the long-term model is too pessimistic, or the short-term horizons are too optimistic, or the truth is somewhere in between.

**The rule.** When the short-term horizons exceed the long-term peak, blend them by *gap size*. **`w_pk` is the weight on `peak.base`** — i.e. higher `w_pk` means the long-term peak dominates the display. The rule is asymmetric: small gaps mean the two models basically agree, so we average them; large gaps mean one of them is producing an outlier, and we trust the long-term peak model (which is purpose-built for this target) over the short-term horizons (which are 1-2y snapshot models, not peak detectors).

```
short_max = max(h1.base, h2.base)

if peak.base ≥ short_max:
    blendedCareer = peak.base               # no contradiction, use as-is
else:
    gap = (short_max − peak.base) / peak.base
    if   gap ≤ 0.15:  w_pk = 0.50            # nearly equal — average them (50/50)
    elif gap ≤ 0.30:  w_pk = 0.65            # mild gap — lean toward peak (65/35)
    elif gap ≤ 0.50:  w_pk = 0.85            # large gap — peak dominates (85/15)
    else:             w_pk = 1.00            # implausible gap — peak alone, ignore short_max

    blendedCareer = w_pk × peak.base + (1 − w_pk) × short_max
```

**Why we trust the peak model more as the gap grows.** When `gap > 50%`, `short_max` exceeds `peak.base` by more than 1.5×. That's far more likely to be h1/h2 noise (an unusual feature pattern producing a wild snapshot prediction) than a sign that the peak model is severely underestimating the player. Letting short_max influence the display in that regime would amplify outlier noise into the headline number. By falling back to `peak.base` alone at 50%+, we treat the contradiction as "trust the model that's actually trained for this target."

### 2b. Floor at current value

```
career = max(blendedCareer, cur)
```

A basic sanity property: the long-term ceiling should never display below the player's current market value.

### 2c. Decline guard

```
if peak.base < cur × 0.95:
    career = cur     # pin display at exactly current value
```

This pins the displayed career peak at `cur` exactly when the long-term peak model says the player has already peaked. Without this guard, ~233 players (5%) would show contradictions where the trend column says ↓ but the displayed peak sits above current — because `blendedCareer` blends in `short_max`, which can drag the display upward even when `peak.base` alone is below `cur`.

**Why we key off `peak.base`** (the long-term central forecast), not `max(h1, h2)`: the trend column also uses `peak.base vs cur` as its sole signal (see section 5). Sourcing the decline guard from the same predicate guarantees the trend column and the career display can never disagree. The 1-2y horizon models occasionally produce noise patterns like "decline now, recover later" — those patterns are noise relative to what the 1-2y models were trained to predict, so we don't let them drive decline framing on the display.

This is the value shown in the **Exp.Peak** column and as the headline of the Career Peak card on the profile page.

---

## 3. Career Peak — Optimistic (the "Opt.Peak" column)

We have two candidate "optimistic" numbers per player and pick the smaller.

### 3a. Smoothed q90 (combined ratio + absolute-gap shrinkage)

The raw `peak.opt` (q90) is a calibrated quantile, but for elite young players the model's uncertainty is so wide that q90 produces market-implausible jumps (Yamal cur €200M → q90 €660M).

We smooth the raw q90 using a combined ratio + absolute-gap penalty:

```
r = peak.opt / peak.base                    # multiplicative ratio
g = peak.opt − peak.base                    # absolute € gap
R = 3.0 × p95(peak.base across population)  # data-driven reference scale

k = 1 / (1 + α·ln(r) + β·ln(1 + g/R))
smoothed_q90 = peak.base × r^k

with α = 0.2, β = 0.7
```

The `α·ln(r)` term penalizes large multiplicative ratios — handles small-value players whose q90 is many multiples of their base. The `β·ln(1 + g/R)` term penalizes large absolute jumps — handles elite players whose ratio looks moderate but whose absolute € gap is unrealistic.

`R` is **data-driven**: 3 × the 95th-percentile of `peak.base` across all loaded players. For the current dataset R ≈ €52M. The 3× multiplier was chosen so R lands in the "near-impossible market jump" zone where shrinkage starts dominating. The rule self-tunes to whatever distribution of players is loaded.

### 3b. q75 (trained quantile)

The q75 model was trained as a separate XGBoost regressor with `quantile_alpha=0.75`. Its output is a true 75th-percentile prediction, calibrated post-hoc with isotonic regression. **Cross-validation showed actual coverage of 73.5–73.7%** vs the 75% target — well within tolerance.

The merge step caps q75 at q90 (`min(q75, q90)`) to fix quantile crossings where the independently-trained models occasionally produce q75 > q90. About 2% of cases hit this cap.

### 3c. The combination rule — `min(q75, smoothed)`

```
optimistic_displayed = min(q75, smoothed_q90)
optimistic_final = max(optimistic_displayed, career)   # floor at career
```

**Why min, no parameters, no thresholds:**

Population analysis on 4,770 players:
- ~96% of cases: `q75 < smoothed_q90` (median: q75 is 22.6% lower).
- ~2% of cases: `q75 ≈ smoothed_q90`.
- ~2% of cases: `q75 ≥ smoothed_q90` — these are Yamal-class outliers where q75 hit the q90 cap due to quantile crossing in extreme uncertainty cases.

For the 96%, `q75` is the calibrated tighter band — trust it. For the 2% where `q75 ≥ smoothed`, the trained q75 isn't actually informative about the upper tail anymore (it crashed into q90), so we use the shrunk q90 which has a defensible floor. Taking the min handles both cleanly with no thresholds.

**Examples:**

| Player | `cur` | `peak.opt` (q90) | `smoothed_q90` | `peak.q75` | `min(q75, smoothed)` |
|---|---|---|---|---|---|
| Yamal | €200M | €660M | €443M | €660M | **€443M** |
| Doué | €90M | €259M | €174M | €216M | **€174M** |
| Mastantuono | €50M | €168M | €105M | €130M | **€105M** |
| Estêvão | €80M | €266M | €142M | €173M | **€142M** |
| Haaland | €180M | €269M | €223M | €198M | **€198M** |
| Saka | €150M | €240M | (~€211M) | (~€177M) | **q75 (~€177M)** |

For elite/young/uncertain cases, `smoothed_q90` typically wins (Yamal, Doué, Mastantuono, Estêvão). For typical cases, `q75` wins (Haaland, Saka).

This is the value shown in the **Opt.Peak** column and as the Optimistic pill on the Career Peak card.

---

## 4. 1-2 Year Peak (`shortTerm`) — used in the profile, not the search list

The display value for the 1-2 year window:

```
shortTerm_raw = max(h1.base, h2.base)
shortTerm = clamp(shortTerm_raw, min=cur, max=career)
```

Two clamps:

- **Lower clamp at `cur`**: a player's expected near-term peak should never display below their current market value. If the model predicts a 1-2yr decline, that's communicated via the trend column (section 5) and the Outlook panel (section 6), not by displaying a sub-current peak.
- **Upper clamp at `career`**: the 1-2yr peak should never exceed the calibrated career peak. Any contradiction has already been resolved upstream by the graduated smoothing in section 2.

This value is shown:
- In the player profile header summary row ("1-2 Year Peak")
- Inside the profile **Near-Term Outlook** companion panel as "1-2 Year Expected Peak"

It is **NOT** shown as a column in the search list.

---

## 5. Trend column (the search-list "Trend" cell)

A unified directional indicator that replaces what used to be two separate columns (Short-Term + Exp.Up). One number, one direction, one cell. The rule:

```
exp_pct = (career − cur) / cur                 // % above cur of the displayed Career Peak

if exp_pct ≥ 5%:
    show ↑ X%  with X = exp_pct × 100
    (exact same direction & magnitude as the displayed Career Peak)

elif peak.base < cur × 0.95:
    show ↓ Y%  with Y = (cur − peak.base) / cur × 100
    (decline magnitude from the raw long-term peak model)

else:
    show '—'
```

Coloring: ↑ uses the magnitude-ramp palette (small = neutral grey, mid = blue, large = green, matching the old Exp.Up coloring); ↓ is solid red.

**Why two different sources for ↑ vs ↓:**

`career` is floored at `cur` by design — the displayed peak can never sit below current value. That floor means `exp_pct` can only be 0% or positive: it cannot tell you about decline. To surface the decline signal we have to fall back to the un-floored `peak.base`. So the rule uses the smoothed display value for "how high?" and the raw model output for "is this player past peak?" — which is exactly what each signal is good at.

The asymmetry is invisible to the user: they see a single arrow + percentage, with the % matching what's most informative for that player.

**Why this replaces both Short-Term and Exp.Up:**

In the old design, decline players showed `Exp.Up: +0%` (career floored at cur) and `Short-Term: ↓ X%` (raw peak signal) in two adjacent columns. Two cells telling two pieces of the same story, looking superficially contradictory. The unified Trend column shows one number per player, with the direction picked from whichever signal is informative.

**Population distribution** (4,770 players):
- ↑ rising (≥5%): 2,193 (46.0%)
- ↓ declining (≤−5%): 1,486 (31.2%)
- — flat: 1,091 (22.9%)

**Sortable.** Sorts by signed pct: declines below flat below rises in ascending order, vice versa in descending.

---

## 6. Profile cards — Career Peak + Near-Term Outlook

The calibrated profile shows **one large primary card** (Career Peak) and **one companion panel** (Near-Term Outlook).

### 6a. Career Peak card

Standard ModelCard with three values:

| Pill | Value |
|---|---|
| Base Case (headline) | `career` (from section 2) |
| Optimistic           | `min(q75, smoothed_q90)` floored at `career` (from section 3) |
| Pessimistic          | `peak.pes` (raw q10) |

**Note:** The card does not display the q75 separately as its own pill — the combination is already baked into the Optimistic value. This keeps the card consistent with the search-list Opt.Peak column.

### 6b. Near-Term Outlook panel

A companion panel to the right of the Career Peak card. Communicates the player's expected trajectory in plain language. **Three states**, all decided from the same `peak.base vs cur` predicate that drives the trend column and the career-display decline guard — so this panel can never contradict either of them.

```
if peak.base < cur × 0.95:
    state    = "Past Peak"
    headline = "Already at career peak"      (red)
    subtitle = "Long-term model expects this player has peaked"
    value_label   = "Career Peak Forecast"
    value_amount  = peak.base                (the model's career-best forecast from now)
    delta_pct     = (peak.base − cur) / cur  (matches the Trend column exactly)
    delta_color   = red

else:
    gap = (career − shortTerm) / career
    if gap ≤ 15%:
        state    = "Near Peak"
        headline = "Near peak in 1-2y"        (green)
        subtitle = "Expected to approach career ceiling within 1-2 seasons"
        value_label  = "1-2 Year Expected Peak"
        value_amount = shortTerm              (clamped display value)
        delta_color  = green if positive else red
    else:
        state    = "Building"
        headline = "Building toward peak"     (blue)
        subtitle = "Career ceiling is ⌈gap × 100⌉% above the 1-2y forecast"
        value_label  = "1-2 Year Expected Peak"
        value_amount = shortTerm
        delta_color  = green if positive else red

Below the headline, the panel displays value_amount and (value_amount / cur − 1) × 100%.
```

**Why Past Peak shows `peak.base`, not `max(h1, h2)`.** Earlier versions showed the un-clamped `shortRaw = max(h1.base, h2.base)` which is even more pessimistic than `peak.base` for many late-career players. That created two problems:

1. **Headline ↔ value source mismatch.** The headline ("Already at career peak") is decided from `peak.base < cur × 0.95`. Showing a value sourced from h1/h2 meant the panel's headline came from one model while its number came from a different model. Surfacing `peak.base` makes both come from the same source.

2. **Trend column ↔ panel value mismatch.** The Trend column's ↓ percentage is `(peak.base − cur) / cur`. With the old design, the panel showed a different number (e.g. trend ↓ 15% from peak.base, panel −37% from h1). Now they're identical.

3. **h1/h2 noise amplification.** For past-peak players the 1-2y horizons frequently produce more pessimistic snapshots than the long-term peak model justifies. Using h1/h2 made the panel display significantly worse than the model's actual long-term belief. Using peak.base reflects the actual forecast.

Concrete example (Omer Atzili: cur €1.40M, peak.base €1.19M, h1 €0.89M):
- Old panel: "1-2 Year Expected Value €0.89M (−37%)"
- New panel: "Career Peak Forecast €1.19M (−15%)" — matches the Trend column's ↓ 15%

**Why no "dip then recovery" state.** Earlier versions of the panel had a fourth state for the 56 players where `peak.base > cur` (long-term holds) but `max(h1, h2) < cur` (1-2y dip). That orange "Short-term dip — long-term holds" state was removed because the 1-2y horizon models aren't trained to predict recovery patterns — the dip-then-recover signal is essentially noise around `peak.base`. We treat these players as the long-term model treats them: at-peak with normal short-term variation. Trend shows ↑ based on the displayed career-vs-cur, panel shows "Near peak in 1-2y", career displays at `peak.base`. No invented narratives.

**Population distribution** (4,770 players):
- Past Peak: 1,486 (31.2%)
- Near Peak: 3,185 (66.8%)
- Building: 99 (2.1%)

**The 15% threshold** matches the lowest gap-bucket boundary in section 2 (where `w_pk = 0.50`) — i.e. the regime where the model treats short-term and long-term peaks as roughly equal. Above that threshold, the model genuinely predicts a multi-year ramp.

---

## 7. Search-list columns (Calibrated mode)

| # | Column | Source | Notes |
|---|---|---|---|
| 1 | # (rank)         | row index after sort | |
| 2 | Player           | name + club | clickable photo |
| 3 | Pos              | `primary_position` | |
| 4 | Age              | `age_at_cutoff` | |
| 5 | Value            | `cur` | current market value |
| 6 | Exp.Peak         | `career` (section 2) | sortable; calibrated central forecast |
| 7 | Trend            | unified Trend signal (section 5) | sortable; ↑ from career, ↓ from peak.base, '—' otherwise |
| 8 | Opt.Peak         | `min(q75, smoothed)` (section 3) | sortable |
| 9 | Opt.Up           | `(opt / cur − 1) × 100` | sortable; color-coded |
| 10 | Opt.Risk        | `peak.risk_score = (opt − pes) / base` | computed at merge time on raw quantiles |

The old separate **Short-Term** and **Exp.Up** columns have been merged into the single **Trend** column (section 5). The earlier **Q75** column was previously folded into Opt.Peak via the min rule (section 3). The 1-2Y peak column lives in the profile only.

---

## 8. Risk score (Opt.Risk column)

The risk score is computed at merge time, on the **raw** quantile values (before any smoothing or capping):

```
risk_score = (peak.opt − peak.pes) / peak.base
```

It measures the **width of the q10–q90 prediction interval** as a fraction of the central forecast. Higher = more uncertainty.

Rendered as a categorical pill (Very Low / Low / Medium / High / Very High) using quintile-based buckets fit on the population. Bucket boundaries are static constants in `scout-data.js` (`RISK_BUCKETS`).

The label "Optimistic Risk" is used because the dominant uncertainty in the band typically comes from the optimistic side (the q90 has a much wider tail than the q10).

---

## 9. Filters

All filters are applied in the same way for both Raw and Calibrated modes, except for one:

- **Career Peak (€M) range filter** uses the **calibrated** career value (section 2) when the system is set to Calibrated, and uses raw `peak.base` when Raw. This keeps the slider consistent with what the user sees in the table.

The other filters (positions, leagues, teams, nationalities, age, current value, contract years remaining) are mode-agnostic.

The **Team filter** is a cascading filter: it appears only when at least one league is selected, and shows the teams from the selected leagues alphabetically. Tournament-only "leagues" never appear here because the merge step prefers each player's local league as their `current_league`. When the user changes their league selection, any team selections that no longer apply are pruned automatically.

In server mode, `/api/meta` exposes `teams_by_league` (a dict of league → sorted team list) and `/api/players` accepts a `teams` query parameter.

---

## 10. Reference scale R (data-driven)

The shrinkage formula in section 3a uses a population-derived reference scale:

```
R = 3.0 × p95(peak.base across all loaded players)
```

For the current dataset (4,770 attackers): R ≈ €52M.

In server mode, R is computed once at startup and exposed via `/api/meta` as `opt_ref_scale_eur` so the frontend uses the same R as the server (preserves filter/sort consistency between client and server modes).

If the database changes (more elite players, different position mix, different leagues), R recomputes automatically — the rule is self-tuning rather than hard-coded.

---

## 11. Order of operations (worked example: Saka)

Inputs:
```
cur          = 150,000,000
peak.base    = 172,000,000
peak.opt     = 240,000,000
peak.q75     = 177,000,000
peak.pes     =  90,000,000
h1.base      = 165,000,000
h2.base      = 194,000,000
```

Step-by-step:

```
1. shortRaw = max(165M, 194M) = 194M

2. Career peak — graduated smoothing:
   peak.base (172M) < shortRaw (194M)
   gap = (194 − 172) / 172 = 12.8%      → bucket ≤15% → w_pk = 0.50
   blendedCareer = 0.50 × 172 + 0.50 × 194 = 183M

3. Floor at cur:
   career = max(183M, 150M) = 183M

4. Decline guard check:
   peak.base (172M) < cur × 0.95 (142.5M)?  No.  → guard does NOT fire.
   career stays at 183M.

5. shortTerm = clamp(194M, min=150M, max=183M) = 183M
   (h2.base exceeds calibrated career, gets clamped to it)

6. Smoothed q90:
   r = 240/172 = 1.395, g = 68M, R = 52M
   k = 1 / (1 + 0.2·ln(1.395) + 0.7·ln(1 + 68/52))
     = 1 / (1 + 0.0666 + 0.5870) = 0.605
   smoothed_q90 = 172 × 1.395^0.605 = 211M
   floored at career → max(211M, 183M) = 211M

7. Optimistic display:
   optimistic = min(q75, smoothed) = min(177M, 211M) = 177M
   floored at career → max(177M, 183M) = 183M

8. Trend (unified rule, section 5):
   exp_pct = (183 − 150) / 150 = +22%   → ≥5% → ↑ 22%
   (Career-display direction wins; peak.base would have given +15% but
   exp_pct dominates by design.)

9. Outlook panel:
   peak.base (172M) ≥ cur × 0.95 → not Past Peak
   gap = (183M − 183M) / 183M = 0.0%   → Near Peak (≤15%)
   headline: "Near peak in 1-2y" (green)
```

Display:

| Search-list cell | Value |
|---|---|
| Value | €150M |
| Exp.Peak | €183M |
| Trend | ↑ 22% (green) |
| Opt.Peak | €183M |
| Opt.Up | +22% |
| Opt.Risk | (raw risk pill) |

Profile:
- Header chip: Career Peak = €183M
- Career Peak card: Base €183M, Optimistic €183M, Pessimistic €90M
- Near-Term Outlook panel: green dot, "Near peak in 1-2y", 1-2 Year Expected Peak €183M (+22%)

All four places — search row Trend, header chip, profile card, panel — show the same +22% / €183M. ✓

---

## 12. Worked example: a past-peak player (Omer Atzili)

Real player from the dataset.

Inputs:
```
cur          =  1,400,000
peak.base    =  1,194,000
peak.opt     = (~1.4M, near-zero upside)
peak.q75     = (~1.3M)
peak.pes     =  1,090,000
h1.base      =    887,000
h2.base      =    862,000
```

Step-by-step:

```
1. shortRaw = max(887k, 862k) = 887k

2. Career peak — graduated smoothing:
   peak.base (1.194M) ≥ shortRaw (887k)  → no contradiction
   blendedCareer = peak.base = 1.194M

3. Floor at cur:
   career = max(1.194M, 1.400M) = 1.400M    (cur wins)

4. Decline guard check:
   peak.base (1.194M) < cur × 0.95 (1.330M)?  YES.  → guard FIRES.
   career = cur = 1.400M  (pinned exactly)

5. shortTerm = clamp(887k, min=1.400M, max=1.400M) = 1.400M
   (entire 1-2y window forced up to cur — display only)

6. Optimistic display:
   smoothed_q90 ≈ 1.4M (very tight band — risk score ~0.665)
   q75 ≈ 1.3M
   optimistic = min(q75, smoothed) ≈ 1.3M
   floored at career → max(1.3M, 1.4M) = 1.4M

7. Trend (unified rule):
   exp_pct = (1.400M − 1.400M) / 1.400M = 0%   → NOT ≥5%
   peak.base (1.194M) < cur × 0.95 → fallback fires
   peak_pct = (1.194M − 1.400M) / 1.400M = −14.7%   → ≤−5% → ↓ 15%

8. Outlook panel:
   peak.base (1.194M) < cur × 0.95 → Past Peak state
   headline: "Already at career peak" (red)
   value_label  = "Career Peak Forecast"
   value_amount = peak.base = 1.194M
   delta        = (1.194 − 1.400) / 1.400 = −15%
```

Display:

| Search-list cell | Value |
|---|---|
| Value | €1.40M |
| Exp.Peak | €1.40M |
| Trend | ↓ 15% (red) |
| Opt.Peak | €1.40M |
| Opt.Up | +0% |
| Opt.Risk | (raw risk pill) |

Profile:
- Header chip: Career Peak = €1.40M
- Career Peak card: Base €1.40M, Optimistic €1.40M, Pessimistic €1.09M
- Near-Term Outlook panel: red dot, "Already at career peak", **Career Peak Forecast €1.19M (−15%)**

The Trend column's −15% and the panel's −15% delta both come from `(peak.base − cur) / cur`. Single source of truth → no contradictions. The decline guard ensures every cell tells the same story: this player has peaked, expect ~15% decline.

---

## 13. Files implementing this

| File | Where these calculations live |
|---|---|
| `web_system/scout-data.js` | All transformations: `calibratedPeaks`, `calibratedBands`, `smoothedOptimistic`, `calibratedOptimistic`, `unifiedTrend` (alias `valueTrend`), `getOptimisticRefScale` |
| `web_system/scout-components.jsx` | `PlayerRowCalibrated` (search row), `ValueTrendCell`, `ModelCard` |
| `web_system/scout.html` | Profile page (Career Peak card + Near-Term Outlook panel), header chips, table headers, `sortVal` |
| `web_system/server.py` | Server-side mirror: `_build_meta`, `calibrated_career_base`, `calibrated_short_term`, `smoothed_optimistic`, `calibrated_optimistic` (parity with JS, used for server-mode filter/sort) |

Server functions are bit-for-bit equivalent to their JS counterparts so server-mode and local-mode produce identical displayed values.

---

## 14. Backend pipeline summary (how the JSON gets built)

For completeness, here's the chain that produces the JSON the frontend reads:

1. **Train q50/q10/q90** — `04_*.py` scripts in `model/` and `model_mh/{1y,2y}/`. Each fits an XGBoost regressor with `objective=reg:quantileerror, quantile_alpha=...`, then post-hoc calibrates with isotonic regression on a held-out fold so actual coverage matches the nominal target.
2. **Train q75** — `04q_q75*.py` scripts. Same procedure with `quantile_alpha=0.75`.
3. **Production training** — `05*_production.py` scripts retrain on the full dataset (no held-out fold) using the chosen hyperparameters from steps 1-2.
4. **Inference** — `07*_inference.py` scripts run the production models on the current-season feature vectors and write `att_predictions_2425*.csv`.
5. **Merge predictions + history** — `merge_predictions_and_history_data.py` reads all CSVs, attaches every quantile to its model block, and applies `q75 = min(q75, q90)` to fix quantile crossings. Writes `core_players_db.json`.
6. **Final merge** — `merge_final_frontend_db.py` joins extra per-player data (citizenships, contract, photos, advanced stats) and writes `final_players_db.json`. This is what the frontend loads.

The Calibrated transformations described in this document all happen on top of this — none of the smoothing, clamping, or display rules touch the JSON. They run entirely in the frontend (`scout-data.js`) or in the server's filter/sort path (`server.py`), so the underlying model outputs remain available unchanged for the Raw display mode.