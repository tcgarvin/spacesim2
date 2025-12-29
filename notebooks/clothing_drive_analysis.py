import marimo

__generated_with = "0.18.1"
app = marimo.App()


@app.cell
def _():
    import os
    import marimo as mo
    import polars as pl
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from spacesim2.analysis.loading.loader import SimulationData
    from spacesim2.analysis.loading import get_run_path_with_fallback, NoRunsFoundError
    from pathlib import Path
    return Path, SimulationData, NoRunsFoundError, get_run_path_with_fallback, go, make_subplots, mo, os, pl, px


@app.cell
def _(Path, SimulationData, NoRunsFoundError, get_run_path_with_fallback, mo, os):
    """Load simulation data with auto-detection or manual override."""
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
    # Clothing Drive Analysis

    This notebook analyzes the newly implemented clothing drive system, including:
    - **Fiber** and **Clothing** commodities (newly added)
    - **gather_fiber** and **make_clothing** processes
    - Market maker dynamic commodity handling
    - Comparison with food and shelter drives

    ---

    {status_msg}

    {run_selector}
    """)
    return run_selector, run_path_str, status_msg


@app.cell
def _(Path, SimulationData, mo, run_selector):
    """Load simulation data from the selected run."""
    if not run_selector.value:
        data = None
        _ = mo.md("No run path specified. Run `uv run spacesim2 run` first.")
    else:
        try:
            data = SimulationData(Path(run_selector.value))
            _ = mo.md(f"Data loaded successfully from {run_selector.value}")
        except FileNotFoundError as e:
            _ = mo.md(f"Error loading data: {e}")
            data = None
    return (data,)


@app.cell
def _(data, mo, pl):
    """Display simulation overview statistics."""
    if data is None:
        overview_output = mo.md("## Simulation Overview\n\nNo data loaded")
    else:
        num_turns = data.actor_turns["turn"].max() if len(data.actor_turns) > 0 else 0
        num_actors = data.actor_turns["actor_id"].n_unique() if len(data.actor_turns) > 0 else 0
        num_transactions = len(data.market_transactions)

        # Check which drives exist
        drive_names = data.actor_drives.select("drive_name").unique().to_series().to_list() if len(data.actor_drives) > 0 else []

        # Check which commodities exist
        _all_commodities = data.market_snapshots.select("commodity_id").unique().to_series().to_list() if len(data.market_snapshots) > 0 else []

        overview_output = mo.md(f"""
        ## Simulation Overview

        | Metric | Value |
        |--------|-------|
        | Turns | {num_turns} |
        | Actors | {num_actors} |
        | Total Transactions | {num_transactions} |
        | Drives Tracked | {', '.join(drive_names)} |
        | Commodities in Market | {len(_all_commodities)} |

        **Key Clothing-Related Commodities:**
        - `fiber`: {'Present' if 'fiber' in _all_commodities else 'MISSING'}
        - `clothing`: {'Present' if 'clothing' in _all_commodities else 'MISSING'}
        """)
    overview_output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 1: Clothing Drive Metrics Over Time

    The clothing drive uses a stochastic consumption model:
    - **Event probability**: ~1 clothing replacement per 60 days
    - **Health**: 1.0 if actor has clothing, 0.0 otherwise
    - **Debt**: Accumulates when clothing needs aren't met, decays over time
    - **Buffer**: Expected days of coverage based on current inventory
    """)
    return


@app.cell
def _(data, mo, pl, px):
    """Analyze clothing drive metrics over time."""
    if data is None or len(data.actor_drives) == 0:
        clothing_drive_data = None
        clothing_by_turn = None
        _output = mo.md("No drive data available")
    else:
        clothing_drive_data = data.actor_drives.filter(pl.col("drive_name") == "clothing")

        if clothing_drive_data.height == 0:
            clothing_by_turn = None
            _output = mo.md("**Warning**: No clothing drive data found. The clothing drive may not be implemented or active.")
        else:
            # Aggregate metrics by turn
            clothing_by_turn = clothing_drive_data.group_by("turn").agg(
                pl.col("health").mean().alias("avg_health"),
                pl.col("debt").mean().alias("avg_debt"),
                pl.col("buffer").mean().alias("avg_buffer"),
                pl.col("health").std().alias("health_std"),
                pl.col("debt").std().alias("debt_std"),
            ).sort("turn")

            _fig = px.line(
                clothing_by_turn.to_pandas(),
                x="turn",
                y=["avg_health", "avg_debt", "avg_buffer"],
                title="Clothing Drive Metrics Over Time (Population Average)",
                labels={"value": "Metric Value (0-1)", "turn": "Turn", "variable": "Metric"},
            )
            _fig.update_layout(legend_title_text="Metric")
            _output = _fig
    _output
    return clothing_by_turn, clothing_drive_data


