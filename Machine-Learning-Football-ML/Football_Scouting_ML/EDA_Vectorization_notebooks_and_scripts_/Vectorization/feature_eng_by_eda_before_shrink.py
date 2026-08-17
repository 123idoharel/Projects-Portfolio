"""
preprocess.py — Complete preprocessing + feature engineering

Input:  data/raw/att_with_tiers_for_eda.csv   (126 columns, tiers pre-merged)
Output: data/processed/att_features.parquet   (~146 columns, modeling-ready)

Pipeline:
  1. Row filters (future_max NaN / zero, mv_start NaN, attacker filter)
  2. Drop 38 columns (GK, defender-specific, redundant, birth_year)
  3. Log transforms on target and market values
  4. Position split into primary / secondary (text)
  5. Bayesian-shrunk per-90 features (27 columns, raw kept alongside)
  6. xG / xA per-90 conversion + proxy fill + drop raw
  7. Derived ratios, exposure, age penalty, open-play goals
  8. Z-scores (grouped by league_tier × season) + rating residual
  9. Tactical composites (4 columns)
 10. Team context (mean mv + log)
 11. Interaction flags + market momentum
 12. Quality × durability
 13. Validation checks
"""

import numpy as np
import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
INPUT_PATH = Path("../../data/processed/att_with_tiers_for_eda.csv")
RAW_PATH   = Path("../../data/raw/database_ATT.csv")   # for recovering _league column
OUTPUT_DIR = Path("../../data/processed/att_features_before_shrink")
OUTPUT_NAME = "att_features_before_shrink"   # basename for both .parquet and .csv outputs


# Tournament competitions and their short flag names (added at end of pipeline)
TOURNAMENT_FLAGS = {
    'UEFA Champions League':      'is_ucl',
    'UEFA Europa League':         'is_uel',
    'UEFA Conference League':     'is_uecl',
    'UEFA European Championship': 'is_euro',
    'FIFA World Cup':             'is_wc',
    'CONMEBOL Copa Libertadores': 'is_libertadores',
    'CONCACAF Gold Cup':          'is_gold_cup',
}


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
ATTACKER_ROLES = {'ST', 'CF', 'RW', 'LW', 'RM', 'LM', 'CAM', 'AM'}

# 38 columns dropped unconditionally at the start
DROP_COLUMNS = [
    # Goalkeeper stats (19)
    'saves', 'savesCaught', 'savesParried',
    'savedShotsFromInsideTheBox', 'savedShotsFromOutsideTheBox',
    'punches', 'highClaims', 'runsOut', 'successfulRunsOut',
    'crossesNotClaimed', 'penaltySave', 'penaltyFaced', 'goalKicks',
    'goalsPrevented', 'outfielderBlocks', 'cleanSheet',
    'goalsConceded', 'goalsConcededInsideTheBox', 'goalsConcededOutsideTheBox',
    # Defender-specific (5)
    'blockedShots', 'clearances', 'dribbledPast',
    'penaltyConceded', 'ownGoals',
    # Redundant with percentages / other columns (13)
    'aerialLost', 'duelLost', 'inaccuratePasses', 'shotsOffTarget',
    'tacklesWon', 'totalCross', 'totalLongBalls', 'totalPasses',
    'totalChippedPasses', 'totalOwnHalfPasses', 'totalOppositionHalfPasses',
    'countRating', 'totalRating',
    # Replaced by engineered equivalents (1; player_positions dropped later after split)
    'birth_year',
]

# 27 columns that get Bayesian-shrunk per-90 partners (raw versions kept)
P90_SHRUNK_COLUMNS = [
    'goals', 'assists', 'shotsOnTarget', 'bigChancesCreated', 'keyPasses',
    'successfulDribbles', 'totalContest', 'possessionWonAttThird',
    'ballRecovery', 'touches', 'wasFouled', 'dispossessed',
    'passToAssist', 'shotFromSetPiece', 'accurateFinalThirdPasses',
    'accurateCrosses', 'accurateChippedPasses', 'accurateLongBalls',
    'accurateOppositionHalfPasses', 'tackles', 'interceptions',
    'fouls', 'offsides', 'totalShots', 'totalAttemptAssist',
    'shotsFromInsideTheBox', 'shotsFromOutsideTheBox',
]

