"""Tier-1 probe: can ships afford fuel at its honest replacement cost?

TODO.md ("Cross-planet fuel demand doesn't propagate") says: before plumbing
demand signals across planets, establish whether the fuel chain is viable at
all. This probe derives each ship's *realized* fuel willingness-to-pay from
trade P&L and compares it with fuel's honest replacement cost on the best
ore-rich planet.

Run against a run exported with ship logging:

    uv run spacesim2 run --turns 800 --log-actor-types ship trader --run-id X
    uv run spacesim2 dev analyze notebooks/ship_fuel_wtp_probe.py

Output contract: prints small aggregates only; saves figures to tmp/.

Questions:
  1. Fuel burned per ship (bought - sold - tank delta) and trips flown.
  2. Break-even fuel price per ship: (cargo margin - maintenance) / fuel
     burned. This is the max sustainable fuel price at realized margins.
  3. Realized fuel price actually paid, for comparison.
  4. Honest replacement cost of fuel per planet, from recipe constants and
     exported planet attributes: 4 ore x (wage+wear)/(2*attr) + (wage+wear).
  5. Verdict: does best-planet honest cost fit under fleet break-even WTP?
"""

import json
from pathlib import Path

import polars as pl

from spacesim2.analysis.loading import load_run

# Mirrors core/actor_brain.py imputed-cost constants.
GOVERNMENT_WAGE = 10
TOOL_EXPECTED_LIFESPAN = 100
MAINT_GOODS = {"ship_supplies", "ship_parts", "ship_components"}

r = load_run()
print(f"run: {r.simulation_id}")

at = r.actor_turns
ships = at.filter(pl.col("actor_name").str.starts_with("Trader-"))
ship_names = sorted(set(ships["actor_name"].unique().to_list()))
if not ship_names:
    print("!! No ships in actor_turns; re-export with --log-actor-types ship trader")
    raise SystemExit(0)
print(
    f"ships logged: {len(ship_names)}   turns: {ships['turn'].min()}..{ships['turn'].max()}"
)


def _fuel(js: str) -> int:
    try:
        return int(json.loads(js).get("nova_fuel", 0))
    except (json.JSONDecodeError, TypeError):
        return 0


ships = ships.with_columns(
    pl.col("inventory_json").map_elements(_fuel, return_dtype=pl.Int64).alias("fuel"),
).sort(["actor_name", "turn"])

# ---------------------------------------------------------------------------
# Q1+Q2: per-ship fuel burn, trips, and break-even fuel price
# ---------------------------------------------------------------------------
tx = r.market_transactions
buys = tx.filter(pl.col("buyer_name").is_in(ship_names)).with_columns(
    pl.col("buyer_name").alias("ship")
)
sells = tx.filter(pl.col("seller_name").is_in(ship_names)).with_columns(
    pl.col("seller_name").alias("ship")
)


def _sum(df: pl.DataFrame, pred: pl.Expr, col: str, alias: str) -> pl.DataFrame:
    return df.filter(pred).group_by("ship").agg(pl.col(col).sum().alias(alias))


is_fuel = pl.col("commodity_id") == "nova_fuel"
is_maint = pl.col("commodity_id").is_in(list(MAINT_GOODS))
parts = [
    _sum(buys, is_fuel, "quantity", "fuel_bought_units"),
    _sum(buys, is_fuel, "total_amount", "fuel_spend"),
    _sum(sells, is_fuel, "quantity", "fuel_sold_units"),
    _sum(buys, is_maint, "total_amount", "maint_spend"),
    _sum(buys, ~is_fuel & ~is_maint, "total_amount", "cargo_buy"),
    _sum(sells, ~is_fuel, "total_amount", "cargo_sell"),
]
tank = ships.group_by("actor_name").agg(
    pl.col("fuel").first().alias("fuel_start"),
    pl.col("fuel").last().alias("fuel_end"),
    (pl.col("planet_name") != pl.col("planet_name").shift(1)).sum().alias("trips"),
    pl.col("money").last().alias("final_money"),
)
per_ship = tank.rename({"actor_name": "ship"})
for p in parts:
    per_ship = per_ship.join(p, on="ship", how="left")
