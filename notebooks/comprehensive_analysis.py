"""Comprehensive Simulation Analysis

This notebook provides analysis across three key areas:
1. Actor drive health distributions by planet and drive type
2. Economic production activity by planet
3. Ship trading activity and cash reserves over time
"""

import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import json
    import marimo as mo
    import polars as pl
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from spacesim2.analysis.loading.loader import SimulationData
    from spacesim2.analysis.loading import get_run_path_with_fallback, NoRunsFoundError
    from pathlib import Path
    return Path, SimulationData, NoRunsFoundError, get_run_path_with_fallback, go, json, make_subplots, mo, os, pl, px


@app.cell
def _(Path, NoRunsFoundError, get_run_path_with_fallback, mo, os):
    """Load simulation data with auto-detection or manual override."""
    try:
        _auto_run_path = get_run_path_with_fallback()
        _run_path_str = str(_auto_run_path)
        _status_msg = f"Using run: **{_auto_run_path.name}**"
        if os.getenv("SPACESIM_RUN_PATH"):
            _status_msg += " (from SPACESIM_RUN_PATH)"
        else:
            _status_msg += " (auto-detected)"
    except NoRunsFoundError as e:
        _run_path_str = ""
        _status_msg = f"**No runs found**\n\n```\n{str(e)}\n```"

    run_selector = mo.ui.text(
        value=_run_path_str,
        label="Run Path (edit to override):",
        full_width=True,
    )

    mo.md(f"""
    # Comprehensive Simulation Analysis

    This notebook analyzes:
    1. **Drive Health Distributions** - How well are actors meeting their needs on each planet?
    2. **Production Activity** - What economic actions are actors taking on each planet?
    3. **Ship Trading** - How are ships performing in interplanetary trade?

    ---

    {_status_msg}

    {run_selector}
    """)
    return (run_selector,)


@app.cell
def _(Path, SimulationData, mo, run_selector):
    """Load simulation data from the selected run."""
    if not run_selector.value:
        data = None
        _load_msg = mo.md("No run path specified. Run `uv run spacesim2 run` first.")
    else:
        try:
            data = SimulationData(Path(run_selector.value))
            _load_msg = mo.md(f"Data loaded successfully")
        except FileNotFoundError as e:
            _load_msg = mo.md(f"Error loading data: {e}")
            data = None
    _load_msg
    return (data,)


@app.cell
def _(data, mo, pl):
    """Display simulation overview statistics."""
    if data is None:
        _overview = mo.md("## Simulation Overview\n\nNo data loaded")
    else:
        _num_turns = data.actor_turns["turn"].max() if len(data.actor_turns) > 0 else 0
        _num_actors = data.actor_turns["actor_id"].n_unique() if len(data.actor_turns) > 0 else 0
        _num_transactions = len(data.market_transactions)
        _planets = data.actor_turns["planet_name"].unique().to_list() if len(data.actor_turns) > 0 else []
        _drive_names = data.actor_drives.select("drive_name").unique().to_series().to_list() if len(data.actor_drives) > 0 else []

        # Count ships
        _ships = data.actor_turns.filter(
            pl.col("actor_name").str.contains("(?i)ship|trader")
        ).select("actor_name").unique()
        _num_ships = len(_ships)

        _overview = mo.md(f"""
        ## Simulation Overview

        | Metric | Value |
        |--------|-------|
        | Turns | {_num_turns} |
        | Actors Tracked | {_num_actors} |
        | Ships | {_num_ships} |
        | Planets | {len(_planets)} ({', '.join(_planets[:5])}{'...' if len(_planets) > 5 else ''}) |
        | Total Transactions | {_num_transactions:,} |
        | Drives Tracked | {', '.join(_drive_names)} |
        """)
    _overview
    return


# =============================================================================
# SECTION 1: Drive Health Distributions by Planet
# =============================================================================


