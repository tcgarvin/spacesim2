//! Native backend for the spacesim2 recipe-evaluation kernel.
//!
//! Mirrors `spacesim2/core/kernel/backend_py.py` operation-for-operation:
//! identical iteration order, identical f64 association order for every sum
//! and product, first-wins strict-improvement tie-breaking, the same
//! `None`/`inf` failure modes, and the same string-keyed imputation memo
//! semantics (only "make"-branch results are memoized; the buy branch reads
//! live quotes every call). Any semantic change must land in `backend_py`
//! first — that file is the reference this one is held to by
//! `tests/test_kernel_parity.py`.
//!
//! The module declares free-threaded support (`gil_used = false`): it holds
//! no global state, uses no RNG, and never calls back into Python during
//! compute. All classes are frozen plain data, constructed once per
//! Python-side struct lifetime by `backend_native.py` and cached on the
//! originating dataclass, so per-call marshalling is limited to scalars.

use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashSet;

/// Setup-time flattening of the commodity/process registries.
/// Built once per `EconomyTable` (i.e. once per registry pair per run).
#[pyclass(frozen, module = "spacesim2_kernel")]
struct KernelTable {
    commodity_ids: Vec<String>,
    proc_inputs: Vec<Vec<(usize, i64)>>,
    proc_outputs: Vec<Vec<(usize, i64)>>,
    proc_tools: Vec<Vec<usize>>,
    proc_facilities: Vec<Vec<usize>>,
    proc_skills: Vec<Vec<usize>>,
    proc_resource_attr: Vec<i64>,
    producers_of: Vec<Vec<(usize, i64)>>,
    facility_build_proc: Vec<i64>,
    government_wage: i64,
    tool_lifespan: i64,
    max_impute_depth: i64,
    colonist_profit_floor: f64,
    num_attr_slots: usize,
    num_skills: usize,
}

fn check_index(name: &str, idx: usize, len: usize) -> PyResult<()> {
    if idx >= len {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "{name} index {idx} out of range (len {len})"
        )));
    }
    Ok(())
}

#[pymethods]
impl KernelTable {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        commodity_ids: Vec<String>,
        proc_inputs: Vec<Vec<(usize, i64)>>,
        proc_outputs: Vec<Vec<(usize, i64)>>,
        proc_tools: Vec<Vec<usize>>,
        proc_facilities: Vec<Vec<usize>>,
        proc_skills: Vec<Vec<usize>>,
        proc_resource_attr: Vec<i64>,
        producers_of: Vec<Vec<(usize, i64)>>,
        facility_build_proc: Vec<i64>,
        government_wage: i64,
        tool_lifespan: i64,
        max_impute_depth: i64,
        colonist_profit_floor: f64,
    ) -> PyResult<Self> {
        let c = commodity_ids.len();
        let p = proc_inputs.len();
        for (field, len) in [
            ("proc_outputs", proc_outputs.len()),
            ("proc_tools", proc_tools.len()),
            ("proc_facilities", proc_facilities.len()),
            ("proc_skills", proc_skills.len()),
            ("proc_resource_attr", proc_resource_attr.len()),
        ] {
            if len != p {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "{field} length {len} != process count {p}"
                )));
            }
        }
        if producers_of.len() != c || facility_build_proc.len() != c {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "producers_of/facility_build_proc length != commodity count",
            ));
        }
        for edges in proc_inputs.iter().chain(proc_outputs.iter()) {
            for &(cidx, _) in edges {
                check_index("commodity", cidx, c)?;
            }
        }
        for owned in proc_tools.iter().chain(proc_facilities.iter()) {
            for &cidx in owned {
                check_index("commodity", cidx, c)?;
            }
        }
        for edges in &producers_of {
            for &(pidx, _) in edges {
                check_index("process", pidx, p)?;
            }
        }
        for &pidx in &facility_build_proc {
            if pidx >= 0 {
                check_index("process", pidx as usize, p)?;
            }
        }
        let num_attr_slots = proc_resource_attr
            .iter()
            .filter(|&&slot| slot >= 0)
            .map(|&slot| slot as usize + 1)
            .max()
            .unwrap_or(0);
        let num_skills = proc_skills
            .iter()
            .flatten()
            .map(|&s| s + 1)
            .max()
            .unwrap_or(0);
        Ok(KernelTable {
            commodity_ids,
            proc_inputs,
            proc_outputs,
            proc_tools,
            proc_facilities,
            proc_skills,
            proc_resource_attr,
            producers_of,
            facility_build_proc,
            government_wage,
            tool_lifespan,
            max_impute_depth,
            colonist_profit_floor,
            num_attr_slots,
            num_skills,
        })
    }
}

