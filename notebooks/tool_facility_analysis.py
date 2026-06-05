import marimo

__generated_with = "0.18.1"
app = marimo.App()


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
    from pathlib import Path

    return Path, SimulationData, go, json, make_subplots, mo, os, pl, px


@app.cell
def _(mo, os, Path):
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
    # Tool and Facility Economy Analysis

    This notebook analyzes whether the tool and facility system is working as designed:

    - **Facility building**: Actors should build smelting_facility and metalworking_facility
    - **Tool requirements**: Processes like harvest_wood, make_clothing require simple_tools
    - **Tool degradation**: ~1% chance of tools breaking per use creates ongoing demand
    - **Bootstrap path**: Actors should be able to start from nothing and build up

    ---

    {status_msg}

    {run_selector}
    """)

    return (run_selector,)


@app.cell
def _(Path, SimulationData, mo, run_selector):
    if not run_selector.value:
        _output = mo.md("No run path specified. Run `spacesim2 run` first.")
        data = None
    else:
        try:
            data = SimulationData(Path(run_selector.value))
            _output = mo.md(f"Data loaded successfully from: {run_selector.value}")
        except FileNotFoundError as e:
            _output = mo.md(f"Error loading data: {e}")
            data = None

    _output
    return (data,)


@app.cell
def _(data, mo):
    if data is None:
        _output = mo.md("## Simulation Overview\n\nNo data loaded")
    else:
        _total_turns = (
            data.actor_turns["turn"].max() if len(data.actor_turns) > 0 else 0
        )
        _num_actors = (
            data.actor_turns["actor_id"].n_unique() if len(data.actor_turns) > 0 else 0
        )
        _num_transactions = len(data.market_transactions)

        _output = mo.md(f"""
        ## Simulation Overview
        - **Turns simulated:** {_total_turns}
        - **Actors tracked:** {_num_actors}
        - **Total transactions:** {_num_transactions}
        """)

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 1. Tool and Facility Market Activity

    This section analyzes market transactions for tools and facilities to understand:
    - When these items start being traded
    - Volume of production and consumption
    - Price trends over time
    """)
    return


@app.cell
def _(data, mo, pl, px):
    # Analyze transactions for tool/facility related commodities
    TOOL_FACILITY_COMMODITIES = [
        "simple_tools",
        "smelting_facility",
        "metalworking_facility",
        "common_metal",
        "common_metal_ore",
        "simple_building_materials",
    ]

    if data is None or len(data.market_transactions) == 0:
        _output = mo.md("No transaction data available")
    else:
        # Filter to tool/facility commodities
        _tool_txns = data.market_transactions.filter(
            pl.col("commodity_id").is_in(TOOL_FACILITY_COMMODITIES)
        )

        if len(_tool_txns) == 0:
            _output = mo.md(
                "**No transactions found for tool/facility commodities.** This may indicate the bootstrap path is not working - actors are not producing or trading these items."
            )
        else:
            # Aggregate by turn and commodity
            _volume_by_turn = (
                _tool_txns.group_by(["turn", "commodity_id"])
                .agg(
                    pl.col("quantity").sum().alias("volume"),
                    pl.col("price").mean().alias("avg_price"),
                )
                .sort("turn")
            )

            _output = px.line(
                _volume_by_turn.to_pandas(),
                x="turn",
                y="volume",
                color="commodity_id",
                title="Tool/Facility Transaction Volume Over Time",
                labels={
                    "volume": "Units Traded",
                    "turn": "Turn",
                    "commodity_id": "Commodity",
                },
            )

    _output
    return (TOOL_FACILITY_COMMODITIES,)


