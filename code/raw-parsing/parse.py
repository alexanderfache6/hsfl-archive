"""HTML -> JSON parsers, one per output file type. See instructions.md section 2 for schemas.

Structural notes confirmed 2026-08-06 against the 2025 season, applicable
to all years unless a season's markup differs:
- Roster/box-score stat columns carry a `stat_{N}` class matching the
  scoring rule stat IDs from settings.html, so a stat can be traced back
  to its point value.
- Manager identity is a persistent NFL.com `userId-{N}` embedded in a
  `.userName` span wherever a team's manager is shown (schedule, game
  center, transactions) - use this as manager_id, not fuzzy name matching.
- schedule.html without a `?week=` parameter only returns week 1. Full
  schedule/matchup data is instead derived from the already-fetched
  per-team gamecenter pages (see parse_schedule_from_gamecenters and
  parse_matchup_week below), which each expose both teams' team_id and
  user_id in the matchup header.
"""

import re

from bs4 import BeautifulSoup


def _extract_name_value_pairs(container) -> list[tuple[str, str]]:
    """Generic (label, value) extractor for the em + .value li pattern used
    across leagueSettings, scoreSettings, and confirmationPreview blocks."""
    pairs = []
    for li in container.select("li"):
        label_element = li.select_one("em")
        value_element = li.select_one(".value")
        if label_element and value_element:
            key = label_element.get_text(strip=True).rstrip(":")
            value = value_element.get_text(strip=True)
            pairs.append((key, value))
    return pairs


ROSTER_POSITION_LABEL_TO_KEY = {
    "Quarterback": "QB",
    "Running Back": "RB",
    "Wide Receiver": "WR",
    "Tight End": "TE",
    "Wide Receiver / Running Back": "FLEX",
    "Kicker": "K",
    "Defensive Team": "DEF",
    "Bench": "BENCH",
    "Reserve": "RESERVE",
}


