"""Builds archive/player_fantasy_value_metrics.json: for every player who was
BOTH drafted in a season (archive/parsed/{year}/draft.json) AND has real
weekly fantasy output that season (archive/player_ownership.json),
computes that season's fantasy value per game - fantasy points per game
divided by what the pick "cost". Meant to run once a week (new weekly
data lands throughout an active season) rather than on every request, so
the frontend just loads the finished file. See pages_drafts.py's Player
Analysis tab for the consumer - a per-season box plot of every
drafted player's value, with the searched player placed inside it.

Cost is a real dollar amount for an auction pick, or, for a SNAKE pick, a
pseudo-cost built from draft position: (total_picks - overall_pick + 1),
so pick #1 gets the HIGHEST pseudo-cost (the biggest investment, like the
biggest $ bid) and the last pick gets the lowest. There's no real dollar
figure for a snake draft to fall back on - this is a stand-in, not a
validated value model. A KEEPER pick (auction era, auction_amount null -
never had a real bid, see draft.json's own notes field) gets a flat
KEEPER_DEFAULT_COST ($50) instead of None, so it still gets a real
fantasy_value_per_game rather than being silently dropped from the
comparison - is_keeper flags this on the entry so it's not confused with
a genuine $50 bid.
"""

from utils import ARCHIVE_DIRECTORY, PARSED_DIRECTORY, parsed_path, read_json, write_json

# Flat stand-in cost for a keeper pick (no real auction bid ever
# happened) - roughly the midpoint of a $200 budget, picked so a keeper
# neither looks free (cost near 0, value_per_game -> huge) nor looks
# like a top-dollar auction buy.
KEEPER_DEFAULT_COST = 50


def discover_parsed_seasons() -> list[int]:
    if not PARSED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in PARSED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


def _draft_cost(draft_type: str, auction_amount: float | None, overall_pick: int, total_picks: int) -> float:
    if draft_type == "auction":
        return auction_amount if auction_amount is not None else KEEPER_DEFAULT_COST
    return total_picks - overall_pick + 1


def build_player_fantasy_value_metrics(years: list[int], player_ownership: dict[str, list[dict]]) -> dict:
    value_by_season: dict[int, list[dict]] = {}

    for year in years:
        draft_path = parsed_path(year, "draft.json")
        if not draft_path.exists():
            continue
        draft = read_json(draft_path)
        total_picks = len(draft["picks"])
        print(f"{year=}")
        print(f"{total_picks=}")

        for pick in draft["picks"]:
            player_id = pick.get("player_id")
            if not player_id:
                continue

            weekly_points = [entry["points"] for entry in player_ownership.get(player_id, []) if entry["season"] == year]
            if not weekly_points:
                continue

            games_played = len(weekly_points)
            total_fantasy_points = sum(weekly_points)
            fantasy_points_per_game = total_fantasy_points / games_played

            is_keeper = draft["draft_type"] == "auction" and pick.get("auction_amount") is None
            cost = _draft_cost(draft["draft_type"], pick.get("auction_amount"), pick["overall_pick"], total_picks)
            fantasy_value_per_season = total_fantasy_points / cost
            fantasy_value_per_game = fantasy_points_per_game / cost

            value_by_season.setdefault(year, []).append(
                {
                    "player_id": player_id,
                    "player_name": pick["player_name"],
                    "position": pick["position"],
                    "games_played": games_played,
                    "is_keeper": is_keeper,
                    "draft_type": draft["draft_type"],
                    "overall_pick": pick["overall_pick"],
                    "auction_amount": pick.get("auction_amount"),
                    "cost": cost,
                    "total_fantasy_points": round(total_fantasy_points, 2),
                    "fantasy_points_per_game": round(fantasy_points_per_game, 2),
                    "fantasy_value_per_season": round(fantasy_value_per_season, 2),
                    "fantasy_value_per_game": round(fantasy_value_per_game, 2),
                }
            )

    for entries in value_by_season.values():
        entries.sort(key=lambda entry: entry["player_name"])

    return {"player_fantasy_value_metrics": {str(year): entries for year, entries in value_by_season.items()}}


def main() -> None:
    years = discover_parsed_seasons()
    player_ownership = read_json(ARCHIVE_DIRECTORY / "player_ownership.json")["player_ownership"]
    registry = build_player_fantasy_value_metrics(years, player_ownership)
    output_path = ARCHIVE_DIRECTORY / "player_fantasy_value_metrics.json"
    write_json(output_path, registry)
    player_count = sum(len(entries) for entries in registry["player_fantasy_value_metrics"].values())
    print(f"wrote {output_path}: {player_count} player-seasons across {len(registry['player_fantasy_value_metrics'])} seasons")


if __name__ == "__main__":
    main()