@app.cell
def _(TOOL_FACILITY_COMMODITIES, data, mo, pl, px):
    # Price trends for tool/facility commodities
    if data is None or len(data.market_snapshots) == 0:
        _output = mo.md("No market snapshot data available")
    else:
        _tool_snapshots = data.market_snapshots.filter(
            pl.col("commodity_id").is_in(TOOL_FACILITY_COMMODITIES)
        )

        if len(_tool_snapshots) == 0:
            _output = mo.md("No market data for tool/facility commodities")
        else:
            _fig = px.line(
                _tool_snapshots.to_pandas(),
                x="turn",
                y="avg_price",
                color="commodity_id",
                facet_col="planet_name",
                facet_col_wrap=3,
                title="Tool/Facility Prices by Planet",
                labels={"avg_price": "Average Price", "turn": "Turn"},
            )
            _fig.update_layout(height=600)
            _output = _fig

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 2. Tool Production and Consumption Analysis

    Tracking simple_tools specifically to understand:
    - Production rate (sell transactions)
    - Consumption/acquisition rate (buy transactions)
    - Whether degradation creates ongoing demand
    """)
    return


@app.cell
def _(data, go, make_subplots, mo, pl):
    if data is None or len(data.market_transactions) == 0:
        _output = mo.md("No transaction data available")
    else:
        _tool_txns = data.market_transactions.filter(
            pl.col("commodity_id") == "simple_tools"
        )

        if len(_tool_txns) == 0:
            _output = mo.md("""
            **No simple_tools transactions found.**

            This indicates a potential issue with the bootstrap path:
            - Actors may not be building metalworking facilities
            - Or the production chain is broken somewhere
            """)
        else:
            # Analyze buy vs sell patterns
            _tools_per_turn = (
                _tool_txns.group_by("turn")
                .agg(
                    [
                        pl.col("quantity").sum().alias("total_volume"),
                        pl.col("price").mean().alias("avg_price"),
                        pl.len().alias("num_transactions"),
                    ]
                )
                .sort("turn")
            )

            # Cumulative tools traded
            _tools_per_turn = _tools_per_turn.with_columns(
                pl.col("total_volume").cum_sum().alias("cumulative_volume")
            )

            _fig = make_subplots(
                rows=2,
                cols=1,
                subplot_titles=("Tools Traded Per Turn", "Cumulative Tools Traded"),
                vertical_spacing=0.15,
            )

            _tools_pd = _tools_per_turn.to_pandas()

            _fig.add_trace(
                go.Bar(x=_tools_pd["turn"], y=_tools_pd["total_volume"], name="Volume"),
                row=1,
                col=1,
            )

            _fig.add_trace(
                go.Scatter(
                    x=_tools_pd["turn"],
                    y=_tools_pd["cumulative_volume"],
                    mode="lines",
                    name="Cumulative",
                ),
                row=2,
                col=1,
            )

            _fig.update_layout(height=500, title_text="Simple Tools Trading Activity")
            _output = _fig

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 3. Facility Construction Analysis

    Tracking when smelting and metalworking facilities are first produced and traded.
    """)
    return


