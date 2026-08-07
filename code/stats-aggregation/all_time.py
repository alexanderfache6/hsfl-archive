"""Cross-season ("History" tab) aggregation - combines every season's
already-computed aggregate_season.py output (weekly_tables.json,
players_started.json, head_to_head.json, records.json) into all-time
files. Deliberately does NOT re-derive per-season stats independently -
wins/losses/points/streaks/coaching/head-to-head all come from Phase F's
own validated per-season output, not recomputed from archive/parsed/.
The only things pulled from archive/parsed/ are what Phase F doesn't
produce at all: manager identity (metadata.json), final standings
(standings.json), and playoff results (playoffs.json). See
execution-plan.md Phase G.
"""

from utils import (
    AGGREGATED_DIRECTORY,
    aggregated_path,
    combine_top_n_records,
    load_display_name_alternates,
    parsed_path,
    placement_number,
    read_json,
    team_id_to_manager,
    write_json,
)


def discover_aggregated_seasons() -> list[int]:
    if not AGGREGATED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in AGGREGATED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


def _find_last_place(consolation_bracket: dict, final_standings: list[dict]) -> str:
    """Loser of the highest-placement-number game (e.g. "9th Place Game"
    in a 10-team league) - the mirror image of parse.py's
    consolation_winner_team_id (lowest placement number's winner).

    Fallback added 2026-08-07 (found via 2012, a 4-team season): when a
    season has no real consolation bracket at all (e.g. every team made
    the single championship bracket, as happened in a small league), the
    bracket-based lookup has no candidates - fall back to the
    worst-ranked team in that season's final regular-season standings,
    since "last place" is still a well-defined concept even without a
    consolation bracket to derive it from."""
    candidates = []
    for round_entry in consolation_bracket.get("rounds", []):
        for matchup in round_entry.get("matchups", []):
            if matchup.get("is_bye"):
                continue
            placement = placement_number(matchup.get("round_label", ""))
            home_id, away_id, winner_id = matchup.get("team_id_home"), matchup.get("team_id_away"), matchup.get("winner_team_id")
            if placement is None or not home_id or not away_id or not winner_id:
                continue
            loser_id = away_id if winner_id == home_id else home_id
            candidates.append((placement, loser_id))
    if candidates:
        _, loser_id = max(candidates, key=lambda pair: pair[0])
        return loser_id

    if not final_standings:
        return ""
    worst_row = max(final_standings, key=lambda row: row["rank"])
    return worst_row["team_id"]


def _empty_totals() -> dict:
    return {"wins": 0, "losses": 0, "ties": 0, "points_for": 0.0, "points_against": 0.0}


