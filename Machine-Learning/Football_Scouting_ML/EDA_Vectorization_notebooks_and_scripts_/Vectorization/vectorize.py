"""
vectorize.py — Build per (player, cutoff_year) vectors from att_features.parquet

Input:
    data/processed/att_features/att_features.parquet
        Per-row features (player × season × competition), 32,524 rows × 154 cols.

Output:
    data/processed/att_vectors/att_vectors.parquet  and .csv
        One row per (player, cutoff_year) pair where the player has:
          - A league (non-tournament) row at the cutoff season
          - A valid future_max_value target
        Approximately 22,671 rows × ~290 columns.

Architecture:
    The vectorizer uses BULK pandas groupby operations instead of per-player
    Python loops. For each cutoff year, historical aggregates are computed
    once across all players in a single groupby pass, then joined back to the
    primary rows. This is ~1000x faster than row-by-row iteration.

Cutoffs emitted: 2020, 2021, 2022, 2023, 2024 (5 cutoffs).
  2017 excluded: only 263 players, essentially no prior history.
  2018 excluded: 93% of players have no history (data effectively starts at 17/18).
  2019 excluded: 88% have <= 1 prior season — too thin for meaningful history signal.
  2025 excluded: no forward target (last season in data).
"""

from pathlib import Path
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
INPUT_PATH  = Path("../../data/processed/att_features_before_vectorization/att_features_before_vectorization.parquet")
OUTPUT_DIR  = Path("../../data/processed/att_vectors")
OUTPUT_NAME = "att_vectors"

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

# Map season labels to integer cutoff_year.
# Both '17/18' (ends summer 2018) and '2018' (ends Dec 2018) map to cutoff=2018
SEASON_TO_CUTOFF = {
    '17/18': 2018, '2018': 2018,
    '18/19': 2019, '2019': 2019,
    '19/20': 2020, '2020': 2020,
    '20/21': 2021, '2021': 2021,
    '21/22': 2022, '2022': 2022,
    '22/23': 2023, '2023': 2023,
    '23/24': 2024, '2024': 2024,
    '24/25': 2025, '2025': 2025,
    '2017':  2017,
}

EMIT_CUTOFFS = [2020, 2021, 2022, 2023, 2024]

# Stats with full 6-aggregate historical treatment.
# ballRecovery excluded: 72.5% null uniformly across tiers, no usable signal.
# passToAssist excluded: 91% zeros, too rare.
HIST_STATS = [
    'goals_p90_shrunk',
    'assists_p90_shrunk',
    'open_play_goals_p90_shrunk',
    'expectedGoals_p90',
    'expectedAssists_p90',
    'shotsOnTarget_p90_shrunk',
    'totalShots_p90_shrunk',
    'shotsFromInsideTheBox_p90_shrunk',
    'bigChancesCreated_p90_shrunk',
    'keyPasses_p90_shrunk',
    'accurateFinalThirdPasses_p90_shrunk',
    'successfulDribbles_p90_shrunk',
    'progression_p90',
    'touches_p90_shrunk',
    'wasFouled_p90_shrunk',
    'possessionWonAttThird_p90_shrunk',
    'dispossessed_p90_shrunk',
    'rating',
    'rating_residual',
    'modern_forward_score',
]

# Stats that get a league-tier-weighted historical mean (weight = 6 - tier).
HIST_WEIGHTED_STATS = [
    'goals_p90_shrunk',
    'assists_p90_shrunk',
    'expectedGoals_p90',
    'expectedAssists_p90',
    'rating',
    'rating_residual',
    'modern_forward_score',
    'ga_vs_league',
]

CONTINENTAL_FLAGS = ['is_ucl', 'is_uel', 'is_uecl', 'is_libertadores']
INTL_FLAGS        = ['is_euro', 'is_wc', 'is_gold_cup']