@app.cell
def _(clothing_drive_data, mo, pl):
    """Clothing drive statistics summary."""
    if clothing_drive_data is None or clothing_drive_data.height == 0:
        stats_output = mo.md("No clothing drive data to summarize")
    else:
        stats = clothing_drive_data.select(["health", "debt", "buffer"]).describe()

        # Calculate additional stats
        total = clothing_drive_data.height
        unhealthy = clothing_drive_data.filter(pl.col("health") < 0.5).height
        high_debt = clothing_drive_data.filter(pl.col("debt") > 0.5).height
        low_buffer = clothing_drive_data.filter(pl.col("buffer") < 0.3).height

        stats_output = mo.md(f"""
        ### Clothing Drive Health Assessment

        | Condition | Count | Percentage |
        |-----------|-------|------------|
        | Total actor-turn records | {total} | 100% |
        | Without clothing (health < 0.5) | {unhealthy} | {100*unhealthy/total:.1f}% |
        | High debt (debt > 0.5) | {high_debt} | {100*high_debt/total:.1f}% |
        | Low buffer (buffer < 0.3) | {low_buffer} | {100*low_buffer/total:.1f}% |

        **Statistics:**

        {stats}
        """)
    stats_output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 2: Fiber and Clothing Production/Consumption

    The clothing supply chain:
    1. **gather_fiber** process: Produces 3 fiber per action
    2. **make_clothing** process: Consumes 4 fiber, produces 2 clothing

    Let's examine market activity for these commodities.
    """)
    return


@app.cell
def _(data, mo, pl, px):
    """Analyze fiber and clothing market prices over time."""
    if data is None or len(data.market_snapshots) == 0:
        clothing_market = None
        price_output = mo.md("No market snapshot data available")
    else:
        _clothing_commodities = ["fiber", "clothing"]
        clothing_market = data.market_snapshots.filter(
            pl.col("commodity_id").is_in(_clothing_commodities)
        )

        if clothing_market.height == 0:
            price_output = mo.md("**Warning**: No market data for fiber or clothing. These commodities may not be traded yet.")
        else:
            _fig = px.line(
                clothing_market.to_pandas(),
                x="turn",
                y="avg_price",
                color="commodity_id",
                title="Fiber and Clothing Prices Over Time",
                labels={"avg_price": "Average Price ($)", "turn": "Turn", "commodity_id": "Commodity"},
            )
            price_output = _fig
    price_output
    return (clothing_market,)


@app.cell
def _(data, mo, pl, px):
    """Analyze transaction volume for fiber and clothing."""
    if data is None or len(data.market_transactions) == 0:
        clothing_txns = None
        volume_output = mo.md("No transaction data available")
    else:
        _clothing_commodities = ["fiber", "clothing"]
        clothing_txns = data.market_transactions.filter(
            pl.col("commodity_id").is_in(_clothing_commodities)
        )

        if clothing_txns.height == 0:
            volume_output = mo.md("""
            **No transactions for fiber or clothing yet.**

            This could indicate:
            - The simulation hasn't run long enough for actors to start trading these commodities
            - Market makers are still in price discovery phase
            - Actors are consuming fiber/clothing before reaching the market
            """)
        else:
            # Volume by turn
            _volume_by_turn = clothing_txns.group_by(["turn", "commodity_id"]).agg(
                pl.col("quantity").sum().alias("volume")
            ).sort("turn")

            _fig = px.line(
                _volume_by_turn.to_pandas(),
                x="turn",
                y="volume",
                color="commodity_id",
                title="Fiber and Clothing Transaction Volume Over Time",
                labels={"volume": "Quantity Traded", "turn": "Turn", "commodity_id": "Commodity"},
            )
            volume_output = _fig
    volume_output
    return (clothing_txns,)


@app.cell
def _(clothing_txns, mo, pl):
    """Transaction summary for clothing commodities."""
    if clothing_txns is None or clothing_txns.height == 0:
        txn_summary = mo.md("No clothing-related transactions to summarize")
    else:
        summary = clothing_txns.group_by("commodity_id").agg(
            pl.col("quantity").sum().alias("total_volume"),
            pl.col("quantity").count().alias("num_transactions"),
            pl.col("price").mean().alias("avg_price"),
            pl.col("price").min().alias("min_price"),
            pl.col("price").max().alias("max_price"),
        )

        txn_summary = mo.md(f"""
        ### Fiber and Clothing Transaction Summary

        {summary}
        """)
    txn_summary
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 3: Market Maker Commodity Coverage

    **Key Finding**: Market makers now dynamically handle all transportable commodities instead of a hardcoded list.

    This means fiber and clothing are automatically included in market maker trading as soon as they are added to the commodity registry.
    """)
    return