/// Per-(market, turn) constant state: avg price / price signal / planet
/// resource availability. Built once per planet-turn.
#[pyclass(frozen, module = "spacesim2_kernel")]
struct KernelSnapshot {
    avg_price: Vec<i64>,
    has_signal: Vec<bool>,
    attr_avail: Vec<f64>,
}

#[pymethods]
impl KernelSnapshot {
    #[new]
    fn new(avg_price: Vec<i64>, has_signal: Vec<bool>, attr_avail: Vec<f64>) -> Self {
        KernelSnapshot {
            avg_price,
            has_signal,
            attr_avail,
        }
    }
}

/// Live top-of-book vectors; `None` = no resting order on that side.
/// Built once per actor-turn (same lifetime as `BrainCache.kernel_quotes`).
#[pyclass(frozen, module = "spacesim2_kernel")]
struct KernelQuotes {
    bid: Vec<Option<i64>>,
    ask: Vec<Option<i64>>,
}

#[pymethods]
impl KernelQuotes {
    #[new]
    fn new(bid: Vec<Option<i64>>, ask: Vec<Option<i64>>) -> Self {
        KernelQuotes { bid, ask }
    }
}

/// One actor's kernel closure: skills + available inventory + horizon.
/// Built once per `ActorPack` (invalidated with the BrainCache actor group).
#[pyclass(frozen, module = "spacesim2_kernel")]
struct KernelPack {
    skills: Vec<f64>,
    inventory_available: Vec<i64>,
    amortization_horizon: i64,
}

#[pymethods]
impl KernelPack {
    #[new]
    fn new(skills: Vec<f64>, inventory_available: Vec<i64>, amortization_horizon: i64) -> Self {
        KernelPack {
            skills,
            inventory_available,
            amortization_horizon,
        }
    }
}

/// Validate that snapshot/quotes/pack vectors cover the table's index space,
/// so the compute loops below can index without bounds surprises.
fn check_shapes(
    table: &KernelTable,
    snap: &KernelSnapshot,
    quotes: &KernelQuotes,
    pack: &KernelPack,
) -> PyResult<()> {
    let c = table.commodity_ids.len();
    if snap.avg_price.len() != c
        || snap.has_signal.len() != c
        || quotes.bid.len() != c
        || quotes.ask.len() != c
        || pack.inventory_available.len() != c
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "snapshot/quotes/pack commodity vectors do not match table size",
        ));
    }
    if snap.attr_avail.len() < table.num_attr_slots {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "snapshot attr_avail shorter than table attribute slots",
        ));
    }
    if pack.skills.len() < table.num_skills {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "pack skills shorter than table skill slots",
        ));
    }
    Ok(())
}

/// Expected output per turn of labor for a mean combined skill rating.
/// Exact mirror of `backend_py.expected_skill_factor`'s non-empty branch:
/// ratings below 1.0 fail proportionally; above 1.0 sometimes double the run.
fn skill_factor_from_mean(rating: f64) -> f64 {
    let success_probability = if rating < 1.0 { rating } else { 1.0 };
    let excess = if rating - 1.0 > 0.0 { rating - 1.0 } else { 0.0 };
    let expected_multiplier = 1.0 + excess * 0.5;
    success_probability * expected_multiplier
}

