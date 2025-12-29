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
def _(mo):
    mo.md("""
    # Shelter Supply Chain Diagnostic Analysis

    **Problem Statement:** Actors are not producing or trading shelter materials (wood, common_metal, common_metal_ore), causing shelter drive health to collapse.

    This notebook diagnoses the root causes by examining:
    1. Transaction data for shelter-related commodities
    2. Market maker commodity support
    3. Actor brain trading behavior
    4. Drive health trends
    5. Supply chain configuration
    """)
    return


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
    ## Data Source

    {status_msg}

    {run_selector}
    """)

    return (run_selector, auto_run_path, get_run_path_with_fallback, NoRunsFoundError, status_msg, run_path_str)


@app.cell
def _(Path, SimulationData, mo, run_selector):
    if not run_selector.value:
        mo.md("No run path specified.")
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
def _(mo):
    mo.md("""
    ---
    ## 1. Transaction Analysis: Which Commodities Were Actually Traded?

    This section reveals the core problem: only a subset of commodities have any market activity.
    """)
    return


@app.cell
def _(data, pl, px, mo):
    if data is None:
        mo.md("No data loaded")
    elif len(data.market_transactions) > 0:
        # Aggregate transactions by commodity
        volume_by_commodity = data.market_transactions.group_by('commodity_id').agg([
            pl.col('quantity').sum().alias('total_volume'),
            pl.col('quantity').count().alias('transaction_count'),
            pl.col('price').mean().alias('avg_price'),
        ]).sort('total_volume', descending=True)

        # Display the table
        mo.md(f"""
        ### Commodity Trading Summary

        **Total Transactions:** {len(data.market_transactions):,}

        | Commodity | Total Volume | Transaction Count | Avg Price |
        |-----------|-------------|-------------------|-----------|
        """)

        volume_by_commodity.to_pandas()
    else:
        mo.md("No transaction data available")
    return (volume_by_commodity,)


@app.cell
def _(data, mo, pl):
    if data is None:
        "No data"
    elif len(data.market_transactions) > 0:
        # Define shelter-related commodities
        shelter_commodities = ['wood', 'common_metal', 'common_metal_ore']
        clothing_commodities = ['clothing']
        traded_commodities = data.market_transactions.select('commodity_id').unique().to_series().to_list()

        shelter_traded = [c for c in shelter_commodities if c in traded_commodities]
        shelter_missing = [c for c in shelter_commodities if c not in traded_commodities]

        clothing_traded = [c for c in clothing_commodities if c in traded_commodities]
        clothing_missing = [c for c in clothing_commodities if c not in traded_commodities]

        mo.md(f"""
        ### Critical Finding: Missing Commodity Markets

        **Shelter Materials:**
        - Traded: {shelter_traded if shelter_traded else 'NONE'}
        - **Missing from market:** {shelter_missing if shelter_missing else 'All present'}

        **Clothing:**
        - Traded: {clothing_traded if clothing_traded else 'NONE'}
        - **Missing from market:** {clothing_missing if clothing_missing else 'All present'}

        **All Commodities Traded:** {sorted(traded_commodities)}
        """)
    return (shelter_commodities, clothing_commodities, traded_commodities, shelter_traded, shelter_missing, clothing_traded, clothing_missing)


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 2. Drive Health Analysis: Impact of Missing Supply Chains

    Without shelter materials being traded, the shelter drive health should deteriorate over time.
    """)
    return


