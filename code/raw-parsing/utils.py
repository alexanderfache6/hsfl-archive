"""Shared helpers: rate limiting, idempotent fetch/write, error logging."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

LEAGUE_ID = "1401993"
BASE_HISTORY_URL = f"https://fantasy.nfl.com/league/{LEAGUE_ID}/history"
BASE_CURRENT_URL = f"https://fantasy.nfl.com/league/{LEAGUE_ID}"

PROJECT_ROOT_DIRECTORY = Path(__file__).resolve().parent.parent.parent
ARCHIVE_DIRECTORY = PROJECT_ROOT_DIRECTORY / "archive"
RAW_DIRECTORY = ARCHIVE_DIRECTORY / "raw"
PARSED_DIRECTORY = ARCHIVE_DIRECTORY / "parsed"
PROGRESS_DIRECTORY = ARCHIVE_DIRECTORY / "progress"
INDEX_PATH = ARCHIVE_DIRECTORY / "index.json"
MANAGERS_PATH = ARCHIVE_DIRECTORY / "managers.json"
PLAYERS_PATH = ARCHIVE_DIRECTORY / "players.json"
ERROR_LOG_PATH = PROGRESS_DIRECTORY / "errors.log"

REQUEST_DELAY_SECONDS = 1.5


def polite_sleep(seconds: float = REQUEST_DELAY_SECONDS) -> None:
    time.sleep(seconds)


def raw_path(year: int, filename: str, team_id: str | None = None, subdirectory: str | None = None) -> Path:
    if team_id is not None:
        return RAW_DIRECTORY / str(year) / f"team_{team_id}" / filename
    if subdirectory is not None:
        return RAW_DIRECTORY / str(year) / subdirectory / filename
    return RAW_DIRECTORY / str(year) / filename


def parsed_path(year: int, filename: str, subdirectory: str | None = None) -> Path:
    if subdirectory is not None:
        return PARSED_DIRECTORY / str(year) / subdirectory / filename
    return PARSED_DIRECTORY / str(year) / filename


def write_json(destination_path: Path, data) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(json.dumps(data, indent=2))


def write_meta(destination_path: Path, url: str, status_code: int, from_cache: bool = False) -> None:
    meta_path = destination_path.with_suffix(destination_path.suffix + ".meta.json")
    meta = {
        "url": url,
        "status_code": status_code,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "from_cache": from_cache,
    }
    meta_path.write_text(json.dumps(meta, indent=2))


def log_error(url: str, status_code: int | None, exception_text: str) -> None:
    PROGRESS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "status_code": status_code,
        "error": exception_text,
    }
    with ERROR_LOG_PATH.open("a") as log_file:
        log_file.write(json.dumps(entry) + "\n")


def already_fetched(destination_path: Path) -> bool:
    """A page only counts as "done" if it's on disk AND its cached status
    was a success. A cached 4xx/5xx response must NOT block a retry -
    otherwise a fixed URL-pattern bug never self-heals on re-run, since
    the bad response was already written to disk on the first attempt
    (confirmed 2026-08-06: this is exactly why the league_home and
    draft_results URL fixes earlier required manually deleting stale
    cached files instead of just re-running the fetch)."""
    if not destination_path.exists():
        return False
    meta_path = destination_path.with_suffix(destination_path.suffix + ".meta.json")
    if not meta_path.exists():
        return True  # no meta to check against - assume a prior successful write
    status_code = json.loads(meta_path.read_text()).get("status_code")
    return status_code is not None and 200 <= status_code < 300


def write_raw(destination_path: Path, content: str, url: str, status_code: int) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(content)
    write_meta(destination_path, url, status_code, from_cache=False)