BAYESIAN_PRIOR_90S    = 10.0     # 900 minutes of phantom play — for noisy rate stats
XG_XA_PRIOR_90S       = 5.0      # lighter prior — xG/xA are already smoothed statistics
WINSOR_QUANTILE       = 0.99     # upper-tail clip


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def has_attacking_role(positions_str) -> bool:
    """True if the player's position list contains at least one attacking role."""
    if pd.isna(positions_str):
        return False
    roles = {r.strip() for r in str(positions_str).split(',')}
    return bool(roles & ATTACKER_ROLES)


def bayesian_shrunk_p90(df: pd.DataFrame, col: str,
                       prior_90s: float = BAYESIAN_PRIOR_90S,
                       winsor_q: float = WINSOR_QUANTILE) -> pd.Series:
    """
    Empirical-Bayes shrunk per-90 rate:
        x_p90_shrunk = (x + prior_x) / (n90 + prior_90s)
    where prior_x = prior_90s * global_rate(x).
    Upper-tail winsorized at the given quantile.
    """
    minutes = df['minutesPlayed'].fillna(0)
    n90     = minutes / 90.0
    values  = df[col].fillna(0)

    total_90s = n90.sum()
    global_rate = values.sum() / total_90s if total_90s > 0 else 0.0
    prior_val   = prior_90s * global_rate

    shrunk = (values + prior_val) / (n90 + prior_90s)
    return shrunk.clip(upper=shrunk.quantile(winsor_q))


def safe_divide(num: pd.Series, den: pd.Series, fill: float = 0.0) -> np.ndarray:
    """Return num/den as ndarray, with `fill` where den is 0 or NaN."""
    num = num.fillna(0)
    den = den.fillna(0)
    return np.where(den > 0, num / den.replace(0, np.nan), fill)


# ---------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------
def apply_row_filters(df: pd.DataFrame) -> pd.DataFrame:
    n0 = len(df)
    df = df.dropna(subset=['future_max_value'])
    n1 = len(df)
    df = df[df['future_max_value'] > 0].copy()
    n2 = len(df)
    df = df.dropna(subset=['mv_start']).copy()
    n3 = len(df)
    df = df[df['player_positions'].apply(has_attacking_role)].copy()
    n4 = len(df)

    print("Row filters:")
    print(f"  start:                      {n0:>6}")
    print(f"  after future_max NaN drop:  {n1:>6}  (-{n0 - n1})")
    print(f"  after future_max == 0 drop: {n2:>6}  (-{n1 - n2})")
    print(f"  after mv_start NaN drop:    {n3:>6}  (-{n2 - n3})")
    print(f"  after attacker filter:      {n4:>6}  (-{n3 - n4})")
    return df


