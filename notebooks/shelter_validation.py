import marimo

__generated_with = "0.18.1"
app = marimo.App()


@app.cell
def _():
    import os
    import marimo as mo
    import polars as pl
    import plotly.express as px
    from spacesim2.analysis.loading.loader import SimulationData
    from spacesim2.analysis.loading import get_run_path_with_fallback
    from pathlib import Path
    return Path, SimulationData, get_run_path_with_fallback, mo, os, pl, px


@app.cell
def _(Path, SimulationData, get_run_path_with_fallback, mo, os):
    run_path = get_run_path_with_fallback()
    data = SimulationData(run_path)

    mo.md(f"""
    # Shelter Drive Validation

    **Run:** {run_path.name}
    """)
    return data, run_path


@app.cell
def _(data, mo, pl):
    # Filter shelter drive data
    shelter = data.actor_drives.filter(pl.col("drive_name") == "shelter")

    stats = shelter.select(["health", "debt", "buffer", "urgency"]).describe()

    mo.md(f"""
    ## Shelter Drive Statistics

    **Records:** {shelter.height}

    {stats}
    """)
    return shelter, stats


@app.cell
def _(mo, pl, shelter):
    # Calculate unhealthy periods
    total = shelter.height
    unhealthy = shelter.filter(pl.col("health") < 0.5).height
    high_debt = shelter.filter(pl.col("debt") > 0.5).height
    very_high_debt = shelter.filter(pl.col("debt") > 0.8).height

    mo.md(f"""
    ## Shelter Health Assessment

    | Metric | Count | Percentage |
    |--------|-------|------------|
    | Total records | {total} | 100% |
    | Unhealthy (health < 0.5) | {unhealthy} | {100*unhealthy/total:.1f}% |
    | High debt (debt > 0.5) | {high_debt} | {100*high_debt/total:.1f}% |
    | Very high debt (debt > 0.8) | {very_high_debt} | {100*very_high_debt/total:.1f}% |
    """)
    return high_debt, total, unhealthy, very_high_debt


@app.cell
def _(pl, px, shelter):
    # Shelter health over time
    avg_health = shelter.group_by("turn").agg(
        pl.col("health").mean().alias("avg_health"),
        pl.col("debt").mean().alias("avg_debt"),
        pl.col("buffer").mean().alias("avg_buffer"),
    ).sort("turn")

    fig = px.line(
        avg_health.to_pandas(),
        x="turn",
        y=["avg_health", "avg_debt", "avg_buffer"],
        title="Shelter Drive Metrics Over Time",
        labels={"value": "Value (0-1)", "turn": "Turn", "variable": "Metric"}
    )
    fig
    return avg_health, fig


@app.cell
def _(mo):
    mo.md("""
    ## Shelter-Related Market Analysis

    Shelter consumes either **wood** or **common_metal**. Common metal is refined from **common_metal_ore**.
    """)
    return


@app.cell
def _(data, mo, pl):
    # Market commodities relevant to shelter
    shelter_commodities = ["wood", "common_metal", "common_metal_ore"]

    market_data = data.market_snapshots.filter(
        pl.col("commodity_id").is_in(shelter_commodities)
    )

    # Check what commodities exist in market data
    all_commodities = data.market_snapshots.select("commodity_id").unique().to_series().to_list()
    shelter_found = [c for c in shelter_commodities if c in all_commodities]
    shelter_missing = [c for c in shelter_commodities if c not in all_commodities]

    # Get price and volume stats
    if market_data.height > 0:
        price_stats = market_data.group_by("commodity_id").agg(
            pl.col("avg_price").mean().alias("mean_price"),
            pl.col("avg_price").min().alias("min_price"),
            pl.col("avg_price").max().alias("max_price"),
            pl.col("avg_price").std().alias("price_std"),
        )
        price_table = str(price_stats)
    else:
        price_table = "No price data for shelter commodities"

    mo.md(f"""
    ### Market Price Statistics

    **Commodities in market:** {len(all_commodities)} total
    **Shelter commodities found:** {shelter_found if shelter_found else 'NONE'}
    **Shelter commodities missing:** {shelter_missing if shelter_missing else 'none'}

    {price_table}
    """)
    return all_commodities, market_data, price_stats, shelter_commodities, shelter_found, shelter_missing


