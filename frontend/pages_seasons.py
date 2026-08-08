"""Seasons tab - weekly stat tables/charts and season aggregates for a
single selected season. See execution-plan.md Phase G.
"""

# ========================================
# IMPORTS
# ========================================

import html
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    contrasting_text_color,
    discover_seasons,
    load_matchups,
    load_metadata,
    load_playoffs,
    load_post_season_stats,
    load_team_logo_data_uri,
    load_transactions,
    load_weekly_tables,
    resolve_manager_name,
    team_id_to_manager_map,
)
from pages_history import CHAMPION_COLOR, RUNNER_UP_COLOR, THIRD_PLACE_COLOR

# ========================================
# CONSTANTS
# ========================================

BRACKET_NEUTRAL_COLOR = "#888888"
BRACKET_CARD_HEIGHT_PX = 190
BRACKET_CARD_GAP_PX = 40
BRACKET_ROW_UNIT_PX = BRACKET_CARD_HEIGHT_PX + BRACKET_CARD_GAP_PX
BRACKET_HEADER_HEIGHT_PX = 40

TRANSACTIONS_PAGE_SIZE = 10

PODIUM_BLOCK_HEIGHT_PX = {1: 250, 2: 190, 3: 140}
PODIUM_COLOR = {1: CHAMPION_COLOR, 2: RUNNER_UP_COLOR, 3: THIRD_PLACE_COLOR}
PODIUM_LABEL = {1: "1st", 2: "2nd", 3: "3rd"}
PODIUM_DISPLAY_ORDER = [2, 1, 3]

PODIUM_LOGO_SIZE_PX = {1: 120, 2: 100, 3: 90}
PODIUM_LOGO_GAP_PX = 10

PODIUM_EMOJI = {1: "🏆", 2: "🥈", 3: "🥉"}
LAST_PLACE_EMOJI = "🥞"

SCHEDULE_ROW_COLUMN_RATIOS = [4, 1.2, 4]

# ========================================
# FUNCTIONS
# ========================================


def _full_table_height(row_count: int) -> int:
    """Same sizing rule as the History tab's tables - st.dataframe
    defaults to a fixed max height with internal scrolling once a table
    has more rows than fit; passing an explicit height instead shows
    every row with no fold/scroll."""
    return 38 + 35 * row_count


def _parse_transaction_date(date_text: str, season: int) -> datetime:
    """"Dec 28, 4:33pm" + season -> a real datetime. A season's playoffs
    can run into January of the FOLLOWING calendar year (confirmed for
    2012, 2021, 2022) - only "Jan" dates get season+1, everything else
    (Aug-Dec) uses the season's own year."""
    month_text = date_text.split(" ", 1)[0]
    year = season + 1 if month_text == "Jan" else season
    return datetime.strptime(f"{date_text} {year}", "%b %d, %I:%M%p %Y")


def _bracket_effective_winner(game: dict) -> str:
    """A bye game has no winner_team_id (nobody actually played) - the
    lone present team advances automatically, so it's treated as this
    game's "winner" for the purpose of wiring a connector into the next
    round. Some brackets (e.g. 2023's 6-team championship bracket) also
    have a round-1-loser "continues on" slot that has only one side
    filled but is NOT flagged is_bye - checking "exactly one side
    present" directly (rather than trusting is_bye) catches those too."""
    if game["winner_team_id"]:
        return game["winner_team_id"]
    home, away = game["team_id_home"], game["team_id_away"]
    if bool(home) != bool(away):
        return home or away
    return ""


def _bracket_team_label(team_id: str, seed: int | None, team_info: dict[str, dict], name_resolver: dict[str, str]) -> str:
    info = team_info.get(team_id, {})
    team_name = info.get("team_name", "")
    manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))
    seed_text = f"#{seed} " if seed else ""
    return f"{seed_text}{team_name} ({manager_name})"


def _bracket_highlight_style(team_id: str, winner_team_id: str, team_info: dict[str, dict], manager_color_map: dict[str, str]) -> str:
    """Background-color + contrasting text-color for the winning side's
    name/score lines - same manager-color-highlight convention as the
    Matchups page's own matchup cards - empty string (no highlight) for
    the losing side."""
    if team_id != winner_team_id:
        return ""
    manager_id = team_info.get(team_id, {}).get("manager_id", "")
    background_color = manager_color_map.get(manager_id, BRACKET_NEUTRAL_COLOR)
    text_color = contrasting_text_color(background_color)
    return f"background-color:{background_color}; color:{text_color}; border-radius:4px;"


def _bracket_game_card_html(
    game: dict,
    top_px: float,
    team_info: dict[str, dict],
    name_resolver: dict[str, str],
    manager_color_map: dict[str, str],
    round_label: str,
    path_team_id: str,
) -> str:
    """Reusable single-game card - one call site per bracket (Championship,
    Consolation), used for every round. Byes render as a single
    auto-advancing team with no opponent line. Returns an absolutely
    positioned HTML div (not an st.container - no invisible spacer
    containers needed to push it to the right row; its "top" is the exact
    pixel the connector math also uses, so lines tie to the true card
    center). round_label is the DISPLAY label (see
    _bracket_display_round_label) - not always game["round_label"]
    verbatim, since some rounds need one synthesized. path_team_id is that
    bracket's eventual winner (champion_team_id / consolation_winner_
    team_id) - every game they played in (not just the ones they won)
    gets a light gray card background, tracing their whole route through
    the bracket at a glance."""
    winner_team_id = _bracket_effective_winner(game)
    on_winning_path = bool(path_team_id) and path_team_id in (game["team_id_home"], game["team_id_away"])
    card_background = "background:#F0F0F0; " if on_winning_path else ""

    lines_html = []
    if round_label:
        lines_html.append(f'<div style="font-size:0.75rem; opacity:0.7; margin-bottom:6px;">{html.escape(round_label)}</div>')

    # "Only one side present" (not the is_bye flag, which some brackets
    # leave False on a loser's "continues on" slot with an empty
    # opponent - see _bracket_effective_winner) is what actually
    # determines whether this is a single-team card.
    if bool(game["team_id_home"]) != bool(game["team_id_away"]):
        lone_team_id = game["team_id_home"] or game["team_id_away"]
        lone_seed = game["seed_home"] or game["seed_away"]
        lone_label = html.escape(_bracket_team_label(lone_team_id, lone_seed, team_info, name_resolver))
        lone_highlight = _bracket_highlight_style(lone_team_id, winner_team_id, team_info, manager_color_map)
        lines_html.append(f'<div style="text-align:center; padding:2px 0; {lone_highlight}"><strong>{lone_label}</strong></div>')
        lines_html.append('<div style="text-align:center; padding:2px 0; opacity:0.7; font-style:italic;">Bye</div>')
    else:
        home_label = html.escape(_bracket_team_label(game["team_id_home"], game["seed_home"], team_info, name_resolver))
        away_label = html.escape(_bracket_team_label(game["team_id_away"], game["seed_away"], team_info, name_resolver))
        home_html = f"<strong>{home_label}</strong>" if game["team_id_home"] == winner_team_id else home_label
        away_html = f"<strong>{away_label}</strong>" if game["team_id_away"] == winner_team_id else away_label
        score_home_text = f"{game['score_home']:.2f}" if game["score_home"] is not None else "—"
        score_away_text = f"{game['score_away']:.2f}" if game["score_away"] is not None else "—"
        score_home_html = f"<strong>{score_home_text}</strong>" if game["team_id_home"] == winner_team_id else score_home_text
        score_away_html = f"<strong>{score_away_text}</strong>" if game["team_id_away"] == winner_team_id else score_away_text
        home_highlight = _bracket_highlight_style(game["team_id_home"], winner_team_id, team_info, manager_color_map)
        away_highlight = _bracket_highlight_style(game["team_id_away"], winner_team_id, team_info, manager_color_map)
        # Row 1 = round label (above), row 2 = team 1 name, row 3 = team 1
        # score, row 4 = "vs", row 5 = team 2 score, row 6 = team 2 name.
        # A winning side's name+score are ONE outer div (one continuous
        # highlighted box spanning both lines), not two separately
        # highlighted divs - the inner name/score lines carry no
        # background of their own, just the outer wrapper.
        lines_html.append(
            f'<div style="text-align:center; padding:2px 0; {home_highlight}"><div>{home_html}</div><div>{score_home_html}</div></div>'
        )
        lines_html.append('<div style="text-align:center; padding:2px 0; opacity:0.6;">vs</div>')
        lines_html.append(
            f'<div style="text-align:center; padding:2px 0; {away_highlight}"><div>{score_away_html}</div><div>{away_html}</div></div>'
        )

    return (
        f'<div style="position:absolute; top:{top_px}px; left:0; width:100%; box-sizing:border-box; '
        f'{card_background}border:2px solid black; border-radius:8px; padding:10px; '
        f'height:{BRACKET_CARD_HEIGHT_PX}px; overflow:hidden;">{"".join(lines_html)}</div>'
    )


