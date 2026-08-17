# Preprocessing Knowledge Base — Football Scouting Project (Attackers)

This document preserves the complete reasoning behind every preprocessing and feature-engineering decision made on the attacker dataset, from the raw source file through to the modeling-ready output. It is intended as a reference before the vectorization stage so that every choice is traceable to its justification.

## Source data and baseline

- Raw source: `data/raw/database_ATT.csv` — 45,789 rows × 126 columns, one row per (player, season, competition) from Sofascore-ingested Transfermarkt snapshots, covering 17/18 through 24/25 + calendar-year seasons 2017-2025.
- Intermediate: `data/processed/att_with_tiers_for_eda.csv` — same 45,789 rows, with raw `_league` and `team` text columns replaced by `league_tier` (1-5) and `team_tier` (1-5) after tier merges. The raw `_league` column is reattached during preprocessing for tournament flag derivation.
- Target: `future_max_value` — for each row, the max of `mv_end` across all strictly-later rows of the same player. Constructed externally to our pipeline. Verified to correctly include 24/25 `mv_end` when computing targets of earlier seasons.

## EDA summary — the methodology that shaped every decision

The EDA ran 28 notebook cells to test ~40 candidate features. The central methodological innovation appeared in cell 21: the **residual correlation** test. Rather than asking "does feature X correlate with log(future_max_value)?", every candidate was evaluated against the residual AFTER regressing `log_target` on `log_mv_start`. This answered the only question that matters: does this feature add signal beyond the market's existing valuation of the player?

Features with high solo correlation but low residual correlation were rejected as redundant with `log_mv_start`. Features with modest solo correlation but high residual correlation became the backbone of the engineered feature set.

## Row filters

Four row filters were applied in order to reduce 45,789 rows to the final 32,524:

### Filter 1 — Drop rows where `future_max_value` is NaN (removed 12,335 rows)

**Source:** target construction constraint. The target is undefined for rows where the player has no subsequent observations (single-row players) or whose last observation is in the current row. These rows cannot be used for supervised training.

**Decision verified:** concentrated in 24/25 (4,410 rows) and 23/24 (1,281 rows) as expected, plus ~4,000 single-row players distributed across all seasons. Correct behavior.

### Filter 2 — Drop rows where `future_max_value == 0` (removed 287 rows)

**Source:** cell 2 of the EDA showed a distinct zero-spike in the log-target distribution. Investigation confirmed these are career-ended players whose final Transfermarkt valuation dropped to zero.

**Rationale:** including them pulls the model toward predicting zero for any declining player. Excluding gives cleaner gradients.

### Filter 3 — Drop rows where `mv_start` is NaN (removed 615 rows)

**Source:** `log_mv_start` is the baseline predictor (r = +0.77 with log_target) and the anchor for every residual computation. Rows without it cannot be meaningfully scored.

### Filter 4 — Keep only rows with at least one attacking primary role (removed 28 rows)

**Source:** cell 15 of the EDA. Keep positions {ST, CF, RW, LW, RM, LM, CAM, AM}. Only 28 rows had a pure non-attacker position tag in the attacker dataset.

**Note on CF:** explicitly retained despite small sample (n=111). Per user decision, CF's high median log_target was interpreted as star-bias (only elite players get the CF tag) rather than a sampling artifact.

**Final row count: 32,524.**

## Columns dropped entirely (38 source columns)

Thirty-nine source columns were dropped outright (in addition to `player_positions`, which gets split into two text columns first).

### Goalkeeper stats (19 columns)
`saves`, `savesCaught`, `savesParried`, `savedShotsFromInsideTheBox`, `savedShotsFromOutsideTheBox`, `punches`, `highClaims`, `runsOut`, `successfulRunsOut`, `crossesNotClaimed`, `penaltySave`, `penaltyFaced`, `goalKicks`, `goalsPrevented`, `outfielderBlocks`, `cleanSheet`, `goalsConceded`, `goalsConcededInsideTheBox`, `goalsConcededOutsideTheBox`.

**Source:** cell 3 of the EDA flagged these as >95% null or zero for attackers. Genuinely irrelevant to the use case.

### Defender-specific stats (5 columns)
`blockedShots`, `clearances`, `dribbledPast`, `penaltyConceded`, `ownGoals`.

**Source:** cell 3 nullity audit. Near-zero for attackers. Retaining them adds noise.

