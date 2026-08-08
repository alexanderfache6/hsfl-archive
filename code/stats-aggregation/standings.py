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


def _head_to_head_win_pct(team_id: str, group_team_ids: set[str], head_to_head: dict) -> float:
    """This team's win% in games against just the OTHER teams currently
    tied with it (not the full schedule) - the league's actual
    tiebreaker setting, confirmed 2026-08-07 by comparing against every
    season's officially parsed regular_season_standings. 0.0 if the tied
    teams never actually played each other (e.g. a tie that arose without
    a shared matchup), which then falls through to the points_for
    tiebreaker below exactly as before."""
    wins = losses = ties = 0
    for opponent_id in group_team_ids:
        if opponent_id == team_id:
            continue
        record = head_to_head.get(team_id, {}).get(opponent_id)
        if record is None:
            continue
        wins += record["wins"]
        losses += record["losses"]
        ties += record["ties"]
    games_played = wins + losses + ties
    return (wins + 0.5 * ties) / games_played if games_played else 0.0


def _rank_with_tiebreakers(week_rows: list[dict], head_to_head: dict) -> list[dict]:
    """Sorts by win_pct descending; within a group of teams tied on
    win_pct, re-sorts by head-to-head win% among just that group, then by
    points_for - the league's actual "Head to Head Record" tiebreaker
    setting (metadata.json.settings), not a flat win_pct-then-points_for
    sort across everyone."""
    ranked: list[dict] = []
    rows_by_win_pct: dict[float, list[dict]] = {}
    win_pct_order: list[float] = []
    for row in week_rows:
        if row["win_pct"] not in rows_by_win_pct:
            win_pct_order.append(row["win_pct"])
            rows_by_win_pct[row["win_pct"]] = []
        rows_by_win_pct[row["win_pct"]].append(row)

    for win_pct in sorted(win_pct_order, reverse=True):
        group = rows_by_win_pct[win_pct]
        group_team_ids = {row["team_id"] for row in group}
        group.sort(key=lambda row: (-_head_to_head_win_pct(row["team_id"], group_team_ids, head_to_head), -row["points_for"]))
        ranked.extend(group)
    return ranked


def compute_standings_tables(team_week_index: dict, team_ids: list[str], weeks: list[int]) -> dict[int, list[dict]]:
    """Returns {week: [rows]}, one row per team that played that week:
    {team_id, rank, wins, losses, ties, win_pct, win_streak, points_for,
    points_against, weekly: {result, points_for, points_against}}.

    Rank ties are broken by head-to-head record among just the tied
    teams (the league's actual "Head to Head Record" tiebreaker setting),
    then by cumulative points_for if still tied - see
    _rank_with_tiebreakers.
    """
    cumulative = {team_id: {"wins": 0, "losses": 0, "ties": 0, "points_for": 0.0, "points_against": 0.0} for team_id in team_ids}
    results_history = {team_id: [] for team_id in team_ids}
    head_to_head: dict[str, dict[str, dict]] = {team_id: {} for team_id in team_ids}
    tables_by_week = {}

    for week in weeks:
        week_rows = []
        for team_id in team_ids:
            entry = team_week_index.get((team_id, week))
            if entry is None:  # bye
                continue
            score, opponent_score = entry["score"], entry["opponent_score"]
            opponent_id = entry["opponent_team_id"]
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

            opponent_record = head_to_head[team_id].setdefault(opponent_id, {"wins": 0, "losses": 0, "ties": 0})
            opponent_record["wins" if result == "W" else "losses" if result == "L" else "ties"] += 1

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

        week_rows = _rank_with_tiebreakers(week_rows, head_to_head)
        for rank, row in enumerate(week_rows, start=1):
            row["rank"] = rank
        tables_by_week[week] = week_rows

    return tables_by_week
