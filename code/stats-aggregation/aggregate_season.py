"""Aggregate one season's parsed data into archive/aggregated/{year}/.
Runs independent of code/raw-parsing/ - reads only archive/parsed/{year}/*.json.

Usage:
    python aggregate_season.py --year 2025
"""

import argparse

from breakdown import compute_breakdown_tables
from coaching import compute_coaching_tables
from head_to_head import compute_post_season_head_to_head, compute_regular_season_head_to_head
from players_started import compute_players_started
from post_season_stats import compute_post_season_stats
from records import compute_season_records
from standings import compute_standings_tables
from true_ranking import compute_true_ranking_tables
from utils import (
    aggregated_path,
    build_team_week_index,
    load_metadata,
    load_regular_season_weeks,
    parsed_path,
    read_json,
    team_id_to_manager,
    write_json,
)


def aggregate_season(year: int) -> None:
    metadata = load_metadata(year)
    team_ids = [team["team_id"] for team in metadata["teams"]]
    roster_settings = metadata["settings"]["roster_settings"]
    weeks = load_regular_season_weeks(year)
    team_week_index = build_team_week_index(year)
    manager_by_team_id = team_id_to_manager(year)

    standings_by_week = compute_standings_tables(team_week_index, team_ids, weeks)
    breakdown_by_week = compute_breakdown_tables(team_week_index, team_ids, weeks)
    coaching_by_week = compute_coaching_tables(team_week_index, team_ids, weeks, roster_settings)
    true_ranking_by_week = compute_true_ranking_tables(standings_by_week, breakdown_by_week, coaching_by_week, team_ids, weeks)

    weekly_tables = [
        {
            "week": week,
            "standings": standings_by_week[week],
            "breakdown": breakdown_by_week[week],
            "coaching": coaching_by_week[week],
            "true_ranking": true_ranking_by_week[week],
        }
        for week in weeks
    ]
    write_json(aggregated_path(year, "weekly_tables.json"), {"season": year, "weeks": weekly_tables})

    players_started = compute_players_started(team_week_index, team_ids, weeks)
    write_json(aggregated_path(year, "players_started.json"), {"season": year, "teams": players_started})

    playoffs = read_json(parsed_path(year, "playoffs.json"))
    head_to_head = {
        "season": year,
        "regular_season": compute_regular_season_head_to_head(team_week_index, team_ids, weeks),
        "post_season": compute_post_season_head_to_head(playoffs),
    }
    write_json(aggregated_path(year, "head_to_head.json"), head_to_head)

    post_season_stats = compute_post_season_stats(playoffs, standings_by_week[weeks[-1]])
    write_json(aggregated_path(year, "post_season_stats.json"), {"season": year, **post_season_stats})

    season_records = compute_season_records(manager_by_team_id, standings_by_week, coaching_by_week, weeks, players_started, post_season_stats)
    write_json(aggregated_path(year, "records.json"), {"season": year, **season_records})
    if season_records["unresolved"]:
        print(f"[{year}] WARNING: {len(season_records['unresolved'])} unresolved team_id -> manager lookups in records.json: {season_records['unresolved']}")

    print(f"[{year}] wrote weekly_tables.json ({len(weekly_tables)} weeks), players_started.json, head_to_head.json, post_season_stats.json, records.json")


def main() -> None:
    argument_parser = argparse.ArgumentParser(description="Aggregate one HSFL archive season's stats")
    argument_parser.add_argument("--year", type=int, required=True, help="Season to aggregate, e.g. 2025")
    parsed_arguments = argument_parser.parse_args()
    aggregate_season(parsed_arguments.year)


if __name__ == "__main__":
    main()