### Redundant with retained columns (13 columns)
`aerialLost`, `duelLost`, `inaccuratePasses`, `shotsOffTarget`, `tacklesWon`, `totalCross`, `totalLongBalls`, `totalPasses`, `totalChippedPasses`, `totalOwnHalfPasses`, `totalOppositionHalfPasses`, `countRating`, `totalRating`.

**Source:** manual inventory — each has a retained counterpart. `aerialLost` is captured by `aerialDuelsWon` + the percentage column; `inaccuratePasses` by `accuratePassesPercentage`; `totalCross` by `accurateCrosses` + the percentage; etc. Keeping both versions doubles column count without adding signal.

### Identifiers replaced by derived equivalents (1 column dropped now, 1 later)
`birth_year` (replaced by `age_in_season`). `player_positions` is dropped after being split into `primary_position` and `secondary_position`.

## Columns kept as-is (78 columns total)

### Identifiers retained for joining (8 columns)
`tm_id`, `player id`, `team id`, `player`, `_season_year`, `is_imputed`, `mv_start_date`, `mv_end_date`. These stay through preprocessing and are dropped only at model-input time. They're essential for compression (grouping by `tm_id`) and GroupKFold (splitting by `tm_id`).

**Note:** `team` and `_league` as text columns are NOT in the kept-as-is list because they were already removed in the tier-merge step. `_league` is transiently reattached to derive tournament flags, then dropped again.

### Core metadata (6 columns)
`age_in_season`, `rating`, `appearances`, `matchesStarted`, `minutesPlayed`, `totwAppearances`.

### Percentage stats (12 columns, already normalized)
`accuratePassesPercentage`, `accurateCrossesPercentage`, `accurateLongBallsPercentage`, `aerialDuelsWonPercentage`, `groundDuelsWonPercentage`, `totalDuelsWonPercentage`, `tacklesWonPercentage`, `successfulDribblesPercentage`, `goalConversionPercentage`, `scoringFrequency`, `penaltyConversion`, `setPieceConversion`.

**Rationale:** percentages are inherently comparable across sample sizes. No transformation needed.

### Tier context (2 columns)
`league_tier`, `team_tier`. Merged upstream.

**Source:** cell 5 of the EDA showed a clean monotonic relationship between `league_tier` and `log_target` (tier 1 median ≈ €5M, tier 5 ≈ €250k). Tiers replaced raw league/team strings because they capture hierarchy compactly and work identically for league and tournament rows.

### Raw counts of attack/aggression/market events (50 columns)
`goals`, `assists`, `penaltyGoals`, `penaltyWon`, `aerialDuelsWon`, `goalsAssistsSum`, `hitWoodwork`, `errorLeadToGoal`, `errorLeadToShot`, `yellowCards`, `redCards`, `directRedCards`, `yellowRedCards`, `goalsFromInsideTheBox`, `goalsFromOutsideTheBox`, `freeKickGoal`, `headedGoals`, `leftFootGoals`, `rightFootGoals`, `penaltiesTaken`, `attemptPenaltyMiss`, `attemptPenaltyPost`, `attemptPenaltyTarget`, `shotsFromInsideTheBox`, `shotsFromOutsideTheBox`, `shotsOnTarget`, `totalShots`, `keyPasses`, `bigChancesCreated`, `bigChancesMissed`, `successfulDribbles`, `totalContest`, `touches`, `wasFouled`, `dispossessed`, `possessionLost`, `possessionWonAttThird`, `passToAssist`, `shotFromSetPiece`, `tackles`, `interceptions`, `fouls`, `offsides`, `accurateFinalThirdPasses`, `accurateCrosses`, `accurateChippedPasses`, `accurateLongBalls`, `accurateOppositionHalfPasses`, `accurateOwnHalfPasses`, `accuratePasses`, `totalAttemptAssist`, `ballRecovery`, `mv_start`, `mv_end`.

**Rationale for keeping both raw and shrunk-per-90 versions:** user decision, empirically supported. Cell 10 showed that raw `goals` and `goals_per_90` carry subtly different signal (raw=volume, rate=efficiency) and trees can exploit both without overfitting. Redundancy doesn't hurt tree models — they're invariant to correlated features; feature importance splits across both. The output file includes both the raw and the `_p90_shrunk` partner for each of the 27 applicable columns.

