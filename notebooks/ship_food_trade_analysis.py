"""Ship Food Trade Analysis

This notebook analyzes how ship traders affect food distribution across planets,
specifically examining whether ships successfully identify food-poor planets
and improve food security by importing food to them.

Key Questions:
1. Do planets with low biomass attributes have worse food drive metrics?
2. Are ships trading food from food-rich to food-poor planets?
3. Do food prices correlate with biomass scarcity?
4. Does ship trading improve food security on food-poor planets over time?
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
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from spacesim2.analysis.loading.loader import SimulationData
    from pathlib import Path
    return Path, SimulationData, go, json, make_subplots, mo, os, pl, px


@app.cell
def _(Path, mo, os):
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
    # Ship Food Trade Analysis

    This notebook investigates whether ship traders successfully identify food-poor planets
    and improve food security by importing food to them.

    **Key Question:** Are ship traders successfully identifying food-poor planets and
    importing food to them, thereby improving food security for residents?

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
                _status = f"Loaded: {len(data.market_transactions):,} transactions, {len(planet_attrs)} planets with attributes"
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
def _(mo):
    mo.md("""
    ---
    ## Section 1: Planet Food Production Capacity

    This section shows each planet's biomass attribute, which determines their
    ability to produce food locally. Planets with low biomass (<0.4) are
    considered "food-poor" and should rely on imports.
    """)
    return


@app.cell
def _(mo, planet_attrs, pl, px):
    # Display planet biomass attributes and classify food-poor vs food-rich
    if not planet_attrs:
        _output = mo.md("No planet attributes data available.")
        attrs_df = None
        biomass_chart = None
    else:
        # Convert to DataFrame
        _rows = []
        for _planet, _attrs in planet_attrs.items():
            _row = {"planet": _planet}
            _row.update(_attrs)
            _rows.append(_row)

        attrs_df = pl.DataFrame(_rows)

        # Add food classification
        attrs_df = attrs_df.with_columns([
            pl.when(pl.col("biomass") < 0.4)
            .then(pl.lit("Food-Poor"))
            .when(pl.col("biomass") < 0.6)
            .then(pl.lit("Moderate"))
            .otherwise(pl.lit("Food-Rich"))
            .alias("food_classification")
        ])

        # Create bar chart of biomass by planet
        _sorted = attrs_df.sort("biomass")

        biomass_chart = px.bar(
            _sorted.to_pandas(),
            x="planet",
            y="biomass",
            color="food_classification",
            color_discrete_map={
                "Food-Poor": "#ff6b6b",
                "Moderate": "#ffd93d",
                "Food-Rich": "#6bcb77"
            },
            title="Planet Biomass Attributes (Food Production Capacity)",
            labels={"biomass": "Biomass Attribute (0-1)", "planet": "Planet"}
        )

        biomass_chart.add_hline(y=0.4, line_dash="dash", line_color="red",
                                annotation_text="Food-Poor Threshold")
        biomass_chart.add_hline(y=0.6, line_dash="dash", line_color="green",
                                annotation_text="Food-Rich Threshold")

        _food_poor = attrs_df.filter(pl.col("food_classification") == "Food-Poor")
        _food_rich = attrs_df.filter(pl.col("food_classification") == "Food-Rich")

        _output = mo.md(f"""
        ### Planet Food Classification

        - **Food-Poor planets (biomass < 0.4):** {len(_food_poor)} - {", ".join(_food_poor["planet"].to_list()) if len(_food_poor) > 0 else "None"}
        - **Food-Rich planets (biomass >= 0.6):** {len(_food_rich)} - {", ".join(_food_rich["planet"].to_list()) if len(_food_rich) > 0 else "None"}

        Food-poor planets should have higher food prices and depend on ship imports.
        """)

    _output
    return attrs_df, biomass_chart


@app.cell
def _(biomass_chart):
    biomass_chart if biomass_chart is not None else "No chart available"
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 2: Food Drive Metrics Over Time by Planet

    Do food-poor planets have worse food drive metrics? We track health, debt,
    and buffer levels for all actors, grouped by planet. Food-poor planets
    should start with worse metrics but may improve as ships bring food.
    """)
    return