/// An empty ratings list means "no relevant skills": always succeeds (1.0).
fn skill_factor_from_ratings(ratings: &[f64]) -> f64 {
    if ratings.is_empty() {
        return 1.0;
    }
    let mut sum = 0.0f64;
    for &r in ratings {
        sum += r;
    }
    skill_factor_from_mean(sum / ratings.len() as f64)
}

fn process_skill_factor(table: &KernelTable, pack: &KernelPack, pidx: usize) -> f64 {
    let slots = &table.proc_skills[pidx];
    if slots.is_empty() {
        return 1.0;
    }
    let mut sum = 0.0f64;
    for &s in slots {
        sum += pack.skills[s];
    }
    skill_factor_from_mean(sum / slots.len() as f64)
}

fn process_yield_modifier(table: &KernelTable, snap: &KernelSnapshot, pidx: usize) -> f64 {
    let slot = table.proc_resource_attr[pidx];
    if slot >= 0 {
        snap.attr_avail[slot as usize]
    } else {
        1.0
    }
}

fn can_execute(table: &KernelTable, inv: &[i64], pidx: usize) -> bool {
    for &(cidx, qty) in &table.proc_inputs[pidx] {
        if inv[cidx] < qty {
            return false;
        }
    }
    for &cidx in &table.proc_tools[pidx] {
        if inv[cidx] < 1 {
            return false;
        }
    }
    for &cidx in &table.proc_facilities[pidx] {
        if inv[cidx] < 1 {
            return false;
        }
    }
    true
}

/// ask-else-avg pricing (input side). `price * qty` is exact in i64 first,
/// like Python's int arithmetic, then converted — identical f64 values.
#[inline]
fn ask_else_avg(quotes: &KernelQuotes, snap: &KernelSnapshot, cidx: usize) -> i64 {
    match quotes.ask[cidx] {
        Some(a) => a,
        None => snap.avg_price[cidx],
    }
}

fn best_process_scan_impl(
    table: &KernelTable,
    snap: &KernelSnapshot,
    quotes: &KernelQuotes,
    pack: &KernelPack,
) -> (i64, f64) {
    let inv = &pack.inventory_available;
    let mut best_process: i64 = -1;
    let mut best_discounted_profit = table.colonist_profit_floor;
    let mut best_raw_profit = 0.0f64;
    for p in 0..table.proc_inputs.len() {
        let mut input_cost = 0.0f64;
        for &(cidx, qty) in &table.proc_inputs[p] {
            input_cost += (ask_else_avg(quotes, snap, cidx) * qty) as f64;
        }
        let mut output_value = 0.0f64;
        for &(cidx, qty) in &table.proc_outputs[p] {
            let price = match quotes.bid[cidx] {
                Some(b) => b,
                None => snap.avg_price[cidx],
            };
            output_value += (price * qty) as f64;
        }
        let skill_factor = process_skill_factor(table, pack, p);
        let yield_modifier = process_yield_modifier(table, snap, p);
        let expected_value = output_value * yield_modifier * skill_factor;
        let discounted_profit = expected_value - input_cost;
        if discounted_profit > best_discounted_profit && can_execute(table, inv, p) {
            best_process = p as i64;
            best_discounted_profit = discounted_profit;
            best_raw_profit = output_value - input_cost;
        }
    }
    (best_process, best_raw_profit)
}