## Columns transformed (34 new columns built from 34 existing or groups)

### Log transforms (3 columns)
`log_target = log1p(future_max_value)`, `log_mv_start = log1p(mv_start)`, `log_mv_end = log1p(mv_end)`.

**Source:** cell 2 showed raw `future_max_value` is severely right-skewed; log-space is near-symmetric and stable. Log-transform is universal for monetary targets.

### Position split (2 columns)
`primary_position` (first token of `player_positions`), `secondary_position` (second token, falls back to `primary_position` when only one position is listed).

**Source:** cells 12 and 15. Kept as text strings rather than one-hot. Modern tree libraries (XGBoost, LightGBM, CatBoost) handle string categoricals natively. User decision: text is cleaner and more interpretable than ~8 binary columns.

**Design choice on fallback:** using `primary_position` as the fallback rather than NaN makes the feature dense and gives the model a free "is_specialist" signal: when `primary == secondary` the player is a one-position specialist, when they differ the player is versatile. Trees learn this distinction at no extra cost.

### xG and xA per-90, with proxy fill (2 columns)
`expectedGoals_p90`, `expectedAssists_p90`.

**Source:** cell 3 flagged 80% null on `expectedGoals` and 79% on `expectedAssists`, concentrated in leagues of tier 3-5. Initial instinct was to drop these columns; EDA cell 4 showed solo r = +0.26 on available rows — too strong to discard.

**Four-step derivation (critical — got iterated three times during the project):**

1. Raw `expectedGoals` and `expectedAssists` are SEASON TOTALS in the source data (verified empirically: Haaland 22/23 shows `expectedGoals = 28.66` over 2776 minutes, which is a total, not a per-match average — the per-match reading would be physically impossible).
2. Convert to per-90 by dividing by `minutesPlayed/90`.
3. Apply Bayesian shrinkage with a LIGHTER prior than other rate stats: `prior_90s = 5` (vs the standard 10). Rationale: xG is already an aggregated statistic (each shot contributes a fractional probability), so it needs less smoothing than raw goal counts. Empirical calibration showed `prior_90s = 5` preserves 90% of elite strikers' real rate while still controlling tiny-minutes outliers.
4. On rows where raw xG/xA are NaN, fall back to the proxy values from the composite formulas below. Both proxies are calibrated to match the real per-90 scale (median 0.27 for xG, 0.10 for xA).

After the fill, raw `expectedGoals` and `expectedAssists` are dropped. No missingness flag is kept — `xg_missing` was tested and found to correlate with `league_tier` at 90%+, so it adds no signal beyond the tier column.

**Why `prior_90s = 5` and not 10:** tested six priors (1, 3, 5, 7, 10, 15). At prior=10, Haaland's 0.93 real xG/90 gets shrunk to 0.78 (84% of real) — excessive given his 30+ match sample. At prior=5, it becomes 0.84 (91% of real) while a 2-minute outlier is still controlled at 0.39. Residual correlation peaks at prior=5 (+0.072 vs +0.042 with no shrinkage).

### Bayesian-shrunk per-90 versions of 27 rate stats (27 columns)
For each of the 27 source count columns listed below, a new column suffixed `_p90_shrunk` is created:

`goals`, `assists`, `shotsOnTarget`, `bigChancesCreated`, `keyPasses`, `successfulDribbles`, `totalContest`, `possessionWonAttThird`, `ballRecovery`, `touches`, `wasFouled`, `dispossessed`, `passToAssist`, `shotFromSetPiece`, `accurateFinalThirdPasses`, `accurateCrosses`, `accurateChippedPasses`, `accurateLongBalls`, `accurateOppositionHalfPasses`, `tackles`, `interceptions`, `fouls`, `offsides`, `totalShots`, `totalAttemptAssist`, `shotsFromInsideTheBox`, `shotsFromOutsideTheBox`.

**Source:** cells 7, 10, 19, and especially 23 of the EDA. Cell 7 showed that raw per-90 rates on unfiltered data have `goals_per_90` correlation of only +0.087 vs raw `goals` at +0.19 — the per-90 is noisier because small-sample players have wild per-90 values. Cell 23 ran the residual correlation test and showed that Bayesian-shrunk goals_p90 beats both raw goals and naive goals_p90 on residual r (0.079 vs 0.070 vs 0.037).

