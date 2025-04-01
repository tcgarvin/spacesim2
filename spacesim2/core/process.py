from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import yaml

from spacesim2.core.commodity import CommodityRegistry, CommodityDefinition


@dataclass
class ProcessDefinition:
    """Definition of a production process."""
    id: str
    name: str
    inputs: Dict[CommodityDefinition, int]  # CommodityDefinition -> quantity
    outputs: Dict[CommodityDefinition, int]  # CommodityDefinition -> quantity
    tools_required: List[CommodityDefinition]  # List of CommodityDefinition for tools
    facilities_required: List[CommodityDefinition]  # List of CommodityDefinition for facilities
    labor: int
    description: str
    # Skills that are relevant to this process
    relevant_skills: List[str] = field(default_factory=list)
    
    def __str__(self) -> str:
        return self.name


class ProcessRegistry:
    """Registry that loads and manages process definitions."""
    
    def __init__(self, commodity_registry: CommodityRegistry):
        self._processes: Dict[str, ProcessDefinition] = {}
        self._commodity_registry = commodity_registry
        
    def load_from_file(self, filepath: str) -> None:
        """Load process definitions from a YAML file."""
        try:
            with open(filepath, 'r') as f:
                processes_data = yaml.safe_load(f)
                
            for process_data in processes_data:
                # Convert string commodity IDs to CommodityDefinition objects
                inputs = {}
                for commodity_id, quantity in process_data['inputs'].items():
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        inputs[commodity] = quantity
                    else:
                        # Skip inputs with unknown commodities
                        print(f"Warning: Skipping unknown commodity ID '{commodity_id}' in process inputs")
                
                outputs = {}
                for commodity_id, quantity in process_data['outputs'].items():
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        outputs[commodity] = quantity
                    else:
                        # Skip outputs with unknown commodities
                        print(f"Warning: Skipping unknown commodity ID '{commodity_id}' in process outputs")
                
                tools_required = []
                for commodity_id in process_data['tools_required']:
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        tools_required.append(commodity)
                    else:
                        # Skip unknown tools
                        print(f"Warning: Skipping unknown commodity ID '{commodity_id}' in process tools required")
                
                facilities_required = []
                for commodity_id in process_data['facilities_required']:
                    commodity = self._commodity_registry.get_commodity(commodity_id)
                    if commodity:
                        facilities_required.append(commodity)
                    else:
                        # Skip unknown facilities
                        print(f"Warning: Skipping unknown commodity ID '{commodity_id}' in process facilities required")
                
                # Get relevant skills with default empty list if not present
                relevant_skills = process_data.get('relevant_skills', [])
                
                process_def = ProcessDefinition(
                    id=process_data['id'],
                    name=process_data['name'],
                    inputs=inputs,
                    outputs=outputs,
                    tools_required=tools_required,
                    facilities_required=facilities_required,
                    labor=process_data['labor'],
                    description=process_data['description'],
                    relevant_skills=relevant_skills
                )
                self._processes[process_def.id] = process_def
        except Exception as e:
            print(f"Error loading processes from {filepath}: {e}")
    
    def get_process(self, process_id: str) -> Optional[ProcessDefinition]:
        """Get a process definition by ID."""
        return self._processes.get(process_id)
        
    def all_processes(self) -> List[ProcessDefinition]:
        """Get all process definitions."""
        return list(self._processes.values())
        
    def get_processes_producing(self, commodity: CommodityDefinition) -> List[ProcessDefinition]:
        """Get all processes that produce a specific commodity.
        
        Args:
            commodity: A CommodityDefinition object
        """
        return [p for p in self._processes.values() if commodity in p.outputs]
        
    def get_processes_consuming(self, commodity: CommodityDefinition) -> List[ProcessDefinition]:
        """Get all processes that consume a specific commodity.
        
        Args:
            commodity: A CommodityDefinition object
        """
        return [p for p in self._processes.values() if commodity in p.inputs]