def parse_metadata(settings_html: str, standings_final_html: str, year: int) -> dict:
    """Team list source changed 2026-08-07: was schedule.html week 1's
    matchups, which silently omits any team with a week-1 bye (odd team
    count, a team not yet active, etc - a real risk once Phase E hits
    seasons with a different team/manager roster than 2024/2025).
    standings.html lists every team regardless of any single week's
    schedule, so it's used for the team_id/team_name list instead.
    Manager identity comes from each team's own team_home.html (fetched
    once per team_id, independent of any week) rather than schedule.html's
    week-1 matchup header - see raw_path(..., team_id=...) below.
    """
    settings_soup = BeautifulSoup(settings_html, "lxml")

    confirmation_preview = settings_soup.select_one(".mod.confirmationPreview")
    header_pairs = []
    for key, value in _extract_name_value_pairs(confirmation_preview):
        if key == "Divisions":  # league settings repeat from here on - stop
            break
        header_pairs.append((key, value))
    header = dict(header_pairs)

    league_settings_mod = settings_soup.select_one(".mod.leagueSettings")
    general_settings_list = league_settings_mod.select_one("ul.formItems:not(.positionsAndRoster)")
    roster_settings_list = league_settings_mod.select_one("ul.positionsAndRoster")
    general_settings = dict(_extract_name_value_pairs(general_settings_list))
    roster_settings = {
        ROSTER_POSITION_LABEL_TO_KEY.get(label, label): int(value)
        for label, value in _extract_name_value_pairs(roster_settings_list)
        if value.isdigit()
    }

    score_settings_mod = settings_soup.select_one(".mod.scoreSettings")
    scoring_rules = dict(_extract_name_value_pairs(score_settings_mod))

    draft_format = header.get("Draft Format", "")
    draft_type = "auction" if "salary cap" in draft_format.lower() or "auction" in draft_format.lower() else "snake"
    draft_date_match = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", header.get("Draft Type", ""))
    draft_date = draft_date_match.group(1) if draft_date_match else ""

    from utils import raw_path  # file-access exception, same precedent as parse_schedule_from_gamecenters

    standings_soup = BeautifulSoup(standings_final_html, "lxml")
    teams = []
    unresolved_teams = []
    seen_team_ids = set()
    for team_name_element in standings_soup.select("a.teamName"):
        team_id_match = re.search(r"teamId-(\d+)", " ".join(team_name_element.get("class", [])))
        if not team_id_match:
            continue
        team_id = team_id_match.group(1)
        if team_id in seen_team_ids:  # standings.html repeats the #1 team in both the champion block and the ranked list
            continue
        seen_team_ids.add(team_id)
        team_name = team_name_element.get_text(strip=True)

        manager_id, manager_display_name = "", ""
        team_home_path = raw_path(year, "team_home.html", team_id=team_id)
        if team_home_path.exists():
            user_name_element = BeautifulSoup(team_home_path.read_text(), "lxml").select_one(".userName")
            if user_name_element:
                user_id_match = re.search(r"userId-(\d+)", " ".join(user_name_element.get("class", [])))
                manager_id = user_id_match.group(1) if user_id_match else ""
                manager_display_name = user_name_element.get_text(strip=True)

        if not manager_id:
            unresolved_teams.append({"team_id": team_id, "team_name": team_name, "reason": "no manager userId found on team_home.html"})

        teams.append({"team_id": team_id, "team_name": team_name, "manager_id": manager_id, "manager_display_name": manager_display_name})

    expected_team_count = int(general_settings.get("Teams", 0) or 0)
    notes = ""
    if expected_team_count and len(teams) != expected_team_count:
        notes = f"Team count mismatch: settings.html reports {expected_team_count} teams but standings.html yielded {len(teams)} - investigate before trusting this season's data."

    return {
        "season": year,
        "league_id": header.get("League ID", ""),
        "league_name": header.get("League Name", ""),
        "commissioner": header.get("Commissioner", ""),
        "settings": {
            "num_teams": expected_team_count,
            "roster_settings": roster_settings,
            "waiver_type": general_settings.get("Waiver Type", ""),
            "trade_deadline": general_settings.get("Trade Deadline", ""),
            "playoff_teams_and_weeks": general_settings.get("Playoffs", ""),
        },
        "scoring_rules": scoring_rules,
        "draft_info": {
            "draft_type": draft_type,
            "draft_date": draft_date,
            "draft_format_raw": draft_format,
        },
        "teams": teams,
        "unresolved_teams": unresolved_teams,
        "source_urls": [],
        "fetch_status": "ok",
        "notes": notes,
    }


def _parse_ordinal_rank(place_text: str) -> int:
    match = re.match(r"(\d+)", place_text)
    return int(match.group(1)) if match else 0


