#!/usr/bin/env python

from spacesim2.core.simulation import Simulation
from spacesim2.core.actor import ActorType
from spacesim2.core.commodity import CommodityType
import random
import statistics
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import norm

def plot_market_maker_behavior(simulation, num_turns=20):
    """Run a simulation and plot the market maker behavior."""
    # Get reference to market and market maker
    planet = simulation.planets[0]
    market = planet.market
    market_maker = None
    for actor in simulation.actors:
        if actor.actor_type == ActorType.MARKET_MAKER:
            market_maker = actor
            break
    
    if not market_maker:
        print("No market maker found in simulation")
        return
    
    # Data to track
    turns = []
    avg_prices = []
    inventory = []
    buy_order_counts = []
    sell_order_counts = []
    buy_price_ranges = []
    sell_price_ranges = []
    market_action_logs = []
    
    # Run simulation
    for i in range(num_turns):
        simulation.run_turn()
        
        # Record data
        turns.append(simulation.current_turn)
        avg_prices.append(market.get_avg_price(CommodityType.RAW_FOOD))
        inventory.append(market_maker.inventory.get_quantity(CommodityType.RAW_FOOD))
        
        # Get order stats
        orders = market.get_actor_orders(market_maker)
        buy_orders = orders["buy"]
        sell_orders = orders["sell"]
        
        buy_order_counts.append(len(buy_orders))
        sell_order_counts.append(len(sell_orders))
        
        # Calculate price ranges
        buy_prices = [order.price for order in buy_orders] if buy_orders else []
        sell_prices = [order.price for order in sell_orders] if sell_orders else []
        
        buy_price_ranges.append((min(buy_prices) if buy_prices else 0, 
                               max(buy_prices) if buy_prices else 0))
        sell_price_ranges.append((min(sell_prices) if sell_prices else 0, 
                                max(sell_prices) if sell_prices else 0))
        
        # Record last market action
        market_action_logs.append(market_maker.last_market_action)
    
    # Plot results
    fig, axs = plt.subplots(3, 1, figsize=(12, 15), sharex=True)
    
    # Plot 1: Average price and inventory
    ax1 = axs[0]
    ax1.set_title('Market Maker Behavior')
    ax1.set_ylabel('Price / Inventory')
    price_line = ax1.plot(turns, avg_prices, 'b-', label='Avg Price')
    ax1.tick_params(axis='y', labelcolor='b')
    
    ax1_2 = ax1.twinx()
    inventory_line = ax1_2.plot(turns, inventory, 'r-', label='MM Inventory')
    ax1_2.tick_params(axis='y', labelcolor='r')
    ax1_2.set_ylabel('MM Inventory', color='r')
    
    # Combine legends
    lines = price_line + inventory_line
    labels = [line.get_label() for line in lines]
    ax1.legend(lines, labels, loc='upper left')
    
    # Plot 2: Order counts
    ax2 = axs[1]
    ax2.set_ylabel('Order Counts')
    ax2.plot(turns, buy_order_counts, 'g-', label='Buy Orders')
    ax2.plot(turns, sell_order_counts, 'm-', label='Sell Orders')
    ax2.legend()
    
    # Plot 3: Price ranges
    ax3 = axs[2]
    ax3.set_ylabel('Price Ranges')
    ax3.set_xlabel('Turn')
    
    # Plot buy price ranges
    for i, (min_price, max_price) in enumerate(buy_price_ranges):
        if max_price > 0:  # Only plot if there are orders
            ax3.plot([turns[i], turns[i]], [min_price, max_price], 'g-', alpha=0.6)
            ax3.plot([turns[i]], [min_price], 'go', alpha=0.6, markersize=4)
            ax3.plot([turns[i]], [max_price], 'go', alpha=0.6, markersize=4)
    
    # Plot sell price ranges
    for i, (min_price, max_price) in enumerate(sell_price_ranges):
        if max_price > 0:  # Only plot if there are orders
            ax3.plot([turns[i], turns[i]], [min_price, max_price], 'm-', alpha=0.6)
            ax3.plot([turns[i]], [min_price], 'mo', alpha=0.6, markersize=4)
            ax3.plot([turns[i]], [max_price], 'mo', alpha=0.6, markersize=4)
    
    # Plot average price for reference
    ax3.plot(turns, avg_prices, 'b--', label='Avg Price', alpha=0.5)
    ax3.legend()
    
    plt.tight_layout()
    plt.savefig('market_maker_validation.png')
    print(f"Plot saved to 'market_maker_validation.png'")
    
    # Print market action logs
    print("\nMarket Action Logs:")
    for turn, log in zip(turns, market_action_logs):
        print(f"Turn {turn}: {log}")


def test_normal_distribution():
    """Test the normal distribution price calculations."""
    # Sample parameters
    average_price = 10
    price_sigma = 2
    
    # Test different percentiles
    percentiles = [0.1, 0.25, 0.5, 0.75, 0.9]
    
    print("\nNormal Distribution Price Tests:")
    print("--------------------------------")
    print("Percentile | Price")
    print("--------------------------------")
    
    for p in percentiles:
        price = norm.ppf(p, loc=average_price, scale=price_sigma)
        print(f"{p:.2f}       | {price:.2f}")
    
    # Verify symmetry
    p = 0.75
    high_price = norm.ppf(p, loc=average_price, scale=price_sigma)
    low_price = norm.ppf(1-p, loc=average_price, scale=price_sigma)
    
    print("\nSymmetry check:")
    print(f"Price at {p:.2f} percentile: {high_price:.2f}")
    print(f"Price at {1-p:.2f} percentile: {low_price:.2f}")
    print(f"Average of both: {(high_price + low_price)/2:.2f}")
    print(f"Should be close to average price: {average_price}")


def modify_simulation_params(simulation):
    """Modify simulation parameters for better validation."""
    # Update regular actors to be more willing to sell excess food
    for actor in simulation.actors:
        if actor.actor_type == ActorType.REGULAR:
            # Randomize production efficiency to create more varied supply
            actor.production_efficiency = random.uniform(0.8, 1.5)
            
            # Give some initial money variation
            actor.money = random.randint(40, 70)
            
            # Give regular actors more initial food
            actor.inventory.add_commodity(CommodityType.RAW_FOOD, random.randint(1, 5))
            
    # Give market maker more starting capital
    for actor in simulation.actors:
        if actor.actor_type == ActorType.MARKET_MAKER:
            actor.money = 500


if __name__ == "__main__":
    # Test the normal distribution calculations
    test_normal_distribution()
    
    # Create and initialize simulation
    simulation = Simulation()
    simulation.setup_simple(num_regular_actors=8, num_market_makers=1)
    
    # Modify simulation parameters for better validation
    modify_simulation_params(simulation)
    
    # Run simulation and plot results
    plot_market_maker_behavior(simulation, num_turns=20)