def build_all_time_champions(years: list[int], unresolved: list) -> dict:
    """One row per season: top 3 final standings + last place (no
    consolation-bracket winner - removed 2026-08-07 in favor of last
    place, since the winning side of the consolation bracket wasn't
    judged useful enough to keep alongside the punishment stat). Each
    entry now carries both regular_season (from standings.json) and
    post_season (from the new per-season post_season_stats.json) blocks -
    top_3 uses their championship-bracket record, last_place uses their
    consolation-bracket record, since that's unambiguously which bracket
    each side played in. Any team_id that can't be resolved to a manager
    is appended to `unresolved` rather than silently left with a blank
    manager_id/display_name - see the "do not drop anything silently"
    hardening pass, 2026-08-07."""
    seasons = []
    for year in years:
        standings = read_json(parsed_path(year, "standings.json"))
        playoffs = read_json(parsed_path(year, "playoffs.json"))
        post_season_stats = read_json(aggregated_path(year, "post_season_stats.json"))
        manager_by_team_id = team_id_to_manager(year)

        top_3 = []
        for row in sorted(standings["final_standings"], key=lambda r: r["rank"])[:3]:
            manager = manager_by_team_id.get(row["team_id"])
            if manager is None:
                unresolved.append({"season": year, "team_id": row["team_id"], "context": "all_time_champions.top_3"})
                manager = {}
            post_season = post_season_stats["championship"].get(row["team_id"], _empty_totals())
            top_3.append(
                {
                    "rank": row["rank"],
                    "team_id": row["team_id"],
                    "manager_id": manager.get("manager_id", ""),
                    "display_name": manager.get("display_name", ""),
                    "regular_season": {
                        "wins": row["wins"],
                        "losses": row["losses"],
                        "ties": row["ties"],
                        "points_for": row["points_for"],
                        "points_against": row["points_against"],
                    },
                    "post_season": post_season,
                }
            )

        last_place_team_id = _find_last_place(playoffs["consolation_bracket"], standings["final_standings"])
        last_place_manager = manager_by_team_id.get(last_place_team_id)
        if last_place_manager is None:
            if last_place_team_id:
                unresolved.append({"season": year, "team_id": last_place_team_id, "context": "all_time_champions.last_place"})
            last_place_manager = {}
        last_place_regular_season = next((r for r in standings["final_standings"] if r["team_id"] == last_place_team_id), None)

        seasons.append(
            {
                "season": year,
                "top_3": top_3,
                "last_place": {
                    "team_id": last_place_team_id,
                    "manager_id": last_place_manager.get("manager_id", ""),
                    "display_name": last_place_manager.get("display_name", ""),
                    "regular_season": (
                        {
                            "wins": last_place_regular_season["wins"],
                            "losses": last_place_regular_season["losses"],
                            "ties": last_place_regular_season["ties"],
                            "points_for": last_place_regular_season["points_for"],
                            "points_against": last_place_regular_season["points_against"],
                        }
                        if last_place_regular_season
                        else _empty_totals()
                    ),
                    "post_season": post_season_stats["consolation"].get(last_place_team_id, _empty_totals()),
                },
            }
        )
    return {"champions": seasons}


def _add_head_to_head_matrix(managers: dict, block_key: str, matrix_by_team: dict, team_to_manager: dict, year: int, unresolved: list) -> None:
    """Merges one season's {team_id: {opponent_team_id: {wins,losses,ties}}}
    matrix into managers[manager_id][block_key]["head_to_head"]
    (mutated in place), resolving team_ids to persistent manager_ids in a
    single pass. managers[manager_id] entries must already exist. Any
    team_id (row-owner or opponent) that can't be resolved is appended to
    `unresolved` instead of silently dropped."""
    for team_id, opponents in matrix_by_team.items():
        manager = team_to_manager.get(team_id)
        if not manager:
            unresolved.append({"season": year, "team_id": team_id, "context": f"head_to_head.{block_key} (row owner)"})
            continue
        target = managers[manager["manager_id"]][block_key]["head_to_head"]
        for opponent_team_id, record in opponents.items():
            opponent_manager = team_to_manager.get(opponent_team_id)
            if not opponent_manager:
                unresolved.append({"season": year, "team_id": opponent_team_id, "context": f"head_to_head.{block_key} (opponent)"})
                continue
            cell = target.setdefault(opponent_manager["manager_id"], {"wins": 0, "losses": 0, "ties": 0})
            cell["wins"] += record["wins"]
            cell["losses"] += record["losses"]
            cell["ties"] += record["ties"]


def _empty_record_block() -> dict:
    return {"wins": 0, "losses": 0, "ties": 0, "points_for": 0.0, "points_against": 0.0, "head_to_head": {}}


def _finalize_record_block(block: dict) -> dict:
    games_played = block["wins"] + block["losses"] + block["ties"]
    win_pct = round((block["wins"] + 0.5 * block["ties"]) / games_played, 4) if games_played else 0.0
    return {
        "wins": block["wins"],
        "losses": block["losses"],
        "ties": block["ties"],
        "win_pct": win_pct,
        "points_for": round(block["points_for"], 2),
        "points_against": round(block["points_against"], 2),
        "head_to_head": block["head_to_head"],
    }


BLOCK_KEYS = ("regular_season", "post_season_championship", "post_season_consolation")