def drop_unused_columns(df: pd.DataFrame) -> pd.DataFrame:
    existing = [c for c in DROP_COLUMNS if c in df.columns]
    missing  = [c for c in DROP_COLUMNS if c not in df.columns]
    if missing:
        print(f"  [note] drop-list columns not in file: {missing}")
    df = df.drop(columns=existing)
    print(f"  dropped {len(existing)} columns; remaining: {df.shape[1]}")
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    # ----- 3. LOG TRANSFORMS (3 columns) ------------------------------
    df['log_target']   = np.log1p(df['future_max_value'])
    df['log_mv_start'] = np.log1p(df['mv_start'])
    df['log_mv_end']   = np.log1p(df['mv_end'])

    # ----- 4. POSITION SPLIT (2 columns) ------------------------------
    positions_split = (
        df['player_positions']
          .astype(str)
          .str.split(',')
          .apply(lambda lst: [s.strip() for s in lst])
    )
    df['primary_position']   = positions_split.str[0]
    df['secondary_position'] = positions_split.apply(
        lambda lst: lst[1] if len(lst) > 1 else lst[0]
    )
    df = df.drop(columns=['player_positions'])

    # ----- 5. BAYESIAN-SHRUNK PER-90 (27 columns; batched for speed) -
    shrunk_block = {}
    for col in P90_SHRUNK_COLUMNS:
        if col not in df.columns:
            raise KeyError(f"Expected source column missing: {col}")
        shrunk_block[f'{col}_p90_shrunk'] = bayesian_shrunk_p90(df, col)
    df = pd.concat([df, pd.DataFrame(shrunk_block, index=df.index)], axis=1)

    # ----- 6. xG / xA SHRUNK PER-90 + PROXY FILL + DROP RAW (2 columns) -
    # Proxies are intermediate — computed, used, and not saved.
    shot_quality_proxy = (
        0.12 * df['shotsFromInsideTheBox_p90_shrunk']
        + 0.04 * df['shotsFromOutsideTheBox_p90_shrunk']
        + 0.08 * df['shotsOnTarget_p90_shrunk']
    )
    chance_creation_proxy = (
        0.35 * df['bigChancesCreated_p90_shrunk']
        + 0.02 * df['keyPasses_p90_shrunk']
    )

    # Raw xG/xA in the source are SEASON TOTALS (verified: Haaland 22/23 =
    # 28.66 over 2776 min). Apply Bayesian shrinkage, but with a LIGHTER
    # prior than the other rate stats.
    #
    # Why lighter prior? xG is already a smoothed statistic — every shot
    # contributes a fractional probability, so a player's xG/90 estimate is
    # much less noisy than their raw goals/90 at the same minute count.
    # Using the standard prior_90s=10 would over-shrink elite strikers
    # (Haaland 0.93 → 0.78 = 84% of real). Using prior_90s=5 preserves
    # their signal better (0.93 → 0.84 = 91%) while still correcting
    # tiny-minutes outliers (18.0 → 0.39).
    #
    # Workflow for each of {xG, xA}:
    #   1. Compute global rate from rows that have real values only.
    #   2. On real-value rows: shrunk = (xG_total + prior_xG) / (n90 + prior_90s)
    #   3. On missing rows: fall back to the proxy (already shrunk per-90).
    n90 = df['minutesPlayed'].fillna(0) / 90.0
    prior_90s = XG_XA_PRIOR_90S

    for raw_col, out_col, proxy in [
        ('expectedGoals',   'expectedGoals_p90',   shot_quality_proxy),
        ('expectedAssists', 'expectedAssists_p90', chance_creation_proxy),
    ]:
        real_mask   = df[raw_col].notna()
        real_values = df.loc[real_mask, raw_col]
        real_n90    = n90[real_mask]
        total_real_90s = real_n90.sum()
        global_rate = (real_values.sum() / total_real_90s) if total_real_90s > 0 else 0.0
        prior_val   = prior_90s * global_rate

        shrunk_real = (df[raw_col].fillna(0) + prior_val) / (n90 + prior_90s)
        df[out_col] = np.where(real_mask, shrunk_real, proxy)

    df = df.drop(columns=['expectedGoals', 'expectedAssists'])

    # ----- 7. DERIVED COUNTS, EXPOSURE, RATIOS, AGE ------------------
    # Open-play goals and its shrunk partner
    df['open_play_goals'] = (
        df['goals'].fillna(0)
        - df['penaltyGoals'].fillna(0)
        - df['freeKickGoal'].fillna(0)
    ).clip(lower=0)
    df['open_play_goals_p90_shrunk'] = bayesian_shrunk_p90(df, 'open_play_goals')

    # Exposure & role (safe division everywhere)
    df['starts_rate']   = pd.Series(
        safe_divide(df['matchesStarted'], df['appearances']), index=df.index
    ).clip(0, 1)
    df['minutes_share'] = pd.Series(
        safe_divide(df['minutesPlayed'], df['appearances'] * 90), index=df.index
    ).clip(0, 1)
    df['is_pen_taker']  = (df['penaltiesTaken'].fillna(0) >= 3).astype(int)

    # Shape / share ratios
    df['inside_box_goal_share'] = pd.Series(
        safe_divide(df['goalsFromInsideTheBox'], df['goals']), index=df.index
    ).clip(0, 1)
    df['inside_box_shot_share'] = pd.Series(
        safe_divide(df['shotsFromInsideTheBox'], df['totalShots']), index=df.index
    ).clip(0, 1)
    df['final_third_share'] = pd.Series(
        safe_divide(
            df['accurateFinalThirdPasses'],
            df['accurateOwnHalfPasses'].fillna(0) + df['accurateOppositionHalfPasses'].fillna(0),
        ),
        index=df.index,
    ).clip(0, 1)

    # Age penalty (0 below 25; squared distance above)
    age = df['age_in_season'].fillna(25)
    df['age_penalty'] = np.where(age >= 25, (age - 25) ** 2, 0.0)

    # ----- 8. Z-SCORES + RATING RESIDUAL (6 columns) ------------------
    def _zscore_group(s: pd.Series) -> pd.Series:
        return (s - s.mean()) / (s.std() + 1e-6)

    zscore_targets = [
        ('rating',            'rating_tier_z'),
        ('goals',             'goals_tier_z'),
        ('assists',           'assists_tier_z'),
        ('shotsOnTarget',     'shotsOnTarget_tier_z'),
        ('bigChancesCreated', 'bigChancesCreated_tier_z'),
    ]
    for src, dst in zscore_targets:
        df[dst] = df.groupby(['league_tier', '_season_year'])[src].transform(_zscore_group)

    peer_mean = df.groupby(['league_tier', 'team_tier'])['rating'].transform('mean')
    df['rating_residual'] = df['rating'] - peer_mean

    # ----- 9. TACTICAL COMPOSITES (4 columns; proxies stay intermediate) --
    df['ga_vs_league'] = (
        (df['goals_p90_shrunk'] + df['assists_p90_shrunk'])
        * (6 - df['league_tier'])
    )
    df['progression_p90'] = (
        df['accurateFinalThirdPasses_p90_shrunk']
        + df['successfulDribbles_p90_shrunk']
        + df['keyPasses_p90_shrunk']
    )
    df['involvement_p90'] = (
        df['totalShots_p90_shrunk']
        + df['keyPasses_p90_shrunk']
        + df['successfulDribbles_p90_shrunk']
    )
    df['modern_forward_score'] = (
        df['goals_p90_shrunk']
        + 0.7 * df['assists_p90_shrunk']
        + 0.5 * df['bigChancesCreated_p90_shrunk']
        + 0.3 * df['possessionWonAttThird_p90_shrunk']
        + 0.2 * df['successfulDribbles_p90_shrunk']
        - 0.3 * df['dispossessed_p90_shrunk']
    )

    # ----- 10. TEAM CONTEXT (2 columns) ------------------------------
    df['team_mean_mv']     = df.groupby(['team id', '_season_year'])['mv_start'].transform('mean')
    df['log_team_mean_mv'] = np.log1p(df['team_mean_mv'])

    # ----- 11. INTERACTION FLAGS + MARKET MOMENTUM (5 columns) ------
    df['young_top_club']   = ((df['age_in_season'] <= 21) & (df['team_tier']   <= 2)).astype(int)
    df['young_top_league'] = ((df['age_in_season'] <= 21) & (df['league_tier'] <= 2)).astype(int)

    # breakout_flag uses RAW goals per 90 (threshold 0.4 was set on raw values)
    raw_goals_p90 = pd.Series(
        np.where(
            df['minutesPlayed'].fillna(0) > 0,
            df['goals'].fillna(0) / (df['minutesPlayed'] / 90),
            0.0,
        ),
        index=df.index,
    )
    df['breakout_flag'] = (
        (raw_goals_p90 > 0.4) & (df['age_in_season'] <= 22)
    ).astype(int)

    df['log_mv_change_season'] = df['log_mv_end'] - df['log_mv_start']
    df['mv_surge_flag']        = (df['mv_end'] > df['mv_start'] * 1.25).astype(int)

    # ----- 12. QUALITY × DURABILITY (1 column) ----------------------
    df['rating_x_minutes'] = df['rating'].fillna(0) * df['minutesPlayed'].fillna(0)

    # Defragment after many incremental assignments
    return df.copy()