def parse_standings(standings_final_html: str, standings_regular_html: str, year: int) -> dict:
    final_soup = BeautifulSoup(standings_final_html, "lxml")
    regular_soup = BeautifulSoup(standings_regular_html, "lxml")

    regular_by_team_id = {}
    for row in regular_soup.select("#leagueHistoryStandings table tbody tr"):
        team_id_element = row.select_one(".teamRank[class*='teamId-']")
        team_id_match = re.search(r"teamId-(\d+)", " ".join(team_id_element.get("class", []))) if team_id_element else None
        if not team_id_match:
            continue
        team_id = team_id_match.group(1)
        record_text = row.select_one(".teamRecord").get_text(strip=True)
        wins, losses, ties = (int(part) for part in record_text.split("-"))
        points_for = float(row.select_one(".teamPts").get_text(strip=True).replace(",", ""))
        points_against = float(row.select(".teamPts")[1].get_text(strip=True).replace(",", ""))
        regular_by_team_id[team_id] = {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "points_for": points_for,
            "points_against": points_against,
        }

    final_standings = []
    for index, item in enumerate(final_soup.select("#championResults .results li"), start=1):
        team_name_element = item.select_one("a.teamName")
        if not team_name_element:
            continue
        team_id_match = re.search(r"teamId-(\d+)", " ".join(team_name_element.get("class", [])))
        team_id = team_id_match.group(1) if team_id_match else ""
        place_text = item.select_one(".place").get_text(strip=True)
        rank = _parse_ordinal_rank(place_text)
        record = regular_by_team_id.get(team_id, {})
        final_standings.append(
            {
                "rank": rank,
                "team_id": team_id,
                "team_name": team_name_element.get_text(strip=True),
                "wins": record.get("wins"),
                "losses": record.get("losses"),
                "ties": record.get("ties"),
                "points_for": record.get("points_for"),
                "points_against": record.get("points_against"),
                "champion": rank == 1,
            }
        )

    regular_season_standings = []
    for row in regular_soup.select("#leagueHistoryStandings table tbody tr"):
        # td.teamRank wraps both the clean rank (span.teamRank) and a
        # rank-change badge (span.teamRankChange, e.g. "+1") - selecting
        # ".teamRank" alone matches the td first and concatenates both
        # texts (e.g. "2+1"), so target the inner span specifically.
        rank_element = row.select_one("span.teamRank")
        team_name_element = row.select_one("a.teamName")
        if not rank_element or not team_name_element:
            continue
        team_id_match = re.search(r"teamId-(\d+)", " ".join(team_name_element.get("class", [])))
        team_id = team_id_match.group(1) if team_id_match else ""
        record = regular_by_team_id.get(team_id, {})
        regular_season_standings.append(
            {
                "rank": int(rank_element.get_text(strip=True)),
                "team_id": team_id,
                "team_name": team_name_element.get_text(strip=True),
                **record,
            }
        )

    return {
        "season": year,
        "final_standings": final_standings,
        "regular_season_standings": regular_season_standings,
        "notes": "final_standings wins/losses/points are regular-season figures (site doesn't separately expose postseason W-L) - see playoffs.json for actual postseason results.",
    }


def parse_draft(nomination_view_html: str, by_team_view_html: str, year: int) -> dict:
    nomination_soup = BeautifulSoup(nomination_view_html, "lxml")
    results_container = nomination_soup.select_one("#leagueDraftResultsResults .results")

    bid_amount_by_player_id = {}
    by_team_soup = BeautifulSoup(by_team_view_html, "lxml")
    for pick_row in by_team_soup.select("#leagueDraftResultsResults li"):
        player_link = pick_row.select_one("a.playerName")
        if not player_link:
            continue
        player_id_match = re.search(r"playerNameId-(\d+)", " ".join(player_link.get("class", [])))
        if not player_id_match:
            continue
        amount_match = re.search(r"\$(\d+)", pick_row.get_text())
        if amount_match:
            bid_amount_by_player_id[player_id_match.group(1)] = int(amount_match.group(1))

    is_auction = results_container.select_one("li.isAuction") is not None

    picks = []
    overall_pick = 0
    for wrap in results_container.find_all("div", class_="wrap", recursive=False):
        pick_list = wrap.select_one("ul")
        if not pick_list:
            continue
        for pick_element in pick_list.find_all("li", recursive=False):
            overall_pick += 1
            player_link = pick_element.select_one("a.playerName")
            if not player_link:
                continue
            player_id_match = re.search(r"playerNameId-(\d+)", " ".join(player_link.get("class", [])))
            player_id = player_id_match.group(1) if player_id_match else ""
            position_team_text = pick_element.select_one("div.c em").get_text(strip=True)
            position, _, nfl_team = position_team_text.partition(" - ")
            team_name_element = pick_element.select_one("span.tw a.teamName")
            team_id_match = re.search(r"teamId-(\d+)", " ".join(team_name_element.get("class", []))) if team_name_element else None
            picks.append(
                {
                    "overall_pick": overall_pick,
                    "player_id": player_id,
                    "player_name": player_link.get_text(strip=True),
                    "position": position,
                    "nfl_team": nfl_team,
                    "team_id": team_id_match.group(1) if team_id_match else "",
                    "auction_amount": bid_amount_by_player_id.get(player_id),
                }
            )

    return {
        "season": year,
        "draft_type": "auction" if is_auction else "snake",
        "picks": picks,
        "notes": "auction_amount is null for keeper picks (no auctionCost span in source markup - keepers are set before the live auction starts, confirmed 2026-08-06 against the 2025 season's 1-keeper league setting).",
    }


