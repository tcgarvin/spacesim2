"""Tier-1 probe: trading-ship profitability and going-broke dynamics.

Fuel stranding is largely fixed (cc95633); the residual failure mode is ships
trading themselves BROKE — ending up without enough money to buy fuel. This
probe quantifies that.

Run against a run exported with ship logging:

    uv run spacesim2 run --turns 800 --log-actor-types ship trader --run-id X
    uv run spacesim2 dev analyze notebooks/ship_pnl_probe.py

Output contract: prints small aggregates only; saves any figures to tmp/.

Questions:
  1. Money trajectories: final/min money per ship; how many end broke?
  2. Cash-flow decomposition per ship: trade revenue vs trade spend vs fuel
     spend vs maintenance spend. Where does the money go?
  3. Loss trades: for each ship+commodity, realized sell price vs the average
     price it paid — how often do ships sell below cost?
  4. Broke spiral: once a ship's money first drops below the fuel-reserve
     price, does it recover?
  5. Per-commodity ship P&L across the fleet: which cargoes make/lose money?
"""

import json

import polars as pl

from spacesim2.analysis.loading import load_run

BROKE_MONEY = 60  # ~2 round-trip fuel units at typical prices + buffer
MAINT_GOODS = {"ship_supplies", "ship_parts", "ship_components"}

r = load_run()
print(f"run: {r.simulation_id}")

at = r.actor_turns
ships = at.filter(pl.col("actor_name").str.starts_with("Trader-"))
ship_names = sorted(set(ships["actor_name"].unique().to_list()))
n_ships = len(ship_names)
turn_max = int(ships["turn"].max())
print(f"ships logged: {n_ships}   turns: {ships['turn'].min()}..{turn_max}")
if n_ships == 0:
    print("!! No ships in actor_turns; re-export with --log-actor-types ship trader")
    raise SystemExit(0)


def _fuel(js: str) -> int:
    try:
        return int(json.loads(js).get("nova_fuel", 0))
    except (json.JSONDecodeError, TypeError):
        return 0


ships = ships.with_columns(
    pl.col("inventory_json").map_elements(_fuel, return_dtype=pl.Int64).alias("fuel"),
).sort(["actor_name", "turn"])

# ---------------------------------------------------------------------------
# Q1: money trajectories
# ---------------------------------------------------------------------------
print("\n=== Q1: per-ship money (start -> min -> final) ===")
q1 = (
    ships.group_by("actor_name")
    .agg(
        pl.col("money").first().alias("start_money"),
        pl.col("money").min().alias("min_money"),
        pl.col("money").last().alias("final_money"),
        pl.col("fuel").last().alias("final_fuel"),
        (pl.col("money") < BROKE_MONEY).sum().alias("turns_broke"),
    )
    .sort("final_money")
)
print(q1)
n_broke_end = q1.filter(pl.col("final_money") < BROKE_MONEY).height
n_rich_end = q1.filter(pl.col("final_money") > pl.col("start_money")).height
print(f"\nships ending broke (<{BROKE_MONEY}): {n_broke_end}/{n_ships}")
print(f"ships ending above starting money: {n_rich_end}/{n_ships}")

# ---------------------------------------------------------------------------
# Q2: cash-flow decomposition from transactions
# ---------------------------------------------------------------------------
print("\n=== Q2: cash-flow decomposition per ship ===")
tx = r.market_transactions
buys = tx.filter(pl.col("buyer_name").is_in(ship_names)).with_columns(
    pl.when(pl.col("commodity_id") == "nova_fuel")
    .then(pl.lit("fuel_buy"))
    .when(pl.col("commodity_id").is_in(list(MAINT_GOODS)))
    .then(pl.lit("maint_buy"))
    .otherwise(pl.lit("cargo_buy"))
    .alias("kind"),
    pl.col("buyer_name").alias("ship"),
)
sells = tx.filter(pl.col("seller_name").is_in(ship_names)).with_columns(
    pl.when(pl.col("commodity_id") == "nova_fuel")
    .then(pl.lit("fuel_sell"))
    .otherwise(pl.lit("cargo_sell"))
    .alias("kind"),
    pl.col("seller_name").alias("ship"),
)
flows = pl.concat(
    [
        buys.select("ship", "kind", "total_amount", "commodity_id", "turn"),
        sells.select("ship", "kind", "total_amount", "commodity_id", "turn"),
    ]
)
decomp = flows.pivot(
    index="ship", on="kind", values="total_amount", aggregate_function="sum"
).fill_null(0)
for col in ("cargo_buy", "cargo_sell", "fuel_buy", "fuel_sell", "maint_buy"):
    if col not in decomp.columns:
        decomp = decomp.with_columns(pl.lit(0).alias(col))
