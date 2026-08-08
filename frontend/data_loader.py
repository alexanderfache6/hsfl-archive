"""Reads the committed archive/*.json output directly - no database, no
API calls. See execution-plan.md Phase G for the architecture (data is
fetched/parsed/aggregated offline and committed to the repo; the
frontend is a pure read-only view over those static files).
"""

import json
import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT_DIRECTORY = Path(__file__).resolve().parent.parent
ARCHIVE_DIRECTORY = PROJECT_ROOT_DIRECTORY / "archive"
AGGREGATED_DIRECTORY = ARCHIVE_DIRECTORY / "aggregated"
PARSED_DIRECTORY = ARCHIVE_DIRECTORY / "parsed"

# Reuses code/stats-aggregation's own optimal-lineup solver (the same
# formula behind best_coaching_season/worst_coaching_season) instead of
# reimplementing it here, so the Games tab's optimal-lineup column can
# never drift out of sync with the backend's own coaching-efficiency math.
STATS_AGGREGATION_DIRECTORY = PROJECT_ROOT_DIRECTORY / "code" / "stats-aggregation"
if str(STATS_AGGREGATION_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(STATS_AGGREGATION_DIRECTORY))
from optimal_lineup import FLEX_ELIGIBLE_POSITIONS, solve_optimal_lineup  # noqa: E402

# Standard 12-color ColorBrewer "Paired" qualitative palette - not
# available under plotly.express.colors.qualitative by this name (that
# module has Set1/Set2/Set3 etc, but no "Paired"), so hardcoded here
# rather than adding a matplotlib dependency just for these 12 hex codes.
PAIRED_PALETTE = [
    "#A6CEE3", "#1F78B4", "#B2DF8A", "#33A02C",
    "#FB9A99", "#E31A1C", "#FDBF6F", "#FF7F00",
    "#CAB2D6", "#6A3D9A", "#FFFF99", "#B15928",
]


def _read_json(path: Path):
    return json.loads(path.read_text())


@st.cache_resource
def load_all_time_champions() -> dict:
    return _read_json(AGGREGATED_DIRECTORY / "all_time_champions.json")


@st.cache_resource
def load_all_time_manager_stats() -> dict:
    return _read_json(AGGREGATED_DIRECTORY / "all_time_manager_stats.json")


@st.cache_resource
def load_all_time_records() -> dict:
    return _read_json(AGGREGATED_DIRECTORY / "all_time_records.json")


@st.cache_resource
def discover_seasons() -> list[int]:
    if not PARSED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in PARSED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


@st.cache_resource
def load_weekly_tables(year: int) -> dict:
    return _read_json(AGGREGATED_DIRECTORY / str(year) / "weekly_tables.json")


@st.cache_resource
def load_players_started(year: int) -> dict:
    return _read_json(AGGREGATED_DIRECTORY / str(year) / "players_started.json")


@st.cache_resource
def build_manager_name_resolver() -> dict[str, str]:
    """{manager_id: display name to actually show in the UI}. Prefers
    display_names_seen_alternate (set in archive/managers.json for
    managers who share a display_name with someone else, e.g. two
    different manager_ids both named "Alex") over the raw
    display_names_seen, per user instruction 2026-08-07: "for all UI
    items first check if display_names_seen_alternate is not "" and if
    so use [it]". Every UI element that shows a manager's name should
    resolve through this rather than reading a raw display_name field
    directly, so the disambiguation is applied consistently everywhere -
    not just the one table it was first requested for."""
    manager_stats = load_all_time_manager_stats()
    resolver = {}
    for manager in manager_stats["managers"]:
        alternate = manager.get("display_names_seen_alternate", "")
        if alternate:
            resolver[manager["manager_id"]] = alternate
        elif manager["display_names_seen"]:
            resolver[manager["manager_id"]] = manager["display_names_seen"][-1]
    return resolver


def resolve_manager_name(manager_id: str, resolver: dict[str, str], fallback: str = "") -> str:
    return resolver.get(manager_id, fallback)