# ---------------------------------------------------------------------
# Block B: determine which columns to copy verbatim from cutoff row
# ---------------------------------------------------------------------
def block_b_columns(df: pd.DataFrame) -> list:
    exclude = {
        # Pure identifiers
        'tm_id', 'player id', 'team id', 'player', '_league',
        # Metadata-only
        '_season_year', 'is_imputed', 'mv_start_date', 'mv_end_date',
        # Target & cutoff
        'future_max_value', 'log_target', '_cutoff_year',
        # Redundant raw-EUR columns — their log counterparts (log_mv_start,
        # log_mv_end, log_team_mean_mv) carry the same information in a
        # model-friendlier distribution. Keeping both creates duplication
        # that inflates feature importance metrics and confuses interpretation.
        # Tree models also handle log scale better for highly-skewed price data.
        'mv_start', 'mv_end', 'team_mean_mv',
    }
    return [c for c in df.columns if c not in exclude]


# ---------------------------------------------------------------------
# Bulk historical aggregates for Block D and weighted means
# ---------------------------------------------------------------------
def compute_hist_aggs_for_cutoff(
    all_league_rows: pd.DataFrame,
    cutoff: int,
) -> pd.DataFrame:
    """
    For a single cutoff year C, compute per-player historical aggregates
    using rows with _cutoff_year < C (LEAGUE rows only, already filtered).
    Returns DataFrame indexed by tm_id.
    """
    hist = all_league_rows[all_league_rows['_cutoff_year'] < cutoff]
    if len(hist) == 0:
        return pd.DataFrame()

    grouped = hist.groupby('tm_id', sort=False)

    # Standard mean/median/max aggregates for HIST_STATS
    agg_spec = {stat: ['mean', 'median', 'max'] for stat in HIST_STATS if stat in hist.columns}
    aggs = grouped.agg(agg_spec)
    # Flatten multi-index columns
    aggs.columns = [f'hist_{stat}_{func}' for stat, func in aggs.columns]

    # League-tier-weighted mean for HIST_WEIGHTED_STATS
    # weight = (6 - league_tier), clipped at 1
    weights = (6 - hist['league_tier'].astype(float)).clip(lower=1)
    hist_w = hist.copy()
    hist_w['_w'] = weights
    for stat in HIST_WEIGHTED_STATS:
        if stat not in hist_w.columns:
            aggs[f'hist_{stat}_weighted_mean'] = np.nan
            continue
        hist_w[f'_num_{stat}'] = hist_w[stat] * hist_w['_w']
        hist_w[f'_den_{stat}'] = np.where(hist_w[stat].notna(), hist_w['_w'], 0)
    sum_cols = {}
    for stat in HIST_WEIGHTED_STATS:
        if stat not in hist.columns:
            continue
        sum_cols[f'_num_{stat}'] = 'sum'
        sum_cols[f'_den_{stat}'] = 'sum'
    if sum_cols:
        wsums = hist_w.groupby('tm_id', sort=False).agg(sum_cols)
        for stat in HIST_WEIGHTED_STATS:
            if stat not in hist.columns:
                continue
            num = wsums[f'_num_{stat}']
            den = wsums[f'_den_{stat}']
            aggs[f'hist_{stat}_weighted_mean'] = np.where(den > 0, num / den, np.nan)

    # General career aggregates (Block E)
    aggs['hist_n_prior_seasons'] = grouped.size()
    aggs['hist_minutes_mean']    = grouped['minutesPlayed'].mean()
    aggs['hist_minutes_sum']     = grouped['minutesPlayed'].sum()

    # MV lag features — use .apply with iloc for correct tm_id-indexed Series.
    # Note: groupby().nth(-1) returns a Series indexed by the ORIGINAL row index,
    # not by the group key. Assigning it to a tm_id-indexed DataFrame produces
    # NaN for almost every row due to index misalignment (a subtle pandas gotcha).
    # Using .apply with iloc returns a properly tm_id-indexed Series.
    hist_sorted = hist.sort_values(['tm_id', 'mv_start_date'])
    lmv_by_player = hist_sorted.groupby('tm_id')['log_mv_start']
    aggs['hist_log_mv_prev_1'] = lmv_by_player.apply(
        lambda s: s.iloc[-1] if len(s) >= 1 else np.nan
    )
    aggs['hist_log_mv_prev_2'] = lmv_by_player.apply(
        lambda s: s.iloc[-2] if len(s) >= 2 else np.nan
    )
    aggs['hist_career_mv_peak_log'] = grouped['log_mv_start'].max()

    # League-tier career stats
    aggs['hist_avg_league_tier']  = grouped['league_tier'].mean()
    aggs['hist_peak_league_tier'] = grouped['league_tier'].min()
    aggs['hist_pct_prior_seasons_in_tier_1_2'] = grouped['league_tier'].apply(
        lambda s: float((s <= 2).sum() / len(s)) if len(s) > 0 else np.nan
    )
    aggs['hist_pct_prior_seasons_in_tier_1'] = grouped['league_tier'].apply(
        lambda s: float((s == 1).sum() / len(s)) if len(s) > 0 else np.nan
    )

    return aggs