@app.cell
def _(mo):
    mo.md("""
    ---
    # Section 1: Drive Health Distributions by Planet

    This section shows how well actors on each planet are meeting their basic needs.
    Each drive (food, clothing, shelter) is analyzed separately, showing the distribution
    of health values across actors on each planet.

    - **Health = 1.0**: Need is fully satisfied
    - **Health = 0.0**: Need is completely unmet
    """)
    return


@app.cell
def _(data, mo, pl, px):
    """Drive health distributions across all planets - summary view."""
    if data is None or len(data.actor_drives) == 0:
        _fig = mo.md("No drive data available")
    else:
        # Join drive data with actor turns to get planet info
        _drive_with_planet = data.actor_drives.join(
            data.actor_turns.select(["turn", "actor_id", "planet_name"]),
            on=["turn", "actor_id"],
            how="left"
        )

        # Get final turn data for snapshot
        _final_turn = _drive_with_planet["turn"].max()
        _final_snapshot = _drive_with_planet.filter(pl.col("turn") == _final_turn)

        # Create box plot of health by drive and planet
        _fig = px.box(
            _final_snapshot.to_pandas(),
            x="planet_name",
            y="health",
            color="drive_name",
            title=f"Drive Health Distribution by Planet (Turn {_final_turn})",
            labels={"health": "Health (0-1)", "planet_name": "Planet", "drive_name": "Drive"},
        )
        _fig.update_layout(
            xaxis_tickangle=-45,
            legend_title_text="Drive",
            height=500,
        )
    _fig
    return


@app.cell
def _(data, mo, pl, px):
    """Food drive health over time by planet."""
    if data is None or len(data.actor_drives) == 0:
        _fig = mo.md("No drive data available")
    else:
        _drive_with_planet = data.actor_drives.join(
            data.actor_turns.select(["turn", "actor_id", "planet_name"]),
            on=["turn", "actor_id"],
            how="left"
        )

        _food_by_planet = _drive_with_planet.filter(
            pl.col("drive_name") == "food"
        ).group_by(["turn", "planet_name"]).agg(
            pl.col("health").mean().alias("avg_health"),
            pl.col("health").std().alias("health_std"),
            pl.col("debt").mean().alias("avg_debt"),
        ).sort(["planet_name", "turn"])

        _fig = px.line(
            _food_by_planet.to_pandas(),
            x="turn",
            y="avg_health",
            color="planet_name",
            title="Food Drive: Average Health Over Time by Planet",
            labels={"avg_health": "Average Health", "turn": "Turn", "planet_name": "Planet"},
        )
        _fig.update_layout(hovermode="x unified")
    _fig
    return


@app.cell
def _(data, mo, pl, px):
    """Clothing drive health over time by planet."""
    if data is None or len(data.actor_drives) == 0:
        _fig = mo.md("No drive data available")
    else:
        _drive_with_planet = data.actor_drives.join(
            data.actor_turns.select(["turn", "actor_id", "planet_name"]),
            on=["turn", "actor_id"],
            how="left"
        )

        _clothing_by_planet = _drive_with_planet.filter(
            pl.col("drive_name") == "clothing"
        ).group_by(["turn", "planet_name"]).agg(
            pl.col("health").mean().alias("avg_health"),
            pl.col("debt").mean().alias("avg_debt"),
        ).sort(["planet_name", "turn"])

        if _clothing_by_planet.height == 0:
            _fig = mo.md("No clothing drive data found")
        else:
            _fig = px.line(
                _clothing_by_planet.to_pandas(),
                x="turn",
                y="avg_health",
                color="planet_name",
                title="Clothing Drive: Average Health Over Time by Planet",
                labels={"avg_health": "Average Health", "turn": "Turn", "planet_name": "Planet"},
            )
            _fig.update_layout(hovermode="x unified")
    _fig
    return


