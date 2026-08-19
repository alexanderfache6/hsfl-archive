"""
Reads the committed archive/*.json output directly - no database, no
API calls. See execution-plan.md Phase G for the architecture (data is
fetched/parsed/aggregated offline and committed to the repo; the
frontend is a pure read-only view over those static files).
"""

# ========================================
# IMPORTS
# ========================================

import base64
import json
import re
import sys
from pathlib import Path

import streamlit as st
from colors import COLOR_BLACK, COLOR_PALETTE_PAIRED, COLOR_WHITE

# ========================================
# CONSTANTS
# ========================================

PROJECT_ROOT_DIRECTORY = Path(__file__).resolve().parent.parent
ARCHIVE_DIRECTORY = PROJECT_ROOT_DIRECTORY / "archive"
AGGREGATED_DIRECTORY = ARCHIVE_DIRECTORY / "aggregated"
PARSED_DIRECTORY = ARCHIVE_DIRECTORY / "parsed"

# Reuses code/stats-aggregation's own optimal-lineup solver (the same
# formula behind best_coaching_season/worst_coaching_season) instead of
# reimplementing it here, so the Matchups tab's optimal-lineup column can
# never drift out of sync with the backend's own coaching-efficiency math.
STATS_AGGREGATION_DIRECTORY = PROJECT_ROOT_DIRECTORY / "code" / "stats-aggregation"
if str(STATS_AGGREGATION_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(STATS_AGGREGATION_DIRECTORY))
from optimal_lineup import FLEX_ELIGIBLE_POSITIONS, solve_optimal_lineup

# stat_N -> the scoring_rules key (in archive/parsed/{year}/metadata.json)
# it's scored under. Most map to their own obviously-named rule; a few
# notes on the non-obvious ones, confirmed against every season's
# scoring_rules (2012-2025, all identical in structure/key names):
#   - stat_34 (PAT Miss) and stat_40-44 (FG Miss by distance) have no
#     rule at all - misses simply aren't scored, so they're 0 points.
#   - stat_45/46/47 (Sck/Int/Fum on a DEF entry) map to the TEAM defense
#     rules ("Sacks"/"Interceptions"/"Fumbles Recovered"), not the
#     IDP-specific "Defense Interception"/"Forced Fumble"/"Fumbles
#     Recovery" rules (stat_72/73/75) - this league's DEF roster slot is
#     a team defense, not an individual defender, except in 2012 which
#     used real IDP scoring (stat_70-78) for actual individual players.
#   - stat_54 ("Pts") on a DEF entry is POINTS ALLOWED that game, not a
#     fantasy point value - it's scored via the tiered "Points Allowed
#     0/1-6/7-13/.../35+" rules, handled specially in
#     compute_stat_fantasy_points() rather than this flat table.
STAT_ID_TO_SCORING_RULE = {
    "stat_5": "Passing Yards",
    "stat_6": "Passing Touchdowns",
    "stat_7": "Interceptions Thrown",
    "stat_14": "Rushing Yards",
    "stat_15": "Rushing Touchdowns",
    "stat_21": "Receiving Yards",
    "stat_22": "Receiving Touchdowns",
    "stat_30": "Fumbles Lost",
    "stat_32": "2-Point Conversions",
    "stat_33": "PAT Made",
    "stat_35": "FG Made 0-19",
    "stat_36": "FG Made 20-29",
    "stat_37": "FG Made 30-39",
    "stat_38": "FG Made 40-49",
    "stat_39": "FG Made 50+",
    "stat_45": "Sacks",
    "stat_46": "Interceptions",
    "stat_47": "Fumbles Recovered",
    "stat_49": "Safeties",
    "stat_50": "Touchdowns",
    "stat_53": "Kickoff and Punt Return Touchdowns",
    "stat_70": None,  # Tack(le) - not scored in this league's rule set
    "stat_71": None,  # Ast(ist) - not scored
    "stat_72": "Sacks",
    "stat_73": "Defense Interception",
    "stat_74": "Forced Fumble",
    "stat_75": "Fumbles Recovery",
    "stat_76": "Touchdown (Interception return)",
    "stat_77": "Touchdown (Fumble return)",
    "stat_78": "Touchdown (Blocked kick)",
}

