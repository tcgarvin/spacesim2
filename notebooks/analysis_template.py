import marimo

__generated_with = "0.18.1"
app = marimo.App()


@app.cell
def __():
    import os
    import marimo as mo
    import polars as pl
    import plotly.express as px
    from spacesim2.analysis.loading.loader import SimulationData
    from pathlib import Path
    return mo, os, pl, px, SimulationData, Path


@app.cell
def __(mo, os, Path):
    # Load run path from environment or use default
    default_run = "data/runs/test_run"  # placeholder
    run_path_str = os.getenv("SPACESIM_RUN_PATH", default_run)

    # UI to select different runs if needed
    run_selector = mo.ui.text(
        value=run_path_str,
        label="Run Path:",
        full_width=True
    )
    mo.md(f"# SpaceSim2 Analysis\n\n{run_selector}")
    return run_path_str, run_selector


@app.cell
def __(SimulationData, Path, run_selector):
    # Load data
    data = SimulationData(Path(run_selector.value))
    return data,


@app.cell
def __(mo, data):
    # Show basic stats
    mo.md(f"""
    ## Simulation Overview
    - **Turns:** {data.actor_turns['turn'].max() if len(data.actor_turns) > 0 else 'N/A'}
    - **Actors:** {data.actor_turns['actor_id'].n_unique() if len(data.actor_turns) > 0 else 'N/A'}
    - **Transactions:** {len(data.market_transactions)}
    - **Market Snapshots:** {len(data.market_snapshots)}
    """)


@app.cell
def __(mo):
    mo.md("## Actor Behavior Over Time")


@app.cell
def __(data, px):
    # Example: Money over time for actors
    if len(data.actor_turns) > 0:
        actor_money = data.actor_turns.select(['turn', 'actor_id', 'actor_name', 'money'])
        fig_money = px.line(
            actor_money.to_pandas(),
            x='turn',
            y='money',
            color='actor_name',
            title='Actor Money Over Time',
            labels={'money': 'Money ($)', 'turn': 'Turn'}
        )
        fig_money
    else:
        "No actor turn data available"


@app.cell
def __(mo):
    mo.md("## Market Dynamics")


@app.cell
def __(data, px):
    # Example: Average price per commodity over time
    if len(data.market_snapshots) > 0:
        price_trends = data.market_snapshots.select(['turn', 'commodity', 'avg_price'])
        fig_prices = px.line(
            price_trends.to_pandas(),
            x='turn',
            y='avg_price',
            color='commodity',
            title='Commodity Prices Over Time',
            labels={'avg_price': 'Average Price ($)', 'turn': 'Turn'}
        )
        fig_prices
    else:
        "No market snapshot data available"


@app.cell
def __(data, px):
    # Example: Transaction volume per commodity
    if len(data.market_transactions) > 0:
        volume_by_commodity = data.market_transactions.group_by('commodity').agg(
            pl.col('quantity').sum().alias('total_volume')
        ).sort('total_volume', descending=True)

        fig_volume = px.bar(
            volume_by_commodity.to_pandas(),
            x='commodity',
            y='total_volume',
            title='Total Transaction Volume by Commodity',
            labels={'total_volume': 'Total Quantity', 'commodity': 'Commodity'}
        )
        fig_volume
    else:
        "No transaction data available"


@app.cell
def __(mo):
    mo.md("## Economic Health Metrics")


@app.cell
def __(data, px, pl):
    # Example: Drive health over time
    if len(data.actor_drives) > 0:
        drive_health = data.actor_drives.select(['turn', 'drive_name', 'health'])
        avg_health = drive_health.group_by(['turn', 'drive_name']).agg(
            pl.col('health').mean().alias('avg_health')
        )
        fig_drives = px.line(
            avg_health.to_pandas(),
            x='turn',
            y='avg_health',
            color='drive_name',
            title='Average Drive Health Over Time',
            labels={'avg_health': 'Average Health', 'turn': 'Turn', 'drive_name': 'Drive'}
        )
        fig_drives
    else:
        "No drive data available"


@app.cell
def __(data, px, pl):
    # Example: Drive debt over time
    if len(data.actor_drives) > 0:
        drive_debt = data.actor_drives.select(['turn', 'drive_name', 'debt'])
        avg_debt = drive_debt.group_by(['turn', 'drive_name']).agg(
            pl.col('debt').mean().alias('avg_debt')
        )
        fig_debt = px.line(
            avg_debt.to_pandas(),
            x='turn',
            y='avg_debt',
            color='drive_name',
            title='Average Drive Debt Over Time',
            labels={'avg_debt': 'Average Debt', 'turn': 'Turn', 'drive_name': 'Drive'}
        )
        fig_debt
    else:
        "No drive data available"


if __name__ == "__main__":
    app.run()
