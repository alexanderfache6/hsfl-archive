import plotly.graph_objects as go
import streamlit as st
from colors import (
    COLOR_CHART_PICK,
    COLOR_CHART_SCATTER_MARKER_OUTLINE,
    COLOR_CHART_STAT,
    COLOR_MANAGER_BACKUP,
    COLOR_PERCENTILE_OTHER_PLAYERS,
    COLOR_PERCENTILE_SELECTED_PLAYER,
)
from constants import CHART_LINE_AUCTION_WIDTH, ORDINAL_WORDS, SCATTER_PLOT_MARKER_SIZE_MEDIUM
from data_loader import (
    contrasting_text_color,
    discover_seasons,
    load_draft,
    load_player_fantasy_value_metrics,
    load_player_ownership,
    resolve_manager_name,
    team_id_to_manager_map,
)


def manager_pill(manager_id: str, name_resolver: dict[str, str], manager_color_map: dict[str, str], label: str | None = None) -> str:
    name = resolve_manager_name(manager_id, name_resolver)
    text = f"{label} ({name})" if label else name
    background_color = manager_color_map.get(manager_id, COLOR_MANAGER_BACKUP)
    text_color = contrasting_text_color(background_color)
    return f"<span style='background-color:{background_color}; color:{text_color}; padding:2px 8px; border-radius:6px; font-weight:600; white-space:nowrap;'>{text}</span>"


def ordinal_word(n: int) -> str:
    if 0 <= n < len(ORDINAL_WORDS):
        return ORDINAL_WORDS[n]
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def return_plural(check, singular, plural) -> str:
    return singular if check == 1 else plural


def return_s(check):
    return "s" if check != 1 else ""


def check_keeper_pick_criteria(pick):
    is_snake_era_keeper = pick["draft_type"] == "snake" and pick["overall_pick"] <= pick["num_teams"]
    is_auction_era_keeper = pick["draft_type"] == "auction" and pick["auction_amount"] is None
    return is_snake_era_keeper or is_auction_era_keeper


# get picks from auction era with auction value
def check_auction_pick_criteria(pick):
    return pick["draft_type"] == "auction" and pick["auction_amount"] is not None


def build_picks_by_player() -> dict[str, list[dict]]:
    """{player_name: [{"season", "draft_type", "overall_pick",
    "auction_amount", "num_teams", "position", "player_id",
    "total_picks"}, ...]} - every draft pick across every season in the
    archive, keyed by player name. Shared by pages_drafts.py's Player
    Analysis tab and pages_players.py's Value Analysis tab - built once
    here rather than each page re-scanning discover_seasons()/load_draft()
    on its own."""
    picks_by_player: dict[str, list[dict]] = {}
    for season in discover_seasons():
        draft = load_draft(season)
        if not draft:
            continue
        num_teams = len(team_id_to_manager_map(season))
        total_picks = len(draft["picks"])
        for pick in draft["picks"]:
            picks_by_player.setdefault(pick["player_name"], []).append(
                {
                    "season": season,
                    "draft_type": draft["draft_type"],
                    "overall_pick": pick["overall_pick"],
                    "auction_amount": pick.get("auction_amount"),
                    "num_teams": num_teams,
                    "position": pick["position"],
                    "player_id": pick.get("player_id"),
                    "total_picks": total_picks,
                }
            )
    return picks_by_player


FANTASY_VALUE_STAT_FIELDS = {
    ("Total Fantasy Points", False): "total_fantasy_points",
    ("Total Fantasy Points", True): "fantasy_value_per_season",
    ("Per Game Fantasy Points", False): "fantasy_points_per_game",
    ("Per Game Fantasy Points", True): "fantasy_value_per_game",
    ("Per Game Fantasy Points Box Plots", False): "fantasy_points_per_game",
    ("Per Game Fantasy Points Box Plots", True): "fantasy_value_per_game",
}


