"""Table 4: true ranking - composite power ranking through week N,
cumulative-only (confirmed 2026-08-07). Sums each team's rank across
standings (record), points_for, breakdown, and coaching (all cumulative
through that week); lower sum is better. See execution-plan.md Phase F,
table 4.
"""


def compute_true_ranking_tables(
    standings_by_week: dict[int, list[dict]],
    breakdown_by_week: dict[int, list[dict]],
    coaching_by_week: dict[int, list[dict]],
    team_ids: list[str],
    weeks: list[int],
) -> dict[int, list[dict]]:
    """Returns {week: [rows]}: {team_id, record_rank, points_for_rank,
    breakdown_rank, coaching_rank, true_ranking_score, true_rank}.
    points_for_rank is its own independent sort by cumulative points_for,
    not table 1's win-based rank."""
    tables_by_week = {}

    for week in weeks:
        standings_rows = {row["team_id"]: row for row in standings_by_week[week]}
        breakdown_rows = {row["team_id"]: row for row in breakdown_by_week[week]}
        coaching_rows = {row["team_id"]: row for row in coaching_by_week[week]}

        present_team_ids = [team_id for team_id in team_ids if team_id in standings_rows]
        points_for_sorted = sorted(present_team_ids, key=lambda team_id: -standings_rows[team_id]["points_for"])
        points_for_rank_by_team = {team_id: rank for rank, team_id in enumerate(points_for_sorted, start=1)}

        week_rows = []
        for team_id in present_team_ids:
            record_rank = standings_rows[team_id]["rank"]
            points_for_rank = points_for_rank_by_team[team_id]
            breakdown_rank = breakdown_rows[team_id]["cumulative"]["rank"]
            coaching_rank = coaching_rows[team_id]["cumulative"]["rank"]
            true_ranking_score = record_rank + points_for_rank + breakdown_rank + coaching_rank
            week_rows.append(
                {
                    "team_id": team_id,
                    "record_rank": record_rank,
                    "points_for_rank": points_for_rank,
                    "breakdown_rank": breakdown_rank,
                    "coaching_rank": coaching_rank,
                    "true_ranking_score": true_ranking_score,
                }
            )

        week_rows.sort(key=lambda row: row["true_ranking_score"])
        for rank, row in enumerate(week_rows, start=1):
            row["true_rank"] = rank
        week_rows.sort(key=lambda row: int(row["team_id"]))
        tables_by_week[week] = week_rows

    return tables_by_week
