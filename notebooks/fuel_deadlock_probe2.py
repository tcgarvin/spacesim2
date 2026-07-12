"""Tier-1 probe: why do trading ships end up broke AND fuel-dry?

Digs one level deeper than fuel_stranding_probe: per-ship P&L by commodity,
fuel spend vs trade revenue, end-state cargo valuation, and whether stranded
ships' standing fuel bids are visible/fillable by anyone.

    uv run spacesim2 dev analyze notebooks/fuel_deadlock_probe2.py
"""

import json

import polars as pl

from spacesim2.analysis.loading import load_run

r = load_run()
print(f"run: {r.simulation_id}")

at = r.actor_turns
tx = r.market_transactions
snaps = r.market_snapshots

ships = at.filter(pl.col("actor_name").str.starts_with("Trader-"))
ship_names = sorted(ships["actor_name"].unique().to_list())
turn_max = int(ships["turn"].max())


def _inv(js: str) -> dict:
    try:
        return json.loads(js)
    except (json.JSONDecodeError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# 1. Per-ship P&L by commodity: units and cash bought vs sold over whole run
# ---------------------------------------------------------------------------
print("\n=== 1. per-ship P&L by commodity (whole run) ===")
for name in ship_names:
    buys = tx.filter(pl.col("buyer_name") == name)
    sells = tx.filter(pl.col("seller_name") == name)
    b = buys.group_by("commodity_id").agg(
        pl.col("quantity").sum().alias("units_bought"),
        pl.col("total_amount").sum().alias("cash_out"),
    )
    s = sells.group_by("commodity_id").agg(
        pl.col("quantity").sum().alias("units_sold"),
        pl.col("total_amount").sum().alias("cash_in"),
    )
    pnl = b.join(s, on="commodity_id", how="full", coalesce=True).fill_null(0)
    pnl = pnl.with_columns((pl.col("cash_in") - pl.col("cash_out")).alias("net_cash"))
    total_net = int(pnl["net_cash"].sum())
    print(f"\n-- {name} (net cash from trades: {total_net:+d}) --")
    print(pnl.sort("net_cash"))

# ---------------------------------------------------------------------------
# 2. End state: what does each ship hold, and what is it worth locally?
# ---------------------------------------------------------------------------
print("\n=== 2. end-state holdings + local best bid for them ===")
last = ships.filter(pl.col("turn") == turn_max)
final_snaps = snaps.filter(pl.col("turn") >= turn_max - 5)
for row in last.iter_rows(named=True):
    inv = _inv(row["inventory_json"])
    planet = row["planet_name"]
    print(
        f"\n-- {row['actor_name']} @ {planet}  money={row['money']} "
        f"reserved={row['reserved_money']} --"
    )
    for cid, qty in sorted(inv.items()):
        local = final_snaps.filter(
            (pl.col("planet_name") == planet) & (pl.col("commodity_id") == cid)
        )
        bid = local["best_bid"].mean() if local.height else None
        ask = local["best_ask"].mean() if local.height else None
        nb = local["num_buy_orders"].mean() if local.height else None
        print(
            f"   {cid:28s} x{qty:<5d} local best_bid~{bid} best_ask~{ask} n_bids~{nb}"
        )

# ---------------------------------------------------------------------------
# 3. Correlation: all-ship fuel + money over time (50-turn samples)
# ---------------------------------------------------------------------------
print("\n=== 3. fleet fuel & money over time ===")
samp = ships.filter(pl.col("turn") % 50 == 0).with_columns(
    pl.col("inventory_json")
    .map_elements(lambda js: int(_inv(js).get("nova_fuel", 0)), return_dtype=pl.Int64)
    .alias("fuel")
)
pivot_fuel = samp.pivot(index="turn", on="actor_name", values="fuel").sort("turn")
pivot_money = samp.pivot(index="turn", on="actor_name", values="money").sort("turn")
print("fuel:")
print(pivot_fuel)
print("money (unreserved):")
print(pivot_money)

# ---------------------------------------------------------------------------
# 4. Fuel purchases by ships: when, where, how much, at what price
# ---------------------------------------------------------------------------
print("\n=== 4. ship fuel purchases over time (100-turn windows) ===")
fuel_buys = tx.filter(
    (pl.col("commodity_id") == "nova_fuel") & pl.col("buyer_name").is_in(ship_names)
)
if fuel_buys.height:
    fb = (
        fuel_buys.with_columns((pl.col("turn") // 100 * 100).alias("window"))
        .group_by(["window", "planet_name"])
        .agg(
            pl.col("quantity").sum().alias("units"),
            pl.col("price").mean().round(1).alias("mean_price"),
        )
        .sort(["window", "planet_name"])
    )
    print(fb)
else:
    print("  ships never bought fuel!")

# Who sells fuel late in the run (turn>=300)? Is there any ask to lift at all?
print("\n=== 4b. late-run (t>=300) fuel market state by planet ===")
late = snaps.filter((pl.col("turn") >= 300) & (pl.col("commodity_id") == "nova_fuel"))
print(
    late.group_by("planet_name")
    .agg(
        pl.col("num_sell_orders").mean().round(2).alias("mean_asks"),
        pl.col("num_buy_orders").mean().round(2).alias("mean_bids"),
        pl.col("best_ask").filter(pl.col("best_ask") > 0).mean().alias("mean_ask"),
        pl.col("best_bid").filter(pl.col("best_bid") > 0).mean().alias("mean_bid"),
        pl.col("volume").sum().alias("volume"),
    )
    .sort("planet_name")
)

# Late-run fuel sellers: who is producing/selling fuel at all after t=300?
late_fuel_sells = tx.filter(
    (pl.col("commodity_id") == "nova_fuel") & (pl.col("turn") >= 300)
)
print("\nlate-run fuel transactions (t>=300):")
if late_fuel_sells.height:
    print(
        late_fuel_sells.group_by(["planet_name"]).agg(
            pl.col("quantity").sum().alias("units"),
            pl.col("price").mean().round(1).alias("mean_price"),
            pl.col("seller_name").n_unique().alias("n_sellers"),
            pl.col("buyer_name").n_unique().alias("n_buyers"),
        )
    )
else:
    print("  NONE")

print("\nDONE.")
