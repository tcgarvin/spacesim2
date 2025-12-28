"""Ship Trading Diagnosis

Quick diagnostic notebook to check if ships are trading and turning a profit.
"""

import marimo

__generated_with = "0.18.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import json
    import marimo as mo
    import polars as pl
    from pathlib import Path
    return Path, mo, os, pl


@app.cell
def _(mo, os):
    from spacesim2.analysis.loading import (
        get_run_path_with_fallback,
        NoRunsFoundError,
    )

    try:
        auto_run_path = get_run_path_with_fallback()
        run_path_str = str(auto_run_path)
        status_msg = f"✓ Using run: **{auto_run_path.name}**"

        if os.getenv("SPACESIM_RUN_PATH"):
            status_msg += " (from SPACESIM_RUN_PATH)"
        else:
            status_msg += " (auto-detected)"

    except NoRunsFoundError as e:
        run_path_str = ""
        status_msg = f"⚠️ **No runs found**\n\n```\n{str(e)}\n```"

    run_selector = mo.ui.text(
        value=run_path_str,
        label="Run Path (edit to override):",
        full_width=True,
    )

    mo.md(
        f"""
    # Ship Trading Diagnosis

    {status_msg}

    {run_selector}
    """
    )
    return (run_selector,)


@app.cell
def _(Path, mo, pl, run_selector):
    # Load data
    if not run_selector.value:
        mo.md("⚠️ No run path specified. Run `spacesim2 analyze` first.")
        txns = None
        actor_turns = None
    else:
        try:
            run_path = Path(run_selector.value)
            txns = pl.read_parquet(run_path / "market_transactions.parquet")
            actor_turns = pl.read_parquet(run_path / "actor_turns.parquet")
            mo.md(f"✓ Data loaded successfully")
        except Exception as e:
            mo.md(f"❌ Error loading data: {e}")
            txns = None
            actor_turns = None
    return actor_turns, txns


@app.cell
def _(mo):
    mo.md("""
    ## 1. Are Ships Being Logged?
    """)
    return


@app.cell
def _(actor_turns, mo, pl):
    if actor_turns is not None:
        unique_actors = actor_turns.select("actor_name").unique()
        ship_actors = unique_actors.filter(
            pl.col("actor_name").str.contains("(?i)ship|trader")
        )

        mo.md(
            f"""
        **Total Unique Actors Logged:** {len(unique_actors)}

        **Ships in Actor Log:** {len(ship_actors)}

        {ship_actors if len(ship_actors) > 0 else '⚠️ **No ships are being logged in actor_turns!**'}

        **Diagnosis:** Ships are trading but not being logged. Need to add ships to `data_logger.add_actor_to_log()`.
        """
        )
    else:
        mo.md("No data loaded")
    return


@app.cell
def _(mo):
    mo.md("""
    ## 2. Are Ships Trading?
    """)
    return


@app.cell
def _(mo, pl, txns):
    if txns is not None:
        # Find all transactions involving ships/traders
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

        mo.md(
            f"""
        **Ships Found in Transactions:** {len(all_ships)}

        {all_ships}

        **Total Ship Transactions:** {len(ship_txns)}

        {'✓ Ships are actively trading!' if len(ship_txns) > 0 else '❌ No ship trading activity found!'}
        """
        )
    else:
        mo.md("No data loaded")
    return (ship_txns,)


@app.cell
def _(mo):
    mo.md("""
    ## 3. Ship Trading Profitability
    """)
    return


@app.cell
def _(mo, pl, ship_txns):
    if ship_txns is not None and len(ship_txns) > 0:
        # Analyze each ship's trading
        for ship_name in ship_txns.filter(
            pl.col("buyer_name").str.contains("(?i)ship|trader")
            | pl.col("seller_name").str.contains("(?i)ship|trader")
        ).select(
            pl.when(pl.col("buyer_name").str.contains("(?i)ship|trader"))
            .then(pl.col("buyer_name"))
            .otherwise(pl.col("seller_name"))
            .alias("ship_name")
        ).unique().to_series().to_list():
            # Get buys and sells for this ship
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

            mo.md(
                f"""
            ### {ship_name}

            **Purchases:** {len(buys)} transactions, \${buy_total} total spent

            **Sales:** {len(sells)} transactions, \${sell_total} total revenue

            **Net Profit:** \${net_profit} {'✓ PROFITABLE' if net_profit > 0 else '❌ LOSING MONEY'}

            **Profit Margin:** {(net_profit / buy_total * 100) if buy_total > 0 else 0:.1f}%
            """
            )
    else:
        mo.md("No ship transaction data available")
    return


