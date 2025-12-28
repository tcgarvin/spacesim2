"""Analyze a specific ship's trading strategy."""

import sys
from pathlib import Path

import polars as pl


def analyze_specific_trader(run_path: Path, ship_name: str) -> None:
    """Analyze a specific ship's trading patterns.

    Args:
        run_path: Path to simulation run data
        ship_name: Name of ship to analyze
    """
    # Load data
    txns = pl.read_parquet(run_path / "market_transactions.parquet")
    actor_turns = pl.read_parquet(run_path / "actor_turns.parquet")

    print("=" * 80)
    print(f"DETAILED ANALYSIS: {ship_name}")
    print("=" * 80)

    # Get ship's transactions
    buys = txns.filter(pl.col("buyer_name") == ship_name).sort("turn")
    sells = txns.filter(pl.col("seller_name") == ship_name).sort("turn")

    print("\nPRICE ANALYSIS")
    print("-" * 80)

    if len(buys) > 0:
        avg_buy = buys.select(
            (pl.col("total_amount").sum() / pl.col("quantity").sum())
        ).item()
        print(f"Average buy price: ${avg_buy:.2f}")

    if len(sells) > 0:
        avg_sell = sells.select(
            (pl.col("total_amount").sum() / pl.col("quantity").sum())
        ).item()
        print(f"Average sell price: ${avg_sell:.2f}")

    if len(buys) > 0 and len(sells) > 0:
        margin = avg_sell - avg_buy
        print(f"Price margin: ${margin:.2f} ({margin/avg_buy*100:.1f}%)")

    print("\n\nTRADING LOCATIONS")
    print("-" * 80)

    if len(buys) > 0:
        buy_planets = buys.group_by("planet_name").agg(
            [
                pl.len().alias("txns"),
                pl.col("total_amount").sum().alias("spent"),
                (pl.col("total_amount").sum() / pl.col("quantity").sum()).alias(
                    "avg_price"
                ),
            ]
        ).sort("spent", descending=True)

        print("\nWhere ship BUYS:")
        for row in buy_planets.rows():
            planet, count, spent, avg_price = row
            print(f"  {planet:<20}: {count:2d} txns, ${spent:6.0f} spent @ avg ${avg_price:.2f}")

    if len(sells) > 0:
        sell_planets = sells.group_by("planet_name").agg(
            [
                pl.len().alias("txns"),
                pl.col("total_amount").sum().alias("revenue"),
                (pl.col("total_amount").sum() / pl.col("quantity").sum()).alias(
                    "avg_price"
                ),
            ]
        ).sort("revenue", descending=True)

        print("\nWhere ship SELLS:")
        for row in sell_planets.rows():
            planet, count, revenue, avg_price = row
            print(
                f"  {planet:<20}: {count:2d} txns, ${revenue:6.0f} revenue @ avg ${avg_price:.2f}"
            )

    print("\n\nTRADE ROUTE PAIRS")
    print("-" * 80)

    # Show which planets have best price differentials
    if len(buy_planets) > 0 and len(sell_planets) > 0:
        print("\nApparent strategy:")
        best_buy_planet = buy_planets.rows()[0]
        best_sell_planet = sell_planets.rows()[0]

        print(
            f"  Buy from: {best_buy_planet[0]} @ avg ${best_buy_planet[3]:.2f} ({best_buy_planet[1]} txns)"
        )
        print(
            f"  Sell to:  {best_sell_planet[0]} @ avg ${best_sell_planet[3]:.2f} ({best_sell_planet[1]} txns)"
        )
        print(
            f"  Arbitrage margin: ${best_sell_planet[3] - best_buy_planet[3]:.2f} per unit"
        )

    print("\n\nTRANSACTION TIMELINE")
    print("-" * 80)

    all_txns = pl.concat(
        [
            buys.select(
                ["turn", "planet_name", "commodity_id", "quantity", "price", "total_amount"]
            ).with_columns([pl.lit("BUY").alias("type")]),
            sells.select(
                ["turn", "planet_name", "commodity_id", "quantity", "price", "total_amount"]
            ).with_columns([pl.lit("SELL").alias("type")]),
        ]
    ).sort("turn")

    print("\nAll transactions (showing trade pattern):")
    print(
        f"{'Turn':<6} {'Type':<5} {'Planet':<20} {'Commodity':<12} {'Qty':>4} {'Price':>6} {'Total':>7}"
    )
    print("-" * 80)
    for row in all_txns.rows():
        turn, planet, commodity, qty, price, total, txn_type = row
        print(
            f"{turn:<6} {txn_type:<5} {planet:<20} {commodity:<12} {qty:>4} ${price:>5} ${total:>6}"
        )

    print("\n\nMONEY OVER TIME")
    print("-" * 80)

    ship_data = actor_turns.filter(pl.col("actor_name") == ship_name)
    if len(ship_data) > 0:
        print("\nMoney progression (showing key turns):")
        print(f"{'Turn':<6} {'Money':>8} {'Change':>8}")
        print("-" * 80)

        prev_money = None
        for i in range(0, len(ship_data), 10):  # Show every 10th turn
            row = ship_data.row(i)
            turn = row[1]
            money = row[4]
            change = money - prev_money if prev_money is not None else 0
            print(f"{turn:<6} ${money:>7} ${change:>+7}")
            prev_money = money

        # Show final turn
        last_row = ship_data.row(-1)
        turn = last_row[1]
        money = last_row[4]
        change = money - prev_money if prev_money is not None else 0
        print(f"{turn:<6} ${money:>7} ${change:>+7}")

    print()
    print("=" * 80)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_trader.py <run_path> [ship_name]")
        sys.exit(1)

    run_path = Path(sys.argv[1])
    ship_name = sys.argv[2] if len(sys.argv) > 2 else "Trader-4"

    analyze_specific_trader(run_path, ship_name)
