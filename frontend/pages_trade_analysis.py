"""Trade Analysis tab - every trade in the archive as a card, filterable by year."""

# ========================================
# IMPORTS
# ========================================

import re

import plotly.graph_objects as go
import streamlit as st
from colors import COLOR_CHART_STAT, COLOR_CHART_VERTICAL_DASHED_YEARS, COLOR_MANAGER_BACKUP, COLOR_POINTS_POSITIVE
from constants import CHART_LINE_WIDTH_MEDIUM, CHART_MARKER_SIZE_MEDIUM
from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    discover_seasons,
    load_season_player_bye_weeks,
    load_season_player_weekly_points,
    load_transactions,
    load_week_player_info,
    resolve_manager_name,
    team_id_to_manager_map,
)
from helpers import manager_pill, parse_transaction_date, player_line
from strings import DOT_STR

# ========================================
# CONSTANTS
# ========================================

TRADE_ROW_COLUMN_RATIOS = [1, 2]

# ========================================
# FUNCTIONS
# ========================================


def _load_trades(season: int) -> list[dict]:
    """One dict per trade in that season. NFL.com logs a trade as one
    transaction row per player moved (from/to are team names), so the rows
    sharing a date and the same pair of teams are one trade. team_1 is the
    team on the first row's "from" side."""
    manager_by_team_name = {info["team_name"]: info["manager_id"] for info in team_id_to_manager_map(season).values()}
    grouped: dict[tuple, dict] = {}
    for transaction in load_transactions(season)["transactions"]:
        if transaction["type"] != "Trade":
            continue
        key = (transaction["date"], frozenset({transaction["from"], transaction["to"]}))
        trade = grouped.setdefault(
            key,
            {
                "season": season,
                "week": transaction["week"],
                "datetime": parse_transaction_date(transaction["date"], season),
                "team_1": transaction["from"],
                "team_2": transaction["to"],
                "team_1_players": [],
                "team_2_players": [],
            },
        )
        (trade["team_1_players"] if transaction["from"] == trade["team_1"] else trade["team_2_players"]).append(transaction["player_name"])

    trades = list(grouped.values())
    for trade in trades:
        trade["manager_1_id"] = manager_by_team_name.get(trade["team_1"], "")
        trade["manager_2_id"] = manager_by_team_name.get(trade["team_2"], "")
    return trades


def _player_info_by_name(trade: dict) -> dict[str, dict]:
    """A player is on a roster the week of the trade and the week after,
    so either week's rosters can supply their position and NFL team."""
    if trade["week"] is None:
        return {}
    return {**load_week_player_info(trade["season"], trade["week"] + 1), **load_week_player_info(trade["season"], trade["week"])}


