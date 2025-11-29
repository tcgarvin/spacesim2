"""Ship Economic Activity and Profitability Analysis

This notebook analyzes the economic performance of trading ships, including:
- Money and profit over time
- Trade route effectiveness
- Transaction profitability
- Cargo utilization
- Fuel efficiency
"""

import marimo

__generated_with = "0.18.1"
app = marimo.App(width="medium")


@app.cell
def __():
    import os
    import json
    import marimo as mo
    import polars as pl
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from spacesim2.analysis.loading.loader import SimulationData
    from pathlib import Path
    return mo, os, pl, px, go, make_subplots, SimulationData, Path, json


@app.cell
def __(mo, os, Path):
    # Load run path from environment or use default
    default_run = "data/runs/test_run"
    run_path_str = os.getenv("SPACESIM_RUN_PATH", default_run)

    # UI to select different runs if needed
    run_selector = mo.ui.text(
        value=run_path_str,
        label="Run Path:",
        full_width=True
    )
    mo.md(f"# Ship Economics Analysis\n\n{run_selector}")
    return run_path_str, run_selector, default_run


@app.cell
def __(SimulationData, Path, run_selector):
    # Load data
    data = SimulationData(Path(run_selector.value))
    return data,


@app.cell
def __(mo, data, pl):
    # Filter for ships only (ships typically have "Ship" in their name)
    all_actors = data.actor_turns

    # Identify ships - look for actors with "Ship" in name or check their transaction patterns
    ship_actors = all_actors.filter(
        pl.col('actor_name').str.contains('(?i)ship|trader')
    )

    num_ships = ship_actors.select('actor_name').unique().shape[0] if len(ship_actors) > 0 else 0
    num_turns = all_actors.select('turn').max()[0] if len(all_actors) > 0 else 0

    mo.md(f"""
    ## Simulation Overview
    - **Total Turns:** {num_turns}
    - **Ships Tracked:** {num_ships}
    - **Total Transactions:** {len(data.market_transactions)}

    {'⚠️ No ships found in this run data!' if num_ships == 0 else f'✓ Analyzing {num_ships} ships'}
    """)
    return all_actors, ship_actors, num_ships, num_turns


@app.cell
def __(mo):
    mo.md("## Ship Profitability Over Time")


@app.cell
def __(ship_actors, px, num_ships):
    # Plot money over time for each ship
    if num_ships > 0:
        fig_money = px.line(
            ship_actors.to_pandas(),
            x='turn',
            y='money',
            color='actor_name',
            title='Ship Money Over Time',
            labels={'money': 'Money ($)', 'turn': 'Turn', 'actor_name': 'Ship'}
        )
        fig_money.update_layout(hovermode='x unified')
        fig_money
    else:
        "No ship data available. Ships need to be added to simulation.data_logger to be tracked."


@app.cell
def __(mo):
    mo.md("## Profit Calculation & Performance Metrics")


@app.cell
def __(ship_actors, pl, px, num_ships):
    # Calculate profit (change in money) for each ship
    if num_ships > 0:
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

        # Plot profit per turn
        fig_profit = px.line(
            ship_profits.filter(pl.col('profit_per_turn').is_not_null()).to_pandas(),
            x='turn',
            y='profit_per_turn',
            color='actor_name',
            title='Ship Profit Per Turn',
            labels={'profit_per_turn': 'Profit ($)', 'turn': 'Turn', 'actor_name': 'Ship'}
        )
        fig_profit.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Break Even")
        fig_profit.update_layout(hovermode='x unified')
        fig_profit
    else:
        ship_profits = None
        "No ship data available"

    return ship_profits,


@app.cell
def __(ship_profits, px, num_ships):
    # Plot cumulative ROI
    if num_ships > 0 and ship_profits is not None:
        latest_roi = ship_profits.group_by('actor_name').agg([
            pl.col('roi_percent').last().alias('final_roi')
        ])

        fig_roi = px.line(
            ship_profits.to_pandas(),
            x='turn',
            y='roi_percent',
            color='actor_name',
            title='Ship Return on Investment (ROI)',
            labels={'roi_percent': 'ROI (%)', 'turn': 'Turn', 'actor_name': 'Ship'}
        )
        fig_roi.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Break Even")
        fig_roi.update_layout(hovermode='x unified')
        fig_roi
    else:
        latest_roi = None
        "No ship data available"

    return latest_roi,


@app.cell
def __(mo):
    mo.md("## Trading Activity Analysis")


