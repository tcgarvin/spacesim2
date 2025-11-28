"""Parquet table schemas for simulation data export."""

import pyarrow as pa


# Actor state per turn (money, inventory)
ACTOR_TURNS_SCHEMA = pa.schema([
    ("simulation_id", pa.string()),
    ("turn", pa.int32()),
    ("actor_id", pa.string()),
    ("actor_name", pa.string()),
    ("money", pa.int64()),
    ("reserved_money", pa.int64()),
    ("inventory_json", pa.string()),  # JSON string of {commodity_id: quantity}
    ("planet_name", pa.string()),
])

# Drive metrics per turn per actor
ACTOR_DRIVES_SCHEMA = pa.schema([
    ("simulation_id", pa.string()),
    ("turn", pa.int32()),
    ("actor_id", pa.string()),
    ("drive_name", pa.string()),  # food, clothing, shelter
    ("health", pa.float64()),
    ("debt", pa.float64()),
    ("buffer", pa.float64()),
    ("urgency", pa.float64()),
])

# Market transactions
MARKET_TRANSACTIONS_SCHEMA = pa.schema([
    ("simulation_id", pa.string()),
    ("turn", pa.int32()),
    ("planet_name", pa.string()),
    ("commodity_id", pa.string()),
    ("buyer_id", pa.string()),
    ("buyer_name", pa.string()),
    ("seller_id", pa.string()),
    ("seller_name", pa.string()),
    ("quantity", pa.int32()),
    ("price", pa.int64()),
    ("total_amount", pa.int64()),
])

# Aggregated market state per turn
MARKET_SNAPSHOTS_SCHEMA = pa.schema([
    ("simulation_id", pa.string()),
    ("turn", pa.int32()),
    ("planet_name", pa.string()),
    ("commodity_id", pa.string()),
    ("avg_price", pa.float64()),
    ("volume", pa.int32()),  # Total traded volume this turn
    ("num_buy_orders", pa.int32()),
    ("num_sell_orders", pa.int32()),
    ("best_bid", pa.int64()),  # Highest buy order price
    ("best_ask", pa.int64()),  # Lowest sell order price
])