# stat_N -> ESPN gamelog field name (archive/nfl_player_stats.json's own
# "stats" dict keys, from code/raw-parsing/nfl/nfl_player_stats.py) - a
# DIRECT single-value field, comparable as-is against this league's own
# stat_N raw value. Confirmed 2026-08-14 against a real downloaded 2012
# season (QB/RB/WR/TE/K categories only - individual DB players' own
# ESPN category ("defensive") was never actually sampled in that pull,
# since no DB player had 2012 data resolved yet). None = no ESPN field
# available at all for this stat_N in the categories confirmed so far -
# either genuinely not itemized by ESPN (stat_32 2-Point Conversions),
# or DB-only/defensive stats (46/47/49/72/73/74/75/76/77/78) whose real
# ESPN field names are still UNCONFIRMED, not verified to not exist -
# revisit once a DB player's own gamelog response has actually been
# inspected live, rather than guessing names into this table now.
STAT_ID_TO_ESPN_FIELD = {
    "stat_5": "passingYards",
    "stat_6": "passingTouchdowns",
    "stat_7": "interceptions",
    "stat_14": "rushingYards",
    "stat_15": "rushingTouchdowns",
    "stat_21": "receivingYards",
    "stat_22": "receivingTouchdowns",
    "stat_30": "fumblesLost",
    "stat_32": None,  # 2-Point Conversions - not itemized in the sampled ESPN categories
    "stat_45": "sacks",  # QB's own sacks-taken, not a defensive sack
    "stat_46": None,  # Interceptions (defense) - DB category unconfirmed
    "stat_47": None,  # Fumbles Recovered - DB/DEF category unconfirmed
    "stat_49": None,  # Safeties - DB/DEF category unconfirmed
    "stat_50": None,  # Touchdowns (general) - meaning ambiguous, not itemized in sampled categories
    "stat_53": None,  # Kickoff/Punt Return TDs - return stats not itemized in sampled categories
    "stat_70": None,  # Tack(le) - not scored in this league's rule set (see STAT_ID_TO_SCORING_RULE)
    "stat_71": None,  # Ast(ist) - not scored
    "stat_72": None,  # Sacks (defense) - DB/DEF category unconfirmed
    "stat_73": None,  # Defense Interception - DB/DEF category unconfirmed
    "stat_74": None,  # Forced Fumble - DB/DEF category unconfirmed
    "stat_75": None,  # Fumbles Recovery - DB/DEF category unconfirmed
    "stat_76": None,  # Touchdown (Interception return) - DB/DEF category unconfirmed
    "stat_77": None,  # Touchdown (Fumble return) - DB/DEF category unconfirmed
    "stat_78": None,  # Touchdown (Blocked kick) - DB/DEF category unconfirmed
}

# stat_N -> ESPN gamelog field name for kicking stats, where ESPN reports
# a single "{made}-{attempted}" string (e.g. "3-3") instead of a bare
# made count - see _espn_made_attempted_count() below for the parser.
# Confirmed 2026-08-14 against real downloaded 2012 K data.
STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD = {
    "stat_33": "extraPointsMade-extraPointAttempts",
    "stat_35": "fieldGoalsMade1_19-fieldGoalAttempts1_19",
    "stat_36": "fieldGoalsMade20_29-fieldGoalAttempts20_29",
    "stat_37": "fieldGoalsMade30_39-fieldGoalAttempts30_39",
    "stat_38": "fieldGoalsMade40_49-fieldGoalAttempts40_49",
    "stat_39": "fieldGoalsMade50-fieldGoalAttempts50",
}


def _espn_made_attempted_count(raw_value: str | None) -> int | None:
    """ "3-3" -> 3 (the MADE count, left of the dash) - None if the field
    is missing or not in the expected "{made}-{attempted}" shape."""
    if not raw_value or "-" not in raw_value:
        return None
    made, _, _attempted = raw_value.partition("-")
    try:
        return int(made)
    except ValueError:
        return None


