"""Table 3: coaching - how much worse than optimal a team's actual lineup
scored that week (always <= 0). Weekly and cumulative. Uses
optimal_lineup.solve_optimal_lineup(). See execution-plan.md Phase F,
table 3.
"""

from optimal_lineup import solve_optimal_lineup


def compute_coaching_tables(team_week_index: dict, team_ids: list[str], weeks: list[int], roster_settings: dict) -> dict[int, list[dict]]:
    """Returns {week: [rows]}: {team_id, weekly: {actual_points,
    optimal_points, diff, rank}, cumulative: {diff_sum, rank}}. rank =
    closest-to-zero diff is best (least points wasted on the bench) -
    diffs are always <= 0, so higher (less negative) sorts as rank 1.
    """
    cumulative_diff_sum = {team_id: 0.0 for team_id in team_ids}
    tables_by_week = {}

    for week in weeks:
        week_rows = []
        for team_id in team_ids:
            entry = team_week_index.get((team_id, week))
            if entry is None:  # bye
                continue
            all_players = entry["starters"] + entry["bench"]
            solved = solve_optimal_lineup(all_players, roster_settings)
            actual_points = round(sum((p.get("points") or 0.0) for p in entry["starters"]), 2)
            optimal_points = round(solved["optimal_points"], 2)
            diff = round(actual_points - optimal_points, 2)
            cumulative_diff_sum[team_id] += diff

            week_rows.append(
                {
                    "team_id": team_id,
                    "weekly": {"actual_points": actual_points, "optimal_points": optimal_points, "diff": diff},
                    "cumulative": {"diff_sum": round(cumulative_diff_sum[team_id], 2)},
                }
            )

        weekly_sorted = sorted(week_rows, key=lambda row: -row["weekly"]["diff"])
        for rank, row in enumerate(weekly_sorted, start=1):
            row["weekly"]["rank"] = rank
        cumulative_sorted = sorted(week_rows, key=lambda row: -row["cumulative"]["diff_sum"])
        for rank, row in enumerate(cumulative_sorted, start=1):
            row["cumulative"]["rank"] = rank

        week_rows.sort(key=lambda row: int(row["team_id"]))
        tables_by_week[week] = week_rows

    return tables_by_week
