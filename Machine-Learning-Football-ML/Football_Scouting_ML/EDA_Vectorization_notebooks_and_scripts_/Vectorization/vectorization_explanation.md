# Vectorization Knowledge Base — Football Scouting Project (Attackers)

This document preserves the complete reasoning behind the per-(player, cutoff_year) vector design, covering every block, every decision, and how each feature traces back to either the EDA findings, the preprocessing decisions, or explicit user-driven requirements. It is a companion to `PREPROCESSING_KNOWLEDGE.md` and should be read after it.

## Purpose of the vectorization stage

The per-row feature file (`att_features.parquet`) contains one row per (player, season, competition). A single player appears across multiple rows — different seasons, different leagues, and different competitions within the same season (league, UCL, national team). This is the right structure for per-row feature engineering but the wrong structure for training a market-value prediction model.

The model needs a single row per "scouting moment" — a point in time when you would evaluate a player for transfer. That moment is the end of a season. At that moment, the scout knows:
- Everything the player did this season (current form)
- Everything the player did in prior seasons (history)
- Tournament exposure across club and national team
- Current market valuation and its trajectory

The model predicts: the player's peak future market value, defined as `log1p(max(mv_end over all strictly later rows))`.

This stage takes the 32,524 per-row file and produces a 17,635 × 319 per-(player, cutoff) file, where each row is a complete snapshot of what's knowable about a player at the end of a given season.

## Source data and baseline

- Input: `data/processed/att_features/att_features.parquet` — 32,524 rows × 154 columns, fully preprocessed with shrunk per-90 stats, engineered features, and tournament flags.
- Output: `data/processed/att_vectors/att_vectors.{parquet,csv}` — 17,635 rows × 319 columns.

## Cutoff selection

A "cutoff" is the end of a season — a scouting moment in time. The vectorizer maps source `_season_year` labels to integer cutoff years using the end-of-season date as anchor:

| Season label | `cutoff_year` | Why |
|---|---:|---|
| `17/18` (ends June 2018) | 2018 | Summer end |
| `2018` (calendar, ends Dec 2018) | 2018 | Same calendar year end |
| `18/19`, `2019` | 2019 | |
| `19/20`, `2020` | 2020 | |
| `20/21`, `2021` | 2021 | |
| `21/22`, `2022` | 2022 | |
| `22/23`, `2023` | 2023 | |
| `23/24`, `2024` | 2024 | |
| `24/25`, `2025` | 2025 | |
| `2017` (calendar only) | 2017 | |

Two types of season labels map to the same cutoff year: European split seasons (e.g. `19/20`, running Aug 2019 → Jun 2020) and contemporaneous calendar-year seasons (e.g. `2020`, running Jan-Dec 2020 for South American/MLS/Scandinavian competitions). Both end at roughly the same scouting moment in late 2020, so they're grouped together.

**Emitted cutoffs (5 total): 2020, 2021, 2022, 2023, 2024.**

### Cutoffs deliberately excluded

Four cutoffs are present in the SEASON_TO_CUTOFF mapping (for history computation) but NOT emitted as training rows:

| Cutoff | Why excluded |
|---|---|
| 2017 | Only 263 players in the data — statistically too thin. Zero prior history possible (nothing earlier exists in the dataset). |
| 2018 | 93% of players have no history. The dataset effectively starts at 17/18, so cutoff-2018 rows contribute only current-season features; the history block is 93% NaN. Training value marginal. |
| 2019 | 88% of players have ≤1 prior season. The `hist_*` block is essentially a repeat of 17/18 for most players — no meaningful trajectory or historical trend information. Training value marginal. |
| 2025 | Last season in the data. No strictly-later rows exist to compute `future_max_value`, so no valid target. Rows at this cutoff are reserved for INFERENCE, not training. |

### History availability per cutoff (the basis for exclusion decisions)

The critical metric is how many prior seasons each player has when the cutoff vector is built. Numbers from the source data:

| Cutoff | Total rows | No history | 1 season | 2+ seasons | Avg history |
|---|---:|---:|---:|---:|---:|
| 2018 | 2,469 | **93.0%** | 6.9% | 0.1% | 0.07 |
| 2019 | 2,567 | 26.1% | 61.9% | 12.0% | 0.87 |
| 2020 | 2,985 | 29.4% | 19.2% | 51.4% | 1.52 |
| 2021 | 3,590 | 27.4% | 19.7% | 52.9% | 2.13 |
| 2022 | 3,577 | 20.5% | 18.3% | 61.2% | 2.68 |
| 2023 | 3,758 | 20.8% | 15.4% | 63.9% | 3.16 |
| 2024 | 3,725 | 18.7% | 16.2% | 65.1% | 3.46 |

The sharp inflection happens between 2019 and 2020: at cutoff 2020 more than 50% of players have meaningful history (2+ prior seasons), while at cutoff 2019 only 12% do. Including 2020 is a clear win; including 2018-2019 dilutes training with weak-history rows.

### Trade-off analysis — why 5 cutoffs beat 4

| Combination | Rows | No-history % | 2+ seasons hist % | Unique players |
|---|---:|---:|---:|---:|
| 2021-2024 (4 cutoffs) | 14,650 | 21.8% | 60.8% | 6,146 |
| **2020-2024 (5 cutoffs) — chosen** | **17,635** | **23.1%** | **59.2%** | **6,626** |
| 2019-2024 (6 cutoffs) | 20,202 | 23.5% | 53.2% | 6,939 |
| 2018-2024 (7 cutoffs) | 22,671 | 31.1% | 47.4% | 7,258 |

Including cutoff 2020 adds 2,985 rows (+20% training data) for only a 1.3 percentage-point worse no-history rate compared to the 2021-2024 set. That's a favorable trade — more data almost always beats slightly cleaner data, especially because the tree model handles the NaN history via `has_history` flag natively.

Cutoffs 2018 and 2019 were explicitly ruled out: 2018 contributes 93% no-history rows (essentially dead weight), and 2019's history is a single repeat season for most players.

## Row selection and primary row identification

For each (player, cutoff) pair, the vectorizer applies these filters in order:

1. **Require at least one league (non-tournament) row** at the cutoff year. If the player has only national-team rows or no rows at all, they are skipped.
2. **Require a valid `future_max_value`**. If `NaN` or `0`, skipped.
3. **Require `_cutoff_year ∈ EMIT_CUTOFFS`**. Excludes 2017, 2018, 2019, 2025.

If a player has multiple league rows in the same cutoff year (e.g. Wayne Rooney 2018 = 17/18 Everton + 2018 MLS DC United), the vectorizer picks the **primary row = the row with max `minutesPlayed`**. This handles mid-season transfers and calendar-split seasons deterministically. About 10% of pairs have multi-row cutoff years; the rest are clean 1-row cases.

## History selection

For a given (player, cutoff) pair, the historical rows are all of the player's rows with `mv_start_date` strictly before the earliest `mv_start_date` at the cutoff year. This is a clean temporal split that handles split-season vs calendar-year boundary correctly.

Important: **excluded cutoffs still contribute as history**. A player active in 17/18 and 20/21 has their 17/18 row USED as history when their cutoff-2020 vector is built. The cutoff exclusion is only about which moments become training ROWS — it does not filter what can be used as historical data within those rows.

## Vector structure — 7 blocks, 319 total columns

### Block A — Identity and cutoff context (8 features)

| Feature | Source |
|---|---|
| `tm_id` | Primary row identifier — kept for GroupKFold grouping, dropped before `fit()` |
| `cutoff_year` | Integer cutoff year — kept for segmented analysis, dropped before `fit()` |
| `age_at_cutoff` | Primary row's `age_in_season` |
| `age_penalty` | `max(0, age − 25)²` — computed fresh at cutoff |
| `primary_position` | Primary row's `primary_position` (text) |
| `secondary_position` | Primary row's `secondary_position` (text) |
| `league_tier_at_cutoff` | Primary row's `league_tier` |
| `team_tier_at_cutoff` | Primary row's `team_tier` |

**Why `tm_id` kept but dropped at fit time**: GroupKFold needs it for player-based cross-validation splits. If left in the feature matrix, XGBoost would treat the integer as a numerical feature and potentially split on it, effectively memorizing specific players. Removal at `fit()` prevents this leakage while preserving its utility for CV.

