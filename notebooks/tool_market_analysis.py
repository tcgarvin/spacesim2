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
    from pathlib import Path

    return Path, SimulationData, go, make_subplots, mo, os, pl, px


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
    # Tool Market Analysis

    This notebook analyzes the tool economy in SpaceSim2, including:
    - Tool production (who is making simple_tools)
    - Tool trading (buy/sell orders and transactions)
    - Tool usage (processes requiring tools)
    - Tool degradation (creating ongoing demand)

    {status_msg}

    {run_selector}
    """)

    return auto_run_path, run_path_str, run_selector, status_msg


@app.cell
def _(Path, SimulationData, mo, run_selector):
    if not run_selector.value:
        mo.md("No run path specified. Run `spacesim2 run` first.")
        data = None
    else:
        try:
            data = SimulationData(Path(run_selector.value))
            mo.md(f"Data loaded successfully")
        except Exception as e:
            mo.md(f"Error loading data: {e}")
            data = None

    return (data,)


@app.cell
def _(data, mo, pl):
    if data is None:
        _overview = mo.md("## Simulation Overview\n\nNo data loaded")
    else:
        _total_turns = (
            data.market_snapshots["turn"].max() if len(data.market_snapshots) > 0 else 0
        )
        _total_transactions = len(data.market_transactions)
        _commodities_traded = (
            data.market_transactions["commodity_id"].n_unique()
            if len(data.market_transactions) > 0
            else 0
        )

        _tools_txns = data.market_transactions.filter(
            pl.col("commodity_id") == "simple_tools"
        )
        _tools_txn_count = len(_tools_txns)
        _tools_volume = _tools_txns["quantity"].sum() if len(_tools_txns) > 0 else 0

        _overview = mo.md(f"""
        ## Simulation Overview

        - **Total Turns:** {_total_turns}
        - **Total Transactions:** {_total_transactions}
        - **Commodities Traded:** {_commodities_traded}
        - **Tool Transactions:** {_tools_txn_count} (volume: {_tools_volume})
        """)
    _overview
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 1. Tool Market Orders

    Are actors placing buy/sell orders for tools? This shows the demand and supply signals.
    """)
    return


@app.cell
def _(data, go, make_subplots, mo, pl):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_snapshots) == 0:
        _result = mo.md("No market snapshot data available")
    else:
        _tools_snaps = data.market_snapshots.filter(
            pl.col("commodity_id") == "simple_tools"
        )

        if len(_tools_snaps) == 0:
            _result = mo.md("No tool market data found")
        else:
            # Aggregate across all planets per turn
            _tools_by_turn = (
                _tools_snaps.group_by("turn")
                .agg(
                    [
                        pl.col("num_buy_orders").sum().alias("total_buy_orders"),
                        pl.col("num_sell_orders").sum().alias("total_sell_orders"),
                        pl.col("best_bid").max().alias("max_bid"),
                        pl.col("best_ask")
                        .filter(pl.col("best_ask") > 0)
                        .min()
                        .alias("min_ask"),
                    ]
                )
                .sort("turn")
            )

            _fig = make_subplots(
                rows=2,
                cols=1,
                subplot_titles=("Tool Order Book Over Time", "Best Bid/Ask Prices"),
                vertical_spacing=0.15,
            )

            _fig.add_trace(
                go.Scatter(
                    x=_tools_by_turn["turn"].to_list(),
                    y=_tools_by_turn["total_buy_orders"].to_list(),
                    name="Buy Orders",
                    mode="lines",
                    line=dict(color="green"),
                ),
                row=1,
                col=1,
            )

            _fig.add_trace(
                go.Scatter(
                    x=_tools_by_turn["turn"].to_list(),
                    y=_tools_by_turn["total_sell_orders"].to_list(),
                    name="Sell Orders",
                    mode="lines",
                    line=dict(color="red"),
                ),
                row=1,
                col=1,
            )

            _fig.add_trace(
                go.Scatter(
                    x=_tools_by_turn["turn"].to_list(),
                    y=_tools_by_turn["max_bid"].to_list(),
                    name="Best Bid",
                    mode="lines",
                    line=dict(color="green", dash="dash"),
                ),
                row=2,
                col=1,
            )

            _fig.add_trace(
                go.Scatter(
                    x=_tools_by_turn["turn"].to_list(),
                    y=_tools_by_turn["min_ask"].to_list(),
                    name="Best Ask",
                    mode="lines",
                    line=dict(color="red", dash="dash"),
                ),
                row=2,
                col=1,
            )

            _fig.update_layout(
                height=600, title_text="Simple Tools Market Activity", showlegend=True
            )
            _fig.update_xaxes(title_text="Turn", row=2, col=1)
            _fig.update_yaxes(title_text="Number of Orders", row=1, col=1)
            _fig.update_yaxes(title_text="Price", row=2, col=1)

            _result = _fig

    _result
    return


