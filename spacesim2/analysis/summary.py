"""Compact, population-wide behavioral summary of a simulation.

This is the Tier-0 "smoke" readout for the agent dev loop: a small,
machine-readable dict of macro KPIs computed directly from the live
``Simulation`` object (not the sampled Parquet logs), plus a coarse
PASS/WARN/FAIL verdict against expected ranges.

The goal is token efficiency: an agent runs one command and reads ~20
numbers and a verdict, instead of loading Parquet or a rendered notebook.
For open-ended questions, write a Tier-1 analysis script instead (see the
``sim-evaluation`` skill).
"""

from __future__ import annotations

import statistics
from typing import Dict, List

from spacesim2.core.actor import ActorType
from spacesim2.core.simulation import Simulation

# Verdict thresholds are deliberately *catastrophe floors*, not aspirational
# targets: a healthy run can sit well above them. They flag runs that are
# unambiguously broken regardless of design intent, avoiding alarm fatigue.
#
# Only `food` (the survival need) is thresholded by default. Comfort-tier
# drives (shelter, clothing, health) ramp slowly and their intended
# steady-state level is a design decision — they are *reported* in `drives`
# but not asserted here. Add them once a target steady state is defined.
_DRIVE_HEALTH_THRESHOLDS: Dict[str, tuple[float, float]] = {
    "food": (0.80, 0.50),
}

# Survival commodity whose market must stay alive for the economy to function.
_LIVENESS_COMMODITY = "food"

# A drive instance is counted as "deprived" when its debt exceeds this.
_DEPRIVED_DEBT = 0.80


def compute_summary(sim: Simulation) -> Dict[str, object]:
    """Compute a compact KPI summary from a finished simulation.

    Args:
        sim: The simulation to summarize (after running its turns).

    Returns:
        A JSON-serializable dict of macro KPIs plus a ``verdict`` block.
        Numeric values are rounded for compact, stable output.
    """
    regular_actors = [a for a in sim.actors if a.actor_type == ActorType.REGULAR]

    drives = _summarize_drives(regular_actors)
    prices = _summarize_prices(sim)
    summary: Dict[str, object] = {
        "turns": sim.current_turn,
        "planets": len(sim.planets),
        "regular_actors": len(regular_actors),
        "market_makers": sum(
            1 for a in sim.actors if a.actor_type == ActorType.MARKET_MAKER
        ),
        "ships": len(sim.ships),
        "money": _summarize_money(regular_actors),
        "drives": drives,
        "inventory_totals": _summarize_inventory(sim),
        "prices": prices,
    }
    summary["verdict"] = _build_verdict(drives, prices)
    return summary


def _summarize_money(regular_actors: List) -> Dict[str, float]:
    """Summarize the money distribution across regular actors."""
    if not regular_actors:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    money = [float(a.money) for a in regular_actors]
    return {
        "mean": round(statistics.fmean(money), 1),
        "median": round(statistics.median(money), 1),
        "min": round(min(money), 1),
        "max": round(max(money), 1),
    }


def _summarize_drives(regular_actors: List) -> Dict[str, Dict[str, float]]:
    """Aggregate per-drive metrics across the population.

    Returns a mapping of drive name -> {mean_health, mean_debt, pct_deprived},
    where pct_deprived is the fraction of actors whose debt for that drive
    exceeds the deprivation threshold.
    """
    health: Dict[str, List[float]] = {}
    debt: Dict[str, List[float]] = {}
    deprived: Dict[str, int] = {}

    for actor in regular_actors:
        for drive in actor.drives:
            name = drive.metrics.get_name()
            health.setdefault(name, []).append(drive.metrics.health)
            debt.setdefault(name, []).append(drive.metrics.debt)
            if drive.metrics.debt > _DEPRIVED_DEBT:
                deprived[name] = deprived.get(name, 0) + 1

    result: Dict[str, Dict[str, float]] = {}
    n = len(regular_actors)
    for name in sorted(health):
        result[name] = {
            "mean_health": round(statistics.fmean(health[name]), 3),
            "mean_debt": round(statistics.fmean(debt[name]), 3),
            "pct_deprived": round(deprived.get(name, 0) / n, 3) if n else 0.0,
        }
    return result


def _summarize_inventory(sim: Simulation) -> Dict[str, int]:
    """Sum every commodity held across all actors (population-wide stock)."""
    totals: Dict[str, int] = {}
    for actor in sim.actors:
        for commodity, quantity in actor.inventory.commodities.items():
            totals[commodity.id] = totals.get(commodity.id, 0) + quantity
    return {cid: totals[cid] for cid in sorted(totals)}


def _summarize_prices(sim: Simulation) -> Dict[str, float]:
    """Mean 30-day average price per commodity, averaged across planet markets.

    Commodities with no trading history on any market are omitted (rather
    than reported as a misleading zero).
    """
    per_commodity: Dict[str, List[float]] = {}
    for planet in sim.planets:
        market = planet.market
        for commodity in sim.commodity_registry.all_commodities():
            if market.has_history(commodity):
                price = market.get_30_day_average_price(commodity)
                per_commodity.setdefault(commodity.id, []).append(price)

    return {
        cid: round(statistics.fmean(prices), 1)
        for cid, prices in sorted(per_commodity.items())
    }


def _build_verdict(
    drives: Dict[str, Dict[str, float]], prices: Dict[str, float]
) -> Dict[str, object]:
    """Derive a coarse PASS/WARN/FAIL catastrophe verdict.

    Checks survival-drive health floors and that the survival commodity's
    market is still trading. The overall status is the worst signal. Each
    flag is human-readable so an agent can act on the verdict without
    re-deriving it from the raw numbers.
    """
    flags: List[str] = []
    status = "PASS"

    for name, (warn, fail) in _DRIVE_HEALTH_THRESHOLDS.items():
        if name not in drives:
            continue
        mean_health = drives[name]["mean_health"]
        if mean_health < fail:
            status = "FAIL"
            flags.append(f"{name} health {mean_health:.2f} < {fail:.2f}")
        elif mean_health < warn:
            if status != "FAIL":
                status = "WARN"
            flags.append(f"{name} health {mean_health:.2f} < {warn:.2f}")

    # Market liveness: a frozen survival market is a catastrophic regression.
    if _LIVENESS_COMMODITY not in prices:
        status = "FAIL"
        flags.append(f"no {_LIVENESS_COMMODITY} market activity (dead market)")

    return {"status": status, "flags": flags}
