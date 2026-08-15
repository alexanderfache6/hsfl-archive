"""Fetches every mapped player's real NFL stats, per week, for every
regular season 2012-present - REGARDLESS of whether that player was on
a fantasy roster that week. This is the backfill data for the gap weeks
pages_players.py's _build_full_game_list currently renders as a red
"Not on a Fantasy Roster" placeholder with no real stats behind it (see
instructions/cool-features.md's "players" section).

Only players with a resolved ESPN ID in archive/nfl_player_id_map.json
(status "matched" or "matched_manual") are fetched - run
nfl_player_id_map.py first.

Postseason is explicitly OUT of scope (per plan discussion 2026-08-14):
a season's gamelog response splits into separate seasonTypes ("{year}
Regular Season" / "{year} Postseason" when that player's team made the
playoffs) - only the Regular Season one is parsed here.

Fantasy point conversion is explicitly NOT done here - this script only
collects RAW NFL stat categories under ESPN's own names (e.g.
"passingTouchdowns", not this league's stat_N scheme). Converting to
this league's own scoring rubric (data_loader.py's
compute_stat_fantasy_points) is a separate, later step once this raw
data exists.

ESPN's gamelog endpoint:
https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{espn_id}/gamelog?season={year}
Each event's "stats" array lines up 1:1, in order, with the response's
own top-level "names" array (confirmed 2026-08-14) - zip(names, stats)
directly, no per-category slicing needed even though "categories"
nominally breaks "names" into passing/rushing/etc groups. Per-game
week/opponent/result/team live in the response's own top-level "events"
dict (keyed by eventId), not inside the per-category event stub.

Each (espn_id, season) raw response is cached to
archive/raw/espn_gamelog/{espn_id}/{season}.json (idempotent via
already_fetched) - a season with no career data for that player (before
their rookie year, or after retirement) still caches a real, successful
(just sparse) response, so it's never re-fetched on a later run either.
Output is rebuilt from the FULL raw cache on every run (cheap, no
network) rather than incrementally merged, so a parsing bug fix takes
effect for every already-fetched season without re-fetching anything.

Safe to run WEEKLY during an active season: every season is cached
forever EXCEPT _active_season() (this run's current NFL season, per
calendar date - see its own docstring), which is force-refetched on
every run regardless of cache state, since that's the one season still
gaining new weeks. A completed past season's cache is never touched
again once written, so a weekly cron-style run only ever makes one new
request per resolved player (that one active-season refetch), not a
full re-crawl of league history.

Output: archive/nfl_player_stats.json, keyed by fantasy player_id:
    {"<player_id>": {"espn_id": ..., "name": ..., "position": ...,
    "seasons": {"2018": {"weeks": {"3": {"team": "PHI", "opponent":
    "TEN", "result": "W", "stats": {"passingYards": "270", ...}},
    ...}}, ...}}}

This is a one-time full-history backfill (~800+ players x up to ~15
seasons) - deliberately slow/polite (REQUEST_DELAY_SECONDS between every
live request, same as every other fetcher in this package) rather than
optimized for speed; expect a multi-hour run the first time. Re-runs
after that are fast, since almost everything is already cached.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import (
    ARCHIVE_DIRECTORY,
    already_fetched,
    log_error,
    polite_sleep,
    write_json,
    write_raw,
)

ESPN_GAMELOG_URL_TEMPLATE = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{espn_id}/gamelog"

ID_MAP_PATH = ARCHIVE_DIRECTORY / "nfl_player_id_map.json"
STATS_OUTPUT_PATH = ARCHIVE_DIRECTORY / "nfl_player_stats.json"
GAMELOG_RAW_DIRECTORY = ARCHIVE_DIRECTORY / "raw" / "espn_gamelog"

FIRST_SEASON = 2012
RESOLVED_STATUSES = ("matched", "matched_manual")


def _default_last_season() -> int:
    """Current calendar year - "present," not "next year" like
    nfl_bye_weeks.py's own default (that script is fine reaching one
    year ahead for a not-yet-published schedule; a gamelog request for a
    season that hasn't started yet has nothing useful to cache)."""
    return datetime.now(timezone.utc).year


def _active_season() -> int:
    """The one season whose raw cache is force-refreshed on every run
    (see fetch_gamelog) so this script is safe to run weekly during a
    season without re-fetching every already-cached prior season. NFL
    regular-season games run September through early January, so a
    January/February run is still the PREVIOUS calendar year's season
    (e.g. Week 18 games in early January belong to the season labeled
    by the year before) - not a new season that hasn't started."""
    now = datetime.now(timezone.utc)
    return now.year - 1 if now.month <= 2 else now.year


def _resolved_players() -> dict[str, dict]:
    if not ID_MAP_PATH.exists():
        raise SystemExit(f"{ID_MAP_PATH} not found - run nfl_player_id_map.py first.")
    id_map = json.loads(ID_MAP_PATH.read_text())
    return {player_id: entry for player_id, entry in id_map.items() if entry.get("status") in RESOLVED_STATUSES and entry.get("espn_id")}


