"""Trade Analysis tab - every trade in the archive as a card, filterable by year."""

# ========================================
# IMPORTS
# ========================================

import plotly.graph_objects as go
import streamlit as st
from colors import COLOR_CHART_VERTICAL_DASHED_YEARS, COLOR_MANAGER_BACKUP
from constants import BENCH_POSITION_COLOR, CHART_LINE_WIDTH_MEDIUM, CHART_MARKER_SIZE_MEDIUM
from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    discover_seasons,
    load_season_player_weekly_points,
    load_transactions,
    load_week_player_info,
    resolve_manager_name,
    team_id_to_manager_map,
)
from helpers import manager_pill, parse_transaction_date, player_line

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


def _trade_key(trade: dict) -> str:
    return f"{trade['season']}_{trade['datetime'].isoformat()}_{trade['team_1']}_{trade['team_2']}"


def _select_trade(trade_key: str) -> None:
    st.session_state["trades_selected_trade"] = trade_key


def _render_trade_card(trade: dict, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """Two rows - manager 1 then the player(s) they sent, manager 2 then
    the player(s) they sent - each player as its own position / name /
    (team) card."""
    trade_key = _trade_key(trade)
    with st.container(border=True):
        caption_column, info_column = st.columns([8, 1], vertical_alignment="center")
        caption_column.caption(f"{trade['season']} · Week {trade['week']} · {trade['datetime'].strftime('%b %d, %Y %I:%M%p')}")
        info_column.button("ⓘ", key=f"trade_info_{trade_key}", type="tertiary", help="Show player stats for this trade.", on_click=_select_trade, args=(trade_key,))

        player_info_by_name = _player_info_by_name(trade)

        # One row per manager: their name, then the player(s) they sent.
        # Both rows use the same column split so names and players line up.
        for manager_id, team_name, player_names in (
            (trade["manager_1_id"], trade["team_1"], trade["team_1_players"]),
            (trade["manager_2_id"], trade["team_2"], trade["team_2_players"]),
        ):
            manager_column, players_column = st.columns([1, 2], vertical_alignment="center")
            manager_column.markdown(manager_pill(manager_id, name_resolver, manager_color_map) if manager_id else team_name, unsafe_allow_html=True)
            with players_column:
                for player_name in player_names:
                    player_info = player_info_by_name.get(player_name, {})
                    with st.container(border=True):
                        st.markdown(player_line(player_name, player_info.get("nfl_team"), player_info.get("position")), unsafe_allow_html=True)


def _summed_points(points_by_player: dict[str, dict[int, float]], player_names: list[str], weeks: list[int]) -> tuple[list[int], list[float]]:
    """Combined fantasy points of the given players, week by week (only
    weeks at least one of them has points)."""
    kept_weeks, totals = [], []
    for week in weeks:
        weekly = [points_by_player[name][week] for name in player_names if week in points_by_player.get(name, {})]
        if weekly:
            kept_weeks.append(week)
            totals.append(sum(weekly))
    return kept_weeks, totals


def _render_manager_points_chart(trade: dict, manager_name: str, sent_players: list[str], received_players: list[str], player_info_by_name: dict[str, dict]) -> None:
    """One manager's fantasy points off these two players: the player(s)
    they sent while they still had them (before the trade week), then the
    player(s) they got from the trade week on - each part colored by that
    player's position. A dashed line marks the trade."""
    points_by_player = load_season_player_weekly_points(trade["season"])
    all_weeks = sorted({week for name in sent_players + received_players for week in points_by_player.get(name, {})})
    trade_week = trade["week"]

    def _position_color(player_names: list[str]) -> str:
        position = player_info_by_name.get(player_names[0], {}).get("position") if player_names else None
        return BENCH_POSITION_COLOR.get(position, COLOR_MANAGER_BACKUP)

    # The players change hands going INTO the trade week (verified against
    # the rosters), so before = weeks before it, after = it and later.
    segments = (
        (sent_players, [week for week in all_weeks if trade_week is None or week < trade_week]),
        (received_players, [week for week in all_weeks if trade_week is not None and week >= trade_week]),
    )
    figure = go.Figure()
    for player_names, weeks in segments:
        kept_weeks, totals = _summed_points(points_by_player, player_names, weeks)
        color = _position_color(player_names)
        figure.add_trace(
            go.Scatter(
                x=kept_weeks,
                y=totals,
                name=", ".join(player_names),
                mode="lines+markers",
                line={"color": color, "width": CHART_LINE_WIDTH_MEDIUM},
                marker={"color": color, "size": CHART_MARKER_SIZE_MEDIUM},
                hovertemplate="<b>Week %{x}</b><br>" + ", ".join(player_names) + ": %{y:.2f}<extra></extra>",
            )
        )
    if trade_week is not None:
        figure.add_vline(x=trade_week - 0.5, line_dash="dash", line_color=COLOR_CHART_VERTICAL_DASHED_YEARS)
    figure.update_layout(
        title=f"{manager_name} - {', '.join(sent_players)} --> {', '.join(received_players)}",
        xaxis={"title": "Week", "dtick": 1},
        yaxis={"title": "Fantasy Points"},
        legend={"orientation": "h", "y": 1.15, "yanchor": "bottom", "x": 0.5, "xanchor": "center"},
        margin={"t": 90, "l": 60, "r": 20, "b": 50},
    )
    st.plotly_chart(figure, width="stretch")


def _render_trade_stats(trade: dict | None, name_resolver: dict[str, str]) -> None:
    if not trade:
        st.info("Click the ⓘ on a trade to see its player stats.")
        return

    player_info_by_name = _player_info_by_name(trade)
    for manager_id, team_name, sent_players, received_players in (
        (trade["manager_1_id"], trade["team_1"], trade["team_1_players"], trade["team_2_players"]),
        (trade["manager_2_id"], trade["team_2"], trade["team_2_players"], trade["team_1_players"]),
    ):
        manager_name = resolve_manager_name(manager_id, name_resolver) if manager_id else team_name
        _render_manager_points_chart(trade, manager_name, sent_players, received_players, player_info_by_name)


# ========================================
# RENDER
# ========================================


def render_trades_page() -> None:
    # Only seasons that actually had a trade are offered in the filter.
    trades_by_season = {season: _load_trades(season) for season in sorted(discover_seasons(), reverse=True)}
    seasons = [season for season, season_trades in trades_by_season.items() if season_trades]
    if not seasons:
        st.info("No trades recorded in the archive yet.")
        return

    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()

    # Left column: the year filter with every trade card under it. The
    # right column shows the stats for the trade whose ⓘ was clicked.
    left_column, right_column = st.columns([1, 2])

    with left_column:
        selected_year = st.selectbox("Select Year", ["All"] + seasons, key="trades_year")

        selected_seasons = seasons if selected_year == "All" else [selected_year]
        trades = [trade for season in selected_seasons for trade in trades_by_season[season]]
        trades.sort(key=lambda trade: trade["datetime"], reverse=True)
        if not trades:
            st.info("No trades found for this selection.")
            return

        for trade in trades:
            _render_trade_card(trade, name_resolver, manager_color_map)

    with right_column:
        selected_trade_key = st.session_state.get("trades_selected_trade")
        selected_trade = next((trade for trade in trades if _trade_key(trade) == selected_trade_key), None)
        _render_trade_stats(selected_trade, name_resolver)
