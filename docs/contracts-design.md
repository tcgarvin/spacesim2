# Contracts: Transport Jobs, Passage, and Government Freight

Status: approved 2026-09-11, implementation in progress. The first use is
migration v2 (`docs/migration-design.md`, "Open"); the primitive is meant to
carry later uses without changing shape.

## Why

Migration v1 moves an actor by teleport at ship speed. The fare goes to the
spaceport operators and no ship is involved. Two things are wrong with that:

- Fleet capacity does not bound migration. A wave of leavers moves at once,
  which is the herding the decision log records at 100 planets.
- The fare is a flat distance rate. Everything else a ship carries is priced
  by what the ship could otherwise do with the trip.

A ship should carry the migrant. Once a ship can be paid to carry something
that is not its own cargo, the same mechanism covers other jobs: a
spaceport operator ordering fuel delivered, an industrialist ordering an
input, the government paying for routine freight. That last one is the
baseline the fleet is missing today: a broke ship has no income and a
docked ship on a poor planet has nothing worth exporting.

## The primitive

One data type, `Contract`, in `core/contracts.py`. Core owns what a contract
does. Brains own whether to post one and whether to accept one, the same
split as migration and market orders.

```python
@dataclass
class Contract:
    contract_id: str
    poster: Poster            # an Actor, or GOVERNMENT
    origin: Planet
    destination: Planet
    payload: Payload          # see below
    advance: int              # paid to the carrier when the payload loads
    on_delivery: int          # paid to the carrier on arrival at destination
    posted_turn: int
    expires_turn: int
    status: ContractStatus    # OPEN, ACCEPTED, LOADED, DELIVERED, CANCELLED, EXPIRED
    carrier: Ship | None
```

Payloads, one class each, all with a `hold_units` property:

| Payload | Carries | Hold units | First user |
|---------|---------|------------|------------|
| `PassengerPayload(actor, land)` | a regular actor, with the destination land claimed at load | `MIGRANT_CARGO_UNITS` | migration v2 |
| `ConsignmentPayload(units)` | an abstract lot that exists only inside the contract | `units` | government freight |
| `CargoPayload(commodity, quantity, supplied_by)` | real goods; `supplied_by` is `POSTER` (freight: the poster hands the goods over at load) or `CARRIER` (procurement: the ship sources them and is paid on delivery) | `quantity` | later: operator fuel orders, input orders |

v2 implements the first two. `CargoPayload` is in the design so the type does
not have to change for it, but no brain posts or accepts one yet.

Money. A poster that is an actor reserves `advance + on_delivery` at posting,
the way a bid reserves money, and the reserve is released on cancel or
expiry. The government reserves nothing; its payouts are created, the same
way the government wage is. Every payment goes to the carrier in full. v1's
fare went to the origin's spaceport operators; a port fee to keep that flow
was considered and rejected on 2026-09-11 as unneeded.

Boards. Each planet has a `ContractBoard` holding its open contracts, next to
its market. Ships read every board, as they already read every market, so a
ship two lanes away can plan a trip around a contract. Boards expire
contracts at the top of the turn.

Lifecycle, all in core:

| Step | Who calls it | What happens |
|------|--------------|--------------|
| `board.post(contract)` | migration phase, government refresh | reserve poster money, status OPEN |
| `board.accept(contract, ship)` | ship brain, docked at origin | status ACCEPTED, `ship.contracts` gains it; hold units count against the hold from here |
| `load_contract(ship, contract)` | `Ship.start_journey`, after the fuel check passes | payload boards or is handed over, advance paid, status LOADED |
| `deliver_contract(ship, contract)` | `Ship.update_journey` on arrival at `destination` | payload delivered, `on_delivery` paid, status DELIVERED |
| `release_contract(ship, contract)` | ship brain, or core after `CONTRACT_LOAD_PATIENCE` turns unloaded | back to OPEN on the board, no money moves |
| `strand_contract(ship, contract, planet)` | core, when a loaded ship ends up docked somewhere that is not the destination for `CONTRACT_STRAND_PATIENCE` turns | payload unloaded where the ship is, `on_delivery` refunded to the poster, status CANCELLED |
| `board.cancel(contract)` | poster's brain, before acceptance | reserve released |

