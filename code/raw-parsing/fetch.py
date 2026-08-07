"""Raw HTML fetcher. httpx first, Playwright fallback for JS-rendered pages.

Per instructions.md sections 0 and 3: every fetch is idempotent (skip if
already on disk), polite (delay between live requests), and logged on
failure.
"""

import re

import httpx

from utils import (
    BASE_HISTORY_URL,
    already_fetched,
    log_error,
    polite_sleep,
    raw_path,
    write_raw,
)

# Page-type -> (relative URL template, raw filename template).
# {year} / {week} / {offset} / {team_id} are filled in per season.
SEASON_URL_TEMPLATES = {
    # "/{year}/" alone 404s - confirmed 2026-08-06 against the 2025 season.
    # The season "home" is the standings page; archive it under both
    # league_home.html and standings.html since it's the same content.
    "league_home": ("/{year}/standings", "league_home.html"),
    "settings": ("/{year}/settings", "settings.html"),
    "standings_final": ("/{year}/standings", "standings.html"),
    "standings_regular": ("/{year}/standings?historyStandingsType=regular", "standings_regular.html"),
    "schedule": ("/{year}/schedule", "schedule.html"),
    # "draftresults" alone only returns picks 1-10 (page 1 of a paginated
    # view) - confirmed 2026-08-06. draftResultsDetail=0 is the "full
    # draft" view; two tabs needed since only "team" shows auction bid
    # amounts and only "nomination" shows the pick/nomination order.
    "draft_results_by_nomination": (
        "/{year}/draftresults?draftResultsDetail=0&draftResultsTab=nomination&draftResultsType=results",
        "draft_results_by_nomination.html",
    ),
    "draft_results_by_team": (
        "/{year}/draftresults?draftResultsDetail=0&draftResultsTab=team&draftResultsType=results",
        "draft_results_by_team.html",
    ),
    "playoffs_championship": ("/{year}/playoffs", "playoffs.html"),
    "playoffs_consolation": (
        "/{year}/playoffs?bracketType=consolation&standingsTab=playoffs",
        "playoffs_consolation.html",
    ),
}

# Requires {offset} substitution (transactions pagination). Confirmed
# working 2026-08-06 against the 2025 season as originally specified.
TRANSACTIONS_TEMPLATE = ("/{year}/transactions?offset={offset}", "transactions_page_{offset}.html")

# Requires {team_id}. Confirmed 2026-08-06: endpoint is "teamhome", not
# "team" as originally assumed - the playoffs bracket page links teams via
# .../teamhome?teamId={id}.
TEAM_HOME_TEMPLATE = ("/{year}/teamhome?teamId={team_id}", "team_home.html")

# Requires {team_id}, {week}. Confirmed 2026-08-06: same "teamhome"
# endpoint with a week parameter added returns that team's weekly roster.
TEAM_ROSTER_TEMPLATE = ("/{year}/teamhome?teamId={team_id}&week={week}", "roster_week_{week}.html")

# Requires {team_id}, {week}. Confirmed 2026-08-06 (user-supplied): there is
# no standalone "scoreboard" endpoint - matchup/box-score pages are fetched
# per team via teamgamecenter, one page per (team_id, week) pair.
TEAM_GAME_CENTER_TEMPLATE = ("/{year}/teamgamecenter?teamId={team_id}&week={week}", "gamecenter_week_{week}.html")


def fetch_static(client: httpx.Client, url: str, destination_path) -> tuple[str | None, int | None]:
    """Fetch a single URL via httpx, writing raw HTML and sidecar meta on success."""
    if already_fetched(destination_path):
        return destination_path.read_text(), 0  # 0 = served from disk, no network hit

    try:
        response = client.get(url, follow_redirects=True)
        write_raw(destination_path, response.text, url, response.status_code)
        polite_sleep()
        if response.status_code >= 400:
            log_error(url, response.status_code, "non-2xx response")
        return response.text, response.status_code
    except httpx.HTTPError as error:
        log_error(url, None, str(error))
        return None, None


def fetch_rendered(url: str, destination_path) -> tuple[str | None, int | None]:
    """Fallback for JS-rendered pages (live scoring, transactions feed) via Playwright.

    Only import playwright here - it's an optional/heavy dependency only
    needed when a static fetch returns an empty/JS-shell page.
    """
    if already_fetched(destination_path):
        return destination_path.read_text(), 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        log_error(url, None, f"playwright not available: {error}")
        return None, None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle")
            html_content = page.content()
            browser.close()
        write_raw(destination_path, html_content, url, 200)
        polite_sleep()
        return html_content, 200
    except Exception as error:  # noqa: BLE001 - log and continue, don't crash the run
        log_error(url, None, str(error))
        return None, None


