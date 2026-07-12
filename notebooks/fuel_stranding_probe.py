"""Tier-1 probe: trading-ship fuel stranding.

Quantifies the "ships get stuck without fuel and spiral" problem.

Run against the latest exported run (must be exported WITH --log-all-actors so
ship per-turn state lands in actor_turns.parquet; ship fuel is the `nova_fuel`
quantity carried in the ship's cargo/inventory):

    uv run spacesim2 dev analyze notebooks/fuel_stranding_probe.py

Output contract: prints small aggregates only; saves any figures to tmp/.

Answers 5 questions:
  1. Do ships get fuel-stranded? how many, how early, do they recover?
  2. Where do they strand? (planet nova_fuel_ore attr + local fuel market)
  3. The spiral: per-turn timeline for example stranded ships.
  4. Fuel price geography + would a supply run clear bid>ask+fuel+15%?
  5. Macro impact: lost trade volume, healthy vs stranded ships, ship decay.
"""

import json
from pathlib import Path

import polars as pl

from spacesim2.analysis.loading import load_run

# --- tunables ---------------------------------------------------------------
STRAND_STREAK = 20  # turns on same planet to count as "parked"
LOW_FUEL = 5  # nova_fuel units at/below which a ship likely can't make a round trip
MARGIN = 0.15  # TraderBrain arbitrage margin (bid > ask + fuel + 15%)

r = load_run()
print(f"run: {r.simulation_id}")

# --- planet nova_fuel_ore attributes ---------------------------------------
attrs_path = Path(r.run_path) / "planet_attributes.json"
fuel_ore = {}
if attrs_path.exists():
    with open(attrs_path) as f:
        pa = json.load(f)
    fuel_ore = {p: v.get("nova_fuel_ore", float("nan")) for p, v in pa.items()}
    print("\n=== planet nova_fuel_ore attribute (mining possible where high) ===")
    for p, v in sorted(fuel_ore.items(), key=lambda kv: -kv[1]):
        tag = "FUEL-RICH" if v >= 0.5 else "fuel-poor"
        print(f"  {p:10s} {v:5.2f}  {tag}")

# --- ship per-turn frame ----------------------------------------------------
at = r.actor_turns
ships = at.filter(pl.col("actor_name").str.starts_with("Trader-"))
n_ships = ships["actor_name"].n_unique()
turn_max = int(ships["turn"].max())
print(f"\nships logged: {n_ships}   turns: {ships['turn'].min()}..{turn_max}")

if n_ships == 0:
    print("\n!! No ships in actor_turns. Re-run the sim WITH --log-all-actors.")
    raise SystemExit(0)


def _fuel(js: str) -> int:
    try:
        return int(json.loads(js).get("nova_fuel", 0))
    except (json.JSONDecodeError, TypeError):
        return 0


def _cargo_units(js: str) -> int:
    """Non-fuel cargo units on board."""
    try:
        d = json.loads(js)
    except (json.JSONDecodeError, TypeError):
        return 0
    return int(sum(v for k, v in d.items() if k != "nova_fuel"))


ships = ships.with_columns(
    pl.col("inventory_json").map_elements(_fuel, return_dtype=pl.Int64).alias("fuel"),
    pl.col("inventory_json")
    .map_elements(_cargo_units, return_dtype=pl.Int64)
    .alias("cargo_units"),
).sort(["actor_name", "turn"])

# per-turn movement: did the ship's planet change vs previous logged turn?
ships = ships.with_columns(
    (pl.col("planet_name") != pl.col("planet_name").shift(1))
    .over("actor_name")
    .fill_null(True)
    .alias("moved")
)

# ---------------------------------------------------------------------------
# Q1 + Q5: mobility, low-fuel, and permanent stranding per ship
# ---------------------------------------------------------------------------
print("\n=== Q1/Q5: per-ship mobility & fuel ===")
per_ship_rows = []
strand_events = []  # (ship, strand_turn, planet, fuel_at_strand)
for name, g in ships.group_by("actor_name", maintain_order=True):
    name = name[0] if isinstance(name, tuple) else name
    g = g.sort("turn")
    turns = g["turn"].to_list()
    planets = g["planet_name"].to_list()
    fuels = g["fuel"].to_list()
    moves = int(g["moved"].sum()) - 1  # first row always counts as "moved"
    moves = max(moves, 0)
    # find permanent-park onset: last index where planet changed; if the tail
    # after it is >= STRAND_STREAK turns of the same planet with low fuel -> stranded.
    last_change_idx = 0
    for i in range(1, len(planets)):
        if planets[i] != planets[i - 1]:
            last_change_idx = i
    tail_len = len(planets) - last_change_idx
    tail_planet = planets[last_change_idx]
    tail_fuel_end = fuels[-1]
    stranded = tail_len >= STRAND_STREAK and tail_fuel_end <= LOW_FUEL
    # fuel at the moment it went idle (start of the final parked stretch)
    fuel_at_park = fuels[last_change_idx]
    strand_turn = turns[last_change_idx] if stranded else None
    if stranded:
        strand_events.append((name, strand_turn, tail_planet, fuel_at_park))
    per_ship_rows.append(
        {
            "ship": name,
            "moves": moves,
            "final_planet": planets[-1],
            "final_fuel": tail_fuel_end,
            "min_fuel": min(fuels),
            "turns_low_fuel": int(sum(1 for x in fuels if x <= LOW_FUEL)),
            "final_park_len": tail_len,
            "stranded": stranded,
            "strand_turn": strand_turn,
        }
    )