@app.cell
def _(data, mo, pl):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_snapshots) == 0:
        _result = mo.md("No market snapshot data")
    else:
        _tools_snaps = data.market_snapshots.filter(
            pl.col("commodity_id") == "simple_tools"
        )
        _total_buy = _tools_snaps["num_buy_orders"].sum()
        _total_sell = _tools_snaps["num_sell_orders"].sum()
        _avg_buy = _tools_snaps["num_buy_orders"].mean()
        _avg_sell = _tools_snaps["num_sell_orders"].mean()
        _max_bid = _tools_snaps["best_bid"].max()
        _min_ask_list = _tools_snaps.filter(pl.col("best_ask") > 0)[
            "best_ask"
        ].to_list()
        _min_ask = min(_min_ask_list) if _min_ask_list else 0

        _result = mo.md(f"""
        ### Tool Order Summary

        | Metric | Buy Side | Sell Side |
        |--------|----------|-----------|
        | Total Orders (all turns) | {_total_buy} | {_total_sell} |
        | Average per snapshot | {_avg_buy:.1f} | {_avg_sell:.1f} |
        | Best Price Seen | Bid: {_max_bid} | Ask: {_min_ask if _min_ask > 0 else "None"} |

        **Key Finding:** {"High demand but no supply - tool production is broken!" if _total_sell == 0 and _total_buy > 0 else "Market appears active" if _total_sell > 0 else "No market activity"}
        """)

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 2. Tool Transactions

    Have any tool trades actually executed?
    """)
    return


@app.cell
def _(data, mo, pl, px):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_transactions) == 0:
        _result = mo.md("No transaction data available")
    else:
        _tools_txns = data.market_transactions.filter(
            pl.col("commodity_id") == "simple_tools"
        )

        if len(_tools_txns) == 0:
            _result = mo.md("""
            ### No Tool Transactions Recorded

            **This is a critical finding.** Despite buy orders being placed, no tools have been traded.

            Possible causes:
            1. No one is producing tools (no sell orders)
            2. Price mismatch between buyers and sellers
            3. Bootstrap path is blocked (missing facilities)
            """)
        else:
            _txn_by_turn = (
                _tools_txns.group_by("turn")
                .agg(
                    [
                        pl.col("quantity").sum().alias("volume"),
                        pl.col("price").mean().alias("avg_price"),
                    ]
                )
                .sort("turn")
            )

            _fig = px.bar(
                _txn_by_turn.to_pandas(),
                x="turn",
                y="volume",
                title="Tool Trading Volume by Turn",
                labels={"volume": "Quantity Traded", "turn": "Turn"},
            )
            _result = _fig

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 3. Facility Supply Chain Analysis

    Tools require a metalworking_facility, which requires common_metal.
    Common_metal requires a smelting_facility.
    Let's check if facilities are being built.
    """)
    return


