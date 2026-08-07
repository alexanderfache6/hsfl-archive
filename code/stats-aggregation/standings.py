"""Table 1: standings - record, win%, streak, points for/against, rank.
Weekly (that week's result alone) and cumulative (through that week).
See execution-plan.md Phase F, table 1.
"""


def _compute_streak(results: list[str]) -> str:
    if not results:
        return ""
    last_result = results[-1]
    count = 0
    for result in reversed(results):
        if result != last_result:
            break
        count += 1
    return f"{last_result}{count}"


def compute_standings_tables(team_week_index: dict, team_ids: list[str], weeks: list[int]) -> dict[int, list[dict]]:
    """Returns {week: [rows]}, one row per team that played that week:
    {team_id, rank, wins, losses, ties, win_pct, win_streak, points_for,
    points_against, weekly: {result, points_for, points_against}}.

    Simplification, documented per bugs.md's generalization-risk pattern:
    rank ties are broken by win_pct then cumulative points_for, NOT this
    league's actual "Head to Head Record" tiebreaker setting from
    metadata.json.settings - implementing true head-to-head tiebreaking
    would need full pairwise matchup history reconciliation, judged not
    worth the complexity for this archive/visualization use case.
    """
    cumulative = {team_id: {"wins": 0, "losses": 0, "ties": 0, "points_for": 0.0, "points_against": 0.0} for team_id in team_ids}
    results_history = {team_id: [] for team_id in team_ids}
    tables_by_week = {}

    for week in weeks:
        week_rows = []
        for team_id in team_ids:
            entry = team_week_index.get((team_id, week))
            if entry is None:  # bye
                continue
            score, opponent_score = entry["score"], entry["opponent_score"]
            if score > opponent_score:
                result = "W"
                cumulative[team_id]["wins"] += 1
            elif score < opponent_score:
                result = "L"
                cumulative[team_id]["losses"] += 1
            else:
                result = "T"
                cumulative[team_id]["ties"] += 1
            cumulative[team_id]["points_for"] += score
            cumulative[team_id]["points_against"] += opponent_score
            results_history[team_id].append(result)

            wins, losses, ties = cumulative[team_id]["wins"], cumulative[team_id]["losses"], cumulative[team_id]["ties"]
            games_played = wins + losses + ties
            win_pct = round((wins + 0.5 * ties) / games_played, 4) if games_played else 0.0

            week_rows.append(
                {
                    "team_id": team_id,
                    "wins": wins,
                    "losses": losses,
                    "ties": ties,
                    "win_pct": win_pct,
                    "win_streak": _compute_streak(results_history[team_id]),
                    "points_for": round(cumulative[team_id]["points_for"], 2),
                    "points_against": round(cumulative[team_id]["points_against"], 2),
                    "weekly": {"result": result, "points_for": round(score, 2), "points_against": round(opponent_score, 2)},
                }
            )

        week_rows.sort(key=lambda row: (-row["win_pct"], -row["points_for"]))
        for rank, row in enumerate(week_rows, start=1):
            row["rank"] = rank
        tables_by_week[week] = week_rows

    return tables_by_week
