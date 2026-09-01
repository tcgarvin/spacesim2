from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry


@dataclass
class ResourceAttribute:
    """Configuration for how planet resource availability affects a process.

    Used by gathering processes to specify which planet attribute affects
    the process and how (success probability vs output quantity).
    """

    commodity: str  # The commodity ID whose availability affects this process
    effect: str  # "success" or "output"

    def __post_init__(self) -> None:
        """Validate effect type."""
        valid_effects = ("success", "output")
        if self.effect not in valid_effects:
            raise ValueError(
                f"effect must be one of {valid_effects}, got {self.effect!r}"
            )


@dataclass
class ProcessDefinition:
    """Definition of a production process."""

    id: str
    name: str
    inputs: Dict[CommodityDefinition, int]  # CommodityDefinition -> quantity
    outputs: Dict[CommodityDefinition, int]  # CommodityDefinition -> quantity
    tools_required: List[CommodityDefinition]  # List of CommodityDefinition for tools
    facilities_required: List[
        CommodityDefinition
    ]  # List of CommodityDefinition for facilities
    labor: int
    description: str
    # Skills that are relevant to this process
    relevant_skills: List[str] = field(default_factory=list)
    # Optional resource attribute configuration for gathering processes
    resource_attribute: Optional[ResourceAttribute] = None
    # Precomputed, read-only flattenings of the fields above, built once at
    # construction for hot scan loops (definitions are immutable after
    # registry load, so these can never go stale):
    # inputs/outputs as (commodity, quantity) tuples — avoids a fresh
    # dict.items() view per process per scan.
    inputs_items: Tuple[Tuple[CommodityDefinition, int], ...] = field(
        init=False, repr=False
    )
    outputs_items: Tuple[Tuple[CommodityDefinition, int], ...] = field(
        init=False, repr=False
    )
    # Everything Actor.can_execute checks, in its exact order: inputs at
    # their quantities, then tools and facilities at quantity 1.
    requirements: Tuple[Tuple[CommodityDefinition, int], ...] = field(
        init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.inputs_items = tuple(self.inputs.items())
        self.outputs_items = tuple(self.outputs.items())
        self.requirements = (
            self.inputs_items
            + tuple((tool, 1) for tool in self.tools_required)
            + tuple((facility, 1) for facility in self.facilities_required)
        )

    def __str__(self) -> str:
        return self.name


class ProcessRegistry:
    """Registry that loads and manages process definitions."""

    def __init__(self, commodity_registry: CommodityRegistry):
        self._processes: Dict[str, ProcessDefinition] = {}
        self._commodity_registry = commodity_registry
        # Lazily built caches. The registry is populated during setup and
        # immutable afterward; both caches are dropped whenever a load adds
        # processes, and rebuilt on next access. Returned lists are shared —
        # callers must treat them as read-only.
        self._all_cache: Optional[List[ProcessDefinition]] = None
        self._producers_index: Optional[Dict[str, List[ProcessDefinition]]] = None

    def load_from_file(self, filepath: str | Path) -> None:
        """Load process definitions from a YAML file."""
        try:
            with open(filepath, "r") as f:
                processes_data = yaml.safe_load(f)

            for process_data in processes_data:
                # Convert string commodity IDs to CommodityDefinition objects
                inputs = {}
                for commodity_id, quantity in process_data["inputs"].items():
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        inputs[commodity] = quantity
                    else:
                        # Skip inputs with unknown commodities
                        print(
                            f"Warning: Skipping unknown commodity ID '{commodity_id}' in process inputs"
                        )

                outputs = {}
                for commodity_id, quantity in process_data["outputs"].items():
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        outputs[commodity] = quantity
                    else:
                        # Skip outputs with unknown commodities
                        print(
                            f"Warning: Skipping unknown commodity ID '{commodity_id}' in process outputs"
                        )

                tools_required = []
                for commodity_id in process_data["tools_required"]:
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        tools_required.append(commodity)
                    else:
                        # Skip unknown tools
                        print(
                            f"Warning: Skipping unknown commodity ID '{commodity_id}' in process tools required"
                        )

                facilities_required = []
                for commodity_id in process_data["facilities_required"]:
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        facilities_required.append(commodity)
                    else:
                        # Skip unknown facilities
                        print(
                            f"Warning: Skipping unknown commodity ID '{commodity_id}' in process facilities required"
                        )

                # Get relevant skills with default empty list if not present
                relevant_skills = process_data.get("relevant_skills", [])

                # Parse resource_attribute if present
                resource_attribute = None
                if "resource_attribute" in process_data:
                    ra_data = process_data["resource_attribute"]
                    resource_attribute = ResourceAttribute(
                        commodity=ra_data["commodity"],
                        effect=ra_data["effect"],
                    )

                process_def = ProcessDefinition(
                    id=process_data["id"],
                    name=process_data["name"],
                    inputs=inputs,
                    outputs=outputs,
                    tools_required=tools_required,
                    facilities_required=facilities_required,
                    labor=process_data["labor"],
                    description=process_data["description"],
                    relevant_skills=relevant_skills,
                    resource_attribute=resource_attribute,
                )
                self._processes[process_def.id] = process_def
            self._all_cache = None
            self._producers_index = None
        except Exception as e:
            print(f"Error loading processes from {filepath}: {e}")

    def get_process(self, process_id: str) -> Optional[ProcessDefinition]:
        """Get a process definition by ID."""
        return self._processes.get(process_id)

    def all_processes(self) -> List[ProcessDefinition]:
        """Get all process definitions.

        Returns a cached list (this is called on hot decision paths every
        turn). Callers must treat the returned list as read-only.
        """
        if self._all_cache is None:
            self._all_cache = list(self._processes.values())
        return self._all_cache

    def get_processes_producing(
        self, commodity: CommodityDefinition
    ) -> List[ProcessDefinition]:
        """Get all processes that produce a specific commodity.

        Backed by a commodity-id -> producers index built once per registry
        load, so lookups are O(1) instead of a full registry scan. The
        returned list is shared with the index; callers must treat it as
        read-only.

        Args:
            commodity: A CommodityDefinition object
        """
        if self._producers_index is None:
            index: Dict[str, List[ProcessDefinition]] = {}
            for process in self._processes.values():
                for output in process.outputs:
                    index.setdefault(output.id, []).append(process)
            self._producers_index = index
        return self._producers_index.get(commodity.id, [])
