"""Players tab - search for a player, see a flow chart of which manager's
team they've been on and for which weeks (collapsed into contiguous
stints, not one node per week), plus a stacked bar chart summarizing
starts vs bench per manager. See execution-plan.md Phase G.
"""

# ========================================
# IMPORTS
# ========================================

import plotly.graph_objects as go
import streamlit as st
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.layouts import ManualLayout
from streamlit_flow.state import StreamlitFlowState

from data_loader import (
    CHART_XAXIS_MAX_TICKS,
    CHART_YAXIS_MAX_TICKS,
    build_manager_color_map,
    build_manager_name_resolver,
    load_nfl_season_lengths,
    load_player_ownership,
    load_players,
    load_stat_id_labels,
    resolve_manager_name,
)

# ========================================
# CONSTANTS
# ========================================

UNROSTERED_COLOR = "#888888"
STARTER_COLOR = "#4C78A8"
BENCH_COLOR = "#B0B0B0"
STAT_CHART_COLOR = "#6B7280"

NODE_X_SPACING = 260

ZERO_POINT_GAMES_HELP = "Excludes 0-point games, assuming those are injuries/inactives rather than a real scoring outcome that should drag the average down."

# Yardage stats (stat_id_labels.json's "Pass/Rush/Rec Yds") can run into
# the hundreds in a single game, so the shared nticks cap alone gives a
# sensible axis. Every other per-game stat (TDs, Int, Fum, 2PT, Sacks,
# etc) is a small whole-number count where that same auto-scaling can
# land on a fractional dtick (e.g. 0.5) - those get a forced
# integer-only axis instead.
YARDAGE_STAT_LABELS = {"Pass Yds", "Rush Yds", "Rec Yds"}

UNROSTERED_GAME_COLOR = "#D32F2F"

NFL_GAMES_HELP = (
    "Real NFL games this player was ELIGIBLE to appear in (that season's actual NFL regular-season length minus 1 bye week, "
    "or however many fantasy weeks they were actually rostered for if that's higher - e.g. a deep playoff run), summed across "
    "every season they show up in the archive. Compare against Games (below) to see how many eligible games they went "
    "completely unrostered for - same count as the red 'Not on a Fantasy Roster' bars on the Fantasy Points per Game chart."
)

PLAYER_FILTER_WIDGET_BASE_KEYS = ("player_selected_player_id", "player_season_filter")

# ========================================
# FUNCTIONS
# ========================================


def _build_ownership_stints(timeline: list[dict]) -> list[dict]:
    """Collapses a flat per-week ownership timeline into contiguous
    stints: consecutive weeks (within a season the player has any data
    for) under the same team_id become one stint; a gap between two
    weeks the player *does* have data for, within that same season,
    becomes its own "Unrostered" stint (team_id None). Gaps ACROSS
    seasons we haven't fetched yet are NOT synthesized as "Unrostered" -
    we genuinely don't know their status those years, so no node bridges
    that gap."""
    entries_by_season: dict[int, dict[int, dict]] = {}
    for entry in timeline:
        entries_by_season.setdefault(entry["season"], {})[entry["week"]] = entry

    stints: list[dict] = []
    for season in sorted(entries_by_season):
        weeks_with_data = entries_by_season[season]
        first_week, last_week = min(weeks_with_data), max(weeks_with_data)
        current_stint = None
        for week in range(first_week, last_week + 1):
            entry = weeks_with_data.get(week)
            team_id = entry["team_id"] if entry else None
            if current_stint and current_stint["team_id"] == team_id:
                current_stint["end_week"] = week
                if entry:
                    current_stint["weeks"].append(entry)
            else:
                if current_stint:
                    stints.append(current_stint)
                current_stint = {
                    "season": season,
                    "team_id": team_id,
                    "manager_id": entry["manager_id"] if entry else "",
                    "display_name": entry["display_name"] if entry else "",
                    "start_week": week,
                    "end_week": week,
                    "weeks": [entry] if entry else [],
                }
        if current_stint:
            stints.append(current_stint)

    return stints


def _stint_week_range_label(stint: dict) -> str:
    if stint["start_week"] == stint["end_week"]:
        return f"Wk {stint['start_week']}"
    return f"Wk {stint['start_week']}-{stint['end_week']}"


