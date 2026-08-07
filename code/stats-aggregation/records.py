"""Per-season record-book superlatives (highest/lowest weekly score,
season points, streaks, coaching, players started) - scoped to just one
season, so the Yearly UI page can show that season's own records.
Written by aggregate_season.py to archive/aggregated/{year}/records.json;
combined across years by all_time.py into the all-time version. See
execution-plan.md Phase G.

Updated 2026-08-07: each stat is now a top-3 list (not just the single
best) via update_top_n_records, so the History page can show 2nd/3rd
place alongside each record.
"""

from utils import update_top_n_records


def compute_season_records(
    team_id_to_manager: dict,
    standings_by_week: dict[int, list[dict]],
    coaching_by_week: dict[int, list[dict]],
    weeks: list[int],
    players_started_rows: list[dict],
) -> dict:
    highest_weekly_score: list[dict] = []
    lowest_weekly_score: list[dict] = []
    highest_season_points_for: list[dict] = []
    lowest_season_points_for: list[dict] = []
    longest_win_streak: list[dict] = []
    longest_losing_streak: list[dict] = []
    best_coaching_season: list[dict] = []
    worst_coaching_season: list[dict] = []
    most_players_started_season: list[dict] = []
    fewest_players_started_season: list[dict] = []
    unresolved: list[dict] = []

    def resolve(team_id: str, context_label: str) -> dict:
        manager = team_id_to_manager.get(team_id)
        if manager is None:
            unresolved.append({"team_id": team_id, "context": context_label})
            return {}
        return manager

    for week in weeks:
        for row in standings_by_week[week]:
            manager = resolve(row["team_id"], "records.weekly_score")
            context = {"week": week, "manager_id": manager.get("manager_id", ""), "display_name": manager.get("display_name", "")}
            highest_weekly_score = update_top_n_records(highest_weekly_score, row["weekly"]["points_for"], True, context)
            lowest_weekly_score = update_top_n_records(lowest_weekly_score, row["weekly"]["points_for"], False, context)

            streak = row["win_streak"]
            if streak:
                streak_type, streak_length = streak[0], int(streak[1:])
                streak_context = {**context, "streak": streak}
                if streak_type == "W":
                    longest_win_streak = update_top_n_records(longest_win_streak, streak_length, True, streak_context)
                elif streak_type == "L":
                    longest_losing_streak = update_top_n_records(longest_losing_streak, streak_length, True, streak_context)

    if weeks:
        final_week = weeks[-1]
        final_coaching = {row["team_id"]: row for row in coaching_by_week[final_week]}
        for row in standings_by_week[final_week]:
            manager = resolve(row["team_id"], "records.season_points_and_coaching")
            context = {"manager_id": manager.get("manager_id", ""), "display_name": manager.get("display_name", "")}
            highest_season_points_for = update_top_n_records(highest_season_points_for, row["points_for"], True, context)
            lowest_season_points_for = update_top_n_records(lowest_season_points_for, row["points_for"], False, context)

            coaching_row = final_coaching.get(row["team_id"])
            if coaching_row:
                diff_sum = coaching_row["cumulative"]["diff_sum"]
                best_coaching_season = update_top_n_records(best_coaching_season, diff_sum, True, context)
                worst_coaching_season = update_top_n_records(worst_coaching_season, diff_sum, False, context)

    for team_row in players_started_rows:
        manager = resolve(team_row["team_id"], "records.players_started")
        context = {"manager_id": manager.get("manager_id", ""), "display_name": manager.get("display_name", "")}
        most_players_started_season = update_top_n_records(most_players_started_season, team_row["player_count"], True, context)
        fewest_players_started_season = update_top_n_records(fewest_players_started_season, team_row["player_count"], False, context)

    return {
        "highest_weekly_score": highest_weekly_score,
        "lowest_weekly_score": lowest_weekly_score,
        "highest_season_points_for": highest_season_points_for,
        "lowest_season_points_for": lowest_season_points_for,
        "longest_win_streak": longest_win_streak,
        "longest_losing_streak": longest_losing_streak,
        "best_coaching_season": best_coaching_season,
        "worst_coaching_season": worst_coaching_season,
        "most_players_started_season": most_players_started_season,
        "fewest_players_started_season": fewest_players_started_season,
        "unresolved": unresolved,
    }