@app.cell
def _(market_data, px):
    # Price trends for shelter commodities
    fig_prices = px.line(
        market_data.to_pandas(),
        x="turn",
        y="avg_price",
        color="commodity_id",
        title="Shelter Material Prices Over Time",
        labels={"avg_price": "Average Price ($)", "turn": "Turn", "commodity_id": "Commodity"}
    )
    fig_prices
    return (fig_prices,)


@app.cell
def _(data, mo, pl, shelter_commodities):
    # Transaction volume for shelter commodities
    txns = data.market_transactions.filter(
        pl.col("commodity_id").is_in(shelter_commodities)
    )

    # Check all commodities that have transactions
    all_txn_commodities = data.market_transactions.select("commodity_id").unique().to_series().to_list()

    if txns.height > 0:
        volume_by_commodity = txns.group_by("commodity_id").agg(
            pl.col("quantity").sum().alias("total_volume"),
            pl.col("quantity").count().alias("num_transactions"),
            pl.col("price").mean().alias("avg_transaction_price"),
        )
        volume_table = str(volume_by_commodity)
    else:
        volume_by_commodity = None
        volume_table = "NO TRANSACTIONS for shelter materials!"

    mo.md(f"""
    ### Transaction Volume for Shelter Materials

    **Total transaction records:** {data.market_transactions.height}
    **Commodities with transactions:** {all_txn_commodities}
    **Shelter material transactions:** {txns.height}

    {volume_table}
    """)
    return all_txn_commodities, txns, volume_by_commodity


@app.cell
def _(mo, pl, txns):
    # Transaction timeline
    txn_timeline = txns.group_by(["turn", "commodity_id"]).agg(
        pl.col("quantity").sum().alias("volume")
    ).sort("turn")

    if txn_timeline.height == 0:
        mo.md("**Warning: No transactions for shelter materials!**")
    else:
        mo.md(f"Total transaction records: {txn_timeline.height}")
    return (txn_timeline,)


@app.cell
def _(px, txn_timeline):
    if txn_timeline.height > 0:
        fig_volume = px.line(
            txn_timeline.to_pandas(),
            x="turn",
            y="volume",
            color="commodity_id",
            title="Transaction Volume Over Time",
            labels={"volume": "Quantity Traded", "turn": "Turn", "commodity_id": "Commodity"}
        )
        fig_volume
    else:
        "No transactions to display"
    return (fig_volume,)


@app.cell
def _(data, mo, pl):
    # Check all drives for comparison
    all_drives = data.actor_drives.group_by("drive_name").agg(
        pl.col("health").mean().alias("avg_health"),
        pl.col("debt").mean().alias("avg_debt"),
        pl.col("buffer").mean().alias("avg_buffer"),
    )

    mo.md(f"""
    ## Comparison: All Drives

    {all_drives}
    """)
    return (all_drives,)


@app.cell
def _(mo, all_drives, pl, shelter):
    # Final assessment
    shelter_avg_health = shelter.select(pl.col("health").mean()).item()
    shelter_avg_debt = shelter.select(pl.col("debt").mean()).item()
    shelter_end_health = shelter.filter(pl.col("turn") == shelter["turn"].max()).select(pl.col("health").mean()).item()

    if shelter_avg_health > 0.5 and shelter_avg_debt < 0.5:
        status = "HEALTHY"
        emoji = "✅"
    elif shelter_avg_health > 0.3 or shelter_end_health > 0.5:
        status = "MODERATE"
        emoji = "⚠️"
    else:
        status = "UNHEALTHY"
        emoji = "❌"

    mo.md(f"""
    ## Summary

    {emoji} **Shelter Drive Status: {status}**

    - Average health: {shelter_avg_health:.3f}
    - Average debt: {shelter_avg_debt:.3f}
    - End-of-simulation health: {shelter_end_health:.3f}

    ### All Drive Comparison
    {all_drives}
    """)
    return emoji, shelter_avg_debt, shelter_avg_health, shelter_end_health, status


if __name__ == "__main__":
    app.run()