def espn_stat_value(stat_id: str, espn_week_stats: dict) -> int | None:
    """This week's ESPN value for a fantasy stat_N, as an int - via
    STAT_ID_TO_ESPN_FIELD's direct field, or
    STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD's parsed made-count for kicking
    stats. None if stat_id has no known ESPN mapping yet, or the field is
    genuinely absent from this week's ESPN data (e.g. a QB with no field
    goal attempts simply has no fieldGoalsMade... key that week)."""
    direct_field = STAT_ID_TO_ESPN_FIELD.get(stat_id)
    if direct_field:
        raw_value = espn_week_stats.get(direct_field)
        if raw_value is None:
            return None
        try:
            return int(float(raw_value))
        except ValueError:
            return None

    made_attempted_field = STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD.get(stat_id)
    if made_attempted_field:
        return _espn_made_attempted_count(espn_week_stats.get(made_attempted_field))

    return None


# ESPN field name -> stat_N, the inverse of STAT_ID_TO_ESPN_FIELD /
# STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD - 1:1 in both source dicts, so
# inversion is safe. Used by the "Select NFL Stat to View" chart to know
# whether a selected ESPN-native field (e.g. "rushingYards") has a
# fantasy stat_N counterpart worth cross-checking for a mismatch at all
# - most of NFL_STAT_FIELDS_BY_POSITION's fields (completions, targets,
# per-attempt averages, "FG Made (Total)", "Total Kicking Points") have
# NO stat_N equivalent, so they're simply absent from this map.
ESPN_FIELD_TO_STAT_ID = {field: stat_id for stat_id, field in STAT_ID_TO_ESPN_FIELD.items() if field} | {field: stat_id for stat_id, field in STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD.items()}


def fantasy_raw_stat_value(stat_id: str, entry_stats: dict) -> int | None:
    """This league's own box-score value for a stat_N, as an int -
    same rounding convention as espn_stat_value() above, so the two are
    directly comparable. None if this stat_N wasn't recorded that week
    (this league's box score omits a stat_N entirely rather than storing
    an explicit 0 - see code/raw-parsing/nfl/nfl_stat_consistency_check.py)."""
    raw_value = entry_stats.get(stat_id)
    if raw_value is None:
        return None
    try:
        return round(float(raw_value))
    except (TypeError, ValueError):
        return None


# Curated per-position ESPN field list for the Players page's "Select
# NFL Stat to View" chart (frontend/pages_players.py) - user-specified
# 2026-08-14, sourced directly from archive/nfl_player_stats.json's own
# field names (NOT limited to this league's fantasy-scored stat_N set -
# e.g. "completions"/"receivingTargets"/the "yardsPer..." per-attempt
# averages have no stat_N equivalent at all, since this league's own box
# score never itemized them). DEF is intentionally absent - no NFL-stat
# backfill exists for team defenses yet.
# RB/WR/TE all share the identical skill-position field list below - RB
# and WR come from optimal_lineup.py's own FLEX_ELIGIBLE_POSITIONS (the
# two positions this league's FLEX roster slot accepts); TE is added on
# top of that set for THIS field list specifically (a pass-catcher/
# rusher stat shape, not a flex-roster-eligibility claim - TE itself is
# NOT flex-eligible in this league's own scoring rules).
_SKILL_POSITION_NFL_STAT_FIELDS = [
    "rushingAttempts",
    "rushingYards",
    "yardsPerRushAttempt",
    "rushingTouchdowns",
    "receptions",
    "receivingTargets",
    "receivingYards",
    "yardsPerReception",
    "receivingTouchdowns",
    "fumbles",
    "fumblesLost",
]

NFL_STAT_FIELDS_BY_POSITION = {
    "QB": [
        "completions",
        "passingAttempts",
        "passingYards",
        "completionPct",
        "yardsPerPassAttempt",
        "passingTouchdowns",
        "interceptions",
        "rushingAttempts",
        "rushingYards",
        "yardsPerRushAttempt",
        "rushingTouchdowns",
    ],
    **{position: _SKILL_POSITION_NFL_STAT_FIELDS for position in FLEX_ELIGIBLE_POSITIONS | {"TE"}},
    "K": [
        "fieldGoalsMade1_19-fieldGoalAttempts1_19",
        "fieldGoalsMade20_29-fieldGoalAttempts20_29",
        "fieldGoalsMade30_39-fieldGoalAttempts30_39",
        "fieldGoalsMade40_49-fieldGoalAttempts40_49",
        "fieldGoalsMade50-fieldGoalAttempts50",
        "fieldGoalsMade-fieldGoalAttempts",
        "extraPointsMade-extraPointAttempts",
        "totalKickingPoints",
    ],
}