**Formula (closed-form, no iteration):**
```
prior_90s = 10
global_rate = sum(X) / sum(minutesPlayed / 90)      across the whole dataset
prior_X = prior_90s * global_rate
X_p90_shrunk = (X + prior_X) / (minutesPlayed/90 + prior_90s)
X_p90_shrunk = winsorize(X_p90_shrunk, upper=99th_percentile)
```

**What the formula does:** pulls small-sample players toward the global mean (a player with 95 minutes and 1 goal gets shrunk from raw 0.95 to ~0.22), leaves large-sample players almost unchanged (Haaland barely moves). The 99th-percentile winsorization handles any remaining extreme outliers.

**Why prior_90s = 10:** user decision, matches the convention that ~10 matches (900 minutes) is the rough threshold below which a single-season statistical estimate becomes unstable. Cell 19's winsorization plot confirmed that ~99% of players sit below a realistic ceiling once the prior kicks in.

## Columns newly created (27 new engineered features)

### Open-play goals (2 columns)
`open_play_goals = goals − penaltyGoals − freeKickGoal`, then `open_play_goals_p90_shrunk` using the same Bayesian formula.

**Source:** cell 11 of the EDA showed `open_play_goals` correlation +0.193 vs raw `goals` at +0.188 — a small but real improvement. Removing penalty/free-kick goals isolates "open-play conversion ability" which differs from "penalty-taker status."

### Exposure and role ratios (6 columns)
`starts_rate`, `minutes_share`, `is_pen_taker`, `inside_box_goal_share`, `inside_box_shot_share`, `final_third_share`.

**Source:** cells 11, 13, 19 of the EDA.

- `starts_rate = matchesStarted / appearances` — cell 11 showed r = +0.18, a clean role signal.
- `minutes_share = minutesPlayed / (appearances × 90)` — cell 19 showed r = +0.20. Answers "on average, how many minutes does this player get when he plays?" which trees use as a composite role indicator.
- `is_pen_taker = penaltiesTaken >= 3` (binary) — cell 9 showed penalty-taker status is a status signal (trusted player) more than a stat. Binary flag replaces raw count.
- `inside_box_goal_share = goalsFromInsideTheBox / goals` — cell 11 showed r = +0.12. "Poacher" profile.
- `inside_box_shot_share = shotsFromInsideTheBox / totalShots` — cell 13 showed r = +0.04. Kept for completeness.
- `final_third_share = accurateFinalThirdPasses / (accurateOwnHalfPasses + accurateOppositionHalfPasses)` — cell 13 showed r = +0.11. Measures how much of the player's passing is near the opposition goal.

All use safe division guarded against zero denominators.

### Age penalty (1 column)
`age_penalty = max(0, age_in_season − 25)²`.

**Source:** cells 6, 12, and 16.

- Cell 6 showed the actual age-value curve: plateau from 17-26, steep decline from 27-35. Linear age captures the decline but washes out the flat region.
- Cell 12 tested `age_squared` (r = -0.174) vs raw age (r = -0.162) — trivial improvement because the relationship isn't smoothly quadratic.
- Cell 16 introduced the one-sided penalty: 0 below 25, squared distance above. Residual correlation with log_delta was -0.301, the strongest single-feature signal for growth potential at that stage.

Kept alongside raw `age_in_season` so the model has both the level (age) and the nonlinearity (penalty).

### League-relative z-scores (5 columns)
`rating_tier_z`, `goals_tier_z`, `assists_tier_z`, `shotsOnTarget_tier_z`, `bigChancesCreated_tier_z`.

**Source:** cell 17 of the EDA. `goals_tier_z` correlation r = +0.22, `rating_tier_z` r = +0.14. Z-scores normalize within peer group (same league_tier, same season) so that "elite in tier 3" and "average in tier 1" become distinguishable. Grouping is (`league_tier`, `_season_year`).

### Rating residual (1 column)
`rating_residual = rating − mean(rating by league_tier × team_tier)`.

**Source:** cell 17. r = +0.112. Measures how much a player's rating exceeds what's expected given the strength of their specific league × team context.

### Tactical composites (4 columns) — proxies are intermediate only

**Final composites:** `ga_vs_league`, `progression_p90`, `involvement_p90`, `modern_forward_score`.