@app.cell
def _(data, mo, pl):
    # Join drive data with actor location to get planet info
    if data is None:
        _output = mo.md("No data available")
        drives_with_planet = None
    else:
        # Get actor-planet mapping (actors stay on their home planet)
        _actor_planets = data.actor_turns.select([
            "actor_id", "planet_name", "turn"
        ])

        # Join drives with actor locations
        drives_with_planet = data.actor_drives.join(
            _actor_planets,
            on=["actor_id", "turn"],
            how="left"
        )

        # Filter to food drive only
        drives_with_planet = drives_with_planet.filter(
            pl.col("drive_name") == "food"
        )

        _output = mo.md(f"""
        **Drive Data:** {len(drives_with_planet):,} food drive records across simulation
        """)

    _output
    return (drives_with_planet,)


@app.cell
def _(attrs_df, drives_with_planet, go, make_subplots, mo, pl):
    # Plot food drive metrics over time, grouped by planet classification
    if drives_with_planet is None or attrs_df is None:
        _output = mo.md("No drive data available")
        drive_metrics_fig = None
    else:
        # Add food classification to drive data
        _class_map = dict(zip(
            attrs_df["planet"].to_list(),
            attrs_df["food_classification"].to_list()
        ))

        _drives_classified = drives_with_planet.with_columns([
            pl.col("planet_name").replace(_class_map, default="Unknown").alias("food_classification")
        ])

        # Aggregate by turn and classification
        _agg = _drives_classified.group_by(["turn", "food_classification"]).agg([
            pl.col("health").mean().alias("avg_health"),
            pl.col("debt").mean().alias("avg_debt"),
            pl.col("buffer").mean().alias("avg_buffer"),
        ]).sort("turn")

        # Create subplots for health, debt, and buffer
        drive_metrics_fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=("Food Drive Health", "Food Drive Debt", "Food Drive Buffer"),
            vertical_spacing=0.1
        )

        _colors = {
            "Food-Poor": "#ff6b6b",
            "Moderate": "#ffd93d",
            "Food-Rich": "#6bcb77"
        }

        for _classification in ["Food-Poor", "Moderate", "Food-Rich"]:
            _subset = _agg.filter(pl.col("food_classification") == _classification)
            if len(_subset) == 0:
                continue

            _color = _colors.get(_classification, "gray")

            drive_metrics_fig.add_trace(
                go.Scatter(
                    x=_subset["turn"].to_list(),
                    y=_subset["avg_health"].to_list(),
                    name=f"{_classification} Health",
                    line=dict(color=_color),
                    legendgroup=_classification,
                ),
                row=1, col=1
            )

            drive_metrics_fig.add_trace(
                go.Scatter(
                    x=_subset["turn"].to_list(),
                    y=_subset["avg_debt"].to_list(),
                    name=f"{_classification} Debt",
                    line=dict(color=_color),
                    legendgroup=_classification,
                    showlegend=False,
                ),
                row=2, col=1
            )

            drive_metrics_fig.add_trace(
                go.Scatter(
                    x=_subset["turn"].to_list(),
                    y=_subset["avg_buffer"].to_list(),
                    name=f"{_classification} Buffer",
                    line=dict(color=_color),
                    legendgroup=_classification,
                    showlegend=False,
                ),
                row=3, col=1
            )

        drive_metrics_fig.update_layout(
            title="Food Drive Metrics by Planet Classification",
            height=700,
            hovermode="x unified"
        )

        drive_metrics_fig.update_yaxes(title_text="Health (0-1)", row=1, col=1)
        drive_metrics_fig.update_yaxes(title_text="Debt (0-1)", row=2, col=1)
        drive_metrics_fig.update_yaxes(title_text="Buffer (0-1)", row=3, col=1)
        drive_metrics_fig.update_xaxes(title_text="Turn", row=3, col=1)

        _output = mo.md("""
        **Interpretation:**
        - **Health:** Higher is better (1.0 = fully satisfied)
        - **Debt:** Lower is better (0.0 = no accumulated need)
        - **Buffer:** Higher is better (food inventory coverage)

        If ships are effective, food-poor planets should see improving metrics over time.
        """)

    _output
    return (drive_metrics_fig,)


