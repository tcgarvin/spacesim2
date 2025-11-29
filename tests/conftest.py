"""Shared test fixtures and utilities."""

import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest
from .helpers import _get_mock_sim, _get_mock_brain


@pytest.fixture
def mock_sim():
    """Create a mock simulation for testing."""
    return _get_mock_sim()


@pytest.fixture
def mock_brain():
    """Mock actor brain"""
    return _get_mock_brain()


@pytest.fixture
def marimo_notebook_runner():
    """
    Pytest fixture for running marimo notebooks headlessly.

    Returns a function that executes marimo notebooks via `marimo export html`
    and captures output for validation.

    Example usage:
        def test_analysis_notebook(marimo_notebook_runner, sample_run_data):
            returncode, stdout, stderr = marimo_notebook_runner(
                Path('notebooks/analysis_template.py'),
                env={'SPACESIM_RUN_PATH': str(sample_run_data)}
            )
            assert returncode == 0, f"Notebook failed: {stderr}"
    """

    def run_notebook(
        notebook_path: Path, env: Optional[Dict[str, str]] = None
    ) -> Tuple[int, str, str]:
        """
        Run a marimo notebook headlessly via export.

        Args:
            notebook_path: Path to the marimo notebook (.py file)
            env: Optional environment variables to set

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        result = subprocess.run(
            ["marimo", "export", "html", str(notebook_path), "-o", "/tmp/test.html"],
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr

    return run_notebook