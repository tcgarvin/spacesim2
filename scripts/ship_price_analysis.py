"""Detailed ship price analysis to diagnose trading losses."""

import sys
from pathlib import Path

import polars as pl


def analyze_ship_prices(run_path: Path) -> None:
    """Analyze ship trading prices to understand losses.

    Args:
        run_path: Path to simulation run data
    """
    # Load data
    txns = pl.read_parquet(run_path / "market_transactions.parquet")

    print("=" * 80)
    print("SHIP PRICE ANALYSIS - DIAGNOSING LOSSES")
    print("=" * 80)
    print()

    # Get ship transactions
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

    for ship_name in all_ships.to_series().to_list():
        print(f"SHIP: {ship_name}")
        print("=" * 80)

        # Get buy and sell transactions
        buys = ship_txns.filter(pl.col("buyer_name") == ship_name).sort("turn")
        sells = ship_txns.filter(pl.col("seller_name") == ship_name).sort("turn")

        print("\nPRICE STATISTICS")
        print("-" * 80)

        # Calculate average buy and sell prices
        for commodity in ["food", "nova_fuel"]:
            commodity_buys = buys.filter(pl.col("commodity_id") == commodity)
            commodity_sells = sells.filter(pl.col("commodity_id") == commodity)

            if len(commodity_buys) > 0 or len(commodity_sells) > 0:
                print(f"\n{commodity.upper()}:")

                if len(commodity_buys) > 0:
                    avg_buy_price = commodity_buys.select(
                        (pl.col("total_amount").sum() / pl.col("quantity").sum())
                    ).item()
                    min_buy_price = commodity_buys.select(pl.col("price").min()).item()
                    max_buy_price = commodity_buys.select(pl.col("price").max()).item()
                    total_bought = commodity_buys.select(
                        pl.col("quantity").sum()
                    ).item()

                    print(
                        f"  Buying:  {total_bought:3d} units @ avg ${avg_buy_price:.2f} "
                        f"(range: ${min_buy_price}-${max_buy_price})"
                    )

                if len(commodity_sells) > 0:
                    avg_sell_price = commodity_sells.select(
                        (pl.col("total_amount").sum() / pl.col("quantity").sum())
                    ).item()
                    min_sell_price = commodity_sells.select(
                        pl.col("price").min()
                    ).item()
                    max_sell_price = commodity_sells.select(
                        pl.col("price").max()
                    ).item()
                    total_sold = commodity_sells.select(pl.col("quantity").sum()).item()

                    print(
                        f"  Selling: {total_sold:3d} units @ avg ${avg_sell_price:.2f} "
                        f"(range: ${min_sell_price}-${max_sell_price})"
                    )

                if len(commodity_buys) > 0 and len(commodity_sells) > 0:
                    margin = avg_sell_price - avg_buy_price
                    margin_pct = (margin / avg_buy_price * 100) if avg_buy_price > 0 else 0
                    status = "✓ PROFITABLE" if margin > 0 else "❌ LOSS"
                    print(f"  Margin:  ${margin:+.2f} ({margin_pct:+.1f}%) {status}")

        # Analyze trade routes
        print("\n\nTRADE ROUTE ANALYSIS")
        print("-" * 80)

        # Create a chronological view of buys and sells
        all_txns = (
            pl.concat(
                [
                    buys.select(
                        ["turn", "planet_name", "commodity_id", "quantity", "price", "total_amount"]
                    ).with_columns([pl.lit("BUY").alias("type")]),
                    sells.select(
                        ["turn", "planet_name", "commodity_id", "quantity", "price", "total_amount"]
                    ).with_columns([pl.lit("SELL").alias("type")]),
                ]
            )
            .sort("turn")
            .head(20)
        )

        print(
            "\nFirst 20 transactions (showing BUY/SELL pattern):"
        )
        print(
            f"{'Turn':<6} {'Type':<5} {'Planet':<15} {'Commodity':<12} {'Qty':>4} {'Price':>6} {'Total':>7}"
        )
        print("-" * 80)
        for row in all_txns.rows():
            turn, planet, commodity, qty, price, total, txn_type = row
            print(
                f"{turn:<6} {txn_type:<5} {planet:<15} {commodity:<12} {qty:>4} ${price:>5} ${total:>6}"
            )

        # Look for patterns - is ship buying and selling at same planet?
        print("\n\nTRADING LOCATIONS")
        print("-" * 80)

        buy_planets = buys.group_by("planet_name").agg(
            [pl.len().alias("transactions"), pl.col("total_amount").sum().alias("spent")]
        )
        sell_planets = sells.group_by("planet_name").agg(
            [
                pl.len().alias("transactions"),
                pl.col("total_amount").sum().alias("revenue"),
            ]
        )

        print("\nPurchase locations:")
        for row in buy_planets.rows():
            planet, txns, spent = row
            print(f"  {planet:<15}: {txns:3d} transactions, ${spent:6.0f} spent")

        print("\nSale locations:")
        for row in sell_planets.rows():
            planet, txns, revenue = row
            print(f"  {planet:<15}: {txns:3d} transactions, ${revenue:6.0f} revenue")

        # Check if ship is trading at same planet (bad) or different planets (good)
        print("\n\nDIAGNOSIS")
        print("-" * 80)

        buy_planet_set = set(buy_planets.select("planet_name").to_series().to_list())
        sell_planet_set = set(sell_planets.select("planet_name").to_series().to_list())

        if buy_planet_set == sell_planet_set:
            print("⚠️  PROBLEM: Ship is buying and selling at the SAME planets!")
            print(
                "   This means the ship is competing with itself and not doing spatial arbitrage."
            )
        else:
            print("✓ Ship is trading at different planets (spatial arbitrage possible)")

        # Check timing - is ship buying high and selling low?
        avg_buy = (
            buys.select(pl.col("price").mean()).item() if len(buys) > 0 else 0
        )
        avg_sell = (
            sells.select(pl.col("price").mean()).item() if len(sells) > 0 else 0
        )

        if avg_sell < avg_buy:
            print(
                f"\n❌ PROBLEM: Average sell price (${avg_sell:.2f}) < average buy price (${avg_buy:.2f})"
            )
            print("   Ship is buying expensive and selling cheap!")
        else:
            print(
                f"\n✓ Average sell price (${avg_sell:.2f}) > average buy price (${avg_buy:.2f})"
            )

        # Check market prices to see if there's arbitrage opportunity
        print("\n\nMARKET PRICE COMPARISON")
        print("-" * 80)

        # Get all market prices for food to see arbitrage opportunities
        all_food_txns = txns.filter(pl.col("commodity_id") == "food")

        planet_prices = all_food_txns.group_by("planet_name").agg(
            [
                pl.col("price").mean().alias("avg_price"),
                pl.col("price").min().alias("min_price"),
                pl.col("price").max().alias("max_price"),
            ]
        )

        print("\nFood prices by planet (overall market):")
        for row in planet_prices.rows():
            planet, avg, min_p, max_p = row
            print(f"  {planet:<15}: avg ${avg:5.2f}, range ${min_p:2.0f}-${max_p:2.0f}")

        print()

    print("=" * 80)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_path = Path(sys.argv[1])
    else:
        # Auto-detect most recent run
        from spacesim2.analysis.loading import get_run_path_with_fallback

        run_path = get_run_path_with_fallback()
        print(f"Using most recent run: {run_path.name}\n")

    analyze_ship_prices(run_path)
