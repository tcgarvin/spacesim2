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
    from spacesim2.analysis.loading.loader import SimulationData
    from pathlib import Path
    return Path, SimulationData, go, json, mo, os, pl, px


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
    # Planet Specialization Analysis

    This notebook investigates whether the planet attribute system creates meaningful
    economic differentiation across planets, and whether traders exploit these differences.

    **Key Questions:**
    1. Do planets with high resource attributes produce more of those commodities?
    2. Are there consistent trade routes from producing to consuming planets?
    3. Do price differentials reflect resource scarcity/abundance?

    ---

    {status_msg}

    {run_selector}
    """)

    return (run_selector,)


@app.cell
def _(Path, SimulationData, json, mo, run_selector):
    # Load simulation data and planet attributes
    if not run_selector.value:
        _status_output = mo.md("No run path specified. Run a simulation with --planet-attributes first.")
        data = None
        planet_attrs = {}
    else:
        try:
            _run_path = Path(run_selector.value)
            data = SimulationData(_run_path)

            # Load planet attributes
            _attrs_path = _run_path / "planet_attributes.json"
            if _attrs_path.exists():
                with open(_attrs_path) as _f:
                    planet_attrs = json.load(_f)
                _status = f"Loaded data: {len(data.market_transactions):,} transactions, {len(planet_attrs)} planets with attributes"
            else:
                planet_attrs = {}
                _status = "Warning: planet_attributes.json not found - was --planet-attributes enabled?"

            _status_output = mo.md(f"**Data Status:** {_status}")
        except Exception as e:
            _status_output = mo.md(f"Error loading data: {e}")
            data = None
            planet_attrs = {}

    _status_output
    return data, planet_attrs


@app.cell
def _(mo, planet_attrs, pl):
    # Display planet attributes as a table
    if not planet_attrs:
        _output = mo.md("## Planet Attributes\n\nNo planet attributes data available.")
        attrs_df = None
    else:
        # Convert to DataFrame for display
        _rows = []
        for _planet, _attrs in planet_attrs.items():
            _row = {"planet": _planet}
            _row.update(_attrs)
            _rows.append(_row)

        attrs_df = pl.DataFrame(_rows)

        # Format for display
        _display_df = attrs_df.select([
            pl.col("planet"),
            pl.col("biomass").round(2),
            pl.col("fiber").round(2),
            pl.col("wood").round(2),
            pl.col("common_metal_ore").round(2),
            pl.col("nova_fuel_ore").round(2),
            pl.col("simple_building_materials").round(2),
        ])

        _output = mo.md(f"""
        ## Planet Resource Attributes

        Each planet has randomly generated resource availability (0.0 to 1.0).
        Higher values mean more output from gathering/mining processes.

        {mo.ui.table(_display_df.to_pandas())}
        """)

    _output
    return (attrs_df,)


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 1: Production vs Resource Attributes

    Do planets with higher resource attributes actually produce more of those commodities?
    We measure production by looking at sell transactions from colonists/industrialists
    (excluding market makers and traders).
    """)
    return


@app.cell
def _(data, mo, pl):
    # Calculate production by planet and commodity
    # Production = what local actors sell (colonists, industrialists)
    if data is None or len(data.market_transactions) == 0:
        _output = mo.md("No transaction data available")
        production_by_planet = None
    else:
        # Filter to local sellers (not Trader, not MarketMaker)
        _local_sells = data.market_transactions.filter(
            ~pl.col("seller_name").str.contains("Trader") &
            ~pl.col("seller_name").str.contains("MarketMaker")
        )

        # Group by planet and commodity
        production_by_planet = _local_sells.group_by(["planet_name", "commodity_id"]).agg([
            pl.col("quantity").sum().alias("total_produced"),
            pl.col("price").mean().alias("avg_sell_price"),
        ]).sort(["planet_name", "total_produced"], descending=[False, True])

        _output = mo.md(f"""
        **Production Summary:**
        - Total local transactions analyzed: {len(_local_sells):,}
        - Unique planet-commodity pairs: {len(production_by_planet)}
        """)

    _output
    return (production_by_planet,)