def compute_continental_hist_aggs_for_cutoff(
    all_rows: pd.DataFrame,
    cutoff: int,
) -> pd.DataFrame:
    """Block F historical continental aggregates for a given cutoff."""
    hist_cont = all_rows[
        (all_rows['_cutoff_year'] < cutoff)
        & (all_rows[CONTINENTAL_FLAGS].sum(axis=1) > 0)
    ]
    if len(hist_cont) == 0:
        return pd.DataFrame()

    grp = hist_cont.groupby('tm_id', sort=False)
    out = pd.DataFrame(index=grp.size().index)
    out['hist_cont_minutes_sum']             = grp['minutesPlayed'].sum()
    out['hist_cont_rating_mean']             = grp['rating'].mean()
    out['hist_cont_rating_max']              = grp['rating'].max()
    out['hist_cont_expectedGoals_p90_mean']  = grp['expectedGoals_p90'].mean()
    out['hist_cont_expectedGoals_p90_max']   = grp['expectedGoals_p90'].max()
    out['hist_cont_goals_p90_mean']          = grp['goals_p90_shrunk'].mean()
    return out


def compute_current_tournament_summary(cutoff_year_rows: pd.DataFrame) -> pd.DataFrame:
    """
    Block C: tournament summary aggregated per (tm_id) for a given cutoff year.
    Input: all rows at cutoff (both league and tournament types).
    """
    trows = cutoff_year_rows[cutoff_year_rows['is_tournament'] == 1]
    if len(trows) == 0:
        return pd.DataFrame()

    grp = trows.groupby('tm_id', sort=False)
    out = pd.DataFrame(index=grp.size().index)
    out['tournament_played_at_cutoff'] = 1
    ucl_sum  = grp['is_ucl'].sum()
    uel_sum  = grp['is_uel'].sum()
    uecl_sum = grp['is_uecl'].sum()
    out['uefa_club_cup_at_cutoff'] = ((ucl_sum + uel_sum + uecl_sum) > 0).astype(int)
    out['uefa_highest_tier_at_cutoff'] = np.where(
        ucl_sum > 0, 1,
        np.where(uel_sum > 0, 2,
                 np.where(uecl_sum > 0, 3, 0))
    )
    intl_sum = sum(grp[c].sum() for c in INTL_FLAGS)
    out['national_team_tournament_at_cutoff'] = (intl_sum > 0).astype(int)
    out['tournament_minutes_at_cutoff'] = grp['minutesPlayed'].sum()
    out['tournament_goals_at_cutoff']   = grp['goals'].sum()
    return out


def compute_current_continental_summary(cutoff_year_rows: pd.DataFrame) -> pd.DataFrame:
    """Block F current-season continental summary per (tm_id)."""
    cont = cutoff_year_rows[cutoff_year_rows[CONTINENTAL_FLAGS].sum(axis=1) > 0]
    if len(cont) == 0:
        return pd.DataFrame()

    grp = cont.groupby('tm_id', sort=False)
    out = pd.DataFrame(index=grp.size().index)
    out['cont_played_current_season'] = 1
    ucl_s  = grp['is_ucl'].sum()
    uel_s  = grp['is_uel'].sum()
    uecl_s = grp['is_uecl'].sum()
    lib_s  = grp['is_libertadores'].sum()
    out['cont_highest_tier_current'] = np.where(
        ucl_s > 0, 1,
        np.where(uel_s > 0, 2,
                 np.where(uecl_s > 0, 3,
                          np.where(lib_s > 0, 4, 0)))
    )
    out['cont_minutes_current']             = grp['minutesPlayed'].sum()
    out['cont_goals_current']               = grp['goals'].sum()
    out['cont_assists_current']             = grp['assists'].sum()
    out['cont_expectedGoals_p90_current']   = grp['expectedGoals_p90'].mean()
    out['cont_expectedAssists_p90_current'] = grp['expectedAssists_p90'].mean()
    out['cont_rating_current']              = grp['rating'].mean()
    return out