per_ship = pl.DataFrame(per_ship_rows).sort("moves")
print(per_ship)

n_str = int(per_ship["stranded"].sum())
print(
    f"\nstranded ships (parked >={STRAND_STREAK} turns to end w/ fuel<={LOW_FUEL}): "
    f"{n_str}/{n_ships}"
)
if strand_events:
    print("strand onset turns:", sorted(t for _, t, _, _ in strand_events))
    print(
        "mean moves - stranded:",
        round(per_ship.filter(pl.col("stranded"))["moves"].mean() or 0, 1),
        " healthy:",
        round(per_ship.filter(~pl.col("stranded"))["moves"].mean() or 0, 1),
    )

# recovery check: after a ship first hits low fuel, does it ever move again?
print("\n=== Q1: recovery — after first hitting low fuel, moves afterward ===")
rec_rows = []
for name, g in ships.group_by("actor_name", maintain_order=True):
    name = name[0] if isinstance(name, tuple) else name
    g = g.sort("turn")
    fuels = g["fuel"].to_list()
    planets = g["planet_name"].to_list()
    first_low = next((i for i, x in enumerate(fuels) if x <= LOW_FUEL), None)
    if first_low is None:
        rec_rows.append({"ship": name, "first_low_turn": None, "moves_after_low": None})
        continue
    moves_after = sum(
        1 for i in range(first_low + 1, len(planets)) if planets[i] != planets[i - 1]
    )
    rec_rows.append(
        {
            "ship": name,
            "first_low_turn": g["turn"].to_list()[first_low],
            "moves_after_low": moves_after,
        }
    )
print(pl.DataFrame(rec_rows).sort("first_low_turn"))

# ---------------------------------------------------------------------------
# Q2: where do they strand + local fuel market on those planets
# ---------------------------------------------------------------------------
print("\n=== Q2: stranding planets vs nova_fuel_ore + local fuel market ===")
snaps = r.market_snapshots
fuel_snaps = snaps.filter(pl.col("commodity_id") == "nova_fuel")
fuel_mkt = fuel_snaps.group_by("planet_name").agg(
    pl.col("avg_price").mean().round(2).alias("mean_price"),
    pl.col("volume").sum().alias("tot_volume"),
    pl.col("num_sell_orders").mean().round(2).alias("mean_asks"),
    pl.col("num_buy_orders").mean().round(2).alias("mean_bids"),
    pl.col("best_ask")
    .filter(pl.col("best_ask") > 0)
    .mean()
    .round(2)
    .alias("mean_best_ask"),
    pl.col("best_bid")
    .filter(pl.col("best_bid") > 0)
    .mean()
    .round(2)
    .alias("mean_best_bid"),
)
fuel_mkt = fuel_mkt.with_columns(
    pl.col("planet_name")
    .map_elements(lambda p: fuel_ore.get(p, float("nan")), return_dtype=pl.Float64)
    .alias("nova_fuel_ore_attr")
).sort("nova_fuel_ore_attr", descending=True)
print(fuel_mkt)

if strand_events:
    strand_planets = (
        pl.DataFrame({"planet": [p for _, _, p, _ in strand_events]})["planet"]
        .value_counts()
        .sort("count", descending=True)
    )
    print("\nstranding location counts:")
    print(strand_planets)

# nova_fuel production: who ever SELLS fuel, and on which planet?
print("\n=== Q2b: nova_fuel sellers by planet (is fuel produced/sold there?) ===")
tx = r.market_transactions
fuel_tx = tx.filter(pl.col("commodity_id") == "nova_fuel")
if fuel_tx.height:
    by_planet = (
        fuel_tx.group_by("planet_name")
        .agg(
            pl.col("quantity").sum().alias("units_sold"),
            pl.col("price").mean().round(2).alias("mean_price"),
            pl.col("seller_name").n_unique().alias("n_sellers"),
        )
        .sort("units_sold", descending=True)
    )
    print(by_planet)