@app.cell
def _(data, mo, pl, px):
    """Shelter drive health over time by planet."""
    if data is None or len(data.actor_drives) == 0:
        _fig = mo.md("No drive data available")
    else:
        _drive_with_planet = data.actor_drives.join(
            data.actor_turns.select(["turn", "actor_id", "planet_name"]),
            on=["turn", "actor_id"],
            how="left"
        )

        _shelter_by_planet = _drive_with_planet.filter(
            pl.col("drive_name") == "shelter"
        ).group_by(["turn", "planet_name"]).agg(
            pl.col("health").mean().alias("avg_health"),
            pl.col("debt").mean().alias("avg_debt"),
        ).sort(["planet_name", "turn"])

        if _shelter_by_planet.height == 0:
            _fig = mo.md("No shelter drive data found")
        else:
            _fig = px.line(
                _shelter_by_planet.to_pandas(),
                x="turn",
                y="avg_health",
                color="planet_name",
                title="Shelter Drive: Average Health Over Time by Planet",
                labels={"avg_health": "Average Health", "turn": "Turn", "planet_name": "Planet"},
            )
            _fig.update_layout(hovermode="x unified")
    _fig
    return


@app.cell
def _(data, go, make_subplots, mo, pl):
    """Comparative drive health heatmap by planet."""
    if data is None or len(data.actor_drives) == 0:
        _fig = mo.md("No drive data available")
    else:
        _drive_with_planet = data.actor_drives.join(
            data.actor_turns.select(["turn", "actor_id", "planet_name"]),
            on=["turn", "actor_id"],
            how="left"
        )

        # Aggregate by planet and drive
        _summary = _drive_with_planet.group_by(["planet_name", "drive_name"]).agg(
            pl.col("health").mean().alias("avg_health"),
            pl.col("debt").mean().alias("avg_debt"),
            pl.col("buffer").mean().alias("avg_buffer"),
        ).sort(["planet_name", "drive_name"])

        # Pivot for heatmap
        _health_pivot = _summary.pivot(
            values="avg_health",
            index="planet_name",
            on="drive_name",
        ).sort("planet_name")

        _planets = _health_pivot["planet_name"].to_list()
        _drives = [c for c in _health_pivot.columns if c != "planet_name"]

        _z_values = [[_health_pivot[drive][i] for drive in _drives] for i in range(len(_planets))]

        _fig = go.Figure(data=go.Heatmap(
            z=_z_values,
            x=_drives,
            y=_planets,
            colorscale="RdYlGn",
            zmin=0,
            zmax=1,
            text=[[f"{v:.2f}" if v is not None else "" for v in row] for row in _z_values],
            texttemplate="%{text}",
            textfont={"size": 12},
            hovertemplate="Planet: %{y}<br>Drive: %{x}<br>Avg Health: %{z:.2f}<extra></extra>",
        ))
        _fig.update_layout(
            title="Average Drive Health by Planet (All Time)",
            xaxis_title="Drive",
            yaxis_title="Planet",
            height=400 + len(_planets) * 20,
        )
    _fig
    return


# =============================================================================
# SECTION 2: Economic Production Activity by Planet
# =============================================================================


@app.cell
def _(mo):
    mo.md("""
    ---
    # Section 2: Economic Production Activity by Planet

    This section analyzes the production patterns on each planet by examining:
    - **Market transaction volume** by commodity (proxy for production activity)
    - **Sell-side activity** by non-ship actors (direct production indicator)
    - **Production mix** showing what each planet specializes in producing
    """)
    return


@app.cell
def _(data, mo, pl, px):
    """Production activity by commodity and planet (based on local sales)."""
    if data is None or len(data.market_transactions) == 0:
        _fig = mo.md("No transaction data available")
    else:
        # Filter out ship transactions to see local production
        _local_sales = data.market_transactions.filter(
            ~pl.col("seller_name").str.contains("(?i)ship|trader")
        )

        # Aggregate by planet and commodity
        _production_by_planet = _local_sales.group_by(["planet_name", "commodity_id"]).agg(
            pl.col("quantity").sum().alias("total_sold"),
            pl.col("quantity").count().alias("num_transactions"),
        ).sort(["planet_name", "total_sold"], descending=[False, True])

        _fig = px.bar(
            _production_by_planet.to_pandas(),
            x="planet_name",
            y="total_sold",
            color="commodity_id",
            title="Production by Planet (Local Actor Sales, Excluding Ships)",
            labels={"total_sold": "Total Quantity Sold", "planet_name": "Planet", "commodity_id": "Commodity"},
            barmode="stack",
        )
        _fig.update_layout(
            xaxis_tickangle=-45,
            legend_title_text="Commodity",
            height=500,
        )
    _fig
    return


