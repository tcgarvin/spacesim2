"""Probe: where does the production/trade chain break across the tier tree?"""

import polars as pl

from spacesim2.analysis.loading import load_run

r = load_run()
print(f"run: {r.simulation_id}")

# Schemas (small) so we know available columns
print("market_transactions cols:", r.market_transactions.columns)
print("market_snapshots cols:", r.market_snapshots.columns)

# Trade volume per commodity over the whole run
tx = r.market_transactions
vol = (
    tx.group_by("commodity_id")
    .agg(
        pl.len().alias("n_trades"),
        pl.col("quantity").sum().alias("total_qty"),
    )
    .sort("total_qty", descending=True)
)
print("\n=== trade volume per commodity (traded at all) ===")
print(vol)

# Which commodities NEVER traded
traded = set(vol["commodity_id"].to_list())
print("\n=== commodities that NEVER traded ===")
# pull full commodity list from snapshots (every commodity gets a snapshot)
all_comm = set(r.market_snapshots["commodity_id"].to_list())
never = sorted(all_comm - traded)
print(never)

# Avg price in last 30 turns for never-traded vs traded
last = r.market_snapshots.filter(
    pl.col("turn") >= r.market_snapshots["turn"].max() - 30
)
price_tail = (
    last.group_by("commodity_id")
    .agg(pl.col("avg_price").mean().round(1).alias("price_tail"))
    .sort("commodity_id")
)
print("\n=== mean avg_price, last 30 turns ===")
print(price_tail)