else:
    print("  NO nova_fuel transactions at all.")

# ---------------------------------------------------------------------------
# Q3: the spiral — per-turn timeline for up to 2 example stranded ships
# ---------------------------------------------------------------------------
print("\n=== Q3: spiral timelines (sampled every ~25 turns) ===")
example_ships = [s[0] for s in strand_events[:2]]
if not example_ships:
    # fall back to the two least-mobile ships
    example_ships = per_ship.sort("moves")["ship"].to_list()[:2]
for name in example_ships:
    g = ships.filter(pl.col("actor_name") == name).sort("turn")
    sample = g.filter((pl.col("turn") % 25 == 0) | (pl.col("turn") == turn_max))
    print(f"\n-- {name} --")
    print(
        sample.select(["turn", "planet_name", "fuel", "cargo_units", "money", "moved"])
    )

# ---------------------------------------------------------------------------
# Q4: fuel geography + would a supply run clear bid>ask+fuel+15%?
# ---------------------------------------------------------------------------
print("\n=== Q4: fuel price geography + arbitrage viability ===")
if fuel_mkt.height:
    rich = fuel_mkt.sort("nova_fuel_ore_attr", descending=True).head(1)
    poor = fuel_mkt.sort("nova_fuel_ore_attr").head(1)
    rp = rich["mean_price"][0]
    pp = poor["mean_price"][0]
    print(f"  fuel-rich planet {rich['planet_name'][0]}: mean fuel price {rp}")
    print(f"  fuel-poor planet {poor['planet_name'][0]}: mean fuel price {pp}")
    if rp and pp:
        print(
            f"  spread poor-rich: {round(pp - rp, 2)}  "
            f"({round((pp - rp) / rp * 100, 1) if rp else 0}%)"
        )
    # A delivery run: buy fuel at rich planet's ask, spend ~1 fuel/trip, must
    # clear bid > ask + fuel_cost + 15%. Report the min poor-planet bid needed.
    rich_ask = rich["mean_best_ask"][0] or rp
    if rich_ask:
        fuel_trip_cost = rich_ask  # ~1 unit fuel per short hop, valued at origin
        need_bid = (rich_ask + fuel_trip_cost) * (1 + MARGIN)
        print(
            f"  to arbitrage: poor-planet bid must exceed "
            f"~{round(need_bid, 2)} (ask {round(rich_ask, 2)} + fuel + {int(MARGIN * 100)}%)"
        )
        print(f"  actual mean best_bid on poor planet: {poor['mean_best_bid'][0]}")

# ---------------------------------------------------------------------------
# Q5: macro — ship trade volume over time + effective active ship count
# ---------------------------------------------------------------------------
print("\n=== Q5: macro impact — ship trading over time ===")
ship_names = set(ships["actor_name"].unique().to_list())
ship_tx = tx.filter(
    pl.col("buyer_name").is_in(ship_names) | pl.col("seller_name").is_in(ship_names)
)
# bucket into 100-turn windows
if ship_tx.height:
    ship_tx = ship_tx.with_columns((pl.col("turn") // 100 * 100).alias("window"))
    vol = (
        ship_tx.group_by("window")
        .agg(
            pl.len().alias("n_trades"),
            pl.col("total_amount").sum().alias("gross_value"),
        )
        .sort("window")
    )
    print("ship trades per 100-turn window:")
    print(vol)

# effective active ships: how many distinct ships MOVED in each 100-turn window
mv = ships.filter(pl.col("moved") & (pl.col("turn") > 1))
if mv.height:
    mv = mv.with_columns((pl.col("turn") // 100 * 100).alias("window"))
    active = (
        mv.group_by("window")
        .agg(pl.col("actor_name").n_unique().alias("ships_that_moved"))
        .sort("window")
    )
    print(f"\nships that moved per 100-turn window (of {n_ships} total):")
    print(active)

# healthy vs stranded: trades per ship over whole run
print("\n=== Q5b: trades per ship, stranded vs healthy ===")
trade_counts = []
stranded_set = set(per_ship.filter(pl.col("stranded"))["ship"].to_list())
for name in sorted(ship_names):
    n = ship_tx.filter(
        (pl.col("buyer_name") == name) | (pl.col("seller_name") == name)
    ).height
    trade_counts.append(
        {
            "ship": name,
            "trades": n,
            "stranded": name in stranded_set,
        }
    )
tc = pl.DataFrame(trade_counts)
print(
    tc.group_by("stranded").agg(
        pl.col("trades").mean().round(1).alias("mean_trades"),
        pl.col("trades").sum().alias("total_trades"),
        pl.len().alias("n_ships"),
    )
)
print("\nDONE.")
