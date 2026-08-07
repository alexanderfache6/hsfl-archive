"""Per-season head-to-head record matrices - regular season (from weekly
matchups) and post season (from playoffs.json, kept separate by bracket
since championship and consolation are different competitive contexts).
Written by aggregate_season.py to archive/aggregated/{year}/head_to_head.json;
combined across years by all_time.py. See execution-plan.md Phase G.
"""


def compute_regular_season_head_to_head(team_week_index: dict, team_ids: list[str], weeks: list[int]) -> dict:
    """{team_id: {opponent_team_id: {wins, losses, ties}}}."""
    matrix: dict[str, dict] = {}
    for week in weeks:
        for team_id in team_ids:
            entry = team_week_index.get((team_id, week))
            if entry is None:  # bye
                continue
            opponent_id = entry["opponent_team_id"]
            cell = matrix.setdefault(team_id, {}).setdefault(opponent_id, {"wins": 0, "losses": 0, "ties": 0})
            if entry["score"] > entry["opponent_score"]:
                cell["wins"] += 1
            elif entry["score"] < entry["opponent_score"]:
                cell["losses"] += 1
            else:
                cell["ties"] += 1
    return matrix


def _bracket_head_to_head(bracket: dict) -> dict:
    matrix: dict[str, dict] = {}
    for round_entry in bracket.get("rounds", []):
        for matchup in round_entry.get("matchups", []):
            if matchup.get("is_bye"):
                continue
            home_id, away_id, winner_id = matchup.get("team_id_home"), matchup.get("team_id_away"), matchup.get("winner_team_id")
            if not home_id or not away_id or not winner_id:
                continue
            home_cell = matrix.setdefault(home_id, {}).setdefault(away_id, {"wins": 0, "losses": 0, "ties": 0})
            away_cell = matrix.setdefault(away_id, {}).setdefault(home_id, {"wins": 0, "losses": 0, "ties": 0})
            if winner_id == home_id:
                home_cell["wins"] += 1
                away_cell["losses"] += 1
            else:
                away_cell["wins"] += 1
                home_cell["losses"] += 1
    return matrix


def compute_post_season_head_to_head(playoffs: dict) -> dict:
    """{"championship": {team_id: {opponent_team_id: {wins,losses,ties}}},
    "consolation": {...}} - kept as two separate matrices (the
    "flag that separates these 2 brackets", confirmed 2026-08-07) rather
    than one merged matrix with a per-game bracket tag."""
    return {
        "championship": _bracket_head_to_head(playoffs["championship_bracket"]),
        "consolation": _bracket_head_to_head(playoffs["consolation_bracket"]),
    }
