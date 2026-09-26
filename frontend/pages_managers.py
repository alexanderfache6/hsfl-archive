"""Managers tab - manager-level analysis across the whole archive."""

# ========================================
# IMPORTS
# ========================================

import plotly.graph_objects as go
import streamlit as st
from colors import COLOR_NFL_BYE_WEEK, COLOR_NFL_GAME_MISSED, COLOR_OPTIMAL_OUTLINE, COLOR_MANAGER_BACKUP, COLOR_PLAYER_STARTER, COLOR_POINTS_NEGATIVE, COLOR_POINTS_POSITIVE, COLOR_TABLE_ROSTER
from constants import CHART_LINE_WIDTH_MEDIUM, CHART_MARKER_SIZE_MEDIUM, EMOJI_FIRST_PLACE, EMOJI_LAST_PLACE, EMOJI_SECOND_PLACE, EMOJI_THIRD_PLACE
from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    load_all_time_manager_stats,
    load_matchups,
    load_post_season_stats,
    load_weekly_tables,
    resolve_manager_name,
    team_id_to_manager_map,
)
from helpers import integer_yaxis_nticks, optimal_lineup_details, pad_missing_starters, player_line, position_pill, render_record_metrics, render_season_qualification_metrics
from strings import TOGGLE_OPTIMAL_LINEUP

# ========================================
# CONSTANTS
# ========================================

DEPTH_CHART_PLAYER_COLUMNS = 4
DEPTH_CHART_LABEL_COLUMN_WIDTH = 0.5

# Code shown in the top-right of a player card -> (color, legend meaning).
# The archive has no injury status, so IR means the player sat in the
# roster's reserve (IR) slot that week.
PLAYER_STATUS_CODES = {
    "BYE": (COLOR_NFL_BYE_WEEK, "NFL bye week"),
    "IR": (COLOR_NFL_GAME_MISSED, "Reserve (IR) slot"),
}

# stat option -> (True when a lower value is better, i.e. ranks, so the axis flips)
HISTORICAL_STAT_OPTIONS = {
    "Final Regular Season Rank": True,
    "Final Post Season Rank": True,
    "Points Scored": False,
    "Point Differential": False,
    "Wins": False,
    "Losses": False,
}

# ========================================
# FUNCTIONS
# ========================================


def _assign_backups(starters: list[dict], bench: list[dict]) -> list[list[dict]]:
    """One list of backups per starting slot. All of a position's bench
    players (best points first) sit on that position's FIRST starter row
    - e.g. every backup RB is on the top RB row, every backup WR on the
    top WR row - so a position's players share one row. The W/R flex
    slot never gets backups of its own."""
    backups: list[list[dict]] = [[] for _ in starters]
    for player in sorted(bench, key=lambda bench_player: bench_player["points"], reverse=True):
        first_slot_index = next((index for index, starter in enumerate(starters) if starter.get("slot", starter["position"]) == player["position"]), None)
        if first_slot_index is not None:
            backups[first_slot_index].append(player)
    return backups


def _player_status_code(player: dict) -> str | None:
    if str(player.get("opp", "")).lower() == "bye":
        return "BYE"
    if player.get("slot") == "RES":
        return "IR"
    return None


def _render_player_card(player: dict, card_key: str, is_bench: bool, optimal_details: dict | None, style_rules: list[str]) -> None:
    """Same bordered card as the Drafts page's selection cards, minus the
    position pill - the slot label column already carries the position.
    With optimal_details, players in the optimal lineup are outlined
    (CSS collected in style_rules, injected once per chart) and their points
    are colored like the Matchups cards: green for a bench player who
    belongs in the optimal lineup, red for a starter who doesn't."""
    with st.container(border=True, key=card_key):
        if player.get("is_empty_slot"):
            st.markdown(f"<span style='color:{COLOR_TABLE_ROSTER}; font-style:italic;'>Empty</span>", unsafe_allow_html=True)
            return
        points_color = None
        if optimal_details:
            player_id = player.get("player_id")
            if player_id in optimal_details["optimal_player_ids"]:
                style_rules.append(f".st-key-{card_key} {{ border: 2px solid {COLOR_OPTIMAL_OUTLINE} !important; }}")
            if is_bench and player_id in optimal_details["gains"]:
                points_color = COLOR_POINTS_POSITIVE
            elif not is_bench and player_id in optimal_details["losses"]:
                points_color = COLOR_POINTS_NEGATIVE
        status_code = _player_status_code(player)
        status_color = PLAYER_STATUS_CODES[status_code][0] if status_code else None
        st.markdown(player_line(player["player_name"], player["nfl_team"], points=player["points"], points_color=points_color, status_code=status_code, status_color=status_color), unsafe_allow_html=True)


