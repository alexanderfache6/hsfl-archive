"""Season-long count of distinct players a team started at least once,
from the union of starters across all weeks' matchups/*.json for that
team. See execution-plan.md Phase F stat list.
"""


def compute_players_started(team_week_index: dict, team_ids: list[str], weeks: list[int]) -> list[dict]:
    """Returns [{team_id, player_count, player_ids}] - the union of
    starter player_ids across every week's matchup for that team. Bench
    players are excluded - this counts who was actually started, not who
    was ever rostered."""
    results = []
    for team_id in team_ids:
        player_ids = set()
        for week in weeks:
            entry = team_week_index.get((team_id, week))
            if entry is None:
                continue
            for player in entry["starters"]:
                player_id = player.get("player_id")
                if player_id:
                    player_ids.add(player_id)
        results.append({"team_id": team_id, "player_count": len(player_ids), "player_ids": sorted(player_ids)})
    return results