@app.cell
def _(data, mo, pl):
    if data is None or len(data.market_transactions) == 0:
        _output = mo.md("No transaction data available")
    else:
        _facility_types = ["smelting_facility", "metalworking_facility"]
        _facility_txns = data.market_transactions.filter(
            pl.col("commodity_id").is_in(_facility_types)
        )

        if len(_facility_txns) == 0:
            _output = mo.md("""
            **No facility transactions found.**

            Facilities are not transportable and typically not traded between actors.
            This is expected behavior - actors build facilities for their own use.

            We need to look at inventory data to see facility ownership.
            """)
        else:
            # First transaction per facility type
            _first_txns = _facility_txns.group_by("commodity_id").agg(
                [
                    pl.col("turn").min().alias("first_traded_turn"),
                    pl.col("quantity").sum().alias("total_traded"),
                    pl.col("price").mean().alias("avg_price"),
                ]
            )

            _output = mo.md(f"""
            ### Facility Trading Summary

            {_first_txns.to_pandas().to_markdown(index=False)}
            """)

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 4. Actor Inventory Analysis - Tools and Facilities

    Parsing actor inventory data to track:
    - Which actors have tools
    - Which actors have facilities
    - Inventory levels over time
    """)
    return


@app.cell
def _(data, json, mo, pl, px):
    if data is None or len(data.actor_turns) == 0:
        _output = mo.md("No actor turn data available")
    else:
        # Parse inventory JSON to extract tool/facility counts
        def _parse_inventory(inv_json: str) -> dict:
            """Parse inventory JSON and return counts of relevant items."""
            try:
                inv = json.loads(inv_json) if inv_json else {}
                return {
                    "simple_tools": inv.get("simple_tools", 0),
                    "smelting_facility": inv.get("smelting_facility", 0),
                    "metalworking_facility": inv.get("metalworking_facility", 0),
                    "common_metal": inv.get("common_metal", 0),
                    "common_metal_ore": inv.get("common_metal_ore", 0),
                }
            except json.JSONDecodeError:
                return {
                    "simple_tools": 0,
                    "smelting_facility": 0,
                    "metalworking_facility": 0,
                    "common_metal": 0,
                    "common_metal_ore": 0,
                }

        # Apply parsing to all rows
        _parsed = []
        for row in data.actor_turns.iter_rows(named=True):
            inv = _parse_inventory(row["inventory_json"])
            _parsed.append(
                {
                    "turn": row["turn"],
                    "actor_id": row["actor_id"],
                    "actor_name": row["actor_name"],
                    **inv,
                }
            )

        _inv_df = pl.DataFrame(_parsed)

        # Aggregate across all actors per turn
        _agg_inv = (
            _inv_df.group_by("turn")
            .agg(
                [
                    pl.col("simple_tools").sum().alias("total_tools"),
                    pl.col("smelting_facility").sum().alias("total_smelting"),
                    pl.col("metalworking_facility").sum().alias("total_metalworking"),
                    pl.col("common_metal").sum().alias("total_metal"),
                    pl.col("common_metal_ore").sum().alias("total_ore"),
                ]
            )
            .sort("turn")
        )

        # Melt for plotting
        _melted = _agg_inv.unpivot(
            index="turn",
            on=[
                "total_tools",
                "total_smelting",
                "total_metalworking",
                "total_metal",
                "total_ore",
            ],
            variable_name="commodity",
            value_name="quantity",
        )

        _output = px.line(
            _melted.to_pandas(),
            x="turn",
            y="quantity",
            color="commodity",
            title="Total Inventory of Tools and Facilities Across All Actors",
            labels={"quantity": "Total Quantity", "turn": "Turn"},
        )

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 5. Bootstrap Path Verification

    The expected bootstrap path is:
    1. Mine common metal ore (no tools needed)
    2. Gather building materials (no tools needed)
    3. Build smelting facility (needs building materials)
    4. Refine metal at smelting facility
    5. Build metalworking facility (needs building materials)
    6. Make simple tools at metalworking facility
    7. Use tools for advanced processes

    We verify this by looking at the order of first transactions/production.
    """)
    return