def _layout_bracket_rounds(
    rounds: list[dict],
) -> tuple[list[tuple[int, str, list[tuple[dict, float]]]], list[tuple[int, float, int, float, str]]]:
    """Assigns each game a vertical "row" (row 0 = top): round-1 games get
    evenly spaced whole-number rows in bracket_position order; every later
    round's game whose team(s) can be traced back to a specific prior-round
    game ("connected") is centered on the average row of the game(s) it
    drew its two teams from (found via each team's most recent
    advancement, not by assuming a fixed bracket_position parent/child
    shape - some rounds mix a semifinal with unrelated placement games, so
    position alone doesn't imply lineage). A round's "orphan" games -
    byes/placement slots with no traceable prior game - are always placed
    BELOW every connected game in that same round, each spaced a full row
    apart, so they never visually overlap the main bracket. A minimum
    1-row gap is also enforced between consecutive connected games for the
    same reason, in case two of them average out to nearly the same row.
    Returns (rounds_with_rows, connectors) where rounds_with_rows entries
    are (round_order, round_name, games) and each connector is
    (from_round_order, from_row, to_round_order, to_row, winner_team_id) -
    winner_team_id colors the connector line."""
    rounds_with_rows: list[tuple[int, str, list[tuple[dict, float]]]] = []
    connectors: list[tuple[int, float, int, float, str]] = []
    last_advanced_from: dict[str, tuple[int, float]] = {}  # team_id -> (round_order, row)
    previous_round_order: int | None = None

    for round_entry in sorted(rounds, key=lambda r: r["round_order"]):
        round_order = round_entry["round_order"]
        games = sorted(round_entry["matchups"], key=lambda g: g["bracket_position"])

        # Pending connectors for this round, target row filled in once
        # every game's final (de-overlapped) row is known below.
        pending_connectors: list[dict] = []
        connected_games: list[tuple[dict, float]] = []
        orphan_games: list[dict] = []

        for game in games:
            source_rows = []
            for team_id in (game["team_id_home"], game["team_id_away"]):
                source = last_advanced_from.get(team_id) if team_id else None
                # Only a team that WON its immediately preceding round (or
                # had a bye there) gets a connector drawn - a team that
                # lost isn't tracked past that loss (see the winner-only
                # update below), and a stale older win (skipping a round)
                # doesn't count as "connected" either, so it can't draw a
                # line spanning past a round it didn't actually win.
                if source is not None and source[0] == previous_round_order:
                    source_round_order, source_row = source
                    source_rows.append(source_row)
                    pending_connectors.append({"from_round": source_round_order, "from_row": source_row, "team_id": team_id, "game": game})
            if source_rows:
                connected_games.append((game, sum(source_rows) / len(source_rows)))
            else:
                orphan_games.append(game)

        connected_games.sort(key=lambda entry: entry[1])

        final_row_by_id: dict[int, float] = {}
        cursor = -1.0
        for game, raw_row in connected_games:
            row = max(raw_row, cursor + 1.0)
            final_row_by_id[id(game)] = row
            cursor = row
        for game in orphan_games:
            cursor += 1.0
            final_row_by_id[id(game)] = cursor

        # A 3-round championship bracket's final round is a special case:
        # the generic connected/orphan ordering above puts the untraceable
        # 3rd Place Game (both entrants LOST their semifinal, so neither
        # is trackable) below the 5th Place Game, purely because it's
        # processed as an orphan after 5th place happens to be
        # "connected" via its own bye-like continuation slots. The 5th
        # Place Game's own row is already correctly centered on its two
        # parent cells (round 2's continuation slots) - leave it as-is.
        # Only reposition the 3rd Place Game, into the otherwise-empty gap
        # between the championship and that already-centered 5th place
        # row, instead of pushing it below everything.
        round_label_set = {game["round_label"] for game in games}
        if round_label_set == {"Fantasy Super Bowl", "3rd Place Game", "5th Place Game"}:
            row_by_label = {game["round_label"]: final_row_by_id[id(game)] for game in games}
            championship_row = row_by_label["Fantasy Super Bowl"]
            fifth_place_row = row_by_label["5th Place Game"]
            third_place_game = next(game for game in games if game["round_label"] == "3rd Place Game")
            gap_top = championship_row + 1.0
            gap_bottom = fifth_place_row - 1.0
            final_row_by_id[id(third_place_game)] = gap_top if gap_top <= gap_bottom else (championship_row + fifth_place_row) / 2

        games_with_rows = [(game, final_row_by_id[id(game)]) for game in games]

        for pending in pending_connectors:
            connectors.append((pending["from_round"], pending["from_row"], round_order, final_row_by_id[id(pending["game"])], pending["team_id"]))

        rounds_with_rows.append((round_order, round_entry["round_name"], games_with_rows))
        for game, row in games_with_rows:
            winner_team_id = _bracket_effective_winner(game)
            if winner_team_id:
                last_advanced_from[winner_team_id] = (round_order, row)
        previous_round_order = round_order

    return rounds_with_rows, connectors


def _bracket_display_round_label(game: dict, round_order: int, max_round_order: int, is_consolation: bool) -> str:
    """The raw round_label (e.g. "Semifinal", "7th Place Game") when the
    data has one - but the consolation bracket's OWN semifinal-equivalent
    round often comes through with an empty round_label (only its later
    placement-game rounds, like "7th Place Game", are labeled), so that
    empty case is synthesized as "Consolation Semifinal" specifically for
    the second-to-last round of the consolation bracket."""
    if game["round_label"]:
        return game["round_label"]
    if is_consolation and round_order == max_round_order - 1:
        return "Consolation Semifinal"
    return ""


def _championship_bye_team_ids(season: int) -> set[str]:
    """Team ids that received a first-round bye in the CHAMPIONSHIP
    bracket only (per request, consolation byes don't count) - just the
    FIRST round's is_bye=True games (real seed-1/seed-2 byes). Later
    rounds can also carry is_bye=True on a "loser continues on" placement
    slot (e.g. 2022's Week 16 pos 4) - restricting to round_order == the
    minimum keeps those out."""
    playoffs = load_playoffs(season)
    if not playoffs:
        return set()
    rounds = playoffs.get("championship_bracket", {}).get("rounds", [])
    if not rounds:
        return set()
    first_round = min(rounds, key=lambda round_entry: round_entry["round_order"])
    return {game["team_id_home"] or game["team_id_away"] for game in first_round["matchups"] if game["is_bye"]}


