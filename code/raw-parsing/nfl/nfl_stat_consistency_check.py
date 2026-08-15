"""Offline data-quality check (Phase 4 of the NFL-stats backfill plan,
2026-08-14): compares this league's own fantasy box score
(archive/player_ownership.json's stat_N values) against the newer ESPN
NFL stats backfill (archive/nfl_player_stats.json) for every week where
BOTH sources have real data for the same player, and buckets every
comparable (player, week, stat) triple into exactly one of:

  - MATCH: both sources have a value for this stat, and they agree
    once each is rounded to 0 decimals - this league's own box score
    only ever records whole-number single-game stats (confirmed
    2026-08-14), so a rounding difference beyond that is a real
    disagreement, not float noise. ALSO counted as a match (not
    missing - see below): one side is None (omitted) and the other is
    an explicit 0, since this league's own box score omits a stat_N
    entirely when nothing happened that game (e.g. 0 sacks), while ESPN
    always reports the field explicitly, even as 0 - None and 0 are the
    same real-world value here, just represented differently.
  - MISSING: one source has a value for this stat that week and the
    other has no value at all, and it ISN'T the None-vs-0 case above -
    e.g. ESPN has a real nonzero passingYards figure but this league's
    box score has no stat_5 entry at all that week.
  - MISMATCH: both sources have a value, but they disagree after
    rounding - a real data-quality issue worth investigating.

Only stat_N ids with a confirmed ESPN field mapping are compared (DEF
players are skipped entirely - no NFL-stat backfill exists for team
defenses at all, see nfl_player_id_map.py's own DEF exclusion). A week
with no ESPN backfill at all (not yet fetched, or a genuine gap like
Justin Tucker's - see 2026-08-14 investigation) is skipped outright,
not counted as "missing" for every stat - that would conflate "this
whole week isn't backfilled yet" with "this one specific field is
absent," which are very different situations.

NOTE on duplication: STAT_ID_TO_ESPN_FIELD/STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD
below are a deliberate copy of frontend/data_loader.py's own constants
of the same name, not imported directly - this script (like every other
code/raw-parsing/ script) has no streamlit/frontend dependency. Keep
both copies in sync if the mapping ever changes.

Output: archive/progress/nfl_stat_consistency_report.json (full
missing/mismatch record detail, keyed by category) plus a console
summary of the three counts.

Usage:
    python nfl_stat_consistency_check.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import ARCHIVE_DIRECTORY, PROGRESS_DIRECTORY, write_json

PLAYER_OWNERSHIP_PATH = ARCHIVE_DIRECTORY / "player_ownership.json"
NFL_PLAYER_STATS_PATH = ARCHIVE_DIRECTORY / "nfl_player_stats.json"
REPORT_OUTPUT_PATH = PROGRESS_DIRECTORY / "nfl_stat_consistency_report.json"

# --- mirrored from frontend/data_loader.py's STAT_ID_TO_ESPN_FIELD /
# STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD - keep both copies in sync ---
STAT_ID_TO_ESPN_FIELD = {
    "stat_5": "passingYards",
    "stat_6": "passingTouchdowns",
    "stat_7": "interceptions",
    "stat_14": "rushingYards",
    "stat_15": "rushingTouchdowns",
    "stat_21": "receivingYards",
    "stat_22": "receivingTouchdowns",
    "stat_30": "fumblesLost",
    "stat_45": "sacks",
}
STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD = {
    "stat_33": "extraPointsMade-extraPointAttempts",
    "stat_35": "fieldGoalsMade1_19-fieldGoalAttempts1_19",
    "stat_36": "fieldGoalsMade20_29-fieldGoalAttempts20_29",
    "stat_37": "fieldGoalsMade30_39-fieldGoalAttempts30_39",
    "stat_38": "fieldGoalsMade40_49-fieldGoalAttempts40_49",
    "stat_39": "fieldGoalsMade50-fieldGoalAttempts50",
}
COMPARABLE_STAT_IDS = sorted(set(STAT_ID_TO_ESPN_FIELD) | set(STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD))
# --- end mirror ---


def _espn_made_attempted_count(raw_value: str | None) -> int | None:
    if not raw_value or "-" not in raw_value:
        return None
    made, _, _attempted = raw_value.partition("-")
    try:
        return int(made)
    except ValueError:
        return None


def _espn_stat_value(stat_id: str, espn_week_stats: dict) -> int | None:
    direct_field = STAT_ID_TO_ESPN_FIELD.get(stat_id)
    if direct_field:
        raw_value = espn_week_stats.get(direct_field)
        if raw_value is None:
            return None
        try:
            return round(float(raw_value))
        except ValueError:
            return None

    made_attempted_field = STAT_ID_TO_ESPN_MADE_ATTEMPTED_FIELD.get(stat_id)
    if made_attempted_field:
        return _espn_made_attempted_count(espn_week_stats.get(made_attempted_field))

    return None


def _fantasy_stat_value(raw_value) -> int | None:
    if raw_value is None:
        return None
    try:
        return round(float(raw_value))
    except (TypeError, ValueError):
        return None


def check_consistency(player_ownership: dict, nfl_player_stats: dict) -> dict:
    match_count = 0
    missing_records: list[dict] = []
    mismatch_records: list[dict] = []

    for player_id, entries in player_ownership.items():
        espn_entry = nfl_player_stats.get(player_id)
        if not espn_entry or espn_entry.get("position") == "DEF":
            continue

        for entry in entries:
            season, week = entry["season"], entry["week"]
            espn_week = espn_entry.get("seasons", {}).get(str(season), {}).get("weeks", {}).get(str(week))
            if not espn_week:
                continue  # whole week not backfilled (or a genuine ESPN gap) - not a per-stat comparison at all

            espn_week_stats = espn_week["stats"]
            fantasy_stats = entry.get("stats", {})

            for stat_id in COMPARABLE_STAT_IDS:
                fantasy_value = _fantasy_stat_value(fantasy_stats.get(stat_id))
                espn_value = _espn_stat_value(stat_id, espn_week_stats)

                if fantasy_value is None and espn_value is None:
                    continue  # neither source has this stat this week - not applicable

                # This league's own box score omits a stat_N entirely
                # when nothing happened (e.g. 0 sacks that game), while
                # ESPN always reports the field explicitly, even as 0 -
                # None (omitted) and 0 (explicit) are semantically the
                # SAME real-world value, not a "missing" gap, so they're
                # counted as a match rather than flagged.
                if (fantasy_value is None and espn_value == 0) or (espn_value is None and fantasy_value == 0):
                    match_count += 1
                    continue

                record = {
                    "player_id": player_id,
                    "name": espn_entry.get("name", ""),
                    "season": season,
                    "week": week,
                    "stat_id": stat_id,
                    "fantasy_value": fantasy_value,
                    "espn_value": espn_value,
                }
                if fantasy_value is None or espn_value is None:
                    missing_records.append(record)
                elif fantasy_value == espn_value:
                    match_count += 1
                else:
                    mismatch_records.append(record)

    return {
        "match_count": match_count,
        "missing_count": len(missing_records),
        "mismatch_count": len(mismatch_records),
        "missing_records": missing_records,
        "mismatch_records": mismatch_records,
    }


def main() -> None:
    player_ownership = json.loads(PLAYER_OWNERSHIP_PATH.read_text())["player_ownership"]
    nfl_player_stats = json.loads(NFL_PLAYER_STATS_PATH.read_text())

    report = check_consistency(player_ownership, nfl_player_stats)

    write_json(REPORT_OUTPUT_PATH, report)
    print(f"Matches: {report['match_count']}")
    print(f"Missing (one source has no value for a comparable stat): {report['missing_count']}")
    print(f"Mismatches (both present, disagree after rounding): {report['mismatch_count']}")
    print(f"wrote {REPORT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