def looks_like_javascript_shell(html_content: str | None) -> bool:
    """Heuristic: very short body or missing expected content markers."""
    if html_content is None:
        return True
    return len(html_content) < 2000


def fetch_page(
    client: httpx.Client,
    year: int,
    relative_url_template: str,
    filename_template: str,
    team_id: str | None = None,
    week: int | None = None,
    offset: int | None = None,
    subdirectory: str | None = None,
):
    url = f"{BASE_HISTORY_URL}{relative_url_template.format(year=year, team_id=team_id, week=week, offset=offset)}"
    filename = filename_template.format(week=week, offset=offset)
    destination_path = raw_path(year, filename, team_id=team_id, subdirectory=subdirectory)
    html_content, status_code = fetch_static(client, url, destination_path)
    if looks_like_javascript_shell(html_content):
        html_content, status_code = fetch_rendered(url, destination_path)
    return html_content, status_code


def fetch_season_static_pages(client: httpx.Client, year: int) -> dict:
    """Fetch the fixed set of per-season pages (section 3 table, minus paginated/per-week/per-team)."""
    results = {}
    for purpose, (relative_url_template, filename_template) in SEASON_URL_TEMPLATES.items():
        html_content, status_code = fetch_page(client, year, relative_url_template, filename_template)
        results[purpose] = status_code
    return results


def fetch_team_home_pages(client: httpx.Client, year: int, team_ids: list[str]) -> dict:
    relative_url_template, filename_template = TEAM_HOME_TEMPLATE
    results = {}
    for team_id in team_ids:
        _, status_code = fetch_page(client, year, relative_url_template, filename_template, team_id=team_id)
        results[team_id] = status_code
    return results


def fetch_weekly_rosters(client: httpx.Client, year: int, team_ids: list[str], weeks: list[int]) -> dict:
    relative_url_template, filename_template = TEAM_ROSTER_TEMPLATE
    results = {}
    for team_id in team_ids:
        for week in weeks:
            _, status_code = fetch_page(client, year, relative_url_template, filename_template, team_id=team_id, week=week)
            results[(team_id, week)] = status_code
    return results


def fetch_team_game_centers(client: httpx.Client, year: int, team_ids: list[str], weeks: list[int]) -> dict:
    relative_url_template, filename_template = TEAM_GAME_CENTER_TEMPLATE
    results = {}
    for team_id in team_ids:
        for week in weeks:
            _, status_code = fetch_page(client, year, relative_url_template, filename_template, team_id=team_id, week=week)
            results[(team_id, week)] = status_code
    return results


def page_has_no_transactions(html_content: str) -> bool:
    """True once the page shows the "No transactions" empty-state message.

    Comparing consecutive pages for exact-duplicate content does NOT work
    here - confirmed 2026-08-06: every page (including genuinely empty
    ones) embeds volatile per-request ad-tracking fields (AD_ORD, TIME),
    so no two page fetches are ever byte-identical even when the visible
    transaction content is the same/empty.
    """
    return "no transactions" in html_content.lower()


def fetch_all_transactions_pages(client: httpx.Client, year: int, page_size: int = 25) -> int:
    """Paginate through transactions until a page shows the empty-state message.

    Returns the number of pages fetched, including the first empty page
    (kept for auditability - it's proof pagination terminated correctly
    rather than being cut off by the safety cap).
    """
    relative_url_template, filename_template = TRANSACTIONS_TEMPLATE
    offset = 0
    pages_fetched = 0
    while True:
        html_content, status_code = fetch_page(
            client, year, relative_url_template, filename_template, offset=offset, subdirectory="transactions"
        )
        if html_content is None or status_code not in (0, 200):
            break
        pages_fetched += 1
        if page_has_no_transactions(html_content):
            break
        offset += page_size
        if offset > 5000:  # safety cap - a single season shouldn't have this many transactions
            log_error(f"{BASE_HISTORY_URL}/{year}/transactions", None, "safety cap reached without empty-state page")
            break
    return pages_fetched


def discover_team_ids_and_weeks(year: int) -> tuple[list[str], list[int]]:
    """Lightweight regex-based discovery from already-fetched standings/schedule HTML.

    Not a full parser (see parse.py) - just enough structure detection to
    know which team_ids and weeks exist so the per-team/per-week fetch
    loops have something to iterate over.
    """
    standings_path = raw_path(year, "standings.html")
    schedule_path = raw_path(year, "schedule.html")

    standings_html = standings_path.read_text() if standings_path.exists() else ""
    schedule_html = schedule_path.read_text() if schedule_path.exists() else ""
    combined_html = standings_html + schedule_html

    team_ids = sorted(set(re.findall(r"teamId-(\d+)", combined_html)), key=int)
    weeks = sorted(set(int(week) for week in re.findall(r"[Ww]eek[^0-9]{0,5}(\d+)", combined_html)))
    return team_ids, weeks