# ---------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------
def validate(df: pd.DataFrame) -> None:
    assert df['log_target'].notna().all(),   "log_target has nulls"
    assert df['log_mv_start'].notna().all(), "log_mv_start has nulls"
    assert df['league_tier'].notna().all(),  "league_tier has nulls"
    assert df['team_tier'].notna().all(),    "team_tier has nulls"

    for c in [c for c in df.columns if c.endswith('_p90_shrunk')]:
        if not np.isfinite(df[c]).all():
            raise ValueError(f"{c} has non-finite values")

    binary_checks = [
        'young_top_club', 'young_top_league', 'breakout_flag',
        'mv_surge_flag', 'is_pen_taker', 'is_tournament',
    ] + list(TOURNAMENT_FLAGS.values())
    for c in binary_checks:
        if not df[c].isin([0, 1]).all():
            raise ValueError(f"{c} is not binary")

    assert df['primary_position'].dtype == object
    assert df['secondary_position'].notna().all(), "secondary_position has nulls"

    assert 'expectedGoals' not in df.columns,   "raw expectedGoals should be dropped"
    assert 'expectedAssists' not in df.columns, "raw expectedAssists should be dropped"
    assert 'player_positions' not in df.columns

    print("All sanity checks passed.")


# ---------------------------------------------------------------------
# Recover _league (dropped by the tier-merge step) for tournament flagging
# ---------------------------------------------------------------------
def attach_league_from_raw(df: pd.DataFrame) -> pd.DataFrame:
    """
    The tier-merge step removed the raw _league column. To recover it, we
    read the original raw file and attach _league by POSITION — both files
    have identical row ordering (verified: 45,789 rows, tm_id matches at
    every index). A key-based join would be ambiguous because some
    (tm_id, _season_year, team id) triples have multiple rows (league + cup).

    Side effect: also persists the _league column back to
    att_with_tiers_for_eda.csv on disk, so that file stays consistent with
    what the pipeline uses internally. This write is idempotent — if
    _league is already present in the source file, no rewrite happens.
    """
    if '_league' in df.columns:
        # Already persisted from an earlier run — nothing to do
        print(f"  _league already present in {INPUT_PATH}, skipping attach")
        return df

    if not RAW_PATH.exists():
        raise FileNotFoundError(
            f"Raw file needed for tournament flags not found: {RAW_PATH}"
        )
    raw = pd.read_csv(RAW_PATH, usecols=['tm_id', '_league'])
    if len(raw) != len(df):
        raise ValueError(
            f"Row count mismatch: raw={len(raw)} vs tiered={len(df)} — "
            f"positional alignment not valid, refusing to attach _league."
        )
    if not (raw['tm_id'].values == df['tm_id'].values).all():
        raise ValueError(
            "tm_id sequences do not match between raw and tiered files — "
            "positional alignment is broken."
        )

    df = df.copy()
    df['_league'] = raw['_league'].values

    # Persist the update back to disk so att_with_tiers_for_eda.csv is
    # consistent with what we use in memory going forward.
    df.to_csv(INPUT_PATH, index=False)
    print(f"  attached _league and wrote back: {INPUT_PATH}")
    return df