@app.cell
def _(drive_metrics_fig):
    drive_metrics_fig if drive_metrics_fig is not None else "No chart available"
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 3: Ship Trade Routes Analysis

    Where are ships buying and selling food? We analyze trader transactions
    to identify trade patterns and determine which planets are net importers
    vs exporters of food.
    """)
    return


@app.cell
def _(data, mo, pl):
    # Analyze ship food trading patterns
    if data is None:
        _output = mo.md("No data available")
        trader_food_buys = None
        trader_food_sells = None
    else:
        # Get all trader transactions for food and biomass
        _food_commodities = ["food", "biomass"]

        # Trader buys (trader is buyer)
        trader_food_buys = data.market_transactions.filter(
            pl.col("buyer_name").str.contains("Trader") &
            pl.col("commodity_id").is_in(_food_commodities)
        )

        # Trader sells (trader is seller)
        trader_food_sells = data.market_transactions.filter(
            pl.col("seller_name").str.contains("Trader") &
            pl.col("commodity_id").is_in(_food_commodities)
        )

        _output = mo.md(f"""
        **Ship Food Trading Activity:**
        - Trader food/biomass purchases: {len(trader_food_buys):,}
        - Trader food/biomass sales: {len(trader_food_sells):,}
        """)

    _output
    return trader_food_buys, trader_food_sells


@app.cell
def _(attrs_df, mo, pl, px, trader_food_buys, trader_food_sells):
    # Calculate net imports/exports by planet
    if trader_food_buys is None or trader_food_sells is None or attrs_df is None:
        _output = mo.md("No trader data available")
        net_imports_fig = None
    else:
        # Trader buys FROM a planet = that planet is exporting
        _exports = trader_food_buys.group_by("planet_name").agg([
            pl.col("quantity").sum().alias("exported_qty")
        ])

        # Trader sells TO a planet = that planet is importing
        _imports = trader_food_sells.group_by("planet_name").agg([
            pl.col("quantity").sum().alias("imported_qty")
        ])

        # Combine and calculate net
        _net = _exports.join(_imports, on="planet_name", how="outer").fill_null(0)
        _net = _net.with_columns([
            (pl.col("imported_qty") - pl.col("exported_qty")).alias("net_imports")
        ])

        # Add biomass attribute
        _biomass_map = dict(zip(
            attrs_df["planet"].to_list(),
            attrs_df["biomass"].to_list()
        ))

        _net = _net.with_columns([
            pl.col("planet_name").replace(_biomass_map, default=0.5).alias("biomass_attr")
        ]).sort("biomass_attr")

        net_imports_fig = px.bar(
            _net.to_pandas(),
            x="planet_name",
            y="net_imports",
            color="biomass_attr",
            color_continuous_scale="RdYlGn",
            title="Net Food Imports by Planet (Trader Activity)",
            labels={
                "net_imports": "Net Imports (positive = importing)",
                "planet_name": "Planet",
                "biomass_attr": "Biomass Attribute"
            }
        )

        net_imports_fig.add_hline(y=0, line_dash="solid", line_color="black")
        net_imports_fig.update_layout(xaxis_tickangle=-45)

        _output = mo.md(f"""
        ### Net Food Import/Export by Planet

        - **Positive values:** Planet is a net importer (ships sell food here)
        - **Negative values:** Planet is a net exporter (ships buy food here)

        **Expected pattern:** Food-poor planets (low biomass, red) should be net importers,
        while food-rich planets (high biomass, green) should be net exporters.
        """)

    _output
    return (net_imports_fig,)


@app.cell
def _(net_imports_fig):
    net_imports_fig if net_imports_fig is not None else "No chart available"
    return


@app.cell
def _(mo, pl, trader_food_buys, trader_food_sells):
    # Analyze specific trade routes
    if trader_food_buys is None or trader_food_sells is None:
        _output = mo.md("No trade route data available")
        trade_routes_df = None
    else:
        # For each trader, find their buying and selling patterns
        _buy_summary = trader_food_buys.group_by(["buyer_name", "planet_name"]).agg([
            pl.col("quantity").sum().alias("qty_bought"),
            pl.col("price").mean().alias("avg_buy_price")
        ]).rename({"buyer_name": "trader", "planet_name": "buy_planet"})

        _sell_summary = trader_food_sells.group_by(["seller_name", "planet_name"]).agg([
            pl.col("quantity").sum().alias("qty_sold"),
            pl.col("price").mean().alias("avg_sell_price")
        ]).rename({"seller_name": "trader", "planet_name": "sell_planet"})

        # Build route table
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
                    "Profit Margin %": round(_profit_margin, 1)
                })

        if _routes:
            trade_routes_df = pl.DataFrame(_routes).sort("Qty Bought", descending=True)
            _output = mo.md(f"""
            ### Food Trade Routes by Trader

            {mo.ui.table(trade_routes_df.to_pandas())}

            **Key insight:** Look for patterns where traders buy from food-rich planets
            and sell to food-poor planets with positive profit margins.
            """)
        else:
            trade_routes_df = None
            _output = mo.md("No food trade routes found.")

    _output
    return (trade_routes_df,)


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 4: Food Price Differentials

    Are food prices higher on food-poor planets? Ships should exploit these
    price differences for profit while equalizing food availability.
    """)
    return