@app.cell
def _(mo):
    mo.md("""
    ## 4. Transaction Details
    """)
    return


@app.cell
def _(mo, ship_txns):
    if ship_txns is not None and len(ship_txns) > 0:
        # Show all transactions chronologically
        ship_txns_display = ship_txns.select(
            [
                "turn",
                "planet_name",
                "commodity_id",
                "buyer_name",
                "seller_name",
                "quantity",
                "price",
                "total_amount",
            ]
        ).sort("turn")

        mo.md(
            f"""
        ### All Ship Transactions (Total: {len(ship_txns_display)})

        {mo.ui.table(ship_txns_display, selection=None)}
        """
        )
    else:
        mo.md("No ship transactions to display")
    return


@app.cell
def _(mo):
    mo.md("""
    ## 5. Trading Patterns
    """)
    return


@app.cell
def _(mo, pl, ship_txns):
    if ship_txns is not None and len(ship_txns) > 0:
        # Analyze what commodities ships are trading
        ship_commodity_buys = (
            ship_txns.filter(pl.col("buyer_name").str.contains("(?i)ship|trader"))
            .group_by("commodity_id")
            .agg(
                [
                    pl.col("quantity").sum().alias("total_bought"),
                    pl.col("total_amount").sum().alias("total_spent"),
                    (pl.col("total_amount").sum() / pl.col("quantity").sum()).alias(
                        "avg_buy_price"
                    ),
                ]
            )
            .sort("total_spent", descending=True)
        )

        ship_commodity_sells = (
            ship_txns.filter(pl.col("seller_name").str.contains("(?i)ship|trader"))
            .group_by("commodity_id")
            .agg(
                [
                    pl.col("quantity").sum().alias("total_sold"),
                    pl.col("total_amount").sum().alias("total_revenue"),
                    (pl.col("total_amount").sum() / pl.col("quantity").sum()).alias(
                        "avg_sell_price"
                    ),
                ]
            )
            .sort("total_revenue", descending=True)
        )

        mo.md(
            f"""
        ### What Ships Are Buying

        {mo.ui.table(ship_commodity_buys, selection=None)}

        ### What Ships Are Selling

        {mo.ui.table(ship_commodity_sells, selection=None)}
        """
        )
    else:
        mo.md("No ship transaction data available")
    return


@app.cell
def _(mo):
    mo.md("""
    ## 6. Trade Routes
    """)
    return


@app.cell
def _(mo, pl, ship_txns):
    if ship_txns is not None and len(ship_txns) > 0:
        # Analyze which planets ships are trading at
        trade_locations = (
            ship_txns.group_by("planet_name")
            .agg([pl.len().alias("num_transactions")])
            .sort("num_transactions", descending=True)
        )

        mo.md(
            f"""
        ### Trading Locations

        {mo.ui.table(trade_locations, selection=None)}
        """
        )
    else:
        mo.md("No ship transaction data available")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Summary & Diagnosis

    **Key Findings:**

    1. Ships exist and are trading in the simulation
    2. Ships are NOT being tracked in actor_turns (not added to data logger)
    3. Ship profitability can only be analyzed through market_transactions

    **Recommendations:**

    1. Add ships to the data logger in simulation initialization:
       ```python
       for ship in ships:
           simulation.data_logger.add_actor_to_log(ship)
       ```

    2. This will enable full economic tracking including:
       - Money over time
       - Inventory changes
       - Reserved money for orders

    3. Currently can only see indirect trading activity, not full economic picture
    """)
    return


if __name__ == "__main__":
    app.run()