def _week_summary(season: int, week: int, manager_id: str) -> dict | None:
    """One manager's week: their side of the matchup, padded starters, and
    the optimal-lineup numbers - shared by the weekly depth chart and the
    season chart so both always agree."""
    matchups = load_matchups(season, week, manager_id, None, "all")
    if not matchups:
        return None

    matchup = matchups[0]
    side = matchup["home"] if matchup["home"]["manager_id"] == manager_id else matchup["away"]
    starters = pad_missing_starters(side["starters"], season)
    optimal_details = optimal_lineup_details(side, season)

    # DB (2012's vestigial IDP slot) is never part of the optimal lineup,
    # so it's left out of the starter count too.
    countable_starters = [starter for starter in starters if starter.get("position") != "DB"]
    optimal_started_count = sum(1 for starter in countable_starters if starter.get("player_id") in optimal_details["optimal_player_ids"])
    return {
        "side": side,
        "starters": starters,
        "optimal_details": optimal_details,
        "points": side["score"],
        "optimal_points": optimal_details["optimal_points"],
        "optimal_started_count": optimal_started_count,
        "starter_count": len(countable_starters),
    }


def _render_depth_chart(season: int, week: int, manager_id: str, show_optimal: bool) -> None:
    summary = _week_summary(season, week, manager_id)
    if not summary:
        st.info("No matchup found for this week.")
        return

    side = summary["side"]
    starters = summary["starters"]
    optimal_details = summary["optimal_details"]
    backups = _assign_backups(starters, side["bench"])
    card_optimal_details = optimal_details if show_optimal else None

    points_column, optimal_points_column, optimal_started_column = st.columns(3)
    points_column.metric("Total Points", f"{summary['points']:.2f}")
    optimal_points_column.metric("Optimal Points", f"{summary['optimal_points']:.2f}")
    optimal_started_column.metric("Optimal Players Started", f"{summary['optimal_started_count']} / {summary['starter_count']}")

    # Row 2: whole-roster (starters + bench) status counts, value colored
    # to match the BYE / IR card codes.
    style_rules: list[str] = []
    roster_status_codes = [_player_status_code(player) for player in side["starters"] + side["bench"]]
    key_prefix = f"depth_{season}_{week}_{manager_id}"
    bye_column, ir_column, _ = st.columns(3)
    for column, code, label in ((bye_column, "BYE", "Players on Bye"), (ir_column, "IR", "Players on IR")):
        metric_key = f"{key_prefix}_metric_{code}"
        style_rules.append(f".st-key-{metric_key} [data-testid='stMetricValue'] {{ color: {PLAYER_STATUS_CODES[code][0]}; }}")
        with column, st.container(key=metric_key):
            st.metric(label, roster_status_codes.count(code), help=f"Rostered players with the {code} code ({PLAYER_STATUS_CODES[code][1]}).")

    legend_html = " &nbsp;·&nbsp; ".join(f"<span style='color:{color}; font-weight:700;'>{code}</span> {meaning}" for code, (color, meaning) in PLAYER_STATUS_CODES.items())
    st.caption(f"{legend_html}", unsafe_allow_html=True)

    # 4 player columns (starter + up to 3 backups), preceded by a narrow
    # position column. More backups than that widen the grid rather than
    # adding rows.
    player_column_count = max(DEPTH_CHART_PLAYER_COLUMNS, 1 + max((len(slot_backups) for slot_backups in backups), default=0))
    column_widths = [DEPTH_CHART_LABEL_COLUMN_WIDTH] + [1] * player_column_count

    header_columns = st.columns(column_widths)
    header_columns[0].markdown("**Position**")
    header_columns[1].markdown("**Starters**")
    header_columns[2].markdown("**Backups**")

    for row_index, (starter, slot_backups) in enumerate(zip(starters, backups)):
        columns = st.columns(column_widths, vertical_alignment="center")
        with columns[0]:
            st.markdown(position_pill(starter.get("slot", starter["position"])), unsafe_allow_html=True)
        with columns[1]:
            _render_player_card(starter, f"{key_prefix}_{row_index}_0", False, card_optimal_details, style_rules)
        for backup_index, (column, backup) in enumerate(zip(columns[2:], slot_backups), start=1):
            with column:
                _render_player_card(backup, f"{key_prefix}_{row_index}_{backup_index}", True, card_optimal_details, style_rules)

    if style_rules:
        st.html(f"<style>{''.join(style_rules)}</style>")