NFL_STAT_FIELD_LABELS = {
    "completions": "Completions",
    "passingAttempts": "Passing Attempts",
    "passingYards": "Passing Yards",
    "completionPct": "Completion %",
    "yardsPerPassAttempt": "Yards Per Pass Attempt",
    "passingTouchdowns": "Passing TDs",
    "interceptions": "Interceptions",
    "rushingAttempts": "Rushing Attempts",
    "rushingYards": "Rushing Yards",
    "yardsPerRushAttempt": "Yards Per Rush Attempt",
    "rushingTouchdowns": "Rushing TDs",
    "receptions": "Receptions",
    "receivingTargets": "Receiving Targets",
    "receivingYards": "Receiving Yards",
    "yardsPerReception": "Yards Per Reception",
    "receivingTouchdowns": "Receiving TDs",
    "fumbles": "Fumbles",
    "fumblesLost": "Fumbles Lost",
    "fieldGoalsMade1_19-fieldGoalAttempts1_19": "FG Made 0-19",
    "fieldGoalsMade20_29-fieldGoalAttempts20_29": "FG Made 20-29",
    "fieldGoalsMade30_39-fieldGoalAttempts30_39": "FG Made 30-39",
    "fieldGoalsMade40_49-fieldGoalAttempts40_49": "FG Made 40-49",
    "fieldGoalsMade50-fieldGoalAttempts50": "FG Made 50+",
    "fieldGoalsMade-fieldGoalAttempts": "FG Made (Total)",
    "extraPointsMade-extraPointAttempts": "PAT Made",
    "totalKickingPoints": "Total Kicking Points",
}

# Chart y-axis treatment, same idea as pages_players.py's own
# YARDAGE_STAT_LABELS/forced-integer-dtick split for the fantasy stat_N
# chart - genuinely fractional fields (percentages, per-attempt
# averages) and yardage fields (which can run into the hundreds) both
# get the auto-scaling nticks axis; every other field here is a small
# whole-number count that gets a forced integer-only dtick instead.
NFL_STAT_FRACTIONAL_FIELDS = {"completionPct", "yardsPerPassAttempt", "yardsPerRushAttempt", "yardsPerReception"}
NFL_STAT_YARDAGE_FIELDS = {"passingYards", "rushingYards", "receivingYards"}

# Fields reported as a 0-100 percentage - the chart pins the y-axis to
# the full 0-100 range for these instead of auto-scaling to the data.
NFL_STAT_PERCENTAGE_FIELDS = {"completionPct"}

# Fields ESPN reports as a single "{made}-{attempted}" string (parsed via
# _espn_made_attempted_count) rather than a bare number - every "FG
# Made ..."/"PAT Made" entry in NFL_STAT_FIELDS_BY_POSITION["K"] above,
# not "totalKickingPoints" (a plain int).
NFL_STAT_MADE_ATTEMPTED_FIELDS = {
    "fieldGoalsMade1_19-fieldGoalAttempts1_19",
    "fieldGoalsMade20_29-fieldGoalAttempts20_29",
    "fieldGoalsMade30_39-fieldGoalAttempts30_39",
    "fieldGoalsMade40_49-fieldGoalAttempts40_49",
    "fieldGoalsMade50-fieldGoalAttempts50",
    "fieldGoalsMade-fieldGoalAttempts",
    "extraPointsMade-extraPointAttempts",
}


def nfl_stat_field_value(field: str, espn_week_stats: dict) -> float | None:
    """This week's ESPN value for a NFL_STAT_FIELDS_BY_POSITION field -
    a made-count (int) for NFL_STAT_MADE_ATTEMPTED_FIELDS, else the raw
    field parsed as a float (some of these ARE genuinely fractional -
    completionPct, yardsPerRushAttempt/yardsPerReception - unlike
    espn_stat_value()'s int-only fantasy stat_N counterparts above).
    None if the field is missing, or ESPN's own "-" placeholder for an
    undefined average (e.g. 0 attempts that week)."""
    if field in NFL_STAT_MADE_ATTEMPTED_FIELDS:
        return _espn_made_attempted_count(espn_week_stats.get(field))

    raw_value = espn_week_stats.get(field)
    if raw_value is None or raw_value == "-":
        return None
    try:
        return float(raw_value)
    except ValueError:
        return None


