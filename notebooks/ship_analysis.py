"""Comprehensive Ship Trading Analysis

Combines profitability, price analysis, and route analysis for all ships.
"""

import marimo

__generated_with = "0.18.1"
app = marimo.App(width="medium")

with app.setup:
    # Initialization code that runs before all other cells
    pass


@app.cell
def _():
    import os
    import marimo as mo
    import polars as pl
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from pathlib import Path
    return Path, mo, os, pl, px


@app.cell
def _(mo, txns_data):
    mo.ui.table(txns_data)
    return


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
    # Ship Trading Analysis

    {status_msg}

    {run_selector}
    """
    )
    return (run_selector,)


@app.cell
def _(Path, mo, pl, run_selector):
    # Load data
    if run_selector.value:
        try:
            run_path_loaded = Path(run_selector.value)
            txns_data = pl.read_parquet(run_path_loaded / "market_transactions.parquet")
            actor_turns_data = pl.read_parquet(run_path_loaded / "actor_turns.parquet")
            load_msg = mo.md(f"✓ Data loaded successfully")
        except Exception as e:
            txns_data = None
            actor_turns_data = None
            load_msg = mo.md(f"❌ Error loading data: {e}")
    else:
        txns_data = None
        actor_turns_data = None
        load_msg = mo.md("⚠️ No run path specified. Run `spacesim2 analyze` first.")

    load_msg
    return actor_turns_data, txns_data


@app.cell
def _(mo):
    mo.md("""
    ## Executive Summary
    """)
    return


@app.cell
def _(actor_turns_data, mo, pl, txns_data):
    if txns_data is not None and actor_turns_data is not None:
        # Get ship transactions
        all_ship_txns = txns_data.filter(
            pl.col("buyer_name").str.contains("(?i)ship|trader")
            | pl.col("seller_name").str.contains("(?i)ship|trader")
        )

        # Get unique ships
        buyers_list = all_ship_txns.filter(
            pl.col("buyer_name").str.contains("(?i)ship|trader")
        ).select("buyer_name")
        sellers_list = all_ship_txns.filter(
            pl.col("seller_name").str.contains("(?i)ship|trader")
        ).select("seller_name")

        unique_ships = pl.concat(
            [
                buyers_list.rename({"buyer_name": "ship_name"}),
                sellers_list.rename({"seller_name": "ship_name"}),
            ]
        ).unique()

        total_ships = len(unique_ships)
        total_transactions = len(all_ship_txns)

        # Calculate aggregate profit
        aggregate_profit = 0
        ships_with_profit = 0

        for ship_iter in unique_ships.to_series().to_list():
            ship_buys_iter = all_ship_txns.filter(pl.col("buyer_name") == ship_iter)
            ship_sells_iter = all_ship_txns.filter(pl.col("seller_name") == ship_iter)

            buy_sum = (
                ship_buys_iter.select(pl.col("total_amount").sum()).item()
                if len(ship_buys_iter) > 0
                else 0
            )
            sell_sum = (
                ship_sells_iter.select(pl.col("total_amount").sum()).item()
                if len(ship_sells_iter) > 0
                else 0
            )
            profit = sell_sum - buy_sum
            aggregate_profit += profit

            if profit > 0:
                ships_with_profit += 1

        profit_status = "✓ PROFITABLE" if aggregate_profit > 0 else "❌ LOSING MONEY"

        summary_output = mo.md(
            f"""
        **Ships Found:** {total_ships}

        **Total Transactions:** {total_transactions}

        **Profitable Ships:** {ships_with_profit} / {total_ships}

        **Total Trading Profit:** ${aggregate_profit:.0f} {profit_status}
        """
        )
    else:
        total_ships = 0
        unique_ships = None
        all_ship_txns = None
        summary_output = mo.md("No data loaded")

    summary_output
    return all_ship_txns, total_ships, unique_ships


@app.cell
def _(mo):
    mo.md("""
    ## Individual Ship Performance
    """)
    return


@app.cell
def _(actor_turns_data, all_ship_txns, mo, pl, unique_ships):
    if unique_ships is not None and len(unique_ships) > 0:
        # Build summary table
        summary_rows = []

        for ship_name_iter in unique_ships.to_series().to_list():
            buys_data = all_ship_txns.filter(pl.col("buyer_name") == ship_name_iter)
            sells_data = all_ship_txns.filter(pl.col("seller_name") == ship_name_iter)

            buy_amount = (
                buys_data.select(pl.col("total_amount").sum()).item()
                if len(buys_data) > 0
                else 0
            )
            sell_amount = (
                sells_data.select(pl.col("total_amount").sum()).item()
                if len(sells_data) > 0
                else 0
            )
            trading_profit = sell_amount - buy_amount
            profit_margin = (trading_profit / buy_amount * 100) if buy_amount > 0 else 0

            # Get money change
            ship_actor_data = actor_turns_data.filter(
                pl.col("actor_name") == ship_name_iter
            )
            if len(ship_actor_data) > 0:
                money_start = ship_actor_data.select(pl.col("money").first()).item()
                money_end = ship_actor_data.select(pl.col("money").last()).item()
                money_delta = money_end - money_start
                return_on_investment = (
                    (money_delta / money_start * 100) if money_start > 0 else 0
                )
            else:
                money_start = None
                money_end = None
                money_delta = None
                return_on_investment = None

            summary_rows.append(
                {
                    "Ship": ship_name_iter,
                    "Purchases": len(buys_data),
                    "Sales": len(sells_data),
                    "Trading Profit": trading_profit,
                    "Margin %": profit_margin,
                    "Start $": money_start,
                    "End $": money_end,
                    "ROI %": return_on_investment,
                }
            )

        summary_table = pl.DataFrame(summary_rows).sort(
            "Trading Profit", descending=True
        )

        table_output = mo.ui.table(summary_table, selection=None)
    else:
        summary_table = None
        table_output = "No ships found"

    table_output
    return (summary_table,)


@app.cell
def _(mo):
    mo.md("""
    ## Ship Money Over Time
    """)
    return


@app.cell
def _(actor_turns_data, pl, px, total_ships):
    if actor_turns_data is not None and total_ships > 0:
        all_ship_actor_data = actor_turns_data.filter(
            pl.col("actor_name").str.contains("(?i)ship|trader")
        )

        if len(all_ship_actor_data) > 0:
            fig_money_time = px.line(
                all_ship_actor_data.to_pandas(),
                x="turn",
                y="money",
                color="actor_name",
                title="Ship Money Over Time",
                labels={"money": "Money ($)", "turn": "Turn", "actor_name": "Ship"},
            )
            fig_money_time.update_layout(hovermode="x unified")
            money_chart = fig_money_time
        else:
            money_chart = "Ships not tracked. Use --log-actor-types ship"
    else:
        money_chart = "No ship data"

    money_chart
    return


@app.cell
def _(mo):
    mo.md("""
    ## Trading Profit Analysis
    """)
    return


@app.cell
def _(px, summary_table, total_ships):
    if summary_table is not None and total_ships > 0:
        fig_profit_bar = px.bar(
            summary_table.to_pandas(),
            x="Ship",
            y="Trading Profit",
            title="Trading Profit by Ship",
            color="Trading Profit",
            color_continuous_scale=["red", "yellow", "green"],
        )
        fig_profit_bar.add_hline(y=0, line_dash="dash", line_color="black")
        profit_chart = fig_profit_bar
    else:
        profit_chart = "No data"

    profit_chart
    return


@app.cell
def _(mo):
    mo.md("""
    ## Detailed Ship Analysis

    Select a ship:
    """)
    return


@app.cell
def _(mo, total_ships, unique_ships):
    if unique_ships is not None and total_ships > 0:
        ship_list = unique_ships.to_series().to_list()
        selected_ship_dropdown = mo.ui.dropdown(
            options=ship_list, value=ship_list[0], label="Ship:"
        )
        ship_dropdown_output = selected_ship_dropdown
    else:
        selected_ship_dropdown = None
        ship_dropdown_output = "No ships"

    ship_dropdown_output
    return (selected_ship_dropdown,)


@app.cell(hide_code=True)
def _(all_ship_txns, mo, pl, selected_ship_dropdown):
    if selected_ship_dropdown is not None and selected_ship_dropdown.value:
        current_ship = selected_ship_dropdown.value

        # Get ship's transactions
        current_buys = all_ship_txns.filter(
            pl.col("buyer_name") == current_ship
        ).sort("turn")
        current_sells = all_ship_txns.filter(
            pl.col("seller_name") == current_ship
        ).sort("turn")

        # Price analysis
        if len(current_buys) > 0:
            current_avg_buy = current_buys.select(
                (pl.col("total_amount").sum() / pl.col("quantity").sum())
            ).item()
        else:
            current_avg_buy = 0

        if len(current_sells) > 0:
            current_avg_sell = current_sells.select(
                (pl.col("total_amount").sum() / pl.col("quantity").sum())
            ).item()
        else:
            current_avg_sell = 0

        current_margin = current_avg_sell - current_avg_buy
        current_margin_pct = (
            (current_margin / current_avg_buy * 100) if current_avg_buy > 0 else 0
        )

        ship_detail_output = mo.md(
            f"""
        ### {current_ship}

        **Average Buy:** ${current_avg_buy:.2f}
        **Average Sell:** ${current_avg_sell:.2f}
        **Margin:** ${current_margin:.2f} ({current_margin_pct:.1f}%)
        """
        )
    else:
        current_ship = None
        current_buys = None
        current_sells = None
        ship_detail_output = ""

    ship_detail_output
    return current_buys, current_sells, current_ship


@app.cell
def _(current_buys, current_sells, mo, pl):
    if current_buys is not None and current_sells is not None:
        # Trading locations
        if len(current_buys) > 0:
            buy_planets = current_buys.group_by("planet_name").agg(
                [
                    pl.len().alias("txns"),
                    pl.col("total_amount").sum().alias("spent"),
                    (
                        pl.col("total_amount").sum() / pl.col("quantity").sum()
                    ).alias("avg_price"),
                ]
            ).sort("spent", descending=True)
        else:
            buy_planets = None

        if len(current_sells) > 0:
            sell_planets = current_sells.group_by("planet_name").agg(
                [
                    pl.len().alias("txns"),
                    pl.col("total_amount").sum().alias("revenue"),
                    (
                        pl.col("total_amount").sum() / pl.col("quantity").sum()
                    ).alias("avg_price"),
                ]
            ).sort("revenue", descending=True)
        else:
            sell_planets = None

        locations_msg = "**Trading Locations:**\n\n"

        if buy_planets is not None and len(buy_planets) > 0:
            best_buy_row = buy_planets.row(0)
            locations_msg += f"Buy: {best_buy_row[0]} ({best_buy_row[1]} txns @ ${best_buy_row[3]:.2f})\n\n"
        else:
            locations_msg += "No purchases\n\n"

        if sell_planets is not None and len(sell_planets) > 0:
            best_sell_row = sell_planets.row(0)
            locations_msg += f"Sell: {best_sell_row[0]} ({best_sell_row[1]} txns @ ${best_sell_row[3]:.2f})\n\n"

            if buy_planets is not None and len(buy_planets) > 0:
                arb_margin = best_sell_row[3] - best_buy_row[3]
                locations_msg += f"**Arbitrage:** ${arb_margin:.2f}/unit\n\n"
        else:
            locations_msg += "No sales"

        locations_output = mo.md(locations_msg)
    else:
        buy_planets = None
        sell_planets = None
        locations_output = ""

    locations_output
    return buy_planets, sell_planets


@app.cell
def _(buy_planets, mo):
    buy_header = mo.md("#### Purchases") if buy_planets is not None else ""
    buy_header
    return


@app.cell
def _(buy_planets, mo):
    buy_table = mo.ui.table(buy_planets, selection=None) if buy_planets is not None else ""
    buy_table
    return


@app.cell
def _(mo, sell_planets):
    sell_header = mo.md("#### Sales") if sell_planets is not None else ""
    sell_header
    return


@app.cell
def _(mo, sell_planets):
    sell_table = mo.ui.table(sell_planets, selection=None) if sell_planets is not None else ""
    sell_table
    return


@app.cell
def _(mo):
    mo.md("""
    ### Transaction Timeline
    """)
    return


@app.cell
def _(current_buys, current_sells, mo, pl):
    if current_buys is not None and current_sells is not None:
        timeline_txns = pl.concat(
            [
                current_buys.select(
                    ["turn", "planet_name", "commodity_id", "quantity", "price", "total_amount"]
                ).with_columns([pl.lit("BUY").alias("type")]),
                current_sells.select(
                    ["turn", "planet_name", "commodity_id", "quantity", "price", "total_amount"]
                ).with_columns([pl.lit("SELL").alias("type")]),
            ]
        ).sort("turn")

        timeline_output = mo.ui.table(timeline_txns, selection=None)
    else:
        timeline_output = ""

    timeline_output
    return


@app.cell
def _(actor_turns_data, current_ship, mo, pl, px):
    if current_ship is not None:
        ship_money_history = actor_turns_data.filter(
            pl.col("actor_name") == current_ship
        )

        if len(ship_money_history) > 0:
            fig_ship_money_history = px.line(
                ship_money_history.to_pandas(),
                x="turn",
                y="money",
                title=f"{current_ship} Money",
            )
            ship_money_output = fig_ship_money_history
        else:
            ship_money_output = mo.md("Ship not logged")
    else:
        ship_money_output = ""

    ship_money_output
    return


@app.cell
def _(mo):
    mo.md("""
    ## Market Price Comparison
    """)
    return


@app.cell
def _(mo, pl, txns_data):
    if txns_data is not None:
        food_market_txns = txns_data.filter(pl.col("commodity_id") == "food")

        market_prices = food_market_txns.group_by("planet_name").agg(
            [
                pl.col("price").mean().alias("avg_price"),
                pl.col("price").min().alias("min_price"),
                pl.col("price").max().alias("max_price"),
                pl.len().alias("transactions"),
            ]
        ).sort("avg_price")

        price_table_output = mo.ui.table(market_prices, selection=None)
    else:
        market_prices = None
        price_table_output = ""

    price_table_output
    return (market_prices,)


@app.cell
def _(market_prices, px):
    if market_prices is not None:
        fig_market_prices = px.bar(
            market_prices.to_pandas(),
            x="planet_name",
            y="avg_price",
            title="Food Prices by Planet",
        )
        price_chart_output = fig_market_prices
    else:
        price_chart_output = ""

    price_chart_output
    return


@app.cell
def _(market_prices, mo):
    if market_prices is not None and len(market_prices) >= 2:
        cheap_planet = market_prices.row(0)
        expensive_planet = market_prices.row(-1)

        price_gap = expensive_planet[1] - cheap_planet[1]
        gap_pct = (price_gap / cheap_planet[1] * 100) if cheap_planet[1] > 0 else 0

        arbitrage_output = mo.md(
            f"""
        ### Arbitrage Opportunity

        **Cheapest:** {cheap_planet[0]} @ ${cheap_planet[1]:.2f}
        **Most Expensive:** {expensive_planet[0]} @ ${expensive_planet[1]:.2f}
        **Spread:** ${price_gap:.2f} ({gap_pct:.1f}%)
        """
        )
    else:
        arbitrage_output = ""

    arbitrage_output
    return


if __name__ == "__main__":
    app.run()
