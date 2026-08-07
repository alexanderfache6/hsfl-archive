"""Per-season post-season (playoff) win/loss/points per team, split by
bracket - championship and consolation are different competitive
contexts, so kept separate rather than merged (a team is only ever in
one bracket per season, so there's no double-counting either way, but
"championship bracket record" and "consolation bracket record" mean
different things and shouldn't be blended). Written by aggregate_season.py
to archive/aggregated/{year}/post_season_stats.json; read directly by
all_time.py rather than re-derived from playoffs.json there. See
execution-plan.md Phase G.
"""


def _bracket_team_records(bracket: dict) -> dict:
    """{team_id: {wins, losses, ties, points_for, points_against}} from one
    bracket's completed (non-bye) matchups."""
    records: dict[str, dict] = {}

    def cell(team_id: str) -> dict:
        return records.setdefault(team_id, {"wins": 0, "losses": 0, "ties": 0, "points_for": 0.0, "points_against": 0.0})

    for round_entry in bracket.get("rounds", []):
        for matchup in round_entry.get("matchups", []):
            if matchup.get("is_bye"):
                continue
            home_id, away_id, winner_id = matchup.get("team_id_home"), matchup.get("team_id_away"), matchup.get("winner_team_id")
            if not home_id or not away_id or not winner_id:
                continue
            home_score, away_score = matchup.get("score_home") or 0.0, matchup.get("score_away") or 0.0

            home_cell = cell(home_id)
            home_cell["points_for"] += home_score
            home_cell["points_against"] += away_score
            away_cell = cell(away_id)
            away_cell["points_for"] += away_score
            away_cell["points_against"] += home_score

            if winner_id == home_id:
                home_cell["wins"] += 1
                away_cell["losses"] += 1
            else:
                away_cell["wins"] += 1
                home_cell["losses"] += 1

    for record in records.values():
        record["points_for"] = round(record["points_for"], 2)
        record["points_against"] = round(record["points_against"], 2)

    return records


def compute_final_placements(playoffs: dict) -> dict[str, int]:
    """{team_id: final_overall_rank} for every team that played a labeled
    placement game (e.g. "Fantasy Super Bowl"/"Championship" -> 1st,
    "3rd Place Game" -> 3rd) in either bracket's final round. Winner of a
    game labeled placement N gets rank N; loser gets rank N+1. Confirmed
    2026-08-07 across 2012/2013/2024/2025: consolation-bracket placement
    numbers already continue globally from wherever the championship
    bracket left off (e.g. a 4-team championship bracket yields ranks
    1-4, and that year's consolation final round is labeled "5th Place
    Game" rather than "7th" - the numbering adapts to actual bracket
    sizes on its own), so no manual offsetting between brackets is
    needed - just combine both brackets' final-round results directly.
    A team with no labeled placement game in either bracket's final
    round (should be rare/nonexistent given the pattern above, but not
    guaranteed for every possible season) simply won't appear in the
    returned dict."""
    from utils import placement_number

    placements: dict[str, int] = {}
    for bracket_key in ("championship_bracket", "consolation_bracket"):
        rounds = playoffs[bracket_key].get("rounds", [])
        if not rounds:
            continue
        final_round = rounds[-1]
        for matchup in final_round.get("matchups", []):
            if matchup.get("is_bye"):
                continue
            placement = placement_number(matchup.get("round_label", ""))
            home_id, away_id, winner_id = matchup.get("team_id_home"), matchup.get("team_id_away"), matchup.get("winner_team_id")
            if placement is None or not home_id or not away_id or not winner_id:
                continue
            loser_id = away_id if winner_id == home_id else home_id
            placements[winner_id] = placement
            placements[loser_id] = placement + 1
    return placements


def compute_post_season_stats(playoffs: dict) -> dict:
    return {
        "championship": _bracket_team_records(playoffs["championship_bracket"]),
        "consolation": _bracket_team_records(playoffs["consolation_bracket"]),
        "final_placements": compute_final_placements(playoffs),
    }