def _top_three_final_standings(season: int, name_resolver: dict[str, str]) -> dict[int, tuple[str, str, str, str]]:
    """{rank: (team_id, team_name, manager_name, combined_record)} for
    ranks 1-3 - post-season final_placements when available (matches the
    Final Standings tab), falling back to the final week's regular-season
    standings rank for a season with no recorded playoff bracket.
    combined_record sums the regular-season W-L-T with the post-season
    (championship or consolation bracket) W-L, when there was one."""
    team_info = team_id_to_manager_map(season)
    post_season_stats = load_post_season_stats(season)
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        return {}
    regular_season_record_by_team = {row["team_id"]: (row["wins"], row["losses"], row["ties"]) for row in weekly_tables[-1]["standings"]}

    if post_season_stats and post_season_stats.get("final_placements"):
        ranked_team_ids = sorted(post_season_stats["final_placements"].items(), key=lambda entry: entry[1])
    else:
        ranked_team_ids = [(row["team_id"], row["rank"]) for row in weekly_tables[-1]["standings"]]

    top_three = {}
    for team_id, rank in ranked_team_ids:
        if rank not in (1, 2, 3):
            continue
        info = team_info.get(team_id, {})
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))

        wins, losses, ties = regular_season_record_by_team.get(team_id, (0, 0, 0))
        if post_season_stats:
            post_season_record = post_season_stats["championship"].get(team_id) or post_season_stats["consolation"].get(team_id)
            if post_season_record:
                wins += post_season_record["wins"]
                losses += post_season_record["losses"]
                ties += post_season_record["ties"]
        combined_record = f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"

        top_three[rank] = (team_id, team_name, manager_name, combined_record)
    return top_three


def _go_to_game_from_schedule(season: int, week: int, team1_manager_id: str, team2_manager_id: str) -> None:
    """Jumps to the Games page pre-filtered to this exact matchup, same
    st.switch_page pattern as the History tab's _go_to_game - must be
    called from the main script body (not a button's on_click callback),
    since st.switch_page is a no-op/error from within a callback."""
    st.session_state["games_team1_manager_id"] = team1_manager_id
    st.session_state["games_season"] = season
    st.session_state["games_week"] = week
    st.session_state["games_team2_manager_id"] = team2_manager_id
    st.session_state["games_matchup_type"] = "regular"
    st.session_state["games_filters_generation"] = st.session_state.get("games_filters_generation", 0) + 1
    st.session_state["games_applied_filters"] = {
        "season": season,
        "week": week,
        "team1_manager_id": team1_manager_id,
        "team2_manager_id": team2_manager_id,
        "matchup_type": "regular",
    }
    st.switch_page(st.session_state["_games_page"])


# ========================================
# RENDER
# ========================================


def _render_standings_table(season: int, name_resolver: dict[str, str]) -> None:
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        st.info("No standings available for this season yet.")
        return

    # The final week's standings row is already CUMULATIVE through that
    # week (standings.py builds each week's row as a running total, not
    # just that week's own result) - so it's exactly the season's current
    # (or, once finished, final) standings, no separate aggregation needed.
    current_standings = weekly_tables[-1]["standings"]
    team_info = team_id_to_manager_map(season)

    rows = []
    for row in current_standings:
        info = team_info.get(row["team_id"], {})
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))
        rows.append(
            {
                "Rank": row["rank"],
                # Plain text for now - clicking a team name will open a
                # modal (team name, image, stats, etc), per user
                # direction that modal's design is a separate discussion.
                "Team": f"{team_name} ({manager_name})",
                "W-L-T": f"{row['wins']}-{row['losses']}-{row['ties']}",
                "Win %": row["win_pct"],
                # Signed int (not the raw "W5"/"L3" text) so Streamlit's
                # built-in click-to-sort on this column orders it
                # correctly: W5...W1, L1...L5 (a continuous "how good is
                # this streak" scale) - a text column would sort
                # alphabetically instead (W5...W1, L5...L1), since there's
                # no way to give st.dataframe's interactive sort a custom
                # comparator. +d format keeps the sign visible either way.
                "Streak": int(row["win_streak"][1:]) * (1 if row["win_streak"][0] == "W" else -1) if row["win_streak"] else 0,
                "Points For": row["points_for"],
                "Points Against": row["points_against"],
            }
        )
    dataframe = pd.DataFrame(rows).sort_values("Rank")

    # Same green/red used elsewhere in the app (Games tab's optimal-lineup
    # gains/losses). Alpha scales with streak length instead of a flat
    # tint - a 1-game streak stays light, longer streaks get
    # progressively darker, capped so text stays legible even at very
    # long streaks.
    def _highlight_streak(value: int) -> str:
        if value == 0:
            return ""
        alpha = min(0.15 + 0.08 * (abs(value) - 1), 0.85)
        color = "46, 125, 50" if value > 0 else "198, 40, 40"
        return f"background-color: rgba({color}, {alpha:.2f})"

    styled_dataframe = dataframe.style.map(_highlight_streak, subset=["Streak"])

    st.dataframe(
        styled_dataframe,
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(dataframe)),
        column_config={
            "Win %": st.column_config.NumberColumn(format="%.3f"),
            "Streak": st.column_config.NumberColumn(format="%+d"),
            "Points For": st.column_config.NumberColumn(format="%.2f"),
            "Points Against": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def _render_standings_chart(season: int, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """Cumulative win % per manager, one line per manager in their own
    color, week 1 through the current week."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        return

    team_info = team_id_to_manager_map(season)
    weeks = [week_table["week"] for week_table in weekly_tables]

    figure = go.Figure()
    for team_id, info in team_info.items():
        manager_id = info.get("manager_id", "")
        manager_name = resolve_manager_name(manager_id, name_resolver, info.get("display_name", ""))
        percentages = []
        custom_data = []
        for week_table in weekly_tables:
            row = next((r for r in week_table["standings"] if r["team_id"] == team_id), None)
            if row is None:
                percentages.append(None)
                custom_data.append([manager_name, "—", "—", "—"])
                continue
            percentages.append(round(row["win_pct"] * 100, 1))
            custom_data.append(
                [
                    manager_name,
                    f"{row['wins']}-{row['losses']}-{row['ties']}",
                    row["weekly"]["result"],
                    f"{row['win_pct'] * 100:.1f}%",
                ]
            )

        figure.add_trace(
            go.Scatter(
                x=weeks,
                y=percentages,
                mode="lines",
                name=manager_name,
                line=dict(color=manager_color_map.get(manager_id, "#CCCCCC")),
                customdata=custom_data,
                hovertemplate=(
                    "Manager: %{customdata[0]}<br>"
                    "W-L-T: %{customdata[1]}<br>"
                    "Week Result: %{customdata[2]}<br>"
                    "Cumulative Win %: %{customdata[3]}"
                    "<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        xaxis_title="Week",
        yaxis_title="Cumulative Win %",
        xaxis=dict(tickmode="linear", dtick=1),
        legend_title_text="Manager",
        height=450,
    )
    st.plotly_chart(figure, width="stretch")


def _render_breakdown_table(season: int, name_resolver: dict[str, str]) -> None:
    """"All-play" record - each week, a team's record if it had played
    every other team that week instead of just its scheduled opponent
    (see code/stats-aggregation/breakdown.py). Rank/Team/Overall come
    from the final week's CUMULATIVE all-play record; one column per
    week after that shows just THAT week's own all-play record (not
    cumulative through it - Overall already covers the running total),
    left (week 1) to right (current week) - st.dataframe scrolls
    horizontally on its own once the week columns overflow the visible
    width, no extra config needed for that."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        st.info("No breakdown available for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    final_breakdown = {row["team_id"]: row for row in weekly_tables[-1]["breakdown"]}

    rows = []
    for team_id, final_row in final_breakdown.items():
        info = team_info.get(team_id, {})
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))
        cumulative = final_row["cumulative"]
        row = {
            "Rank": cumulative["rank"],
            "Team": f"{team_name} ({manager_name})",
            "Overall W-L-T": f"{cumulative['wins']}-{cumulative['losses']}-{cumulative['ties']}",
        }
        for week_table in weekly_tables:
            week_row = next((r for r in week_table["breakdown"] if r["team_id"] == team_id), None)
            weekly = week_row["weekly"] if week_row else None
            row[f"Wk {week_table['week']}"] = f"{weekly['wins']}-{weekly['losses']}-{weekly['ties']}" if weekly else "—"
        rows.append(row)

    dataframe = pd.DataFrame(rows).sort_values("Rank")

    # A perfect all-play week (beat every other team, or lost to every
    # other team) highlighted at 85% opacity - same green/red used
    # elsewhere in the app. Checked by actual win/loss counts (not a
    # hardcoded "9-0-0"/"0-9-0" string) since league size - and so how
    # many "all-play" games exist in a week - varies by season.
    def _highlight_perfect_week(value: str) -> str:
        if value == "—" or "-" not in value:
            return ""
        wins, losses, ties = (int(part) for part in value.split("-"))
        if losses == 0 and ties == 0 and wins > 0:
            return "background-color: rgba(46, 125, 50, 0.85)"
        if wins == 0 and ties == 0 and losses > 0:
            return "background-color: rgba(198, 40, 40, 0.85)"
        return ""

    week_columns = [f"Wk {week_table['week']}" for week_table in weekly_tables]
    styled_dataframe = dataframe.style.map(_highlight_perfect_week, subset=week_columns)

    st.dataframe(
        styled_dataframe,
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(dataframe)),
        column_config={
            "Rank": st.column_config.Column(pinned=True),
            "Team": st.column_config.Column(pinned=True),
            "Overall W-L-T": st.column_config.Column(pinned=True),
        },
    )


