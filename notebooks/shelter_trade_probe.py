"""Tier-1 probe: does ship trade even out shelter across planets?

Hypothesis (user): trading ships move simple_building_materials from planets
where it's easy to make (high `wood` attribute) to planets where it's hard,
giving the hard planets a consistent supply.

Checks, per planet:
  * wood availability (planet attribute) -- the supply-side driver
  * shelter drive health/debt over the last 50 turns -- the outcome
  * local building-material production vs ship import/export
"""

import json
from pathlib import Path

import polars as pl

from spacesim2.analysis.loading import load_run

r = load_run()
print(f"run: {r.simulation_id}")

attrs = json.loads((Path(r.run_path) / "planet_attributes.json").read_text())
wood = {p: a["wood"] for p, a in attrs.items()}

LAST = 50
max_turn = int(r.actor_drives["turn"].max())
cutoff = max_turn - LAST

# --- shelter outcome per planet (join drives to actor planet) ---------------
planet_of = r.actor_turns.select("turn", "actor_id", "planet_name")
shelter = (
    r.actor_drives.filter(
        (pl.col("drive_name") == "shelter") & (pl.col("turn") >= cutoff)
    )
    .join(planet_of, on=["turn", "actor_id"], how="left")
    .group_by("planet_name")
    .agg(
        pl.col("health").mean().round(3).alias("shelter_health"),
        pl.col("debt").mean().round(3).alias("shelter_debt"),
    )
)

# --- building-material flow per planet --------------------------------------
sbm = r.market_transactions.filter(
    (pl.col("commodity_id") == "simple_building_materials") & (pl.col("turn") >= cutoff)
)
is_ship = pl.col("buyer_name").str.starts_with("Trader-")
ship_buy = (
    sbm.filter(pl.col("buyer_name").str.starts_with("Trader-"))
    .group_by("planet_name")
    .agg(pl.col("quantity").sum().alias("ship_bought"))
)
ship_sell = (
    sbm.filter(pl.col("seller_name").str.starts_with("Trader-"))
    .group_by("planet_name")
    .agg(pl.col("quantity").sum().alias("ship_sold"))
)
local_vol = sbm.group_by("planet_name").agg(
    pl.col("quantity").sum().alias("sbm_total_vol")
)

# --- price per planet -------------------------------------------------------
price = (
    r.market_snapshots.filter(
        (pl.col("commodity_id") == "simple_building_materials")
        & (pl.col("turn") >= cutoff)
    )
    .group_by("planet_name")
    .agg(pl.col("avg_price").mean().round(1).alias("sbm_price"))
)

wood_df = pl.DataFrame(
    {"planet_name": list(wood), "wood_attr": [round(v, 3) for v in wood.values()]}
)

table = (
    wood_df.join(shelter, on="planet_name", how="left")
    .join(price, on="planet_name", how="left")
    .join(local_vol, on="planet_name", how="left")
    .join(ship_buy, on="planet_name", how="left")
    .join(ship_sell, on="planet_name", how="left")
    .fill_null(0)
    .sort("wood_attr")
)
print(f"\n=== per-planet, last {LAST} turns (sorted by wood availability) ===")
print(table)

# net ship flow: positive = ships net-import building materials to this planet
table2 = table.with_columns(
    (pl.col("ship_sold") - pl.col("ship_bought")).alias("net_ship_import")
)
print("\n=== net ship import of building materials (sold here - bought here) ===")
print(table2.select("planet_name", "wood_attr", "shelter_health", "net_ship_import"))

total_ship_sbm = int(
    sbm.filter(pl.col("buyer_name").str.starts_with("Trader-"))["quantity"].sum() or 0
)
total_sbm = int(sbm["quantity"].sum() or 0)
print(
    f"\nbuilding-material volume last {LAST}t: total={total_sbm}, "
    f"ship-bought={total_ship_sbm} ({100 * total_ship_sbm / max(total_sbm, 1):.1f}% ship-mediated)"
)