@app.cell
def _(data, mo, pl, px):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_snapshots) == 0:
        _result = mo.md("No market snapshot data")
    else:
        # Check facility market activity
        _facilities = ["smelting_facility", "metalworking_facility"]
        _facility_snaps = data.market_snapshots.filter(
            pl.col("commodity_id").is_in(_facilities)
        )

        _facility_summary = _facility_snaps.group_by("commodity_id").agg(
            [
                pl.col("num_buy_orders").sum().alias("total_buy_orders"),
                pl.col("num_sell_orders").sum().alias("total_sell_orders"),
            ]
        )

        if len(_facility_summary) > 0:
            _result = mo.vstack(
                [
                    mo.md("""
                ### Facility Market Activity

                Facilities are not traded (they're non-transportable), but let's check if there's any market activity:
                """),
                    mo.ui.table(_facility_summary.to_pandas()),
                ]
            )
        else:
            _result = mo.md("No facility market data found")

    _result
    return


@app.cell
def _(data, go, make_subplots, mo, pl):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_snapshots) == 0:
        _result = mo.md("No market snapshot data")
    else:
        # Check the supply chain commodities
        _supply_chain = [
            "simple_building_materials",
            "common_metal_ore",
            "common_metal",
            "simple_tools",
        ]

        _chain_snaps = data.market_snapshots.filter(
            pl.col("commodity_id").is_in(_supply_chain)
        )

        _chain_by_turn = (
            _chain_snaps.group_by(["turn", "commodity_id"])
            .agg(
                [
                    pl.col("num_buy_orders").sum().alias("buy_orders"),
                    pl.col("num_sell_orders").sum().alias("sell_orders"),
                ]
            )
            .sort("turn")
        )

        _fig = make_subplots(
            rows=2,
            cols=2,
            subplot_titles=[f"{c}" for c in _supply_chain],
            vertical_spacing=0.15,
            horizontal_spacing=0.1,
        )

        for _i, _commodity in enumerate(_supply_chain):
            _row = _i // 2 + 1
            _col = _i % 2 + 1

            _commodity_data = _chain_by_turn.filter(
                pl.col("commodity_id") == _commodity
            )

            if len(_commodity_data) > 0:
                _fig.add_trace(
                    go.Scatter(
                        x=_commodity_data["turn"].to_list(),
                        y=_commodity_data["buy_orders"].to_list(),
                        name=f"{_commodity} Buy",
                        mode="lines",
                        line=dict(color="green"),
                        showlegend=(_i == 0),
                    ),
                    row=_row,
                    col=_col,
                )

                _fig.add_trace(
                    go.Scatter(
                        x=_commodity_data["turn"].to_list(),
                        y=_commodity_data["sell_orders"].to_list(),
                        name=f"{_commodity} Sell",
                        mode="lines",
                        line=dict(color="red"),
                        showlegend=(_i == 0),
                    ),
                    row=_row,
                    col=_col,
                )

        _fig.update_layout(
            height=600,
            title_text="Tool Supply Chain - Buy vs Sell Orders",
            showlegend=True,
        )

        _result = _fig

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 4. Transaction Volume by Commodity

    Which commodities are actually being traded? This helps identify where the supply chain is working vs. broken.
    """)
    return


@app.cell
def _(data, mo, pl, px):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_transactions) == 0:
        _result = mo.md("No transaction data")
    else:
        _volume_by_commodity = (
            data.market_transactions.group_by("commodity_id")
            .agg(
                [
                    pl.col("quantity").sum().alias("total_volume"),
                    pl.col("quantity").count().alias("num_transactions"),
                    pl.col("price").mean().alias("avg_price"),
                ]
            )
            .sort("total_volume", descending=True)
        )

        _fig = px.bar(
            _volume_by_commodity.to_pandas(),
            x="commodity_id",
            y="total_volume",
            title="Total Transaction Volume by Commodity",
            labels={"total_volume": "Total Quantity", "commodity_id": "Commodity"},
            text="total_volume",
        )
        _fig.update_traces(textposition="outside")

        _result = mo.vstack(
            [
                _fig,
                mo.md("### Detailed Transaction Summary"),
                mo.ui.table(_volume_by_commodity.to_pandas()),
            ]
        )

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 5. Tool-Requiring Processes

    These processes require simple_tools. If tools aren't available, these cannot execute.

    | Process | Tools Required | Other Requirements |
    |---------|---------------|-------------------|
    | harvest_wood | simple_tools | - |
    | mine_nova_fuel_ore | simple_tools | - |
    | make_clothing | simple_tools | - |
    | refine_nova_fuel | simple_tools | - |
    """)
    return


