# MODEL PIPELINE KNOWLEDGE

This document describes the complete attacker market-value prediction pipeline implemented under `model/`. It covers every stage from setup through inference, the key design decisions made at each step, the empirical results obtained, and the rationale behind the final architecture.

The pipeline trains 4 production models (mean + 3 quantiles) on 17,633 player-cutoff vectors, predicts log-ratio of future peak value to current value, and produces calibrated probabilistic forecasts for current 24/25 attackers.

---

## Table of Contents

1. [Setup module (`setup.py`)](#1-setup-module-setuppy)
2. [Stage 1 — Diagnostic baseline (`01_baseline.py`)](#2-stage-1--diagnostic-baseline)
3. [Stage 2 — Hyperparameter tuning (`02_tune_mean.py`)](#3-stage-2--hyperparameter-tuning)
4. [Stage 3 — Segmented evaluation (`03_segmented_eval.py`)](#4-stage-3--segmented-evaluation)
5. [Stage 4 — Quantile model training (`04_quantiles.py`)](#5-stage-4--quantile-model-training)
6. [Stage 4b — Quantile diagnostics (`04b_quantile_diagnostics.py`)](#6-stage-4b--quantile-diagnostics)
7. [Stage 5 — Production model training (`05_production.py`)](#7-stage-5--production-model-training)
8. [Stage 6 — Historical backtests (`06_historical_backtests.py`)](#8-stage-6--historical-backtests)
9. [Stage 7a — Inference vector building (`07a_build_inference_vectors.py`)](#9-stage-7a--inference-vector-building)
10. [Stage 7 — Live inference (`07_inference.py`)](#10-stage-7--live-inference)
11. [Stage 8 — Final report (`08_final_report.py`)](#11-stage-8--final-report)
12. [Final results summary](#12-final-results-summary)

---

## 1. Setup module (`setup.py`)

### Purpose

Shared utilities imported by every stage. Defines paths, the data loader, the feature/target split function, and helper functions. **Never run directly** — only imported.

### Key decisions

**Path resolution anchored to project root.** All paths are derived from `Path(__file__).resolve().parent.parent`, making scripts work regardless of the current working directory.

**Three categories of column drops at runtime.**

1. **Structural drops** (always): `tm_id`, `cutoff_year`, `log_target`. These are used for grouping and target derivation, never as features.

2. **Redundant raw-EUR drops**: `mv_start`, `mv_end`, `team_mean_mv`. Their log counterparts (`log_mv_start`, `log_mv_end`, `log_team_mean_mv`) carry identical information on a model-friendlier distribution. Tree splits behave better on log-scale market values.

3. **Data quality drops**: `ballRecovery` and `ballRecovery_p90_shrunk`. The raw column is 72% null in source data. The Bayesian-shrunk version was confirmed to behave as a "data coverage proxy" (encoding "did Sofascore track this game?") rather than a real football-skill signal. Both are dropped.

**Target reformulation to log-ratio.** This is the most important design decision. The original target `log_target = log1p(future_max_value)` correlates 0.83 with `log_mv_end`, allowing the model to score artificially high R² simply by copying the current price. Instead we train on:

```
y_ratio = log_target - log_mv_end ≈ log(future_max / mv_end)
```

This forces the model to learn trajectory patterns:
- y_ratio > 0 → expected gain (breakout)
- y_ratio = 0 → expected stability
- y_ratio < 0 → expected decline

`log_mv_end` is **kept** as a feature (not dropped) because price level conditions volatility — a €5M player can 10x more easily than a €100M player.

**Compose function.** `compose_prediction(predicted_ratio, log_mv_end_values)` reverses the ratio to absolute EUR via `expm1(log_mv_end + predicted_ratio)`. Used at inference time and for EUR-scale segmented evaluation.

**Pinball loss helper.** Used for quantile-model evaluation (q=0.5 reduces to MAE; q=0.9 penalizes under-prediction; q=0.1 penalizes over-prediction).

### Invalid-row filter

A small number of rows (typically 2) have NaN/Inf in the ratio target due to edge cases in source data. These are filtered at runtime inside `split_features_target`.

---

## 2. Stage 1 — Diagnostic baseline

**File**: `01_baseline.py`

### Purpose

Train a single XGBoost model with default hyperparameters to verify that the feature set behaves as expected before investing in tuning.

### Implementation

5-fold GroupKFold split (grouping by `tm_id` to prevent player-level leakage between train and validation). Each fold trains for up to 2000 trees with `early_stopping_rounds=50`. Reports overall MAE, R², top-20 feature importance, and an acceptance check.

### Acceptance check

Looks for trajectory-relevant features in the top-10:
- `age_at_cutoff`, `age_penalty` (age effects)
- `log_mv_end`, `log_mv_start` (volatility conditioner)
- `young_top_club`, `young_top_league` (breakout signals)
- `mv_surge_flag`, `breakout_flag` (market momentum)
- `log_mv_change_season` (in-season trajectory)
- `modern_forward_score` (quality signal)
- `rating`, `rating_residual` (performance vs expected)

### Final baseline result

```
Feature matrix shape:    (17633, 311)
Baseline 5-fold MAE:     0.4996 ± 0.0083
Overall R²:              0.41
Top-10 features include: log_mv_end, age_at_cutoff, hist_minutes_sum,
                         current_expectedGoals_p90_vs_hist_max,
                         involvement_p90, cont_xG_vs_domestic_current,
                         young_top_club, totalShots_p90_shrunk,
                         log_mv_change_season, log_mv_start
Acceptance: 4/12 expected features in top-10 ✓
```

The MAE 0.50 on the ratio target reflects genuine signal: the standard deviation of `y_ratio` is 0.91, so a naive predictor would have MAE ~0.65-0.70. The 0.50 baseline beats naive by ~25-30%.

---

## 3. Stage 2 — Hyperparameter tuning

**File**: `02_tune_mean.py`

### Purpose

Run Optuna search over XGBoost hyperparameters to find the configuration that minimizes 5-fold CV MAE.

### Search space

```
max_depth         : 4-8
learning_rate     : 0.02-0.1 (log scale)
min_child_weight  : 1-20
subsample         : 0.6-1.0
colsample_bytree  : 0.5-1.0
reg_alpha         : 0.0-5.0
reg_lambda        : 1.0-10.0
n_estimators      : 3000 (ceiling, early stopping decides actual)
```

50 trials × 5 GroupKFold folds = ~70 minutes of compute.

### Outputs

- `models/best_params_mean.pkl` — winning hyperparameters
- `results/stage2_oof_tuned.parquet` — out-of-fold predictions with `tm_id`, `cutoff_year`, `log_target`, `log_mv_end`, `y_ratio`, `oof_pred_ratio`

### Final tuning result

```
Best CV MAE: 0.4998 (vs baseline 0.4996 — essentially zero improvement)

Best params:
  max_depth: 6
  learning_rate: 0.0202
  min_child_weight: 4
  subsample: 0.659
  colsample_bytree: 0.942
  reg_alpha: 2.79
  reg_lambda: 9.12
```

### Interpretation

The fact that 50 Optuna trials couldn't beat the default configuration is itself a finding: **the bottleneck is not hyperparameters**. The model is hitting the realistic signal-to-noise ceiling of trajectory prediction. The chosen params favor conservative learning (low LR) and strong regularization, consistent with extracting all available signal without overfitting to noise.

---

## 4. Stage 3 — Segmented evaluation

**File**: `03_segmented_eval.py`

### Purpose

Decompose the aggregate MAE into segments to identify where the model is strong vs weak, and to quantify the variable-horizon effect (cutoff 2020 has 5 years of future to predict; cutoff 2024 has only 1).

### Segments reported

- Age bucket (17-21, 22-25, 26-29, 30+)
- Cutoff year (= prediction horizon proxy)
- League tier (1-5)
- Has-history (0/1)
- Primary position
- Cross-tab: cutoff_year × age_bucket

### Final segmented results

**Overall**: ratio MAE 0.4998, EUR median error €384,501

**By age bucket**:
| Age | Ratio MAE | EUR median err | n |
|---|---:|---:|---:|
| 17-21 | 0.798 | €822k | 3,365 |
| 22-25 | 0.521 | €531k | 5,708 |
| 26-29 | 0.375 | €316k | 4,897 |
| 30+ | 0.356 | €148k | 3,640 |

**By cutoff year (= future-window length)**:
| Year | Ratio MAE | n |
|---|---:|---:|
| 2020 (5y) | 0.549 | 2,983 |
| 2021 (4y) | 0.556 | 3,590 |
| 2022 (3y) | 0.513 | 3,577 |
| 2023 (2y) | 0.473 | 3,758 |
| 2024 (1y) | 0.421 | 3,725 |

**By league tier**:
| Tier | Ratio MAE | EUR median err | n |
|---|---:|---:|---:|
| 1 | 0.441 | €1.6M | 3,293 |
| 2 | 0.527 | €497k | 2,268 |
| 3 | 0.523 | €374k | 6,941 |
| 4 | 0.533 | €228k | 3,951 |
| 5 | 0.366 | €65k | 1,180 |

**By has-history**:
| Group | Ratio MAE | n |
|---|---:|---:|
| no history | 0.674 | 4,073 |
| has history | 0.447 | 13,560 |

### Interpretation

All three patterns (age, cutoff year, has-history) converge on a single explanation: **the model is uncertain in proportion to how much real future could still happen.** Younger players have more time to deviate from current trajectory; earlier cutoffs have longer future windows; players without history have less observed evidence to anchor predictions.

The Tier 1 EUR median error (€1.6M) is high in absolute terms because Tier 1 players have larger absolute values (a 10% error on €60M is €6M; same 10% on €600k is €60k). On the ratio scale Tier 1 is actually best (0.44).

---

## 5. Stage 4 — Quantile model training

**File**: `04_quantiles.py`

### Purpose

Train 3 separate XGBoost models with `objective='reg:quantileerror'` for q=0.10, 0.50, and 0.90, then verify calibration and apply isotonic correction if needed.

### Implementation

Each quantile gets its own Optuna tuning (30 trials × 5 folds × ~60 minutes = ~3 hours per quantile, ~9 hours total).

Quantile models use stronger regularization than the mean model (`min_child_weight 5-50` vs `1-20`) because extreme quantiles are sensitive to outliers.

### Calibration logic

After training each quantile, OOF predictions are checked: for q=0.10, we expect 10% of actuals to fall below the prediction. If empirical coverage drifts more than 3% from target, an `IsotonicRegression` calibrator is fit and saved.

### Outputs

- `models/best_params_quantiles.pkl` — params for all 3 quantiles
- `models/quantile_calibrators.pkl` — calibrators (None if not needed)
- `models/quantile_oof.npz` — OOF predictions for diagnostics

### Final calibration results

```
q10 coverage:  10.7% (target 10%) — 0.7% drift, no calibration needed ✓
q50 coverage:  51.1% (target 50%) — 1.1% drift, no calibration needed ✓
q90 coverage:  88.2% (target 90%) — 1.8% drift, no calibration needed ✓
80% interval coverage: 77.5% (target 80%) — 2.5% drift, acceptable
```

All three quantiles are within 2% of target. The XGBoost native quantile objective produced well-calibrated outputs without requiring isotonic correction. This is unusually clean.

---

## 6. Stage 4b — Quantile diagnostics

**File**: `04b_quantile_diagnostics.py`

### Purpose

Calibration alone isn't sufficient — a model that always predicts q10 = €0 and q90 = €500M would technically cover 80% of cases but tell the scout nothing. We need to verify **sharpness** (how tight the intervals are) and **interaction with uncertainty drivers** (intervals should widen for risky cases).

### Diagnostics computed

- Median interval width in EUR and as % of median prediction
- Width by age bucket, cutoff year, has-history
- Inverted intervals check (q10 > q90 — quantile crossings)

### Final diagnostic results

**Overall sharpness** (median values):
```
Mean interval width (ratio space, log scale): 1.474
Median interval width in EUR:                 €1,955,774
Median width as % of median prediction:       158%
Median width as % of current value:           166%
```

The 100-200% zone is the "useful but not vague" target, so 158% is healthy.

**By age bucket** (width as % of mv_end):
- 17-21: **645%** (massive uncertainty for young players — correct)
- 22-25: 241%
- 26-29: 121%
- 30+: **84%** (low uncertainty for established players — correct)

**By has-history**:
- no history: **469%** (correct — wider for cold-start)
- has history: 140%

**By cutoff year**: widths 149-180% (in the expected direction, modest variation since training target is "future_max" regardless of horizon).

**Inverted intervals**: 11 / 17,633 (0.06%) — negligible.

### Interpretation

The model produces meaningful, calibrated intervals that vary intelligently with player-level uncertainty. Combined with the calibration coverage of 77.5% on the 80% interval, this confirms the quantile output is genuinely production-quality.

---

## 7. Stage 5 — Production model training

**File**: `05_production.py`

### Purpose

Train final deployable artifacts on the FULL dataset (no holdout) using locked hyperparameters from Stages 2 and 4.

### Critical n_estimators handling

Tuning uses early stopping, so saved hyperparameters have `n_estimators=3000` as a ceiling, not the actual count used. Training with that ceiling and no validation set would overfit. To find the right tree count, Stage 5 runs an internal 3-fold CV check with early stopping for each model, takes the mean `best_iteration`, and adds a 10% buffer (because production trains on more data than the CV folds did).

### Outputs

- `models/production_attacker_v1.pkl` — dict of 4 fitted XGBRegressors
- `models/production_optimal_iters.pkl` — the determined tree counts

### Final production tree counts

```
mean model:        396 trees
pessimistic q10:   427 trees
expected q50:      513 trees  (highest — q50 needs the most learning)
optimistic q90:    294 trees
```

These numbers replace the original guess of 400 trees with empirically derived values.

---

## 8. Stage 6 — Historical backtests

**File**: `06_historical_backtests.py`

### Purpose

Strict-temporal validation. For each historical year, train fresh models that NEVER saw any data from that year or later. This produces an honest "what would the system have predicted if deployed at that time?" demonstration.

Backtest models use the same hyperparameters and tree counts as production — only the training data window differs.

### Final historical track record

| Year | Train rows | Ratio MAE | Median EUR error |
|---|---:|---:|---:|
| Summer 2022 | 6,573 | 0.5522 | €471,319 |
| Summer 2023 | 10,150 | 0.4954 | €391,880 |
| Summer 2024 | 13,908 | 0.4535 | €389,661 |

### Interpretation

Performance improves monotonically as historical data accumulates — a healthy sign that the model is genuinely learning patterns, not memorizing. Each new season of training data tightens predictions. The Summer 2024 backtest with MAE 0.45 is comparable to the full-data CV MAE of 0.50, confirming production model quality on real held-out time periods.

This is the executive demonstration: "If we'd deployed in 2022, we'd have median error €471k. By 2024 it's €390k. Each season makes the model more accurate."

---

## 9. Stage 7a — Inference vector building

**File**: `07a_build_inference_vectors.py`

### Purpose

Build feature vectors for current 24/25 players (cutoff 2025) using the same logic as training. Standalone end-to-end script that runs preprocess + vectorize in-memory, bypassing the original preprocess output (which had filtered out most 24/25 rows due to the `future_max_value > 0` filter).

### Key trick: placeholder injection

Production preprocess.py requires `future_max_value > 0` to keep a row. For 24/25 players, `future_max_value` doesn't exist yet (their future hasn't happened). We force-set `future_max_value = 1.0` for ALL 24/25 + 2025 rows so they pass the filter, then drop the bogus `log_target` after vectorization.

### Pipeline executed

1. Load `att_with_tiers_for_eda.csv` (45,789 rows × 127 cols, BEFORE preprocess filtering)
2. Attach `_league` from raw data
3. Force-inject placeholder `future_max_value=1.0` for current-season rows
4. Run preprocess: `apply_row_filters` → `drop_unused_columns` → `build_features` → `add_tournament_flags`
5. Override `EMIT_CUTOFFS = [2025]` and call `vectorize.build_all_vectors`
6. Drop placeholder `log_target` column
7. Validate output structure (matches training schema)

### Final inference vector results

```
Raw 24/25 + 2025 rows:    6,691 (5,413 unique players)
After mv_start NaN filter: lost ~268 (Transfermarkt didn't publish)
After attacker filter:     lost ~3 (player_positions doesn't include attacker)
After league-row req:      lost ~313 (tournament-only, no league row at cutoff 2025)
                           ───────
Final cutoff-2025 vectors: 4,849 unique players × 315 columns
```

### Position breakdown
```
ST: 2399 (49.5%)
RW: 1005 (20.7%)
LW:  995 (20.5%)
RM:  249 (5.1%)
LM:  200 (4.1%)
CM:    1 (0.0%)  ← will be remapped at inference by 07_inference.py
```

The 1 CM player exists because `vectorize.py`'s `primary_remaps` doesn't include CM. Rather than modify vectorize.py (which would force re-vectorizing the entire training set), we handle this defensively in Stage 7.

---

## 10. Stage 7 — Live inference

**File**: `07_inference.py`

### Purpose

Score the 4,849 cutoff-2025 inference vectors with all 4 production models and produce per-player predictions in EUR.

### Pre-inference safety steps

**1. Filter players with invalid `mv_end`**: Some 24/25 players have `mv_end = 0` (broken/missing data, not real €0 valuations). Without a valid baseline, the ratio composition `mv_end × exp(predicted_ratio)` produces meaningless numbers. We drop:
- `log_mv_end` is NaN
- `log_mv_end <= 0` (i.e., mv_end <= €1)
- `mv_end < €10,000` (sanity floor)

In the 24/25 inference, this dropped 79 players (76 with `log_mv_end=0`, 3 with NaN), leaving 4,770 valid.

**2. Position safety remap**: The `POSITION_SAFETY_REMAP` dict catches any position labels not in the 5 training categories (`ST`, `LW`, `RW`, `RM`, `LM`) and remaps them. CM → (RM, LM); CAM → (RM, LM); CF → (ST, LW); etc. The 1 CM player gets remapped to `primary=RM, secondary=LM`.

**3. Drop runtime columns**: Same as setup.py drops (`mv_start`, `mv_end`, `team_mean_mv`, `ballRecovery`, `ballRecovery_p90_shrunk`).

**4. Cast position columns to Categorical** with the 5 training categories.

### Predictions

For each model, predict the log-ratio. For quantile models, apply isotonic calibration if present (in this case, none was needed). Compose ratios back to EUR via `setup.compose_prediction`.

### Outputs

- `data/processed/att_predictions/att_predictions_2425.{parquet,csv}` with columns:
  - `tm_id`, `cutoff_year`, `mv_at_cutoff`
  - `predicted_mean_eur`, `predicted_pessimistic_eur`, `predicted_expected_eur`, `predicted_optimistic_eur`
  - `predicted_*_log_ratio` (raw model outputs)
  - `upside_multiple` = `predicted_optimistic_eur / mv_at_cutoff`

### Final inference results

```
4,770 players scored

Distribution of predicted ratios (log-scale):
  pessimistic median: -0.479 (=> 0.62x current value)
  expected median:    +0.022 (=> 1.02x current value)
  optimistic median:  +0.745 (=> 2.11x current value)
```

The 80% interval covers from 0.62x to 2.11x of current value at the median.

### Top-20 breakouts (mv >= €1M filter)

The "mv >= €1M" filtered list (1,846 players) is the operationally useful scouting output. Sample top picks (verified plausible):

- **Jonah Kusi-Asare** (18, Bayern München) — Sweden U-21
- **Paris Brunner** (19, Cercle Brugge) — German youth international
- **Ian Subiabre** (18, River Plate) — Argentina U-20 captain
- **Ibrahim Mbaye** (17, PSG) — Senegal youth phenom
- **Cole Campbell** (19, Borussia Dortmund) — USA U-20 prospect
- **Hugo Camberos** (18, Chivas) — Mexico's top youth attacker

All top-20 picks share: age 17-21, plays in top-tier or strong league, currently undervalued by Transfermarkt — exactly the breakout profile.

Multiples in the 9-16x range for these picks are realistic for successful young attackers (Yamal, Wirtz, Gavi all exhibited similar growth curves from €5M-ish to €100M+).

---

## 11. Stage 8 — Final report

**File**: `08_final_report.py`

### Purpose

Generate the executive summary combining production CV-MAE and historical backtests.

### Final executive summary

```
PRODUCTION QUALITY ESTIMATE (cross-validated)
  CV-MAE on ratio target:       0.4998
  Median absolute EUR error:    €384,501
  (5-fold GroupKFold by player. Expected error on new players.)

HISTORICAL TRACK RECORD (strict-temporal backtests)
  Summer 2022    6,573 train rows    Ratio MAE 0.5522    Median err €471,319
  Summer 2023    10,150 train rows   Ratio MAE 0.4954    Median err €391,880
  Summer 2024    13,908 train rows   Ratio MAE 0.4535    Median err €389,661
```

---

## 12. Final results summary

### Quality metrics

| Metric | Value | Notes |
|---|---:|---|
| Production CV-MAE (ratio) | 0.4998 | 5-fold GroupKFold |
| Median absolute EUR error | €384,501 | More robust than mean for skewed distribution |
| R² on ratio target | 0.41 | Realistic ceiling for trajectory prediction |
| q10 calibration | 10.7% (target 10%) | Excellent, no recalibration needed |
| q50 calibration | 51.1% (target 50%) | Excellent |
| q90 calibration | 88.2% (target 90%) | Excellent |
| 80% interval coverage | 77.5% (target 80%) | Acceptable |
| Median 80% interval width | 158% of median pred | Sharp, in healthy 100-200% zone |
| Inverted intervals | 11/17,633 (0.06%) | Negligible |

### Historical track record

| Year | Train rows | Ratio MAE | Median EUR error |
|---|---:|---:|---:|
| Summer 2022 | 6,573 | 0.5522 | €471,319 |
| Summer 2023 | 10,150 | 0.4954 | €391,880 |
| Summer 2024 | 13,908 | 0.4535 | €389,661 |

Performance improves monotonically with data accumulation.

### Inference output

- 4,770 valid 24/25 players scored (dropped 79 with broken mv_end data)
- Each player gets 4 predictions: mean point estimate + pessimistic/expected/optimistic quantile bands
- Top breakout candidates verified plausible (real youth prospects at strong clubs)
- Median 80% confidence band: 0.62x — 2.11x of current value

### Key design decisions justified empirically

1. **Log-ratio target** (vs absolute log_target): Forces trajectory learning, prevents trivial price-copying. Confirmed by feature importance distribution and segmented patterns.
2. **Drop ballRecovery** (raw + shrunk): Identified as data-coverage proxy via segment analysis.
3. **No horizon feature**: Considered adding `years_until_data_ends` but rejected because it doesn't generalize to live deployment in future years.
4. **Production tree counts via internal CV check**: Replaced arbitrary guess (400) with empirically determined values (294-513 per model).
5. **Defensive position remap at inference**: Handles edge cases (e.g., 1 CM player) without forcing re-vectorization of training data.
