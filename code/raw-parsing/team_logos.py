"""Downloads each team's logo image and records both the original URL
and the local downloaded path on that manager's per-season entry in
archive/managers.json. No new HTML fetches needed - the image URL is
already sitting in archive/raw/{year}/team_{id}/team_home.html, fetched
during the original crawl for standings/roster parsing
(<a class="teamImg ..."><img src="...">); this just parses that
already-cached HTML further and downloads the one additional image
asset it points to. See execution-plan.md Phase G.
"""

import re
from pathlib import Path

import httpx

from utils import ARCHIVE_DIRECTORY, MANAGERS_PATH, log_error, polite_sleep, raw_path, write_json

LOGO_URL_PATTERN = re.compile(r'<a href="[^"]*" class="teamImg[^"]*"><img src="([^"]+)"')

TEAM_LOGOS_DIRECTORY = ARCHIVE_DIRECTORY / "team_logos"


def extract_team_logo_url(team_home_html: str) -> str | None:
    match = LOGO_URL_PATTERN.search(team_home_html)
    return match.group(1) if match else None


def _logo_extension(url: str) -> str:
    # Strip the query string (e.g. "?&x=40&y=40") before reading the
    # extension, or it'd get picked up as part of the suffix.
    path_part = url.split("?", 1)[0]
    suffix = Path(path_part).suffix
    return suffix if suffix else ".jpg"


def download_team_logo(url: str, destination_path: Path) -> bool:
    """Idempotent like the HTML fetchers elsewhere in this package - skips
    entirely if the file's already on disk. Returns True on success (or
    already cached), False on failure (logged, not raised, so one bad
    image doesn't stop the whole run)."""
    if destination_path.exists():
        return True
    try:
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        log_error(url, status_code, str(exc))
        return False

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_bytes(response.content)
    polite_sleep()
    return True


def attach_team_logos(managers_registry: dict) -> dict:
    """Mutates managers_registry in place: for every manager's every
    season entry, parses that season's already-fetched team_home.html
    for the logo <img> URL, downloads it to
    archive/team_logos/{year}/team_{team_id}{ext}, and records both
    "logo_url" and "logo_path" (relative to archive/) on that season
    entry. A season/team missing team_home.html or a logo tag is simply
    left without those two fields, not treated as an error."""
    downloaded = 0
    for manager in managers_registry["managers"]:
        for season_entry in manager["seasons"]:
            year = season_entry["season"]
            team_id = season_entry["team_id"]
            team_home_path = raw_path(year, "team_home.html", team_id=team_id)
            if not team_home_path.exists():
                continue

            logo_url = extract_team_logo_url(team_home_path.read_text(encoding="utf-8", errors="ignore"))
            if not logo_url:
                continue

            destination_path = TEAM_LOGOS_DIRECTORY / str(year) / f"team_{team_id}{_logo_extension(logo_url)}"
            if download_team_logo(logo_url, destination_path):
                season_entry["logo_url"] = logo_url
                season_entry["logo_path"] = str(destination_path.relative_to(ARCHIVE_DIRECTORY))
                downloaded += 1

    print(f"attached {downloaded} team logos")
    return managers_registry


def main() -> None:
    import json

    registry = json.loads(MANAGERS_PATH.read_text())
    registry = attach_team_logos(registry)
    write_json(MANAGERS_PATH, registry)
    print(f"wrote {MANAGERS_PATH}")


if __name__ == "__main__":
    main()
