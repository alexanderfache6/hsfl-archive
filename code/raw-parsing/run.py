"""Orchestrator entrypoint. See instructions/execution-plan.md for phased rollout.

Phase B usage (single test season):
    python run.py --year 2025

Full run (Phase E, not yet wired up):
    python run.py --all
"""

import argparse

import httpx

from fetch import fetch_season_static_pages
from manifest import update_index

PAGE_TYPE_BY_FETCH_PURPOSE = {
    "league_home": None,  # not tracked in index.json individually
    "settings": "metadata",
    "standings_final": "standings_final",
    "standings_regular": "standings_regular",
    "schedule": "schedule",
    "draft_results_by_nomination": "draft",
    "draft_results_by_team": "draft",
    "playoffs_championship": "playoffs_championship",
    "playoffs_consolation": "playoffs_consolation",
}


def run_static_fetch_for_season(year: int) -> None:
    with httpx.Client(timeout=30) as client:
        fetch_results_by_purpose = fetch_season_static_pages(client, year)

    for purpose, status_code in fetch_results_by_purpose.items():
        page_type = PAGE_TYPE_BY_FETCH_PURPOSE.get(purpose)
        if page_type is None:
            continue
        status = "ok" if status_code in (0, 200) else "missing"
        update_index(year, page_type, status)


def main() -> None:
    argument_parser = argparse.ArgumentParser(description="HSFL fantasy league archiver")
    argument_parser.add_argument("--year", type=int, help="Fetch a single season (Phase B test run)")
    argument_parser.add_argument("--all", action="store_true", help="Run all seasons 2012-2025 (Phase E, not yet implemented)")
    parsed_arguments = argument_parser.parse_args()

    if parsed_arguments.year:
        run_static_fetch_for_season(parsed_arguments.year)
    elif parsed_arguments.all:
        raise NotImplementedError("Phase E full run not yet implemented - validate Phase B/C on 2025 first")
    else:
        argument_parser.print_help()


if __name__ == "__main__":
    main()