def _css_key(key: str) -> str:
    """Streamlit turns a widget key into a CSS class, so keep only characters safe in one."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", key)


def _trade_key(trade: dict) -> str:
    return f"{trade['season']}_{trade['datetime'].isoformat()}_{trade['team_1']}_{trade['team_2']}"


def _select_trade(trade_key: str) -> None:
    st.session_state["trade_analysis_selected_trade"] = trade_key


def _render_trade_card(trade: dict, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """Three rows - Info button and date, manager 1 with the player(s) they
    sent, manager 2 with the player(s) they sent - each player as its own
    position / name / (team) card."""
    trade_key = _trade_key(trade)
    with st.container(border=True):
        # Row 1: Info button (left column) and date (right column), using the
        # same column split as the manager rows below so they line up.
        info_column, caption_column = st.columns(TRADE_ROW_COLUMN_RATIOS, vertical_alignment="center")
        info_column.button("Info", key=f"trade_info_{trade_key}", help="Show player stats for this trade.", on_click=_select_trade, args=(trade_key,))
        caption_column.caption(f"{trade['season']} · Week {trade['week']} · {trade['datetime'].strftime('%b %d, %Y %I:%M%p')}")

        player_info_by_name = _player_info_by_name(trade)

        # One row per manager: their name, then the player(s) they sent.
        # Both rows use the same column split so names and players line up.
        for manager_id, team_name, player_names in (
            (trade["manager_1_id"], trade["team_1"], trade["team_1_players"]),
            (trade["manager_2_id"], trade["team_2"], trade["team_2_players"]),
        ):
            manager_column, players_column = st.columns(TRADE_ROW_COLUMN_RATIOS, vertical_alignment="center")
            manager_column.markdown(manager_pill(manager_id, name_resolver, manager_color_map) if manager_id else team_name, unsafe_allow_html=True)
            with players_column:
                for player_name in player_names:
                    player_info = player_info_by_name.get(player_name, {})
                    with st.container(border=True):
                        st.markdown(player_line(player_name, player_info.get("nfl_team"), player_info.get("position")), unsafe_allow_html=True)


def _render_trade_chart(trade: dict, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """One chart for the whole trade: every player's weekly fantasy
    points, colored by the manager who had them that week. Player(s)
    sent by manager 1 are solid lines, player(s) sent by manager 2 are
    dashed. The players change hands going INTO the trade week (verified
    against the rosters), so a player belongs to their sender before it
    and to the other manager from it on. A dashed vertical line marks the
    trade."""
    points_by_player = load_season_player_weekly_points(trade["season"])
    trade_week = trade["week"]
    manager_names = [resolve_manager_name(manager_id, name_resolver) if manager_id else team_name for manager_id, team_name in ((trade["manager_1_id"], trade["team_1"]), (trade["manager_2_id"], trade["team_2"]))]
    manager_colors = [manager_color_map.get(manager_id, COLOR_MANAGER_BACKUP) for manager_id in (trade["manager_1_id"], trade["manager_2_id"])]

    figure = go.Figure()
    for side, (player_names, line_dash) in enumerate(((trade["team_1_players"], "solid"), (trade["team_2_players"], "dash"))):
        before_color, after_color = manager_colors[side], manager_colors[1 - side]
        for player_name in player_names:
            weekly_points = points_by_player.get(player_name, {})
            weeks = sorted(weekly_points)
            # Legend-only entry: neutral gray so it shows just the line type
            # (solid / dashed), not a manager color. Shares a legend group
            # with the real segments, so clicking it toggles them.
            figure.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    name=player_name,
                    legendgroup=player_name,
                    mode="lines",
                    line={"color": COLOR_CHART_STAT, "width": CHART_LINE_WIDTH_MEDIUM, "dash": line_dash},
                )
            )
            segments = (
                ([week for week in weeks if trade_week is None or week < trade_week], before_color),
                ([week for week in weeks if trade_week is not None and week >= trade_week], after_color),
            )
            for segment_weeks, color in segments:
                figure.add_trace(
                    go.Scatter(
                        x=segment_weeks,
                        y=[weekly_points[week] for week in segment_weeks],
                        name=player_name,
                        legendgroup=player_name,
                        showlegend=False,
                        mode="lines+markers",
                        line={"color": color, "width": CHART_LINE_WIDTH_MEDIUM, "dash": line_dash},
                        marker={"color": color, "size": CHART_MARKER_SIZE_MEDIUM},
                        hovertemplate="<b>Week %{x}</b><br>" + player_name + ": %{y:.2f}<extra></extra>",
                    )
                )
    if trade_week is not None:
        figure.add_vline(x=trade_week - 0.5, line_dash="dash", line_color=COLOR_CHART_VERTICAL_DASHED_YEARS)

    # Title: one row per side of the trade, with the manager as the same
    # colored pill the Matchups page uses (Plotly titles can't draw a pill,
    # so the title is rendered above the chart instead).
    for side, (manager_id, sent_players, received_players) in enumerate(
        (
            (trade["manager_1_id"], trade["team_1_players"], trade["team_2_players"]),
            (trade["manager_2_id"], trade["team_2_players"], trade["team_1_players"]),
        )
    ):
        pill = manager_pill(manager_id, name_resolver, manager_color_map) if manager_id else manager_names[side]
        st.markdown(f"{pill} {DOT_STR} {', '.join(sent_players)} → {', '.join(received_players)}", unsafe_allow_html=True)

    figure.update_layout(
        xaxis={"title": "Week", "dtick": 1},
        yaxis={"title": "Fantasy Points"},
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "xanchor": "left"},
        margin={"t": 40, "l": 60, "r": 20, "b": 50},
    )
    st.plotly_chart(figure, width="stretch")


def _points_split(trade: dict, player_names: list[str]) -> dict[str, float | int]:
    """Total fantasy points and games played by these players before the
    trade week and from it on. Bye weeks (0 points, no game) don't count as games."""
    points_by_player = load_season_player_weekly_points(trade["season"])
    bye_weeks = load_season_player_bye_weeks(trade["season"])
    split = {"points_before": 0.0, "games_before": 0, "points_after": 0.0, "games_after": 0}
    for player_name in player_names:
        for week, points in points_by_player.get(player_name, {}).items():
            period = "before" if trade["week"] is None or week < trade["week"] else "after"
            split[f"points_{period}"] += points
            if week not in bye_weeks.get(player_name, set()):
                split[f"games_{period}"] += 1
    return split


