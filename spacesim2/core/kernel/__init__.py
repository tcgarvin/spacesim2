"""Recipe-evaluation kernel: flattened economy data + pure compute.

Phase 1 of the planned native extraction (see docs/performance.md): the
brains' hot valuation math — best-process scan, replacement cost, make-or-buy
imputation, skill/yield expectation — expressed over plain integer-indexed
data so a native (Rust/PyO3) backend can replace ``backend_py`` behind this
exact module interface.

Backend selection: the native (Rust) backend is preferred when its compiled
extension is importable; the pure-Python backend is the fallback. Override
with ``SPACESIM_KERNEL_BACKEND=python|native|auto`` — ``native`` fails loudly
when the extension is missing instead of silently falling back, which is what
parity and perf comparisons need.
"""

import os
from typing import TYPE_CHECKING

from spacesim2.core.kernel.adapters import (
    build_pack,
    build_quotes,
    get_snapshot,
    get_table,
    try_context,
)
from spacesim2.core.kernel.table import (
    COLONIST_PROFIT_FLOOR,
    DEFAULT_FACILITY_AMORTIZATION_HORIZON,
    FACILITY_BUILD_PROCESSES,
    GOVERNMENT_WAGE,
    MAX_IMPUTE_DEPTH,
    TOOL_EXPECTED_LIFESPAN,
    ActorEval,
    ActorPack,
    EconomyTable,
    PlanetSnapshot,
    Quotes,
    build_economy_table,
)

if TYPE_CHECKING:
    # Type checkers always see the Python backend's signatures; the native
    # backend must match them exactly.
    from spacesim2.core.kernel import backend_py as _backend
else:
    _requested = os.environ.get("SPACESIM_KERNEL_BACKEND", "auto")
    if _requested == "python":
        from spacesim2.core.kernel import backend_py as _backend
    elif _requested == "native":
        # Deliberately no fallback: a missing extension must fail loudly.
        from spacesim2.core.kernel import backend_native as _backend
    elif _requested == "auto":
        try:
            from spacesim2.core.kernel import backend_native as _backend
        except ImportError:
            from spacesim2.core.kernel import backend_py as _backend
    else:
        raise ValueError(
            f"SPACESIM_KERNEL_BACKEND={_requested!r}: expected "
            "'python', 'native', or 'auto'"
        )

best_process_scan = _backend.best_process_scan
evaluate_actor = _backend.evaluate_actor
expected_skill_factor = _backend.expected_skill_factor
imputed_unit_cost = _backend.imputed_unit_cost
impute_recipe_cost = _backend.impute_recipe_cost
replacement_cost = _backend.replacement_cost

__all__ = [
    "COLONIST_PROFIT_FLOOR",
    "DEFAULT_FACILITY_AMORTIZATION_HORIZON",
    "FACILITY_BUILD_PROCESSES",
    "GOVERNMENT_WAGE",
    "MAX_IMPUTE_DEPTH",
    "TOOL_EXPECTED_LIFESPAN",
    "ActorEval",
    "ActorPack",
    "EconomyTable",
    "PlanetSnapshot",
    "Quotes",
    "best_process_scan",
    "build_economy_table",
    "build_pack",
    "build_quotes",
    "evaluate_actor",
    "expected_skill_factor",
    "get_snapshot",
    "get_table",
    "impute_recipe_cost",
    "imputed_unit_cost",
    "replacement_cost",
    "try_context",
]
