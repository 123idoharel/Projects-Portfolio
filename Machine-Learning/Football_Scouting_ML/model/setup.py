"""
setup.py — Common utilities for the modeling pipeline.

Path resolution strategy:
  All paths are anchored to the PROJECT ROOT (the parent of the `model/`
  directory containing this file).

KEY DESIGN CHOICES:

(1) Drop redundant raw-EUR columns
    `mv_start`, `mv_end`, `team_mean_mv` carry the same information as their
    log counterparts but on a heavily skewed scale. Dropped at runtime so
    the model only sees the well-behaved log versions.

(2) Drop ballRecovery (raw AND shrunk)
    Raw `ballRecovery` is 72% null uniformly. The Bayesian-shrunk version
    looked clean (0% null) because shrinkage filled missing values with
    a prior — but this means for those 72% of rows, the "shrunk" value
    is essentially constant. Empirically the model learns to use this
    column as a data-coverage proxy ("did Sofascore track this game?")
    rather than a football skill signal. Dropping both versions.

(3) Reformulate target as a log-ratio
    y_ratio = log_target - log_mv_end
    This represents "how much will the player gain or lose vs current value."
    Forces the model to learn trajectory patterns instead of memorizing prices.

(4) Filter invalid target rows
    A small number of rows (typically 2) have NaN/Inf in the ratio target
    due to edge cases in the source data. Dropped at runtime.
"""
import pandas as pd
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — anchored to project root, not cwd
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR        = PROJECT_ROOT / "data" / "processed" / "att_vectors"
INFERENCE_DIR   = PROJECT_ROOT / "data" / "processed" / "att_inference_vectors"
PREDICTIONS_DIR = PROJECT_ROOT / "data" / "processed" / "att_predictions"
MODEL_DIR       = PROJECT_ROOT / "models"
RESULT_DIR      = PROJECT_ROOT / "results"

MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)
PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
INFERENCE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Columns to drop at runtime
# ---------------------------------------------------------------------------
# Redundant raw-EUR columns (their log counterparts are kept)
RAW_EUR_TO_DROP = ['mv_start', 'mv_end', 'team_mean_mv']

# ballRecovery is 72% null in source. Both the raw and shrunk versions are
# corrupted: raw is missing for most rows, and shrunk is essentially constant
# (= prior) for those rows. The model uses it as a data-coverage signal,
# not a real football pattern. Both are dropped.
DATA_QUALITY_DROPS = ['ballRecovery', 'ballRecovery_p90_shrunk']


# ---------------------------------------------------------------------------
# Data loading and splitting
# ---------------------------------------------------------------------------
def load_vectors():
    """Load the master player-cutoff vectors file (training vectors)."""
    path = DATA_DIR / "att_vectors.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Training vectors not found at {path}\n"
            f"Make sure att_vectors.parquet exists in {DATA_DIR}"
        )
    return pd.read_parquet(path)


def split_features_target(vectors):
    """
    Split vectors into modeling components, transforming target to a ratio.

    Returns:
        X        — feature matrix
        y_ratio  — log-ratio target (log_target - log_mv_end)
        groups   — tm_id series (for GroupKFold splitting only)

    Drops:
        - Structural cols: tm_id, cutoff_year, log_target
        - Redundant raw-EUR cols: mv_start, mv_end, team_mean_mv
        - Data-quality drops: ballRecovery (raw + shrunk)
        - Invalid target rows: NaN/Inf in y_ratio
    """
    if 'log_mv_end' not in vectors.columns:
        raise KeyError("log_mv_end not found in vectors — cannot construct ratio target")

    # 1. Compute ratio target
    y_orig  = vectors['log_target']
    y_ratio = y_orig - vectors['log_mv_end']

    # 2. Filter invalid target rows
    valid_mask = y_ratio.notna() & (~np.isinf(y_ratio))
    n_dropped = (~valid_mask).sum()
    if n_dropped > 0:
        print(f"[setup] CLEANUP: Dropped {n_dropped} rows with invalid target (NaN/Inf).")

    y_ratio = y_ratio[valid_mask]
    groups  = vectors.loc[valid_mask, 'tm_id']

    # 3. Build feature matrix
    drop_cols = ['tm_id', 'cutoff_year', 'log_target']
    drop_cols += [c for c in RAW_EUR_TO_DROP if c in vectors.columns]
    drop_cols += [c for c in DATA_QUALITY_DROPS if c in vectors.columns]

    X = vectors.loc[valid_mask].drop(columns=drop_cols)

    # 4. Categorical handling
    for col in ['primary_position', 'secondary_position']:
        if col in X.columns:
            X[col] = X[col].astype('category')

    dropped_raw  = [c for c in RAW_EUR_TO_DROP if c in vectors.columns]
    dropped_qual = [c for c in DATA_QUALITY_DROPS if c in vectors.columns]
    print(f"[setup] Dropped redundant raw-EUR cols: {dropped_raw}")
    print(f"[setup] Dropped data-quality cols (high null / corrupted shrink): {dropped_qual}")
    print(f"[setup] Target reformulated to log-ratio (log_target - log_mv_end)")
    print(f"[setup]   y_ratio mean: {y_ratio.mean():+.3f}, std: {y_ratio.std():.3f}")
    print(f"[setup]   y_ratio = 0   means no expected change")
    print(f"[setup]   y_ratio > 0   means expected gain (breakout)")
    print(f"[setup]   y_ratio < 0   means expected loss (decline)")
    print(f"[setup] Feature matrix shape: {X.shape}")

    return X, y_ratio, groups


def compose_prediction(predicted_ratio, log_mv_end_values):
    """
    Convert a model's predicted log-ratio back to absolute EUR.

    Args:
        predicted_ratio   : array — model output
        log_mv_end_values : array — log_mv_end values for those same rows

    Returns:
        absolute_eur : predicted future_max_value in EUR
    """
    predicted_log_target = log_mv_end_values + predicted_ratio
    return np.expm1(predicted_log_target)


# ---------------------------------------------------------------------------
# Loss functions
# ---------------------------------------------------------------------------
def pinball_loss(y_true, y_pred, quantile):
    """Pinball loss for quantile regression."""
    err = y_true - y_pred
    return np.where(err >= 0, quantile * err, (quantile - 1) * err).mean()


# ---------------------------------------------------------------------------
# Sanity check helper
# ---------------------------------------------------------------------------
def print_paths():
    """Print all configured paths and whether they exist."""
    print(f"PROJECT_ROOT:    {PROJECT_ROOT}  exists={PROJECT_ROOT.exists()}")
    print(f"DATA_DIR:        {DATA_DIR}  exists={DATA_DIR.exists()}")
    print(f"  └─ att_vectors.parquet exists: {(DATA_DIR / 'att_vectors.parquet').exists()}")
    print(f"INFERENCE_DIR:   {INFERENCE_DIR}  exists={INFERENCE_DIR.exists()}")
    print(f"PREDICTIONS_DIR: {PREDICTIONS_DIR}  exists={PREDICTIONS_DIR.exists()}")
    print(f"MODEL_DIR:       {MODEL_DIR}  exists={MODEL_DIR.exists()}")
    print(f"RESULT_DIR:      {RESULT_DIR}  exists={RESULT_DIR.exists()}")


if __name__ == '__main__':
    print_paths()