@app.cell
def _(data, mo, pl):
    if data is None or len(data.market_transactions) == 0:
        _output = mo.md("No transaction data available")
    else:
        # Track first appearance of each commodity in transactions
        _bootstrap_commodities = [
            "common_metal_ore",
            "simple_building_materials",
            "common_metal",
            "smelting_facility",
            "metalworking_facility",
            "simple_tools",
            "wood",
            "nova_fuel_ore",
            "clothing",
        ]

        _first_appearances = []
        for commodity in _bootstrap_commodities:
            _txns = data.market_transactions.filter(pl.col("commodity_id") == commodity)
            if len(_txns) > 0:
                _first_turn = _txns["turn"].min()
                _total_volume = _txns["quantity"].sum()
                _first_appearances.append(
                    {
                        "commodity": commodity,
                        "first_traded_turn": _first_turn,
                        "total_volume": _total_volume,
                    }
                )
            else:
                _first_appearances.append(
                    {
                        "commodity": commodity,
                        "first_traded_turn": None,
                        "total_volume": 0,
                    }
                )

        _bootstrap_df = pl.DataFrame(_first_appearances).sort(
            "first_traded_turn", nulls_last=True
        )

        _output = mo.md(f"""
        ### Bootstrap Path Timeline

        This table shows when each commodity first appeared in market transactions:

        {_bootstrap_df.to_pandas().to_markdown(index=False)}

        **Expected order** (based on dependencies):
        1. common_metal_ore, simple_building_materials (no prereqs)
        2. common_metal (needs smelting_facility + ore)
        3. simple_tools (needs metalworking_facility + metal)
        4. wood, clothing, nova_fuel_ore (need simple_tools)

        **Interpretation:**
        - If simple_tools never appears, the industrial chain is broken
        - If wood/clothing/nova_fuel_ore never appear, tool-requiring processes are not running
        - Commodities with first_traded_turn=None are never traded
        """)

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 6. Process Execution Patterns

    Analyzing which processes are being executed successfully based on transaction patterns.
    We can infer process execution from output commodities appearing in transactions.
    """)
    return


@app.cell
def _(data, mo, pl, px):
    if data is None or len(data.market_transactions) == 0:
        _output = mo.md("No transaction data available")
    else:
        # Map commodities to their source processes
        OUTPUT_TO_PROCESS = {
            "biomass": "gather_biomass",
            "food": "make_food",
            "fiber": "gather_fiber",
            "clothing": "make_clothing (requires tools)",
            "wood": "harvest_wood (requires tools)",
            "common_metal_ore": "mine_common_metal_ore",
            "nova_fuel_ore": "mine_nova_fuel_ore (requires tools)",
            "common_metal": "refine_common_metal (requires smelting_facility)",
            "nova_fuel": "refine_nova_fuel (requires tools)",
            "simple_tools": "make_simple_tools (requires metalworking_facility)",
            "simple_building_materials": "gather_building_materials",
            "smelting_facility": "build_smelting_facility",
            "metalworking_facility": "build_metalworking_facility",
        }

        # Calculate total volume per commodity (as proxy for process execution)
        _volume_by_commodity = (
            data.market_transactions.group_by("commodity_id")
            .agg(pl.col("quantity").sum().alias("total_volume"))
            .sort("total_volume", descending=True)
        )

        # Add process info
        _volume_by_commodity = _volume_by_commodity.with_columns(
            pl.col("commodity_id")
            .replace(OUTPUT_TO_PROCESS, default="unknown")
            .alias("likely_process")
        )

        _fig = px.bar(
            _volume_by_commodity.to_pandas(),
            x="commodity_id",
            y="total_volume",
            color="likely_process",
            title="Total Transaction Volume by Commodity (Indicates Process Execution)",
            labels={"total_volume": "Total Volume Traded", "commodity_id": "Commodity"},
            hover_data=["likely_process"],
        )
        _fig.update_layout(xaxis_tickangle=-45, height=500)
        _output = _fig

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 7. Summary and Findings
    """)
    return


@app.cell
def _(data, mo, pl):
    if data is None:
        _output = mo.md("No data to summarize")
    else:
        # Calculate key metrics
        _tool_txns = data.market_transactions.filter(
            pl.col("commodity_id") == "simple_tools"
        )
        _has_tools = len(_tool_txns) > 0
        _tools_volume = _tool_txns["quantity"].sum() if _has_tools else 0

        _wood_txns = data.market_transactions.filter(pl.col("commodity_id") == "wood")
        _has_wood = len(_wood_txns) > 0

        _clothing_txns = data.market_transactions.filter(
            pl.col("commodity_id") == "clothing"
        )
        _has_clothing = len(_clothing_txns) > 0

        _metal_txns = data.market_transactions.filter(
            pl.col("commodity_id") == "common_metal"
        )
        _has_metal = len(_metal_txns) > 0

        # Build assessment
        _findings = []

        if _has_tools:
            _findings.append(
                f"- **Tools are being produced**: {_tools_volume} simple_tools traded"
            )
        else:
            _findings.append(
                "- **ISSUE: No tools being traded** - metalworking chain may be broken"
            )

        if _has_metal:
            _findings.append(
                "- **Metal refining working**: common_metal is being traded"
            )
        else:
            _findings.append(
                "- **ISSUE: No metal being traded** - smelting chain may be broken"
            )

        if _has_wood:
            _findings.append(
                "- **Tool-requiring processes working**: wood is being harvested"
            )
        else:
            _findings.append(
                "- **Note**: No wood being traded - harvest_wood requires tools"
            )

        if _has_clothing:
            _findings.append(
                "- **Clothing production working**: clothing is being traded"
            )
        else:
            _findings.append(
                "- **Note**: No clothing being traded - make_clothing requires tools"
            )

        _output = mo.md(f"""
        ### Key Findings

        {chr(10).join(_findings)}

        ### Recommendations

        If tools or facilities are not appearing:
        1. Check that actors are choosing facility-building processes
        2. Verify building_materials are available
        3. Check that industrialist brains are working correctly
        4. Run with `--verbose` to see actor decision logs
        """)

    _output
    return


if __name__ == "__main__":
    app.run()