def get_espn_week_stats(player_id: str, season: int, week: int, nfl_player_stats: dict) -> dict | None:
    """This player's ESPN "stats" dict for one real NFL week, or None if
    unavailable (unresolved ESPN id, that season not yet backfilled, or
    a genuine bye/no-game week)."""
    player_entry = nfl_player_stats.get(player_id)
    if not player_entry:
        return None
    week_entry = player_entry.get("seasons", {}).get(str(season), {}).get("weeks", {}).get(str(week))
    return week_entry["stats"] if week_entry else None


# (points, allows tiers below) for the "Points Allowed" ladder - checked
# in order, first matching upper bound wins. stat_54 on a DEF entry only.
POINTS_ALLOWED_TIERS = [
    (0, "Points Allowed 0"),
    (6, "Points Allowed 1-6"),
    (13, "Points Allowed 7-13"),
    (20, "Points Allowed 14-20"),
    (27, "Points Allowed 21-27"),
    (34, "Points Allowed 28-34"),
]
POINTS_ALLOWED_TOP_TIER = "Points Allowed 35+"

# roster_settings key -> the literal "slot" value matchup data uses for
# it - most positions match their own settings key (QB/RB/WR/TE/K/DEF),
# but the flex slot is always recorded as "W/R" in the archived data
# regardless of season, and 2012's IDP flex-adjacent slot ("Defensive
# Back" in roster_settings) is recorded as "DB". Confirmed by scanning
# every season's roster_settings and a sample matchup file per year -
# these are the only two that don't match their own settings key.
ROSTER_SETTINGS_KEY_TO_SLOT = {"FLEX": "W/R", "Defensive Back": "DB"}
NON_STARTING_ROSTER_SETTINGS_KEYS = {"BENCH", "RESERVE"}

# Shared across every Plotly chart in the app - caps how many gridlines/
# tick labels can appear on an axis before Plotly starts thinning them,
# so a chart with lots of data points (many weeks, many transaction
# dates, etc) never clogs up with overlapping labels.
CHART_YAXIS_MAX_TICKS = 10
CHART_XAXIS_MAX_TICKS = 20

# This archive's own nfl_team abbreviations (e.g. matchup data's
# "nfl_team": "WAS") -> the lowercase abbreviation
# code/raw-parsing/nfl/nfl_bye_weeks.json is keyed by (ESPN's team-page
# URL slug). Every other team's code is identical once lowercased -
# confirmed by diffing this archive's DEF_TEAM_ABBREVIATIONS values
# against nfl_bye_weeks.json's full team list - Washington is the only
# real mismatch (ESPN uses "wsh", this archive uses "WAS").
NFL_TEAM_TO_ESPN_ABBR = {"WAS": "wsh"}

# ========================================
# FUNCTIONS
# ========================================


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
def load_transactions(year: int) -> dict:
    return _read_json(PARSED_DIRECTORY / str(year) / "transactions.json")


@st.cache_resource
def load_draft(year: int) -> dict | None:
    """{"season", "draft_type" ("snake"/"auction"), "picks": [{"overall_pick",
    "player_id", "player_name", "position", "nfl_team", "team_id",
    "auction_amount"}], "notes"} - auction_amount is null for every pick
    in a snake draft, and for keeper picks in an auction draft (no live
    bid took place - see the file's own "notes" field)."""
    path = PARSED_DIRECTORY / str(year) / "draft.json"
    if not path.exists():
        return None
    return _read_json(path)


@st.cache_resource
def load_post_season_stats(year: int) -> dict | None:
    path = AGGREGATED_DIRECTORY / str(year) / "post_season_stats.json"
    if not path.exists():
        return None
    return _read_json(path)


@st.cache_resource
def _team_logo_paths(year: int) -> dict[str, Path]:
    """{team_id: local logo image path for this season}, sourced from
    archive/managers.json's per-manager, per-season logo_path field (a
    manager's logo can change season to season, so this is keyed by
    year, not looked up once for all time)."""
    managers = _read_json(ARCHIVE_DIRECTORY / "managers.json")["managers"]
    paths = {}
    for manager in managers:
        for season_entry in manager["seasons"]:
            if season_entry["season"] == year and season_entry.get("logo_path"):
                paths[season_entry["team_id"]] = ARCHIVE_DIRECTORY / season_entry["logo_path"]
    return paths