per_ship = per_ship.fill_null(0).with_columns(
    (
        pl.col("fuel_bought_units")
        - pl.col("fuel_sold_units")
        + pl.col("fuel_start")
        - pl.col("fuel_end")
    ).alias("fuel_burned"),
    (pl.col("cargo_sell") - pl.col("cargo_buy")).alias("cargo_margin"),
)
per_ship = per_ship.with_columns(
    pl.when(pl.col("fuel_burned") > 0)
    .then((pl.col("cargo_margin") - pl.col("maint_spend")) / pl.col("fuel_burned"))
    .otherwise(None)
    .round(2)
    .alias("breakeven_fuel_px"),
    pl.when(pl.col("fuel_bought_units") > 0)
    .then(pl.col("fuel_spend") / pl.col("fuel_bought_units"))
    .otherwise(None)
    .round(2)
    .alias("paid_fuel_px"),
    pl.when(pl.col("trips") > 0)
    .then(pl.col("fuel_burned") / pl.col("trips"))
    .otherwise(None)
    .round(2)
    .alias("fuel_per_trip"),
    pl.when(pl.col("trips") > 0)
    .then((pl.col("cargo_margin") - pl.col("maint_spend")) / pl.col("trips"))
    .otherwise(None)
    .round(1)
    .alias("net_margin_per_trip"),
)
print("\n=== Q1/Q2: per-ship fuel economics ===")
print(
    per_ship.select(
        "ship",
        "trips",
        "fuel_burned",
        "fuel_per_trip",
        "cargo_margin",
        "maint_spend",
        "net_margin_per_trip",
        "breakeven_fuel_px",
        "paid_fuel_px",
        "final_money",
    ).sort("breakeven_fuel_px", nulls_last=True)
)

fleet = per_ship.select(
    pl.col("cargo_margin").sum(),
    pl.col("maint_spend").sum(),
    pl.col("fuel_burned").sum(),
    pl.col("fuel_spend").sum(),
    pl.col("trips").sum(),
)
cargo_margin = fleet["cargo_margin"][0]
maint = fleet["maint_spend"][0]
burned = fleet["fuel_burned"][0]
fleet_breakeven = (cargo_margin - maint) / burned if burned > 0 else float("nan")
print(
    f"\nFLEET: cargo_margin={cargo_margin}  maint={maint}  fuel_burned={burned}"
    f"  trips={fleet['trips'][0]}"
)
print(f"FLEET break-even fuel price (max sustainable WTP): {fleet_breakeven:.2f}")
if burned > 0:
    print(
        f"FLEET realized avg fuel price paid: {fleet['fuel_spend'][0] / max(1, per_ship['fuel_bought_units'].sum()):.2f}"
    )

# ---------------------------------------------------------------------------
# Q4: honest replacement cost of fuel per planet from attributes
# ---------------------------------------------------------------------------
print("\n=== Q4: honest fuel replacement cost by planet ===")
attrs_path = Path(r.run_path) / "planet_attributes.json"
if not attrs_path.exists():
    print(f"!! {attrs_path} missing (run with planet attributes enabled)")
else:
    attrs = json.loads(attrs_path.read_text())
    action_cost = GOVERNMENT_WAGE + 25 / TOOL_EXPECTED_LIFESPAN  # wage + tool wear
    rows = []
    for planet, a in attrs.items():
        ore_attr = a.get("nova_fuel_ore", 1.0)
        if ore_attr <= 0:
            cost = None
        else:
            # mine: 2 ore expected per action at attr (success effect);
            # refine: 4 ore -> 1 fuel, one more action.
            cost = round(4 * action_cost / (2 * ore_attr) + action_cost, 1)
        rows.append(
            {"planet": planet, "ore_attr": round(ore_attr, 2), "honest_fuel_cost": cost}
        )
    cost_df = pl.DataFrame(rows).sort("honest_fuel_cost", nulls_last=True)
    print(cost_df.head(10))
    best = cost_df.drop_nulls("honest_fuel_cost").head(1)
    if best.height:
        best_cost = best["honest_fuel_cost"][0]
        print(
            f"\nBest-planet honest fuel cost: {best_cost} ({best['planet'][0]},"
            f" attr {best['ore_attr'][0]})"
        )
        print(f"Fleet break-even WTP:          {fleet_breakeven:.2f}")
        if fleet_breakeven >= best_cost:
            print(
                "VERDICT: VIABLE — margins can pay honest cost; fix demand propagation."
            )
        else:
            gap = best_cost - fleet_breakeven
            print(
                f"VERDICT: STRUCTURALLY UNVIABLE at current margins — gap {gap:.1f}/unit."
                " Needs yield/burn/margin rebalance, not just signal plumbing."
            )

# ---------------------------------------------------------------------------
# Q5: what fuel actually traded at, galaxy-wide (context)
# ---------------------------------------------------------------------------
print("\n=== Q5: realized nova_fuel trades galaxy-wide ===")
ft = tx.filter(pl.col("commodity_id") == "nova_fuel")
if ft.height:
    print(
        ft.select(
            pl.len().alias("trades"),
            pl.col("quantity").sum().alias("units"),
            (pl.col("total_amount").sum() / pl.col("quantity").sum())
            .round(2)
            .alias("avg_px"),
            pl.col("price").min().alias("min_px"),
            pl.col("price").max().alias("max_px"),
        )
    )
else:
    print("no fuel trades at all this run")

print("\nDONE.")