@app.cell
def _(data, mo, pl, px):
    """Production mix percentage by planet."""
    if data is None or len(data.market_transactions) == 0:
        _fig = mo.md("No transaction data available")
    else:
        _local_sales = data.market_transactions.filter(
            ~pl.col("seller_name").str.contains("(?i)ship|trader")
        )

        _production_by_planet = _local_sales.group_by(["planet_name", "commodity_id"]).agg(
            pl.col("quantity").sum().alias("total_sold"),
        )

        # Calculate percentage within each planet
        _planet_totals = _production_by_planet.group_by("planet_name").agg(
            pl.col("total_sold").sum().alias("planet_total")
        )

        _production_pct = _production_by_planet.join(
            _planet_totals, on="planet_name"
        ).with_columns(
            (pl.col("total_sold") / pl.col("planet_total") * 100).alias("pct_of_planet")
        ).sort(["planet_name", "pct_of_planet"], descending=[False, True])

        _fig = px.bar(
            _production_pct.to_pandas(),
            x="planet_name",
            y="pct_of_planet",
            color="commodity_id",
            title="Production Mix by Planet (% of Local Sales)",
            labels={"pct_of_planet": "% of Planet Production", "planet_name": "Planet", "commodity_id": "Commodity"},
            barmode="stack",
        )
        _fig.update_layout(
            xaxis_tickangle=-45,
            legend_title_text="Commodity",
            height=500,
        )
    _fig
    return


@app.cell
def _(data, mo, pl, px):
    """Production activity over time (rolling average)."""
    if data is None or len(data.market_transactions) == 0:
        _fig = mo.md("No transaction data available")
    else:
        _local_sales = data.market_transactions.filter(
            ~pl.col("seller_name").str.contains("(?i)ship|trader")
        )

        # Aggregate by turn and planet
        _production_by_turn = _local_sales.group_by(["turn", "planet_name"]).agg(
            pl.col("quantity").sum().alias("total_production"),
        ).sort(["planet_name", "turn"])

        # Rolling average
        _production_smoothed = _production_by_turn.with_columns(
            pl.col("total_production").rolling_mean(window_size=50, min_periods=1).over("planet_name").alias("production_avg")
        )

        _fig = px.line(
            _production_smoothed.to_pandas(),
            x="turn",
            y="production_avg",
            color="planet_name",
            title="Local Production Activity Over Time (50-turn rolling avg)",
            labels={"production_avg": "Production Volume", "turn": "Turn", "planet_name": "Planet"},
        )
        _fig.update_layout(hovermode="x unified")
    _fig
    return


@app.cell
def _(data, mo, pl):
    """Top commodities produced per planet."""
    if data is None or len(data.market_transactions) == 0:
        _table = mo.md("No transaction data available")
    else:
        _local_sales = data.market_transactions.filter(
            ~pl.col("seller_name").str.contains("(?i)ship|trader")
        )

        _production_by_planet = _local_sales.group_by(["planet_name", "commodity_id"]).agg(
            pl.col("quantity").sum().alias("total_sold"),
        ).sort(["planet_name", "total_sold"], descending=[False, True])

        # Get top 3 commodities per planet
        _top_by_planet = _production_by_planet.with_columns(
            pl.col("total_sold").rank(descending=True).over("planet_name").alias("rank")
        ).filter(pl.col("rank") <= 3).sort(["planet_name", "rank"])

        _table = mo.ui.table(_top_by_planet.to_pandas(), label="Top 3 Produced Commodities per Planet")
    _table
    return


