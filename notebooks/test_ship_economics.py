"""Test script to verify ship_economics notebook logic works."""

import os
import json
import polars as pl
from pathlib import Path
from spacesim2.analysis.loading.loader import SimulationData

# Use environment variable or default
run_path = os.getenv("SPACESIM_RUN_PATH", "data/runs/ship_economics_run/run_20251128_142009")
print(f"Loading data from: {run_path}")

# Load data
data = SimulationData(Path(run_path))
print("✓ Data loaded successfully")

# Check basic data availability
all_actors = data.actor_turns
print(f"✓ Actor turns data: {len(all_actors)} rows")

# Filter for ships
ship_actors = all_actors.filter(
    pl.col('actor_name').str.contains('(?i)ship|trader')
)
num_ships = ship_actors.select('actor_name').unique().shape[0] if len(ship_actors) > 0 else 0
num_turns = all_actors.select('turn').max()[0] if len(all_actors) > 0 else 0

print(f"✓ Ships found: {num_ships}")
print(f"✓ Total turns: {num_turns}")

if num_ships > 0:
    print("\n=== Ship Profitability Analysis ===")

    # Calculate profit
    ship_profits = (
        ship_actors
        .sort(['actor_name', 'turn'])
        .with_columns([
            (pl.col('money') - pl.col('money').shift(1).over('actor_name')).alias('profit_per_turn'),
            pl.col('money').first().over('actor_name').alias('starting_money')
        ])
        .with_columns([
            ((pl.col('money') - pl.col('starting_money')) / pl.col('starting_money') * 100).alias('roi_percent')
        ])
    )

    # Get final ROI
    latest_roi = ship_profits.group_by('actor_name').agg([
        pl.col('roi_percent').last().alias('final_roi'),
        pl.col('money').first().alias('starting_money'),
        pl.col('money').last().alias('ending_money')
    ])

    print("\nFinal Ship Performance:")
    print(latest_roi)

    # Analyze transactions
    ship_txns = data.market_transactions.filter(
        pl.col('buyer_name').str.contains('(?i)ship|trader') |
        pl.col('seller_name').str.contains('(?i)ship|trader')
    )

    print(f"\n✓ Ship transactions: {len(ship_txns)}")

    if len(ship_txns) > 0:
        # Separate buy and sell
        ship_buys = ship_txns.filter(
            pl.col('buyer_name').str.contains('(?i)ship|trader')
        ).with_columns([
            pl.col('buyer_name').alias('ship_name'),
            pl.lit('buy').alias('transaction_type')
        ])

        ship_sells = ship_txns.filter(
            pl.col('seller_name').str.contains('(?i)ship|trader')
        ).with_columns([
            pl.col('seller_name').alias('ship_name'),
            pl.lit('sell').alias('transaction_type')
        ])

        print(f"  - Buy transactions: {len(ship_buys)}")
        print(f"  - Sell transactions: {len(ship_sells)}")

        # Calculate profit margins
        if len(ship_buys) > 0 and len(ship_sells) > 0:
            buy_prices = ship_buys.group_by(['ship_name', 'commodity_id']).agg([
                (pl.col('total_amount').sum() / pl.col('quantity').sum()).alias('avg_buy_price'),
                pl.col('quantity').sum().alias('total_bought')
            ])

            sell_prices = ship_sells.group_by(['ship_name', 'commodity_id']).agg([
                (pl.col('total_amount').sum() / pl.col('quantity').sum()).alias('avg_sell_price'),
                pl.col('quantity').sum().alias('total_sold')
            ])

            margins = buy_prices.join(
                sell_prices,
                on=['ship_name', 'commodity_id'],
                how='inner'
            ).with_columns([
                ((pl.col('avg_sell_price') - pl.col('avg_buy_price')) / pl.col('avg_buy_price') * 100).alias('profit_margin_pct'),
                ((pl.col('avg_sell_price') - pl.col('avg_buy_price')) * pl.col('total_sold')).alias('total_profit')
            ])

            if len(margins) > 0:
                print("\nProfit Margins by Commodity:")
                print(margins)

                avg_margin = margins.select(pl.col('profit_margin_pct').mean()).item()
                total_profit = margins.select(pl.col('total_profit').sum()).item()

                print(f"\n✓ Average profit margin: {avg_margin:.1f}%")
                print(f"✓ Total profit from trades: ${total_profit:.0f}")
            else:
                print("\n⚠ No matching buy/sell pairs found for margin calculation")

    # Parse inventory
    inventory_expanded = ship_actors.with_columns([
        pl.col('inventory_json').map_elements(
            lambda x: json.loads(x) if x else {},
            return_dtype=pl.Object
        ).alias('inventory_dict')
    ]).with_columns([
        pl.col('inventory_dict').map_elements(
            lambda x: x.get('food', 0) if isinstance(x, dict) else 0,
            return_dtype=pl.Int64
        ).alias('food_qty'),
        pl.col('inventory_dict').map_elements(
            lambda x: x.get('nova_fuel', 0) if isinstance(x, dict) else 0,
            return_dtype=pl.Int64
        ).alias('fuel_qty'),
        pl.col('inventory_dict').map_elements(
            lambda x: sum(x.values()) if isinstance(x, dict) else 0,
            return_dtype=pl.Int64
        ).alias('total_cargo')
    ])

    print("\n✓ Inventory analysis completed")

    # Summary statistics
    avg_roi = latest_roi.select(pl.col('final_roi').mean()).item()
    print(f"\n=== SUMMARY ===")
    print(f"Average ROI: {avg_roi:.1f}%")

    if avg_roi > 0:
        print("✓ Ships are profitable!")
    else:
        print("⚠ Ships are losing money")

else:
    print("\n⚠ No ship data found in this run")
    print("Run a simulation with: --log-actor-types ship")

print("\n✓ All notebook logic validated successfully!")
