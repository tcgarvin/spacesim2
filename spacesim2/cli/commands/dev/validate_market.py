"""Market maker validation command implementation."""

import argparse
import random

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import norm

from spacesim2.cli.common import create_and_setup_simulation
from spacesim2.cli.output import print_success
from spacesim2.core.actor import ActorType


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore
    """Add the 'validate-market' dev subcommand parser.

    Args:
        subparsers: Subparsers to add this command to

    Returns:
        The created parser
    """
    parser = subparsers.add_parser(
        "validate-market",
        help="Validate market maker behavior with visualization",
        description="Run a simulation to validate market maker behavior and generate plots",
    )

    parser.add_argument(
        "--turns", type=int, default=20, help="Number of turns to simulate (default: 20)"
    )
    parser.add_argument(
        "--actors", type=int, default=8, help="Number of regular actors (default: 8)"
    )
    parser.add_argument(
        "--makers", type=int, default=1, help="Number of market makers (default: 1)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="market_maker_validation.png",
        help="Output plot file path (default: market_maker_validation.png)",
    )

    parser.set_defaults(func=execute)
    return parser


def _modify_simulation_params(simulation):  # type: ignore
    """Modify simulation parameters for better validation.

    Args:
        simulation: Simulation instance to modify
    """
    # Get RAW_FOOD commodity
    raw_food = simulation.commodity_registry.get_commodity("RAW_FOOD")
    if not raw_food:
        print("Warning: RAW_FOOD commodity not found")
        return

    # Update regular actors to be more willing to sell excess food
    for actor in simulation.actors:
        if actor.actor_type == ActorType.REGULAR:
            # Randomize production efficiency to create more varied supply
            actor.production_efficiency = random.uniform(0.8, 1.5)

            # Give some initial money variation
            actor.money = random.randint(40, 70)

            # Give regular actors more initial food
            actor.inventory.add_commodity(raw_food, random.randint(1, 5))

    # Give market maker more starting capital
    for actor in simulation.actors:
        if actor.actor_type == ActorType.MARKET_MAKER:
            actor.money = 500


def _plot_market_maker_behavior(simulation, num_turns: int, output_path: str):  # type: ignore
    """Run a simulation and plot the market maker behavior.

    Args:
        simulation: Simulation instance
        num_turns: Number of turns to simulate
        output_path: Path to save the plot
    """
    # Get RAW_FOOD commodity
    raw_food = simulation.commodity_registry.get_commodity("RAW_FOOD")
    if not raw_food:
        print("Error: RAW_FOOD commodity not found")
        return

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
        avg_prices.append(market.get_avg_price(raw_food))
        inventory.append(market_maker.inventory.get_quantity(raw_food))

        # Get order stats
        orders = market.get_actor_orders(market_maker)
        buy_orders = orders["buy"]
        sell_orders = orders["sell"]

        buy_order_counts.append(len(buy_orders))
        sell_order_counts.append(len(sell_orders))

        # Calculate price ranges
        buy_prices = [order.price for order in buy_orders] if buy_orders else []
        sell_prices = [order.price for order in sell_orders] if sell_orders else []

        buy_price_ranges.append(
            (min(buy_prices) if buy_prices else 0, max(buy_prices) if buy_prices else 0)
        )
        sell_price_ranges.append(
            (
                min(sell_prices) if sell_prices else 0,
                max(sell_prices) if sell_prices else 0,
            )
        )

        # Record last market action
        market_action_logs.append(market_maker.last_market_action)

    # Plot results
    fig, axs = plt.subplots(3, 1, figsize=(12, 15), sharex=True)

    # Plot 1: Average price and inventory
    ax1 = axs[0]
    ax1.set_title("Market Maker Behavior")
    ax1.set_ylabel("Price / Inventory")
    price_line = ax1.plot(turns, avg_prices, "b-", label="Avg Price")
    ax1.tick_params(axis="y", labelcolor="b")

    ax1_2 = ax1.twinx()
    inventory_line = ax1_2.plot(turns, inventory, "r-", label="MM Inventory")
    ax1_2.tick_params(axis="y", labelcolor="r")
    ax1_2.set_ylabel("MM Inventory", color="r")

    # Combine legends
    lines = price_line + inventory_line
    labels = [line.get_label() for line in lines]
    ax1.legend(lines, labels, loc="upper left")

    # Plot 2: Order counts
    ax2 = axs[1]
    ax2.set_ylabel("Order Counts")
    ax2.plot(turns, buy_order_counts, "g-", label="Buy Orders")
    ax2.plot(turns, sell_order_counts, "m-", label="Sell Orders")
    ax2.legend()

    # Plot 3: Price ranges
    ax3 = axs[2]
    ax3.set_ylabel("Price Ranges")
    ax3.set_xlabel("Turn")

    # Plot buy price ranges
    for i, (min_price, max_price) in enumerate(buy_price_ranges):
        if max_price > 0:  # Only plot if there are orders
            ax3.plot([turns[i], turns[i]], [min_price, max_price], "g-", alpha=0.6)
            ax3.plot([turns[i]], [min_price], "go", alpha=0.6, markersize=4)
            ax3.plot([turns[i]], [max_price], "go", alpha=0.6, markersize=4)

    # Plot sell price ranges
    for i, (min_price, max_price) in enumerate(sell_price_ranges):
        if max_price > 0:  # Only plot if there are orders
            ax3.plot([turns[i], turns[i]], [min_price, max_price], "m-", alpha=0.6)
            ax3.plot([turns[i]], [min_price], "mo", alpha=0.6, markersize=4)
            ax3.plot([turns[i]], [max_price], "mo", alpha=0.6, markersize=4)

    # Plot average price for reference
    ax3.plot(turns, avg_prices, "b--", label="Avg Price", alpha=0.5)
    ax3.legend()

    plt.tight_layout()
    plt.savefig(output_path)
    print(f"Plot saved to '{output_path}'")

    # Print market action logs
    print("\nMarket Action Logs:")
    for turn, log in zip(turns, market_action_logs):
        print(f"Turn {turn}: {log}")


def _test_normal_distribution() -> None:
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
    low_price = norm.ppf(1 - p, loc=average_price, scale=price_sigma)

    print("\nSymmetry check:")
    print(f"Price at {p:.2f} percentile: {high_price:.2f}")
    print(f"Price at {1-p:.2f} percentile: {low_price:.2f}")
    print(f"Average of both: {(high_price + low_price)/2:.2f}")
    print(f"Should be close to average price: {average_price}")


def execute(args: argparse.Namespace) -> int:
    """Execute the validate-market command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Test the normal distribution calculations
    _test_normal_distribution()

    # Create and initialize simulation
    simulation = create_and_setup_simulation(
        planets=1, actors=args.actors, makers=args.makers, ships=0
    )

    # Modify simulation parameters for better validation
    _modify_simulation_params(simulation)

    # Run simulation and plot results
    _plot_market_maker_behavior(simulation, args.turns, args.output)

    print_success("Market maker validation complete!")
    return 0
