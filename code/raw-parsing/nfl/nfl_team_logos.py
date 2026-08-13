"""Downloads each real NFL team's official logo image from ESPN's team
index page (not the fantasy league's own uploaded team logos - see
code/raw-parsing/team_logos.py for those, a separate, unrelated source).
One-time fetch: run once and re-run only if a team ever rebrands (moves
cities, changes logo) - these are NOT re-fetched automatically the way
the fantasy-site scrapers are, since there's no per-season variation to
track.

Source: https://www.espn.com/nfl/teams - each team's block has:
    <a href="/nfl/team/_/name/{abbr}/{slug}">
        <img alt="{Full Team Name}" class="Image Logo Logo__lg" ...
             src="https://a.espncdn.com/combiner/i?img=/i/teamlogos/nfl/500/{abbr}.png&...">
    </a>
(confirmed 2026-08-12, e.g. abbr="buf", alt="Buffalo Bills").

ESPN blocks plain httpx/curl requests (returns an empty 202 - bot
detection), so the team INDEX page is fetched via Playwright, same as
nfl_bye_weeks.py in the parent directory - but the actual logo IMAGE
download itself is a plain file download (no bot-detection issue there),
so that part reuses httpx like the fantasy-site's own team_logos.py.

Output:
    archive/nfl-team-logos/{abbr}.png - one downloaded image per team
    archive/nfl_team_logos.json - reference list: [{"team": abbr,
        "name": full name, "logo_url": original ESPN URL, "logo_path":
        path to the downloaded file, relative to archive/}, ...]
"""

import html
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import ARCHIVE_DIRECTORY, log_error, polite_sleep, write_json  # noqa: E402

ESPN_TEAMS_URL = "https://www.espn.com/nfl/teams"

NFL_TEAM_LOGOS_DIRECTORY = ARCHIVE_DIRECTORY / "nfl-team-logos"
NFL_TEAM_LOGOS_REFERENCE_PATH = ARCHIVE_DIRECTORY / "nfl_team_logos.json"

TEAM_LOGO_PATTERN = re.compile(
    r'href="/nfl/team/_/name/([a-z]+)/[a-z0-9-]+"><img alt="([^"]+)" class="Image Logo Logo__lg"[^>]*src="([^"]+)"'
)

# Real browser UA - ESPN's bot detection blocks the default
# Playwright/httpx user agent strings outright (confirmed 2026-08-12: a
# bare httpx.get() on espn.com returns an empty 202).
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def fetch_team_logo_urls() -> list[dict]:
    """[{"team": abbr, "name": full name, "logo_url": ...}, ...] scraped
    from the team index page - the src URL is ESPN's own "combiner" image
    API, HTML-entity-escaped in the raw markup (&amp;) so it's decoded
    here before use."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(user_agent=BROWSER_USER_AGENT)
        page.goto(ESPN_TEAMS_URL, wait_until="domcontentloaded", timeout=30000)
        polite_sleep(2)
        # The page lazy-loads team logo <img> tags (a placeholder
        # data:image/gif shows until each one scrolls into view) -
        # confirmed 2026-08-12: roughly half came back as unloaded
        # placeholders without this, and which half was inconsistent
        # between runs (viewport/timing dependent). Scrolling the full
        # page height in steps forces every logo to actually load before
        # the DOM gets captured.
        page_height = page.evaluate("document.body.scrollHeight")
        for offset in range(0, page_height, 800):
            page.evaluate(f"window.scrollTo(0, {offset})")
            page.wait_for_timeout(150)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        polite_sleep(1)
        content = page.content()
        browser.close()

    return [
        {"team": team, "name": name, "logo_url": html.unescape(logo_url)}
        for team, name, logo_url in TEAM_LOGO_PATTERN.findall(content)
    ]


def download_team_logo(url: str, destination_path: Path) -> bool:
    """Idempotent - skips entirely if the file's already on disk, same
    pattern as the fantasy-site's own team_logos.py. Returns True on
    success (or already cached), False on failure (logged, not raised,
    so one bad image doesn't stop the whole run)."""
    if destination_path.exists():
        return True
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": BROWSER_USER_AGENT})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        log_error(url, status_code, str(exc))
        return False

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_bytes(response.content)
    polite_sleep()
    return True


def build_nfl_team_logos() -> list[dict]:
    teams = fetch_team_logo_urls()
    print(f"found {len(teams)} teams")

    reference = []
    for entry in teams:
        destination_path = NFL_TEAM_LOGOS_DIRECTORY / f"{entry['team']}.png"
        if not download_team_logo(entry["logo_url"], destination_path):
            continue
        reference.append(
            {
                "team": entry["team"],
                "name": entry["name"],
                "logo_url": entry["logo_url"],
                "logo_path": str(destination_path.relative_to(ARCHIVE_DIRECTORY)),
            }
        )

    return reference


def main() -> None:
    reference = build_nfl_team_logos()
    write_json(NFL_TEAM_LOGOS_REFERENCE_PATH, reference)
    print(f"downloaded {len(reference)} logos, wrote {NFL_TEAM_LOGOS_REFERENCE_PATH}")


if __name__ == "__main__":
    main()