def _render_breakdown_chart(season: int, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """Cumulative all-play win % per manager, one line per manager in
    their own color (same map used across the app), week 1 through the
    current week."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        return

    team_info = team_id_to_manager_map(season)
    weeks = [week_table["week"] for week_table in weekly_tables]

    figure = go.Figure()
    for team_id, info in team_info.items():
        manager_id = info.get("manager_id", "")
        manager_name = resolve_manager_name(manager_id, name_resolver, info.get("display_name", ""))
        percentages = []
        custom_data = []
        for week_table in weekly_tables:
            row = next((r for r in week_table["breakdown"] if r["team_id"] == team_id), None)
            if row is None:
                percentages.append(None)
                custom_data.append([manager_name, "—", "—", "—"])
                continue
            cumulative = row["cumulative"]
            weekly = row["weekly"]
            games = cumulative["wins"] + cumulative["losses"] + cumulative["ties"]
            percentage = round((cumulative["wins"] + 0.5 * cumulative["ties"]) / games * 100, 1) if games else None
            percentages.append(percentage)
            custom_data.append(
                [
                    manager_name,
                    f"{cumulative['wins']}-{cumulative['losses']}-{cumulative['ties']}",
                    f"{weekly['wins']}-{weekly['losses']}-{weekly['ties']}",
                    f"{percentage:.1f}%" if percentage is not None else "—",
                ]
            )

        figure.add_trace(
            go.Scatter(
                x=weeks,
                y=percentages,
                mode="lines",
                name=manager_name,
                line=dict(color=manager_color_map.get(manager_id, "#CCCCCC")),
                customdata=custom_data,
                hovertemplate=(
                    "Manager: %{customdata[0]}<br>"
                    "Cumulative Breakdown: %{customdata[1]}<br>"
                    "Week Breakdown: %{customdata[2]}<br>"
                    "Breakdown %: %{customdata[3]}"
                    "<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        xaxis_title="Week",
        yaxis_title="Overall Breakdown %",
        xaxis=dict(tickmode="linear", dtick=1),
        legend_title_text="Manager",
        height=450,
    )
    st.plotly_chart(figure, width="stretch")


def _render_coach_table(season: int, name_resolver: dict[str, str]) -> None:
    """Coaching efficiency - each week, actual lineup points vs the
    optimal lineup that could've been set (see
    code/stats-aggregation/coaching.py's diff, always <= 0: 0 = perfect,
    more negative = more points left on the bench). Rank/Team/Total come
    from the final week's CUMULATIVE diff_sum; one column per week after
    that shows just THAT week's own diff, left (week 1) to right
    (current week) - same pinned-columns/horizontal-scroll treatment as
    the Breakdown tab."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        st.info("No coaching data available for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    final_coaching = {row["team_id"]: row for row in weekly_tables[-1]["coaching"]}

    rows = []
    for team_id, final_row in final_coaching.items():
        info = team_info.get(team_id, {})
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))
        row = {
            "Rank": final_row["cumulative"]["rank"],
            "Team": f"{team_name} ({manager_name})",
            "Total": final_row["cumulative"]["diff_sum"],
        }
        for week_table in weekly_tables:
            week_row = next((r for r in week_table["coaching"] if r["team_id"] == team_id), None)
            row[f"Wk {week_table['week']}"] = week_row["weekly"]["diff"] if week_row else None
        rows.append(row)

    dataframe = pd.DataFrame(rows).sort_values("Rank")
    week_columns = [f"Wk {week_table['week']}" for week_table in weekly_tables]

    # diff is always <= 0 (0 = the actual lineup already WAS the optimal
    # one that week, no points left on the bench) - only a green
    # highlight makes sense here, unlike Breakdown's win/loss pair, since
    # there's no "perfect bad" analog to a 0-9-0 week. Same 85% opacity
    # green used there.
    def _highlight_perfect_coaching_week(value: float) -> str:
        return "background-color: rgba(46, 125, 50, 0.85)" if value == 0 else ""

    styled_dataframe = dataframe.style.map(_highlight_perfect_coaching_week, subset=week_columns)

    st.dataframe(
        styled_dataframe,
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(dataframe)),
        column_config={
            "Rank": st.column_config.Column(pinned=True),
            "Team": st.column_config.Column(pinned=True),
            "Total": st.column_config.NumberColumn(pinned=True, format="%.2f"),
            **{week_column: st.column_config.NumberColumn(format="%.2f") for week_column in week_columns},
        },
    )