def _build_full_game_list(timeline: list[dict], nfl_season_lengths: dict[str, int]) -> list[dict]:
    """timeline only has an entry for weeks SOME manager rostered this
    player - this fills in every other NFL-eligible week (that season's
    real game count minus 1 bye, same assumption as the "NFL Games"
    metric) as a synthetic {"unrostered": True, "week": N} placeholder, so
    the chart can show them as a distinct red 0 rather than silently
    omitting them. Placeholder week numbers are whichever numbers in
    1..eligible_weeks the real entries DIDN'T use - this is exact when
    the missing-week count matches placeholder_count (the typical case),
    but if a player has more gaps than the 1-bye assumption accounts for,
    only the first placeholder_count of those missing numbers get used
    (we can't tell which specific gap week is the "true" bye vs a real
    unrostered week, so this just picks consistently rather than
    guessing)."""
    real_by_season_week: dict[tuple[int, int], dict] = {(entry["season"], entry["week"]): entry for entry in timeline}
    seasons_present = sorted({entry["season"] for entry in timeline})

    full_list = []
    for season in seasons_present:
        eligible_weeks = nfl_season_lengths.get(str(season), 0) - 1
        real_weeks_this_season = sorted(week for (s, week) in real_by_season_week if s == season)
        # Placeholders fill in whatever's left after the real weeks -
        # e.g. 14 real weeks out of 15 eligible leaves exactly 1
        # placeholder.
        placeholder_count = max(0, eligible_weeks - len(real_weeks_this_season))
        missing_weeks = sorted(set(range(1, eligible_weeks + 1)) - set(real_weeks_this_season))

        # Merge real and placeholder weeks and sort by week number so
        # they appear in true chronological order within the season,
        # rather than all real weeks first followed by all placeholders.
        season_entries = [real_by_season_week[(season, week)] for week in real_weeks_this_season]
        season_entries += [{"season": season, "week": week, "unrostered": True} for week in missing_weeks[:placeholder_count]]
        season_entries.sort(key=lambda entry: entry["week"])
        full_list.extend(season_entries)

    return full_list


# ========================================
# RENDER
# ========================================


def _render_flow_chart(stints: list[dict], name_resolver: dict[str, str], manager_color_map: dict[str, str], flow_key: str) -> None:
    st.subheader("Transfers")
    nodes = []
    edges = []
    for index, stint in enumerate(stints):
        starts = sum(1 for w in stint["weeks"] if w["status"] == "starter")
        bench = sum(1 for w in stint["weeks"] if w["status"] == "bench")

        if stint["team_id"] is None:
            content = f"**Unrostered**\n\n{stint['season']} {_stint_week_range_label(stint)}"
        else:
            manager_name = resolve_manager_name(stint["manager_id"], name_resolver, stint["display_name"])
            content = f"**{manager_name}**\n\n{stint['season']} {_stint_week_range_label(stint)}\n\nStarts: {starts} · Bench: {bench}"

        nodes.append(
            StreamlitFlowNode(
                id=str(index),
                # Explicit left-to-right x position, computed here rather
                # than relying on streamlit_flow's auto-layout (found
                # 2026-08-07: nodes all rendered stacked at the same spot -
                # the ELK-based auto-layout doesn't reliably re-run across
                # reruns/different node sets under a reused component key).
                # ManualLayout below respects these positions as-is.
                pos=(index * NODE_X_SPACING, 0),
                data={"content": content},
                source_position="right",
                target_position="left",
                style={"backgroundColor": UNROSTERED_COLOR if stint["team_id"] is None else manager_color_map.get(stint["manager_id"], "#DCE8F5")},
            )
        )
        if index > 0:
            edges.append(StreamlitFlowEdge(id=f"e{index - 1}-{index}", source=str(index - 1), target=str(index)))

    state = StreamlitFlowState(nodes=nodes, edges=edges)
    streamlit_flow(
        flow_key,
        state,
        layout=ManualLayout(),
        fit_view=True,
        height=300,
        show_controls=True,
        get_node_on_click=False,
    )