# =============================================================================
# SECTION 3: Ship Trading Activity and Cash Reserves
# =============================================================================


@app.cell
def _(mo):
    mo.md("""
    ---
    # Section 3: Ship Trading Activity and Cash Reserves

    This section analyzes the performance of trading ships:
    - **Cash reserves over time** - Are ships profitable?
    - **Trading volume** - How active are ships in buying/selling?
    - **Trade patterns** - What are ships trading and where?
    """)
    return


@app.cell
def _(data, mo, pl, px):
    """Ship cash reserves over time."""
    if data is None or len(data.actor_turns) == 0:
        ship_actors = None
        _fig = mo.md("No actor data available")
    else:
        ship_actors = data.actor_turns.filter(
            pl.col("actor_name").str.contains("(?i)ship|trader")
        )

        if ship_actors.height == 0:
            _fig = mo.md("No ship data found in simulation. Ships may not be logged.")
        else:
            _fig = px.line(
                ship_actors.to_pandas(),
                x="turn",
                y="money",
                color="actor_name",
                title="Ship Cash Reserves Over Time",
                labels={"money": "Cash ($)", "turn": "Turn", "actor_name": "Ship"},
            )
            _fig.update_layout(hovermode="x unified", height=500)
    _fig
    return (ship_actors,)


@app.cell
def _(mo, pl, px, ship_actors):
    """Ship profit/loss per turn."""
    if ship_actors is None or ship_actors.height == 0:
        _fig = mo.md("No ship data available")
    else:
        _ship_profits = (
            ship_actors
            .sort(["actor_name", "turn"])
            .with_columns([
                (pl.col("money") - pl.col("money").shift(1).over("actor_name")).alias("profit_per_turn"),
                pl.col("money").first().over("actor_name").alias("starting_money"),
            ])
            .filter(pl.col("profit_per_turn").is_not_null())
        )

        # Rolling average of profit
        _ship_profits_smooth = _ship_profits.with_columns(
            pl.col("profit_per_turn").rolling_mean(window_size=20, min_periods=1).over("actor_name").alias("profit_avg")
        )

        _fig = px.line(
            _ship_profits_smooth.to_pandas(),
            x="turn",
            y="profit_avg",
            color="actor_name",
            title="Ship Profit per Turn (20-turn rolling avg)",
            labels={"profit_avg": "Profit ($)", "turn": "Turn", "actor_name": "Ship"},
        )
        _fig.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="Break Even")
        _fig.update_layout(hovermode="x unified")
    _fig
    return


@app.cell
def _(data, mo, pl, px):
    """Ship trading volume over time (buys vs sells)."""
    if data is None or len(data.market_transactions) == 0:
        ship_txns = None
        _fig = mo.md("No transaction data available")
    else:
        # Get ship transactions
        ship_txns = data.market_transactions.filter(
            pl.col("buyer_name").str.contains("(?i)ship|trader") |
            pl.col("seller_name").str.contains("(?i)ship|trader")
        )

        if ship_txns.height == 0:
            _fig = mo.md("No ship transactions found")
        else:
            # Separate buys and sells
            _ship_buys = ship_txns.filter(
                pl.col("buyer_name").str.contains("(?i)ship|trader")
            ).group_by("turn").agg(
                pl.col("quantity").sum().alias("quantity")
            ).with_columns(pl.lit("buy").alias("type"))

            _ship_sells = ship_txns.filter(
                pl.col("seller_name").str.contains("(?i)ship|trader")
            ).group_by("turn").agg(
                pl.col("quantity").sum().alias("quantity")
            ).with_columns(pl.lit("sell").alias("type"))

            _volume_by_turn = pl.concat([_ship_buys, _ship_sells]).sort("turn")

            # Rolling average
            _volume_smooth = _volume_by_turn.with_columns(
                pl.col("quantity").rolling_mean(window_size=25, min_periods=1).over("type").alias("volume_avg")
            )

            _fig = px.line(
                _volume_smooth.to_pandas(),
                x="turn",
                y="volume_avg",
                color="type",
                title="Ship Trading Volume Over Time (25-turn rolling avg)",
                labels={"volume_avg": "Quantity", "turn": "Turn", "type": "Transaction Type"},
            )
            _fig.update_layout(hovermode="x unified")
    _fig
    return (ship_txns,)