**Why `cutoff_year` dropped at fit time**: The model needs to generalize to unseen future years (e.g., live inference at cutoff 2025 or 2026). Training with `cutoff_year` as a feature would let the model learn "rows with cutoff_year = 2024 have short forward horizons" or other dataset artifacts that won't generalize. The legitimate market-era signal is already captured through features like `log_team_mean_mv` (continuous, reflects league-wide inflation).

### Block B — Full current-season profile (141 features, copied verbatim)

The vectorizer copies every non-identifier, non-target column from the primary league row into the vector. Explicitly excluded columns:
- Pure identifiers: `tm_id`, `player id`, `team id`, `player`, `_league`
- Metadata-only: `_season_year`, `is_imputed`, `mv_start_date`, `mv_end_date`, `_cutoff_year`
- Target: `future_max_value`, `log_target`

Everything else — raw counts, shrunk per-90 rates, percentages, engineered composites, z-scores, logs, interaction flags, tournament flags, market-movement flags — comes over unchanged.

**Rationale for verbatim copy**: trees are robust to correlated features, and the asymmetric cost of omitting useful information versus including redundant-but-harmless information strongly favors inclusion. Plus, keeping raw counts alongside shrunk per-90 rates gives the model both "volume" and "efficiency" framings of the same behavior, letting it pick whichever is more predictive at each decision node.

### Block C — Cutoff-season tournament summary (6 features)

Aggregated across ALL of the player's rows in the cutoff year (both league and tournament).

| Feature | Computation |
|---|---|
| `tournament_played_at_cutoff` | 1 if any `is_tournament == 1` row exists at cutoff, else 0 |
| `uefa_club_cup_at_cutoff` | 1 if any of UCL/UEL/UECL rows exists |
| `uefa_highest_tier_at_cutoff` | 1=UCL, 2=UEL, 3=UECL, 0=none (Libertadores not here — in Block F instead) |
| `national_team_tournament_at_cutoff` | 1 if any Euro/WC/Gold Cup row |
| `tournament_minutes_at_cutoff` | Sum of `minutesPlayed` across tournament rows |
| `tournament_goals_at_cutoff` | Sum of `goals` across tournament rows |

**Why separate from Block B**: The cutoff-season row picked in Block A is the LEAGUE row only. Tournament rows carry separate statistical profiles that shouldn't be merged into the league profile. This block captures the tournament dimension independently.

### Block D — Domestic league history with league-tier weighting (128 features)

For each of 20 core stats, the vectorizer computes 6 aggregates from rows strictly before the cutoff year (league rows only):

**6 aggregates per stat** = `hist_{stat}_{mean | median | max}` + `current_{stat}_vs_hist_{mean | median | max}` (deltas).

**20 stats chosen for historical aggregation**:

| Category | Stats |
|---|---|
| Offensive output | `goals_p90_shrunk`, `assists_p90_shrunk`, `open_play_goals_p90_shrunk`, `expectedGoals_p90`, `expectedAssists_p90` |
| Shooting | `shotsOnTarget_p90_shrunk`, `totalShots_p90_shrunk`, `shotsFromInsideTheBox_p90_shrunk`, `bigChancesCreated_p90_shrunk` |
| Creation & progression | `keyPasses_p90_shrunk`, `accurateFinalThirdPasses_p90_shrunk`, `successfulDribbles_p90_shrunk`, `progression_p90` |
| Involvement | `touches_p90_shrunk`, `wasFouled_p90_shrunk`, `possessionWonAttThird_p90_shrunk` |
| Negative | `dispossessed_p90_shrunk` |
| Quality | `rating`, `rating_residual`, `modern_forward_score` |

**Stats explicitly excluded from aggregation**:
- `ballRecovery_p90_shrunk`: in the source, `ballRecovery` is 72.5% NaN, and unlike `expectedGoals` the missingness is uniform across all league tiers (22-35% populated per tier). This means the shrunk version is mostly synthetic — aggregating it across history would create misleading "mean" values dominated by Bayesian-imputed defaults.
- `passToAssist_p90_shrunk`: 91% zeros in source, too rare to give meaningful history.