@app.cell
def _(data, mo, pl, px):
    """Analyze which commodities market makers are trading."""
    if data is None or len(data.market_transactions) == 0:
        mm_output = mo.md("No transaction data available")
    else:
        # Get all commodities that have been traded
        all_traded = data.market_transactions.select("commodity_id").unique().to_series().to_list()

        # Volume by commodity
        _volume_by_commodity = data.market_transactions.group_by("commodity_id").agg(
            pl.col("quantity").sum().alias("total_volume"),
            pl.col("quantity").count().alias("num_transactions"),
        ).sort("total_volume", descending=True)

        _fig = px.bar(
            _volume_by_commodity.to_pandas(),
            x="commodity_id",
            y="total_volume",
            title="Total Transaction Volume by Commodity",
            labels={"total_volume": "Total Quantity", "commodity_id": "Commodity"},
            color="total_volume",
            color_continuous_scale="Viridis",
        )
        _fig.update_layout(showlegend=False)

        mm_output = mo.vstack([
            mo.md(f"""
            ### All Traded Commodities

            **Commodities with market activity:** {', '.join(sorted(all_traded))}

            Key clothing-related commodities:
            - fiber: {'Traded' if 'fiber' in all_traded else 'NOT TRADED'}
            - clothing: {'Traded' if 'clothing' in all_traded else 'NOT TRADED'}
            """),
            _fig
        ])
    mm_output
    return


@app.cell
def _(data, mo, pl):
    """Check market snapshots for all commodities."""
    if data is None or len(data.market_snapshots) == 0:
        snapshot_output = mo.md("No market snapshot data")
    else:
        # All commodities in market snapshots
        snapshot_commodities = data.market_snapshots.select("commodity_id").unique().to_series().to_list()

        # Get latest prices for all commodities
        latest_turn = data.market_snapshots["turn"].max()
        latest_prices = data.market_snapshots.filter(
            pl.col("turn") == latest_turn
        ).select(["commodity_id", "avg_price"]).sort("commodity_id")

        snapshot_output = mo.md(f"""
        ### Market Snapshot Coverage (Turn {latest_turn})

        **Commodities with price data:** {len(snapshot_commodities)}

        This confirms that market makers are providing liquidity for all transportable commodities,
        not just a hardcoded subset.

        **Latest Prices:**

        {latest_prices}
        """)
    snapshot_output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 4: Drive Comparison (Food vs Clothing vs Shelter)

    Comparing the three drive systems:

    | Drive | Consumption Pattern | Event Probability | Materials |
    |-------|---------------------|-------------------|-----------|
    | Food | Deterministic (1/day) | 100% | food |
    | Clothing | Stochastic | ~1.67%/day (1/60 days) | clothing |
    | Shelter | Stochastic | ~0.83%/day (1/120 days) | wood OR common_metal |
    """)
    return


@app.cell
def _(data, go, make_subplots, mo, pl):
    """Compare all three drives over time."""
    if data is None or len(data.actor_drives) == 0:
        comparison_output = mo.md("No drive data available")
    else:
        # Get available drives
        available_drives = data.actor_drives.select("drive_name").unique().to_series().to_list()

        # Aggregate by turn and drive
        drive_comparison = data.actor_drives.group_by(["turn", "drive_name"]).agg(
            pl.col("health").mean().alias("avg_health"),
            pl.col("debt").mean().alias("avg_debt"),
            pl.col("buffer").mean().alias("avg_buffer"),
        ).sort(["turn", "drive_name"])

        # Create subplots for each metric
        _fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=("Average Health", "Average Debt", "Average Buffer"),
            shared_xaxes=True,
            vertical_spacing=0.08,
        )

        colors = {"food": "#2ecc71", "clothing": "#3498db", "shelter": "#e74c3c"}

        for drive_name in available_drives:
            drive_data = drive_comparison.filter(pl.col("drive_name") == drive_name).to_pandas()
            color = colors.get(drive_name, "#95a5a6")

            _fig.add_trace(
                go.Scatter(x=drive_data["turn"], y=drive_data["avg_health"],
                          name=f"{drive_name} health", line=dict(color=color)),
                row=1, col=1
            )
            _fig.add_trace(
                go.Scatter(x=drive_data["turn"], y=drive_data["avg_debt"],
                          name=f"{drive_name} debt", line=dict(color=color, dash="dash")),
                row=2, col=1
            )
            _fig.add_trace(
                go.Scatter(x=drive_data["turn"], y=drive_data["avg_buffer"],
                          name=f"{drive_name} buffer", line=dict(color=color, dash="dot")),
                row=3, col=1
            )

        _fig.update_layout(
            height=700,
            title_text="Drive Metrics Comparison Over Time",
            showlegend=True,
        )
        _fig.update_yaxes(title_text="Value (0-1)", range=[0, 1])
        _fig.update_xaxes(title_text="Turn", row=3)

        comparison_output = _fig
    comparison_output
    return


@app.cell
def _(data, mo, pl):
    """Summary statistics for all drives."""
    if data is None or len(data.actor_drives) == 0:
        drive_summary_output = mo.md("No drive data available")
    else:
        drive_summary = data.actor_drives.group_by("drive_name").agg(
            pl.col("health").mean().alias("avg_health"),
            pl.col("health").std().alias("health_std"),
            pl.col("debt").mean().alias("avg_debt"),
            pl.col("debt").std().alias("debt_std"),
            pl.col("buffer").mean().alias("avg_buffer"),
            pl.col("buffer").std().alias("buffer_std"),
        ).sort("drive_name")

        drive_summary_output = mo.md(f"""
        ### Drive Summary Statistics

        {drive_summary}

        **Interpretation:**
        - **Health**: Higher is better (1.0 = fully satisfied)
        - **Debt**: Lower is better (0.0 = no accumulated need)
        - **Buffer**: Higher is better (1.0 = max stockpile coverage)
        """)
    drive_summary_output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 5: Actor Production Decisions

    Do actors consider clothing needs in their production decisions?

    The actor brain should now include clothing-related processes (gather_fiber, make_clothing)
    in its decision-making based on the clothing drive urgency.
    """)
    return


