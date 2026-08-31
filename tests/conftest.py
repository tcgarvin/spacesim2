"""Shared test fixtures and utilities."""

import pytest

from .helpers import _get_mock_brain, _get_mock_sim


@pytest.fixture
def mock_sim():
    """Create a mock simulation for testing."""
    return _get_mock_sim()


@pytest.fixture
def mock_brain():
    """Mock actor brain"""
    return _get_mock_brain()