@app.cell
def _(attrs_df, go, mo, pl, production_by_planet):
    # Correlate production with resource attributes
    if production_by_planet is None or attrs_df is None:
        _output = mo.md("Cannot compute correlations - missing data")
        correlation_results = None
    else:
        # Map commodity to its resource attribute
        _commodity_to_attr = {
            "biomass": "biomass",
            "food": "biomass",  # Food depends on biomass
            "fiber": "fiber",
            "clothing": "fiber",  # Clothing depends on fiber
            "wood": "wood",
            "common_metal_ore": "common_metal_ore",
            "common_metal": "common_metal_ore",  # Metal depends on ore
            "nova_fuel_ore": "nova_fuel_ore",
            "nova_fuel": "nova_fuel_ore",  # Fuel depends on ore
            "simple_building_materials": "simple_building_materials",
        }

        # Build correlation data
        _corr_data = []

        for _commodity, _attr_name in _commodity_to_attr.items():
            # Get production for this commodity
            _prod = production_by_planet.filter(pl.col("commodity_id") == _commodity)
            if len(_prod) == 0:
                continue

            # Join with attributes
            _joined = _prod.join(
                attrs_df.select(["planet", _attr_name]).rename({"planet": "planet_name"}),
                on="planet_name",
                how="left"
            )

            if len(_joined) < 3:
                continue

            # Calculate correlation
            _values = _joined.select([
                pl.col("total_produced").cast(pl.Float64),
                pl.col(_attr_name).cast(pl.Float64)
            ]).drop_nulls()

            if len(_values) >= 3:
                _prod_vals = _values["total_produced"].to_list()
                _attr_vals = _values[_attr_name].to_list()

                # Manual correlation calculation
                _n = len(_prod_vals)
                _mean_prod = sum(_prod_vals) / _n
                _mean_attr = sum(_attr_vals) / _n

                _num = sum((p - _mean_prod) * (a - _mean_attr) for p, a in zip(_prod_vals, _attr_vals))
                _denom_prod = sum((p - _mean_prod) ** 2 for p in _prod_vals) ** 0.5
                _denom_attr = sum((a - _mean_attr) ** 2 for a in _attr_vals) ** 0.5

                if _denom_prod > 0 and _denom_attr > 0:
                    _corr = _num / (_denom_prod * _denom_attr)
                else:
                    _corr = 0.0

                _corr_data.append({
                    "commodity": _commodity,
                    "resource_attribute": _attr_name,
                    "correlation": round(_corr, 3),
                    "n_planets": _n,
                    "interpretation": "Strong positive" if _corr > 0.5 else ("Moderate" if _corr > 0.2 else ("Weak/None" if _corr > -0.2 else "Negative"))
                })

        correlation_results = pl.DataFrame(_corr_data)

        # Create visualization
        _fig = go.Figure()

        _fig.add_trace(go.Bar(
            x=correlation_results["commodity"].to_list(),
            y=correlation_results["correlation"].to_list(),
            marker_color=[
                "green" if c > 0.5 else ("yellow" if c > 0.2 else ("orange" if c > -0.2 else "red"))
                for c in correlation_results["correlation"].to_list()
            ],
            text=[f"{c:.2f}" for c in correlation_results["correlation"].to_list()],
            textposition="outside"
        ))

        _fig.update_layout(
            title="Correlation: Production vs Resource Attributes",
            xaxis_title="Commodity",
            yaxis_title="Correlation Coefficient",
            yaxis_range=[-1, 1],
            showlegend=False
        )

        _fig.add_hline(y=0.5, line_dash="dash", line_color="green", annotation_text="Strong positive threshold")
        _fig.add_hline(y=0, line_dash="solid", line_color="gray")

        _ = mo.md(f"""
        ### Production-Attribute Correlations

        This chart shows how strongly each commodity's production correlates with its
        corresponding planet resource attribute.

        - **Green (>0.5):** Strong positive correlation - attributes drive production
        - **Yellow (0.2-0.5):** Moderate correlation
        - **Orange (-0.2 to 0.2):** Weak or no correlation
        - **Red (<-0.2):** Negative correlation
        """)

        _output = _fig

    _output
    return (correlation_results,)