@app.cell
def _(data, mo, pl, px):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_transactions) == 0:
        _result = mo.md("No transaction data")
    else:
        # Check for outputs from tool-requiring processes
        _tool_process_outputs = ["wood", "nova_fuel_ore", "clothing", "nova_fuel"]

        _tool_outputs = data.market_transactions.filter(
            pl.col("commodity_id").is_in(_tool_process_outputs)
        )

        if len(_tool_outputs) == 0:
            _result = mo.md("""
            ### No Output from Tool-Requiring Processes

            None of these commodities appear in transactions:
            - wood (from harvest_wood)
            - nova_fuel_ore (from mine_nova_fuel_ore)
            - clothing (from make_clothing)
            - nova_fuel (from refine_nova_fuel)

            **This confirms that actors cannot execute tool-requiring processes** because they don't have tools.
            """)
        else:
            _output_volume = (
                _tool_outputs.group_by("commodity_id")
                .agg(
                    [
                        pl.col("quantity").sum().alias("total_volume"),
                    ]
                )
                .sort("total_volume", descending=True)
            )

            _fig = px.bar(
                _output_volume.to_pandas(),
                x="commodity_id",
                y="total_volume",
                title="Transaction Volume from Tool-Requiring Processes",
                labels={"total_volume": "Total Quantity", "commodity_id": "Commodity"},
            )
            _result = _fig

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 6. Common Metal Analysis

    Common metal is required to make tools. Is it being produced and traded?
    """)
    return


@app.cell
def _(data, go, make_subplots, mo, pl):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_transactions) == 0:
        _result = mo.md("No transaction data")
    else:
        _metal_chain = ["common_metal_ore", "common_metal"]

        _metal_txns = data.market_transactions.filter(
            pl.col("commodity_id").is_in(_metal_chain)
        )

        if len(_metal_txns) == 0:
            _result = mo.md("No common metal or ore transactions found")
        else:
            _metal_by_turn = (
                _metal_txns.group_by(["turn", "commodity_id"])
                .agg(
                    [
                        pl.col("quantity").sum().alias("volume"),
                    ]
                )
                .sort("turn")
            )

            _fig = make_subplots(rows=1, cols=1)

            for _commodity in _metal_chain:
                _commodity_data = _metal_by_turn.filter(
                    pl.col("commodity_id") == _commodity
                )
                if len(_commodity_data) > 0:
                    _fig.add_trace(
                        go.Scatter(
                            x=_commodity_data["turn"].to_list(),
                            y=_commodity_data["volume"].to_list(),
                            name=_commodity,
                            mode="lines",
                        )
                    )

            _fig.update_layout(
                title="Common Metal Supply Chain Transactions",
                xaxis_title="Turn",
                yaxis_title="Volume",
            )

            _ore_vol = _metal_txns.filter(pl.col("commodity_id") == "common_metal_ore")[
                "quantity"
            ].sum()
            _metal_vol = _metal_txns.filter(pl.col("commodity_id") == "common_metal")[
                "quantity"
            ].sum()

            _result = mo.vstack(
                [
                    _fig,
                    mo.md(f"""
                ### Metal Supply Chain Summary

                - **Common Metal Ore Traded:** {_ore_vol}
                - **Common Metal Traded:** {_metal_vol}

                Note: Refining ore to metal requires a smelting_facility. If ore is being traded
                but refined metal is scarce, actors may be stockpiling ore without facilities.
                """),
                ]
            )

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 7. Bootstrap Path Analysis

    The tool production bootstrap path is:

    1. **gather_building_materials** -> simple_building_materials (no requirements)
    2. **build_smelting_facility** -> smelting_facility (5 building materials)
    3. **mine_common_metal_ore** -> common_metal_ore (no requirements)
    4. **refine_common_metal** -> common_metal (requires smelting_facility)
    5. **build_metalworking_facility** -> metalworking_facility (5 building materials)
    6. **make_simple_tools** -> simple_tools (requires metalworking_facility, 2 common_metal)

    Let's check which stages are being executed.
    """)
    return