@app.cell
def _(mo, pl, px, ship_txns):
    """What commodities are ships trading?"""
    if ship_txns is None or ship_txns.height == 0:
        _fig = mo.md("No ship transaction data")
    else:
        _ship_buys = ship_txns.filter(
            pl.col("buyer_name").str.contains("(?i)ship|trader")
        ).group_by("commodity_id").agg(
            pl.col("quantity").sum().alias("quantity")
        ).with_columns(pl.lit("Bought").alias("type"))

        _ship_sells = ship_txns.filter(
            pl.col("seller_name").str.contains("(?i)ship|trader")
        ).group_by("commodity_id").agg(
            pl.col("quantity").sum().alias("quantity")
        ).with_columns(pl.lit("Sold").alias("type"))

        _commodity_volume = pl.concat([_ship_buys, _ship_sells])

        _fig = px.bar(
            _commodity_volume.to_pandas(),
            x="commodity_id",
            y="quantity",
            color="type",
            barmode="group",
            title="Ship Trading by Commodity (Total Volume)",
            labels={"quantity": "Total Quantity", "commodity_id": "Commodity", "type": "Direction"},
        )
        _fig.update_layout(xaxis_tickangle=-45)
    _fig
    return


@app.cell
def _(mo, pl, px, ship_txns):
    """Ship trading activity by planet."""
    if ship_txns is None or ship_txns.height == 0:
        _fig = mo.md("No ship transaction data")
    else:
        _ship_buys = ship_txns.filter(
            pl.col("buyer_name").str.contains("(?i)ship|trader")
        ).group_by("planet_name").agg(
            pl.col("quantity").sum().alias("quantity")
        ).with_columns(pl.lit("Bought from").alias("type"))

        _ship_sells = ship_txns.filter(
            pl.col("seller_name").str.contains("(?i)ship|trader")
        ).group_by("planet_name").agg(
            pl.col("quantity").sum().alias("quantity")
        ).with_columns(pl.lit("Sold to").alias("type"))

        _planet_volume = pl.concat([_ship_buys, _ship_sells])

        _fig = px.bar(
            _planet_volume.to_pandas(),
            x="planet_name",
            y="quantity",
            color="type",
            barmode="group",
            title="Ship Trading Activity by Planet",
            labels={"quantity": "Total Quantity", "planet_name": "Planet", "type": "Direction"},
        )
        _fig.update_layout(xaxis_tickangle=-45)
    _fig
    return