def _gamelog_raw_path(espn_id: int, season: int) -> Path:
    return GAMELOG_RAW_DIRECTORY / str(espn_id) / f"{season}.json"


def fetch_gamelog(client: httpx.Client, espn_id: str, season: int, force: bool = False) -> None:
    """Fetch + cache only - see module docstring for why parsing is a
    separate, full-cache-rebuild pass below rather than done inline
    here. force=True (only ever passed for _active_season(), the one
    season still in progress) skips the already_fetched short-circuit -
    every OTHER season is a real completed past season whose cached
    response never changes, so it's safe to skip forever."""
    destination_path = _gamelog_raw_path(espn_id, season)
    if not force and already_fetched(destination_path):
        return

    url = ESPN_GAMELOG_URL_TEMPLATE.format(espn_id=espn_id)
    try:
        response = client.get(url, params={"season": season}, follow_redirects=True)
        polite_sleep()
    except httpx.HTTPError as error:
        log_error(url, None, str(error))
        return

    write_raw(destination_path, response.text, str(response.url), response.status_code)
    if response.status_code >= 400:
        log_error(str(response.url), response.status_code, "non-2xx response")


def _parse_regular_season_weeks(gamelog: dict) -> dict[str, dict]:
    names = gamelog.get("names", [])
    events_by_id = gamelog.get("events", {})
    weeks: dict[str, dict] = {}
    for season_type in gamelog.get("seasonTypes", []):
        if not season_type.get("displayName", "").endswith("Regular Season"):
            continue  # postseason (or any other split) - out of scope
        for category in season_type.get("categories", []):
            for event in category.get("events", []):
                event_meta = events_by_id.get(event.get("eventId"))
                if event_meta is None or event_meta.get("week") is None:
                    continue
                weeks[str(event_meta["week"])] = {
                    "team": event_meta.get("team", {}).get("abbreviation", ""),
                    "opponent": event_meta.get("opponent", {}).get("abbreviation", ""),
                    "result": event_meta.get("gameResult", ""),
                    "stats": dict(zip(names, event.get("stats", []))),
                }
    return weeks


def build_player_stats(start_season: int = FIRST_SEASON, end_season: int | None = None) -> dict[str, dict]:
    """start_season/end_season scope which seasons THIS RUN fetches over
    the network (e.g. a one-off "just backfill 2012" run) - the output
    below always covers the full FIRST_SEASON..present range regardless,
    built from whatever's already cached on disk, so a staged/partial
    run still reports everything fetched by any prior run too, not just
    this one."""
    end_season = end_season if end_season is not None else _default_last_season()
    active_season = _active_season()
    resolved_players = _resolved_players()
    print(f"{len(resolved_players)} players with a resolved ESPN ID, fetching seasons {start_season}-{end_season} (active season {active_season} always refetched)")

    print('fetching game logs')
    with httpx.Client(timeout=30) as client:
        for player_id, entry in tqdm(sorted(resolved_players.items())):
            for season in range(start_season, end_season + 1):
                fetch_gamelog(client, entry["espn_id"], season, force=(season == active_season))

    # Rebuilt entirely from the raw cache (see module docstring), not
    # incrementally merged with any prior output.
    print('parsing game logs')
    player_stats: dict[str, dict] = {}
    for player_id, entry in tqdm(sorted(resolved_players.items())):
        espn_id = entry["espn_id"]
        seasons: dict[str, dict] = {}
        for season in range(FIRST_SEASON, _default_last_season() + 1):
            raw_path = _gamelog_raw_path(espn_id, season)
            if not already_fetched(raw_path):
                continue  # not yet fetched (by this or any prior run), or fetch failed - already logged via log_error
            gamelog = json.loads(raw_path.read_text())
            weeks = _parse_regular_season_weeks(gamelog)
            if weeks:
                seasons[str(season)] = {"weeks": weeks}
        player_stats[player_id] = {"espn_id": espn_id, "name": entry["name"], "position": entry["position"], "seasons": seasons}
        print(f"{entry['name']} ({player_id}): {len(seasons)} season(s) with data")

    return player_stats


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fetch real NFL per-week stats for every rostered-at-least-once player.")
    parser.add_argument("--start-season", type=int, default=FIRST_SEASON, help=f"first season to fetch this run (default: {FIRST_SEASON})")
    parser.add_argument("--end-season", type=int, default=None, help="last season to fetch this run (default: current season)")
    args = parser.parse_args()

    player_stats = build_player_stats(start_season=args.start_season, end_season=args.end_season)
    write_json(STATS_OUTPUT_PATH, player_stats)
    total_weeks = sum(len(season["weeks"]) for player in player_stats.values() for season in player["seasons"].values())
    print(f"wrote {STATS_OUTPUT_PATH}: {len(player_stats)} players, {total_weeks} player-weeks")


if __name__ == "__main__":
    main()
