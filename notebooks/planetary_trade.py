import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import marimo as mo
    import polars as pl
    import plotly.express as px
    import plotly.graph_objects as go
    from spacesim2.analysis.loading.loader import SimulationData
    from pathlib import Path
    return Path, SimulationData, go, mo, os, pl, px


@app.cell
def _(mo, os):
    from spacesim2.analysis.loading import (
        get_run_path_with_fallback,
        NoRunsFoundError,
    )

    try:
        auto_run_path = get_run_path_with_fallback()
        run_path_str = str(auto_run_path)
        status_msg = f"Using run: **{auto_run_path.name}**"

        if os.getenv("SPACESIM_RUN_PATH"):
            status_msg += " (from SPACESIM_RUN_PATH)"
        else:
            status_msg += " (auto-detected)"

    except NoRunsFoundError as e:
        run_path_str = ""
        status_msg = f"**No runs found**\n\n```\n{str(e)}\n```"

    run_selector = mo.ui.text(
        value=run_path_str,
        label="Run Path (edit to override):",
        full_width=True,
    )

    mo.md(f"""
    # Planetary Trade Analysis

    Imports and exports by planet over time.

    - **Import** = Ship sells goods TO planet (goods flow in)
    - **Export** = Ship buys goods FROM planet (goods flow out)

    {status_msg}

    {run_selector}
    """)

    return NoRunsFoundError, auto_run_path, get_run_path_with_fallback, run_path_str, run_selector, status_msg


@app.cell
def _(Path, SimulationData, mo, run_selector):
    # Load data
    if not run_selector.value:
        data = None
        load_msg = mo.md("No run path specified. Run `spacesim2 analyze` first.")
    else:
        try:
            data = SimulationData(Path(run_selector.value))
            load_msg = mo.md(f"Data loaded successfully")
        except Exception as e:
            data = None
            load_msg = mo.md(f"Error loading data: {e}")

    load_msg
    return data, load_msg


@app.cell
def _(data, mo, pl):
    # Extract ship transactions
    if data is None:
        txns = None
        ship_txns = None
        overview_content = mo.md("## Overview\n\nNo data loaded")
    else:
        txns = data.market_transactions

        # Identify ship transactions (ships have "Trader" in name)
        ship_txns = txns.filter(
            pl.col('buyer_name').str.contains('Trader') |
            pl.col('seller_name').str.contains('Trader')
        )

        planets = txns['planet_name'].unique().sort().to_list()
        total_turns = txns['turn'].max()

        overview_content = mo.md(f"""
        ## Simulation Overview
        - **Turns:** {total_turns}
        - **Planets:** {len(planets)} ({', '.join(planets)})
        - **Total Transactions:** {len(txns):,}
        - **Ship Transactions:** {len(ship_txns):,}
        """)

    overview_content
    return overview_content, planets, ship_txns, total_turns, txns


@app.cell
def _(mo):
    mo.md("""
    ## Trade Flow Summary

    Net trade position for each planet across the entire simulation.
    Positive = net importer, Negative = net exporter.
    """)
    return


@app.cell
def _(pl, px, ship_txns):
    # Calculate trade balance
    if ship_txns is None or len(ship_txns) == 0:
        trade_balance = None
        fig_balance = None
    else:
        # Imports: ships SELL to planet (seller contains Trader)
        imports = ship_txns.filter(
            pl.col('seller_name').str.contains('Trader')
        ).group_by('planet_name').agg(
            pl.col('quantity').sum().alias('import_qty'),
            pl.col('total_amount').sum().alias('import_value')
        )

        # Exports: ships BUY from planet (buyer contains Trader)
        exports = ship_txns.filter(
            pl.col('buyer_name').str.contains('Trader')
        ).group_by('planet_name').agg(
            pl.col('quantity').sum().alias('export_qty'),
            pl.col('total_amount').sum().alias('export_value')
        )

        # Join and calculate net
        trade_balance = imports.join(exports, on='planet_name', how='outer').fill_null(0)
        trade_balance = trade_balance.with_columns([
            (pl.col('import_qty') - pl.col('export_qty')).alias('net_qty'),
            (pl.col('import_value') - pl.col('export_value')).alias('net_value')
        ]).sort('net_value', descending=True)

        fig_balance = px.bar(
            trade_balance.to_pandas(),
            x='planet_name',
            y='net_value',
            color='net_value',
            color_continuous_scale='RdBu',
            title='Net Trade Balance by Planet (positive = net importer)',
            labels={'net_value': 'Net Value ($)', 'planet_name': 'Planet'}
        )
        fig_balance.update_layout(coloraxis_showscale=False)

    fig_balance
    return exports, fig_balance, imports, trade_balance


