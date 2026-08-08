"""Builds archive/players.json, the cumulative player_id -> {name, position}
registry. Built entirely from already-parsed data (draft.json, rosters/*.json,
matchups/*.json) across every season - no new live fetches, per user
confirmation 2026-08-07 (the player-card URL was considered but rejected
in favor of reusing already-archived names, since draft.json/rosters
already carry full names, not just the abbreviated ones gamecenter box
scores use).
"""

import json
import re

from utils import PARSED_DIRECTORY, PLAYERS_PATH, write_json


def discover_parsed_seasons() -> list[int]:
    if not PARSED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in PARSED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


def _is_abbreviated_name(name: str) -> bool:
    """True for names like "J. Allen" (single-initial + period) - the
    format gamecenter box scores use, as opposed to the full names
    draft.json and the roster page use ("Josh Allen")."""
    return bool(re.match(r"^[A-Z]\.\s", name))


def _update_player(players: dict, player_id: str, name: str, position: str) -> None:
    if not player_id or not name:
        return
    existing = players.get(player_id)
    if existing is None:
        players[player_id] = {"player_id": player_id, "name": name, "position": position}
        return
    if _is_abbreviated_name(existing["name"]) and not _is_abbreviated_name(name):
        existing["name"] = name  # upgrade to a full name if we only had an abbreviated one so far
    if position and not existing.get("position"):
        existing["position"] = position


def build_players_registry(years: list[int]) -> dict:
    # nfl_team deliberately not tracked here (2026-08-07, user instruction):
    # a player's team changes over time (trades, free agency), so it
    # doesn't belong in a static cumulative registry - see matchups/rosters
    # for whatever team a player was on in a specific week instead.
    players: dict[str, dict] = {}

    for year in years:
        season_directory = PARSED_DIRECTORY / str(year)

        draft_path = season_directory / "draft.json"
        if draft_path.exists():
            draft = json.loads(draft_path.read_text())
            for pick in draft["picks"]:
                _update_player(players, pick["player_id"], pick["player_name"], pick["position"])

        rosters_directory = season_directory / "rosters"
        if rosters_directory.exists():
            for roster_path in rosters_directory.glob("*.json"):
                roster = json.loads(roster_path.read_text())
                for player in roster["starters"] + roster["bench"]:
                    _update_player(players, player.get("player_id", ""), player["player_name"], player["position"])

        matchups_directory = season_directory / "matchups"
        if matchups_directory.exists():
            for matchup_path in matchups_directory.glob("*.json"):
                matchup = json.loads(matchup_path.read_text())
                for side in ("home", "away"):
                    for player in matchup[side]["starters"] + matchup[side]["bench"]:
                        _update_player(players, player.get("player_id", ""), player["player_name"], player["position"])

    return {"players": players}


def main() -> None:
    years = discover_parsed_seasons()
    registry = build_players_registry(years)
    write_json(PLAYERS_PATH, registry)
    print(f"wrote {PLAYERS_PATH}: {len(registry['players'])} players, seasons={years}")


if __name__ == "__main__":
    main()