def _parse_playoff_bracket(bracket_html: str) -> dict:
    soup = BeautifulSoup(bracket_html, "lxml")
    bracket_container = soup.select_one(".mod.playoffs .content")
    rounds = []
    for round_order, week_block in enumerate(bracket_container.select("ul.playoffContent > li"), start=1):
        week_label = week_block.select_one("h4").get_text(strip=True) if week_block.select_one("h4") else ""
        matchups = []
        for bracket_position, game in enumerate(week_block.select("ul > li"), start=1):
            round_name_element = game.select_one("h5")
            round_name = round_name_element.get_text(strip=True) if round_name_element else week_label
            team_wraps = game.select(".teamWrap")
            if len(team_wraps) < 1:
                continue

            def team_info(wrap):
                if "teamWrap-bye" in wrap.get("class", []):
                    return None
                name_element = wrap.select_one("a.teamName")
                if not name_element:
                    return None
                team_id_match = re.search(r"teamId-(\d+)", " ".join(name_element.get("class", [])))
                seed_element = wrap.select_one(".teamRank")
                seed_match = re.search(r"\((\d+)\)", seed_element.get_text(strip=True)) if seed_element else None
                score_element = wrap.select_one(".teamTotal")
                score = float(score_element.get_text(strip=True)) if score_element and score_element.get_text(strip=True) else None
                return {
                    "team_id": team_id_match.group(1) if team_id_match else "",
                    "seed": int(seed_match.group(1)) if seed_match else None,
                    "score": score,
                }

            home_info = team_info(team_wraps[0]) if len(team_wraps) > 0 else None
            away_info = team_info(team_wraps[1]) if len(team_wraps) > 1 else None
            winner_team_id = ""
            game_classes = game.get("class", [])
            if "win" in game_classes and home_info:
                winner_team_id = home_info["team_id"]
            elif "loss" in game_classes and away_info:
                winner_team_id = away_info["team_id"]

            matchups.append(
                {
                    "bracket_position": bracket_position,
                    "round_label": round_name,
                    "week_label": week_label,
                    "seed_home": home_info["seed"] if home_info else None,
                    "team_id_home": home_info["team_id"] if home_info else "",
                    "score_home": home_info["score"] if home_info else None,
                    "seed_away": away_info["seed"] if away_info else None,
                    "team_id_away": away_info["team_id"] if away_info else "",
                    "score_away": away_info["score"] if away_info else None,
                    "is_bye": away_info is None,
                    "winner_team_id": winner_team_id,
                }
            )
        rounds.append({"round_name": week_label, "round_order": round_order, "matchups": matchups})
    return {"rounds": rounds}