@st.cache_resource
def load_team_logo_data_uri(year: int, team_id: str) -> str | None:
    """A ready-to-embed data: URI for this team's logo, or None if no
    logo is on file for that season - embedding as base64 (rather than a
    file:// path or a relative URL) is what lets it drop straight into a
    raw HTML <img> tag anywhere in the app regardless of how/where
    Streamlit is serving from."""
    path = _team_logo_paths(year).get(team_id)
    if not path or not path.exists():
        return None
    mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime_type};base64,{encoded}"


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
    return {manager_id: COLOR_PALETTE_PAIRED[index % len(COLOR_PALETTE_PAIRED)] for index, manager_id in enumerate(manager_ids)}


@st.cache_resource
def load_players() -> dict:
    return _read_json(ARCHIVE_DIRECTORY / "players.json")


@st.cache_resource
def load_player_ownership() -> dict:
    return _read_json(ARCHIVE_DIRECTORY / "player_ownership.json")


@st.cache_resource
def load_nfl_player_stats() -> dict:
    """{"<player_id>": {"espn_id", "name", "position", "seasons": {"2018":
    {"weeks": {"3": {"team", "opponent", "result", "stats": {...}}}}}}} -
    real per-week NFL stats from ESPN (see code/raw-parsing/nfl/
    nfl_player_stats.py), keyed by the SAME fantasy player_id as
    players.json/player_ownership.json (nfl_player_stats.py builds it
    that way directly - no separate espn_id hop needed here)."""
    return _read_json(ARCHIVE_DIRECTORY / "nfl_player_stats.json")


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


def _parse_scoring_rule(rule_text: str) -> tuple[float, float]:
    """ "4 points" -> (4.0, 1.0); "1 point per 25 yards" -> (1.0, 25.0);
    "-2 points" -> (-2.0, 1.0). fantasy_points = value * points / per."""
    match = re.match(r"(-?[\d.]+)\s*points?(?:\s*per\s*([\d.]+)\s*yards?)?", rule_text.strip(), re.IGNORECASE)
    if not match:
        return (0.0, 1.0)
    points = float(match.group(1))
    per = float(match.group(2)) if match.group(2) else 1.0
    return (points, per)


def compute_stat_fantasy_points(stat_id: str, raw_value: str, position: str, year: int) -> float | None:
    """Fantasy points this one stat line contributed, or None if this
    stat isn't scored at all (e.g. a missed FG) or isn't computable (no
    known rule mapping). NOTE: this is NOT guaranteed to sum to the
    player's actual total points for the week - some scoring components
    (e.g. PPR reception-count bonuses) aren't captured as their own
    stat_N in the archived box score data at all, so they can't be
    itemized here."""
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    scoring_rules = load_metadata(year)["scoring_rules"]

    if stat_id == "stat_54" and position == "DEF":
        for upper_bound, tier_key in POINTS_ALLOWED_TIERS:  # DEF points allowed
            if value <= upper_bound:
                rule_key = tier_key
                break
        else:
            rule_key = POINTS_ALLOWED_TOP_TIER
        points, per = _parse_scoring_rule(scoring_rules.get(rule_key, "0 points"))
        return points  # tiered rules are flat, not per-unit

    rule_key = STAT_ID_TO_SCORING_RULE.get(stat_id)
    if rule_key is None or rule_key not in scoring_rules:
        return None

    points, per = _parse_scoring_rule(scoring_rules[rule_key])
    return round(value * points / per, 2)


@st.cache_resource
def load_nfl_season_lengths() -> dict[str, int]:
    """{"2012": 16, ..., "2021": 17, ...} - each year's real NFL
    regular-season game count (see archive/nfl_season_lengths.json's own
    "note" for the 16->17 game expansion in 2021 and why this is
    deliberately NOT the same number as this league's own fantasy
    regular-season week count)."""
    return _read_json(ARCHIVE_DIRECTORY / "nfl_season_lengths.json")["nfl_regular_season_games"]


