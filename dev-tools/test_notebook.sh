#!/bin/bash
# Quick notebook validation script
#
# Usage: ./dev-tools/test_notebook.sh [run_path]
# Example: ./dev-tools/test_notebook.sh data/runs/test_run

set -e

RUN_PATH=${1:-data/runs/test_run}

echo "=== Notebook Validation ==="
echo "Run path: $RUN_PATH"
echo

echo "Step 1: Validating data schema..."
uv run python dev-tools/validate_run_data.py "$RUN_PATH"
echo

echo "Step 2: Exporting notebook to HTML (tests execution)..."
SPACESIM_RUN_PATH="$RUN_PATH" uv run marimo export html notebooks/analysis_template.py -o /tmp/notebook_test.html
echo

echo "✓ Notebook runs successfully!"
echo "  HTML output: /tmp/notebook_test.html"