@app.cell
def _(go, make_subplots, mo, pl, ship_actors, ship_txns):
    """Combined ship performance dashboard."""
    if ship_actors is None or ship_actors.height == 0:
        _fig = mo.md("No ship data available for dashboard")
    else:
        _ship_names = ship_actors.select("actor_name").unique().to_series().to_list()

        _fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "Cash Reserves",
                "Trading Volume (Buys)",
                "Profit per Turn",
                "Trading Volume (Sells)",
            ),
            vertical_spacing=0.12,
            horizontal_spacing=0.08,
        )

        # Colors for ships
        _colors = px.colors.qualitative.Set2

        for _i, _ship_name in enumerate(_ship_names):
            _color = _colors[_i % len(_colors)]

            # Cash reserves
            _ship_data = ship_actors.filter(pl.col("actor_name") == _ship_name).to_pandas()
            _fig.add_trace(
                go.Scatter(x=_ship_data["turn"], y=_ship_data["money"],
                          name=_ship_name, line=dict(color=_color), legendgroup=_ship_name),
                row=1, col=1
            )

            # Profit per turn
            _ship_profits = ship_actors.filter(
                pl.col("actor_name") == _ship_name
            ).sort("turn").with_columns(
                (pl.col("money") - pl.col("money").shift(1)).alias("profit")
            ).filter(pl.col("profit").is_not_null()).to_pandas()

            if len(_ship_profits) > 0:
                _fig.add_trace(
                    go.Scatter(x=_ship_profits["turn"], y=_ship_profits["profit"],
                              name=_ship_name, line=dict(color=_color), legendgroup=_ship_name,
                              showlegend=False),
                    row=2, col=1
                )

            # Trading volume
            if ship_txns is not None and ship_txns.height > 0:
                _buys = ship_txns.filter(
                    pl.col("buyer_name") == _ship_name
                ).group_by("turn").agg(pl.col("quantity").sum()).to_pandas()

                _sells = ship_txns.filter(
                    pl.col("seller_name") == _ship_name
                ).group_by("turn").agg(pl.col("quantity").sum()).to_pandas()

                if len(_buys) > 0:
                    _fig.add_trace(
                        go.Scatter(x=_buys["turn"], y=_buys["quantity"],
                                  name=_ship_name, line=dict(color=_color), legendgroup=_ship_name,
                                  showlegend=False),
                        row=1, col=2
                    )
                if len(_sells) > 0:
                    _fig.add_trace(
                        go.Scatter(x=_sells["turn"], y=_sells["quantity"],
                                  name=_ship_name, line=dict(color=_color), legendgroup=_ship_name,
                                  showlegend=False),
                        row=2, col=2
                    )

        _fig.update_layout(
            height=700,
            title_text="Ship Performance Dashboard",
            showlegend=True,
            hovermode="x unified",
        )
        _fig.update_yaxes(title_text="Cash ($)", row=1, col=1)
        _fig.update_yaxes(title_text="Quantity", row=1, col=2)
        _fig.update_yaxes(title_text="Profit ($)", row=2, col=1)
        _fig.update_yaxes(title_text="Quantity", row=2, col=2)
        _fig.update_xaxes(title_text="Turn", row=2, col=1)
        _fig.update_xaxes(title_text="Turn", row=2, col=2)

    _fig
    return


@app.cell
def _(mo, pl, ship_actors, ship_txns):
    """Ship performance summary statistics."""
    if ship_actors is None or ship_actors.height == 0:
        _summary = mo.md("No ship data for summary")
    else:
        _ship_names = ship_actors.select("actor_name").unique().to_series().to_list()

        _stats = []
        for _ship_name in _ship_names:
            _ship_data = ship_actors.filter(pl.col("actor_name") == _ship_name)
            _start_money = _ship_data.sort("turn").head(1)["money"][0]
            _end_money = _ship_data.sort("turn").tail(1)["money"][0]
            _roi = ((_end_money - _start_money) / _start_money * 100) if _start_money > 0 else 0

            _buy_count = 0
            _sell_count = 0
            _total_bought = 0
            _total_sold = 0

            if ship_txns is not None:
                _buys = ship_txns.filter(pl.col("buyer_name") == _ship_name)
                _sells = ship_txns.filter(pl.col("seller_name") == _ship_name)
                _buy_count = len(_buys)
                _sell_count = len(_sells)
                _total_bought = _buys.select(pl.col("quantity").sum()).item() if len(_buys) > 0 else 0
                _total_sold = _sells.select(pl.col("quantity").sum()).item() if len(_sells) > 0 else 0

            _stats.append({
                "Ship": _ship_name,
                "Start Cash": f"${_start_money:,.0f}",
                "End Cash": f"${_end_money:,.0f}",
                "ROI": f"{_roi:+.1f}%",
                "Buy Txns": _buy_count,
                "Sell Txns": _sell_count,
                "Qty Bought": _total_bought,
                "Qty Sold": _total_sold,
            })

        _stats_df = pl.DataFrame(_stats)
        _summary = mo.vstack([
            mo.md("### Ship Performance Summary"),
            mo.ui.table(_stats_df.to_pandas()),
        ])
    _summary
    return


if __name__ == "__main__":
    app.run()