@app.cell
def _(data, mo, pl):
    # Get food prices over time by planet
    if data is None:
        _output = mo.md("No data available")
        food_prices = None
    else:
        food_prices = data.market_snapshots.filter(
            pl.col("commodity_id") == "food"
        ).select([
            "turn", "planet_name", "avg_price", "volume"
        ])

        _output = mo.md(f"""
        **Food price records:** {len(food_prices):,}
        """)

    _output
    return (food_prices,)


@app.cell
def _(attrs_df, food_prices, mo, pl, px):
    # Plot food prices over time by planet, colored by biomass
    if food_prices is None or attrs_df is None or len(food_prices) == 0:
        _output = mo.md("No food price data available")
        food_price_fig = None
    else:
        # Add biomass attribute to prices
        _biomass_map = dict(zip(
            attrs_df["planet"].to_list(),
            attrs_df["biomass"].to_list()
        ))
        _class_map = dict(zip(
            attrs_df["planet"].to_list(),
            attrs_df["food_classification"].to_list()
        ))

        _prices_classified = food_prices.with_columns([
            pl.col("planet_name").replace(_biomass_map, default=0.5).alias("biomass_attr"),
            pl.col("planet_name").replace(_class_map, default="Unknown").alias("food_classification")
        ])

        food_price_fig = px.line(
            _prices_classified.to_pandas(),
            x="turn",
            y="avg_price",
            color="planet_name",
            title="Food Prices Over Time by Planet",
            labels={
                "avg_price": "Average Food Price",
                "turn": "Turn",
                "planet_name": "Planet"
            }
        )

        food_price_fig.update_layout(hovermode="x unified")

        _output = mo.md("""
        **Expected pattern:** Food-poor planets should have higher food prices initially,
        but prices may converge as ships import food and increase supply.
        """)

    _output
    return (food_price_fig,)


@app.cell
def _(food_price_fig):
    food_price_fig if food_price_fig is not None else "No chart available"
    return