fn replacement_cost_impl(
    table: &KernelTable,
    snap: &KernelSnapshot,
    quotes: &KernelQuotes,
    pack: &KernelPack,
    cidx: usize,
) -> Option<f64> {
    let inv = &pack.inventory_available;
    let mut best: Option<f64> = None;
    for &(p, out_qty) in &table.producers_of[cidx] {
        if out_qty <= 0 {
            continue;
        }
        if table.proc_facilities[p].iter().any(|&f| inv[f] < 1) {
            continue;
        }
        let mut input_cost = 0.0f64;
        for &(in_cidx, qty) in &table.proc_inputs[p] {
            input_cost += (ask_else_avg(quotes, snap, in_cidx) * qty) as f64;
        }
        for &tool in &table.proc_tools[p] {
            if inv[tool] >= 1 {
                continue;
            }
            let price = ask_else_avg(quotes, snap, tool);
            input_cost += price as f64 / table.tool_lifespan as f64;
        }
        let skill_factor = process_skill_factor(table, pack, p);
        let yield_modifier = process_yield_modifier(table, snap, p);
        let expected_out = out_qty as f64 * yield_modifier;
        if expected_out <= 0.0 {
            continue;
        }
        // Inputs are only consumed on success and scale with the output
        // multiplier, so per-unit input cost is independent of skill;
        // labor, by contrast, is spent on failed turns too.
        let per_unit =
            input_cost / expected_out + table.government_wage as f64 / (expected_out * skill_factor);
        if best.is_none_or(|b| per_unit < b) {
            best = Some(per_unit);
        }
    }
    best
}

/// Imputation working state for one entry-point call tree. `visiting` and
/// `memo` are dense per-commodity mirrors of the Python frozenset/dict.
struct ImputeState {
    visiting: Vec<bool>,
    memo: Vec<Option<f64>>,
}

fn imputed_unit_cost_impl(
    table: &KernelTable,
    snap: &KernelSnapshot,
    quotes: &KernelQuotes,
    pack: &KernelPack,
    state: &mut ImputeState,
    cidx: usize,
    depth: i64,
) -> f64 {
    // 1. Buy it: a live ask is the truest cost; fall back to last-traded avg,
    //    but only when a real trade set it (has_signal gates the fabricated
    //    default of 10).
    if let Some(ask) = quotes.ask[cidx] {
        return ask as f64;
    }
    if snap.has_signal[cidx] {
        let avg = snap.avg_price[cidx];
        if avg > 0 {
            return avg as f64;
        }
    }
    if let Some(value) = state.memo[cidx] {
        return value;
    }
    if depth >= table.max_impute_depth || state.visiting[cidx] {
        return f64::INFINITY; // depth bound or production cycle -> can't value
    }

    // 2. Make it: cheapest producing recipe, costed recursively.
    state.visiting[cidx] = true;
    let mut best = f64::INFINITY;
    for &(pidx, out_qty) in &table.producers_of[cidx] {
        if out_qty <= 0 {
            continue;
        }
        let attribute_modifier = process_yield_modifier(table, snap, pidx);
        if attribute_modifier <= 0.0 {
            continue; // resource absent here -> can't make it locally
        }
        let recipe_cost =
            impute_recipe_cost_impl(table, snap, quotes, pack, state, pidx, depth);
        if recipe_cost.is_infinite() {
            continue;
        }
        let candidate = recipe_cost / (out_qty as f64 * attribute_modifier);
        if candidate < best {
            best = candidate;
        }
    }
    state.visiting[cidx] = false;

    if !best.is_infinite() {
        state.memo[cidx] = Some(best);
    }
    best
}

fn impute_recipe_cost_impl(
    table: &KernelTable,
    snap: &KernelSnapshot,
    quotes: &KernelQuotes,
    pack: &KernelPack,
    state: &mut ImputeState,
    pidx: usize,
    depth: i64,
) -> f64 {
    let inv = &pack.inventory_available;
    let mut total = table.government_wage as f64;

    for &(cidx, quantity) in &table.proc_inputs[pidx] {
        let unit = imputed_unit_cost_impl(table, snap, quotes, pack, state, cidx, depth + 1);
        if unit.is_infinite() {
            return f64::INFINITY;
        }
        total += unit * quantity as f64;
    }

    // Tools the actor lacks must be acquired; amortize over their lifespan.
    for &tool in &table.proc_tools[pidx] {
        if inv[tool] >= 1 {
            continue;
        }
        let unit = imputed_unit_cost_impl(table, snap, quotes, pack, state, tool, depth + 1);
        if unit.is_infinite() {
            return f64::INFINITY;
        }
        total += unit / table.tool_lifespan as f64;
    }

    // Facilities the actor lacks are a lump-sum build cost amortized over
    // this actor's (risk-appetite-dependent) expected usage horizon.
    for &facility in &table.proc_facilities[pidx] {
        if inv[facility] >= 1 {
            continue;
        }
        let build_pidx = table.facility_build_proc[facility];
        if build_pidx < 0 {
            return f64::INFINITY;
        }
        let build_cost = impute_recipe_cost_impl(
            table,
            snap,
            quotes,
            pack,
            state,
            build_pidx as usize,
            depth + 1,
        );
        if build_cost.is_infinite() {
            return f64::INFINITY;
        }
        total += build_cost / pack.amortization_horizon as f64;
    }

    total
}