def compute_last_intl_tournament_before_cutoff(
    all_rows: pd.DataFrame,
    cutoff: int,
) -> pd.DataFrame:
    """
    Block G: for each player, find their most recent international tournament
    row BEFORE the cutoff year. Returns features per tm_id.
    """
    intl_hist = all_rows[
        (all_rows['_cutoff_year'] < cutoff)
        & (all_rows[INTL_FLAGS].sum(axis=1) > 0)
        & (all_rows['mv_start_date'].notna())
    ]
    if len(intl_hist) == 0:
        return pd.DataFrame()

    # Per player, pick the row with the latest mv_start_date
    intl_sorted = intl_hist.sort_values('mv_start_date')
    latest = intl_sorted.drop_duplicates(subset='tm_id', keep='last').set_index('tm_id')

    out = pd.DataFrame(index=latest.index)
    out['hist_years_since_last_major_intl']   = (cutoff - pd.to_datetime(latest['mv_start_date']).dt.year).astype(float)
    out['hist_last_intl_minutes']             = latest['minutesPlayed'].astype(float)
    out['hist_last_intl_goals']               = latest['goals'].astype(float)
    out['hist_last_intl_assists']             = latest['assists'].astype(float)
    out['hist_last_intl_expectedGoals_p90']   = latest['expectedGoals_p90'].astype(float)
    out['hist_last_intl_expectedAssists_p90'] = latest['expectedAssists_p90'].astype(float)
    out['hist_last_intl_rating']              = latest['rating'].astype(float)
    return out