**Why mean AND median AND max?** These answer different scout questions. Mean: long-run average. Median: robust to a single bad season (injury year pulling down mean). Max: personal peak — what the player is capable of at their best. Trees will pick whichever is predictive at each decision node.

**Why 3 deltas?** `current_vs_hist_mean` answers "how does this season compare to my career average?" `current_vs_hist_max` answers "am I setting a new personal best?" Both are strong trajectory signals that naive static features miss.

**League-tier-weighted means (8 additional features)** — user-requested feature. For 8 core stats where league strength matters most, a second type of mean is computed using weights `(6 − league_tier)`:

- Tier 1 → weight 5
- Tier 2 → weight 4
- Tier 3 → weight 3
- Tier 4 → weight 2
- Tier 5 → weight 1

The 8 weighted-mean stats: `goals_p90_shrunk`, `assists_p90_shrunk`, `expectedGoals_p90`, `expectedAssists_p90`, `rating`, `rating_residual`, `modern_forward_score`, `ga_vs_league`. Column name pattern: `hist_{stat}_weighted_mean`.

**Why weighted?** A player scoring 0.5 goals/90 in Bundesliga is not equivalent to 0.5 goals/90 in League Two. The simple mean treats them identically. The weighted mean emphasizes performance in stronger leagues, giving the model a more honest "elite-competition track record" signal. Example from the output:
- Haaland at cutoff 2024: simple historical mean of `goals_p90_shrunk` = 0.551, weighted = 0.579 (lift of +0.028 because his most productive seasons were in top tiers).
- For players whose history is all in one tier, weighted = simple (no difference).
- For players rising through tiers, weighted > simple (correctly credits the higher-tier performances).

### Block E — General career history + league context (12 features)

| Feature | Computation |
|---|---|
| `hist_n_prior_seasons` | Count of prior league rows |
| `has_history` | Binary: 1 if `hist_n_prior_seasons >= 1` |
| `hist_minutes_mean` | Mean minutesPlayed across prior seasons |
| `hist_minutes_sum` | Total minutes across prior seasons |
| `hist_log_mv_prev_1` | Previous season's `log_mv_start` (lag-1) |
| `hist_log_mv_prev_2` | Two seasons ago's `log_mv_start` (lag-2) |
| `hist_career_mv_peak_log` | Max `log_mv_start` across prior seasons |
| `is_at_career_peak` | Binary: 1 if current `log_mv_start >= hist_career_mv_peak_log` |
| `hist_avg_league_tier` | Mean `league_tier` across prior seasons (lower = stronger) |
| `hist_peak_league_tier` | Best tier ever played in (min of `league_tier`) |
| `hist_pct_prior_seasons_in_tier_1_2` | Share of prior seasons in top tiers |
| `hist_pct_prior_seasons_in_tier_1` | Share of prior seasons in tier 1 specifically |

**The four league-context features** (`hist_avg_league_tier`, `hist_peak_league_tier`, `hist_pct_prior_seasons_in_tier_1_2`, `hist_pct_prior_seasons_in_tier_1`) answer "what quality of competition has this player faced historically?" — orthogonal to the stats themselves. A 19-year-old who already played in Serie A (hist_peak_league_tier=1) is more valuable than a 19-year-old who only played in Eredivisie reserves, holding stats constant.

**Why `hist_career_mv_peak_log` matters**: captures players who have already peaked and are declining. A 29-year-old at `log_mv_start = 16.0` with `hist_career_mv_peak_log = 17.5` is a fallen star — different risk profile than a 22-year-old at the same current MV.

**Why `is_at_career_peak`**: a binary partition that separates "still rising" from "past peak" cleanly. Interacts with age to give the model a simple rule to learn.

### Block F — Continental club cup (UCL/UEL/UECL/Libertadores) features (16 features)

**Current-season continental (9 features)**:

| Feature | Computation |
|---|---|
| `cont_played_current_season` | Binary |
| `cont_highest_tier_current` | 1=UCL, 2=UEL, 3=UECL, 4=Libertadores, 0=none |
| `cont_minutes_current` | Sum of minutes in continental rows this season |
| `cont_goals_current` | Sum of goals |
| `cont_assists_current` | Sum of assists |
| `cont_expectedGoals_p90_current` | Mean xG/90 across continental rows |
| `cont_expectedAssists_p90_current` | Mean xA/90 |
| `cont_rating_current` | Mean match rating |
| `cont_xG_vs_domestic_current` | `cont_expectedGoals_p90_current − expectedGoals_p90` (domestic). "Big game player" signal — do they raise their level in Europe? |