def add_tournament_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Append tournament indicator columns at the end of the DataFrame."""
    df['is_tournament'] = df['_league'].isin(TOURNAMENT_FLAGS.keys()).astype(int)
    for league_name, col_name in TOURNAMENT_FLAGS.items():
        df[col_name] = (df['_league'] == league_name).astype(int)
    # _league itself is no longer needed after flagging
    df = df.drop(columns=['_league'])
    return df


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------
def main() -> None:
    print(f"Loading: {INPUT_PATH}")
    df = pd.read_csv(INPUT_PATH)
    print(f"  shape: {df.shape}")

    # Attach _league from raw file BEFORE any filter — alignment is positional
    df = attach_league_from_raw(df)
    print(f"  recovered _league from {RAW_PATH}")

    df = apply_row_filters(df)
    df = drop_unused_columns(df)
    df = build_features(df)
    df = add_tournament_flags(df)
    validate(df)

    # Tournament statistics
    print("\nTournament flag statistics:")
    print(f"  is_tournament = 1: {df['is_tournament'].sum():>6} rows "
          f"({df['is_tournament'].mean() * 100:.1f}%)")
    for col in TOURNAMENT_FLAGS.values():
        n = df[col].sum()
        print(f"  {col:18s} {n:>6} rows")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"{OUTPUT_NAME}.parquet"
    csv_path     = OUTPUT_DIR / f"{OUTPUT_NAME}.csv"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)
    print(f"\nSaved: {parquet_path}  shape={df.shape}")
    print(f"Saved: {csv_path}")


if __name__ == '__main__':
    main()