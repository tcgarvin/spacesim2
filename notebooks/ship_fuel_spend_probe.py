"""Tier-1 probe: where does ship fuel money actually go?

Follow-up to ship_pnl_probe: fleet fuel_buy dwarfs cargo gross margin. This
decomposes fuel flows in UNITS and prices, plus journey/trade cadence.

    SPACESIM_RUN_PATH=data/runs/<run> uv run spacesim2 dev analyze notebooks/ship_fuel_spend_probe.py
"""

import json

import polars as pl

from spacesim2.analysis.loading import load_run

r = load_run()
at = r.actor_turns
tx = r.market_transactions
ships = at.filter(pl.col("actor_name").str.starts_with("Trader-"))
ship_names = sorted(set(ships["actor_name"].unique().to_list()))


def _fuel(js: str) -> int:
    try:
        return int(json.loads(js).get("nova_fuel", 0))
    except (json.JSONDecodeError, TypeError):
        return 0


ships = ships.with_columns(
    pl.col("inventory_json").map_elements(_fuel, return_dtype=pl.Int64).alias("fuel")
).sort(["actor_name", "turn"])

# --- fuel units bought/sold per ship, mean prices ---------------------------
fb = tx.filter(
    (pl.col("commodity_id") == "nova_fuel") & pl.col("buyer_name").is_in(ship_names)
)
fs = tx.filter(
    (pl.col("commodity_id") == "nova_fuel") & pl.col("seller_name").is_in(ship_names)
)
print("=== fuel bought per ship ===")
print(
    fb.group_by("buyer_name")
    .agg(
        pl.col("quantity").sum().alias("units"),
        pl.col("total_amount").sum().alias("spend"),
        (pl.col("total_amount").sum() / pl.col("quantity").sum())
        .round(2)
        .alias("avg_px"),
    )
    .sort("buyer_name")
)
print("\n=== fuel bought by planet (price geography) ===")
print(
    fb.group_by("planet_name")
    .agg(
        pl.col("quantity").sum().alias("units"),
        (pl.col("total_amount").sum() / pl.col("quantity").sum())
        .round(2)
        .alias("avg_px"),
    )
    .sort("units", descending=True)
)
print("\n=== fuel sold per ship (price + counterparty type) ===")
fs = fs.with_columns(
    pl.col("buyer_name").str.starts_with("Trader-").alias("to_other_ship")
)
print(
    fs.group_by("seller_name", "to_other_ship")
    .agg(
        pl.col("quantity").sum().alias("units"),
        (pl.col("total_amount").sum() / pl.col("quantity").sum())
        .round(2)
        .alias("avg_px"),
    )
    .sort("seller_name")
)

# --- units balance: bought+sold vs burned ------------------------------------
print("\n=== per-ship fuel unit balance (bought - sold - final_hold ~= burned) ===")
rows = []
for name in ship_names:
    g = ships.filter(pl.col("actor_name") == name).sort("turn")
    bought = int(fb.filter(pl.col("buyer_name") == name)["quantity"].sum() or 0)
    sold = int(fs.filter(pl.col("seller_name") == name)["quantity"].sum() or 0)
    start = int(g["fuel"].first())
    end = int(g["fuel"].last())
    burned = start + bought - sold - end
    moves = int((g["planet_name"] != g["planet_name"].shift(1)).fill_null(False).sum())
    rows.append(
        {
            "ship": name,
            "start_fuel": start,
            "bought": bought,
            "sold": sold,
            "end_fuel": end,
            "burned(travel+maint)": burned,
            "journeys": moves,
        }
    )
bal = pl.DataFrame(rows)
print(bal)
print("\nfleet units:", bal.select(pl.exclude("ship")).sum().to_dicts()[0])

# --- cadence: cargo trades per 100-turn window --------------------------------
print("\n=== cargo (ex-fuel) ship trades per 100-turn window ===")
cargo_tx = tx.filter(
    (pl.col("commodity_id") != "nova_fuel")
    & (pl.col("buyer_name").is_in(ship_names) | pl.col("seller_name").is_in(ship_names))
).with_columns((pl.col("turn") // 100 * 100).alias("window"))
print(
    cargo_tx.group_by("window")
    .agg(pl.len().alias("n_tx"), pl.col("total_amount").sum().alias("value"))
    .sort("window")
)

# --- money over time (sampled) ------------------------------------------------
print("\n=== fleet money by 100-turn window (mean over ships) ===")
print(
    ships.with_columns((pl.col("turn") // 100 * 100).alias("window"))
    .group_by("window")
    .agg(
        pl.col("money").mean().round(1).alias("mean_money"),
        pl.col("money").min().alias("min_money"),
        pl.col("fuel").mean().round(1).alias("mean_fuel"),
    )
    .sort("window")
)

# --- fuel price context: market mean ask by planet ----------------------------
print("\n=== nova_fuel market mean best_ask / best_bid by planet ===")
snaps = r.market_snapshots.filter(pl.col("commodity_id") == "nova_fuel")
print(
    snaps.group_by("planet_name")
    .agg(
        pl.col("best_ask").filter(pl.col("best_ask") > 0).mean().round(2).alias("ask"),
        pl.col("best_bid").filter(pl.col("best_bid") > 0).mean().round(2).alias("bid"),
        pl.col("volume").sum().alias("vol"),
    )
    .sort("planet_name")
)
print("\nDONE.")