@app.cell
def __(data, pl, num_ships):
    # Analyze ship transactions
    if num_ships > 0:
        ship_txns = data.market_transactions.filter(
            pl.col('buyer_name').str.contains('(?i)ship|trader') |
            pl.col('seller_name').str.contains('(?i)ship|trader')
        )

        # Separate buy and sell transactions
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

        all_ship_txns = pl.concat([
            ship_buys.select(['turn', 'ship_name', 'commodity_id', 'quantity', 'price', 'total_amount', 'transaction_type', 'planet_name']),
            ship_sells.select(['turn', 'ship_name', 'commodity_id', 'quantity', 'price', 'total_amount', 'transaction_type', 'planet_name'])
        ])
    else:
        ship_txns = None
        all_ship_txns = None

    return ship_txns, ship_buys, ship_sells, all_ship_txns


@app.cell
def __(all_ship_txns, px, num_ships):
    # Plot transaction volume over time
    if num_ships > 0 and all_ship_txns is not None:
        txn_volume = all_ship_txns.group_by(['turn', 'transaction_type']).agg([
            pl.col('quantity').sum().alias('total_quantity'),
            pl.col('total_amount').sum().alias('total_value')
        ])

        fig_volume = px.bar(
            txn_volume.to_pandas(),
            x='turn',
            y='total_quantity',
            color='transaction_type',
            title='Ship Trading Volume Over Time',
            labels={'total_quantity': 'Quantity', 'turn': 'Turn', 'transaction_type': 'Type'},
            barmode='group'
        )
        fig_volume
    else:
        "No ship transaction data available"


@app.cell
def __(mo):
    mo.md("## Trade Route Analysis")


@app.cell
def __(all_ship_txns, pl, num_ships):
    # Analyze trade routes (planet pairs)
    if num_ships > 0 and all_ship_txns is not None:
        # Create a sequence of planets visited
        routes = (
            all_ship_txns
            .sort(['ship_name', 'turn'])
            .with_columns([
                pl.col('planet_name').shift(-1).over('ship_name').alias('next_planet')
            ])
            .filter(
                (pl.col('planet_name') != pl.col('next_planet')) &
                pl.col('next_planet').is_not_null()
            )
            .group_by(['ship_name', 'planet_name', 'next_planet']).agg([
                pl.count().alias('trips'),
            ])
            .sort('trips', descending=True)
        )
        routes
    else:
        routes = None
        "No route data available"

    return routes,


@app.cell
def __(mo):
    mo.md("## Profit Margin Analysis")


@app.cell
def __(ship_buys, ship_sells, pl, num_ships):
    # Calculate profit margins on trades
    if num_ships > 0 and ship_buys is not None and ship_sells is not None:
        # Match buys to sells by commodity and ship
        # Calculate average buy and sell prices per commodity per ship
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

        margins
    else:
        margins = None
        "No transaction data available to calculate margins"

    return buy_prices, sell_prices, margins


@app.cell
def __(margins, px, num_ships):
    # Visualize profit margins
    if num_ships > 0 and margins is not None and len(margins) > 0:
        fig_margins = px.bar(
            margins.to_pandas(),
            x='commodity_id',
            y='profit_margin_pct',
            color='ship_name',
            title='Profit Margins by Commodity',
            labels={'profit_margin_pct': 'Profit Margin (%)', 'commodity_id': 'Commodity', 'ship_name': 'Ship'},
            barmode='group'
        )
        fig_margins.add_hline(y=0, line_dash="dash", line_color="red")
        fig_margins.add_hline(y=20, line_dash="dash", line_color="green", annotation_text="20% Target")
        fig_margins
    else:
        "No margin data available"


@app.cell
def __(mo):
    mo.md("## Inventory Analysis")