def _render_trade_metrics(trade: dict) -> None:
    """One row of four metrics per side of the trade (points and points per
    game, before and after the trade). In each column the higher of the two
    sides' numbers is highlighted green."""
    player_info_by_name = _player_info_by_name(trade)
    sides = (trade["team_1_players"], trade["team_2_players"])
    splits = [_points_split(trade, player_names) for player_names in sides]

    def _per_game(split: dict, period: str) -> float | None:
        return split[f"points_{period}"] / split[f"games_{period}"] if split[f"games_{period}"] else None

    # (label, value per side) for each of the four columns
    columns = (
        ("Points Before Trade", [split["points_before"] for split in splits]),
        ("Points After Trade", [split["points_after"] for split in splits]),
        ("Points Per Game Before", [_per_game(split, "before") for split in splits]),
        ("Points Per Game After", [_per_game(split, "after") for split in splits]),
    )

    trade_key = _trade_key(trade)
    style_rules: list[str] = []
    for row, player_names in enumerate(sides):
        st.markdown(
            " &nbsp; ".join(player_line(player_name, player_info_by_name.get(player_name, {}).get("nfl_team"), player_info_by_name.get(player_name, {}).get("position")) for player_name in player_names),
            unsafe_allow_html=True,
        )
        for column, (label, values) in zip(st.columns(4), columns):
            value = values[row]
            other_values = [other for other in values if other is not None]
            is_higher = value is not None and len(other_values) == len(values) and value > min(other_values)
            metric_key = f"trade_metric_{trade_key}_{row}_{label}"
            if is_higher:
                style_rules.append(f".st-key-{_css_key(metric_key)} [data-testid='stMetricValue'] {{ color: {COLOR_POINTS_POSITIVE}; }}")
            with column, st.container(key=_css_key(metric_key)):
                st.metric(label, f"{value:.2f}" if value is not None else "-")
    if style_rules:
        st.html(f"<style>{''.join(style_rules)}</style>")


def _render_trade_stats(trade: dict | None, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    if not trade:
        st.info("Click Info on a trade to see its player stats.")
        return
    _render_trade_chart(trade, name_resolver, manager_color_map)
    _render_trade_metrics(trade)


# ========================================
# RENDER
# ========================================


def render_trade_analysis_page() -> None:
    # Only seasons that actually had a trade are offered in the filter.
    trades_by_season = {season: _load_trades(season) for season in sorted(discover_seasons(), reverse=True)}
    seasons = [season for season, season_trades in trades_by_season.items() if season_trades]
    if not seasons:
        st.info("No trades recorded in the archive yet.")
        return

    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()

    # Left column: the year filter with every trade card under it. The
    # right column shows the stats for the trade whose Info button was clicked.
    left_column, right_column = st.columns([1, 2])

    with left_column:
        selected_year = st.selectbox("Select Year", ["All"] + seasons, key="trade_analysis_year")

        selected_seasons = seasons if selected_year == "All" else [selected_year]
        trades = [trade for season in selected_seasons for trade in trades_by_season[season]]
        trades.sort(key=lambda trade: trade["datetime"], reverse=True)
        if not trades:
            st.info("No trades found for this selection.")
            return

        st.metric("Total Trades", len(trades))

        for trade in trades:
            _render_trade_card(trade, name_resolver, manager_color_map)

    with right_column:
        selected_trade_key = st.session_state.get("trade_analysis_selected_trade")
        selected_trade = next((trade for trade in trades if _trade_key(trade) == selected_trade_key), None)
        _render_trade_stats(selected_trade, name_resolver, manager_color_map)
