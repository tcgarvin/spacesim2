# Migration: Actors Moving Between Planets

Status: v1 landed 2026-09-11. Actors leave a planet that serves them badly
for one that promises more, pay a fare, travel at ship speed, and draw a
new land on arrival. v2, where a ship carries the migrant under a passage
contract, is open.

## Why

Poor planets do not import (decision log, 2026-09-08): a wood-poor or
barren planet self-feeds at most of its labor and ships rarely call. Trade
was the only equalizer and it does not reach those planets. Migration is
the other one: people leave.

## The split

Every reason to move lives in the brain. What a move does lives in core.

| Layer | File | Owns |
|-------|------|------|
| Brain | `core/brains/migration.py` | pressure, propensity, intent with hysteresis, destination scoring, liquidation |
| Brain | `core/brains/colonist.py`, `core/brains/industrialist.py` | `decide_migration`, `on_relocated`, investment and sell-sweep guards while leaving |
| Core | `core/migration.py` | `PlanetStats`, the migration phase, fare, transit, `relocate_actor` |
| Core | `core/planet.py` | `remove_actor`, `release_land`, `add_actor_with_land` |

`ActorBrain.decide_migration(actor)` returns a `MigrationRequest`
(destination, max fare) or `NO_MIGRATION`. The default stays put, so a
brain that never thinks about moving needs no code. `ActorBrain.on_relocated`
is the hook for resetting planet-specific brain state after a move.

## Turn order

1. `refresh_planet_stats` at the top of `run_turn`: one `PlanetStats` per
   planet (population, free land count and per-resource pool mean, median
   need debt, median prosperity, median money) over regular residents.
   Cost is 0.4% of a 12-planet turn.
2. Actor phase. `Actor.take_turn` asks land-claiming actors for a decision
   and stores it on `actor.migration_request`. Nothing moves here: the
   threaded phase shards by planet.
3. Ship phase.
4. `run_migration_phase`: arrivals land first, then departures. A departure
   cancels the actor's orders, charges the fare, reserves a land at the
   destination, removes the actor from the origin and from `sim.actors`,
   clears its inventory, and parks it in `sim.migrants_in_transit`.
5. Market matching.

An in-transit actor is in no actor list and does not act, eat, or trade.
`actor.in_transit` is the authoritative flag; `actor.planet` keeps pointing
at the origin until arrival so nothing has to handle a planet-less actor.
The threaded phase's count invariant still holds.

## The brain's decision

Checked once every `MIGRATION_CHECK_INTERVAL` (10) turns per actor, on an
offset derived from the actor's name, so scoring cost is one tenth of an
actor-turn.

**Pressure**, the push, in [0, 1]: the worst need-drive `debt`, plus 0.2
times the prosperity shortfall, plus 0.3 times the largest gap between the
planet mean and the actor's own land. Debt already integrates neglect over
time, which is why there is no separate "sustained hardship" timer.

**Gain**, the pull. A destination scores
`land + wellbeing + 0.2 * prosperity - 0.5 * fare / money`, where land is
the free pool's mean coefficient (what a newcomer will draw), wellbeing is
one minus the residents' median need debt, and the fare is what the actor
would pay. Staying scores the same way with the actor's own land and no
fare. An intent forms only if some destination beats staying by
`MIN_MIGRATION_GAIN` (0.1). This is the load-bearing rule: in the first
hundred turns of a run every actor everywhere has a need debt of 1.0 while
the economy bootstraps, and pressure alone moved most of the population
between planets that were all equally bad.

**Roll.** With pressure at or above `ENTER_THRESHOLD` (0.35), the actor
forms an intent with probability `BASE_LEAVE_RATE * propensity * pressure`
per check. Propensity is a fixed per-brain draw in [0.2, 1.0]. The base
rate 0.094 gives a chronically deprived actor (pressure 0.8, median
propensity) a 50% chance of forming an intent within 150 turns.

**Intent.** Held for `MIN_INTENT_TURNS` (30) before any request. During the
intent the brain stops buying tools, building facilities, and adopting
recipes, and its sell sweep offers everything it holds at keep level 0,
facilities included, except need-drive materials. The waiting period is
where the actor turns stock into fare money. Every later check re-aims the
destination without the fare term, since the actor has already decided to
pay; if nothing clears the gain floor any more, or pressure falls under
`EXIT_THRESHOLD` (0.2), the intent is dropped.

**Request.** Once the intent is old enough and the fare is affordable, the
brain returns the request every turn until core executes it. The request's
`max_fare` is 1.5 times the estimated fare, capped at the actor's money.

**Destination draw** is a softmax over the scores at temperature 0.1, not
an argmax. Pressure rises on many planets at once, and an argmax would send
every wave to one planet and fill its pool.

## Core mechanics

- Fare: `passage_fare(distance)`, 2 credits per lane unit, minimum 20,
  paid to the origin's spaceport operators. With none it is destroyed.
- Transit: `ceil(distance / 20)` turns, the speed ships fly at.
- Land: the destination land is claimed at departure, so migrants in
  flight cannot overshoot a pool. The origin land returns to the origin's
  pool. Leavers are selected for bad draws, so a high-emigration planet's
  free pool degrades, and that is intended.
- Refused requests: destination is the origin, pool empty, fare above
  `max_fare` or above the actor's money. The request is cleared and the
  brain decides again next turn.
- Kept across a move: money, skills, tastes, drives. Lost: inventory,
  facilities, land, orders.
- Pool size: `--lands-per-planet`, default 200 against 100 actors per
  planet. A bare `Planet` still defaults to 100.

## Measuring it

`--summary` has a `migration` block: departures, arrivals, in transit, and
departures per 100 turns per 1000 actors. It is not in the verdict.

`notebooks/migration_probe.py` follows every migrant and a stayer from the
same origin matched on pressure at the departure turn, and compares need
debt, prosperity, and money 100 and 200 turns later. That is the test of
whether moving helps. Run it at 100 planets for a galaxy-scale answer.

## Open

- v2: the request becomes a passage contract a ship brain accepts at the
  spaceport, and the move happens in the ship phase on arrival.
  `MIGRANT_CARGO_UNITS` (10, undecided against 100) is the hold space one
  migrant takes. `relocate_actor` is unchanged by this.
- The fare is a flat distance rate. Ships price fuel by flow; the v2 fare
  should too.
- A migrant with no facility or recipe re-selects on arrival; whether the
  destination's market has room for one more producer is not scored.
- Brain drain: skills travel with the actor, so a poor planet loses its
  skilled residents first. Unmeasured.
