"""Main coordinator for exporting simulation data to Parquet files."""

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from spacesim2.analysis.export import schema
from spacesim2.analysis.export.streaming_writer import StreamingParquetWriter

if TYPE_CHECKING:
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.market import Market, Transaction
    from spacesim2.core.simulation import Simulation


def transactions_for_turn(market: "Market", turn: int) -> list["Transaction"]:
    """Return the market's transactions for one turn, in execution order.

    ``transaction_history`` is appended in turn order, so this turn's
    transactions form a suffix; scanning backwards from the end makes this
    O(this turn's transactions) instead of O(full history).

    Args:
        market: The market whose history to slice.
        turn: The turn to select.

    Returns:
        This turn's transactions, oldest first.
    """
    result: list[Transaction] = []
    for tx in reversed(market.transaction_history):
        if tx.turn != turn:
            break
        result.append(tx)
    result.reverse()
    return result


def volume_by_commodity(
    transactions: list["Transaction"],
) -> dict["CommodityDefinition", int]:
    """Sum traded quantity per commodity over a list of transactions."""
    volumes: dict[CommodityDefinition, int] = {}
    for tx in transactions:
        volumes[tx.commodity_type] = volumes.get(tx.commodity_type, 0) + tx.quantity
    return volumes


class SimulationExporter:
    """Handles exporting simulation data to Parquet files during execution."""

    def __init__(self, output_dir: Path, simulation_id: str):
        """
        Initialize simulation exporter.

        Args:
            output_dir: Directory to write Parquet files
            simulation_id: Unique identifier for this simulation run
        """
        self.output_dir = output_dir
        self.simulation_id = simulation_id
        self.writers: dict[str, StreamingParquetWriter] = {}
        self.start_time = datetime.now()

    def setup(self, simulation: "Simulation") -> None:
        """
        Initialize export schema and writers.

        Args:
            simulation: Simulation instance to export
        """
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize writers for each table
        self.writers["actor_turns"] = StreamingParquetWriter(
            self.output_dir / "actor_turns.parquet",
            schema.ACTOR_TURNS_SCHEMA,
            batch_size=1000,
        )

        self.writers["actor_drives"] = StreamingParquetWriter(
            self.output_dir / "actor_drives.parquet",
            schema.ACTOR_DRIVES_SCHEMA,
            batch_size=1000,
        )

        self.writers["market_transactions"] = StreamingParquetWriter(
            self.output_dir / "market_transactions.parquet",
            schema.MARKET_TRANSACTIONS_SCHEMA,
            batch_size=500,
        )

        self.writers["market_snapshots"] = StreamingParquetWriter(
            self.output_dir / "market_snapshots.parquet",
            schema.MARKET_SNAPSHOTS_SCHEMA,
            batch_size=500,
        )

        self._export_planet_attributes(simulation)

    def export_turn(self, simulation: "Simulation", turn: int) -> None:
        """
        Export data for a single turn.

        Args:
            simulation: Simulation instance
            turn: Current turn number
        """
        # Export actor state for logged actors
        for actor in simulation.data_logger.get_all_logged_actors():
            # Actor state
            inventory_dict = {
                commodity.id: actor.inventory.get_quantity(commodity)
                for commodity in simulation.commodity_registry.all_commodities()
                if actor.inventory.get_quantity(commodity) > 0
            }

            self.writers["actor_turns"].write_row(
                {
                    "simulation_id": self.simulation_id,
                    "turn": turn,
                    "actor_id": f"actor-{actor.name}",
                    "actor_name": actor.name,
                    "money": actor.money,
                    "reserved_money": actor.reserved_money,
                    "inventory_json": json.dumps(inventory_dict),
                    "planet_name": actor.planet.name if actor.planet else "None",
                }
            )

            # Actor drives
            for drive in actor.drives:
                self.writers["actor_drives"].write_row(
                    {
                        "simulation_id": self.simulation_id,
                        "turn": turn,
                        "actor_id": f"actor-{actor.name}",
                        "drive_name": drive.metrics.get_name(),
                        "health": drive.metrics.health,
                        "debt": drive.metrics.debt,
                        "buffer": drive.metrics.buffer,
                        "urgency": drive.metrics.urgency,
                    }
                )

        # Export market data for all planets
        for planet in simulation.planets:
            market = planet.market

            # Market transactions: single pass over this turn's suffix of the
            # history, which also yields per-commodity volume for snapshots.
            turn_transactions = transactions_for_turn(market, turn)
            for tx in turn_transactions:
                self.writers["market_transactions"].write_row(
                    {
                        "simulation_id": self.simulation_id,
                        "turn": turn,
                        "planet_name": planet.name,
                        "commodity_id": tx.commodity_type.id,
                        "buyer_id": f"actor-{tx.buyer.name}",
                        "buyer_name": tx.buyer.name,
                        "seller_id": f"actor-{tx.seller.name}",
                        "seller_name": tx.seller.name,
                        "quantity": tx.quantity,
                        "price": tx.price,
                        "total_amount": tx.quantity * tx.price,
                    }
                )

            turn_volumes = volume_by_commodity(turn_transactions)

            # Market snapshots (aggregated state)
            for commodity in simulation.commodity_registry.all_commodities():
                turn_volume = turn_volumes.get(commodity, 0)

                # Get bid/ask spread
                best_bid, best_ask = market.get_bid_ask_spread(commodity)
                best_bid = best_bid or 0
                best_ask = best_ask or 0

                # Count orders (skipping lazily-cancelled ones still resting
                # in the books between compactions)
                buy_orders = [
                    o for o in market.buy_orders.get(commodity, []) if not o.cancelled
                ]
                sell_orders = [
                    o for o in market.sell_orders.get(commodity, []) if not o.cancelled
                ]

                self.writers["market_snapshots"].write_row(
                    {
                        "simulation_id": self.simulation_id,
                        "turn": turn,
                        "planet_name": planet.name,
                        "commodity_id": commodity.id,
                        "avg_price": float(market.get_avg_price(commodity)),
                        "volume": turn_volume,
                        "num_buy_orders": len(buy_orders),
                        "num_sell_orders": len(sell_orders),
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "scarcity_pressure": float(
                            market.scarcity_pressure_for(commodity)
                        ),
                    }
                )

    def finalize(self) -> None:
        """Close all writers and write final metadata."""
        # Flush and close all writers
        for writer in self.writers.values():
            writer.close()

        # Write metadata file (simple JSON)
        metadata = {
            "simulation_id": self.simulation_id,
            "start_time": self.start_time.isoformat(),
            "end_time": datetime.now().isoformat(),
        }

        metadata_path = self.output_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

    def _export_planet_attributes(self, simulation: "Simulation") -> None:
        """Export planet attributes to a JSON file.

        Args:
            simulation: Simulation instance with planet attributes
        """
        planet_data = {}
        for planet in simulation.planets:
            planet_data[planet.name] = planet.attributes.to_dict()

        attrs_path = self.output_dir / "planet_attributes.json"
        with open(attrs_path, "w") as f:
            json.dump(planet_data, f, indent=2)
