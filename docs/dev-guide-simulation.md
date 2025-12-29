# Simulation Architecture & Development Guide

This guide covers the simulation's internal architecture, turn execution flow, and how to test/debug simulation behavior.

## Turn Execution Order

Each turn executes in this order:

1. **Actors take turns** (randomized order each turn)
   - Each actor calls `actor.take_turn()` which executes:
     - One economic action (production/work)
     - Multiple market actions (buy/sell orders)
     - Drive processing (consumption)

2. **Ships take turns** (randomized order each turn)
   - Each ship calls `ship.take_turn()` which executes:
     - Journey updates (if traveling)
     - Trade decisions via `brain.decide_trade_actions()`
     - Travel decisions via `brain.decide_travel()`

3. **Markets process all orders** (deferred matching at end of turn)
   - ALL buy and sell orders are matched simultaneously
   - Matching uses price-time priority
   - This prevents order-dependency issues

## Key Implications

- **Orders are not immediate**: When a ship places a buy order, it won't have the cargo until AFTER the market processes (end of turn)
- **Next-turn cargo checks**: Ships should expect cargo to arrive the turn AFTER placing orders
- **Concurrent decisions**: All ships see the same market state when making decisions
- **Market dynamics**: Prices can change significantly between when a plan is made and when orders execute

## Testing Simulation Behavior

When debugging AI or market mechanics, **use marimo notebooks** to examine simulation state:

```bash
# Run simulation with data export
uv run spacesim2 analyze --turns 100 --notebook

# Or use specific notebook for ship analysis
uv run spacesim2 analyze --turns 100 --notebook --notebook-path notebooks/ship_economics.py
```

Notebooks let you:
- Interactively explore actor/ship state across turns
- Visualize market price dynamics
- Compare different simulation runs
- Preserve analysis for future reference

See `docs/dev-guide-notebooks.md` for notebook development patterns.

**Why 50+ turns?**: Markets need time to develop price differentials through:
- Actors producing/consuming commodities
- Market makers establishing price bands
- Supply/demand imbalances emerging between planets

## Core Components

| Component | File | Description |
|-----------|------|-------------|
| Simulation | `core/simulation.py` | Main loop, setup, orchestration |
| Actor | `core/actor.py` | Economic agents with inventory, money, skills |
| Market | `core/market.py` | Order matching, price discovery |
| Ship | `core/ship.py` | Interplanetary trade vessels |
| Planet | `core/planet.py` | Locations with markets and actors |
| Process | `core/process.py` | Production recipes |
| Commodity | `core/commodity.py` | Tradeable goods definitions |

## Brain Architecture

Actors and ships delegate decision-making to pluggable "brain" classes:

**Actor Brains** (in `core/brains/`):
- `ColonistBrain` - Flexible generalist, meets basic needs first
- `IndustrialistBrain` - Specializes in one production recipe
- `MarketMakerBrain` - Provides liquidity using statistical pricing

**Ship Brains** (in `core/ship.py`):
- `TraderBrain` - Plan-driven interplanetary arbitrage

See `docs/dev-guide-ships.md` for detailed ship AI development patterns.

## Market Mechanics

### Order Types
- **Buy Orders**: Actor reserves money, waits for match
- **Sell Orders**: Actor reserves commodities, waits for match

### Price Discovery
```python
# Get current bid/ask spread
bid, ask = market.get_bid_ask_spread(commodity)

# bid = highest buy order (what buyers will pay)
# ask = lowest sell order (what sellers want)

# Historical average (last 10 trades)
avg = market.get_avg_price(commodity)

# 30-day moving average
avg_30 = market.get_30_day_average_price(commodity)
```

### Order Matching Algorithm
1. For each commodity type:
   - Sort buy orders: highest price first, oldest first
   - Sort sell orders: lowest price first, oldest first
2. Match where buy price >= sell price
3. Transaction price = seller's asking price