/// Build dense imputation state from the Python-visible frozenset/dict, and
/// write newly-memoized entries back afterwards (`sync_memo_back`). Keys that
/// are not table commodities are ignored on read and never touched on write,
/// matching the string-keyed legacy memo exactly.
fn load_impute_state(
    table: &KernelTable,
    visiting: &HashSet<String>,
    memo: &Bound<'_, PyDict>,
) -> PyResult<ImputeState> {
    let c = table.commodity_ids.len();
    let mut state = ImputeState {
        visiting: vec![false; c],
        memo: vec![None; c],
    };
    for (idx, cid) in table.commodity_ids.iter().enumerate() {
        if visiting.contains(cid) {
            state.visiting[idx] = true;
        }
        if let Some(value) = memo.get_item(cid)? {
            state.memo[idx] = Some(value.extract::<f64>()?);
        }
    }
    Ok(state)
}

fn sync_memo_back(
    table: &KernelTable,
    state: &ImputeState,
    memo: &Bound<'_, PyDict>,
) -> PyResult<()> {
    for (idx, value) in state.memo.iter().enumerate() {
        if let Some(v) = value {
            memo.set_item(&table.commodity_ids[idx], *v)?;
        }
    }
    Ok(())
}

#[pyfunction]
fn expected_skill_factor(ratings: Vec<f64>) -> f64 {
    skill_factor_from_ratings(&ratings)
}

#[pyfunction]
fn best_process_scan(
    table: Bound<'_, KernelTable>,
    snapshot: Bound<'_, KernelSnapshot>,
    quotes: Bound<'_, KernelQuotes>,
    pack: Bound<'_, KernelPack>,
) -> PyResult<(i64, f64)> {
    let (table, snap, quotes, pack) = (table.get(), snapshot.get(), quotes.get(), pack.get());
    check_shapes(table, snap, quotes, pack)?;
    Ok(best_process_scan_impl(table, snap, quotes, pack))
}

#[pyfunction]
fn replacement_cost(
    table: Bound<'_, KernelTable>,
    snapshot: Bound<'_, KernelSnapshot>,
    quotes: Bound<'_, KernelQuotes>,
    pack: Bound<'_, KernelPack>,
    cidx: usize,
) -> PyResult<Option<f64>> {
    let (table, snap, quotes, pack) = (table.get(), snapshot.get(), quotes.get(), pack.get());
    check_shapes(table, snap, quotes, pack)?;
    check_index("commodity", cidx, table.commodity_ids.len())?;
    Ok(replacement_cost_impl(table, snap, quotes, pack, cidx))
}