@app.cell
def _(correlation_results, mo):
    # Display correlation table
    if correlation_results is not None and len(correlation_results) > 0:
        _output = mo.md(f"""
        ### Correlation Details

        {mo.ui.table(correlation_results.to_pandas())}

        **Key Insight:** Look for commodities with strong positive correlations (>0.5).
        These indicate the planet attribute system is successfully driving specialization.
        """)
    else:
        _output = mo.md("No correlation data to display.")

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 2: Trade Flow Analysis

    Do traders move goods from high-producing planets to consuming planets?
    We analyze where traders buy vs sell to identify trade routes.
    """)
    return


@app.cell
def _(data, mo, pl):
    # Analyze trader transactions
    if data is None or len(data.market_transactions) == 0:
        _output = mo.md("No transaction data available")
        trader_flows = None
    else:
        # Get trader buy transactions
        _trader_buys = data.market_transactions.filter(
            pl.col("buyer_name").str.contains("Trader")
        ).select([
            pl.col("buyer_name").alias("trader"),
            pl.col("planet_name").alias("buy_planet"),
            pl.col("commodity_id"),
            pl.col("quantity"),
            pl.col("price").alias("buy_price"),
            pl.col("turn")
        ])

        # Get trader sell transactions
        _trader_sells = data.market_transactions.filter(
            pl.col("seller_name").str.contains("Trader")
        ).select([
            pl.col("seller_name").alias("trader"),
            pl.col("planet_name").alias("sell_planet"),
            pl.col("commodity_id"),
            pl.col("quantity"),
            pl.col("price").alias("sell_price"),
            pl.col("turn")
        ])

        # Summarize by trader: where they buy and where they sell
        _buy_summary = _trader_buys.group_by(["trader", "buy_planet", "commodity_id"]).agg([
            pl.col("quantity").sum().alias("qty_bought"),
            pl.col("buy_price").mean().alias("avg_buy_price")
        ])

        _sell_summary = _trader_sells.group_by(["trader", "sell_planet", "commodity_id"]).agg([
            pl.col("quantity").sum().alias("qty_sold"),
            pl.col("sell_price").mean().alias("avg_sell_price")
        ])

        # Find trade routes: where does each trader buy vs sell
        trader_flows = {
            "buy_summary": _buy_summary,
            "sell_summary": _sell_summary,
            "buy_count": len(_trader_buys),
            "sell_count": len(_trader_sells)
        }

        _output = mo.md(f"""
        **Trader Activity:**
        - Trader buy transactions: {len(_trader_buys):,}
        - Trader sell transactions: {len(_trader_sells):,}
        - Active traders: {_trader_buys['trader'].n_unique() if len(_trader_buys) > 0 else 0}
        """)

    _output
    return (trader_flows,)


@app.cell
def _(go, mo, pl, trader_flows):
    # Visualize trade flows as a Sankey diagram
    if trader_flows is None:
        _output = mo.md("No trader flow data available")
    else:
        # Aggregate buy->sell flows
        _buy_summary = trader_flows["buy_summary"]
        _sell_summary = trader_flows["sell_summary"]

        # For each trader, find their primary buy planet and primary sell planet
        _routes = []

        _traders = _buy_summary["trader"].unique().to_list() if len(_buy_summary) > 0 else []
        for _t in _traders:
            # Get top buy planet for this trader
            _t_buys = _buy_summary.filter(pl.col("trader") == _t).sort("qty_bought", descending=True)
            _t_sells = _sell_summary.filter(pl.col("trader") == _t).sort("qty_sold", descending=True)

            if len(_t_buys) > 0 and len(_t_sells) > 0:
                _buy_planet = _t_buys["buy_planet"][0]
                _sell_planet = _t_sells["sell_planet"][0]
                _qty = min(_t_buys["qty_bought"][0], _t_sells["qty_sold"][0])

                if _buy_planet != _sell_planet:
                    _routes.append({
                        "trader": _t,
                        "from_planet": _buy_planet,
                        "to_planet": _sell_planet,
                        "quantity": _qty
                    })

        if _routes:
            _route_df = pl.DataFrame(_routes)

            # Aggregate flows between planet pairs
            _flow_agg = _route_df.group_by(["from_planet", "to_planet"]).agg([
                pl.col("quantity").sum().alias("total_flow"),
                pl.col("trader").n_unique().alias("num_traders")
            ]).sort("total_flow", descending=True)

            # Create Sankey diagram
            _planets = list(set(_flow_agg["from_planet"].to_list() + _flow_agg["to_planet"].to_list()))
            _planet_idx = {p: i for i, p in enumerate(_planets)}

            _sources = [_planet_idx[p] for p in _flow_agg["from_planet"].to_list()]
            _targets = [_planet_idx[p] for p in _flow_agg["to_planet"].to_list()]
            _values = _flow_agg["total_flow"].to_list()

            _fig = go.Figure(go.Sankey(
                node=dict(
                    pad=15,
                    thickness=20,
                    line=dict(color="black", width=0.5),
                    label=_planets,
                    color="blue"
                ),
                link=dict(
                    source=_sources,
                    target=_targets,
                    value=_values,
                    label=[f"{v} units" for v in _values]
                )
            ))

            _fig.update_layout(
                title="Trade Flows: Where Traders Buy -> Where They Sell",
                font_size=12,
                height=500
            )

            _ = mo.md("""
            ### Trade Flow Visualization

            This Sankey diagram shows the flow of goods from planets where traders buy
            (left/source) to planets where they sell (right/target).

            Thick flows indicate strong, consistent trade routes.
            """)

            _output = _fig
        else:
            _output = mo.md("No inter-planet trade routes detected.")

    _output
    return


@app.cell
def _(mo, pl, trader_flows):
    # Show trade route table
    if trader_flows is not None and trader_flows["buy_count"] > 0:
        _buy_summary = trader_flows["buy_summary"]
        _sell_summary = trader_flows["sell_summary"]

        # Find distinct routes
        _routes = []
        _traders = _buy_summary["trader"].unique().to_list()

        for _t in _traders:
            _t_buys = _buy_summary.filter(pl.col("trader") == _t).sort("qty_bought", descending=True)
            _t_sells = _sell_summary.filter(pl.col("trader") == _t).sort("qty_sold", descending=True)

            if len(_t_buys) > 0 and len(_t_sells) > 0:
                _buy_planet = _t_buys["buy_planet"][0]
                _buy_qty = _t_buys["qty_bought"][0]
                _buy_price = round(_t_buys["avg_buy_price"][0], 1)
                _sell_planet = _t_sells["sell_planet"][0]
                _sell_qty = _t_sells["qty_sold"][0]
                _sell_price = round(_t_sells["avg_sell_price"][0], 1)

                _profit_margin = ((_sell_price - _buy_price) / _buy_price * 100) if _buy_price > 0 else 0

                _routes.append({
                    "Trader": _t,
                    "Buy From": _buy_planet,
                    "Qty Bought": _buy_qty,
                    "Avg Buy Price": _buy_price,
                    "Sell At": _sell_planet,
                    "Qty Sold": _sell_qty,
                    "Avg Sell Price": _sell_price,
                    "Est. Margin %": round(_profit_margin, 1)
                })

        if _routes:
            _route_df = pl.DataFrame(_routes).sort("Qty Bought", descending=True)

            _output = mo.md(f"""
            ### Trade Routes by Trader

            Each trader's primary route (where they buy most and sell most):

            {mo.ui.table(_route_df.to_pandas())}

            **Key Insight:** Look for consistent patterns - do traders buy from planets with
            high resource attributes and sell to planets with low attributes?
            """)
        else:
            _output = mo.md("No trade routes found.")
    else:
        _output = mo.md("No trader data available.")

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 3: Price Differentials

    Do market prices reflect resource scarcity?
    Planets with abundant resources should have lower prices (supply > demand),
    while scarce-resource planets should have higher prices.
    """)
    return


