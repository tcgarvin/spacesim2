"""Tier-1: who buys at price<=2, and does the maker's probe-at-1 anchor prices?"""

import polars as pl

from spacesim2.analysis.loading import load_run

r = load_run()
tx = r.market_transactions

names = tx.select(pl.col("buyer_name")).unique()
print("--- distinct buyer name patterns ---")
print(
    names.with_columns(
        pl.col("buyer_name").str.replace_all(r"-?\d+", "").alias("pattern")
    )
    .group_by("pattern")
    .len()
    .sort("len", descending=True)
)

tx = tx.with_columns(
    pl.col("buyer_name").str.replace_all(r"-?\d+", "").alias("buyer_kind"),
    pl.col("seller_name").str.replace_all(r"-?\d+", "").alias("seller_kind"),
    (pl.col("price") <= 2).alias("cheap"),
)

print("--- volume share by buyer kind, cheap (<=2) vs not ---")
print(
    tx.group_by("buyer_kind", "cheap")
    .agg(pl.col("quantity").sum().alias("vol"))
    .sort("vol", descending=True)
    .head(12)
)

print("--- cheap-trade volume by commodity and buyer kind ---")
print(
    tx.filter(pl.col("cheap"))
    .group_by("commodity_id", "buyer_kind")
    .agg(pl.col("quantity").sum().alias("vol"))
    .sort("vol", descending=True)
    .head(15)
)

print("--- seller kind for cheap trades ---")
print(
    tx.filter(pl.col("cheap"))
    .group_by("seller_kind")
    .agg(pl.col("quantity").sum().alias("vol"))
    .sort("vol", descending=True)
)

# Did prices ever recover after anchoring low? food + clothing price by 50-turn bucket
print("--- mean trade price by 50-turn bucket ---")
print(
    tx.filter(
        pl.col("commodity_id").is_in(["food", "clothing", "simple_tools", "wood"])
    )
    .with_columns((pl.col("turn") // 50 * 50).alias("bucket"))
    .group_by("commodity_id", "bucket")
    .agg(pl.col("price").mean().round(2).alias("mean_px"), pl.len().alias("n"))
    .sort("commodity_id", "bucket")
    .pivot(values="mean_px", index="bucket", on="commodity_id")
    .sort("bucket")
)