@app.cell
def __(ship_actors, pl, json, num_ships):
    # Parse inventory JSON and track cargo over time
    if num_ships > 0:
        # Extract inventory data
        inventory_data = ship_actors.with_columns([
            pl.col('inventory_json').map_elements(
                lambda x: json.loads(x) if x else {},
                return_dtype=pl.Object
            ).alias('inventory_dict')
        ])

        # Extract specific commodities
        inventory_expanded = inventory_data.with_columns([
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

        inventory_expanded.select(['turn', 'actor_name', 'food_qty', 'fuel_qty', 'total_cargo'])
    else:
        inventory_expanded = None
        "No ship inventory data available"

    return inventory_data, inventory_expanded


@app.cell
def __(inventory_expanded, make_subplots, go, num_ships):
    # Plot cargo utilization over time
    if num_ships > 0 and inventory_expanded is not None:
        # Create subplot with food and fuel on separate y-axes
        ship_names = inventory_expanded.select('actor_name').unique().to_series().to_list()

        if len(ship_names) > 0:
            ship_name = ship_names[0]  # Focus on first ship for detailed view
            ship_inv = inventory_expanded.filter(pl.col('actor_name') == ship_name)

            fig = make_subplots(
                rows=2, cols=1,
                subplot_titles=('Cargo Levels', 'Total Cargo Utilization'),
                vertical_spacing=0.12
            )

            # Add food and fuel traces
            fig.add_trace(
                go.Scatter(x=ship_inv['turn'], y=ship_inv['food_qty'],
                          name='Food', mode='lines+markers', line=dict(color='green')),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(x=ship_inv['turn'], y=ship_inv['fuel_qty'],
                          name='Fuel', mode='lines+markers', line=dict(color='orange')),
                row=1, col=1
            )

            # Add total cargo
            fig.add_trace(
                go.Scatter(x=ship_inv['turn'], y=ship_inv['total_cargo'],
                          name='Total Cargo', mode='lines+markers',
                          line=dict(color='blue'), fill='tozeroy'),
                row=2, col=1
            )

            fig.update_xaxes(title_text="Turn", row=2, col=1)
            fig.update_yaxes(title_text="Quantity", row=1, col=1)
            fig.update_yaxes(title_text="Total Items", row=2, col=1)

            fig.update_layout(
                title_text=f"Cargo Analysis: {ship_name}",
                height=600,
                showlegend=True,
                hovermode='x unified'
            )
            fig
        else:
            "No ship inventory data to display"
    else:
        "No inventory data available"


@app.cell
def __(mo):
    mo.md("## Summary Statistics")


@app.cell
def __(mo, latest_roi, margins, all_ship_txns, num_ships, pl):
    # Generate summary statistics
    if num_ships > 0:
        # Calculate key metrics
        if latest_roi is not None and len(latest_roi) > 0:
            avg_roi = latest_roi.select(pl.col('final_roi').mean()).item()
            best_ship = latest_roi.sort('final_roi', descending=True).head(1)
        else:
            avg_roi = 0
            best_ship = None

        if margins is not None and len(margins) > 0:
            avg_margin = margins.select(pl.col('profit_margin_pct').mean()).item()
            total_profit = margins.select(pl.col('total_profit').sum()).item()
        else:
            avg_margin = 0
            total_profit = 0

        if all_ship_txns is not None:
            total_trades = len(all_ship_txns)
            buy_trades = len(all_ship_txns.filter(pl.col('transaction_type') == 'buy'))
            sell_trades = len(all_ship_txns.filter(pl.col('transaction_type') == 'sell'))
        else:
            total_trades = 0
            buy_trades = 0
            sell_trades = 0

        mo.md(f"""
        ### Key Performance Indicators

        - **Average ROI:** {avg_roi:.1f}%
        - **Average Profit Margin:** {avg_margin:.1f}%
        - **Total Profit from Trades:** ${total_profit:.0f}
        - **Total Trades:** {total_trades} ({buy_trades} buys, {sell_trades} sells)
        - **Best Performing Ship:** {best_ship['actor_name'][0] if best_ship is not None and len(best_ship) > 0 else 'N/A'} ({best_ship['final_roi'][0]:.1f}% ROI if best_ship is not None and len(best_ship) > 0 else 'N/A')

        ### Interpretation

        {'✓ Ships are profitable! Average ROI is positive.' if avg_roi > 0 else '⚠️ Ships are losing money on average.'}

        {'✓ Good profit margins on trades.' if avg_margin > 15 else '⚠️ Profit margins are below 15% target.'}

        {'✓ Balanced buy/sell activity.' if abs(buy_trades - sell_trades) < buy_trades * 0.3 else '⚠️ Imbalanced trading - ships may be accumulating or depleting cargo.'}
        """)
    else:
        mo.md("""
        ### No Ship Data Available

        To track ships in the simulation:
        1. Ensure ships are created in the simulation
        2. Add ships to `simulation.data_logger` using `data_logger.add_actor_to_log(ship)`
        3. Run the simulation with `spacesim2 analyze` to export data
        """)


if __name__ == "__main__":
    app.run()