@st.cache_resource
def load_nfl_bye_weeks() -> dict:
    """{"2022": {"status": "32 / 32", "teams": [{"team": "ne", "bye":
    10}, ...]}, ...} - see code/raw-parsing/nfl/nfl_bye_weeks.json's own
    docstring. A team entry's "bye" can be None (with a "comment"
    explaining why - e.g. 2017's Miami/Tampa Bay, whose Week 1 game was
    postponed by Hurricane Irma and made up later that season using what
    would've been their bye - genuinely no bye that year, not a fetch
    gap) - get_bye_week() below treats that the same as "no bye to
    mark," not "unknown"."""
    return _read_json(ARCHIVE_DIRECTORY / "nfl_bye_weeks.json")


def get_bye_week(season: int, nfl_team: str) -> int | None:
    """None covers both "not found" (e.g. a future season with no
    schedule out yet) and "found, but this team genuinely had no bye
    that season" - callers only care whether there's a week number to
    mark, not which of those two applies."""
    season_entry = load_nfl_bye_weeks().get(str(season))
    if not season_entry:
        return None
    espn_team = NFL_TEAM_TO_ESPN_ABBR.get(nfl_team, nfl_team.lower())
    for team_entry in season_entry["teams"]:
        if team_entry["team"] == espn_team:
            return team_entry["bye"]
    return None


@st.cache_resource
def player_nfl_team_by_season(player_id: str) -> dict[int, str]:
    """{season: nfl_team}, sourced from archive/nfl_player_stats.json's
    own per-week ESPN gamelog "team" field - NOT the fantasy matchup
    archive's own nfl_team field, which only reflects whichever team was
    current AT PARSE TIME, not the real historical team for that season
    (confirmed 2026-08-15: Aaron Rodgers's entire 2022 season was
    mislabeled "NYJ" - the team he joined in 2023 - throughout
    archive/parsed/2022/matchups/*.json, which fed NYJ's real week-10
    bye into _bye_weeks_by_season instead of GB's real week-14 bye).
    ESPN's own gamelog is a genuine historical record instead. A player
    with no resolved ESPN mapping, or no seasons in
    archive/nfl_player_stats.json, simply isn't a key here - callers
    treat that season as "unknown team, no bye to mark" rather than
    guessing, same contract as before. A player who changes NFL teams
    mid-season (rare) gets whichever team appears most often that
    season - a real, deliberately unhandled edge case, same as
    pages_players.py's "NFL Games" bye assumption."""
    from collections import Counter

    player_entry = load_nfl_player_stats().get(player_id)
    if not player_entry:
        return {}

    teams_by_season: dict[int, Counter] = {}
    for season_str, season_data in player_entry.get("seasons", {}).items():
        for week_data in season_data.get("weeks", {}).values():
            team = week_data.get("team")
            if not team:
                continue
            teams_by_season.setdefault(int(season_str), Counter())[team] += 1

    return {season: counts.most_common(1)[0][0] for season, counts in teams_by_season.items()}


@st.cache_resource
def load_metadata(year: int) -> dict:
    return _read_json(PARSED_DIRECTORY / str(year) / "metadata.json")


@st.cache_resource
def load_starting_slot_counts(year: int) -> dict[str, int]:
    """{slot: expected_count} for that season's STARTING lineup only
    (BENCH/RESERVE excluded) - e.g. {"QB": 1, "RB": 2, "WR": 2, "TE": 1,
    "W/R": 1, "K": 1, "DEF": 1} for a typical season. Used to detect a
    starting slot the user simply forgot to fill that week (fewer actual
    starters in a slot than the season's settings call for), as opposed
    to a bye/injury which still shows an actual (if low-scoring) player."""
    roster_settings = load_metadata(year)["settings"]["roster_settings"]
    return {ROSTER_SETTINGS_KEY_TO_SLOT.get(key, key): count for key, count in roster_settings.items() if key not in NON_STARTING_ROSTER_SETTINGS_KEYS}


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

            matchup["home"].update(manager_id=home_info.get("manager_id", ""), display_name=home_info.get("display_name", ""), team_name=home_info.get("team_name", ""))
            matchup["away"].update(manager_id=away_info.get("manager_id", ""), display_name=away_info.get("display_name", ""), team_name=away_info.get("team_name", ""))
            matchup["matchup_type"] = type_by_week_and_teams.get((matchup["week"], frozenset({matchup["home"]["team_id"], matchup["away"]["team_id"]})), "regular")
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
    return COLOR_BLACK if luminance > 150 else COLOR_WHITE
