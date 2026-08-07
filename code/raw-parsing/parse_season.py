"""Parse every raw page for one season into archive/parsed/{year}/. Reusable across all years.

Usage:
    python parse_season.py --year 2025

Reads the raw HTML fetched by fetch_season.py and writes the JSON files
defined in instructions.md section 2. Requires fetch_season.py to have
already run for the given year.
"""

import argparse
from pathlib import Path

from fetch import discover_team_ids_and_weeks
from parse import (
    parse_draft,
    parse_matchup_week,
    parse_metadata,
    parse_playoffs,
    parse_roster,
    parse_schedule_from_gamecenters,
    parse_standings,
    parse_transactions_page,
)
from utils import RAW_DIRECTORY, parsed_path, raw_path, write_json


def parse_season(year: int) -> None:
    team_ids, weeks = discover_team_ids_and_weeks(year)
    print(f"[{year}] parsing for {len(team_ids)} teams, {len(weeks)} weeks")

    metadata = parse_metadata(
        raw_path(year, "settings.html").read_text(),
        raw_path(year, "schedule.html").read_text(),
        year,
    )
    write_json(parsed_path(year, "metadata.json"), metadata)
    print(f"[{year}] wrote metadata.json")

    standings = parse_standings(
        raw_path(year, "standings.html").read_text(),
        raw_path(year, "standings_regular.html").read_text(),
        year,
    )
    write_json(parsed_path(year, "standings.json"), standings)
    print(f"[{year}] wrote standings.json")

    draft = parse_draft(
        raw_path(year, "draft_results_by_nomination.html").read_text(),
        raw_path(year, "draft_results_by_team.html").read_text(),
        year,
    )
    write_json(parsed_path(year, "draft.json"), draft)
    print(f"[{year}] wrote draft.json ({len(draft['picks'])} picks)")

    playoffs = parse_playoffs(
        raw_path(year, "playoffs.html").read_text(),
        raw_path(year, "playoffs_consolation.html").read_text(),
        year,
    )
    write_json(parsed_path(year, "playoffs.json"), playoffs)
    print(f"[{year}] wrote playoffs.json")

    schedule = parse_schedule_from_gamecenters(year, team_ids, weeks)
    write_json(parsed_path(year, "schedule.json"), schedule)
    print(f"[{year}] wrote schedule.json")

    matchups_written = 0
    for week_entry in schedule["weeks"]:
        week = week_entry["week"]
        for matchup in week_entry["matchups"]:
            home_team_id = matchup["team_id_home"]
            gamecenter_path = raw_path(year, f"gamecenter_week_{week}.html", team_id=home_team_id)
            if not gamecenter_path.exists():
                continue
            matchup_data = parse_matchup_week(gamecenter_path.read_text(), year, week)
            destination = parsed_path(year, f"week_{week}_{home_team_id}_{matchup['team_id_away']}.json", subdirectory="matchups")
            write_json(destination, matchup_data)
            matchups_written += 1
    print(f"[{year}] wrote {matchups_written} matchup files")

    transactions_directory = RAW_DIRECTORY / str(year) / "transactions"
    all_transactions = []
    for transactions_file in sorted(transactions_directory.glob("transactions_page_*.html")):
        all_transactions.extend(parse_transactions_page(transactions_file.read_text(), year))
    write_json(parsed_path(year, "transactions.json"), {"season": year, "transactions": all_transactions})
    print(f"[{year}] wrote transactions.json ({len(all_transactions)} transactions)")

    rosters_written = 0
    for team_id in team_ids:
        for week in weeks:
            roster_path = raw_path(year, f"roster_week_{week}.html", team_id=team_id)
            if not roster_path.exists():
                continue
            gamecenter_path = raw_path(year, f"gamecenter_week_{week}.html", team_id=team_id)
            gamecenter_html = gamecenter_path.read_text() if gamecenter_path.exists() else None
            roster_data = parse_roster(roster_path.read_text(), year, team_id, week, gamecenter_html=gamecenter_html)
            destination = parsed_path(year, f"team_{team_id}_week_{week}.json", subdirectory="rosters")
            write_json(destination, roster_data)
            rosters_written += 1
    print(f"[{year}] wrote {rosters_written} roster files")

    print(f"[{year}] done")


def main() -> None:
    argument_parser = argparse.ArgumentParser(description="Parse all raw pages for one HSFL archive season")
    argument_parser.add_argument("--year", type=int, required=True, help="Season to parse, e.g. 2025")
    parsed_arguments = argument_parser.parse_args()
    parse_season(parsed_arguments.year)


if __name__ == "__main__":
    main()
