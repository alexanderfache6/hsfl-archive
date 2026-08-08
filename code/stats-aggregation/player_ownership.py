"""Builds archive/player_ownership.json: for every player_id, a full
weekly ownership timeline across all seasons - which team/manager had
them, whether they started or benched that week, how many points they
scored, and their raw stat_N breakdown that week (decode stat_N labels
via archive/stat_id_labels.json). Built entirely from already-parsed
rosters/*.json across every season - avoids the frontend Players tab
having to scan ~1000+ roster files per search. See execution-plan.md
Phase G.
"""

from utils import ARCHIVE_DIRECTORY, PARSED_DIRECTORY, read_json, team_id_to_manager, write_json


def discover_parsed_seasons() -> list[int]:
    if not PARSED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in PARSED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


def build_player_ownership(years: list[int]) -> dict:
    ownership: dict[str, list[dict]] = {}

    for year in years:
        manager_by_team_id = team_id_to_manager(year)
        rosters_directory = PARSED_DIRECTORY / str(year) / "rosters"
        if not rosters_directory.exists():
            continue

        for roster_path in rosters_directory.glob("*.json"):
            roster = read_json(roster_path)
            team_id = roster["team_id"]
            week = roster["week"]
            manager = manager_by_team_id.get(team_id, {})

            for status, players in (("starter", roster["starters"]), ("bench", roster["bench"])):
                for player in players:
                    player_id = player.get("player_id")
                    if not player_id:
                        continue
                    ownership.setdefault(player_id, []).append(
                        {
                            "season": year,
                            "week": week,
                            "team_id": team_id,
                            "manager_id": manager.get("manager_id", ""),
                            "display_name": manager.get("display_name", ""),
                            "status": status,
                            "points": player.get("points") or 0.0,
                            "stats": player.get("stats") or {},
                        }
                    )

    for entries in ownership.values():
        entries.sort(key=lambda entry: (entry["season"], entry["week"]))

    return {"player_ownership": ownership}


def main() -> None:
    years = discover_parsed_seasons()
    registry = build_player_ownership(years)
    output_path = ARCHIVE_DIRECTORY / "player_ownership.json"
    write_json(output_path, registry)
    print(f"wrote {output_path}: {len(registry['player_ownership'])} players tracked, seasons={years}")


if __name__ == "__main__":
    main()