@app.cell
def _(data, go, make_subplots, mo, pl):
    if data is None:
        "No data"
    elif len(data.actor_drives) > 0:
        # Calculate average drive metrics by turn and drive
        drive_stats = data.actor_drives.group_by(['turn', 'drive_name']).agg([
            pl.col('health').mean().alias('avg_health'),
            pl.col('debt').mean().alias('avg_debt'),
            pl.col('buffer').mean().alias('avg_buffer'),
        ]).sort(['drive_name', 'turn'])

        # Create subplot figure
        fig = make_subplots(
            rows=3, cols=1,
            subplot_titles=('Average Health by Drive', 'Average Debt by Drive', 'Average Buffer by Drive'),
            vertical_spacing=0.1
        )

        colors = {'food': 'green', 'shelter': 'orange', 'clothing': 'red'}

        for drive_name in drive_stats['drive_name'].unique().to_list():
            drive_data = drive_stats.filter(pl.col('drive_name') == drive_name).to_pandas()
            color = colors.get(drive_name, 'blue')

            fig.add_trace(
                go.Scatter(x=drive_data['turn'], y=drive_data['avg_health'],
                          name=f'{drive_name}', line=dict(color=color),
                          legendgroup=drive_name, showlegend=True),
                row=1, col=1
            )
            fig.add_trace(
                go.Scatter(x=drive_data['turn'], y=drive_data['avg_debt'],
                          name=f'{drive_name}', line=dict(color=color),
                          legendgroup=drive_name, showlegend=False),
                row=2, col=1
            )
            fig.add_trace(
                go.Scatter(x=drive_data['turn'], y=drive_data['avg_buffer'],
                          name=f'{drive_name}', line=dict(color=color),
                          legendgroup=drive_name, showlegend=False),
                row=3, col=1
            )

        fig.update_layout(height=800, title_text="Drive Metrics Over Time")
        fig.update_yaxes(title_text="Health (0-1)", row=1, col=1)
        fig.update_yaxes(title_text="Debt (0-1)", row=2, col=1)
        fig.update_yaxes(title_text="Buffer (0-1)", row=3, col=1)
        fig.update_xaxes(title_text="Turn", row=3, col=1)

        fig
    return (drive_stats, fig, colors)