@app.cell
def _(mo):
    mo.md("""
    ## Imports and Exports Over Time

    Rolling 50-turn average of trade flows by planet.
    """)
    return


@app.cell
def _(pl, px, ship_txns):
    # Imports over time
    if ship_txns is None or len(ship_txns) == 0:
        trade_smoothed = None
        fig_imports = None
    else:
        # Imports per turn per planet
        imports_by_turn = ship_txns.filter(
            pl.col('seller_name').str.contains('Trader')
        ).group_by(['turn', 'planet_name']).agg(
            pl.col('quantity').sum().alias('import_qty')
        )

        # Exports per turn per planet
        exports_by_turn = ship_txns.filter(
            pl.col('buyer_name').str.contains('Trader')
        ).group_by(['turn', 'planet_name']).agg(
            pl.col('quantity').sum().alias('export_qty')
        )

        # Join and fill missing values
        trade_by_turn = imports_by_turn.join(
            exports_by_turn, on=['turn', 'planet_name'], how='outer'
        ).fill_null(0).sort(['planet_name', 'turn'])

        # Calculate rolling average (50 turns)
        trade_smoothed = trade_by_turn.with_columns([
            pl.col('import_qty').rolling_mean(window_size=50, min_periods=1).over('planet_name').alias('import_avg'),
            pl.col('export_qty').rolling_mean(window_size=50, min_periods=1).over('planet_name').alias('export_avg'),
        ])

        fig_imports = px.line(
            trade_smoothed.to_pandas(),
            x='turn',
            y='import_avg',
            color='planet_name',
            title='Imports Over Time (50-turn rolling avg)',
            labels={'import_avg': 'Quantity', 'turn': 'Turn', 'planet_name': 'Planet'}
        )

    fig_imports
    return exports_by_turn, fig_imports, imports_by_turn, trade_by_turn, trade_smoothed


@app.cell
def _(px, trade_smoothed):
    # Exports over time
    if trade_smoothed is None:
        fig_exports = None
    else:
        fig_exports = px.line(
            trade_smoothed.to_pandas(),
            x='turn',
            y='export_avg',
            color='planet_name',
            title='Exports Over Time (50-turn rolling avg)',
            labels={'export_avg': 'Quantity', 'turn': 'Turn', 'planet_name': 'Planet'}
        )

    fig_exports
    return (fig_exports,)


@app.cell
def _(mo):
    mo.md("""
    ## Commodity Breakdown

    What commodities does each planet import and export?
    """)
    return


@app.cell
def _(pl, px, ship_txns):
    # Imports by commodity
    if ship_txns is None or len(ship_txns) == 0:
        fig_imports_commodity = None
    else:
        imports_by_commodity = ship_txns.filter(
            pl.col('seller_name').str.contains('Trader')
        ).group_by(['planet_name', 'commodity_id']).agg(
            pl.col('quantity').sum().alias('quantity')
        )

        fig_imports_commodity = px.bar(
            imports_by_commodity.to_pandas(),
            x='planet_name',
            y='quantity',
            color='commodity_id',
            title='Imports by Planet and Commodity',
            labels={'quantity': 'Total Quantity', 'planet_name': 'Planet', 'commodity_id': 'Commodity'},
            barmode='stack'
        )

    fig_imports_commodity
    return fig_imports_commodity, imports_by_commodity