**Historical continental (6 features)**:

| Feature | Computation |
|---|---|
| `hist_cont_minutes_sum` | Total career minutes in continental cups before cutoff |
| `hist_cont_rating_mean` | Career mean continental rating |
| `hist_cont_rating_max` | Career best continental rating |
| `hist_cont_expectedGoals_p90_mean` | Career mean continental xG/90 |
| `hist_cont_expectedGoals_p90_max` | Career best continental xG/90 |
| `hist_cont_goals_p90_mean` | Career mean continental goals/90 (shrunk) |

**Trajectory (1 feature)**:
- `cont_current_vs_hist_rating_mean` = `cont_rating_current − hist_cont_rating_mean`. Positive = improving in Europe this year.

**Why this block exists separately**: the `league_tier` column alone puts UCL at tier 1, WC at tier 1, Premier League at tier 1 — indistinguishable. The 8 tournament flags recovered during preprocessing make these separable. UCL exposure is a high-value feature because the market heavily rewards demonstrated ability at the elite club level.

### Block G — Most recent national-team tournament (7 features)

From the player's latest pre-cutoff Euro/World Cup/Gold Cup/Copa appearance:

| Feature | Computation |
|---|---|
| `hist_years_since_last_major_intl` | `cutoff_year − year(latest intl row)` |
| `hist_last_intl_minutes` | Minutes in that latest tournament |
| `hist_last_intl_goals` | Goals |
| `hist_last_intl_assists` | Assists |
| `hist_last_intl_expectedGoals_p90` | xG/90 |
| `hist_last_intl_expectedAssists_p90` | xA/90 |
| `hist_last_intl_rating` | Rating |

All `NaN` if the player has never appeared in a major international tournament.

**Why "latest" and not aggregate history?** National tournaments are rare (every 2-4 years), so career aggregates are unstable. The latest tournament is the freshest signal. Combined with `hist_years_since_last_major_intl`, the model can learn: "4 years since last WC → discount this signal" or "0.5 years since Euro with high xG → weight heavily."

**Never looks at the current cutoff year's international row** — only strictly pre-cutoff. Prevents accidental leakage of the current summer's tournament into the cutoff evaluation.

### Target (1 feature)

`log_target = log1p(future_max_value)` — from the primary league row. Always populated (by filter).

## Handling players with thin or no history

At each cutoff, a portion of players are "new to the data" — they have zero rows before the cutoff year. The vectorizer handles this explicitly:

- **All `hist_*` columns left as `NaN`** for such players. XGBoost handles NaN natively via default split directions — it can learn that "missing history" is itself a signal.
- **`has_history` flag explicitly set to 0**, giving the model a cleanly readable indicator.
- **`hist_n_prior_seasons` set to 0** (not NaN) for numerical accessibility.
- **`is_at_career_peak` set to 0** for players with no peak to compare against.
- **Summable career fields (`hist_minutes_sum`, `hist_cont_minutes_sum`) set to 0** (not NaN) since 0 total minutes is the accurate semantic answer.

From the verification output: 4,075 of 17,635 rows (23.1%) have `has_history = 0`. These are typically young players debuting in the data at or near the cutoff, and players whose prior rows are only in seasons before 17/18 (not captured).

## Vectorization algorithm — bulk groupby for performance

An early implementation iterated player-by-player in Python with nested pandas slices. For 6,600+ players × 5 cutoffs × 20 stats × 3 aggregates × several NaN-safe conversions, this was slow and memory-intensive.

The production vectorizer instead uses **bulk pandas groupby operations per cutoff**:

1. For each cutoff year `C`:
   1. Select eligible primary rows (league, non-null target, in EMIT_CUTOFFS) in bulk.
   2. Pick per-(tm_id) primary row via `sort_values().drop_duplicates()`.
   3. Compute ALL per-player historical aggregates in a SINGLE groupby pass: `hist_rows.groupby('tm_id').agg({stat: ['mean','median','max'] for stat in HIST_STATS})`.
   4. Compute weighted means with numerator/denominator sum aggregates.
   5. Reindex aggregates onto the primary-row index and attach as columns.
   6. Compute deltas via vectorized subtraction.