A passenger that is stranded draws a land at the stranding planet if the
pool has one, and otherwise stays aboard until the ship next docks at a
planet that does. Stranding should be rare; it is counted.

## Migration v2 on top of this

`MigrationRequest` keeps `destination` and gains `fare_offer`, what the actor
is offering now. `core/migration.py` no longer moves anyone:

1. Actor phase: the brain returns a request, as today.
2. Ship phase: ships accept, load, and deliver. Delivery calls
   `relocate_actor`, which is unchanged.
3. Contract phase, where the migration phase is now: a request with no open
   contract posts one (`advance = fare_offer`, `on_delivery = 0`, expiry
   `PASSAGE_CONTRACT_TTL` turns); a request with an open contract at a
   higher offer re-prices it; `NO_MIGRATION` from an actor with an open
   contract cancels it.
4. Market matching.

The fare is paid in full at boarding, not on delivery, so a passenger can
fund a ship's fuel the way a government job can. The ship's reason to
deliver is that a loaded contract pins its destination, below.

While the contract is open the actor keeps living on the origin planet:
eats, works, sells. The v1 "leaving" mode of the brain (no tools, no
facilities, no recipes, sell everything) stays on. The brain escalates
`fare_offer` from the v1 estimate toward its cap over
`FARE_ESCALATION_TURNS` (proposed 20) while unaccepted, and drops the
intent if the contract expires twice. That gives fare price discovery
without a second market.

The land is claimed at load, not at post, so an open contract holds nothing
at the destination and the no-overshoot guarantee from v1 still holds.

`sim.migrants_in_transit` goes away; a migrant in flight is a
`PassengerPayload` on a ship. The `migration` summary block keeps its
counts and adds median turns from post to load.

## The ship brain

`TraderBrain` today picks a destination three ways: a loaded `TradePlan`, a
hold of cargo worth more elsewhere, or an empty reposition. Contracts join
in two places and change nothing about how those three are judged.

**Riders.** When the brain has settled on a destination for this departure,
`_accept_riders(destination)` walks the local board for OPEN contracts to
that destination, sorts by `(advance + on_delivery) / hold_units`, and
accepts them while they fit the hold left after the plan's cargo and
add-ons. Riders are pure revenue on a trip already paid for, so no margin
test applies. This is the add-on cargo rule applied to contracts.

**Contract-only trips.** When `_find_best_trade_plan` returns nothing
acceptable, `_best_contract_trip()` groups the OPEN contracts on the local
board by destination and values each group as a plan: payments, less the
outbound fuel priced the way `TradePlan.total_fuel_cost` prices it, less
expected maintenance. The best group becomes a `ContractPlan` and takes the
place of a trade plan in the lifecycle. It passes the same
`_fuel_safe_destination` gate and the same cash gate for round-trip fuel,
with one difference: the advance counts as cash for that gate, because it is
paid at load, before the tank is charged. That is what lets a ship with no
money and a dry tank take a government job, buy fuel with the advance, and
leave. A contract-only trip is accepted when it more than covers its fuel
and maintenance, the test a distressed ship already applies to trade plans.

**Pinning.** A ship holding a LOADED contract flies to its destination. In
`decide_travel` this sits where the loaded-plan branch is: if the fuel gate
allows, depart; otherwise stay, and `decide_trade_actions` commits
`_committed_fuel_need` to that leg so the top-up funds it. The cargo-hop and
reposition branches do not run while a loaded contract is aboard. A refuel
stop is still allowed; the passenger stays aboard through it, and the resume
destination is the contract's. If the ship is still docked short of the
destination after `CONTRACT_STRAND_PATIENCE` (proposed 10) turns, core
strands the contract.