**Intermediate (not saved as columns):** `shot_quality_proxy`, `chance_creation_proxy`. Both computed from shrunk per-90 components and used only as fill values for `expectedGoals_p90` and `expectedAssists_p90` respectively. Verified empirically: once `expectedGoals_p90` is in the model, the proxy adds residual r ≈ +0.02 — redundant.

- `shot_quality_proxy = 0.12 × shotsFromInsideTheBox_p90_shrunk + 0.04 × shotsFromOutsideTheBox_p90_shrunk + 0.08 × shotsOnTarget_p90_shrunk` — weights from xG literature (inside-box shot ≈ 0.12 xG avg, outside-box ≈ 0.04, on-target bonus ≈ 0.08). Empirically aligned with real xG per 90 at the median.

- `chance_creation_proxy = 0.35 × bigChancesCreated_p90_shrunk + 0.02 × keyPasses_p90_shrunk` — weights empirically fitted to match real xA per 90 scale (initial weights of 0.25/0.10/0.05 produced values 5× too large; the final two-term formula correlates at r = 0.73 with real xA). The `accurateFinalThirdPasses` term was dropped after empirical fit gave it essentially zero weight.

- `ga_vs_league = (goals_p90_shrunk + assists_p90_shrunk) × (6 − league_tier)` — cell 16. r = +0.15. Rewards output in stronger leagues.

- `progression_p90 = accurateFinalThirdPasses_p90_shrunk + successfulDribbles_p90_shrunk + keyPasses_p90_shrunk` — cell 24. r = +0.12 solo, +0.05 residual. Captures ball-carrying and playmaking volume.

- `involvement_p90 = totalShots_p90_shrunk + keyPasses_p90_shrunk + successfulDribbles_p90_shrunk` — attacking volume aggregate.

- `modern_forward_score = goals_p90_shrunk + 0.7 × assists_p90_shrunk + 0.5 × bigChancesCreated_p90_shrunk + 0.3 × possessionWonAttThird_p90_shrunk + 0.2 × successfulDribbles_p90_shrunk − 0.3 × dispossessed_p90_shrunk` — cell 14. The composite with highest solo correlation (r = +0.232) among single-feature derivations.

### Quality × durability (1 column)
`rating_x_minutes = rating × minutesPlayed`.

**Source:** cell 19. r = +0.13. A "high-rating player who stayed on the field" interaction — durability-weighted quality.

### Team context (2 columns)
`team_mean_mv = mean(mv_start) grouped by (team id, _season_year)`, `log_team_mean_mv = log1p(team_mean_mv)`.

**Source:** cell 24. Solo r = +0.60, residual r = +0.155 — high value. Continuous alternative to the discrete `team_tier`. Groups by `team id` (still present in data) and `_season_year`.

### Interaction flags (3 columns)
`young_top_club`, `young_top_league`, `breakout_flag`.

**Source:** cell 22 of the EDA, where residual-correlation analysis identified the strongest incremental features in the entire project.

- `young_top_club = (age_in_season <= 21) & (team_tier <= 2)` — residual r = +0.221 (the highest in cell 22). Captures the "prospect premium" at big clubs.
- `young_top_league = (age_in_season <= 21) & (league_tier <= 2)` — residual r = +0.194.
- `breakout_flag = (raw_goals_per_90 > 0.4) & (age_in_season <= 22)` — residual r = +0.140. Uses RAW goals/90, not shrunk, because the 0.4 threshold was empirically calibrated on raw values.

Rejected from this group: `starter_x_league` (residual r = +0.071), `reliable_scorer` (residual r = +0.060). Both showed high solo r but minimal residual signal — i.e., redundant with `log_mv_start`.

### Market momentum (2 columns)
`log_mv_change_season`, `mv_surge_flag`.

**Source:** cell 25 of the EDA. These two features showed the strongest incremental signal of the entire project.

- `log_mv_change_season = log_mv_end − log_mv_start` — residual r = +0.481. The market's in-season re-evaluation of the player. This is legitimately scout-accessible information because by summer (when a scout would be making decisions), `mv_end` is already observable.
- `mv_surge_flag = (mv_end > mv_start × 1.25)` — residual r = +0.301. Binary version for sharp upticks.

Originally these features were computed with a league-aware "safe boundary date" to avoid rare forward-looking leakage. Per user decision, the boundary was dropped because the forward-looking rows are a small minority (6-7%) and because a scout in summer naturally has access to end-of-season valuations.