def build_all_time_manager_stats(years: list[int], unresolved: list) -> dict:
    """One row per manager, cumulative from their first season to their
    last, split into regular_season / post_season_championship /
    post_season_consolation / combined blocks - each with
    wins/losses/ties/win_pct/points_for/points_against/head_to_head.
    combined = the sum of all three other blocks (everything the manager
    ever played, regardless of bracket). All figures come from each
    season's already-computed aggregate_season.py output
    (weekly_tables.json, head_to_head.json, post_season_stats.json) - not
    re-derived from playoffs.json directly, per the "based on
    aggregate_season outputs" principle."""
    display_name_alternates = load_display_name_alternates()
    managers: dict[str, dict] = {}
    career: dict[str, dict] = {}

    def get_manager(manager_id: str, display_name: str) -> dict:
        if manager_id not in managers:
            managers[manager_id] = {key: _empty_record_block() for key in BLOCK_KEYS}
            career[manager_id] = {
                "manager_id": manager_id,
                "display_names_seen": [],
                "seasons_played": [],
                "championships": 0,
                "runner_ups": 0,
                "third_place_finishes": 0,
                "last_place_finishes": 0,
                "_career_player_ids": set(),
                "_regular_season_ranks": [],
                "_post_season_ranks": [],
            }
        if display_name and display_name not in career[manager_id]["display_names_seen"]:
            career[manager_id]["display_names_seen"].append(display_name)
        return managers[manager_id]

    for year in years:
        manager_by_team_id = team_id_to_manager(year)
        weekly_tables = read_json(aggregated_path(year, "weekly_tables.json"))
        head_to_head = read_json(aggregated_path(year, "head_to_head.json"))
        playoffs = read_json(parsed_path(year, "playoffs.json"))
        players_started = read_json(aggregated_path(year, "players_started.json"))
        post_season_stats = read_json(aggregated_path(year, "post_season_stats.json"))
        standings = read_json(parsed_path(year, "standings.json"))

        # Ensure every team_id playing this season has a manager entry
        # before merging any data into it.
        for team_id, manager in manager_by_team_id.items():
            get_manager(manager["manager_id"], manager["display_name"])

        final_week_standings = weekly_tables["weeks"][-1]["standings"] if weekly_tables["weeks"] else []
        for row in final_week_standings:
            manager = manager_by_team_id.get(row["team_id"])
            if not manager:
                unresolved.append({"season": year, "team_id": row["team_id"], "context": "manager_stats.regular_season"})
                continue
            block = get_manager(manager["manager_id"], manager["display_name"])["regular_season"]
            block["wins"] += row["wins"]
            block["losses"] += row["losses"]
            block["ties"] += row["ties"]
            block["points_for"] += row["points_for"]
            block["points_against"] += row["points_against"]
            career[manager["manager_id"]]["seasons_played"].append(year)
            career[manager["manager_id"]]["_regular_season_ranks"].append(row["rank"])

        for bracket_name, block_key in (("championship", "post_season_championship"), ("consolation", "post_season_consolation")):
            for team_id, totals in post_season_stats[bracket_name].items():
                manager = manager_by_team_id.get(team_id)
                if not manager:
                    unresolved.append({"season": year, "team_id": team_id, "context": f"manager_stats.{block_key}"})
                    continue
                block = get_manager(manager["manager_id"], manager["display_name"])[block_key]
                block["wins"] += totals["wins"]
                block["losses"] += totals["losses"]
                block["ties"] += totals["ties"]
                block["points_for"] += totals["points_for"]
                block["points_against"] += totals["points_against"]

        _add_head_to_head_matrix(managers, "regular_season", head_to_head["regular_season"], manager_by_team_id, year, unresolved)
        _add_head_to_head_matrix(managers, "post_season_championship", head_to_head["post_season"]["championship"], manager_by_team_id, year, unresolved)
        _add_head_to_head_matrix(managers, "post_season_consolation", head_to_head["post_season"]["consolation"], manager_by_team_id, year, unresolved)

        champion_team_id = playoffs["championship_bracket"]["champion_team_id"]
        champion_manager = manager_by_team_id.get(champion_team_id)
        if champion_manager:
            get_manager(champion_manager["manager_id"], champion_manager["display_name"])
            career[champion_manager["manager_id"]]["championships"] += 1
        elif champion_team_id:
            unresolved.append({"season": year, "team_id": champion_team_id, "context": "manager_stats.championships"})

        runner_up_team_id = playoffs["championship_bracket"]["runner_up_team_id"]
        runner_up_manager = manager_by_team_id.get(runner_up_team_id)
        if runner_up_manager:
            get_manager(runner_up_manager["manager_id"], runner_up_manager["display_name"])
            career[runner_up_manager["manager_id"]]["runner_ups"] += 1
        elif runner_up_team_id:
            unresolved.append({"season": year, "team_id": runner_up_team_id, "context": "manager_stats.runner_ups"})

        third_place_row = next((row for row in standings["final_standings"] if row["rank"] == 3), None)
        third_place_manager = manager_by_team_id.get(third_place_row["team_id"]) if third_place_row else None
        if third_place_manager:
            get_manager(third_place_manager["manager_id"], third_place_manager["display_name"])
            career[third_place_manager["manager_id"]]["third_place_finishes"] += 1
        elif third_place_row:
            unresolved.append({"season": year, "team_id": third_place_row["team_id"], "context": "manager_stats.third_place_finishes"})

        final_placements = post_season_stats.get("final_placements", {})
        for team_id, placement in final_placements.items():
            manager = manager_by_team_id.get(team_id)
            if manager:
                get_manager(manager["manager_id"], manager["display_name"])
                career[manager["manager_id"]]["_post_season_ranks"].append(placement)
            else:
                unresolved.append({"season": year, "team_id": team_id, "context": "manager_stats.post_season_rank"})

        last_place_team_id = _find_last_place(playoffs["consolation_bracket"], final_week_standings)
        last_place_manager = manager_by_team_id.get(last_place_team_id)
        if last_place_manager:
            get_manager(last_place_manager["manager_id"], last_place_manager["display_name"])
            career[last_place_manager["manager_id"]]["last_place_finishes"] += 1
        elif last_place_team_id:
            unresolved.append({"season": year, "team_id": last_place_team_id, "context": "manager_stats.last_place_finishes"})

        for team_row in players_started["teams"]:
            manager = manager_by_team_id.get(team_row["team_id"])
            if manager:
                get_manager(manager["manager_id"], manager["display_name"])
                career[manager["manager_id"]]["_career_player_ids"].update(team_row["player_ids"])
            else:
                unresolved.append({"season": year, "team_id": team_row["team_id"], "context": "manager_stats.career_players_started"})

    rows = []
    for manager_id, blocks in managers.items():
        finalized = {key: _finalize_record_block(blocks[key]) for key in BLOCK_KEYS}

        combined_head_to_head: dict = {}
        for key in BLOCK_KEYS:
            for opponent_id, record in finalized[key]["head_to_head"].items():
                cell = combined_head_to_head.setdefault(opponent_id, {"wins": 0, "losses": 0, "ties": 0})
                cell["wins"] += record["wins"]
                cell["losses"] += record["losses"]
                cell["ties"] += record["ties"]
        combined = _finalize_record_block(
            {
                "wins": sum(finalized[key]["wins"] for key in BLOCK_KEYS),
                "losses": sum(finalized[key]["losses"] for key in BLOCK_KEYS),
                "ties": sum(finalized[key]["ties"] for key in BLOCK_KEYS),
                "points_for": sum(finalized[key]["points_for"] for key in BLOCK_KEYS),
                "points_against": sum(finalized[key]["points_against"] for key in BLOCK_KEYS),
                "head_to_head": combined_head_to_head,
            }
        )

        career_info = career[manager_id]
        regular_season_ranks = career_info["_regular_season_ranks"]
        post_season_ranks = career_info["_post_season_ranks"]
        rows.append(
            {
                "manager_id": manager_id,
                "display_names_seen": career_info["display_names_seen"],
                "display_names_seen_alternate": display_name_alternates.get(manager_id, ""),
                "seasons_played": career_info["seasons_played"],
                "championships": career_info["championships"],
                "runner_ups": career_info["runner_ups"],
                "third_place_finishes": career_info["third_place_finishes"],
                "last_place_finishes": career_info["last_place_finishes"],
                "career_players_started_count": len(career_info["_career_player_ids"]),
                "average_regular_season_finish": round(sum(regular_season_ranks) / len(regular_season_ranks), 2) if regular_season_ranks else None,
                "average_post_season_finish": round(sum(post_season_ranks) / len(post_season_ranks), 2) if post_season_ranks else None,
                "regular_season": finalized["regular_season"],
                "post_season_championship": finalized["post_season_championship"],
                "post_season_consolation": finalized["post_season_consolation"],
                "combined": combined,
            }
        )
    rows.sort(key=lambda r: (-r["championships"], -r["combined"]["win_pct"]))
    return {"managers": rows}