def render_fantasy_value_section(selected_player: str, player_picks: list[dict], widget_key_prefix: str) -> None:
    """Reads code/stats-aggregation/generate_player_fantasy_value_metrics.py's
    precomputed archive/player_fantasy_value_metrics.json (run weekly,
    not recomputed here) rather than deriving fantasy value from
    player_ownership.json/draft.json directly - that script already
    resolves per-season cost (real $ for auction, a pseudo-cost for
    snake, KEEPER_DEFAULT_COST for keepers) once for every drafted
    player, not just the one being viewed here. Shared by
    pages_drafts.py and pages_players.py's Value Analysis tab -
    widget_key_prefix keeps each caller's own widget keys from colliding
    when both render on the same script run."""
    st.subheader("Fantasy Value")

    st.warning("value assessment is very raw, take with large grain of salt")

    metrics_by_season = load_player_fantasy_value_metrics()["player_fantasy_value_metrics"]
    player_id = player_picks[0].get("player_id")

    seasons = sorted(int(season) for season, entries in metrics_by_season.items() if any(entry["player_id"] == player_id for entry in entries))
    if not seasons:
        st.info("No fantasy value data available for this player yet - run generate_player_fantasy_value_metrics.py.")
        return

    stat_column, adjustment_column, view_column = st.columns(3)
    selected_stat = stat_column.selectbox(
        "Select stat to view",
        ["Total Fantasy Points", "Per Game Fantasy Points", "Per Game Fantasy Points Box Plots"],
        key=f"{widget_key_prefix}_fantasy_stat",
    )
    selected_adjustment = adjustment_column.selectbox(
        "Adjustment",
        ["Fantasy Points", "Adjusted Fantasy Points"],
        key=f"{widget_key_prefix}_fantasy_adjustment",
        help="Adjusted fantasy points try to take into account draft position and cost to assess fantasy value. Fantasy value is fantasy points divided by cost. Auction draft cost (1) auction price or (2) $50 if keeper. Snake draft cost (3) number of players - pick.",
    )
    is_box_plot = selected_stat == "Per Game Fantasy Points Box Plots"
    # Box Plots ONLY work for the searched player individually (one box
    # per season of THEIR OWN weekly points) - "The Field" has no
    # meaning here. Forced back to "Individual" in session_state (not
    # just disabled in the UI) so switching Stat to Box Plots can't leave
    # a stale "The Field" selection sitting underneath the disabled
    # widget, which would still be what gets read below.
    view_widget_key = f"{widget_key_prefix}_fantasy_view"
    if is_box_plot:
        st.session_state[view_widget_key] = "Individual"
    selected_view = view_column.selectbox(
        "View",
        ["Individual", "The Field"],
        disabled=is_box_plot,
        help="View detailed individual stats or stats vs all players in same position." if is_box_plot else None,
        key=view_widget_key,
    )
    is_adjusted = selected_adjustment == "Adjusted Fantasy Points"
    stat_field = FANTASY_VALUE_STAT_FIELDS[(selected_stat, is_adjusted)]

    fantasy_figure = go.Figure()

    if selected_stat == "Per Game Fantasy Points Box Plots":
        # One box per season of the SEARCHED PLAYER's OWN weekly fantasy
        # points - not the field (that's what "The Field" view is for on
        # the other two stats, and it's disabled here for exactly that
        # reason). Needs the real weekly numbers, which
        # player_fantasy_value_metrics.json doesn't carry (it's already
        # aggregated to one row per player-season) - reads
        # player_ownership.json's own per-week timeline instead.
        weekly_points_by_season: dict[int, list[float]] = {}
        for entry in load_player_ownership()["player_ownership"].get(player_id, []):
            weekly_points_by_season.setdefault(entry["season"], []).append(entry["points"])

        for season in seasons:
            weekly_points = weekly_points_by_season.get(season, [])
            if not weekly_points:
                continue
            if is_adjusted:
                own_entry = next((entry for entry in metrics_by_season[str(season)] if entry["player_id"] == player_id), None)
                cost = own_entry["cost"] if own_entry else None
                if not cost:
                    continue
                values = [points / cost for points in weekly_points]
            else:
                values = weekly_points
            fantasy_figure.add_trace(
                go.Box(
                    y=values,
                    x=[str(season)] * len(values),
                    name=str(season),
                    marker={"color": COLOR_CHART_STAT},
                    line={"color": COLOR_CHART_STAT},
                    showlegend=False,
                )
            )
        yaxis_title = ("Adjusted " if is_adjusted else "") + "Points per Game"
    elif selected_view == "The Field":
        # Same "peer scatter + one highlighted player" pattern as
        # pages_players.py's percentile chart - every OTHER player's own
        # (season, stat) point plotted as one shared trace, the searched
        # player's own points as a second, outlined trace on top. "The
        # Field" is scoped to the searched player's OWN position only -
        # a kicker's fantasy value isn't a meaningful comparison against
        # a QB's, same reasoning as the Vs Position chart above.
        selected_position = player_picks[-1]["position"]
        other_x, other_y, other_hover = [], [], []
        selected_x, selected_y, selected_hover = [], [], []
        for season in seasons:
            for entry in metrics_by_season[str(season)]:
                if entry["position"] != selected_position:
                    continue
                value = entry[stat_field]
                if value is None:
                    continue
                if entry["player_id"] == player_id:
                    selected_x.append(str(season))
                    selected_y.append(value)
                    selected_hover.append(f"<b>{selected_player}</b><br>{season}<br>{selected_stat}: {value:.2f}")
                else:
                    other_x.append(str(season))
                    other_y.append(value)
                    other_hover.append(f"<b>{entry['player_name']}</b><br>{season}<br>{selected_stat}: {value:.2f}")
        fantasy_figure.add_trace(
            go.Scatter(
                x=other_x,
                y=other_y,
                mode="markers",
                name="Other Players",
                marker={"size": SCATTER_PLOT_MARKER_SIZE_MEDIUM, "color": COLOR_PERCENTILE_OTHER_PLAYERS, "opacity": 0.5},
                customdata=other_hover,
                hovertemplate="%{customdata}<extra></extra>",
            )
        )
        fantasy_figure.add_trace(
            go.Scatter(
                x=selected_x,
                y=selected_y,
                mode="markers",
                name=selected_player,
                marker={"size": SCATTER_PLOT_MARKER_SIZE_MEDIUM, "color": COLOR_PERCENTILE_SELECTED_PLAYER, "line": {"width": 1, "color": COLOR_CHART_SCATTER_MARKER_OUTLINE}},
                customdata=selected_hover,
                hovertemplate="%{customdata}<extra></extra>",
            )
        )
        yaxis_title = f"Adjusted {selected_stat}" if is_adjusted else selected_stat
    else:
        season_values = []
        for season in seasons:
            own_entry = next((entry for entry in metrics_by_season[str(season)] if entry["player_id"] == player_id), None)
            season_values.append(own_entry[stat_field] if own_entry else None)
        fantasy_figure.add_trace(
            go.Bar(
                x=[str(season) for season in seasons],
                y=season_values,
                name=selected_stat,
                marker={"color": COLOR_CHART_STAT},
                hovertemplate=f"<b>%{{x}}</b><br>{selected_stat}: %{{y:.2f}}<extra></extra>",
            )
        )
        yaxis_title = f"Adjusted {selected_stat}" if is_adjusted else selected_stat

    games_played_by_season = []
    for season in seasons:
        own_entry = next((entry for entry in metrics_by_season[str(season)] if entry["player_id"] == player_id), None)
        games_played_by_season.append(own_entry["games_played"] if own_entry else None)

    fantasy_figure.add_trace(
        go.Scatter(
            x=[str(season) for season in seasons],
            y=games_played_by_season,
            name="Games Played",
            mode="lines+markers",
            line={"color": COLOR_CHART_PICK, "width": CHART_LINE_AUCTION_WIDTH},
            marker={"color": COLOR_CHART_PICK, "size": SCATTER_PLOT_MARKER_SIZE_MEDIUM},
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>Games Played: %{y}<extra></extra>",
        )
    )

    max_games_played = max((value for value in games_played_by_season if value is not None), default=1)

    fantasy_figure.update_layout(
        title=f"{yaxis_title} per Season",
        xaxis={"title": "Season", "type": "category"},
        yaxis={"title": yaxis_title},
        yaxis2={"title": "Games Played", "overlaying": "y", "side": "right", "showgrid": False, "range": [0, max_games_played + 1]},
        legend={"orientation": "h", "y": 1.1, "yanchor": "bottom", "x": 0.5, "xanchor": "center"},
        margin={"t": 70, "l": 60, "r": 60, "b": 50},
    )
    st.plotly_chart(fantasy_figure, width="stretch")