def _render_coach_chart(season: int, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """Cumulative coaching diff_sum per manager, one line per manager in
    their own color, week 1 through the current week."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        return

    team_info = team_id_to_manager_map(season)
    weeks = [week_table["week"] for week_table in weekly_tables]

    figure = go.Figure()
    for team_id, info in team_info.items():
        manager_id = info.get("manager_id", "")
        manager_name = resolve_manager_name(manager_id, name_resolver, info.get("display_name", ""))
        totals = []
        custom_data = []
        for week_table in weekly_tables:
            row = next((r for r in week_table["coaching"] if r["team_id"] == team_id), None)
            if row is None:
                totals.append(None)
                custom_data.append([manager_name, "—", "—"])
                continue
            cumulative_diff = row["cumulative"]["diff_sum"]
            weekly_diff = row["weekly"]["diff"]
            totals.append(cumulative_diff)
            custom_data.append([manager_name, f"{cumulative_diff:.2f}", f"{weekly_diff:.2f}"])

        figure.add_trace(
            go.Scatter(
                x=weeks,
                y=totals,
                mode="lines",
                name=manager_name,
                line=dict(color=manager_color_map.get(manager_id, "#CCCCCC")),
                customdata=custom_data,
                hovertemplate=(
                    "Manager: %{customdata[0]}<br>"
                    "Cumulative Coach: %{customdata[1]}<br>"
                    "Week Coach: %{customdata[2]}"
                    "<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        xaxis_title="Week",
        yaxis_title="Cumulative Coaching Diff",
        xaxis=dict(tickmode="linear", dtick=1),
        legend_title_text="Manager",
        height=450,
    )
    st.plotly_chart(figure, width="stretch")


def _render_true_ranking_chart(season: int, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """True ranking score per manager, one line per manager in their own
    color, week 1 through the current week. Fixed y-axis 0-40 (the max
    possible score for a 10-team league: 4 categories x 10 each)."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        return

    team_info = team_id_to_manager_map(season)
    weeks = [week_table["week"] for week_table in weekly_tables]

    figure = go.Figure()
    for team_id, info in team_info.items():
        manager_id = info.get("manager_id", "")
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(manager_id, name_resolver, info.get("display_name", ""))
        team_label = f"{team_name} ({manager_name})"
        scores = []
        custom_data = []
        for week_table in weekly_tables:
            row = next((r for r in week_table["true_ranking"] if r["team_id"] == team_id), None)
            if row is None:
                scores.append(None)
                custom_data.append([team_label, "—", "—", "—", "—", "—"])
                continue
            scores.append(row["true_ranking_score"])
            custom_data.append(
                [
                    team_label,
                    row["true_ranking_score"],
                    row["record_rank"],
                    row["points_for_rank"],
                    row["breakdown_rank"],
                    row["coaching_rank"],
                ]
            )

        figure.add_trace(
            go.Scatter(
                x=weeks,
                y=scores,
                mode="lines",
                name=manager_name,
                line=dict(color=manager_color_map.get(manager_id, "#CCCCCC")),
                customdata=custom_data,
                hovertemplate=(
                    "Team: %{customdata[0]}<br>"
                    "True Rank: %{customdata[1]}<br>"
                    "Record Rank: %{customdata[2]}<br>"
                    "Points For Rank: %{customdata[3]}<br>"
                    "Breakdown Rank: %{customdata[4]}<br>"
                    "Coach Rank: %{customdata[5]}"
                    "<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        xaxis_title="Week",
        yaxis_title="True Ranking Score",
        xaxis=dict(tickmode="linear", dtick=1),
        yaxis=dict(range=[0, 40]),
        legend_title_text="Manager",
        height=450,
    )
    st.plotly_chart(figure, width="stretch")


def _render_true_ranking_table(season: int, name_resolver: dict[str, str]) -> None:
    """Composite power ranking - each team's rank across 4 different
    lenses (record, points for, all-play/Breakdown, coaching), all
    cumulative through the final week, summed into one score (lower is
    better) and re-ranked by that sum (see
    code/stats-aggregation/true_ranking.py). Single current-standings-
    style table, not per-week columns like Breakdown/Coach - the
    underlying data is cumulative-only, there's no separate "this week
    alone" score to show."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        st.info("No true ranking available for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    final_true_ranking = weekly_tables[-1]["true_ranking"]

    rows = []
    for row in final_true_ranking:
        info = team_info.get(row["team_id"], {})
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))
        rows.append(
            {
                "Rank": row["true_rank"],
                "Team": f"{team_name} ({manager_name})",
                "True Rank": row["true_ranking_score"],
                "Record Rank": row["record_rank"],
                "Points For Rank": row["points_for_rank"],
                "Breakdown Rank": row["breakdown_rank"],
                "Coach Rank": row["coaching_rank"],
            }
        )
    dataframe = pd.DataFrame(rows).sort_values("Rank")

    rank_columns = ["Record Rank", "Points For Rank", "Breakdown Rank", "Coach Rank"]

    def _rank_extremes(series: pd.Series) -> list[str]:
        min_value, max_value = series.min(), series.max()
        if max_value == min_value:
            return [""] * len(series)
        colors = []
        for value in series:
            if value == max_value:
                colors.append("background-color: rgba(46, 125, 50, 0.85)")
            elif value == min_value:
                colors.append("background-color: rgba(198, 40, 40, 0.85)")
            else:
                colors.append("")
        return colors

    styled_dataframe = dataframe.style.apply(_rank_extremes, subset=rank_columns)

    st.dataframe(
        styled_dataframe,
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(dataframe)),
        column_config={
            "Rank": st.column_config.Column(pinned=True),
            "Team": st.column_config.Column(pinned=True),
            "True Rank": st.column_config.Column(pinned=True),
        },
    )


def _render_transactions_table(season: int, name_resolver: dict[str, str]) -> None:
    st.subheader("Transactions")

    transactions = load_transactions(season)["transactions"]
    if not transactions:
        st.info("No transactions recorded for this season.")
        return

    manager_name_by_id = {t["by_manager_id"]: resolve_manager_name(t["by_manager_id"], name_resolver, t["by_manager_display_name"]) for t in transactions if t.get("by_manager_id")}
    # NFL.com's transaction log attributes BOTH legs of a trade to
    # whichever manager clicked "confirm" (by_manager_id) - the other
    # side of the trade gets no transaction record of their own at all,
    # confirmed via 2023's trades (e.g. both "Sam LaPorta -> Liam" and
    # "Jaylen Waddle -> William" showed by_manager_id=Liam). For Trade
    # rows specifically, the Manager column below uses the RECEIVING
    # team ("to") instead, so each leg attributes to the team that
    # actually ended up with that player - the only way both sides of a
    # trade show up under their own manager.
    manager_name_by_team_name = {
        info["team_name"]: resolve_manager_name(info["manager_id"], name_resolver, info["display_name"]) for info in team_id_to_manager_map(season).values()
    }
    all_dates = [_parse_transaction_date(t["date"], season) for t in transactions]
    min_date, max_date = min(all_dates).date(), max(all_dates).date()
    transaction_types = sorted({t["type"] for t in transactions})

    team_column, type_column, date_column, page_column = st.columns(4)
    with team_column:
        selected_team = st.selectbox(
            "Manager",
            sorted(set(manager_name_by_id.values())),
            index=None,
            placeholder="Any",
            key="seasons_transactions_team",
        )
    with type_column:
        selected_type = st.selectbox(
            "Transaction",
            transaction_types,
            index=None,
            placeholder="Any",
            key="seasons_transactions_type",
        )
    with date_column:
        selected_range = st.date_input(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="seasons_transactions_date_range",
        )

    # st.date_input returns a single date while the user has only picked
    # one end of the range yet (before their second click) - skip
    # filtering by date in that transient state rather than erroring.
    start_date, end_date = (selected_range if len(selected_range) == 2 else (min_date, max_date))

    rows = []
    for transaction in transactions:
        if selected_type and transaction["type"] != selected_type:
            continue
        transaction_datetime = _parse_transaction_date(transaction["date"], season)
        if not (start_date <= transaction_datetime.date() <= end_date):
            continue
        if transaction["type"] == "Trade":
            manager_name = manager_name_by_team_name.get(transaction["to"]) or manager_name_by_id.get(transaction.get("by_manager_id"), transaction.get("by_manager_display_name", ""))
        else:
            manager_name = manager_name_by_id.get(transaction.get("by_manager_id"), transaction.get("by_manager_display_name", ""))
        if selected_team and manager_name != selected_team:
            continue

        if transaction["type"] in ("Add", "Drop", "Lineup"):
            description = f"{transaction['player_name']} ({transaction['from']} → {transaction['to']})"
        else:
            description = transaction["player_name"]

        rows.append(
            {
                "Manager": manager_name,
                "Transaction": transaction["type"],
                "Description": description,
                "Date": transaction_datetime.strftime("%b %d, %Y %I:%M%p"),
                "_sort": transaction_datetime,
            }
        )

    if not rows:
        st.info("No transactions match these filters.")
        return

    rows.sort(key=lambda row: row["_sort"], reverse=True)
    for row in rows:
        del row["_sort"]

    total_pages = -(-len(rows) // TRANSACTIONS_PAGE_SIZE)
    # A filter change can shrink total_pages below whatever page the user
    # was previously on - st.number_input errors if its existing
    # session_state value exceeds the new max_value, so clamp first.
    if st.session_state.get("seasons_transactions_page", 1) > total_pages:
        st.session_state["seasons_transactions_page"] = 1
    # page_column was created up front alongside the other filters (same
    # st.columns row) so Page visually sits on their right, even though
    # its max_value can only be computed after those filters are applied.
    with page_column:
        page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="seasons_transactions_page")
    st.caption(f"Page {page} of {total_pages} ({len(rows)} transactions)")

    start_index = (page - 1) * TRANSACTIONS_PAGE_SIZE
    page_rows = rows[start_index : start_index + TRANSACTIONS_PAGE_SIZE]
    # st.column_config.Column's width only takes "small"/"medium"/"large"
    # or a fixed pixel int - no true flex-ratio system - so the requested
    # 1:1:4:2 proportion is approximated here with pixel widths on a
    # 100px base unit (100/100/400/200).
    st.dataframe(
        pd.DataFrame(page_rows),
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(page_rows)),
        column_config={
            "Manager": st.column_config.Column(width=100),
            "Transaction": st.column_config.Column(width=100),
            "Description": st.column_config.Column(width=400),
            "Date": st.column_config.Column(width=200),
        },
    )


def _render_bracket_connectors(connectors: list, canvas_height: int) -> None:
    card_center = BRACKET_CARD_HEIGHT_PX / 2
    color = "black"  # matches the cards' own black outline, per request

    segments = []
    for from_round, from_row, to_round, to_row, team_id in connectors:
        from_y = from_row * BRACKET_ROW_UNIT_PX + card_center
        to_y = to_row * BRACKET_ROW_UNIT_PX + card_center
        top, bottom = min(from_y, to_y), max(from_y, to_y)
        # Left stub (out of the source card) + right stub (into the target
        # card) + a vertical bar joining them - the two 90-degree turns
        # that make this an elbow connector instead of a diagonal line.
        segments.append(f'<div style="position:absolute; left:0; top:{from_y - 1}px; width:50%; height:2px; background:{color};"></div>')
        segments.append(f'<div style="position:absolute; left:50%; top:{top}px; width:2px; height:{bottom - top}px; background:{color};"></div>')
        segments.append(f'<div style="position:absolute; left:50%; top:{to_y - 1}px; width:50%; height:2px; background:{color};"></div>')
        segments.append(
            f'<div style="position:absolute; left:calc(100% - 8px); top:{to_y - 5}px; width:0; height:0; '
            f'border-top:5px solid transparent; border-bottom:5px solid transparent; border-left:8px solid {color};"></div>'
        )

    st.markdown(f'<div style="position:relative; height:{canvas_height}px;">{"".join(segments)}</div>', unsafe_allow_html=True)


def _render_bracket(
    bracket: dict, team_info: dict[str, dict], name_resolver: dict[str, str], manager_color_map: dict[str, str], is_consolation: bool, path_team_id: str
) -> None:
    rounds = bracket.get("rounds", [])
    if not any(round_entry["matchups"] for round_entry in rounds):
        st.info("No bracket data available for this season yet.")
        return

    rounds_with_rows, connectors = _layout_bracket_rounds(rounds)
    max_round_order = max(round_order for round_order, _, _ in rounds_with_rows)

    # One shared coordinate system for every round AND every connector
    # column in this bracket (not just each adjacent pair) - guarantees a
    # connector's "top" always lands on the exact same pixel as the real
    # card it's pointing at, in every column.
    all_rows = [row for _, _, games_with_rows in rounds_with_rows for _, row in games_with_rows]
    canvas_height = int(max(all_rows, default=0.0) * BRACKET_ROW_UNIT_PX + BRACKET_CARD_HEIGHT_PX)

    column_widths = []
    for i in range(len(rounds_with_rows)):
        column_widths.append(3)
        if i < len(rounds_with_rows) - 1:
            column_widths.append(1)
    columns = st.columns(column_widths)

    column_index = 0
    for round_index, (round_order, round_name, games_with_rows) in enumerate(rounds_with_rows):
        with columns[column_index]:
            # A fixed-pixel-height header div (not an st.container) so
            # every column - round or connector - starts its canvas at
            # exactly the same y=0, regardless of any inherent margin
            # differences between bold text and an empty line.
            st.markdown(
                f'<div style="height:{BRACKET_HEADER_HEIGHT_PX}px; display:flex; align-items:center;"><strong>{html.escape(round_name)}</strong></div>',
                unsafe_allow_html=True,
            )
            # All of this round's cards as one absolutely positioned
            # canvas - no invisible st.container spacers between them.
            cards_html = "".join(
                _bracket_game_card_html(
                    game,
                    row * BRACKET_ROW_UNIT_PX,
                    team_info,
                    name_resolver,
                    manager_color_map,
                    _bracket_display_round_label(game, round_order, max_round_order, is_consolation),
                    path_team_id,
                )
                for game, row in games_with_rows
            )
            st.markdown(f'<div style="position:relative; height:{canvas_height}px;">{cards_html}</div>', unsafe_allow_html=True)
        column_index += 1

        if round_index < len(rounds_with_rows) - 1:
            next_round_order = rounds_with_rows[round_index + 1][0]
            round_connectors = [c for c in connectors if c[0] == round_order and c[2] == next_round_order]
            with columns[column_index]:
                st.markdown(f'<div style="height:{BRACKET_HEADER_HEIGHT_PX}px;"></div>', unsafe_allow_html=True)
                _render_bracket_connectors(round_connectors, canvas_height)
            column_index += 1


def _render_playoffs_tab(season: int, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    playoffs = load_playoffs(season)
    if not playoffs:
        st.info("No playoff bracket recorded for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    championship_bracket = playoffs.get("championship_bracket", {})
    consolation_bracket = playoffs.get("consolation_bracket", {})
    championship_tab, consolation_tab = st.tabs(["Championship", "Consolation"])
    with championship_tab:
        _render_bracket(
            championship_bracket, team_info, name_resolver, manager_color_map, is_consolation=False,
            path_team_id=championship_bracket.get("champion_team_id", ""),
        )
    with consolation_tab:
        _render_bracket(
            consolation_bracket, team_info, name_resolver, manager_color_map, is_consolation=True,
            path_team_id=consolation_bracket.get("consolation_winner_team_id", ""),
        )


def _render_final_standings_table(season: int, name_resolver: dict[str, str]) -> None:
    post_season_stats = load_post_season_stats(season)
    if not post_season_stats:
        st.info("No post-season stats recorded for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    final_placements = post_season_stats["final_placements"]
    bye_team_ids = _championship_bye_team_ids(season)
    regular_season_rank_by_team = {row["team_id"]: row["rank"] for row in load_weekly_tables(season)["weeks"][-1]["standings"]}

    rows = []
    for team_id, rank in final_placements.items():
        info = team_info.get(team_id, {})
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))

        if team_id in post_season_stats["championship"]:
            bracket_name = "Championship"
            stats = post_season_stats["championship"][team_id]
        elif team_id in post_season_stats["consolation"]:
            bracket_name = "Consolation"
            stats = post_season_stats["consolation"][team_id]
        else:
            bracket_name, stats = "—", None

        regular_season_rank = regular_season_rank_by_team.get(team_id, rank)

        rows.append(
            {
                "Rank": rank,
                # Regular-season rank minus final (post-season) rank -
                # positive means the team finished HIGHER (a smaller rank
                # number) than where the regular season left them, i.e.
                # an actual gain. Kept as a real int (not text) so
                # st.dataframe's interactive column sort - which sorts by
                # the raw underlying cell value, not the display string -
                # still orders it numerically.
                "Rank Gained": regular_season_rank - rank,
                "Team": f"{team_name} ({manager_name})",
                "Bracket": bracket_name,
                "Bye": "Yes" if team_id in bye_team_ids else "-",
                "W-L": f"{stats['wins']}-{stats['losses']}" if stats else "—",
                # Formatted as strings (not a NumberColumn) so a team that
                # didn't make the post-season can show "—" instead of a
                # numeric column's blank/NaN rendering.
                "Points For": f"{stats['points_for']:.2f}" if stats else "—",
                "Points Against": f"{stats['points_against']:.2f}" if stats else "—",
            }
        )

    dataframe = pd.DataFrame(rows).sort_values("Rank")

    def _format_rank_gained(value: int) -> str:
        if value > 0:
            return f"+{value}"
        if value < 0:
            return str(value)
        return "0"

    def _color_rank_gained(value: int) -> str:
        if value > 0:
            return "color: #2E7D32"
        if value < 0:
            return "color: #C62828"
        return ""

    styled_dataframe = dataframe.style.format({"Rank Gained": _format_rank_gained}).map(_color_rank_gained, subset=["Rank Gained"])

    st.dataframe(styled_dataframe, hide_index=True, width="stretch", height=_full_table_height(len(dataframe)))


def _render_season_podium(season: int, name_resolver: dict[str, str]) -> None:
    top_three = _top_three_final_standings(season, name_resolver)
    if len(top_three) < 3:
        st.info("Not enough standings data to show a podium for this season.")
        return

    st.subheader("Podium")
    max_stack_height = max(PODIUM_BLOCK_HEIGHT_PX[rank] + PODIUM_LOGO_SIZE_PX[rank] + PODIUM_LOGO_GAP_PX for rank in PODIUM_DISPLAY_ORDER)

    columns = st.columns(3)
    for column, rank in zip(columns, PODIUM_DISPLAY_ORDER):
        team_id, team_name, manager_name, combined_record = top_three[rank]
        logo_data_uri = load_team_logo_data_uri(season, team_id)
        logo_size = PODIUM_LOGO_SIZE_PX[rank]
        logo_html = (
            f'<img src="{logo_data_uri}" style="width:{logo_size}px; height:{logo_size}px; object-fit:cover; '
            f'border-radius:12px; margin-bottom:{PODIUM_LOGO_GAP_PX}px;">'
            if logo_data_uri
            else f'<div style="width:{logo_size}px; height:{logo_size}px; margin-bottom:{PODIUM_LOGO_GAP_PX}px;"></div>'
        )
        with column:
            # Outer box is a fixed max height with the [logo + colored
            # block] stack bottom-aligned inside it (align-items:flex-end)
            # - that's what makes the three blocks share one common
            # "floor" line like a real medal podium, despite their
            # different heights.
            st.markdown(
                f'<div style="height:{max_stack_height}px; display:flex; align-items:flex-end;">'
                f'<div style="width:100%; display:flex; flex-direction:column; align-items:center;">'
                f"{logo_html}"
                f'<div style="width:100%; height:{PODIUM_BLOCK_HEIGHT_PX[rank]}px; background:{PODIUM_COLOR[rank]}; '
                f'border-radius:8px 8px 0 0; box-sizing:border-box; padding:12px; color:white; text-align:center; '
                f'display:flex; flex-direction:column; justify-content:flex-end;">'
                f'<div style="font-size:1.5rem; font-weight:bold;">{PODIUM_LABEL[rank]}</div>'
                f'<div style="font-weight:bold;">{html.escape(team_name)}</div>'
                f'<div style="font-size:0.85rem; opacity:0.9;">{html.escape(combined_record)}</div>'
                f'<div style="font-size:0.85rem; opacity:0.9;">{html.escape(manager_name)}</div>'
                f"</div></div></div>",
                unsafe_allow_html=True,
            )


def _render_season_summary_table(season: int, name_resolver: dict[str, str]) -> None:
    """Combined regular + post-season table - same combined-record idea
    as the podium/Final Standings tab, but every team, with W-L-T/Win
    %/Points For/Points Against all summing the regular season with
    whichever post-season bracket (if any) that team played in."""
    weekly_tables = load_weekly_tables(season)["weeks"]
    if not weekly_tables:
        st.info("No standings available for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    post_season_stats = load_post_season_stats(season)
    regular_season_standings = {row["team_id"]: row for row in weekly_tables[-1]["standings"]}

    if post_season_stats and post_season_stats.get("final_placements"):
        ranked_team_ids = sorted(post_season_stats["final_placements"].items(), key=lambda entry: entry[1])
    else:
        ranked_team_ids = [(row["team_id"], row["rank"]) for row in weekly_tables[-1]["standings"]]

    last_place_rank = max((rank for _, rank in ranked_team_ids), default=None)

    rows = []
    for team_id, rank in ranked_team_ids:
        info = team_info.get(team_id, {})
        team_name = info.get("team_name", "")
        manager_name = resolve_manager_name(info.get("manager_id", ""), name_resolver, info.get("display_name", ""))

        regular_row = regular_season_standings.get(team_id, {})
        wins, losses, ties = regular_row.get("wins", 0), regular_row.get("losses", 0), regular_row.get("ties", 0)
        points_for, points_against = regular_row.get("points_for", 0.0), regular_row.get("points_against", 0.0)

        bracket_name = "—"
        if post_season_stats:
            for candidate_bracket, candidate_name in (("championship", "Championship"), ("consolation", "Consolation")):
                post_season_record = post_season_stats[candidate_bracket].get(team_id)
                if post_season_record:
                    bracket_name = candidate_name
                    wins += post_season_record["wins"]
                    losses += post_season_record["losses"]
                    ties += post_season_record["ties"]
                    points_for += post_season_record["points_for"]
                    points_against += post_season_record["points_against"]
                    break

        games_played = wins + losses + ties
        win_pct = (wins + 0.5 * ties) / games_played if games_played else 0.0

        rows.append(
            {
                "Rank": rank,
                "Podium": PODIUM_EMOJI.get(rank) or (LAST_PLACE_EMOJI if rank == last_place_rank else ""),
                "Team": f"{team_name} ({manager_name})",
                "Bracket": bracket_name,
                "W-L-T": f"{wins}-{losses}-{ties}",
                "Win %": win_pct,
                "Points For": points_for,
                "Points Against": points_against,
            }
        )

    dataframe = pd.DataFrame(rows).sort_values("Rank")
    st.dataframe(
        dataframe,
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(dataframe)),
        column_config={
            "Win %": st.column_config.NumberColumn(format="%.3f"),
            "Points For": st.column_config.NumberColumn(format="%.2f"),
            "Points Against": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def _render_schedule_highlight(team: dict, name_resolver: dict[str, str], manager_color_map: dict[str, str], align: str) -> None:
    """Manager name/team name/score in one colored block - same styling
    as the Games tab's matchup card (background = that manager's color,
    text = contrasting_text_color against it) - so a team reads the same
    way in both places."""
    manager_name = resolve_manager_name(team.get("manager_id", ""), name_resolver, team.get("display_name", ""))
    background_color = manager_color_map.get(team.get("manager_id", ""), "#CCCCCC")
    text_color = contrasting_text_color(background_color)
    flex_direction = "row" if align == "left" else "row-reverse"

    st.markdown(
        f"<div style='background-color:{background_color}; color:{text_color}; padding:6px 10px; "
        f"border-radius:6px; display:flex; flex-direction:{flex_direction}; justify-content:space-between; "
        f"align-items:center;'>"
        f"<div style='text-align:{align};'><span style='font-weight:600; font-size:1em;'>{html.escape(manager_name)}</span><br>"
        f"<span style='font-weight:400; font-size:0.85em;'>{html.escape(team.get('team_name', ''))}</span></div>"
        f"<div style='font-weight:600; font-size:2em;'>{team['score']:.2f}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_schedule_record(standings_row: dict | None, align: str) -> None:
    if not standings_row:
        return
    lines = [
        f"Record: {standings_row['wins']}-{standings_row['losses']}-{standings_row['ties']}",
        f"Streak: {standings_row['win_streak'] or '—'}",
        f"Rank: {standings_row['rank']}",
    ]
    st.markdown(f"<div style='text-align:{align};'>{'<br>'.join(lines)}</div>", unsafe_allow_html=True)


def _render_schedule_week(season: int, week: int, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    matchups = load_matchups(season, week, None, None, "regular")
    if not matchups:
        st.info("No regular-season games recorded for this week.")
        return

    weekly_tables = load_weekly_tables(season)["weeks"]
    week_table = next((table for table in weekly_tables if table["week"] == week), None)
    standings_by_team = {row["team_id"]: row for row in week_table["standings"]} if week_table else {}

    # Scoped to this week's own key (the established st.container(key=...)
    # -> ".st-key-*" CSS-scoping technique used elsewhere in the app) so
    # tightening the gap between row containers doesn't leak into any
    # other vertical stack on the page.
    outer_key = f"schedule_week_{season}_{week}"
    with st.container(key=outer_key):
        st.markdown(f"<style>.st-key-{outer_key} div[data-testid='stVerticalBlock'] {{ gap: 0.4rem; }}</style>", unsafe_allow_html=True)
        for matchup in matchups:
            home, away = matchup["home"], matchup["away"]
            # 1:6:1 outer split centers the actual row at exactly 75%
            # (6/8) of the available width, rather than stretching edge
            # to edge.
            _, row_area, _ = st.columns([1, 6, 1])
            with row_area, st.container(border=True):
                # Highlight row and record-stats row are two SEPARATE
                # st.columns calls (not one column stacking both) so
                # vertical_alignment="center" here centers the button
                # against just the colored highlight blocks, not the
                # highlight+record text combined.
                team1_highlight_column, button_column, team2_highlight_column = st.columns(SCHEDULE_ROW_COLUMN_RATIOS, vertical_alignment="center")

                with team1_highlight_column:
                    _render_schedule_highlight(home, name_resolver, manager_color_map, align="left")
                with button_column:
                    if st.button("View Matchup", key=f"schedule_view_game_{matchup['matchup_id']}", use_container_width=True):
                        _go_to_game_from_schedule(season, week, home.get("manager_id", ""), away.get("manager_id", ""))
                with team2_highlight_column:
                    _render_schedule_highlight(away, name_resolver, manager_color_map, align="right")

                st.markdown("<div style='height:0.6rem;'></div>", unsafe_allow_html=True)

                team1_record_column, _, team2_record_column = st.columns(SCHEDULE_ROW_COLUMN_RATIOS)
                with team1_record_column:
                    _render_schedule_record(standings_by_team.get(home["team_id"]), align="left")
                with team2_record_column:
                    _render_schedule_record(standings_by_team.get(away["team_id"]), align="right")


def _render_season_settings_tab(season: int, name_resolver: dict[str, str]) -> None:
    """A straightforward render of that season's own metadata.json - one
    table per section (Settings, Scoring Rules, Draft Info, Teams),
    rather than any computed/derived stat - this is meant as a raw
    reference view of the league's actual configuration that season."""
    metadata = load_metadata(season)
    st.subheader(metadata.get("league_name", ""))
    st.caption(f"League ID: {metadata.get('league_id', '')} · Commissioner: {metadata.get('commissioner', '')}")
    league_id = metadata.get("league_id", "")
    st.link_button("View 'NFL.com League History' Site", f"https://fantasy.nfl.com/league/{league_id}/history/{season}/standings")

    # Each section is its own collapsible expander, and the EXPANDER
    # itself (not just the table inside it) sits in the left half of a
    # 2-column row (the right column is just empty space) - "width=
    # 'stretch'" on the table then fills that half rather than the full
    # page.
    settings = metadata.get("settings", {})

    settings_column, _ = st.columns(2)
    with settings_column, st.expander("League Settings", expanded=True):
        # Value is stringified - these settings mix ints (num_teams) with
        # plain text (trade_deadline, etc), and a mixed-type column
        # doesn't serialize to Arrow cleanly (Streamlit papers over it
        # with a console warning either way, but a plain string column
        # avoids that entirely). roster_settings is its own nested dict
        # (slot -> count), not a flat setting - broken out into its own
        # section below rather than shown here.
        # Value is stringified - these settings mix ints (num_teams) with
        # plain text (trade_deadline, etc), and a mixed-type column
        # doesn't serialize to Arrow cleanly otherwise.
        flat_settings = [
            {"Setting": key.replace("_", " ").title(), "Value": str(value)} for key, value in settings.items() if key != "roster_settings"
        ]
        st.dataframe(pd.DataFrame(flat_settings), hide_index=True, width="stretch", height=_full_table_height(len(flat_settings)))

    draft_column, _ = st.columns(2)
    with draft_column, st.expander("Draft Info", expanded=True):
        draft_rows = [{"Setting": key.replace("_", " ").title(), "Value": value} for key, value in metadata.get("draft_info", {}).items()]
        st.dataframe(pd.DataFrame(draft_rows), hide_index=True, width="stretch", height=_full_table_height(len(draft_rows)))

    teams_column, _ = st.columns(2)
    with teams_column, st.expander("Teams", expanded=True):
        team_rows = []
        for team in metadata.get("teams", []):
            manager_name = resolve_manager_name(team.get("manager_id", ""), name_resolver, team.get("manager_display_name", ""))
            team_rows.append({"Team ID": team.get("team_id", ""), "Team Name": team.get("team_name", ""), "Manager": manager_name})
        # Team ID is a string ("9", "2", ...) - sorted by its int value so
        # ascending order is true numeric order (1, 2, ... 10), not
        # lexicographic ("1", "10", "2", ...).
        team_rows.sort(key=lambda row: int(row["Team ID"]))
        st.dataframe(pd.DataFrame(team_rows), hide_index=True, width="stretch", height=_full_table_height(len(team_rows)))

    roster_settings = settings.get("roster_settings", {})
    if roster_settings:
        roster_column, _ = st.columns(2)
        with roster_column, st.expander("Roster Settings", expanded=True):
            roster_rows = [{"Slot": slot, "Count": count} for slot, count in roster_settings.items()]
            st.dataframe(pd.DataFrame(roster_rows), hide_index=True, width="stretch", height=_full_table_height(len(roster_rows)))

    scoring_column, _ = st.columns(2)
    with scoring_column, st.expander("Scoring Rules", expanded=True):
        scoring_rows = [{"Rule": rule, "Value": value} for rule, value in metadata.get("scoring_rules", {}).items()]
        st.dataframe(pd.DataFrame(scoring_rows), hide_index=True, width="stretch", height=_full_table_height(len(scoring_rows)))


def render_seasons_page() -> None:
    seasons = discover_seasons()
    if not seasons:
        st.info("No seasons aggregated yet.")
        return

    # Single mandatory season (not an "Any" filter like Players/Games -
    # this whole tab is inherently scoped to one season at a time),
    # defaulting to the most recent one.
    selected_season = st.selectbox("Season", seasons, index=len(seasons) - 1, key="seasons_season")

    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()

    season_summary_tab, schedule_tab, regular_season_tab, post_season_tab, season_settings_tab = st.tabs(
        ["Season Summary", "Schedule", "Regular Season", "Post Season", "Season Settings"]
    )

    with season_summary_tab:
        _render_season_podium(selected_season, name_resolver)
        st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)
        _render_season_summary_table(selected_season, name_resolver)

    with schedule_tab:
        # weekly_tables.json is already built from load_regular_season_weeks
        # (see aggregate_season.py) - its "week" numbers never include
        # playoff weeks, so no separate filtering is needed here.
        regular_season_weeks = [week_table["week"] for week_table in load_weekly_tables(selected_season)["weeks"]]
        if not regular_season_weeks:
            st.info("No schedule available for this season yet.")
        else:
            week_tabs = st.tabs([f"Week {week}" for week in regular_season_weeks])
            for week_tab, week in zip(week_tabs, regular_season_weeks):
                with week_tab:
                    _render_schedule_week(selected_season, week, name_resolver, manager_color_map)

    with regular_season_tab:
        standings_tab, breakdown_tab, coach_tab, true_ranking_tab, transactions_tab = st.tabs(
            ["Standings", "Breakdown", "Coach", "True Ranking", "Transactions"]
        )
        with standings_tab:
            _render_standings_table(selected_season, name_resolver)
            _render_standings_chart(selected_season, name_resolver, manager_color_map)
        with breakdown_tab:
            _render_breakdown_table(selected_season, name_resolver)
            _render_breakdown_chart(selected_season, name_resolver, manager_color_map)
        with coach_tab:
            _render_coach_table(selected_season, name_resolver)
            _render_coach_chart(selected_season, name_resolver, manager_color_map)
        with true_ranking_tab:
            _render_true_ranking_table(selected_season, name_resolver)
            _render_true_ranking_chart(selected_season, name_resolver, manager_color_map)
        with transactions_tab:
            _render_transactions_table(selected_season, name_resolver)

    with post_season_tab:
        bracket_tab, final_standings_tab = st.tabs(["Bracket", "Final Standings"])
        with bracket_tab:
            _render_playoffs_tab(selected_season, name_resolver, manager_color_map)
        with final_standings_tab:
            _render_final_standings_table(selected_season, name_resolver)

    with season_settings_tab:
        _render_season_settings_tab(selected_season, name_resolver)
