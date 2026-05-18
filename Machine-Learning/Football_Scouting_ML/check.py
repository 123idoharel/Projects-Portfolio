import pandas as pd

# Pick the right horizon: 1y or 2y
HORIZON = "2y"  # change to "2y" for the second run
TARGET_COL = f"target_{HORIZON}_log"

oof = pd.read_parquet(f"results_mh/{HORIZON}/stage2_oof_tuned.parquet")
vecs = pd.read_parquet("data/processed/att_vectors_mh/att_vectors_mh.parquet")

df = oof.merge(
    vecs[["tm_id", "cutoff_year", "age_at_cutoff", TARGET_COL, "log_mv_end"]],
    on=["tm_id", "cutoff_year"]
)

# True ratio for THIS horizon (not the peak target)
df["actual_ratio"] = df[TARGET_COL] - df["log_mv_end"]
df = df.dropna(subset=["actual_ratio"])  # drop rows where this horizon's target is NaN

df["residual"] = df["actual_ratio"] - df["oof_pred_ratio"]
df["age_bin"] = (df["age_at_cutoff"] // 2 * 2).astype(int)

print(df.groupby("age_bin")["residual"].agg(["mean", "std", "count"]).round(3))