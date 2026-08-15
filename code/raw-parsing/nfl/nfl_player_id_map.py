"""Maps this league's fantasy player_ids (players.json) to ESPN athlete
IDs via ESPN's public player-search endpoint - the first step toward
backfilling real NFL stats for weeks a player wasn't on a fantasy
roster (see instructions/cool-features.md's "players" section).

Only searches players who have actually been rostered at least once
(archive/player_ownership.json's own keys - players.json has 19 extra
draft-only entries never rostered, confirmed 2026-08-14) and excludes
team defenses (position == "DEF" - ESPN's per-athlete gamelog endpoint
is for individual players, not team defense units).

ESPN's search/v2 endpoint (https://site.web.api.espn.com/apis/search/v2
?query={name}) returns candidates across EVERY sport, not just NFL - a
"Justin Tucker" query returns the real NFL kicker plus two unrelated
college basketball players of the same name (confirmed 2026-08-14).
Candidates are filtered to sport == "football" and defaultLeagueSlug ==
"nfl" before anything else. The numeric ESPN athlete ID is NOT the
result's own "id"/"guid" field (that's a search-only GUID) - it's
embedded in the result's "uid" field (format "s:20~l:28~a:{athlete_id}").

Output: archive/nfl_player_id_map_to_review_original.json (NOT
archive/nfl_player_id_map.json - that filename is reserved for the
CONFIRMED, human-reviewed map; see below), keyed by fantasy player_id:
    {"<player_id>": {"name": ..., "position": ..., "espn_id": "4040715"
    or null, "status": "matched" | "ambiguous" | "unmatched" |
    "matched_manual", "candidates": [{"espn_id", "name", "team"}, ...]}}

"matched" = exactly one NFL/football candidate found automatically.
"ambiguous"/"unmatched" need human review, and are re-attempted (fresh
network fetch + re-parse) on every rerun, since a repeat automated
search is exactly as likely to newly resolve as a first attempt.
"matched_manual" is a status set on a player during manual review (see
nfl_player_id_map_review.py / nfl_player_id_map_review_check.py) -
treated as permanently resolved and never re-queried.

Full review workflow (see the two other nfl_player_id_map_*.py scripts
for the rest):
1. THIS script pulls a fresh full map -> nfl_player_id_map_to_review_original.json.
2. nfl_player_id_map_review.py prints the ambiguous ones and makes an
   editable copy, nfl_player_id_map_to_review.json.
3. You hand-edit that copy down to one candidate per ambiguous player.
4. nfl_player_id_map_review_check.py confirms no candidate mismatches
   remain, promotes each resolved entry to "matched_manual", and - once
   EVERY ambiguous player is resolved - renames that file to become the
   real archive/nfl_player_id_map.json, the one nfl_player_stats.py
   actually reads.

On a rerun, THIS script treats archive/nfl_player_id_map.json (the
confirmed, post-review file) as authoritative if it exists - a player
already resolved there is never re-queried, even if this run's own
fresh pull would otherwise re-flag it. If that confirmed file doesn't
exist yet (review not completed even once), it falls back to whatever
this script's own prior _to_review_original.json output already
resolved, so re-running mid-review doesn't lose automated "matched"
progress either.

Each player's raw search response is cached to
archive/raw/espn_player_search/{player_id}.json (idempotent via
already_fetched, same pattern as nfl_bye_weeks.py) so re-running this
script to pick up newly-rostered players doesn't re-query names already
searched. Errors go to the shared archive/progress/errors.log via
log_error.
"""

import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import (
    ARCHIVE_DIRECTORY,
    already_fetched,
    log_error,
    polite_sleep,
    write_json,
    write_raw,
)

ESPN_SEARCH_URL = "https://site.web.api.espn.com/apis/search/v2"

PLAYERS_PATH = ARCHIVE_DIRECTORY / "players.json"
PLAYER_OWNERSHIP_PATH = ARCHIVE_DIRECTORY / "player_ownership.json"
# The confirmed, post-review map (only ever written by
# nfl_player_id_map_review_check.py's rename step) - authoritative for
# skipping already-resolved players on a rerun, but never written here.
CONFIRMED_ID_MAP_PATH = ARCHIVE_DIRECTORY / "nfl_player_id_map.json"
# THIS script's own output - a fresh full pull, not yet human-reviewed.
TO_REVIEW_ORIGINAL_PATH = ARCHIVE_DIRECTORY / "nfl_player_id_map_to_review_original.json"
SEARCH_RAW_DIRECTORY = ARCHIVE_DIRECTORY / "raw" / "espn_player_search"

