"""Quick ship trading profitability summary."""

import sys
from pathlib import Path

import polars as pl


def analyze_ship_trading(run_path: Path) -> None:
    """Analyze ship trading and print summary.

    Args:
        run_path: Path to simulation run data
    """
    # Load data
    txns = pl.read_parquet(run_path / "market_transactions.parquet")
    actor_turns = pl.read_parquet(run_path / "actor_turns.parquet")

    print("=" * 80)
    print("SHIP TRADING PROFITABILITY ANALYSIS")
    print("=" * 80)
    print()

    # Check if ships are logged
    print("1. SHIP LOGGING STATUS")
    print("-" * 80)
    unique_actors = actor_turns.select("actor_name").unique()
    ship_actors = unique_actors.filter(
        pl.col("actor_name").str.contains("(?i)ship|trader")
    )
    print(f"Total actors logged: {len(unique_actors)}")
    print(f"Ships logged: {len(ship_actors)}")

    if len(ship_actors) > 0:
        print("✓ Ships are being logged!")
        print(f"  Ships: {', '.join(ship_actors.to_series().to_list())}")
    else:
        print("⚠️  Ships are NOT being logged in actor_turns!")
        print(
            "   To fix: Use --log-actor-types ship when running spacesim2 analyze"
        )

    print()

    # Check trading activity
    print("2. SHIP TRADING ACTIVITY")
    print("-" * 80)

    ship_txns = txns.filter(
        pl.col("buyer_name").str.contains("(?i)ship|trader")
        | pl.col("seller_name").str.contains("(?i)ship|trader")
    )

    # Get unique ship names
    ship_buyers = ship_txns.filter(
        pl.col("buyer_name").str.contains("(?i)ship|trader")
    ).select("buyer_name")
    ship_sellers = ship_txns.filter(
        pl.col("seller_name").str.contains("(?i)ship|trader")
    ).select("seller_name")

    all_ships = pl.concat(
        [
            ship_buyers.rename({"buyer_name": "ship_name"}),
            ship_sellers.rename({"seller_name": "ship_name"}),
        ]
    ).unique()

    print(f"Ships found in transactions: {len(all_ships)}")
    if len(all_ships) > 0:
        print(f"  Ships: {', '.join(all_ships.to_series().to_list())}")
        print(f"Total ship transactions: {len(ship_txns)}")
        print("✓ Ships are actively trading!")
    else:
        print("❌ No ship trading activity found!")
        return

    print()

    # Analyze profitability for each ship
    print("3. SHIP PROFITABILITY")
    print("-" * 80)

    for ship_name in all_ships.to_series().to_list():
        print(f"\n{ship_name}:")
        print("-" * 40)

        # Get buys and sells
        buys = ship_txns.filter(pl.col("buyer_name") == ship_name)
        sells = ship_txns.filter(pl.col("seller_name") == ship_name)

        buy_total = (
            buys.select(pl.col("total_amount").sum()).item() if len(buys) > 0 else 0
        )
        sell_total = (
            sells.select(pl.col("total_amount").sum()).item()
            if len(sells) > 0
            else 0
        )
        net_profit = sell_total - buy_total

        print(f"  Purchases:    {len(buys):3d} transactions, ${buy_total:8.0f} spent")
        print(
            f"  Sales:        {len(sells):3d} transactions, ${sell_total:8.0f} revenue"
        )
        print(f"  Net Profit:   ${net_profit:8.0f}", end="")

        if net_profit > 0:
            print(" ✓ PROFITABLE")
            margin = (net_profit / buy_total * 100) if buy_total > 0 else 0
            print(f"  Profit Margin: {margin:.1f}%")
        elif net_profit < 0:
            print(" ❌ LOSING MONEY")
        else:
            print(" ⚠️  BREAK EVEN")

        # Show what they're trading
        if len(buys) > 0:
            buy_commodities = (
                buys.group_by("commodity_id")
                .agg([pl.col("quantity").sum().alias("qty")])
                .sort("qty", descending=True)
            )
            print(f"  Buying: {', '.join([f'{row[0]} ({row[1]})' for row in buy_commodities.rows()])}")

        if len(sells) > 0:
            sell_commodities = (
                sells.group_by("commodity_id")
                .agg([pl.col("quantity").sum().alias("qty")])
                .sort("qty", descending=True)
            )
            print(
                f"  Selling: {', '.join([f'{row[0]} ({row[1]})' for row in sell_commodities.rows()])}"
            )

        # Show money over time if ship is logged
        if len(ship_actors) > 0 and ship_name in ship_actors.to_series().to_list():
            ship_data = actor_turns.filter(pl.col("actor_name") == ship_name)
            if len(ship_data) > 0:
                starting_money = ship_data.select(pl.col("money").first()).item()
                ending_money = ship_data.select(pl.col("money").last()).item()
                money_change = ending_money - starting_money
                print(f"\n  Money Tracking:")
                print(f"    Starting: ${starting_money:8.0f}")
                print(f"    Ending:   ${ending_money:8.0f}")
                print(
                    f"    Change:   ${money_change:+8.0f} ({money_change / starting_money * 100:+.1f}%)"
                )

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    total_profit = sum(
        [
            (
                ship_txns.filter(pl.col("seller_name") == ship_name)
                .select(pl.col("total_amount").sum())
                .item()
                if len(ship_txns.filter(pl.col("seller_name") == ship_name)) > 0
                else 0
            )
            - (
                ship_txns.filter(pl.col("buyer_name") == ship_name)
                .select(pl.col("total_amount").sum())
                .item()
                if len(ship_txns.filter(pl.col("buyer_name") == ship_name)) > 0
                else 0
            )
            for ship_name in all_ships.to_series().to_list()
        ]
    )

    if total_profit > 0:
        print("✓ Ships are profitable overall!")
        print(f"  Total profit across all ships: ${total_profit:.0f}")
    elif total_profit < 0:
        print("❌ Ships are losing money overall!")
        print(f"  Total loss across all ships: ${total_profit:.0f}")
    else:
        print("⚠️  Ships are breaking even")

    if len(ship_actors) == 0:
        print("\n⚠️  NOTE: Ships are not being logged, so money tracking is incomplete.")
        print(
            "   Run: uv run spacesim2 analyze --turns 100 --log-actor-types ship"
        )

    print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_path = Path(sys.argv[1])
    else:
        # Auto-detect most recent run
        from spacesim2.analysis.loading import get_run_path_with_fallback

        run_path = get_run_path_with_fallback()
        print(f"Using most recent run: {run_path.name}\n")

    analyze_ship_trading(run_path)
