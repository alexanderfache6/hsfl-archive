"""Shared paths for stats-aggregation. Deliberately independent of code/raw-parsing/
(no imports from it) - reads only finished archive/parsed/{year}/*.json output."""

import json
from pathlib import Path

PROJECT_ROOT_DIRECTORY = Path(__file__).resolve().parent.parent.parent
ARCHIVE_DIRECTORY = PROJECT_ROOT_DIRECTORY / "archive"
PARSED_DIRECTORY = ARCHIVE_DIRECTORY / "parsed"
AGGREGATED_DIRECTORY = ARCHIVE_DIRECTORY / "aggregated"
MANAGERS_PATH = ARCHIVE_DIRECTORY / "managers.json"


def parsed_path(year: int, filename: str, subdirectory: str | None = None) -> Path:
    if subdirectory is not None:
        return PARSED_DIRECTORY / str(year) / subdirectory / filename
    return PARSED_DIRECTORY / str(year) / filename


def aggregated_path(year: int, filename: str, subdirectory: str | None = None) -> Path:
    if subdirectory is not None:
        return AGGREGATED_DIRECTORY / str(year) / subdirectory / filename
    return AGGREGATED_DIRECTORY / str(year) / filename


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_metadata(year: int) -> dict:
    return read_json(parsed_path(year, "metadata.json"))


def team_id_to_manager(year: int) -> dict[str, dict]:
    metadata = load_metadata(year)
    return {
        team["team_id"]: {"manager_id": team["manager_id"], "display_name": team["manager_display_name"]}
        for team in metadata["teams"]
    }


def load_display_name_alternates() -> dict[str, str]:
    """{manager_id: alternate_name} for managers who share a display_name
    with someone else in the league (e.g. two different persistent
    manager_ids both named "Alex") - only non-empty entries are included.
    Source of truth is archive/managers.json's display_names_seen_alternate
    field (set in code/raw-parsing/managers.py); read here rather than
    duplicated, since it's a finished archive output like everything else
    this package reads."""
    if not MANAGERS_PATH.exists():
        return {}
    registry = read_json(MANAGERS_PATH)
    return {
        manager["manager_id"]: manager["display_names_seen_alternate"]
        for manager in registry.get("managers", [])
        if manager.get("display_names_seen_alternate")
    }


def update_record(current: dict | None, candidate_value: float, better_if_higher: bool, context: dict) -> dict:
    """Shared "keep the best/worst seen so far" reducer used by both
    per-season records.py and cross-season all_time.py, so a record's
    shape ({"value": ..., **context}) stays identical whether it's scoped
    to one season or combined across all of them."""
    if current is None:
        return {"value": candidate_value, **context}
    is_better = candidate_value > current["value"] if better_if_higher else candidate_value < current["value"]
    return {"value": candidate_value, **context} if is_better else current


def update_top_n_records(current_list: list[dict], candidate_value: float, better_if_higher: bool, context: dict, n: int = 3) -> list[dict]:
    """Like update_record, but keeps the top N (not just the single best)
    - added 2026-08-07 so the History page can show 2nd/3rd place
    alongside each record. Keeping only the top N per season is provably
    sufficient for an accurate all-time top N too: an all-time top-N list
    can never need a 4th-or-worse entry from any single season, since at
    most N of its slots could ever come from one season anyway - so
    all_time.py can safely combine every season's already-trimmed top-N
    lists (see combine_top_n_records) without re-scanning raw per-team
    data."""
    updated = [*current_list, {"value": candidate_value, **context}]
    updated.sort(key=lambda record: record["value"], reverse=better_if_higher)
    return updated[:n]


def combine_top_n_records(lists_of_records: list[list[dict]], better_if_higher: bool, n: int = 3) -> list[dict]:
    """Merges several already-trimmed top-N lists (e.g. one per season)
    into a single overall top-N list."""
    combined = [record for records in lists_of_records for record in records]
    combined.sort(key=lambda record: record["value"], reverse=better_if_higher)
    return combined[:n]


def placement_number(round_label: str) -> int | None:
    """Extracts the "Nth" from a placement game label (e.g. "9th Place
    Game" -> 9, any "super bowl"/"championship" label -> 1). Duplicated
    from code/raw-parsing/parse.py's _placement_number rather than
    imported, per this package's independence constraint (no
    cross-package imports) - see module docstrings. Bug fix 2026-08-07:
    added "championship" as a placement-1 synonym (2012 data used that
    literal label instead of "Fantasy Super Bowl") - see parse.py's
    _placement_number docstring for the full story."""
    import re

    label_lower = round_label.lower()
    if "super bowl" in label_lower or "championship" in label_lower:
        return 1
    match = re.search(r"(\d+)(?:st|nd|rd|th)\s+Place", round_label, re.IGNORECASE)
    return int(match.group(1)) if match else None


def load_regular_season_weeks(year: int) -> list[int]:
    """Weeks with at least one real matchup AND before the playoffs start.

    Confirmed 2026-08-07: schedule.json's "has matchups" filter alone
    isn't enough - playoff weeks still have real (if bye-reduced)
    matchups, so a naive "any matchups that week" check wrongly included
    weeks 15-17 as "regular season" for both 2024 and 2025. The playoff
    start week is parsed out of metadata.json's
    settings.playoff_teams_and_weeks string (e.g. "Weeks 15, 16 & 17 - 6
    teams" -> playoffs start at 15, so regular season is weeks < 15).
    """
    import re

    schedule = read_json(parsed_path(year, "schedule.json"))
    weeks_with_matchups = [w["week"] for w in schedule["weeks"] if w["matchups"]]

    metadata = load_metadata(year)
    playoff_weeks_text = metadata["settings"].get("playoff_teams_and_weeks", "")
    playoff_start_match = re.search(r"(\d+)", playoff_weeks_text)
    if not playoff_start_match:
        return weeks_with_matchups  # fallback: no playoff info found, don't filter
    playoff_start_week = int(playoff_start_match.group(1))
    return [week for week in weeks_with_matchups if week < playoff_start_week]


def build_team_week_index(year: int) -> dict[tuple[str, int], dict]:
    """One entry per (team_id, week) a team actually played, built once by
    scanning every matchups/*.json file for the season - the single
    source of truth for that team's score, opponent, and full roster
    (starters + bench, with real per-week points/positions) that week.
    Every other module in this package reads through this index rather
    than re-parsing matchup files itself.
    """
    matchups_directory = PARSED_DIRECTORY / str(year) / "matchups"
    index: dict[tuple[str, int], dict] = {}
    for matchup_path in matchups_directory.glob("*.json"):
        matchup = read_json(matchup_path)
        week = matchup["week"]
        home, away = matchup["home"], matchup["away"]
        index[(home["team_id"], week)] = {
            "opponent_team_id": away["team_id"],
            "score": home["score"],
            "opponent_score": away["score"],
            "starters": home["starters"],
            "bench": home["bench"],
        }
        index[(away["team_id"], week)] = {
            "opponent_team_id": home["team_id"],
            "score": away["score"],
            "opponent_score": home["score"],
            "starters": away["starters"],
            "bench": away["bench"],
        }
    return index
