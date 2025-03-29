# MVP Simulation Design Document

This document outlines the minimal viable product (MVP) for a turn-based economic simulation. The goal is to build a running system step-by-step, ensuring that after each task, we have a fully operational simulation that can be tested and validated.

---

## Table of Contents
1. [Overview](#overview)
2. [Simulation Entities](#simulation-entities)
   - [Actors](#actors)
   - [Market](#market)
   - [Planets](#planets)
   - [Ships](#ships)
3. [Commodities](#commodities)
   - [Categories](#categories)
   - [Tool & Factory Mechanics](#tool--factory-mechanics)
4. [Monetary System](#monetary-system)
5. [Turn Processing](#turn-processing)

---

## 1. Overview

In this simulation:
- **Planets** have zero internal friction: any actor on the same planet trades instantly with no transaction cost (beyond those defined in the market).
- **Actors** each turn make one economic action (produce, work, build, etc.) and can place multiple buy/sell orders in a local commodity market.
- **Market-makers** are special actors with a trading preference but no extra privileges.
- **Ships** facilitate interplanetary trade, buying commodities on one planet and selling on another.
- **Money** enters the system through fixed-wage “government work.”

The MVP aims to validate core economic actions, simple commodity markets, and interplanetary trade mechanics without overcomplicating skill growth, health, or advanced governance.

---

## 2. Simulation Entities

### 2.1 Actors
- **Regular Actors**  
  - **Attributes**: money, inventory, (optional) skills, consumption needs.  
  - **Actions**: 
    1. *Economic Action* (one per turn) – examples include producing a commodity, working at a factory, building/maintaining infrastructure, or doing government work.  
    2. *Market Actions* (multiple, limited only for performance) – place buy/sell orders on the local market.  
  - **Motivation**: Meet basic needs (food, shelter, etc.) and accumulate wealth.

- **Market-Makers**  
  - Mechanically identical to regular actors, but they aim to profit from market spreads.  
  - No special privileges in order matching.

- **Ships**  
  - A specialized actor type representing a transport vessel.  
  - Can purchase commodities (especially fuel), travel between planets, and sell cargo for profit.  
  - Uniform ships in MVP: fixed cargo capacity, speed, fuel efficiency.

### 2.2 Market
- Each planet has its own **Market** object.  
- **Order-Matching**: Limit orders are matched if bid ≥ ask, with immediate execution. Unmatched orders persist until the turn ends or are canceled.  
- Execution results (money or goods) are only usable from the next turn onward.

### 2.3 Planets
- **Planets**: host a local market and a fixed population of actors.  
- **Resources**: distributed randomly, influencing what commodities can be easily produced on each planet.  
- **Zero friction** on-planet for travel/communication.

### 2.4 Ships
- **Distance Calculation**: Planets exist in a 2D coordinate space. Travel time is based on distance.  
- **Fuel Consumption**: Must buy and carry refined fuel for each journey.  
- **Maintenance**: Random chance of maintenance requirement before trips, consuming commodities.  
- **No additional risks** (piracy, spoilage) in the MVP.

---

## 3. Commodities

### 3.1 Categories
1. **Raw Resources**: e.g., ores, agricultural products, “fuel-ore.”  
2. **Handmade Goods**: items produced without large infrastructure.  
3. **Manufactured Goods**: require factories or tools (blueprints define inputs/outputs).  
4. **Fuel**: refined from “fuel-ore” for ship travel.

### 3.2 Tool & Factory Mechanics
- **Tools**: degrade randomly on use, so no detailed tracking of partial durability.  
- **Factories**:  
  - Built once, consuming specified commodities.  
  - Require periodic maintenance (consuming smaller amounts of commodities).  
  - Can refine or transform inputs into higher-value goods.

---

## 4. Monetary System
- **Government Work** injects currency at a fixed wage each turn.  
- Actors opt for government work only if other activities are not profitable.  
- For the MVP, no taxation or money removal. Any offset can come in future iterations.

---

## 5. Turn Processing
1. **Randomized Actor Order** each turn to avoid systematic advantage.  
2. **Actor’s Economic Action**: produce, build, maintain, work, or do government work.  
3. **Actor’s Market Actions**: place buy/sell orders on the local market.  
   - Matched trades execute instantly, but resulting goods/money become available next turn.  
4. **Interplanetary Travel**: occurs after an actor sets a travel action (ships only); apply any required fuel consumption, travel time.  
5. **Maintenance Checks**: random checks for factory, tool, and ship maintenance.