### Tournament flags (8 columns — added at the end)

`is_tournament`, `is_ucl`, `is_uel`, `is_uecl`, `is_euro`, `is_wc`, `is_libertadores`, `is_gold_cup`.

**Source:** late-stage addition after realizing tournament rows were indistinguishable from league rows after the tier merge. The `league_tier` column alone groups UCL, WC, Euros, Libertadores all at tier 1 — so the model cannot distinguish "played UCL" from "played for national team at WC."

**How they're reconstructed:** the original `_league` text column is reattached from `data/raw/database_ATT.csv` by positional join. Row alignment was verified (both files have 45,789 rows, all `tm_id` values matching at every position). Key-based joins would have been ambiguous because 4,488 (tm_id, season, team) triples have 2+ rows in the raw file (league + cup rows). Positional attach is unambiguous.

The attach is idempotent — if `_league` is already persisted in `att_with_tiers_for_eda.csv` from a prior run, the step is skipped. After flag derivation, `_league` is dropped from the output.

**Where the value shows up:** at the compression/vectorization stage, where a player's tournament exposure can be aggregated across their multiple rows in a season. Solo residual r of `is_ucl` on individual rows is only +0.073, but aggregated as "played_ucl_this_season" across a player's competitions will carry stronger signal.

## Features deliberately rejected during EDA

These were tested and found to have near-zero residual correlation. They are NOT in the pipeline and should not be reintroduced without new evidence.

- `defensive_workrate = (tackles + interceptions + ballRecovery) / touches` — cell 19, r = -0.008.
- `team_goal_share = goals / team_total_goals` — cell 17, r = +0.03. Too noisy.
- `scoring_momentum = goals_p90 − goals_p90_prev` (naive delta) — cell 18, r = +0.009. Failed.
- `delta_rating_vs_mean`, `delta_goals_p90_vs_mean` (momentum vs personal history) — cell 27, residual r ≈ +0.05. Too weak to include.
- `versatility_ratio` (weak-foot/head goal share) — cell 8, near-zero. All three buckets had identical boxplots.
- `starter_x_league`, `reliable_scorer` — cell 22, residual r < 0.07.
- `shotsOnTarget_tier_z` — redundant with `goals_tier_z`.
- Historical aggregates of `goals_p90`, `rating`, `minutes` (mean/max/std for every stat) — cell 26. Per-stat historical aggregates showed near-zero residual correlation because `log_mv_start` already encodes the player's accumulated trajectory. Only `hist_rating_std` (consistency) survived with residual r = +0.06. History features reserved for the vectorization stage.
- `xg_missing`, `xa_missing`, `ballRecovery_missing` flags — were created, then removed. Correlation with target after controlling for `league_tier` drops to -0.014. Fully redundant with league-tier information.

## Final output file

- Path: `data/processed/att_features/att_features.parquet` and `.csv` (identical content)
- Shape: 32,524 rows × 154 columns
- Dropped: 38 source columns + `player_positions` (split)
- Kept as-is: 78 columns (8 IDs + 6 metadata + 12 percentages + 2 tiers + 50 raw stats + mv_start/mv_end)
- Transformed: 34 columns (3 logs + 2 position splits + 2 xG/xA per-90 + 27 shrunk per-90)
- New: 27 engineered columns (2 open-play + 6 exposure/ratios + 1 age + 5 z-scores + 1 rating_residual + 4 tactical composites + 1 rating_x_minutes + 2 team context + 3 interaction flags + 2 market momentum) + 8 tournament flags

All binary flags are strictly 0/1. All Bayesian-shrunk columns are finite and winsorized. Critical columns (target, baseline, tiers, positions) are null-free. The file is verified ready for the vectorization stage.

## Side effect on the source file

`att_with_tiers_for_eda.csv` is updated in place (once, idempotently) to include the recovered `_league` column. This makes the source file consistent with what the pipeline uses internally and allows downstream steps to access league identity without re-merging from raw.

## Reproducibility

The entire pipeline runs in a single script: `preprocess.py`. Inputs: `data/processed/att_with_tiers_for_eda.csv` and `data/raw/database_ATT.csv`. Output: `data/processed/att_features/att_features.{parquet,csv}`. Run: `python preprocess.py`. Idempotent — repeated runs produce identical output.
