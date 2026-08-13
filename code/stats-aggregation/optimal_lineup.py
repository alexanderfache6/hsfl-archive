"""Computes the highest-scoring legal lineup for one team/week, given that
season's actual roster_settings slot counts (from metadata.json) - not
hardcoded, since slot eligibility (e.g. FLEX = RB/WR only for this league,
confirmed 2026-08-07) can differ season to season. See execution-plan.md
Phase F for the confirmed design.
"""

BENCH_LIKE_SLOTS = {"BENCH", "RESERVE"}

# Confirmed 2026-08-07 for this league (2024/2025): FLEX accepts RB or WR
# only, NOT TE - matches the settings label "Wide Receiver / Running
# Back:" already captured in roster_settings. A different league/year
# could use a different flex-eligible set; this is a known
# generalization risk (see bugs.md) if Phase E hits a season configured
# differently.
FLEX_ELIGIBLE_POSITIONS = {"RB", "WR"}


def _get_points(player: dict) -> float:
    return player.get("points") or 0.0


def solve_optimal_lineup(players: list[dict], roster_settings: dict) -> dict:
    """players: full roster (starters + bench) for one team/week, each with
    at least position and points (see rosters/*.json or matchups/*.json
    slot-entry shape). roster_settings: that season's metadata.json
    settings.roster_settings (e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1,
    "FLEX": 1, "K": 1, "DEF": 1, "BENCH": 7, "RESERVE": 1}).

    Returns {"optimal_starters": [...], "optimal_points": float} - each
    optimal_starters entry is the original player dict plus an
    "optimal_slot" key. BENCH/RESERVE counts are ignored (not starting
    slots). Greedy strict-positions-first-then-flex-from-leftover is
    provably optimal for this problem shape (a single flex spanning
    exactly the RB/WR pool with independent per-position minimums) - see
    execution-plan.md Phase F for the exchange-argument proof sketch.
    """
    starting_slot_counts = {slot: count for slot, count in roster_settings.items() if slot not in BENCH_LIKE_SLOTS}
    flex_count = starting_slot_counts.pop("FLEX", 0) # remove flex instance as this will be handled after "main" positions

    available = list(players)
    optimal_starters = []

    for slot_name, count in starting_slot_counts.items():
        # get players for current slot (ex QB) and sort points descending
        candidates = sorted((p for p in available if p.get("position") == slot_name), key=_get_points, reverse=True)
        # get top N players based on slot count (ex QB 1)
        for player in candidates[:count]:
            optimal_starters.append({**player, "optimal_slot": slot_name})
            available.remove(player)

    # get flex eligble candidates defined as RB/WR
    flex_candidates = sorted((p for p in available if p.get("position") in FLEX_ELIGIBLE_POSITIONS), key=_get_points, reverse=True)
    for player in flex_candidates[:flex_count]:
        optimal_starters.append({**player, "optimal_slot": "FLEX"})
        available.remove(player)

    optimal_points = sum(_get_points(p) for p in optimal_starters)
    return {"optimal_starters": optimal_starters, "optimal_points": optimal_points}