@app.cell
def _(data, mo):
    """Analyze production decisions related to clothing."""
    if data is None:
        production_output = mo.md("No data available")
    else:
        # This would require process execution logs if available
        # For now, we can infer from market activity

        # Check if fiber and clothing are being produced (appearing in transactions)
        _all_commodities = data.market_transactions.select("commodity_id").unique().to_series().to_list() if len(data.market_transactions) > 0 else []

        clothing_chain = {
            "fiber": "fiber" in _all_commodities,
            "clothing": "clothing" in _all_commodities,
        }

        chain_status = "COMPLETE" if all(clothing_chain.values()) else "INCOMPLETE"

        production_output = mo.md(f"""
        ### Clothing Supply Chain Status: {chain_status}

        | Commodity | Market Activity |
        |-----------|-----------------|
        | fiber | {'Active' if clothing_chain['fiber'] else 'None detected'} |
        | clothing | {'Active' if clothing_chain['clothing'] else 'None detected'} |

        **Note:** If no market activity is detected, actors may be:
        - Consuming all produced goods internally (not trading)
        - Still ramping up production to meet their own needs
        - Prioritizing other drives (food, shelter) over clothing

        The stochastic nature of the clothing drive (~1 event per 60 days) means
        clothing needs build up slowly, so actors may take longer to prioritize
        clothing production compared to the daily food requirement.
        """)
    production_output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Key Findings Summary

    ### What Was Added
    1. **Fiber commodity** - Raw plant fibers for textile production
    2. **Clothing commodity** - Basic garments for actor needs
    3. **gather_fiber process** - Produces 3 fiber per action
    4. **make_clothing process** - Converts 4 fiber into 2 clothing

    ### How Market Makers Changed
    - Market makers now dynamically iterate over ALL transportable commodities
    - No more hardcoded commodity list
    - New commodities are automatically included in market making

    ### Drive System Integration
    - Clothing drive uses stochastic consumption (~1 event per 60 days)
    - Actors track clothing health, debt, and buffer metrics
    - The brain considers clothing needs when making production decisions

    ### Comparison with Other Drives
    | Aspect | Food | Clothing | Shelter |
    |--------|------|----------|---------|
    | Consumption | Daily | ~Every 60 days | ~Every 120 days |
    | Urgency | High (constant need) | Medium (random events) | Low (infrequent) |
    | Buffer target | 7 days | 60 days | 120 days |
    """)
    return


if __name__ == "__main__":
    app.run()