/// One-shot evaluation used by `backend_native.evaluate_actor`; returns
/// (best_process, best_raw_profit, replacement_cost[C], can_execute[P],
/// skill_factor[P], yield_modifier[P]).
#[pyfunction]
#[allow(clippy::type_complexity)]
fn evaluate_actor(
    table: Bound<'_, KernelTable>,
    snapshot: Bound<'_, KernelSnapshot>,
    quotes: Bound<'_, KernelQuotes>,
    pack: Bound<'_, KernelPack>,
) -> PyResult<(
    i64,
    f64,
    Vec<Option<f64>>,
    Vec<bool>,
    Vec<f64>,
    Vec<f64>,
)> {
    let (table, snap, quotes, pack) = (table.get(), snapshot.get(), quotes.get(), pack.get());
    check_shapes(table, snap, quotes, pack)?;
    let num_processes = table.proc_inputs.len();
    let num_commodities = table.commodity_ids.len();
    let mut skill_factor = Vec::with_capacity(num_processes);
    let mut yield_modifier = Vec::with_capacity(num_processes);
    let mut can_exec = Vec::with_capacity(num_processes);
    for p in 0..num_processes {
        skill_factor.push(process_skill_factor(table, pack, p));
        yield_modifier.push(process_yield_modifier(table, snap, p));
        can_exec.push(can_execute(table, &pack.inventory_available, p));
    }
    let (best_process, best_raw_profit) = best_process_scan_impl(table, snap, quotes, pack);
    let replacement: Vec<Option<f64>> = (0..num_commodities)
        .map(|cidx| replacement_cost_impl(table, snap, quotes, pack, cidx))
        .collect();
    Ok((
        best_process,
        best_raw_profit,
        replacement,
        can_exec,
        skill_factor,
        yield_modifier,
    ))
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn imputed_unit_cost(
    table: Bound<'_, KernelTable>,
    snapshot: Bound<'_, KernelSnapshot>,
    quotes: Bound<'_, KernelQuotes>,
    pack: Bound<'_, KernelPack>,
    cidx: usize,
    depth: i64,
    visiting: HashSet<String>,
    memo: Bound<'_, PyDict>,
) -> PyResult<f64> {
    let (table_ref, snap, quotes_ref, pack_ref) =
        (table.get(), snapshot.get(), quotes.get(), pack.get());
    check_shapes(table_ref, snap, quotes_ref, pack_ref)?;
    check_index("commodity", cidx, table_ref.commodity_ids.len())?;
    let mut state = load_impute_state(table_ref, &visiting, &memo)?;
    let result = imputed_unit_cost_impl(
        table_ref, snap, quotes_ref, pack_ref, &mut state, cidx, depth,
    );
    sync_memo_back(table_ref, &state, &memo)?;
    Ok(result)
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn impute_recipe_cost(
    table: Bound<'_, KernelTable>,
    snapshot: Bound<'_, KernelSnapshot>,
    quotes: Bound<'_, KernelQuotes>,
    pack: Bound<'_, KernelPack>,
    pidx: usize,
    depth: i64,
    visiting: HashSet<String>,
    memo: Bound<'_, PyDict>,
) -> PyResult<f64> {
    let (table_ref, snap, quotes_ref, pack_ref) =
        (table.get(), snapshot.get(), quotes.get(), pack.get());
    check_shapes(table_ref, snap, quotes_ref, pack_ref)?;
    check_index("process", pidx, table_ref.proc_inputs.len())?;
    let mut state = load_impute_state(table_ref, &visiting, &memo)?;
    let result = impute_recipe_cost_impl(
        table_ref, snap, quotes_ref, pack_ref, &mut state, pidx, depth,
    );
    sync_memo_back(table_ref, &state, &memo)?;
    Ok(result)
}

#[pymodule(gil_used = false)]
fn spacesim2_kernel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<KernelTable>()?;
    m.add_class::<KernelSnapshot>()?;
    m.add_class::<KernelQuotes>()?;
    m.add_class::<KernelPack>()?;
    m.add_function(wrap_pyfunction!(expected_skill_factor, m)?)?;
    m.add_function(wrap_pyfunction!(best_process_scan, m)?)?;
    m.add_function(wrap_pyfunction!(replacement_cost, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_actor, m)?)?;
    m.add_function(wrap_pyfunction!(imputed_unit_cost, m)?)?;
    m.add_function(wrap_pyfunction!(impute_recipe_cost, m)?)?;
    Ok(())
}