def _render_season_stats_chart(season: int, weeks: list[int], manager_id: str) -> None:
    """Per week: actual vs optimal points as side-by-side bars, plus the
    number of optimal starters as a line (right axis - a count, not
    points). Every trace's hover shows all four numbers."""
    summaries = {week: _week_summary(season, week, manager_id) for week in weeks}
    weeks = [week for week in weeks if summaries[week]]
    if not weeks:
        st.info("No weekly data for this season yet.")
        return

    week_labels = [f"Week {week}" for week in weeks]
    points = [summaries[week]["points"] for week in weeks]
    optimal_points = [summaries[week]["optimal_points"] for week in weeks]
    optimal_started = [summaries[week]["optimal_started_count"] for week in weeks]
    starter_counts = [summaries[week]["starter_count"] for week in weeks]
    hover_data = [[point, optimal, optimal - point, started, starters] for point, optimal, started, starters in zip(points, optimal_points, optimal_started, starter_counts)]
    hovertemplate = "<b>%{x}</b><br>Total Points: %{customdata[0]:.2f}<br>Optimal Points: %{customdata[1]:.2f}<br>Points Missed: %{customdata[2]:.2f}<br>Optimal Starters: %{customdata[3]} / %{customdata[4]}<extra></extra>"

    figure = go.Figure()
    figure.add_trace(go.Bar(x=week_labels, y=points, name="Total Points", marker={"color": COLOR_PLAYER_STARTER}, customdata=hover_data, hovertemplate=hovertemplate))
    figure.add_trace(go.Bar(x=week_labels, y=optimal_points, name="Optimal Points", marker={"color": COLOR_OPTIMAL_OUTLINE}, customdata=hover_data, hovertemplate=hovertemplate))
    figure.add_trace(
        go.Scatter(
            x=week_labels,
            y=optimal_started,
            name="Optimal Starters",
            mode="lines+markers",
            yaxis="y2",
            line={"color": COLOR_POINTS_POSITIVE, "width": CHART_LINE_WIDTH_MEDIUM},
            marker={"color": COLOR_POINTS_POSITIVE, "size": CHART_MARKER_SIZE_MEDIUM},
            customdata=hover_data,
            hovertemplate=hovertemplate,
        )
    )
    figure.update_layout(
        barmode="group",
        xaxis={"title": "Week", "type": "category"},
        yaxis={"title": "Points"},
        yaxis2={"title": "Optimal Starters", "overlaying": "y", "side": "right", "showgrid": False, "tickformat": "d", "rangemode": "tozero", "nticks": integer_yaxis_nticks(starter_counts)},
        legend={"orientation": "h", "y": 1.1, "yanchor": "bottom", "x": 0.5, "xanchor": "center"},
        margin={"t": 40, "l": 60, "r": 60, "b": 50},
    )
    st.plotly_chart(figure, width="stretch")


def _season_history_rows(manager_id: str, seasons: list[int]) -> list[dict]:
    """One row per season the manager played: final regular-season
    standings (the last week's cumulative standings row - same source as
    the Seasons page's standings table) plus their post-season placement."""
    rows = []
    for season in sorted(seasons):
        team_id = next((team_id for team_id, info in team_id_to_manager_map(season).items() if info.get("manager_id") == manager_id), None)
        weeks = load_weekly_tables(season)["weeks"]
        if not team_id or not weeks:
            continue
        standing = next((row for row in weeks[-1]["standings"] if row["team_id"] == team_id), None)
        if not standing:
            continue
        post_season_stats = load_post_season_stats(season)
        rows.append(
            {
                "season": season,
                "teams": len(weeks[-1]["standings"]),
                "Final Regular Season Rank": standing["rank"],
                "Final Post Season Rank": post_season_stats["final_placements"].get(team_id) if post_season_stats else None,
                "Points Scored": standing["points_for"],
                "Point Differential": standing["points_for"] - standing["points_against"],
                "Wins": standing["wins"],
                "Losses": standing["losses"],
            }
        )
    return rows