@app.cell
def _(data, mo, pl):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_transactions) == 0:
        _result = mo.md("No transaction data")
    else:
        # Check each stage's output commodity
        _bootstrap_commodities = [
            ("simple_building_materials", "Stage 1: Gathering materials"),
            ("smelting_facility", "Stage 2: Building smelters"),
            ("common_metal_ore", "Stage 3: Mining ore"),
            ("common_metal", "Stage 4: Refining metal"),
            ("metalworking_facility", "Stage 5: Building workshops"),
            ("simple_tools", "Stage 6: Making tools"),
        ]

        _results = []
        for _commodity, _stage in _bootstrap_commodities:
            _txns = data.market_transactions.filter(
                pl.col("commodity_id") == _commodity
            )
            _volume = _txns["quantity"].sum() if len(_txns) > 0 else 0
            _count = len(_txns)
            _results.append(
                {
                    "Stage": _stage,
                    "Commodity": _commodity,
                    "Transactions": _count,
                    "Volume": _volume,
                }
            )

        _df = pl.DataFrame(_results)

        _result = mo.vstack(
            [
                mo.md("### Bootstrap Path Status"),
                mo.ui.table(_df.to_pandas()),
                mo.md("""
            **Interpretation:**
            - Stages with 0 volume are blocked
            - Facilities (smelting/metalworking) won't appear in transactions (non-transportable)
            - If Stage 4 (refining) shows low volume, smelting facilities aren't being built
            - If Stage 6 (tools) shows 0 volume, metalworking facilities aren't available
            """),
            ]
        )

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 8. Price Trends for Key Commodities

    How are prices evolving for the tool supply chain?
    """)
    return


@app.cell
def _(data, mo, pl, px):
    if data is None:
        _result = mo.md("No data loaded")
    elif len(data.market_snapshots) == 0:
        _result = mo.md("No market snapshot data")
    else:
        _key_commodities = [
            "simple_building_materials",
            "common_metal_ore",
            "common_metal",
            "simple_tools",
        ]

        _price_data = data.market_snapshots.filter(
            pl.col("commodity_id").is_in(_key_commodities)
        ).filter(pl.col("avg_price") > 0)

        if len(_price_data) == 0:
            _result = mo.md("No price data available for key commodities")
        else:
            _avg_prices = (
                _price_data.group_by(["turn", "commodity_id"])
                .agg([pl.col("avg_price").mean().alias("price")])
                .sort("turn")
            )

            _fig = px.line(
                _avg_prices.to_pandas(),
                x="turn",
                y="price",
                color="commodity_id",
                title="Price Trends for Tool Supply Chain Commodities",
                labels={
                    "price": "Average Price",
                    "turn": "Turn",
                    "commodity_id": "Commodity",
                },
            )

            _result = _fig

    _result
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Conclusions

    Based on this analysis:

    1. **Tool Demand Exists:** Actors are placing buy orders for simple_tools, indicating they understand they need them.

    2. **Tool Supply is Missing:** No sell orders for tools means no one is producing them.

    3. **Bootstrap Path Appears Blocked:** The supply chain from building materials -> facilities -> refined metal -> tools isn't completing.

    4. **Likely Root Causes:**
       - Industrialists may not be prioritizing facility construction
       - The 5-turn labor requirement for facilities may be too long
       - Colonists can't make tools without facilities they don't have

    **Recommendations:**
    - Examine actor decision logs to see why facilities aren't being built
    - Consider reducing facility construction labor requirements
    - Verify industrialist brain is correctly scoring facility-building processes
    """)
    return


if __name__ == "__main__":
    app.run()
