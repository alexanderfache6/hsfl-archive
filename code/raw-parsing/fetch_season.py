"""Fetch every raw page for one season. Reusable across all years 2012-2025.

Usage:
    python fetch_season.py --year 2025

Runs, in order: static season pages, team_id/week discovery from those
pages, team home pages, weekly rosters, weekly game centers, and paginated
transactions. Every step is idempotent - already-downloaded files are
skipped, so re-running for the same year is safe and resumes cleanly.
"""

import argparse

import httpx

from fetch import (
    discover_team_ids_and_weeks,
    fetch_all_transactions_pages,
    fetch_season_static_pages,
    fetch_team_game_centers,
    fetch_team_home_pages,
    fetch_weekly_rosters,
)


def fetch_season(year: int) -> None:
    with httpx.Client(timeout=30) as client:
        print(f"[{year}] fetching static season pages...")
        static_page_results = fetch_season_static_pages(client, year)
        for purpose, status_code in static_page_results.items():
            print(f"[{year}]   {purpose}: status={status_code}")

        team_ids, weeks = discover_team_ids_and_weeks(year)
        print(f"[{year}] discovered {len(team_ids)} teams, {len(weeks)} weeks")

        print(f"[{year}] fetching team home pages...")
        team_home_results = fetch_team_home_pages(client, year, team_ids)
        print(f"[{year}]   {len(team_home_results)} team home pages fetched")

        print(f"[{year}] fetching weekly rosters ({len(team_ids)} teams x {len(weeks)} weeks)...")
        roster_results = fetch_weekly_rosters(client, year, team_ids, weeks)
        print(f"[{year}]   {len(roster_results)} roster pages fetched")

        print(f"[{year}] fetching weekly game centers ({len(team_ids)} teams x {len(weeks)} weeks)...")
        game_center_results = fetch_team_game_centers(client, year, team_ids, weeks)
        print(f"[{year}]   {len(game_center_results)} game center pages fetched")

        print(f"[{year}] fetching transactions pages...")
        transactions_pages_fetched = fetch_all_transactions_pages(client, year)
        print(f"[{year}]   {transactions_pages_fetched} transactions pages fetched")

    print(f"[{year}] done")


def main() -> None:
    argument_parser = argparse.ArgumentParser(description="Fetch all raw pages for one HSFL archive season")
    argument_parser.add_argument("--year", type=int, required=True, help="Season to fetch, e.g. 2025")
    parsed_arguments = argument_parser.parse_args()
    fetch_season(parsed_arguments.year)


if __name__ == "__main__":
    main()
