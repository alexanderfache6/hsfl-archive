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
    post_season_stats: dict | None = None,
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

    # win_streak is a cumulative counter ("W1", "W2", "W3", ...) that
    # grows every week a streak stays alive, so recording a candidate on
    # EVERY week it's active would let one real 15-game streak flood the
    # top-3 list with itself three times over (13, 14, 15) instead of
    # three actually-different streaks. Only the last week of each
    # contiguous streak - its peak, right before it resets or changes
    # type - gets submitted as a candidate.
    team_weekly_streaks: dict[str, list[tuple[int, str]]] = {}

    for week in weeks:
        for row in standings_by_week[week]:
            manager = resolve(row["team_id"], "records.weekly_score")
            context = {"week": week, "manager_id": manager.get("manager_id", ""), "display_name": manager.get("display_name", "")}
            highest_weekly_score = update_top_n_records(highest_weekly_score, row["weekly"]["points_for"], True, context)
            lowest_weekly_score = update_top_n_records(lowest_weekly_score, row["weekly"]["points_for"], False, context)

            team_weekly_streaks.setdefault(row["team_id"], []).append((week, row["win_streak"]))

    for team_id, weekly_streaks in team_weekly_streaks.items():
        manager = resolve(team_id, "records.win_streak")
        for index, (week, streak) in enumerate(weekly_streaks):
            if not streak:
                continue
            streak_type = streak[0]
            next_streak = weekly_streaks[index + 1][1] if index + 1 < len(weekly_streaks) else ""
            is_streak_peak = not next_streak or next_streak[0] != streak_type
            if not is_streak_peak:
                continue

            streak_length = int(streak[1:])
            streak_context = {
                "week": week,
                # streak_length already counts consecutive weeks including
                # the peak week, so the start week is just peak - length + 1
                # - no separate tracking needed.
                "start_week": week - streak_length + 1,
                "manager_id": manager.get("manager_id", ""),
                "display_name": manager.get("display_name", ""),
                "streak": streak,
            }
            if streak_type == "W":
                longest_win_streak = update_top_n_records(longest_win_streak, streak_length, True, streak_context)
            elif streak_type == "L":
                longest_losing_streak = update_top_n_records(longest_losing_streak, streak_length, True, streak_context)

    # "Season points" means the WHOLE season - regular season plus
    # whichever postseason bracket a team ended up in - not just the
    # regular-season cumulative total standings_by_week tracks (weeks
    # here is regular-season weeks only, via load_regular_season_weeks;
    # postseason points live separately in post_season_stats, keyed by
    # bracket, since a team is only ever in one bracket per season).
    def postseason_points_for(team_id: str) -> float:
        if not post_season_stats:
            return 0.0
        championship_row = post_season_stats.get("championship", {}).get(team_id)
        consolation_row = post_season_stats.get("consolation", {}).get(team_id)
        return (championship_row or {}).get("points_for", 0.0) + (consolation_row or {}).get("points_for", 0.0)

    if weeks:
        final_week = weeks[-1]
        final_coaching = {row["team_id"]: row for row in coaching_by_week[final_week]}
        for row in standings_by_week[final_week]:
            manager = resolve(row["team_id"], "records.season_points_and_coaching")
            context = {"manager_id": manager.get("manager_id", ""), "display_name": manager.get("display_name", "")}
            full_season_points_for = row["points_for"] + postseason_points_for(row["team_id"])
            highest_season_points_for = update_top_n_records(highest_season_points_for, full_season_points_for, True, context)
            lowest_season_points_for = update_top_n_records(lowest_season_points_for, full_season_points_for, False, context)

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