2. Concatenate all cutoff DataFrames.

Result: full 17,635 × 319 vector generation runs in under a minute.

## Output verification

The vectorizer's `validate()` function performs these checks before writing output:
- `tm_id`, `cutoff_year`, `log_target` are all non-null
- All `cutoff_year` values are in `EMIT_CUTOFFS`
- All binary flag columns contain only 0/1
- `primary_position` and `secondary_position` are non-null
- `age_at_cutoff` falls in [14, 45]

Additional manual verification on Haaland (tm_id 418560):
- Cutoff 2020 (Dortmund tier 1) → `cont_highest_tier_current = 1` (UCL), `hist_cont_minutes_sum = 9` (tiny UEL prior)
- Cutoff 2023 (City, tier 1) → `xG/90 = 0.84`, `hist_cont_minutes_sum = 1471`
- Cutoff 2024 (City, tier 1) → `xG/90 = 0.92`, `hist_goals_p90_shrunk_weighted_mean = 0.579` vs simple mean 0.551 (tier-1 seasons correctly emphasized)
- All transitions chronologically consistent

Residual correlations (controlled for `log_mv_start`) match EDA expectations:
- `log_mv_change_season`: +0.57 (strongest, matches EDA)
- `young_top_club`: +0.30 (second strongest)
- `cont_played_current_season`: +0.17 (moderate positive)
- `is_at_career_peak`: +0.07
- `current_goals_p90_shrunk_vs_hist_mean`: +0.14 (trajectory signal)

## Final output

- Path: `data/processed/att_vectors/att_vectors.parquet` and `.csv`
- Shape: 17,635 rows × 319 columns
- Unique players: 6,626 across all cutoffs
- Per-cutoff breakdown:

| Cutoff | Rows | Unique Players |
|---|---:|---:|
| 2020 | 2,985 | 2,985 |
| 2021 | 3,590 | 3,590 |
| 2022 | 3,577 | 3,577 |
| 2023 | 3,758 | 3,758 |
| 2024 | 3,725 | 3,725 |
| **Total** | **17,635** | **6,626** |

Note: total unique players (6,626) is less than the sum of per-cutoff unique players because most players appear across multiple cutoffs.

## Column count breakdown

| Block | Columns | Description |
|---|---:|---|
| A | 8 | Identity + cutoff context |
| B | 141 | Full current-season verbatim copy |
| C | 6 | Tournament summary |
| D | 128 | Historical aggregates (120 standard + 8 weighted) |
| E | 12 | General career + league context |
| F | 16 | Continental cup current + history |
| G | 7 | Last international tournament |
| Target | 1 | `log_target` |
| **Total** | **319** | |

## Training workflow consumption

```python
import pandas as pd
import numpy as np
from sklearn.model_selection import GroupKFold
import xgboost as xgb

vectors = pd.read_parquet("data/processed/att_vectors/att_vectors.parquet")

# Split columns
groups = vectors['tm_id']                           # CV grouping
y = vectors['log_target']                           # target
X = vectors.drop(columns=['tm_id', 'cutoff_year', 'log_target'])   # features

# GroupKFold CV — no player appears in both train and val within a fold
gkf = GroupKFold(n_splits=5)
for train_idx, val_idx in gkf.split(X, y, groups):
    model = xgb.XGBRegressor(**params)
    model.fit(X.iloc[train_idx], y.iloc[train_idx],
              eval_set=[(X.iloc[val_idx], y.iloc[val_idx])],
              early_stopping_rounds=50)
    # ...
```

At inference time (scoring 24/25 players), a separate inference vector file is built with the same vectorization logic but at `cutoff_year = 2025`, using only data from 24/25 and earlier. The target column is absent — that's what the trained model predicts.

## Reproducibility

Single script: `vectorize.py`. Input: `data/processed/att_features/att_features.parquet`. Output: `data/processed/att_vectors/att_vectors.{parquet,csv}`. Run: `python vectorize.py`. Idempotent — repeated runs produce identical output.