@app.cell
def _(data, mo, pl):
    if data is None:
        "No data"
    elif len(data.actor_drives) > 0:
        # Get final turn stats for each drive
        max_turn = data.actor_drives['turn'].max()
        final_stats = data.actor_drives.filter(pl.col('turn') == max_turn).group_by('drive_name').agg([
            pl.col('health').mean().alias('final_avg_health'),
            pl.col('debt').mean().alias('final_avg_debt'),
            pl.col('buffer').mean().alias('final_avg_buffer'),
        ])

        # Get initial stats
        initial_stats = data.actor_drives.filter(pl.col('turn') == 1).group_by('drive_name').agg([
            pl.col('health').mean().alias('initial_avg_health'),
            pl.col('debt').mean().alias('initial_avg_debt'),
        ])

        mo.md(f"""
        ### Drive Health Summary (Turn {max_turn})

        | Drive | Initial Health | Final Health | Final Debt | Status |
        |-------|---------------|--------------|------------|--------|
        """)

        final_stats.join(initial_stats, on='drive_name', how='left').to_pandas()
    return (max_turn, final_stats, initial_stats)


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 3. Root Cause Analysis: Configuration Audit

    Let's examine the configuration to understand why shelter materials aren't being produced or traded.
    """)
    return


@app.cell
def _(mo):
    # Load and analyze processes from YAML
    import yaml
    from pathlib import Path as P

    processes_path = P('/home/timg/code/spacesim2/data/processes.yaml')
    commodities_path = P('/home/timg/code/spacesim2/data/commodities.yaml')

    with open(processes_path) as f:
        processes = yaml.safe_load(f)

    with open(commodities_path) as f:
        commodities = yaml.safe_load(f)

    commodity_ids = [c['id'] for c in commodities]

    # Identify shelter-related processes
    shelter_processes = []
    for proc in processes:
        outputs = list(proc.get('outputs', {}).keys())
        if any(o in ['wood', 'common_metal', 'common_metal_ore'] for o in outputs):
            shelter_processes.append(proc)

    # Check if clothing exists
    clothing_exists = 'clothing' in commodity_ids
    clothing_processes = [p for p in processes if 'clothing' in p.get('outputs', {})]

    mo.md(f"""
    ### Process Configuration Analysis

    **Shelter Material Production Processes:**

    | Process | Inputs | Outputs | Labor |
    |---------|--------|---------|-------|
    """ + "\n".join([
        f"| {p['id']} | {p.get('inputs', 'None')} | {p['outputs']} | {p.get('labor', 1)} |"
        for p in shelter_processes
    ]) + f"""

    **Clothing Configuration:**
    - Clothing commodity exists in data/commodities.yaml: **{clothing_exists}**
    - Clothing production processes: **{[p['id'] for p in clothing_processes] if clothing_processes else 'NONE'}**

    **All Defined Commodities:** {commodity_ids}
    """)
    return (processes_path, commodities_path, processes, commodities, commodity_ids, shelter_processes, clothing_exists, clothing_processes, yaml, P)


@app.cell
def _(mo):
    mo.md("""
    ### Market Maker Configuration Analysis

    The market maker brains only create markets for specific commodities. Let's examine what they support:
    """)
    return


@app.cell
def _(mo):
    # Analyze market maker code
    mm1_commodities = ['food', 'nova_fuel', 'nova_fuel_ore']  # From market_maker_1.py line 37-39
    mm2_commodities = ['food', 'nova_fuel', 'nova_fuel_ore']  # From market_maker_2.py line 127-129

    shelter_commodities_needed = ['wood', 'common_metal', 'common_metal_ore']
    clothing_commodities_needed = ['clothing']

    mm_missing_shelter = [c for c in shelter_commodities_needed if c not in mm1_commodities]
    mm_missing_clothing = [c for c in clothing_commodities_needed if c not in mm1_commodities]

    mo.md(f"""
    **Market Maker Supported Commodities:**
    - MarketMakerBrain (v1): {mm1_commodities}
    - MarketMakerBrain (v2): {mm2_commodities}

    **Missing from Market Makers:**
    - Shelter materials: **{mm_missing_shelter}**
    - Clothing: **{mm_missing_clothing}**

    **Impact:** Without market maker support, these commodities have:
    - No buy orders for actors to sell to
    - No sell orders for actors to buy from
    - No price discovery mechanism
    - No liquidity for trade
    """)
    return (mm1_commodities, mm2_commodities, shelter_commodities_needed, clothing_commodities_needed, mm_missing_shelter, mm_missing_clothing)


@app.cell
def _(mo):
    mo.md("""
    ### Actor Brain Trading Configuration

    The actor brains (ColonistBrain, IndustrialistBrain) also have hardcoded commodity lists:
    """)
    return


@app.cell
def _(mo):
    # Analysis from reading the brain files
    colonist_trades = ['food', 'nova_fuel', 'nova_fuel_ore']  # From colonist.py lines 99-101
    industrialist_trades = ['food']  # Plus recipe inputs/outputs

    mo.md(f"""
    **ColonistBrain trades:** {colonist_trades}

    **IndustrialistBrain trades:**
    - Food (for personal consumption)
    - Recipe inputs/outputs (but only if recipe is selected AND profitable)

    **Critical Gap:** Neither brain type actively:
    - Produces shelter materials based on shelter drive needs
    - Trades shelter materials (wood, common_metal, common_metal_ore)
    - Produces or trades clothing

    **The economic decision loop** (`decide_economic_action`) prioritizes:
    1. Food production if food < 5
    2. Most profitable process (requires market prices to exist!)
    3. Government work (fallback)

    Since there's no market for shelter materials, they never become "profitable" to produce.
    """)
    return (colonist_trades, industrialist_trades)


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 4. Summary: Root Cause Chain
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ```
    ROOT CAUSE CHAIN
    ================

    1. MARKET MAKER GAP
       - Market makers only support: food, nova_fuel, nova_fuel_ore
       - Missing: wood, common_metal, common_metal_ore, clothing

           |
           v

    2. NO PRICE DISCOVERY
       - No buy/sell orders exist for shelter materials
       - market.get_avg_price() returns 0 or None
       - market.get_bid_ask_spread() returns (None, None)

           |
           v

    3. ACTOR BRAIN DECISION FAILURE
       - ColonistBrain._find_most_profitable_process() calculates:
         profit = output_value - input_cost
       - For wood: output_value = 0 (no market price)
       - Wood process never selected as "most profitable"

           |
           v

    4. NO PRODUCTION OF SHELTER MATERIALS
       - Actors never execute: harvest_wood, mine_common_metal_ore, refine_common_metal
       - No shelter materials enter the economy

           |
           v

    5. SHELTER DRIVE FAILURE
       - ShelterDrive needs wood OR common_metal
       - Actors have 0 inventory of both
       - health = 0, debt accumulates to ~1.0

           |
           v

    6. CLOTHING DRIVE FAILURE (SEPARATE ISSUE)
       - "clothing" commodity doesn't exist in commodities.yaml
       - No process produces clothing
       - ClothingDrive references non-existent commodity
       - Always fails
    ```
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 5. Recommended Fixes

    ### Fix 1: Add shelter commodities to market makers

    In `spacesim2/core/brains/market_maker_1.py` and `market_maker_2.py`, add:
    ```python
    wood_commodity = actor.sim.commodity_registry["wood"]
    metal_commodity = actor.sim.commodity_registry["common_metal"]
    metal_ore_commodity = actor.sim.commodity_registry["common_metal_ore"]

    for commodity_type in [food_commodity, fuel_commodity, fuel_ore_commodity,
                           wood_commodity, metal_commodity, metal_ore_commodity]:
        # ... existing market making logic
    ```

    ### Fix 2: Add clothing commodity and production process

    In `data/commodities.yaml`:
    ```yaml
    - id: clothing
      name: Clothing
      transportable: true
      description: Basic clothing for protection and comfort.
    ```

    In `data/processes.yaml`:
    ```yaml
    - id: make_clothing
      name: Make Clothing
      inputs:
        biomass: 2  # or some fiber/textile commodity
      outputs:
        clothing: 1
      tools_required: []
      facilities_required: []
      labor: 1
      relevant_skills:
        - simple_manufacturing
      description: Creates basic clothing from raw materials.
    ```

    ### Fix 3: Add clothing to market makers

    Same pattern as shelter materials - add clothing to the market maker commodity list.

    ### Fix 4 (Optional): Add drive-aware production

    Modify actor brains to check drive health and prioritize producing needed materials:
    ```python
    # In decide_economic_action:
    if actor.shelter_drive.metrics.health < 0.5:
        # Prioritize shelter material production
        if actor.can_execute_process("harvest_wood"):
            return ProcessCommand("harvest_wood")
    ```
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ---
    ## 6. Validation: Market Snapshot Analysis

    Let's verify that no market activity exists for shelter materials.
    """)
    return


@app.cell
def _(data, mo, pl):
    if data is None:
        "No data"
    elif len(data.market_snapshots) > 0:
        # Check which commodities appear in market snapshots
        commodities_with_snapshots = data.market_snapshots.select('commodity_id').unique().to_series().to_list()

        # Check for shelter materials
        shelter_in_snapshots = [c for c in ['wood', 'common_metal', 'common_metal_ore'] if c in commodities_with_snapshots]

        # Get price history for any existing shelter materials
        if shelter_in_snapshots:
            shelter_prices = data.market_snapshots.filter(
                pl.col('commodity_id').is_in(shelter_in_snapshots)
            )
            mo.md(f"""
            **Shelter materials in market snapshots:** {shelter_in_snapshots}

            Price data:
            """)
            shelter_prices.to_pandas()
        else:
            mo.md(f"""
            **Commodities with market data:** {sorted(commodities_with_snapshots)}

            **Shelter materials (wood, common_metal, common_metal_ore):** NONE have any market snapshot data

            This confirms that no market activity occurred for these commodities.
            """)
    return (commodities_with_snapshots, shelter_in_snapshots)


if __name__ == "__main__":
    app.run()
