"""Table 2: breakdown (all-play) - a team's record if it had played every
other team that week instead of just its scheduled opponent. Weekly and
cumulative. See execution-plan.md Phase F, table 2.
"""


def compute_breakdown_tables(team_week_index: dict, team_ids: list[str], weeks: list[int]) -> dict[int, list[dict]]:
    """Returns {week: [rows]}: {team_id, weekly: {wins, losses, ties,
    win_pct, rank}, cumulative: {wins, losses, ties, win_pct, rank}}."""
    cumulative = {team_id: {"wins": 0, "losses": 0, "ties": 0} for team_id in team_ids}
    tables_by_week = {}

    for week in weeks:
        scores_by_team_id = {
            team_id: team_week_index[(team_id, week)]["score"]
            for team_id in team_ids
            if (team_id, week) in team_week_index
        }

        week_rows = []
        for team_id, score in scores_by_team_id.items():
            other_scores = [s for other_id, s in scores_by_team_id.items() if other_id != team_id]
            weekly_wins = sum(1 for s in other_scores if score > s)
            weekly_losses = sum(1 for s in other_scores if score < s)
            weekly_ties = sum(1 for s in other_scores if score == s)
            weekly_games = weekly_wins + weekly_losses + weekly_ties
            weekly_win_pct = round((weekly_wins + 0.5 * weekly_ties) / weekly_games, 4) if weekly_games else 0.0

            cumulative[team_id]["wins"] += weekly_wins
            cumulative[team_id]["losses"] += weekly_losses
            cumulative[team_id]["ties"] += weekly_ties
            cumulative_wins, cumulative_losses, cumulative_ties = (
                cumulative[team_id]["wins"],
                cumulative[team_id]["losses"],
                cumulative[team_id]["ties"],
            )
            cumulative_games = cumulative_wins + cumulative_losses + cumulative_ties
            cumulative_win_pct = round((cumulative_wins + 0.5 * cumulative_ties) / cumulative_games, 4) if cumulative_games else 0.0

            week_rows.append(
                {
                    "team_id": team_id,
                    "weekly": {"wins": weekly_wins, "losses": weekly_losses, "ties": weekly_ties, "win_pct": weekly_win_pct},
                    "cumulative": {"wins": cumulative_wins, "losses": cumulative_losses, "ties": cumulative_ties, "win_pct": cumulative_win_pct},
                }
            )

        for scope in ("weekly", "cumulative"):
            week_rows.sort(key=lambda row: -row[scope]["win_pct"])
            for rank, row in enumerate(week_rows, start=1):
                row[scope]["rank"] = rank
        # sort order above ends on "cumulative" - re-sort by team_id for stable, predictable output order
        week_rows.sort(key=lambda row: int(row["team_id"]))
        tables_by_week[week] = week_rows

    return tables_by_week