@app.cell
def _(data, mo, pl):
    # Calculate average prices by planet and commodity
    if data is None or len(data.market_snapshots) == 0:
        _output = mo.md("No market snapshot data available")
        price_by_planet = None
    else:
        # Get average prices across the simulation
        price_by_planet = data.market_snapshots.group_by(["planet_name", "commodity_id"]).agg([
            pl.col("avg_price").mean().alias("mean_price"),
            pl.col("avg_price").std().alias("price_std"),
            pl.col("volume").sum().alias("total_volume")
        ]).filter(pl.col("mean_price").is_not_null())

        _output = mo.md(f"""
        **Price Data Summary:**
        - Planet-commodity price pairs: {len(price_by_planet)}
        """)

    _output
    return (price_by_planet,)


@app.cell
def _(attrs_df, go, mo, pl, price_by_planet):
    # Correlate prices with resource attributes (expect NEGATIVE correlation)
    if price_by_planet is None or attrs_df is None:
        _output = mo.md("Cannot compute price correlations - missing data")
    else:
        _commodity_to_attr = {
            "biomass": "biomass",
            "food": "biomass",
            "fiber": "fiber",
            "clothing": "fiber",
            "wood": "wood",
            "common_metal_ore": "common_metal_ore",
            "common_metal": "common_metal_ore",
            "nova_fuel_ore": "nova_fuel_ore",
            "nova_fuel": "nova_fuel_ore",
            "simple_building_materials": "simple_building_materials",
        }

        _price_corr_data = []

        for _commodity, _attr_name in _commodity_to_attr.items():
            _prices = price_by_planet.filter(pl.col("commodity_id") == _commodity)
            if len(_prices) == 0:
                continue

            _joined = _prices.join(
                attrs_df.select(["planet", _attr_name]).rename({"planet": "planet_name"}),
                on="planet_name",
                how="left"
            )

            if len(_joined) < 3:
                continue

            _values = _joined.select([
                pl.col("mean_price").cast(pl.Float64),
                pl.col(_attr_name).cast(pl.Float64)
            ]).drop_nulls()

            if len(_values) >= 3:
                _price_vals = _values["mean_price"].to_list()
                _attr_vals = _values[_attr_name].to_list()

                _n = len(_price_vals)
                _mean_price = sum(_price_vals) / _n
                _mean_attr = sum(_attr_vals) / _n

                _num = sum((p - _mean_price) * (a - _mean_attr) for p, a in zip(_price_vals, _attr_vals))
                _denom_price = sum((p - _mean_price) ** 2 for p in _price_vals) ** 0.5
                _denom_attr = sum((a - _mean_attr) ** 2 for a in _attr_vals) ** 0.5

                if _denom_price > 0 and _denom_attr > 0:
                    _corr = _num / (_denom_price * _denom_attr)
                else:
                    _corr = 0.0

                _price_corr_data.append({
                    "commodity": _commodity,
                    "resource_attribute": _attr_name,
                    "correlation": round(_corr, 3),
                    "n_planets": _n,
                    "interpretation": "Expected (negative)" if _corr < -0.3 else ("Weak negative" if _corr < 0 else "Unexpected (positive)")
                })

        if _price_corr_data:
            _price_corr_df = pl.DataFrame(_price_corr_data)

            _fig = go.Figure()

            _fig.add_trace(go.Bar(
                x=_price_corr_df["commodity"].to_list(),
                y=_price_corr_df["correlation"].to_list(),
                marker_color=[
                    "green" if c < -0.3 else ("yellow" if c < 0 else "red")
                    for c in _price_corr_df["correlation"].to_list()
                ],
                text=[f"{c:.2f}" for c in _price_corr_df["correlation"].to_list()],
                textposition="outside"
            ))

            _fig.update_layout(
                title="Correlation: Prices vs Resource Attributes",
                xaxis_title="Commodity",
                yaxis_title="Correlation Coefficient",
                yaxis_range=[-1, 1],
                showlegend=False
            )

            _fig.add_hline(y=-0.3, line_dash="dash", line_color="green", annotation_text="Expected negative threshold")
            _fig.add_hline(y=0, line_dash="solid", line_color="gray")

            _ = mo.md(f"""
            ### Price-Attribute Correlations

            We expect **negative** correlations here: planets with abundant resources
            should have lower prices due to higher supply.

            - **Green (<-0.3):** Expected negative correlation - abundance lowers prices
            - **Yellow (-0.3 to 0):** Weak negative - some price impact
            - **Red (>0):** Unexpected positive - prices don't reflect scarcity

            {mo.ui.table(_price_corr_df.to_pandas())}
            """)

            _output = _fig
        else:
            _output = mo.md("No price correlation data computed.")

    _output
    return