@st.cache_resource
def build_manager_color_map() -> dict[str, str]:
    """{manager_id: color} - one unique, STABLE color per manager (Paired
    palette), assigned once from the full sorted manager_id list so a
    given manager always gets the same color everywhere (pie chart,
    player flow-chart nodes, starter bars, etc), regardless of which
    subset of managers happens to appear in any one chart. Sorting by
    manager_id (not by any chart-specific order like championship count)
    is what makes the assignment stable across different views."""
    manager_stats = load_all_time_manager_stats()
    manager_ids = sorted(manager["manager_id"] for manager in manager_stats["managers"])
    return {manager_id: PAIRED_PALETTE[index % len(PAIRED_PALETTE)] for index, manager_id in enumerate(manager_ids)}


@st.cache_resource
def load_players() -> dict:
    return _read_json(ARCHIVE_DIRECTORY / "players.json")


@st.cache_resource
def load_player_ownership() -> dict:
    return _read_json(ARCHIVE_DIRECTORY / "player_ownership.json")


@st.cache_resource
def load_stat_id_labels() -> dict[str, str]:
    """{"stat_5": "Pass Yds", ...} - NFL.com's fantasy statId -> short
    label, harvested once from every archived gamecenter page's HTML (see
    archive/stat_id_labels.json's own "note" field) and confirmed
    identical across every season on file, so it's stored as a static
    lookup rather than re-derived at parse time. Keys are re-prefixed
    with "stat_" here to match player_ownership.json's "stats" dict keys
    directly (the on-disk file itself just stores the bare numeric ID)."""
    raw_labels = _read_json(ARCHIVE_DIRECTORY / "stat_id_labels.json")["stat_id_labels"]
    return {f"stat_{stat_id}": label for stat_id, label in raw_labels.items()}


@st.cache_resource
def load_nfl_season_lengths() -> dict[str, int]:
    """{"2012": 16, ..., "2021": 17, ...} - each year's real NFL
    regular-season game count (see archive/nfl_season_lengths.json's own
    "note" for the 16->17 game expansion in 2021 and why this is
    deliberately NOT the same number as this league's own fantasy
    regular-season week count)."""
    return _read_json(ARCHIVE_DIRECTORY / "nfl_season_lengths.json")["nfl_regular_season_games"]


@st.cache_resource
def load_metadata(year: int) -> dict:
    return _read_json(PARSED_DIRECTORY / str(year) / "metadata.json")


def compute_optimal_lineup(players: list[dict], year: int) -> dict:
    """players: one team's full starters + bench for one week. Looks up
    that season's roster_settings (slot eligibility can differ season to
    season - see optimal_lineup.py) and returns
    {"optimal_starters": [...with "optimal_slot"...], "optimal_points"}."""
    roster_settings = load_metadata(year)["settings"]["roster_settings"]
    return solve_optimal_lineup(players, roster_settings)


@st.cache_resource
def team_id_to_manager_map(year: int) -> dict[str, dict]:
    """{team_id: {manager_id, display_name, team_name}} for one season -
    team_id is only stable WITHIN a season (a manager's team_id can differ
    year to year), so this is deliberately re-derived per year rather than
    cached globally like build_manager_color_map."""
    metadata = load_metadata(year)
    return {
        team["team_id"]: {
            "manager_id": team["manager_id"],
            "display_name": team["manager_display_name"],
            "team_name": team["team_name"],
        }
        for team in metadata["teams"]
    }


@st.cache_resource
def load_playoffs(year: int) -> dict | None:
    path = PARSED_DIRECTORY / str(year) / "playoffs.json"
    if not path.exists():
        return None
    return _read_json(path)


def _week_label_to_number(week_label: str) -> int:
    return int(week_label.removeprefix("Week ").strip())