RECORD_HIGHER_IS_BETTER = {
    "highest_weekly_score": True,
    "lowest_weekly_score": False,
    "highest_season_points_for": True,
    "lowest_season_points_for": False,
    "longest_win_streak": True,
    "longest_losing_streak": True,
    "best_coaching_season": True,
    "worst_coaching_season": False,
    "most_players_started_season": True,
    "fewest_players_started_season": False,
}


def build_all_time_records(years: list[int]) -> dict:
    """Combines each season's already-computed records.json top-3 lists
    (not a fresh scan of weekly_tables.json) into all-time top-3 lists,
    injecting "season" into each entry since a per-season file doesn't
    carry it (redundant within that file). Keeping only the top-3 per
    season is sufficient to get an accurate all-time top-3 - see
    combine_top_n_records's docstring for why."""
    per_stat_lists: dict[str, list[list[dict]]] = {key: [] for key in RECORD_HIGHER_IS_BETTER}

    for year in years:
        season_records = read_json(aggregated_path(year, "records.json"))
        for key in per_stat_lists:
            season_top_n = season_records.get(key) or []
            with_season = [{"season": year, **{k: v for k, v in entry.items() if k != "value"}, "value": entry["value"]} for entry in season_top_n]
            per_stat_lists[key].append(with_season)

    return {
        key: combine_top_n_records(lists, RECORD_HIGHER_IS_BETTER[key])
        for key, lists in per_stat_lists.items()
    }


