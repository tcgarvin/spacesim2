# MVP Simulation Design Document

## Overview
A turn-based economic simulation featuring multiple planets with frictionless internal economies, actors performing economic activities, and interplanetary commodity trading.

---

## Simulation Entities

### Actors
- **Regular Actors**:
  - Hold inventories and currency.
  - Perform one economic action per turn (production, labor, maintenance).
  - Execute multiple market actions per turn (buying/selling commodities).
  - May perform "government work" to inject currency into the economy when other actions are unprofitable.

- **Market-Makers**:
  - Identical to regular actors but prioritize market-making strategies.
  - No special market privileges.

- **Ships**:
  - Specialized actors transporting commodities between planets.
  - Fixed cargo capacity, fuel efficiency, and speed.
  - Consume refined fuel and commodities for maintenance.

### Commodities
Defined in YAML format. Each commodity is:
- **Transportable** (tools, raw materials, refined goods) or **Non-transportable** (facilities).

Example:
```yaml
- id: common_metal
  name: Common Metal
  transportable: true
  description: Refined metal suitable for construction and tool-making.

- id: smelting_facility
  name: Smelting Facility
  transportable: false
  description: Infrastructure for refining metal ores.
```

### Processes
Economic activities consuming inputs (commodities, labor, facilities, tools) and producing outputs (commodities).

Example:
```yaml
- id: refine_common_metal
  name: Refine Common Metal
  inputs:
    common_metal_ore: 3
  outputs:
    common_metal: 2
  tools_required: []
  facilities_required:
    - smelting_facility
  labor: 2
  description: Smelts common metal ore into usable metal.
```

**Facilities** contain tools necessary for production; actors provide labor.

---

## Markets
- Each planet has an order-matching commodity market.
- Orders persist across turns unless explicitly canceled.
- Matched orders execute immediately, but commodities/money become available next turn.

---

## Planets and Solar Systems
- Planets exist within solar systems in 2D coordinate space.
- Resources distributed randomly; specialization can emerge naturally.
- Fixed populations initially, with actors aiming to meet basic needs (food, shelter).

---

## Interplanetary Trade
- Ships move commodities between planets, consuming refined fuel and occasional maintenance commodities.
- Travel duration based on spatial coordinates; no travel risks in MVP.

---

## Monetary System
- Currency injected via actors performing "government work," providing a fixed daily wage.
- Money represents a debt owed by the government ("King's debt").

---

## Economic Graph
- Commodities and processes form a directed economic graph (commodity ↔ process relationships).
- AI actors utilize this graph to identify opportunities based on market conditions and inventory states.

---

## Decision and Turn Execution
- Actors take turns in randomized order each round.
- Each actor:
  1. Performs one economic action.
  2. Places multiple market orders (limited by CPU constraints).

- Results of market actions become available on the next turn.

---

## Future Extensions
- Population growth and decay.
- Skill-based labor markets.
- Expanded government economic controls (taxes, subsidies).
- Market information delays.
- Travel hazards and piracy.

This document reflects the current state of the MVP design, capturing key elements and structures for initial implementation and iteration.