@app.cell
def _(attrs_df, food_prices, mo, pl, px):
    # Average food price by planet, compared to biomass
    if food_prices is None or attrs_df is None:
        _output = mo.md("No data for price comparison")
        price_vs_biomass_fig = None
    else:
        # Calculate average food price per planet
        _avg_prices = food_prices.group_by("planet_name").agg([
            pl.col("avg_price").mean().alias("mean_food_price"),
            pl.col("avg_price").std().alias("price_std")
        ])

        # Join with biomass
        _comparison = _avg_prices.join(
            attrs_df.select(["planet", "biomass", "food_classification"]).rename({"planet": "planet_name"}),
            on="planet_name",
            how="left"
        )

        price_vs_biomass_fig = px.scatter(
            _comparison.to_pandas(),
            x="biomass",
            y="mean_food_price",
            color="food_classification",
            color_discrete_map={
                "Food-Poor": "#ff6b6b",
                "Moderate": "#ffd93d",
                "Food-Rich": "#6bcb77"
            },
            text="planet_name",
            title="Average Food Price vs Biomass Attribute",
            labels={
                "biomass": "Biomass Attribute",
                "mean_food_price": "Average Food Price",
                "food_classification": "Classification"
            },
            size_max=15
        )

        price_vs_biomass_fig.update_traces(textposition="top center")
        price_vs_biomass_fig.update_layout(showlegend=True)

        # Calculate correlation
        _values = _comparison.select([
            pl.col("biomass").cast(pl.Float64),
            pl.col("mean_food_price").cast(pl.Float64)
        ]).drop_nulls()

        if len(_values) >= 3:
            _biomass_vals = _values["biomass"].to_list()
            _price_vals = _values["mean_food_price"].to_list()

            _n = len(_biomass_vals)
            _mean_b = sum(_biomass_vals) / _n
            _mean_p = sum(_price_vals) / _n

            _num = sum((b - _mean_b) * (p - _mean_p) for b, p in zip(_biomass_vals, _price_vals))
            _denom_b = sum((b - _mean_b) ** 2 for b in _biomass_vals) ** 0.5
            _denom_p = sum((p - _mean_p) ** 2 for p in _price_vals) ** 0.5

            _corr = _num / (_denom_b * _denom_p) if (_denom_b > 0 and _denom_p > 0) else 0
        else:
            _corr = 0

        _output = mo.md(f"""
        ### Price-Biomass Relationship

        **Correlation:** {_corr:.3f}

        - **Expected:** Negative correlation (food-poor planets have higher prices)
        - **Interpretation:** {"Prices correctly reflect scarcity" if _corr < -0.3 else "Weak price-scarcity relationship" if _corr < 0 else "Unexpected: higher biomass = higher prices"}
        """)

    _output
    return (price_vs_biomass_fig,)