@app.cell
def _(attrs_df, mo, pl, price_by_planet):
    # Show detailed price comparison across planets for key commodities
    if price_by_planet is None or attrs_df is None:
        _output = mo.md("No data for price comparison")
    else:
        # Pick key commodities to analyze
        _key_commodities = ["food", "biomass", "nova_fuel", "fiber"]

        _comparison_rows = []
        for _commodity in _key_commodities:
            _prices = price_by_planet.filter(pl.col("commodity_id") == _commodity)

            for _row in _prices.iter_rows(named=True):
                _planet = _row["planet_name"]

                # Get attribute for this commodity
                if _commodity in ["food", "biomass"]:
                    _attr_name = "biomass"
                elif _commodity in ["nova_fuel", "nova_fuel_ore"]:
                    _attr_name = "nova_fuel_ore"
                elif _commodity in ["fiber", "clothing"]:
                    _attr_name = "fiber"
                else:
                    _attr_name = _commodity

                _attr_row = attrs_df.filter(pl.col("planet") == _planet)
                _attr_val = _attr_row[_attr_name][0] if len(_attr_row) > 0 and _attr_name in _attr_row.columns else None

                _comparison_rows.append({
                    "Planet": _planet,
                    "Commodity": _commodity,
                    "Avg Price": round(_row["mean_price"], 1),
                    "Resource Attr": round(_attr_val, 2) if _attr_val else "N/A",
                    "Total Volume": _row["total_volume"]
                })

        if _comparison_rows:
            _comp_df = pl.DataFrame(_comparison_rows).sort(["Commodity", "Avg Price"])

            _output = mo.md(f"""
            ### Price Comparison by Planet

            Sorted by commodity, then by price (lowest first).
            Compare prices to resource attributes - do low-attribute planets have higher prices?

            {mo.ui.table(_comp_df.to_pandas())}
            """)
        else:
            _output = mo.md("No price comparison data available")

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 4: Specialization Summary

    Which planets show the strongest specialization patterns?
    """)
    return


@app.cell
def _():
    # Helper function for commodity-attribute matching
    def _check_commodity_attr_match(commodity_name: str, attribute_name: str) -> bool:
        """Check if a commodity production matches the resource attribute."""
        _matches = {
            "biomass": ["biomass"],
            "fiber": ["fiber"],
            "wood": ["wood"],
            "common_metal_ore": ["common_metal_ore", "common_metal"],
            "nova_fuel_ore": ["nova_fuel_ore", "nova_fuel"],
            "simple_building_materials": ["simple_building_materials"],
        }

        if attribute_name in _matches:
            return commodity_name in _matches[attribute_name]

        # Also check derived products
        _derived = {
            "food": "biomass",
            "clothing": "fiber",
            "common_metal": "common_metal_ore",
            "nova_fuel": "nova_fuel_ore",
        }

        if commodity_name in _derived:
            return _derived[commodity_name] == attribute_name

        return False
    return (_check_commodity_attr_match,)


@app.cell
def _(_check_commodity_attr_match, attrs_df, mo, pl, production_by_planet):
    # Identify planet specializations
    if production_by_planet is None or attrs_df is None:
        _output = mo.md("Cannot compute specializations - missing data")
    else:
        _specializations = []

        _planets = attrs_df["planet"].to_list()

        for _planet in _planets:
            # Get production for this planet
            _planet_prod = production_by_planet.filter(pl.col("planet_name") == _planet)

            if len(_planet_prod) == 0:
                continue

            # Find top produced commodity
            _top = _planet_prod.sort("total_produced", descending=True).head(1)
            _top_commodity = _top["commodity_id"][0]
            _top_qty = _top["total_produced"][0]

            # Get planet's attributes
            _planet_attrs = attrs_df.filter(pl.col("planet") == _planet)

            # Find highest attribute
            _attr_cols = ["biomass", "fiber", "wood", "common_metal_ore", "nova_fuel_ore", "simple_building_materials"]
            _max_attr = None
            _max_attr_val = 0

            for _attr in _attr_cols:
                if _attr in _planet_attrs.columns:
                    _val = _planet_attrs[_attr][0]
                    if _val > _max_attr_val:
                        _max_attr_val = _val
                        _max_attr = _attr

            _specializations.append({
                "Planet": _planet,
                "Top Production": _top_commodity,
                "Qty Produced": _top_qty,
                "Strongest Resource": _max_attr,
                "Resource Value": round(_max_attr_val, 2),
                "Match?": "YES" if _check_commodity_attr_match(_top_commodity, _max_attr) else "no"
            })

        _spec_df = pl.DataFrame(_specializations).sort("Qty Produced", descending=True)

        _match_count = sum(1 for s in _specializations if s["Match?"] == "YES")
        _total = len(_specializations)

        _output = mo.md(f"""
        ### Planet Specialization Summary

        For each planet: what they produce most vs their strongest resource attribute.

        **Match Rate: {_match_count}/{_total} planets ({_match_count/_total*100:.0f}%)**

        A "YES" in Match? indicates the planet's top production aligns with their resource strength.

        {mo.ui.table(_spec_df.to_pandas())}
        """)

    _output
    return


@app.cell
def _(correlation_results, mo, pl, trader_flows):
    # Final summary
    if correlation_results is None or len(correlation_results) == 0:
        _summary = "Insufficient data for summary"
    else:
        _strong_corrs = correlation_results.filter(pl.col("correlation") > 0.5)
        _num_strong = len(_strong_corrs)
        _total_commodities = len(correlation_results)

        _has_trade_routes = trader_flows is not None and trader_flows["sell_count"] > 0

        _summary = f"""
        ## Key Findings

        ### 1. Production-Resource Correlation
        - **{_num_strong}/{_total_commodities} commodities** show strong correlation (>0.5) with planet attributes
        - This indicates the planet attribute system **{"IS" if _num_strong > _total_commodities/2 else "IS NOT fully"}** driving production specialization

        ### 2. Trade Routes
        - Traders made **{trader_flows["sell_count"] if _has_trade_routes else 0:,} sales** across the simulation
        - {"Trade routes appear to be forming between producing and consuming planets" if _has_trade_routes else "Limited inter-planet trading observed"}

        ### 3. Implications
        {"- The economic system shows evidence of meaningful specialization" if _num_strong > 2 else "- Consider tuning the attribute effects to create stronger differentiation"}
        {"- Traders are exploiting price differentials" if _has_trade_routes else "- Traders may need better AI to find profitable routes"}

        ---

        **Next Steps:**
        - If correlations are weak: Check that `resource_attribute` effects in `processes.yaml` are significant
        - If no trade routes: Review ship brain logic for trade opportunity detection
        - Run longer simulations (1000+ turns) to see mature specialization patterns
        """

    mo.md(_summary)
    return


if __name__ == "__main__":
    app.run()