@app.cell
def _(pl, px, ship_txns):
    # Exports by commodity
    if ship_txns is None or len(ship_txns) == 0:
        fig_exports_commodity = None
    else:
        exports_by_commodity = ship_txns.filter(
            pl.col('buyer_name').str.contains('Trader')
        ).group_by(['planet_name', 'commodity_id']).agg(
            pl.col('quantity').sum().alias('quantity')
        )

        fig_exports_commodity = px.bar(
            exports_by_commodity.to_pandas(),
            x='planet_name',
            y='quantity',
            color='commodity_id',
            title='Exports by Planet and Commodity',
            labels={'quantity': 'Total Quantity', 'planet_name': 'Planet', 'commodity_id': 'Commodity'},
            barmode='stack'
        )

    fig_exports_commodity
    return exports_by_commodity, fig_exports_commodity


@app.cell
def _(mo):
    mo.md("""
    ## Trade Patterns Over Time by Planet

    Select a planet to see detailed import/export patterns.
    """)
    return


@app.cell
def _(mo, ship_txns):
    # Planet selector
    if ship_txns is None:
        planet_selector = None
        selector_output = mo.md("No data available")
    else:
        planet_options = ship_txns['planet_name'].unique().sort().to_list()
        planet_selector = mo.ui.dropdown(
            options=planet_options,
            value=planet_options[0] if planet_options else None,
            label="Select Planet:"
        )
        selector_output = planet_selector

    selector_output
    return planet_options, planet_selector, selector_output


@app.cell
def _(mo, pl, planet_selector, px, ship_txns):
    # Per-planet detail view
    if ship_txns is None or planet_selector is None or planet_selector.value is None:
        fig_planet = mo.md("Select a planet above")
    else:
        selected_planet = planet_selector.value
        planet_txns = ship_txns.filter(pl.col('planet_name') == selected_planet)

        # Get imports (ships sell) and exports (ships buy) per turn
        planet_imports = planet_txns.filter(
            pl.col('seller_name').str.contains('Trader')
        ).group_by(['turn', 'commodity_id']).agg(
            pl.col('quantity').sum().alias('quantity')
        ).with_columns(pl.lit('import').alias('flow_type'))

        planet_exports = planet_txns.filter(
            pl.col('buyer_name').str.contains('Trader')
        ).group_by(['turn', 'commodity_id']).agg(
            pl.col('quantity').sum().alias('quantity')
        ).with_columns(pl.lit('export').alias('flow_type'))

        # Combine
        planet_flows = pl.concat([planet_imports, planet_exports])

        # Apply rolling average
        planet_flows_smooth = planet_flows.sort(['commodity_id', 'flow_type', 'turn']).with_columns(
            pl.col('quantity').rolling_mean(window_size=25, min_periods=1).over(['commodity_id', 'flow_type']).alias('quantity_smooth')
        )

        fig_planet = px.line(
            planet_flows_smooth.to_pandas(),
            x='turn',
            y='quantity_smooth',
            color='commodity_id',
            line_dash='flow_type',
            title=f'{selected_planet}: Trade Flows by Commodity (25-turn rolling avg)',
            labels={'quantity_smooth': 'Quantity', 'turn': 'Turn', 'commodity_id': 'Commodity'}
        )

    fig_planet
    return fig_planet, planet_exports, planet_flows, planet_flows_smooth, planet_imports, planet_txns, selected_planet


@app.cell
def _(mo):
    mo.md("""
    ## Summary Table

    Total imports and exports for each planet.
    """)
    return


@app.cell
def _(mo, trade_balance):
    # Summary table
    if trade_balance is None:
        summary_table = mo.md("No data available")
    else:
        summary_table = mo.ui.table(trade_balance.to_pandas())

    summary_table
    return (summary_table,)


if __name__ == "__main__":
    app.run()