def _render_historical_stats_tab(manager: dict) -> None:
    manager_id = manager["manager_id"]
    seasons = manager["seasons_played"]

    first_column, second_column, third_column, last_column = st.columns(4)
    first_column.metric(f"{EMOJI_FIRST_PLACE} 1st Place", manager["championships"])
    second_column.metric(f"{EMOJI_SECOND_PLACE} 2nd Place", manager["runner_ups"])
    third_column.metric(f"{EMOJI_THIRD_PLACE} 3rd Place", manager["third_place_finishes"])
    last_column.metric(f"{EMOJI_LAST_PLACE} Last Place", manager["last_place_finishes"])

    all_matchups = load_matchups(None, None, manager_id, None, "all")
    render_record_metrics(all_matchups, manager_id)
    render_season_qualification_metrics(all_matchups)

    rows = _season_history_rows(manager_id, seasons)
    if not rows:
        st.info("No season history available for this manager yet.")
        return

    selected_stat = st.selectbox("Select Stat", list(HISTORICAL_STAT_OPTIONS), key="managers_historical_stat")
    chart_rows = [row for row in rows if row[selected_stat] is not None]
    if not chart_rows:
        st.info(f"No {selected_stat} data for this manager yet.")
        return

    years = [str(row["season"]) for row in chart_rows]
    values = [row[selected_stat] for row in chart_rows]
    team_counts = [row["teams"] for row in chart_rows]
    is_rank = HISTORICAL_STAT_OPTIONS[selected_stat]
    is_whole_number = selected_stat not in ("Points Scored", "Point Differential")
    manager_color = build_manager_color_map().get(manager_id, COLOR_MANAGER_BACKUP)

    hovertemplate = "<b>%{x}</b><br>" + selected_stat + ": %{y} of %{customdata} teams<extra></extra>" if is_rank else "<b>%{x}</b><br>" + selected_stat + ": %{y}<extra></extra>"
    figure = go.Figure()
    if is_rank:
        figure.add_trace(
            go.Scatter(
                x=years,
                y=values,
                name=selected_stat,
                mode="lines+markers",
                line={"color": manager_color, "width": CHART_LINE_WIDTH_MEDIUM},
                marker={"color": manager_color, "size": CHART_MARKER_SIZE_MEDIUM},
                customdata=team_counts,
                hovertemplate=hovertemplate,
            )
        )
    else:
        figure.add_trace(go.Bar(x=years, y=values, name=selected_stat, marker={"color": manager_color}, hovertemplate=hovertemplate))
    yaxis = {"title": selected_stat}
    if is_rank:
        # Full axis: every rank from 1 to the league size (largest league
        # shown), rank 1 at the top.
        league_size = max(team_counts)
        yaxis.update({"range": [league_size + 0.5, 0.5], "tickvals": list(range(1, league_size + 1)), "tickformat": "d"})
    elif is_whole_number:
        yaxis.update({"tickformat": "d", "nticks": integer_yaxis_nticks(values)})
    figure.update_layout(
        xaxis={"title": "Season", "type": "category"},
        yaxis=yaxis,
        showlegend=False,
        margin={"t": 20, "l": 60, "r": 20, "b": 50},
    )
    st.plotly_chart(figure, width="stretch")


# ========================================
# RENDER
# ========================================


def render_managers_page() -> None:
    manager_stats = load_all_time_manager_stats()
    managers = manager_stats["managers"]
    if not managers:
        st.info("No managers aggregated yet.")
        return

    name_resolver = build_manager_name_resolver()
    seasons_played_by_manager = {manager["manager_id"]: manager["seasons_played"] for manager in managers}
    manager_ids = sorted(seasons_played_by_manager, key=lambda manager_id: resolve_manager_name(manager_id, name_resolver))

    # Single mandatory manager, same pattern as the Seasons page's season filter.
    selected_manager_id = st.selectbox(
        "Select Manager",
        manager_ids,
        format_func=lambda manager_id: resolve_manager_name(manager_id, name_resolver),
        key="managers_manager",
    )

    historical_stats_tab, per_season_tab, head_to_head_tab = st.tabs(["Historical Stats", "Per Season", "Head to Head"])

    with historical_stats_tab:
        _render_historical_stats_tab(next(manager for manager in managers if manager["manager_id"] == selected_manager_id))

    with head_to_head_tab:
        st.info("Head to Head coming soon.")

    with per_season_tab:
        seasons = sorted(seasons_played_by_manager[selected_manager_id], reverse=True)
        if not seasons:
            st.info("This manager has not played any seasons yet.")
            return

        selected_season = st.selectbox("Select Season", seasons, key="managers_season")
        show_optimal = st.toggle("Show Optimal Lineup", key="managers_show_optimal", help=TOGGLE_OPTIMAL_LINEUP)

        # Every week this manager has a matchup - regular season plus
        # championship/consolation post-season weeks ("all" matchup type).
        weeks = sorted({matchup["week"] for matchup in load_matchups(selected_season, None, selected_manager_id, None, "all")})
        if not weeks:
            st.info("No weeks available for this season yet.")
            return

        season_stats_tab, weekly_stats_tab = st.tabs(["Season Stats", "Weekly Depth Charts"])

        with season_stats_tab:
            _render_season_stats_chart(selected_season, weeks, selected_manager_id)

        with weekly_stats_tab:
            week_tabs = st.tabs([f"Week {week}" for week in weeks])
            for week_tab, week in zip(week_tabs, weeks):
                with week_tab:
                    _render_depth_chart(selected_season, week, selected_manager_id, show_optimal)