decomp = decomp.with_columns(
    (
        pl.col("cargo_sell")
        + pl.col("fuel_sell")
        - pl.col("cargo_buy")
        - pl.col("fuel_buy")
        - pl.col("maint_buy")
    ).alias("net_cash")
).sort("net_cash")
print(decomp)
print("\nfleet totals:")
print(decomp.select(pl.exclude("ship")).sum())

# ---------------------------------------------------------------------------
# Q3: loss trades — realized sell vs avg paid, per ship+commodity
# ---------------------------------------------------------------------------
print("\n=== Q3: sell-below-cost incidence (cargo only, ex-fuel) ===")
cargo_buys = buys.filter(pl.col("kind") == "cargo_buy")
cargo_sells = sells.filter(pl.col("kind") == "cargo_sell")
avg_paid = cargo_buys.group_by("ship", "commodity_id").agg(
    (pl.col("total_amount").sum() / pl.col("quantity").sum()).alias("avg_paid"),
    pl.col("quantity").sum().alias("units_bought"),
)
sell_px = cargo_sells.group_by("ship", "commodity_id").agg(
    (pl.col("total_amount").sum() / pl.col("quantity").sum()).alias("avg_sold"),
    pl.col("quantity").sum().alias("units_sold"),
)
pnl = (
    avg_paid.join(sell_px, on=["ship", "commodity_id"], how="full", coalesce=True)
    .with_columns(
        (pl.col("avg_sold") - pl.col("avg_paid")).alias("unit_margin"),
    )
    .sort("unit_margin")
)
print("worst 12 ship+commodity margins:")
print(pnl.head(12))
loss_lines = pnl.filter(pl.col("unit_margin") < 0)
print(
    f"\nship+commodity lines sold below avg cost: {loss_lines.height}/{pnl.drop_nulls('unit_margin').height}"
)
# stuck inventory: bought but never sold (dead capital)
stuck = pnl.filter(pl.col("units_sold").is_null() & (pl.col("units_bought") > 0))
print(f"lines bought but NEVER sold: {stuck.height}")
if stuck.height:
    print(stuck.sort("units_bought", descending=True).head(8))

# ---------------------------------------------------------------------------
# Q4: broke spiral — recovery after first dropping below BROKE_MONEY
# ---------------------------------------------------------------------------
print("\n=== Q4: recovery after first going broke ===")
rows = []
for name in ship_names:
    g = ships.filter(pl.col("actor_name") == name).sort("turn")
    money = g["money"].to_list()
    turns = g["turn"].to_list()
    first_broke = next((i for i, m in enumerate(money) if m < BROKE_MONEY), None)
    if first_broke is None:
        rows.append(
            {
                "ship": name,
                "first_broke_turn": None,
                "recovered": None,
                "max_money_after": None,
            }
        )
        continue
    after = money[first_broke:]
    rows.append(
        {
            "ship": name,
            "first_broke_turn": turns[first_broke],
            "recovered": max(after) > 3 * BROKE_MONEY,
            "max_money_after": max(after),
        }
    )
q4 = pl.DataFrame(rows).sort("first_broke_turn", nulls_last=True)
print(q4)

# ---------------------------------------------------------------------------
# Q5: fleet-wide per-commodity P&L
# ---------------------------------------------------------------------------
print("\n=== Q5: fleet per-commodity net cash (all ships) ===")
com = (
    flows.with_columns(
        pl.when(pl.col("kind").str.contains("sell"))
        .then(pl.col("total_amount"))
        .otherwise(-pl.col("total_amount"))
        .alias("signed")
    )
    .group_by("commodity_id")
    .agg(
        pl.col("signed").sum().alias("net_cash"),
        pl.col("signed").filter(pl.col("signed") > 0).sum().alias("revenue"),
        (-pl.col("signed").filter(pl.col("signed") < 0).sum()).alias("spend"),
    )
    .sort("net_cash")
)
print(com)

print("\nDONE.")