@st.cache_resource
def matchup_type_map(year: int) -> dict[tuple[int, frozenset], str]:
    """{(week, frozenset({team_id_home, team_id_away})): "championship" or
    "consolation"} built from playoffs.json's two brackets - matched by
    week + the pair of team_ids involved (not by which side is home/away,
    since the bracket page and the gamecenter matchup page don't
    necessarily agree on that). Any matchup not present in this map is a
    regular-season game."""
    playoffs = load_playoffs(year)
    if not playoffs:
        return {}

    result: dict[tuple[int, frozenset], str] = {}
    for bracket_key, matchup_type in (("championship_bracket", "championship"), ("consolation_bracket", "consolation")):
        for round_entry in playoffs.get(bracket_key, {}).get("rounds", []):
            week = _week_label_to_number(round_entry["round_name"])
            for game in round_entry["matchups"]:
                if game.get("is_bye"):
                    continue
                result[(week, frozenset({game["team_id_home"], game["team_id_away"]}))] = matchup_type
    return result


@st.cache_resource
def _load_all_matchups_enriched() -> list[dict]:
    """Reads every season's archive/parsed/{year}/matchups/*.json exactly
    once and caches the full result - takes no arguments, so Streamlit
    caches a single result for the app's lifetime rather than re-scanning
    disk for every distinct filter combination load_matchups() gets
    called with. Each matchup is enriched with manager_id/display_name/
    team_name on both its home and away sides, plus a "matchup_type" of
    "regular"/"championship"/"consolation", sorted by (season, week)."""
    matchups = []
    for year in discover_seasons():
        matchups_directory = PARSED_DIRECTORY / str(year) / "matchups"
        if not matchups_directory.exists():
            continue
        manager_by_team_id = team_id_to_manager_map(year)
        type_by_week_and_teams = matchup_type_map(year)

        for matchup_path in matchups_directory.glob("week_*.json"):
            matchup = _read_json(matchup_path)
            home_info = manager_by_team_id.get(matchup["home"]["team_id"], {})
            away_info = manager_by_team_id.get(matchup["away"]["team_id"], {})

            matchup["home"].update(
                manager_id=home_info.get("manager_id", ""), display_name=home_info.get("display_name", ""), team_name=home_info.get("team_name", "")
            )
            matchup["away"].update(
                manager_id=away_info.get("manager_id", ""), display_name=away_info.get("display_name", ""), team_name=away_info.get("team_name", "")
            )
            matchup["matchup_type"] = type_by_week_and_teams.get(
                (matchup["week"], frozenset({matchup["home"]["team_id"], matchup["away"]["team_id"]})), "regular"
            )
            matchups.append(matchup)

    matchups.sort(key=lambda matchup: (matchup["season"], matchup["week"]))
    return matchups


def load_matchups(
    season: int | None,
    week: int | None,
    team1_manager_id: str | None,
    team2_manager_id: str | None,
    matchup_type: str | None,
) -> list[dict]:
    """Filters the single cached full-archive matchup list in memory - no
    file I/O here at all, since _load_all_matchups_enriched() already did
    it once for the whole app lifetime."""
    matchups = []
    for matchup in _load_all_matchups_enriched():
        if season and matchup["season"] != season:
            continue
        if week and matchup["week"] != week:
            continue
        home_manager_id = matchup["home"]["manager_id"]
        away_manager_id = matchup["away"]["manager_id"]
        if team1_manager_id and team1_manager_id not in (home_manager_id, away_manager_id):
            continue
        if team2_manager_id and team2_manager_id not in (home_manager_id, away_manager_id):
            continue
        if matchup_type and matchup_type != "all" and matchup["matchup_type"] != matchup_type:
            continue
        matchups.append(matchup)

    return matchups


def contrasting_text_color(hex_color: str) -> str:
    """Black or white text, whichever contrasts better against the given
    hex background - standard relative-luminance threshold (WCAG-ish
    approximation, not a full contrast-ratio computation, which is
    overkill for a two-choice text color decision)."""
    hex_color = hex_color.lstrip("#")
    red, green, blue = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    luminance = 0.299 * red + 0.587 * green + 0.114 * blue
    return "#000000" if luminance > 150 else "#FFFFFF"
