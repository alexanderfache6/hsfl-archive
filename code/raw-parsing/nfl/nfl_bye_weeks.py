"""Fetches each NFL team's bye week for every season, from ESPN's team
schedule pages (not the fantasy league's own site - a separate, real-NFL
data source). Used for bye-week validation per player on the frontend
Players tab (see pages_players.py's _build_full_game_list): a player
missing from a fantasy roster during their own NFL team's actual bye
week is expected and not "unrostered" the way a genuine gap week is.

Team abbreviations are scraped once from https://www.espn.com/nfl/teams
(each team links to "/nfl/team/schedule/_/name/{abbr}"), then each
team's own schedule page is fetched per season:
https://www.espn.com/nfl/team/schedule/_/name/{abbr}/season/{year}

That schedule page renders one <tr> per week; the bye week's row has no
opponent, just a <td colspan="9">BYE WEEK</td> next to the week number:
    <tr ...><td ...><span data-testid="week">10</span></td>
    <td colspan="9" ...>BYE WEEK</td></tr>
(confirmed 2026-08-12 against New England's 2022 schedule - week 10).

ESPN blocks plain httpx/curl requests (returns an empty 202 - bot
detection), so this uses Playwright like the JS-rendered-page fallback
elsewhere in this package (fetch.py's fetch_rendered), not httpx.

Season range: FIRST_SEASON (2012, the archive's first season) through
"next calendar year" - computed from the current date, not a hardcoded
end year, so a run in 2027 automatically reaches for 2028 without a code
change (that far-future season just won't have a schedule published
yet, which is handled the same as any other incomplete season - see
below - not an error).

Some team-seasons genuinely have no bye at all - a real NFL scheduling
anomaly, not a fetch/parsing failure - e.g. Miami and Tampa Bay's 2017
Week 1 game was postponed by Hurricane Irma and made up later that
season using what would otherwise have been their bye week, so neither
team's ESPN schedule page has a "BYE WEEK" row for 2017 at all (confirmed
2026-08-13: searched their full 2017 schedule tables directly, no
colspan bye row exists anywhere in either page). These are recorded
explicitly via KNOWN_NO_BYE_EXCEPTIONS below as {"bye": null, "comment":
"..."} rather than silently omitted, so the season still resolves to
fully complete instead of being retried forever. Downstream consumers
(not yet wired up - see pages_players.py's _render_summary_metrics) MUST
treat a null bye as "this team played every week, no bye to subtract"
(0 weeks off), NOT as "unknown, skip this team-season" - otherwise a
Dolphins/Buccaneers 2017 player's "NFL Games" total would be silently
undercounted by the 1 week that was never actually missed.

Output: archive/nfl_bye_weeks.json, keyed by season (as a string), each
{"status": "{filled} / {total}", "teams": [{"team": abbr, "bye": week},
...]}:
    {"2022": {"status": "32 / 32", "teams": [{"team": "ne", "bye": 10},
    ...]}, "2017": {"status": "32 / 32", "teams": [..., {"team": "mia",
    "bye": null, "comment": "..."}, ...]}, "2027": {"status": "0 / 32",
    "teams": []}, ...}

Re-running is fast and safe: a season already marked complete ("N / N",
filled == total teams) is skipped ENTIRELY - not even a single request
is made for it - since bye weeks for a past season never change once
published. An incomplete season (a future season with no schedule out
yet, e.g. "0 / 32", or a partial season if some team fetches failed last
time) gets retried in full on the next run, since there's real reason to
expect it might now be complete. Within a season being (re)attempted,
each team/year page is ALSO individually cached on disk
(archive/raw/espn_bye_weeks/{year}/{team}.html) via the same idempotent
already_fetched() pattern used elsewhere in this package, so a partial
season's already-successful teams aren't re-fetched either.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import ARCHIVE_DIRECTORY, already_fetched, log_error, polite_sleep, write_json, write_meta  # noqa: E402

ESPN_TEAMS_URL = "https://www.espn.com/nfl/teams"
ESPN_TEAM_SCHEDULE_URL_TEMPLATE = "https://www.espn.com/nfl/team/schedule/_/name/{team}/season/{year}"

BYE_WEEKS_RAW_DIRECTORY = ARCHIVE_DIRECTORY / "raw" / "espn_bye_weeks"
BYE_WEEKS_OUTPUT_PATH = ARCHIVE_DIRECTORY / "nfl_bye_weeks.json"

FIRST_SEASON = 2012

# (team, year) -> why this team genuinely had no bye that season - see
# the module docstring. Confirmed by directly inspecting the cached
# schedule HTML (no "BYE WEEK" row present anywhere), not just an
# extract_bye_week() miss - a team that legitimately has one but this
# script failed to find should stay unresolved and get retried, not be
# silently added here.
KNOWN_NO_BYE_EXCEPTIONS = {
    ("mia", 2017): (
        "Miami's Week 1 game vs Tampa Bay was postponed by Hurricane Irma and made up later in the season using "
        "what would have been their bye week - Miami had no true bye in 2017."
    ),
    ("tb", 2017): (
        "Tampa Bay's Week 1 game vs Miami was postponed by Hurricane Irma and made up later in the season using "
        "what would have been their bye week - Tampa Bay had no true bye in 2017."
    ),
}


def _default_last_season() -> int:
    """Next calendar year after "now" - always reaches one season ahead
    of the current one, so this script never needs a manual year bump."""
    return datetime.now(timezone.utc).year + 1


TEAM_SCHEDULE_LINK_PATTERN = re.compile(r'href="/nfl/team/schedule/_/name/([a-z]+)"')
BYE_WEEK_ROW_PATTERN = re.compile(r'data-testid="week">(\d+)</span></td><td colspan="9"[^>]*>BYE WEEK</td>')

# Playwright needs a real browser UA - ESPN's bot detection blocks the
# default Playwright/httpx user agent strings outright (confirmed
# 2026-08-12: a bare httpx.get() on espn.com returns an empty 202).
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _team_raw_path(team: str, year: int):
    return BYE_WEEKS_RAW_DIRECTORY / str(year) / f"{team}.html"


def _load_existing_bye_weeks() -> dict[str, dict]:
    if not BYE_WEEKS_OUTPUT_PATH.exists():
        return {}
    import json

    return json.loads(BYE_WEEKS_OUTPUT_PATH.read_text())


def _season_status(filled_count: int, total_teams: int) -> str:
    return f"{filled_count} / {total_teams}"


def _season_is_complete(season_entry: dict | None, total_teams: int) -> bool:
    # A pre-upgrade output file has a bare list per season (no "status"
    # field at all) - treated as incomplete so it gets reprocessed once
    # into the current {"status", "teams"} shape. That reprocessing is
    # cheap: every team/year page is already cached on disk from
    # whatever run produced the old file, so nothing gets re-fetched
    # over the network, just re-read and reformatted.
    if not isinstance(season_entry, dict):
        return False
    return season_entry.get("status") == _season_status(total_teams, total_teams)


def fetch_team_abbreviations(page) -> list[str]:
    """Scrapes every team's schedule-page abbreviation from the team
    index page - e.g. "ne" for New England, "wsh" for Washington (not
    the same as their box-score abbreviation in the fantasy site's own
    archive, which is why bye weeks are stored/looked-up by THIS
    abbreviation, not cross-referenced against DEF_TEAM_ABBREVIATIONS)."""
    page.goto(ESPN_TEAMS_URL, wait_until="domcontentloaded", timeout=30000)
    polite_sleep(2)
    html = page.content()
    abbreviations = sorted(set(TEAM_SCHEDULE_LINK_PATTERN.findall(html)))
    return abbreviations


def fetch_team_season_html(page, team: str, year: int) -> str | None:
    """Idempotent like the fantasy-site fetchers in fetch.py - skips
    entirely (no network hit) if this team/year is already cached on
    disk from a prior run."""
    destination_path = _team_raw_path(team, year)
    if already_fetched(destination_path):
        return destination_path.read_text()

    url = ESPN_TEAM_SCHEDULE_URL_TEMPLATE.format(team=team, year=year)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        polite_sleep(2)
        html = page.content()
    except Exception as error:  # noqa: BLE001 - a single bad page shouldn't kill the whole run
        log_error(url, None, str(error))
        return None

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(html)
    write_meta(destination_path, url, 200)
    return html


def extract_bye_week(html: str) -> int | None:
    match = BYE_WEEK_ROW_PATTERN.search(html)
    return int(match.group(1)) if match else None


def build_bye_weeks(start_year: int = FIRST_SEASON, end_year: int | None = None) -> dict[str, dict]:
    end_year = end_year if end_year is not None else _default_last_season()
    from playwright.sync_api import sync_playwright

    existing = _load_existing_bye_weeks()
    bye_weeks: dict[str, dict] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(user_agent=BROWSER_USER_AGENT)

        teams = fetch_team_abbreviations(page)
        print(f"found {len(teams)} teams: {teams}")

        for year in range(start_year, end_year + 1):
            season_key = str(year)

            if _season_is_complete(existing.get(season_key), len(teams)):
                bye_weeks[season_key] = existing[season_key]
                print(f"{season_key}: already complete ({bye_weeks[season_key]['status']}) - skipped")
                continue

            season_teams = []
            for team in teams:
                html = fetch_team_season_html(page, team, year)
                if html is None:
                    continue
                bye_week = extract_bye_week(html)
                if bye_week is None:
                    exception_comment = KNOWN_NO_BYE_EXCEPTIONS.get((team, year))
                    if exception_comment:
                        season_teams.append({"team": team, "bye": None, "comment": exception_comment})
                    # else: not an error worth log_error-ing on its own -
                    # a future season with no schedule published yet
                    # legitimately has no BYE WEEK row to find (and
                    # correctly stays "incomplete," retried next run).
                    continue
                season_teams.append({"team": team, "bye": bye_week})

            bye_weeks[season_key] = {"status": _season_status(len(season_teams), len(teams)), "teams": season_teams}
            print(f"{season_key}: {bye_weeks[season_key]['status']} teams' bye weeks found")

        browser.close()

    return bye_weeks


def main() -> None:
    bye_weeks = build_bye_weeks()
    write_json(BYE_WEEKS_OUTPUT_PATH, bye_weeks)
    print(f"wrote {BYE_WEEKS_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
