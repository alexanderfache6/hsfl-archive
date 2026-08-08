"""Cross-season win/losing streak variants - enriches the already-built
archive/aggregated/all_time_records.json with 3 additional streak
variants beyond the existing per-season one (see records.py):

- regular_cross_season: regular-season games only, but chronological
  ACROSS seasons (a streak doesn't reset at a season boundary the way
  the per-season variant does).
- postseason_cross_season: championship/consolation bracket games only,
  chronological across every postseason appearance a manager has ever
  had (a season they missed the playoffs entirely just isn't part of
  the sequence - not treated as a "loss" that breaks the streak, same
  principle as player_ownership.py not synthesizing gaps for years not
  yet fetched).
- combined_cross_season: every game (regular + both postseason brackets)
  in one chronological sequence across a manager's whole career.

Must run AFTER all_time.py (reads and re-writes all_time_records.json).
See execution-plan.md Phase G.
"""

from utils import (
    AGGREGATED_DIRECTORY,
    PARSED_DIRECTORY,
    build_team_week_index,
    load_regular_season_weeks,
    read_json,
    team_id_to_manager,
    write_json,
)


def discover_parsed_seasons() -> list[int]:
    if not PARSED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in PARSED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


def _week_label_to_number(week_label: str) -> int:
    return int(week_label.removeprefix("Week ").strip())


def build_manager_game_sequences(years: list[int]) -> dict[str, list[dict]]:
    """{manager_id: [{season, week, bracket: "regular"|"championship"|
    "consolation", result: "W"|"L"|"T", display_name}, ...]} sorted
    chronologically (season, week) - a manager never plays both a
    regular-season and postseason game in the same (season, week), so
    this sort order is unambiguous across brackets too."""
    sequences: dict[str, list[dict]] = {}

    for year in years:
        manager_by_team_id = team_id_to_manager(year)
        team_week_index = build_team_week_index(year)

        for week in load_regular_season_weeks(year):
            for team_id, manager in manager_by_team_id.items():
                entry = team_week_index.get((team_id, week))
                if entry is None:
                    continue
                if entry["score"] > entry["opponent_score"]:
                    result = "W"
                elif entry["score"] < entry["opponent_score"]:
                    result = "L"
                else:
                    result = "T"
                sequences.setdefault(manager["manager_id"], []).append(
                    {"season": year, "week": week, "bracket": "regular", "result": result, "display_name": manager["display_name"]}
                )

        playoffs_path = PARSED_DIRECTORY / str(year) / "playoffs.json"
        if not playoffs_path.exists():
            continue
        playoffs = read_json(playoffs_path)
        for bracket_key, bracket_label in (("championship_bracket", "championship"), ("consolation_bracket", "consolation")):
            for round_entry in playoffs.get(bracket_key, {}).get("rounds", []):
                week = _week_label_to_number(round_entry["round_name"])
                for game in round_entry["matchups"]:
                    if game.get("is_bye"):
                        continue
                    home_id, away_id, winner_id = game.get("team_id_home"), game.get("team_id_away"), game.get("winner_team_id")
                    if not home_id or not away_id or not winner_id:
                        continue
                    for team_id in (home_id, away_id):
                        manager = manager_by_team_id.get(team_id)
                        if not manager:
                            continue
                        result = "W" if team_id == winner_id else "L"
                        sequences.setdefault(manager["manager_id"], []).append(
                            {"season": year, "week": week, "bracket": bracket_label, "result": result, "display_name": manager["display_name"]}
                        )

    for entries in sequences.values():
        entries.sort(key=lambda entry: (entry["season"], entry["week"]))
    return sequences


def _longest_run(entries: list[dict], result_type: str) -> dict | None:
    """Longest consecutive run of entries with result == result_type,
    within an already-filtered/chronologically-sorted entry list. Returns
    {"value", "start_season", "start_week", "season", "week"} (the last
    two named to match every other record type's "season"/"week" fields,
    used generically by the frontend's View Game/Season link) or None if
    result_type never occurs."""
    best_length = 0
    best_start_index = None
    best_end_index = None
    current_length = 0
    current_start_index = None

    for index, entry in enumerate(entries):
        if entry["result"] == result_type:
            if current_length == 0:
                current_start_index = index
            current_length += 1
            if current_length > best_length:
                best_length = current_length
                best_start_index = current_start_index
                best_end_index = index
        else:
            current_length = 0

    if best_length == 0:
        return None

    start_entry, end_entry = entries[best_start_index], entries[best_end_index]
    return {
        "value": best_length,
        "start_season": start_entry["season"],
        "start_week": start_entry["week"],
        "season": end_entry["season"],
        "week": end_entry["week"],
        "display_name": end_entry["display_name"],
    }


def build_cross_season_streaks(sequences: dict[str, list[dict]]) -> dict:
    variants = {
        "regular_cross_season": lambda entries: [e for e in entries if e["bracket"] == "regular"],
        "postseason_cross_season": lambda entries: [e for e in entries if e["bracket"] != "regular"],
        "combined_cross_season": lambda entries: entries,
    }

    result: dict[str, dict[str, list[dict]]] = {}
    for variant_key, filter_fn in variants.items():
        win_candidates, loss_candidates = [], []
        for manager_id, entries in sequences.items():
            filtered = filter_fn(entries)
            win_streak = _longest_run(filtered, "W")
            if win_streak:
                win_candidates.append({"manager_id": manager_id, **win_streak})
            loss_streak = _longest_run(filtered, "L")
            if loss_streak:
                loss_candidates.append({"manager_id": manager_id, **loss_streak})

        win_candidates.sort(key=lambda entry: -entry["value"])
        loss_candidates.sort(key=lambda entry: -entry["value"])
        result[f"longest_win_streak_{variant_key}"] = win_candidates[:3]
        result[f"longest_losing_streak_{variant_key}"] = loss_candidates[:3]

    return result


def main() -> None:
    years = discover_parsed_seasons()
    sequences = build_manager_game_sequences(years)
    cross_season_streaks = build_cross_season_streaks(sequences)

    all_time_records_path = AGGREGATED_DIRECTORY / "all_time_records.json"
    all_time_records = read_json(all_time_records_path)
    all_time_records.update(cross_season_streaks)
    write_json(all_time_records_path, all_time_records)

    print(f"wrote {all_time_records_path} with cross-season streak variants, seasons={years}")


if __name__ == "__main__":
    main()