def _placement_number(round_label: str) -> int | None:
    """Extracts the "Nth" from a placement game label. "Fantasy Super
    Bowl"/"Super Bowl"/"Championship" (any label containing one of those)
    is placement 1. Confirmed 2026-08-06 (2025 data): both brackets share
    this "Nth Place Game" naming, with the championship side counting
    from 1st and the consolation side continuing the sequence (7th, 9th,
    11th for this league's 10 teams) - so the lowest placement number in
    a bracket's final round is always that bracket's own "title game",
    regardless of which numbers appear.

    Bug found and fixed 2026-08-07 (2012 data): the title-game label
    isn't always "Fantasy Super Bowl" - a smaller/earlier-year bracket
    used the literal label "Championship" instead, which this function
    didn't recognize, so _find_bracket_winner() fell through to the only
    OTHER placement-labeled game that round ("3rd Place Game") and
    crowned its winner as champion instead of the actual championship
    game's winner. Confirmed the real winner by comparing scores directly
    against the raw bracket HTML before fixing."""
    label_lower = round_label.lower()
    if "super bowl" in label_lower or "championship" in label_lower:
        return 1
    match = re.search(r"(\d+)(?:st|nd|rd|th)\s+Place", round_label, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _find_bracket_winner(rounds: list[dict]) -> tuple[str, str]:
    """Returns (winner_team_id, runner_up_team_id) for a bracket by finding
    the lowest-placement-number complete game in the final round."""
    if not rounds:
        return "", ""
    final_round_matchups = rounds[-1]["matchups"]
    candidates = [
        (placement, m)
        for m in final_round_matchups
        if (placement := _placement_number(m["round_label"])) is not None and m["winner_team_id"]
    ]
    if not candidates:
        return "", ""
    _, title_game = min(candidates, key=lambda pair: pair[0])
    winner_team_id = title_game["winner_team_id"]
    runner_up_team_id = title_game["team_id_away"] if winner_team_id == title_game["team_id_home"] else title_game["team_id_home"]
    return winner_team_id, runner_up_team_id


def parse_playoffs(championship_html: str, consolation_html: str, year: int) -> dict:
    championship_bracket = _parse_playoff_bracket(championship_html)
    consolation_bracket = _parse_playoff_bracket(consolation_html)

    champion_team_id, runner_up_team_id = _find_bracket_winner(championship_bracket["rounds"])
    consolation_winner_team_id, _ = _find_bracket_winner(consolation_bracket["rounds"])

    return {
        "season": year,
        "championship_bracket": {**championship_bracket, "champion_team_id": champion_team_id, "runner_up_team_id": runner_up_team_id},
        "consolation_bracket": {**consolation_bracket, "consolation_winner_team_id": consolation_winner_team_id},
        "source_urls": [],
        "fetch_status": "ok",
        "notes": "Byes and placement-game structure vary by season - see instructions.md section 2 notes.",
    }


def _matchup_header_teams(gamecenter_soup) -> list[dict]:
    header = gamecenter_soup.select_one("#teamMatchupHeader")
    teams = []
    for team_name_element in header.select("a.teamName"):
        team_id_match = re.search(r"teamId-(\d+)", " ".join(team_name_element.get("class", [])))
        team_id = team_id_match.group(1) if team_id_match else ""
        total_element = header.select_one(f".teamTotal.teamId-{team_id}")
        teams.append(
            {
                "team_id": team_id,
                "team_name": team_name_element.get_text(strip=True),
                "score": float(total_element.get_text(strip=True).replace(",", "")) if total_element and total_element.get_text(strip=True) else None,
            }
        )
    return teams


def parse_schedule_from_gamecenters(year: int, team_ids: list[str], weeks: list[int]) -> dict:
    """Builds schedule.json by reading each already-fetched gamecenter page
    rather than schedule.html (which only returns week 1 without a week
    query param - see module docstring)."""
    from utils import raw_path

    weeks_output = []
    for week in weeks:
        seen_matchup_team_pairs = set()
        matchups = []
        for team_id in team_ids:
            gamecenter_path = raw_path(year, f"gamecenter_week_{week}.html", team_id=team_id)
            if not gamecenter_path.exists():
                continue
            soup = BeautifulSoup(gamecenter_path.read_text(), "lxml")
            teams = _matchup_header_teams(soup)
            if len(teams) != 2:
                continue
            pair_key = frozenset(t["team_id"] for t in teams)
            if pair_key in seen_matchup_team_pairs:
                continue
            seen_matchup_team_pairs.add(pair_key)
            matchups.append(
                {
                    "team_id_home": teams[0]["team_id"],
                    "team_id_away": teams[1]["team_id"],
                    "matchup_id": f"{year}_w{week}_{teams[0]['team_id']}_{teams[1]['team_id']}",
                }
            )
        weeks_output.append({"week": week, "matchups": matchups})
    return {"season": year, "weeks": weeks_output}


def _parse_box_score_table(table) -> list[dict]:
    players = []
    for row in table.select("tbody tr"):
        position_element = row.select_one("td.teamPosition")
        position_label = position_element.get_text(strip=True) if position_element else ""
        if not position_label:  # separator rows (e.g. "benchLabel") carry no position text
            continue
        name_element = row.select_one("a.playerName")
        if not name_element:
            continue
        info_element = row.select_one("td.playerNameAndInfo em")
        position, _, nfl_team = (info_element.get_text(strip=True).partition(" - ") if info_element else ("", "", ""))
        opponent_element = row.select_one("td.playerOpponent")
        stats = {}
        points = None
        for stat_cell in row.select("td.stat"):
            cell_classes = stat_cell.get("class", [])
            value_text = stat_cell.get_text(strip=True)
            if "statTotal" in cell_classes:
                points = float(value_text) if value_text else None
                continue
            stat_id_match = re.search(r"stat_(\d+)", " ".join(cell_classes))
            if stat_id_match and value_text not in ("", "-"):
                stats[f"stat_{stat_id_match.group(1)}"] = value_text
        # Gamecenter box-score rows (as opposed to roster-page rows) pack
        # stats into <span class="statId-N"><b>value</b></span> elements
        # inside a single td.playerStats cell instead of one td per stat.
        player_stats_cell = row.select_one("td.playerStats")
        if player_stats_cell:
            for stat_span in player_stats_cell.select("span[class*=statId-]"):
                stat_id_match = re.search(r"statId-(\d+)", " ".join(stat_span.get("class", [])))
                value_element = stat_span.select_one("b")
                value_text = value_element.get_text(strip=True) if value_element else ""
                if stat_id_match and value_text:
                    stats[f"stat_{stat_id_match.group(1)}"] = value_text
        player_id_match = re.search(r"playerNameId-(\d+)", " ".join(name_element.get("class", [])))
        players.append(
            {
                "slot": position_label,
                "player_id": player_id_match.group(1) if player_id_match else "",
                "player_name": name_element.get_text(strip=True),
                "position": position,
                "nfl_team": nfl_team,
                "opp": opponent_element.get_text(strip=True) if opponent_element else "",
                "points": points,
                "stats": stats,
            }
        )
    return players


def parse_matchup_week(gamecenter_html: str, year: int, week: int) -> dict:
    soup = BeautifulSoup(gamecenter_html, "lxml")
    teams = _matchup_header_teams(soup)
    box_score = soup.select_one("#teamMatchupBoxScore")
    tables = box_score.select("table") if box_score else []
    # confirmed order: tableWrap-1 (home starters), tableWrapBN-1 (home bench),
    # tableWrap-2 (away starters), tableWrapBN-2 (away bench)
    home_starters = _parse_box_score_table(tables[0]) if len(tables) > 0 else []
    home_bench = _parse_box_score_table(tables[1]) if len(tables) > 1 else []
    away_starters = _parse_box_score_table(tables[2]) if len(tables) > 2 else []
    away_bench = _parse_box_score_table(tables[3]) if len(tables) > 3 else []

    home_team = teams[0] if len(teams) > 0 else {"team_id": "", "score": None}
    away_team = teams[1] if len(teams) > 1 else {"team_id": "", "score": None}

    return {
        "season": year,
        "week": week,
        "matchup_id": f"{year}_w{week}_{home_team['team_id']}_{away_team['team_id']}",
        "home": {"team_id": home_team["team_id"], "score": home_team["score"], "starters": home_starters, "bench": home_bench},
        "away": {"team_id": away_team["team_id"], "score": away_team["score"], "starters": away_starters, "bench": away_bench},
    }


def parse_transactions_page(html_content: str, year: int) -> list[dict]:
    soup = BeautifulSoup(html_content, "lxml")
    table = soup.select_one("#leagueTransactions table")
    if not table:
        return []

    transactions = []
    for row in table.select("tbody tr"):
        date_element = row.select_one("td.transactionDate")
        week_element = row.select_one("td.transactionWeek")
        type_element = row.select_one("td.transactionType")
        info_cell = row.select_one("td.playerNameAndInfo")
        player_name_element = info_cell.select_one("a.playerName") if info_cell else None
        from_element = row.select_one("td.transactionFrom")
        to_element = row.select_one("td.transactionTo")
        owner_user_element = row.select_one("td.transactionOwner .userName")
        if not date_element:
            continue
        owner_user_id_match = re.search(r"userId-(\d+)", " ".join(owner_user_element.get("class", []))) if owner_user_element else None
        # Commissioner/league-change rows ("LM" type) have no player link -
        # the whole cell is a free-text message (colspan="3") instead, e.g.
        # "Ashwin changed Draft Time to 'Sep 3, 2025 8:00pm PDT'". Capture
        # it rather than silently leaving player_name/from/to empty.
        message = "" if player_name_element or not info_cell else info_cell.get_text(strip=True)
        transactions.append(
            {
                "date": date_element.get_text(strip=True),
                "week": int(week_element.get_text(strip=True)) if week_element and week_element.get_text(strip=True).isdigit() else None,
                "type": type_element.get_text(strip=True) if type_element else "",
                "player_name": player_name_element.get_text(strip=True) if player_name_element else "",
                "from": from_element.get_text(strip=True) if from_element else "",
                "to": to_element.get_text(strip=True) if to_element else "",
                "message": message,
                "by_manager_id": owner_user_id_match.group(1) if owner_user_id_match else "",
                "by_manager_display_name": owner_user_element.get_text(strip=True) if owner_user_element else "",
            }
        )
    return transactions


def _gamecenter_stats_by_player_id(gamecenter_html: str, team_id: str) -> dict:
    """Extracts {player_id: (points, stats)} for one team's own box score
    tables out of a gamecenter page (see bug 4 in bugs.md: this is the
    genuinely week-specific data source, unlike the roster page)."""
    soup = BeautifulSoup(gamecenter_html, "lxml")
    teams = _matchup_header_teams(soup)
    box_score = soup.select_one("#teamMatchupBoxScore")
    tables = box_score.select("table") if box_score else []
    # tableWrap-1/tableWrapBN-1 = home starters/bench, -2 = away. Use
    # whichever side matches team_id, defaulting to home (index 0) if the
    # header couldn't be read (bye weeks only have one side anyway).
    is_away = len(teams) > 1 and teams[1]["team_id"] == team_id and teams[0]["team_id"] != team_id
    starters_index, bench_index = (2, 3) if is_away else (0, 1)
    players = []
    if len(tables) > starters_index:
        players.extend(_parse_box_score_table(tables[starters_index]))
    if len(tables) > bench_index:
        players.extend(_parse_box_score_table(tables[bench_index]))
    return {p["player_id"]: (p["points"], p["stats"]) for p in players if p["player_id"]}


def parse_roster(html_content: str, year: int, team_id: str, week: int, gamecenter_html: str | None = None) -> dict:
    """Roster composition/slots come from the roster page (teamhome?...&week=).
    points/stats are overridden from the team's own gamecenter page when
    provided, since the roster page's own stat columns are season-cumulative
    totals, not week-specific - see bugs.md bug 4. Falls back to the roster
    page's (wrong) values if no gamecenter page is available for that
    team/week (e.g. a bye), rather than silently dropping the player."""
    soup = BeautifulSoup(html_content, "lxml")
    all_players = []
    for table_id in ("tableWrap-O", "tableWrap-K", "tableWrap-DT"):
        table_wrap = soup.select_one(f"#{table_id} table")
        if table_wrap:
            all_players.extend(_parse_box_score_table(table_wrap))

    if gamecenter_html:
        weekly_stats_by_player_id = _gamecenter_stats_by_player_id(gamecenter_html, team_id)
        for player in all_players:
            weekly_points_and_stats = weekly_stats_by_player_id.get(player["player_id"])
            if weekly_points_and_stats:
                player["points"], player["stats"] = weekly_points_and_stats

    bench_slot_labels = {"BN", "RES"}
    starters = [player for player in all_players if player["slot"] not in bench_slot_labels]
    bench = [player for player in all_players if player["slot"] in bench_slot_labels]

    return {
        "season": year,
        "team_id": team_id,
        "week": week,
        "starters": starters,
        "bench": bench,
    }