@app.cell
def _(price_vs_biomass_fig):
    price_vs_biomass_fig if price_vs_biomass_fig is not None else "No chart available"
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 5: Correlation Analysis

    Comprehensive analysis of relationships between biomass attributes,
    food prices, trade flows, and food drive health.
    """)
    return


@app.cell
def _(attrs_df, drives_with_planet, food_prices, mo, pl, trader_food_buys, trader_food_sells):
    # Build comprehensive correlation analysis
    if attrs_df is None:
        _output = mo.md("No data for correlation analysis")
    else:
        _correlations = []

        # Helper function for correlation
        def _calc_corr(x_vals, y_vals):
            if len(x_vals) < 3:
                return 0
            _n = len(x_vals)
            _mean_x = sum(x_vals) / _n
            _mean_y = sum(y_vals) / _n
            _num = sum((x - _mean_x) * (y - _mean_y) for x, y in zip(x_vals, y_vals))
            _denom_x = sum((x - _mean_x) ** 2 for x in x_vals) ** 0.5
            _denom_y = sum((y - _mean_y) ** 2 for y in y_vals) ** 0.5
            return _num / (_denom_x * _denom_y) if (_denom_x > 0 and _denom_y > 0) else 0

        # 1. Biomass vs Average Food Price
        if food_prices is not None and len(food_prices) > 0:
            _avg_prices = food_prices.group_by("planet_name").agg([
                pl.col("avg_price").mean().alias("mean_price")
            ])
            _joined = _avg_prices.join(
                attrs_df.select(["planet", "biomass"]).rename({"planet": "planet_name"}),
                on="planet_name", how="inner"
            )
            if len(_joined) >= 3:
                _corr = _calc_corr(_joined["biomass"].to_list(), _joined["mean_price"].to_list())
                _correlations.append({
                    "Relationship": "Biomass vs Food Price",
                    "Correlation": round(_corr, 3),
                    "Expected": "Negative",
                    "Interpretation": "Low biomass = higher prices" if _corr < -0.2 else "No clear relationship"
                })

        # 2. Biomass vs Net Imports
        if trader_food_buys is not None and trader_food_sells is not None:
            _exports = trader_food_buys.group_by("planet_name").agg([pl.col("quantity").sum().alias("exported")])
            _imports = trader_food_sells.group_by("planet_name").agg([pl.col("quantity").sum().alias("imported")])
            _net = _exports.join(_imports, on="planet_name", how="outer").fill_null(0)
            _net = _net.with_columns([(pl.col("imported") - pl.col("exported")).alias("net_imports")])

            _joined = _net.join(
                attrs_df.select(["planet", "biomass"]).rename({"planet": "planet_name"}),
                on="planet_name", how="inner"
            )
            if len(_joined) >= 3:
                _corr = _calc_corr(_joined["biomass"].to_list(), _joined["net_imports"].to_list())
                _correlations.append({
                    "Relationship": "Biomass vs Net Food Imports",
                    "Correlation": round(_corr, 3),
                    "Expected": "Negative",
                    "Interpretation": "Low biomass = more imports" if _corr < -0.2 else "No clear relationship"
                })

        # 3. Biomass vs Food Drive Health (final turn)
        if drives_with_planet is not None and len(drives_with_planet) > 0:
            _max_turn = drives_with_planet["turn"].max()
            _final_health = drives_with_planet.filter(pl.col("turn") == _max_turn).group_by("planet_name").agg([
                pl.col("health").mean().alias("mean_health")
            ])
            _joined = _final_health.join(
                attrs_df.select(["planet", "biomass"]).rename({"planet": "planet_name"}),
                on="planet_name", how="inner"
            )
            if len(_joined) >= 3:
                _corr = _calc_corr(_joined["biomass"].to_list(), _joined["mean_health"].to_list())
                _correlations.append({
                    "Relationship": "Biomass vs Final Food Health",
                    "Correlation": round(_corr, 3),
                    "Expected": "Positive (if ships ineffective) or Neutral (if ships effective)",
                    "Interpretation": "Higher biomass = better health" if _corr > 0.2 else "Health equalized across planets" if abs(_corr) < 0.2 else "Unexpected pattern"
                })

        # 4. Biomass vs Food Drive Debt
        if drives_with_planet is not None and len(drives_with_planet) > 0:
            _final_debt = drives_with_planet.filter(pl.col("turn") == _max_turn).group_by("planet_name").agg([
                pl.col("debt").mean().alias("mean_debt")
            ])
            _joined = _final_debt.join(
                attrs_df.select(["planet", "biomass"]).rename({"planet": "planet_name"}),
                on="planet_name", how="inner"
            )
            if len(_joined) >= 3:
                _corr = _calc_corr(_joined["biomass"].to_list(), _joined["mean_debt"].to_list())
                _correlations.append({
                    "Relationship": "Biomass vs Final Food Debt",
                    "Correlation": round(_corr, 3),
                    "Expected": "Negative (if ships ineffective) or Neutral (if ships effective)",
                    "Interpretation": "Low biomass = more debt" if _corr < -0.2 else "Debt equalized across planets" if abs(_corr) < 0.2 else "Unexpected pattern"
                })

        if _correlations:
            _corr_df = pl.DataFrame(_correlations)
            _output = mo.md(f"""
            ### Correlation Summary

            {mo.ui.table(_corr_df.to_pandas())}

            **Key Insights:**
            - If **Biomass vs Net Imports** is strongly negative, ships are correctly identifying food-poor planets
            - If **Biomass vs Final Health/Debt** correlations are weak, ships are successfully equalizing food security
            - If **Biomass vs Food Price** is negative, the market correctly reflects scarcity
            """)
        else:
            _output = mo.md("Could not compute correlations - insufficient data")

    _output
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## Section 6: Summary and Conclusions
    """)
    return