**Remote pickup.** `_find_reposition_target` scores candidate origins by the
best plan sourced there. It adds the best contract trip available there,
so a planet with a queue of passengers and nothing to export can still pull
an empty ship in. This is the only part of the design that reaches poor
planets, and it is the part to measure first: v1's whole purpose was
planets ships do not call at.

Everything above lives in `TraderBrain`; nothing in `Ship` decides. `Ship`
gains `contracts`, `free_hold()` (capacity less cargo less accepted
contract units), the load call in `start_journey`, and the deliver call in
`update_journey`.

## Government freight

`core/government.py`, `refresh_government_jobs(sim)`, runs at the top of the
turn with `refresh_planet_stats`. Every planet's board is kept at
`GOVERNMENT_JOBS_PER_PLANET` (proposed 1) open government contracts:

| Field | Value |
|-------|-------|
| payload | `ConsignmentPayload(GOVERNMENT_JOB_UNITS)`, proposed 20 |
| destination | a random planet within `GOVERNMENT_JOB_MAX_HOPS` (proposed 2) lanes |
| advance | `ceil(fuel_required * fuel_reference * (1 + GOVERNMENT_JOB_MARGIN))`, margin proposed 0.25 |
| on_delivery | 0 |
| expiry | `GOVERNMENT_JOB_TTL` turns, proposed 30, then re-rolled |

`fuel_required` is `Ship.calculate_fuel_needed(distance)` at efficiency 1.0
and `fuel_reference` is `Navigator.fuel_value_reference()`, or
`FUEL_BID_FALLBACK_FLOOR` before anything has traded. A taken job is
replaced the next turn, so the supply is one job per planet at a time, not
one per ship.

Sizing. The advance covers one leg's fuel at the typical galaxy price and a
quarter more. A trade plan needs 15% on its purchase cost, which at the
cargo values ships move is several times a leg's fuel, so a job beats a
trade only when there is no trade. Where fuel is spiked locally the advance
does not cover it; the ship should reposition to a station, as it does now.

Money. These payouts are created. At 100 planets, one job per planet, a
mean leg of a few fuel units at a reference near 40, and a fill rate under
one per planet per 30 turns, the ceiling is on the order of a few hundred
credits per planet per 100 turns, against a government wage that already
creates 10 per actor-turn. The summary reports `government_payouts` so the
number is checked rather than assumed.

## What this should change

Before and after, `dev ab --base 619c4a8`, 12 planets and then 100:

| KPI | Expect |
|-----|--------|
| migration departures per 100 turns per 1000 actors | lower than v1; bounded by fleet trips now |
| migrant outcome at +100 turns (`notebooks/migration_probe.py`) | no worse than v1 |
| median turns from post to load | the new number; large on poor planets is the failure to watch for |
| passage contracts expired | near zero, or the pickup logic is not reaching them |
| stranded ships, idle docked turns | down; jobs give idle ships a paid move |
| ships with money below one short round trip | down |
| government payouts per 100 turns | small against total money |
| fleet money at t400 | up by less than the payouts, or jobs are pure subsidy |

## Decisions to make

1. `MIGRANT_CARGO_UNITS`: 10 or 100. At 100 every migrant is a whole trip.
   v1 moved 295 actors in 400 turns at 12 planets with 12 ships; at 100
   units that is 295 passenger-only trips against roughly 0.2 trips a ship
   can fly per turn, so about a third of the fleet's capacity. At 10 a
   passenger is a rider on a trade the ship was making anyway. Proposal: 10.
2. Government payload: abstract consignment, or real goods the government
   buys and sells. Consignment does not touch the goods economy; real goods
   would. Proposal: consignment now; real goods come free with
   `CargoPayload` if wanted later.
3. Fare timing: all at boarding (proposal), or split with delivery. Boarding
   funds fuel for broke ships; the destination pin is what makes delivery
   happen.
4. Port fee to operators: rejected, none.
5. Government job supply and price: one open job per planet, two hops,
   fuel times 1.25. All three are constants and any of them can be an A/B.
6. Remote pickup in `_find_reposition_target`: in v2, or measured first
   without it. Proposal: in v2, since poor planets are the case that
   matters.