# "s:20~l:28~a:4040715" -> "4040715" (the trailing "a:{id}" segment).
UID_ATHLETE_ID_PATTERN = re.compile(r"~a:(\d+)$")

RESOLVED_STATUSES = ("matched", "matched_manual")


def _load_rostered_players() -> dict[str, dict]:
    players = json.loads(PLAYERS_PATH.read_text())["players"]
    ownership = json.loads(PLAYER_OWNERSHIP_PATH.read_text())["player_ownership"]
    return {player_id: info for player_id, info in players.items() if player_id in ownership and info["position"] != "DEF"}


def _load_existing_map() -> dict[str, dict]:
    """Prefers the confirmed, post-review map when it exists (see module
    docstring) - falls back to this script's own prior fresh-pull output
    only if a review hasn't been completed even once yet."""
    if CONFIRMED_ID_MAP_PATH.exists():
        return json.loads(CONFIRMED_ID_MAP_PATH.read_text())
    if TO_REVIEW_ORIGINAL_PATH.exists():
        return json.loads(TO_REVIEW_ORIGINAL_PATH.read_text())
    return {}


def _search_raw_path(player_id: str) -> Path:
    return SEARCH_RAW_DIRECTORY / f"{player_id}.json"


def fetch_search_results(client: httpx.Client, player_id: str, name: str) -> dict | None:
    destination_path = _search_raw_path(player_id)
    if already_fetched(destination_path):
        return json.loads(destination_path.read_text())

    try:
        response = client.get(ESPN_SEARCH_URL, params={"query": name, "limit": 10}, follow_redirects=True)
        polite_sleep()
    except httpx.HTTPError as error:
        log_error(f"{ESPN_SEARCH_URL}?query={name}", None, str(error))
        return None

    write_raw(destination_path, response.text, str(response.url), response.status_code)
    if response.status_code >= 400:
        log_error(str(response.url), response.status_code, "non-2xx response")
        return None
    try:
        return response.json()
    except ValueError as error:
        log_error(str(response.url), response.status_code, f"invalid JSON: {error}")
        return None


def _extract_football_candidates(search_json: dict) -> list[dict]:
    candidates = []
    for result in search_json.get("results", []):
        if result.get("type") != "player":
            continue
        for content in result.get("contents", []):
            if content.get("sport") != "football" or content.get("defaultLeagueSlug") != "nfl":
                continue
            match = UID_ATHLETE_ID_PATTERN.search(content.get("uid", ""))
            if not match:
                continue
            candidates.append({"espn_id": match.group(1), "name": content.get("displayName", ""), "team": content.get("subtitle", "")})
    return candidates


def _resolve_player(candidates: list[dict]) -> tuple[str | None, str]:
    if len(candidates) == 1:
        return candidates[0]["espn_id"], "matched"
    if not candidates:
        return None, "unmatched"
    return None, "ambiguous"


def build_id_map() -> dict[str, dict]:
    rostered_players = _load_rostered_players()
    existing = _load_existing_map()
    print(f"{len(rostered_players)} rostered non-DEF players to resolve")

    id_map: dict[str, dict] = {}
    with httpx.Client(timeout=30) as client:
        for player_id, info in sorted(rostered_players.items()):
            existing_entry = existing.get(player_id)
            if existing_entry and existing_entry.get("status") in RESOLVED_STATUSES:
                id_map[player_id] = existing_entry
                continue

            search_json = fetch_search_results(client, player_id, info["name"])
            if search_json is None:
                # Fetch/parse failed (already logged) - keep whatever
                # prior attempt exists rather than discarding it.
                id_map[player_id] = existing_entry or {
                    "name": info["name"],
                    "position": info["position"],
                    "espn_id": None,
                    "status": "unmatched",
                    "candidates": [],
                }
                continue

            candidates = _extract_football_candidates(search_json)
            espn_id, status = _resolve_player(candidates)
            id_map[player_id] = {
                "name": info["name"],
                "position": info["position"],
                "espn_id": espn_id,
                "status": status,
                "candidates": candidates,
            }
            detail = f"-> {espn_id}" if espn_id else f"({len(candidates)} candidates)"
            print(f"{info['name']} ({player_id}): {status} {detail}")

    return id_map


def main() -> None:
    id_map = build_id_map()
    write_json(TO_REVIEW_ORIGINAL_PATH, id_map)
    matched = sum(1 for entry in id_map.values() if entry["status"] in RESOLVED_STATUSES)
    print(f"wrote {TO_REVIEW_ORIGINAL_PATH}: {matched}/{len(id_map)} matched")
    print("run nfl_player_id_map_review.py next to review any ambiguous players.")


if __name__ == "__main__":
    main()