@app.cell
def _(attrs_df, drives_with_planet, mo, pl, trader_food_buys, trader_food_sells):
    # Generate summary conclusions
    if attrs_df is None:
        _summary = "Insufficient data for summary"
    else:
        # Calculate key metrics
        _food_poor_planets = attrs_df.filter(pl.col("food_classification") == "Food-Poor")["planet"].to_list()
        _food_rich_planets = attrs_df.filter(pl.col("food_classification") == "Food-Rich")["planet"].to_list()

        # Trading activity
        _total_food_trades = 0
        _has_trading = False
        if trader_food_buys is not None and trader_food_sells is not None:
            _total_food_trades = len(trader_food_buys) + len(trader_food_sells)
            _has_trading = _total_food_trades > 10

        # Health comparison
        _health_comparison = "unknown"
        if drives_with_planet is not None and len(drives_with_planet) > 0:
            _max_turn = drives_with_planet["turn"].max()
            _final = drives_with_planet.filter(pl.col("turn") == _max_turn)

            if len(_food_poor_planets) > 0:
                _poor_health = _final.filter(pl.col("planet_name").is_in(_food_poor_planets))["health"].mean()
            else:
                _poor_health = None

            if len(_food_rich_planets) > 0:
                _rich_health = _final.filter(pl.col("planet_name").is_in(_food_rich_planets))["health"].mean()
            else:
                _rich_health = None

            if _poor_health is not None and _rich_health is not None:
                _health_diff = _rich_health - _poor_health
                if abs(_health_diff) < 0.1:
                    _health_comparison = "similar"
                elif _health_diff > 0.1:
                    _health_comparison = "food-rich better"
                else:
                    _health_comparison = "food-poor better"
            else:
                _health_comparison = "insufficient data"
        else:
            _poor_health = None
            _rich_health = None

        _summary = f"""
        ## Key Findings

        ### Planet Classification
        - **Food-Poor planets:** {len(_food_poor_planets)} ({", ".join(_food_poor_planets) if _food_poor_planets else "None"})
        - **Food-Rich planets:** {len(_food_rich_planets)} ({", ".join(_food_rich_planets) if _food_rich_planets else "None"})

        ### Ship Trading Activity
        - **Total food-related trades:** {_total_food_trades:,}
        - **Trading active:** {"Yes" if _has_trading else "No - ships not trading food significantly"}

        ### Food Security Outcome
        - **Final food health (food-poor planets):** {f"{_poor_health:.3f}" if _poor_health is not None else "N/A"}
        - **Final food health (food-rich planets):** {f"{_rich_health:.3f}" if _rich_health is not None else "N/A"}
        - **Comparison:** {_health_comparison}

        ### Conclusion

        {"**SUCCESS:** Ships are actively trading food and food security is relatively equalized across planets, suggesting the trading system is working as intended." if _has_trading and _health_comparison == "similar" else ""}
        {"**PARTIAL SUCCESS:** Ships are trading food, but food-poor planets still have worse food security. Consider tuning ship AI to prioritize food-poor destinations." if _has_trading and _health_comparison == "food-rich better" else ""}
        {"**NEEDS INVESTIGATION:** Limited food trading activity. Check ship brain logic for trade opportunity detection." if not _has_trading else ""}
        {"**UNEXPECTED:** Food-poor planets have better food health than food-rich planets. This may indicate market inefficiencies or simulation anomalies." if _health_comparison == "food-poor better" else ""}

        ---

        **Recommendations:**
        - Run longer simulations (1000+ turns) to see mature trading patterns
        - If ships are not trading: Check ship brain's commodity selection logic
        - If prices don't reflect scarcity: Review market maker pricing behavior
        """

    mo.md(_summary)
    return


if __name__ == "__main__":
    app.run()