def _render_manager_summary_chart(stints: list[dict], name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    totals: dict[str, dict] = {}
    for stint in stints:
        if stint["team_id"] is None:
            continue
        manager_id = stint["manager_id"]
        entry = totals.setdefault(manager_id, {"display_name": stint["display_name"], "starts": 0, "bench": 0})
        entry["starts"] += sum(1 for w in stint["weeks"] if w["status"] == "starter")
        entry["bench"] += sum(1 for w in stint["weeks"] if w["status"] == "bench")

    if not totals:
        st.info("This player has never been on a roster in the archive.")
        return

    rows = [
        {
            "manager_id": manager_id,
            "name": resolve_manager_name(manager_id, name_resolver, data["display_name"]),
            "starts": data["starts"],
            "bench": data["bench"],
        }
        for manager_id, data in totals.items()
    ]
    rows.sort(key=lambda row: -(row["starts"] + row["bench"]))
    names = [row["name"] for row in rows]

    # Same combined text on both traces so hovering either the bench or
    # starter segment of a stacked bar shows one single pane with
    # everything, rather than two separate per-trace tooltip boxes.
    hover_text = []
    for row in rows:
        total_games = row["starts"] + row["bench"]
        start_pct = (row["starts"] / total_games * 100) if total_games else 0.0
        hover_text.append(f"{row['name']}<br>Starts: {row['starts']}<br>Bench: {row['bench']}<br>Start %: {start_pct:.1f}%")

    # Starter segment uses each manager's own color (same map as the
    # History pie chart / flow-chart nodes); bench stays a flat neutral
    # color regardless of manager.
    starter_colors = [manager_color_map.get(row["manager_id"], STARTER_COLOR) for row in rows]

    # At most CHART_YAXIS_MAX_TICKS y-axis ticks - skip the rest rather
    # than letting a dtick=1 axis grow a tick per game for high-usage
    # players.
    max_stack_total = max((row["starts"] + row["bench"] for row in rows), default=0)
    y_dtick = max(1, -(-max_stack_total // CHART_YAXIS_MAX_TICKS))

    figure = go.Figure()
    figure.add_bar(name="Bench", x=names, y=[row["bench"] for row in rows], marker_color=BENCH_COLOR, customdata=hover_text, hovertemplate="%{customdata}<extra></extra>")
    figure.add_bar(name="Starter", x=names, y=[row["starts"] for row in rows], marker_color=starter_colors, customdata=hover_text, hovertemplate="%{customdata}<extra></extra>")
    figure.update_layout(
        title="Starts vs Bench by Manager",
        barmode="stack",
        xaxis_title="Manager",
        xaxis=dict(nticks=CHART_XAXIS_MAX_TICKS),
        yaxis_title="Games",
        yaxis=dict(dtick=y_dtick, tickformat="d"),
        margin=dict(t=40, b=0, l=0, r=0),
    )
    st.plotly_chart(figure, width="stretch")


def _render_points_metrics(timeline: list[dict]) -> None:
    # 0-point games (starter or bench) are assumed to be injuries/
    # inactives rather than a real scoring outcome, so both averages
    # exclude them rather than letting them drag the average down.
    starter_points = [entry["points"] for entry in timeline if entry["status"] == "starter" and entry["points"] != 0]
    bench_points = [entry["points"] for entry in timeline if entry["status"] == "bench" and entry["points"] != 0]
    zero_point_starts = sum(1 for entry in timeline if entry["status"] == "starter" and entry["points"] == 0)
    zero_point_bench = sum(1 for entry in timeline if entry["status"] == "bench" and entry["points"] == 0)

    points_per_start = sum(starter_points) / len(starter_points) if starter_points else 0.0
    points_per_bench = sum(bench_points) / len(bench_points) if bench_points else 0.0

    start_column, bench_column, zero_start_column, zero_bench_column = st.columns(4)
    start_column.metric("Points per Fantasy Start", f"{points_per_start:.2f}", help=ZERO_POINT_GAMES_HELP)
    bench_column.metric("Points per Fantasy Bench", f"{points_per_bench:.2f}", help=ZERO_POINT_GAMES_HELP)
    zero_start_column.metric("0-Point Starts", zero_point_starts)
    zero_bench_column.metric("0-Point Bench", zero_point_bench)


def _render_fantasy_points_per_game_chart(
    timeline: list[dict], name_resolver: dict[str, str], manager_color_map: dict[str, str], nfl_season_lengths: dict[str, int]
) -> None:
    """One bar per NFL-eligible game that season (see
    _build_full_game_list) - solid in that week's manager color if
    started, flat gray (same BENCH_COLOR as the starts-vs-bench chart) if
    benched, flat red if the player was eligible but not on ANY fantasy
    roster that week. Same x-axis/season-boundary-line treatment as the
    Matchups tab's Point Differential chart, since this is the same "one bar
    per game, chronological" shape."""
    st.subheader("Fantasy Points per Game")

    full_game_list = _build_full_game_list(timeline, nfl_season_lengths)

    x_labels, points, colors, hover_text = [], [], [], []
    legend_entries: dict[str, str] = {}  # manager display name -> color, insertion-ordered
    has_bench = False
    has_unrostered = False
    for entry in full_game_list:
        if entry.get("unrostered"):
            x_labels.append(f"{entry['season']} Wk{entry['week']}")
            points.append(0.0)
            colors.append(UNROSTERED_GAME_COLOR)
            hover_text.append(f"{entry['season']} · Week {entry['week']}<br>Not on a fantasy roster")
            has_unrostered = True
            continue

        manager_name = resolve_manager_name(entry["manager_id"], name_resolver, entry.get("display_name", ""))
        is_starter = entry["status"] == "starter"
        x_labels.append(f"{entry['season']} Wk{entry['week']}")
        points.append(entry["points"])
        bar_color = manager_color_map.get(entry["manager_id"], STARTER_COLOR) if is_starter else BENCH_COLOR
        colors.append(bar_color)
        hover_text.append(f"{entry['season']} · Week {entry['week']}<br>{manager_name}<br>{'Starter' if is_starter else 'Bench'}<br>Points: {entry['points']:.2f}")
        if is_starter:
            legend_entries.setdefault(manager_name, bar_color)
        else:
            has_bench = True

    x_positions = list(range(len(full_game_list)))

    # One centered tick label per season (its year) rather than a label
    # per week - a career-spanning player has far too many weeks for
    # per-week ticks to stay readable, same treatment as the Matchups tab's
    # Point Differential chart when no single season is selected.
    positions_by_season: dict[int, list[int]] = {}
    for index, entry in enumerate(full_game_list):
        positions_by_season.setdefault(entry["season"], []).append(index)
    tick_positions = [sum(positions) / len(positions) for positions in positions_by_season.values()]
    tick_text = [str(season) for season in positions_by_season]

    figure = go.Figure(
        go.Bar(x=x_positions, y=points, marker_color=colors, customdata=hover_text, hovertemplate="%{customdata}<extra></extra>", showlegend=False)
    )

    # The bar trace itself has no per-bar legend (its color varies point
    # to point, which Plotly can't reflect in a single trace's legend
    # entry) - invisible marker-only traces stand in as a manager
    # name/color key instead, one per manager who started this player at
    # least once, plus "Bench"/"Not on a Fantasy Roster" if applicable.
    for manager_name, color in legend_entries.items():
        figure.add_scatter(x=[None], y=[None], mode="markers", marker=dict(size=10, color=color), name=manager_name, showlegend=True)
    if has_bench:
        figure.add_scatter(x=[None], y=[None], mode="markers", marker=dict(size=10, color=BENCH_COLOR), name="Bench", showlegend=True)
    if has_unrostered:
        figure.add_scatter(x=[None], y=[None], mode="markers", marker=dict(size=10, color=UNROSTERED_GAME_COLOR), name="Not on a Fantasy Roster", showlegend=True)

    # A 0-height bar has no height to hover over, so it's otherwise
    # unreachable - a marker dot at y=0 (same color/hover text as the bar
    # it sits on) keeps every game hoverable regardless of score. This
    # covers both genuine 0-point games (gray/manager-colored, per their
    # actual bar color) and unrostered placeholders (red).
    zero_indices = [index for index, value in enumerate(points) if value == 0]
    if zero_indices:
        figure.add_scatter(
            x=[x_positions[i] for i in zero_indices],
            y=[0] * len(zero_indices),
            mode="markers",
            marker=dict(size=8, color=[colors[i] for i in zero_indices], line=dict(width=1, color="#333333")),
            customdata=[hover_text[i] for i in zero_indices],
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )

    figure.update_layout(
        title="Fantasy Points per Game",
        xaxis=dict(title="Season", tickangle=0, tickmode="array", tickvals=tick_positions, ticktext=tick_text),
        yaxis_title="Points",
        yaxis=dict(nticks=CHART_YAXIS_MAX_TICKS),
        legend=dict(x=1, y=1, xanchor="right", yanchor="top", bgcolor="rgba(255,255,255,0.6)", bordercolor="#888888", borderwidth=1),
        margin=dict(t=40, b=0, l=0, r=0),
    )

    for index, entry in enumerate(full_game_list):
        if index > 0 and entry["season"] != full_game_list[index - 1]["season"]:
            figure.add_vline(x=index - 0.5, line_dash="dash", line_color="#888888")

    st.plotly_chart(figure, width="stretch")


def _render_stat_chart(timeline: list[dict], stat_id_labels: dict[str, str], nfl_season_lengths: dict[str, int]) -> None:
    """A dropdown-selected raw stat (Pass Yds, Rush TD, etc, decoded via
    archive/stat_id_labels.json) charted the same way as Fantasy Points
    per Game above - one bar per NFL-eligible game that season (see
    _build_full_game_list): a missing stat on a real roster week is
    treated as a real 0 (e.g. an injury/inactive week still shows up as a
    0 rather than silently vanishing), and weeks the player was eligible
    but on NO fantasy roster at all render as a distinct red 0, same as
    the Fantasy Points chart. Year-only x-ticks, dashed season-boundary
    lines, single flat gray for real games - not manager-colored, since
    this isn't about who owned the player."""
    st.subheader("NFL Stats per Game")

    # Only stats this specific player actually has data for, in
    # stat_id_labels.json's own order (roughly passing -> rushing ->
    # receiving -> kicking -> defense) - a QB shouldn't see "Rec Yds" as
    # an option at all.
    available_stat_ids = [stat_id for stat_id in stat_id_labels if any(stat_id in entry.get("stats", {}) for entry in timeline)]
    if not available_stat_ids:
        st.info("No detailed stat breakdown available for this player.")
        return

    selected_stat_id = st.selectbox(
        "Stat to chart",
        available_stat_ids,
        format_func=lambda stat_id: stat_id_labels.get(stat_id, stat_id),
        index=0,
        key="player_stat_chart_selection",
        label_visibility="collapsed",
    )

    stat_label = stat_id_labels.get(selected_stat_id, selected_stat_id)
    full_game_list = _build_full_game_list(timeline, nfl_season_lengths)

    values, colors, hover_text = [], [], []
    has_unrostered = False
    for entry in full_game_list:
        if entry.get("unrostered"):
            values.append(0.0)
            colors.append(UNROSTERED_GAME_COLOR)
            hover_text.append(f"{entry['season']} · Week {entry['week']}<br>Not on a fantasy roster")
            has_unrostered = True
            continue
        value = float(entry.get("stats", {}).get(selected_stat_id, 0) or 0)
        values.append(value)
        colors.append(STAT_CHART_COLOR)
        hover_text.append(f"{entry['season']} · Week {entry['week']}<br>{stat_label}: {value:g}")

    x_positions = list(range(len(full_game_list)))
    positions_by_season: dict[int, list[int]] = {}
    for index, entry in enumerate(full_game_list):
        positions_by_season.setdefault(entry["season"], []).append(index)
    tick_positions = [sum(positions) / len(positions) for positions in positions_by_season.values()]
    tick_text = [str(season) for season in positions_by_season]

    if stat_label in YARDAGE_STAT_LABELS:
        y_axis_config = dict(nticks=CHART_YAXIS_MAX_TICKS)
    else:
        max_value = max(values, default=0)
        y_dtick = max(1, -(-int(max_value) // CHART_YAXIS_MAX_TICKS))
        y_axis_config = dict(dtick=y_dtick, tickformat="d")

    figure = go.Figure(
        go.Bar(x=x_positions, y=values, marker_color=colors, customdata=hover_text, hovertemplate="%{customdata}<extra></extra>", showlegend=False)
    )
    if has_unrostered:
        figure.add_scatter(x=[None], y=[None], mode="markers", marker=dict(size=10, color=UNROSTERED_GAME_COLOR), name="Not on a Fantasy Roster", showlegend=True)
    figure.update_layout(
        title=f"{stat_label} per Game",
        xaxis=dict(title="Season", tickangle=0, tickmode="array", tickvals=tick_positions, ticktext=tick_text),
        yaxis_title=stat_label,
        yaxis=y_axis_config,
        legend=dict(x=1, y=1, xanchor="right", yanchor="top", bgcolor="rgba(255,255,255,0.6)", bordercolor="#888888", borderwidth=1),
        margin=dict(t=40, b=0, l=0, r=0),
    )
    for index, entry in enumerate(full_game_list):
        if index > 0 and entry["season"] != full_game_list[index - 1]["season"]:
            figure.add_vline(x=index - 0.5, line_dash="dash", line_color="#888888")

    # A 0-value bar has no height to hover over, so it's otherwise
    # unreachable - a marker dot at y=0 (same color/hover text) keeps
    # every game hoverable regardless of value, same treatment as the
    # Fantasy Points per Game chart's zero-point/unrostered games.
    zero_indices = [index for index, value in enumerate(values) if value == 0]
    if zero_indices:
        figure.add_scatter(
            x=[x_positions[i] for i in zero_indices],
            y=[0] * len(zero_indices),
            mode="markers",
            marker=dict(size=8, color=[colors[i] for i in zero_indices], line=dict(width=1, color="#333333")),
            customdata=[hover_text[i] for i in zero_indices],
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )

    st.plotly_chart(figure, width="stretch")


def _render_summary_metrics(timeline: list[dict], nfl_season_lengths: dict[str, int]) -> None:
    # "Games" only counts weeks with a player_ownership.json entry - i.e.
    # weeks SOME manager had them rostered. A season this player appears
    # in at all but wasn't rostered every eligible week won't show that
    # gap anywhere else, so "NFL Games" (their real eligible game count,
    # bye week excluded) sits right next to it for direct comparison.
    # Shares _build_full_game_list with the Fantasy Points per Game chart
    # below (rather than a separately netted per-season sum) so the two
    # can never disagree - some seasons have MORE real entries than the
    # naive "regular season - 1 bye" estimate (a deep fantasy playoff run
    # extends past that), and only a per-season-clamped, shared
    # computation stays consistent with the chart's actual placeholder count.
    nfl_games = len(_build_full_game_list(timeline, nfl_season_lengths))

    starts = sum(1 for entry in timeline if entry["status"] == "starter")
    bench = sum(1 for entry in timeline if entry["status"] == "bench")
    start_pct = starts / len(timeline) if timeline else 0.0
    managers = len({entry["manager_id"] for entry in timeline if entry["manager_id"]})

    nfl_games_column, games_column, starts_column, bench_column, start_pct_column, managers_column = st.columns(6)
    nfl_games_column.metric("NFL Games", nfl_games, help=NFL_GAMES_HELP)
    games_column.metric("Games", len(timeline))
    starts_column.metric("Starts", starts)
    bench_column.metric("Bench", bench)
    start_pct_column.metric("Start %", f"{start_pct:.1%}")
    managers_column.metric("Managers", managers)


def render_players_page() -> None:
    players_data = load_players()["players"]
    ownership_data = load_player_ownership()["player_ownership"]
    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()
    stat_id_labels = load_stat_id_labels()
    nfl_season_lengths = load_nfl_season_lengths()

    if not players_data:
        st.info("No players in the archive yet.")
        return

    player_names_by_id = {player_id: player["name"] for player_id, player in players_data.items()}
    sorted_player_ids = sorted(player_names_by_id, key=lambda player_id: player_names_by_id[player_id])

    # Same versioned-widget-key pattern as the Matchups tab's Clear Filters:
    # each filter's ACTUAL key includes a generation counter, so Clear
    # Filters can bump the counter and force brand-new widget instances
    # instead of relying on session_state deletion alone, which left
    # stale-looking dropdowns in some browsers even after the underlying
    # value was cleared (see pages_matchups.py's _render_filters).
    generation = st.session_state.setdefault("player_filters_generation", 0)

    def versioned_key(base_key: str) -> str:
        return f"{base_key}_gen{generation}"

    for base_key in PLAYER_FILTER_WIDGET_BASE_KEYS:
        widget_key = versioned_key(base_key)
        if widget_key not in st.session_state and base_key in st.session_state:
            st.session_state[widget_key] = st.session_state[base_key]

    player_column, season_column = st.columns(2)
    with player_column:
        selected_player_id = st.selectbox(
            "Search for a player",
            sorted_player_ids,
            format_func=lambda player_id: player_names_by_id[player_id],
            index=None,
            placeholder="Type a player's name...",
            key=versioned_key("player_selected_player_id"),
        )

    # Only seasons this specific player actually has data for - same
    # "Any" (single season or all) treatment as the Matchups tab's Season
    # filter.
    player_seasons = sorted({entry["season"] for entry in ownership_data.get(selected_player_id, [])}) if selected_player_id else []
    season_widget_key = versioned_key("player_season_filter")
    # A previously-picked season can fall outside the new player's
    # player_seasons (e.g. a season picked before switching players) -
    # Streamlit errors if a selectbox's existing session_state value
    # isn't in its options list, so clear it first rather than letting
    # that happen.
    if st.session_state.get(season_widget_key) not in player_seasons and st.session_state.get(season_widget_key) is not None:
        st.session_state[season_widget_key] = None
    with season_column:
        selected_season = st.selectbox(
            "Season",
            player_seasons,
            index=None,
            placeholder="Any",
            disabled=selected_player_id is None,
            help="Select a player first" if selected_player_id is None else None,
            key=season_widget_key,
        )

    st.session_state["player_selected_player_id"] = selected_player_id
    st.session_state["player_season_filter"] = selected_season

    # use_container_width=True fills container
    # don't use gap=0, otherwise no padding between buttons
    # NOTE use same `apply_column, clear_column, _ = st.columns([1, 1, 6])` for any filtering pages
    apply_column, clear_column, _ = st.columns([1, 1, 6])
    with apply_column:
        applied = st.button(
            "Apply Filters",
            disabled=selected_player_id is None,
            help="Select a player first" if selected_player_id is None else None,
            use_container_width=True,
        )
    with clear_column:
        if st.button("Clear Filters", use_container_width=True):
            for base_key in PLAYER_FILTER_WIDGET_BASE_KEYS:
                st.session_state.pop(base_key, None)
            st.session_state.pop("player_applied_filters", None)
            st.session_state["player_filters_generation"] = generation + 1
            st.rerun()

    if applied:
        st.session_state["player_applied_filters"] = {"player_id": selected_player_id, "season": selected_season}

    applied_filters = st.session_state.get("player_applied_filters")
    if applied_filters is None:
        st.info("Set your filters above and click Apply Filters.")
        return

    selected_player_id = applied_filters["player_id"]
    selected_season = applied_filters["season"]

    full_timeline = ownership_data.get(selected_player_id, [])
    if not full_timeline:
        st.info(f"{player_names_by_id[selected_player_id]} has never been on a roster in the archive.")
        return

    timeline = [entry for entry in full_timeline if entry["season"] == selected_season] if selected_season else full_timeline

    stints = _build_ownership_stints(timeline)

    st.subheader(f"{player_names_by_id[selected_player_id]} ({players_data[selected_player_id]['position']})")
    st.divider()
    _render_summary_metrics(timeline, nfl_season_lengths)
    st.divider()
    _render_manager_summary_chart(stints, name_resolver, manager_color_map)
    st.divider()
    _render_flow_chart(stints, name_resolver, manager_color_map, flow_key=f"player_ownership_flow_{selected_player_id}")
    st.divider()
    _render_points_metrics(timeline)
    st.divider()
    _render_fantasy_points_per_game_chart(timeline, name_resolver, manager_color_map, nfl_season_lengths)
    st.divider()
    _render_stat_chart(timeline, stat_id_labels, nfl_season_lengths)