def aggregate_all_time() -> None:
    """Per the 2026-08-07 "do not drop anything silently" hardening pass:
    every team_id that fails to resolve to a manager anywhere in this
    module is collected into `unresolved` (rather than the previous
    behavior of silently skipping/continuing) and written to
    all_time_unresolved.json, along with any unresolved entries each
    season's own records.json already flagged. A non-empty result here
    means some manager's stats are incomplete and should be investigated
    before trusting the other all_time_*.json files."""
    years = discover_aggregated_seasons()
    unresolved: list[dict] = []

    write_json(AGGREGATED_DIRECTORY / "all_time_champions.json", build_all_time_champions(years, unresolved))
    write_json(AGGREGATED_DIRECTORY / "all_time_manager_stats.json", build_all_time_manager_stats(years, unresolved))
    write_json(AGGREGATED_DIRECTORY / "all_time_records.json", build_all_time_records(years))

    for year in years:
        season_records = read_json(aggregated_path(year, "records.json"))
        for entry in season_records.get("unresolved", []):
            unresolved.append({"season": year, **entry})

    write_json(AGGREGATED_DIRECTORY / "all_time_unresolved.json", {"unresolved": unresolved})
    print(f"wrote all_time_champions.json, all_time_manager_stats.json, all_time_records.json, all_time_unresolved.json (seasons={years})")
    if unresolved:
        print(f"WARNING: {len(unresolved)} unresolved team_id -> manager lookups found - see all_time_unresolved.json")


if __name__ == "__main__":
    aggregate_all_time()