# ---------------------------------------------------------------------
# Per-cutoff vector assembly
# ---------------------------------------------------------------------
def build_vectors_for_cutoff(
    df: pd.DataFrame,
    cutoff: int,
    block_b_cols: list,
) -> pd.DataFrame:
    """Build all vectors for a given cutoff year using bulk ops."""
    # All rows at this cutoff (league + tournament)
    cutoff_rows = df[df['_cutoff_year'] == cutoff]
    if len(cutoff_rows) == 0:
        return pd.DataFrame()

    # League rows with valid target are the ELIGIBLE primary rows
    eligible = cutoff_rows[
        (cutoff_rows['is_tournament'] == 0)
        & cutoff_rows['future_max_value'].notna()
        & (cutoff_rows['future_max_value'] > 0)
    ]
    if len(eligible) == 0:
        return pd.DataFrame()

    # Pick primary row per tm_id (max minutes in case of duplicates)
    primary = (
        eligible.sort_values('minutesPlayed', ascending=False, na_position='last')
                .drop_duplicates(subset='tm_id', keep='first')
                .set_index('tm_id')
    )

    # Base: Block A + B (copied from primary row)
    vec = pd.DataFrame(index=primary.index)
    vec['tm_id']                 = primary.index
    vec['cutoff_year']           = cutoff
    age = primary['age_in_season'].astype(float)
    vec['age_at_cutoff']         = age
    vec['age_penalty']           = np.where(age.notna(), np.maximum(0, age - 25) ** 2, np.nan)
    vec['primary_position']      = primary['primary_position'].values
    vec['secondary_position']    = primary['secondary_position'].values
    vec['league_tier_at_cutoff'] = primary['league_tier'].values
    vec['team_tier_at_cutoff']   = primary['team_tier'].values
    # Block B — full cutoff-row feature copy
    for c in block_b_cols:
        if c in primary.columns:
            vec[c] = primary[c].values

    # Position remaps (applied AFTER Block B verbatim copy, which would
    # otherwise overwrite these assignments).
    #
    # The goal is to collapse the position categorical down to just five values:
    # ST, LW, RW, RM, LM — each with 700+ examples. This prevents the model
    # from forming spurious leaves on rare position buckets (which invariably
    # come from quirky utility players whose specific profile does not
    # generalize).
    #
    # Part 1 — primary-position remaps (these also control the secondary value):
    #
    #  - primary='RB'  → 'RM' / 'RM'
    #      Only 2 source rows (Marcus Godinho), utility full-back with RM
    #      secondary. Avoids a spurious 2-sample leaf.
    #
    #  - primary='CF'  → 'ST' / 'LW'
    #      Statistically near-identical to ST (goals 4.3 vs 4.0 mean, minutes
    #      1045 vs 926, rating 6.71 vs 6.74). CF is a center-forward variant;
    #      merging into ST is distributionally safe. LW secondary reflects the
    #      frequent wide-drift of modern center-forwards (e.g. Diogo Jota,
    #      Nkunku).
    #
    #  - primary='CAM' → 'RM' / 'LM'
    #      CAM is an attacking midfielder. Statistical profile (high key
    #      passes, moderate shots) matches midfielders more than wide forwards.
    #      RM primary + LM secondary preserves midfielder nature and
    #      acknowledges bilateral flank flexibility.
    primary_remaps = {
        'RB':  ('RM', 'RM'),
        'CF':  ('ST', 'LW'),
        'CAM': ('RM', 'LM'),
    }
    for old_primary, (new_primary, new_secondary) in primary_remaps.items():
        mask = vec['primary_position'] == old_primary
        if mask.any():
            vec.loc[mask, 'primary_position']   = new_primary
            vec.loc[mask, 'secondary_position'] = new_secondary

    # Part 2 — secondary-only remaps (for rows whose primary is already one of
    # the five canonical values, but whose secondary is a rare category).
    # Same logic as primary remaps: collapse rare categoricals to the nearest
    # tactically similar canonical value.
    #
    #   CAM, CM         → RM   (central-ish midfielders → RM family)
    #   CF              → ST   (center-forward variant → striker family)
    #   RWB, RB         → RM   (right-sided fullback/wing-back → RM)
    #   LWB, LB         → LM   (left-sided fullback/wing-back → LM)
    secondary_remaps = {
        'CAM': 'RM',
        'CM':  'RM',
        'CF':  'ST',
        'RWB': 'RM',
        'RB':  'RM',
        'LWB': 'LM',
        'LB':  'LM',
    }
    for old_secondary, new_secondary in secondary_remaps.items():
        mask = vec['secondary_position'] == old_secondary
        if mask.any():
            vec.loc[mask, 'secondary_position'] = new_secondary

    # Block C: tournament summary at this cutoff
    c_sum = compute_current_tournament_summary(cutoff_rows)
    for col in ['tournament_played_at_cutoff', 'uefa_club_cup_at_cutoff',
                'uefa_highest_tier_at_cutoff', 'national_team_tournament_at_cutoff',
                'tournament_minutes_at_cutoff', 'tournament_goals_at_cutoff']:
        if col in c_sum.columns:
            vec[col] = c_sum[col].reindex(vec.index)
        else:
            vec[col] = 0
    vec['tournament_played_at_cutoff']        = vec['tournament_played_at_cutoff'].fillna(0).astype(int)
    vec['uefa_club_cup_at_cutoff']            = vec['uefa_club_cup_at_cutoff'].fillna(0).astype(int)
    vec['uefa_highest_tier_at_cutoff']        = vec['uefa_highest_tier_at_cutoff'].fillna(0).astype(int)
    vec['national_team_tournament_at_cutoff'] = vec['national_team_tournament_at_cutoff'].fillna(0).astype(int)
    vec['tournament_minutes_at_cutoff']       = vec['tournament_minutes_at_cutoff'].fillna(0.0)
    vec['tournament_goals_at_cutoff']         = vec['tournament_goals_at_cutoff'].fillna(0.0)

    # Block D: bulk historical aggregates
    all_league_rows = df[df['is_tournament'] == 0]
    hist_aggs = compute_hist_aggs_for_cutoff(all_league_rows, cutoff)

    # Attach hist_ columns
    for stat in HIST_STATS:
        for agg in ['mean', 'median', 'max']:
            col = f'hist_{stat}_{agg}'
            vec[col] = hist_aggs[col].reindex(vec.index) if col in hist_aggs.columns else np.nan

        # Deltas: current_vs_hist
        current_col = stat if stat in primary.columns else None
        hist_mean_col = f'hist_{stat}_mean'
        hist_med_col  = f'hist_{stat}_median'
        hist_max_col  = f'hist_{stat}_max'
        cur_val = primary[stat].values if current_col else np.nan
        vec[f'current_{stat}_vs_hist_mean']   = cur_val - vec[hist_mean_col].values if current_col else np.nan
        vec[f'current_{stat}_vs_hist_median'] = cur_val - vec[hist_med_col].values  if current_col else np.nan
        vec[f'current_{stat}_vs_hist_max']    = cur_val - vec[hist_max_col].values  if current_col else np.nan

    for stat in HIST_WEIGHTED_STATS:
        col = f'hist_{stat}_weighted_mean'
        vec[col] = hist_aggs[col].reindex(vec.index) if col in hist_aggs.columns else np.nan

    # Block E: general career aggregates (many already in hist_aggs)
    career_cols = [
        'hist_n_prior_seasons', 'hist_minutes_mean', 'hist_minutes_sum',
        'hist_log_mv_prev_1', 'hist_log_mv_prev_2', 'hist_career_mv_peak_log',
        'hist_avg_league_tier', 'hist_peak_league_tier',
        'hist_pct_prior_seasons_in_tier_1_2', 'hist_pct_prior_seasons_in_tier_1',
    ]
    for col in career_cols:
        if col in hist_aggs.columns:
            vec[col] = hist_aggs[col].reindex(vec.index)
        else:
            vec[col] = np.nan

    # has_history flag
    vec['has_history']         = (vec['hist_n_prior_seasons'].fillna(0) >= 1).astype(int)
    vec['hist_n_prior_seasons'] = vec['hist_n_prior_seasons'].fillna(0).astype(int)
    vec['hist_minutes_sum']    = vec['hist_minutes_sum'].fillna(0.0)

    # is_at_career_peak
    cur_lmv = primary['log_mv_start'].values
    peak_lmv = vec['hist_career_mv_peak_log'].values
    # If no history → not at peak (return 0 to match previous semantics)
    vec['is_at_career_peak'] = np.where(
        np.isnan(peak_lmv), 0,
        np.where(np.isnan(cur_lmv), 0,
                 (cur_lmv >= peak_lmv).astype(int))
    ).astype(int)

    # Block F: continental
    cur_cont = compute_current_continental_summary(cutoff_rows)
    hist_cont = compute_continental_hist_aggs_for_cutoff(df, cutoff)

    cont_current_cols = [
        'cont_played_current_season', 'cont_highest_tier_current',
        'cont_minutes_current', 'cont_goals_current', 'cont_assists_current',
        'cont_expectedGoals_p90_current', 'cont_expectedAssists_p90_current',
        'cont_rating_current',
    ]
    for col in cont_current_cols:
        if col in cur_cont.columns:
            vec[col] = cur_cont[col].reindex(vec.index)
        else:
            vec[col] = np.nan
    # Fill binary/summable defaults
    vec['cont_played_current_season'] = vec['cont_played_current_season'].fillna(0).astype(int)
    vec['cont_highest_tier_current']  = vec['cont_highest_tier_current'].fillna(0).astype(int)
    for c in ['cont_minutes_current', 'cont_goals_current', 'cont_assists_current']:
        vec[c] = vec[c].fillna(0.0)

    # cont xG vs domestic delta
    vec['cont_xG_vs_domestic_current'] = (
        vec['cont_expectedGoals_p90_current'].values - primary['expectedGoals_p90'].values
    )

    cont_hist_cols = [
        'hist_cont_minutes_sum', 'hist_cont_rating_mean', 'hist_cont_rating_max',
        'hist_cont_expectedGoals_p90_mean', 'hist_cont_expectedGoals_p90_max',
        'hist_cont_goals_p90_mean',
    ]
    for col in cont_hist_cols:
        if col in hist_cont.columns:
            vec[col] = hist_cont[col].reindex(vec.index)
        else:
            vec[col] = np.nan
    vec['hist_cont_minutes_sum'] = vec['hist_cont_minutes_sum'].fillna(0.0)

    vec['cont_current_vs_hist_rating_mean'] = (
        vec['cont_rating_current'].values - vec['hist_cont_rating_mean'].values
    )

    # Block G: international tournament history
    intl_hist = compute_last_intl_tournament_before_cutoff(df, cutoff)
    intl_cols = [
        'hist_years_since_last_major_intl',
        'hist_last_intl_minutes', 'hist_last_intl_goals', 'hist_last_intl_assists',
        'hist_last_intl_expectedGoals_p90', 'hist_last_intl_expectedAssists_p90',
        'hist_last_intl_rating',
    ]
    for col in intl_cols:
        if col in intl_hist.columns:
            vec[col] = intl_hist[col].reindex(vec.index)
        else:
            vec[col] = np.nan

    # Target
    vec['log_target'] = np.log1p(primary['future_max_value'].astype(float).values)

    return vec.reset_index(drop=True)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def build_all_vectors(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['_cutoff_year'] = df['_season_year'].map(SEASON_TO_CUTOFF).astype('Int64')
    df['mv_start_date'] = pd.to_datetime(df['mv_start_date'], errors='coerce')
    df = df.sort_values(['tm_id', 'mv_start_date', '_season_year']).reset_index(drop=True)

    block_b_cols = block_b_columns(df)

    all_vectors = []
    for cutoff in EMIT_CUTOFFS:
        print(f"  cutoff {cutoff}...")
        vec = build_vectors_for_cutoff(df, cutoff, block_b_cols)
        if len(vec) > 0:
            print(f"    {len(vec)} vectors, {vec.shape[1]} columns")
            all_vectors.append(vec)

    return pd.concat(all_vectors, ignore_index=True)


def validate(df: pd.DataFrame) -> None:
    """Integrity checks before writing output."""
    assert df['tm_id'].notna().all(),       "tm_id has nulls"
    assert df['cutoff_year'].notna().all(), "cutoff_year has nulls"
    assert df['log_target'].notna().all(),  "log_target has nulls"
    assert set(df['cutoff_year'].unique()).issubset(set(EMIT_CUTOFFS)), \
        f"Unexpected cutoff years: {set(df['cutoff_year'].unique()) - set(EMIT_CUTOFFS)}"

    binary_cols = [
        'tournament_played_at_cutoff', 'uefa_club_cup_at_cutoff',
        'national_team_tournament_at_cutoff',
        'cont_played_current_season', 'has_history', 'is_at_career_peak',
    ]
    for c in binary_cols:
        if c in df.columns:
            uniq = set(df[c].dropna().unique())
            if not uniq.issubset({0, 1}):
                raise ValueError(f"{c} is not binary; got {uniq}")

    assert df['primary_position'].notna().all(),   "primary_position has nulls"
    assert df['secondary_position'].notna().all(), "secondary_position has nulls"

    if 'age_at_cutoff' in df.columns:
        ages = df['age_at_cutoff'].dropna()
        assert (ages >= 14).all() and (ages <= 45).all(), "age_at_cutoff out of range"

    print("  ✓ All sanity checks passed.")


def main() -> None:
    print(f"Loading: {INPUT_PATH}")
    df = pd.read_parquet(INPUT_PATH)
    print(f"  shape: {df.shape}")

    print("Building vectors per cutoff (bulk groupby)...")
    vectors = build_all_vectors(df)
    print(f"\n  built {len(vectors)} vectors × {vectors.shape[1]} columns")

    validate(vectors)

    print("\nVectors per cutoff:")
    for y in EMIT_CUTOFFS:
        n = (vectors['cutoff_year'] == y).sum()
        np_players = vectors[vectors['cutoff_year'] == y]['tm_id'].nunique()
        print(f"  {y}: {n:>5} rows, {np_players:>5} unique players")
    print(f"\nTotal unique players across cutoffs: {vectors['tm_id'].nunique()}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUTPUT_DIR / f"{OUTPUT_NAME}.parquet"
    csv_path     = OUTPUT_DIR / f"{OUTPUT_NAME}.csv"
    vectors.to_parquet(parquet_path, index=False)
    vectors.to_csv(csv_path, index=False)
    print(f"\nSaved: {parquet_path}  shape={vectors.shape}")
    print(f"Saved: {csv_path}")


if __name__ == '__main__':
    main()
