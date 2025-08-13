"""Shared test fixtures and utilities."""

import pytest
from spacesim2.core.commodity import CommodityRegistry


@pytest.fixture
def mock_sim():
    """Create a mock simulation for testing."""
    return type('MockSimulation', (object,), {
        'commodity_registry': CommodityRegistry()
    })()