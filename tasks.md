### Task 1: Core Framework & Single Planet
1. **Create Project Skeleton**  
   - Main simulation loop (`Simulation` class or equivalent).  
   - Basic `Actor` and `Planet` classes.  
   - One planet, one actor setup.

2. **Turn Loop (Stub)**  
   - Minimal structure: for each turn, call `actor.take_turn()`.  
   - Print actor’s money at the end of each turn.

3. **Government Work Action**  
   - Inside `Actor.take_turn()`, implement a “government work” that yields a fixed wage per turn.

**Validation:**  
- **Run** for multiple turns, confirm actor’s money increases consistently.

---

### Task 2: Multiple Actors & Basic Market Stub
1. **Add Multiple Actors**  
   - Put 5 actors on a single planet, all performing government work.

2. **Market Class (Stub)**  
   - Create a `Market` class. No real logic yet—just placeholders for buy/sell orders.

3. **Refactor Turn Logic**  
   - Each actor, in random order, performs one economic action (still just government work).  
   - Leaves a placeholder for market actions.

**Validation:**  
- Ensure multiple actors can exist and earn money from government work.  
- Simulation runs to completion without error.

---

### Task 3: Single Commodity & Simple Market Matching
1. **Define a Commodity**  
   - Example: “Biofiber” with quantity tracking in actor inventories.

2. **Add a Production Action**  
   - Let an actor choose to produce “Biofiber” if they have sufficient money or meet certain conditions.  
   - Otherwise, they do government work.

3. **Implement Basic Market Trading**  
   - Actors place simple buy/sell orders (e.g., fixed price logic).  
   - Market matches orders if bid ≥ ask, transferring goods/money accordingly (usable next turn).

4. **Test**  
   - Observe some actors producing and others buying. Check correct money/commodity flow.

**Validation:**  
- **Run** for many turns, ensure the log shows trades and correct updates to money and inventories.

---

### Task 4: Expand to Multiple Commodities
1. **Add a Second Commodity** (e.g. “Fuel Ore”).  
2. **Separate Order Books** for each commodity in the market.  
3. **Refine Actor Decisions**  
   - Possibly use a simple threshold-based logic to choose which commodity to produce or whether to buy/sell.

**Validation:**  
- Confirm the simulation remains stable and both commodities can be traded.

---

### Task 5: Introduce Ships & Minimal Interplanetary Structure
1. **Add Second Planet**  
   - Each planet has its own market and population of actors (5 on each, for example).

2. **Ship Actor**  
   - Uniform capacity, fuel usage, speed.  
   - Buys fuel or fuel-ore on Planet A, travels, sells on Planet B.

3. **Distance & Travel Time**  
   - Use planet coordinates to compute travel time or number of turns required.  
   - Subtract required fuel upon departure.

4. **Maintenance**  
   - Random chance requiring maintenance commodities before the ship can travel.

**Validation:**  
- Watch a ship make profit by moving goods between two planets with different commodity prices.

---

### Task 6: Factories & Maintenance
1. **Blueprint** for refining fuel (e.g., from “Fuel Ore” to “Fuel”).  
2. **Building a Factory** consumes commodities (e.g., “Metal,” “Machine Parts”).  
3. **Maintenance**: factories periodically consume small amounts of input to remain operational.  
4. **Operate Factory**: an actor can spend their economic action to transform “Fuel Ore” → “Fuel.”

**Validation:**  
- Confirm that building and using factories is profitable if product prices justify the effort.

---

### Task 7: Market-Maker Strategies
1. **Identify Market-Maker Actors**  
   - A small number of actors have a special flag or strategy preference.
2. **Spread-Based Orders**  
   - They place buy orders slightly below average price, sell orders slightly above.
3. **Evaluate Profit**  
   - Track how much they earn via buy-sell spreads vs. other means.

**Validation:**  
- Ensure these market-makers provide liquidity and can be profitable under the right conditions.

---

### Task 8: Fine-Tuning & Basic Analytics
1. **Data Collection**  
   - Track prices, volumes, average money per actor, total population consumption.
2. **Simple Reports/Plots**  
   - Generate charts or console summaries to highlight trends over time.
3. **Parameter Adjustments**  
   - Tweak daily wage, resource distribution, maintenance frequency, etc.  
   - Re-run to see how the economy stabilizes or reacts.

**Validation:**  
- Final check of system-wide behavior.  
- Confirm that the economy looks sensible (e.g., no infinite inflation or mass actor starvation unless intentionally set).

