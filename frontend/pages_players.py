"""Players tab - search for a player, see a flow chart of which manager's
team they've been on and for which weeks (collapsed into contiguous
stints, not one node per week), plus a stacked bar chart summarizing
starts vs bench per manager. See execution-plan.md Phase G.
"""

# ========================================
# IMPORTS
# ========================================

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from constants import CHART_LEGEND_TOP_RIGHT, SCATTER_PLOT_MARKER_SIZE
from data_loader import (
    CHART_XAXIS_MAX_TICKS,
    CHART_YAXIS_MAX_TICKS,
    build_manager_color_map,
    build_manager_name_resolver,
    compute_stat_fantasy_points,
    get_bye_week,
    load_nfl_season_lengths,
    load_player_ownership,
    load_players,
    load_stat_id_labels,
    player_nfl_team_by_season,
    resolve_manager_name,
)
from streamlit_flow import streamlit_flow
from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
from streamlit_flow.layouts import ManualLayout
from streamlit_flow.state import StreamlitFlowState

# ========================================
# CONSTANTS
# ========================================

UNROSTERED_COLOR = "#888888"
STARTER_COLOR = "#4C78A8"
BENCH_COLOR = "#B0B0B0"
STAT_CHART_COLOR = "#6B7280"

# Percentiles tab scatter - every other qualified same-position player's
# dot vs the selected player's own dot.
PERCENTILE_OTHER_COLOR = "#888888"
PERCENTILE_SELECTED_COLOR = "#D32F2F"
PERCENTILE_MAX_OTHER_DOTS_PER_SEASON = 100

PERCENTILE_METRIC_LABELS = {"total": "Total Fantasy Points", "per_game": "Per Game Fantasy Points"}
# TODO: this is just that season's raw NFL schedule length, not adjusted
# for THIS player's own missed games (injury, suspension, etc) - a
# player who missed real games still shows the full season length here.
NFL_GAMES_PLAYED_HELP = "That season's NFL schedule length - not yet adjusted for this player's own injuries/missed games."

NODE_X_SPACING = 260

NONZERO_POINT_GAMES_HELP = "Excludes bye weeks and 0-point games. Qualifed game count in `()`."
ZERO_POINT_COUNT_HELP = "Excludes bye weeks. An indication that (1) player was injured or (2) player delivered no fantasy points." # TODO future should take into account injury games
NFL_POINTS_GAME_HELP = "Excludes bye weeks. Qualified game count in `()`."

# "Big play" = any touchdown-scoring stat line (passing/rushing/receiving/
# return/defensive TDs) - used for the Fantasy Points per Game chart's
# "Big Play Fantasy Points %" view (that week's TD-derived fantasy points
# as a % of the player's total fantasy points that week).
TOUCHDOWN_STAT_IDS = {"stat_6", "stat_15", "stat_22", "stat_50", "stat_53", "stat_76", "stat_77", "stat_78"} # NOTE from archive/stat_id_labels.json
POINTS_CHART_VIEW_LABELS = {"points": "Fantasy Points", "big_play_percentage": "Big Play Fantasy Points %"}
BIG_PLAY_PERCENTAGE_HELP = "Excludes bye weeks and 0-point games. Share of that week's fantasy points that came from touchdown-scoring stats. Qualified game count in `()`."

# Yardage stats (stat_id_labels.json's "Pass/Rush/Rec Yds") can run into
# the hundreds in a single game, so the shared nticks cap alone gives a
# sensible axis. Every other per-game stat (TDs, Int, Fum, 2PT, Sacks,
# etc) is a small whole-number count where that same auto-scaling can
# land on a fractional dtick (e.g. 0.5) - those get a forced
# integer-only axis instead.
YARDAGE_STAT_LABELS = {"Pass Yds", "Rush Yds", "Rec Yds"}

UNROSTERED_GAME_COLOR = "#D32F2F"
BYE_WEEK_COLOR = "#1E88E5"

NFL_GAMES_HELP = (
    "Real NFL games this player was eligible to appear in (that season's actual NFL regular-season length minus 1 bye week, "
    "or however many fantasy weeks they were actually rostered for if that's higher, summed across "
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
    real game count minus 1 bye) as a synthetic {"unrostered": True,
    "week": N} placeholder, so the chart can show them as a distinct red
    0 rather than silently omitting them. Every week in 1..eligible_weeks
    without a real entry gets a placeholder - not capped to a single
    assumed bye's worth (eligible_weeks - real_week_count): a player can
    have MORE than one real gap in a season (e.g. a rookie not added to
    any roster until several weeks in - confirmed via J. Jefferson's 2020
    player_ownership.json entries, which start at week 4, not week 1),
    and capping the placeholder count to "just the bye" silently dropped
    those extra gap weeks from the chart entirely instead of showing them
    as unrostered. We still can't tell which specific missing week was
    this player's own team's real bye vs a genuine unrostered gap (no bye
    schedule data is archived), so a real bye week ends up shown as a red
    "Not on a Fantasy Roster" placeholder same as any other gap - visible
    but not perfectly labeled beats being silently dropped."""
    real_by_season_week: dict[tuple[int, int], dict] = {(entry["season"], entry["week"]): entry for entry in timeline}
    seasons_present = sorted({entry["season"] for entry in timeline})

    full_list = []
    for season in seasons_present:
        eligible_weeks = nfl_season_lengths.get(str(season), 0) - 1
        real_weeks_this_season = sorted(week for (s, week) in real_by_season_week if s == season)
        missing_weeks = sorted(set(range(1, eligible_weeks + 1)) - set(real_weeks_this_season))

        # Merge real and placeholder weeks and sort by week number so
        # they appear in true chronological order within the season,
        # rather than all real weeks first followed by all placeholders.
        season_entries = [real_by_season_week[(season, week)] for week in real_weeks_this_season]
        season_entries += [{"season": season, "week": week, "unrostered": True} for week in missing_weeks]
        season_entries.sort(key=lambda entry: entry["week"])
        full_list.extend(season_entries)

    return full_list


def _bye_weeks_by_season(player_id: str) -> dict[int, int]:
    """{season: bye_week_number} for whichever seasons both this
    player's real NFL team (player_nfl_team_by_season) AND that team's
    real bye week (get_bye_week) are known - a season missing from
    either lookup (never rostered in a real matchup box score that
    season, or that team's bye week not yet published/archived) is
    simply absent here, not a KeyError risk for callers."""
    bye_weeks = {}
    for season, nfl_team in player_nfl_team_by_season(player_id).items():
        bye_week = get_bye_week(season, nfl_team)
        if bye_week is not None:
            bye_weeks[season] = bye_week
    return bye_weeks


# ========================================
# RENDER
# ========================================


def _render_flow_chart(
    stints: list[dict], name_resolver: dict[str, str], manager_color_map: dict[str, str], flow_key: str, player_id: str
) -> None:
    st.subheader("Transfers")
    bye_weeks_by_season = _bye_weeks_by_season(player_id)
    nodes = []
    edges = []
    for index, stint in enumerate(stints):
        starts = sum(1 for w in stint["weeks"] if w["status"] == "starter")
        bench = sum(1 for w in stint["weeks"] if w["status"] == "bench")

        # A stint never spans more than one season (_build_ownership_stints
        # builds them per-season) - a bye is a single week, so at most one
        # can ever fall inside any given stint's own week range. The Bye
        # segment is only included when a bye actually falls within THIS
        # stint - omitted entirely both when unknown (that team's bye not
        # archived, or this player's NFL team that season couldn't be
        # determined) and when it's known but simply doesn't land in this
        # stint's own week range, rather than showing a "Bye: Unknown" or
        # "Bye: —" placeholder either way.
        bye_week = bye_weeks_by_season.get(stint["season"])
        bye_segment = ""
        if bye_week is not None and stint["start_week"] <= bye_week <= stint["end_week"]:
            bye_segment = f" · Bye: Wk{bye_week}"

        if stint["team_id"] is None:
            content = f"**Unrostered**\n\n{stint['season']} {_stint_week_range_label(stint)}\n\nStarts: 0 · Bench: 0{bye_segment}"
        else:
            manager_name = resolve_manager_name(stint["manager_id"], name_resolver, stint["display_name"])
            content = f"**{manager_name}**\n\n{stint['season']} {_stint_week_range_label(stint)}\n\nStarts: {starts} · Bench: {bench}{bye_segment}"

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
        hover_text.append(f"<b>{row['name']}</b><br>Starts: {row['starts']}<br>Bench: {row['bench']}<br>Start %: {start_pct:.1f}%")

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
        title="Starter vs Bench by Manager",
        barmode="stack",
        xaxis_title="Manager",
        xaxis={"nticks": CHART_XAXIS_MAX_TICKS},
        yaxis_title="Fantasy Games",
        yaxis={"dtick": y_dtick, "tickformat": "d"},
        margin={"t": 40, "b": 0, "l": 0, "r": 0},
        legend=CHART_LEGEND_TOP_RIGHT,
    )
    st.plotly_chart(figure, width="stretch")


def _touchdown_fantasy_points(entry: dict, position: str) -> float:
    stats = entry.get("stats") or {}
    total = 0.0
    for stat_id, raw_value in stats.items():
        if stat_id not in TOUCHDOWN_STAT_IDS:
            continue
        stat_points = compute_stat_fantasy_points(stat_id, raw_value, position, entry["season"])
        if stat_points:
            total += stat_points
    return total


def _big_play_percentage(entry: dict, position: str) -> tuple[float, float] | tuple[None, None]:
    """(percentage, points_from_touchdowns) - (None, None) (not 0) when
    there are no fantasy points that week to take a share of. A real
    percentage here, even negative or over 100%, is still a real
    reflection of that week's stat line."""
    if not entry.get("points"):
        return None, None

    points_from_touchdowns = _touchdown_fantasy_points(entry, position)
    return points_from_touchdowns / entry["points"] * 100, points_from_touchdowns


def _render_points_metrics(timeline: list[dict], player_id: str, position: str, view_mode: str) -> None:
    # 0-point games (starter or bench) are assumed to be injuries/
    # inactives rather than a real scoring outcome, so both averages
    # exclude them rather than letting them drag the average down - a
    # bye-week 0 is already excluded here too, same as any other 0.
    starter_points = [entry["points"] for entry in timeline if entry["status"] == "starter" and entry["points"] != 0]
    bench_points = [entry["points"] for entry in timeline if entry["status"] == "bench" and entry["points"] != 0]

    # The 0-Point Starts/Bench COUNTS below are meant to flag genuine
    # injuries/inactives - a real bye week's 0 isn't that, so it's
    # excluded from the count too (not just the averages above).
    bye_weeks_by_season = _bye_weeks_by_season(player_id)
    zero_point_starts = sum(
        1
        for entry in timeline
        if entry["status"] == "starter" and entry["points"] == 0 and bye_weeks_by_season.get(entry["season"]) != entry["week"]
    )
    zero_point_bench = sum(
        1
        for entry in timeline
        if entry["status"] == "bench" and entry["points"] == 0 and bye_weeks_by_season.get(entry["season"]) != entry["week"]
    )

    start_column, bench_column, zero_start_column, zero_bench_column = st.columns(4)
    if view_mode == "big_play_percentage":
        starter_entries_nonzero = [entry for entry in timeline if entry["status"] == "starter" and entry["points"] != 0]
        starter_percentages = [pct for entry in starter_entries_nonzero for pct, _ in [_big_play_percentage(entry, position)] if pct is not None]
        big_play_pct_per_start = sum(starter_percentages) / len(starter_percentages) if starter_percentages else 0.0
        start_column.metric("Big Play % per Fantasy Start", f"{big_play_pct_per_start:.1f}% ({len(starter_percentages)})", help=BIG_PLAY_PERCENTAGE_HELP)

        bench_entries_nonzero = [entry for entry in timeline if entry["status"] == "bench" and entry["points"] != 0]
        bench_percentages = [pct for entry in bench_entries_nonzero for pct, _ in [_big_play_percentage(entry, position)] if pct is not None]
        big_play_pct_per_bench = sum(bench_percentages) / len(bench_percentages) if bench_percentages else 0.0
        bench_column.metric("Big Play % per Fantasy Bench", f"{big_play_pct_per_bench:.1f}% ({len(bench_percentages)})", help=BIG_PLAY_PERCENTAGE_HELP)
    else:
        points_per_start = sum(starter_points) / len(starter_points) if starter_points else 0.0
        start_column.metric("Points per Fantasy Start", f"{points_per_start:.2f} ({len(starter_points)})", help=NONZERO_POINT_GAMES_HELP)

        points_per_bench = sum(bench_points) / len(bench_points) if bench_points else 0.0
        bench_column.metric("Points per Fantasy Bench", f"{points_per_bench:.2f} ({len(bench_points)})", help=NONZERO_POINT_GAMES_HELP)
    zero_start_column.metric("0-Point Starts", zero_point_starts, help=ZERO_POINT_COUNT_HELP)
    zero_bench_column.metric("0-Point Bench", zero_point_bench, help=ZERO_POINT_COUNT_HELP)


def _render_fantasy_points_per_game_chart(
    timeline: list[dict],
    name_resolver: dict[str, str],
    manager_color_map: dict[str, str],
    nfl_season_lengths: dict[str, int],
    player_id: str,
    position: str,
    view_mode: str,
) -> None:
    """One bar per NFL-eligible game that season (see
    _build_full_game_list) - solid in that week's manager color if
    started, flat gray (same BENCH_COLOR as the starts-vs-bench chart) if
    benched, flat red if the player was eligible but not on ANY fantasy
    roster that week. Same x-axis/season-boundary-line treatment as the
    Matchups tab's Point Differential chart, since this is the same "one bar
    per game, chronological" shape."""

    full_game_list = _build_full_game_list(timeline, nfl_season_lengths)
    bye_weeks_by_season = _bye_weeks_by_season(player_id)

    x_labels, points, colors, hover_text, is_bye_week, bye_hover_text = [], [], [], [], [], []
    legend_entries: dict[str, str] = {}  # manager display name -> color, insertion-ordered
    has_bench = False
    has_unrostered = False
    for entry in full_game_list:
        is_bye_week.append(bye_weeks_by_season.get(entry["season"]) == entry["week"])
        if entry.get("unrostered"):
            x_labels.append(f"{entry['season']} Wk{entry['week']}")
            points.append(0.0)
            colors.append(UNROSTERED_GAME_COLOR)
            hover_text.append(
                f"<b>{entry['season']} · Week {entry['week']}</b><br>"
                "Not on a fantasy roster"
            )
            bye_hover_text.append(
                f"<b>{entry['season']} · Week {entry['week']}</b><br>"
                "Bye Week"
            )
            has_unrostered = True
            continue

        manager_name = resolve_manager_name(entry["manager_id"], name_resolver, entry.get("display_name", ""))
        is_starter = entry["status"] == "starter"
        x_labels.append(f"{entry['season']} Wk{entry['week']}")
        if view_mode == "big_play_percentage":
            big_play_percentage, big_play_points = _big_play_percentage(entry, position)
            points.append(big_play_percentage or 0.0)
        else:
            points.append(entry["points"])
        bar_color = manager_color_map.get(entry["manager_id"], STARTER_COLOR) if is_starter else BENCH_COLOR
        colors.append(bar_color)
        if view_mode == "big_play_percentage":
            hover_text.append(
                f"<b>{entry['season']} · Week {entry['week']}</b><br>"
                f"{manager_name}<br>{'Starter' if is_starter else 'Bench'}<br>"
                f"Points: {entry['points']:.2f}<br>"
                f"Points from Big Plays: {big_play_points or 0.0:.2f}<br>"
                f"Big Play Points %: {big_play_percentage or 0.0:.1f}%"
            )
        else:
            hover_text.append(
                f"<b>{entry['season']} · Week {entry['week']}</b><br>"
                f"{manager_name}<br>{'Starter' if is_starter else 'Bench'}<br>"
                f"Points: {entry['points']:.2f}<br>"
            )
        bye_hover_text.append(f"<b>{entry['season']} · Week {entry['week']}</b><br>Bye Week")
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
        figure.add_scatter(x=[None], y=[None], mode="markers", marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": color}, name=manager_name, showlegend=True)
    if has_bench:
        figure.add_scatter(x=[None], y=[None], mode="markers", marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": BENCH_COLOR}, name="Bench", showlegend=True)
    if any(is_bye_week):
        figure.add_scatter(x=[None], y=[None], mode="markers", marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": BYE_WEEK_COLOR}, name="Bye Week", showlegend=True)
    if has_unrostered:
        figure.add_scatter(x=[None], y=[None], mode="markers", marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": UNROSTERED_GAME_COLOR}, name="Not on a Fantasy Roster", showlegend=True)

    # A 0-height bar has no height to hover over, so it's otherwise
    # unreachable - a marker dot at y=0 (same color/hover text as the bar
    # it sits on) keeps every game hoverable regardless of score. This
    # covers both genuine 0-point games (gray/manager-colored, per their
    # actual bar color) and unrostered placeholders (red). Bye weeks are
    # excluded here entirely - they get their own distinct blue marker
    # below instead of this one sitting underneath it.
    zero_indices = [index for index, value in enumerate(points) if value == 0 and not is_bye_week[index]]
    if zero_indices:
        figure.add_scatter(
            x=[x_positions[i] for i in zero_indices],
            y=[0] * len(zero_indices),
            mode="markers",
            marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": [colors[i] for i in zero_indices], "line": {"width": 1, "color": "#333333"}},
            customdata=[hover_text[i] for i in zero_indices],
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )

    # Bye-week marker - a blue dot at the player's own NFL team's real
    # bye week that season (see _bye_weeks_by_season), distinct from a
    # genuinely-mysterious red "unrostered" 0: this one's explained. Its
    # own hover is deliberately just "{season}-{week}, {manager if any},
    # Bye Week" - no point value, since the bye itself is the point.
    bye_indices = [index for index, flag in enumerate(is_bye_week) if flag]
    if bye_indices:
        figure.add_scatter(
            x=[x_positions[i] for i in bye_indices],
            y=[points[i] for i in bye_indices],
            mode="markers",
            marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": BYE_WEEK_COLOR, "line": {"width": 1, "color": "#333333"}},
            customdata=[bye_hover_text[i] for i in bye_indices],
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )

    if view_mode == "big_play_percentage":
        chart_title, yaxis_title = "Big Play Fantasy Points % per Game", "Big Play Fantasy Points %"
        yaxis = {"nticks": CHART_YAXIS_MAX_TICKS, "range": [-5, 100]}
    else:
        chart_title, yaxis_title = "Fantasy Points per Game", "Fantasy Points"
        yaxis = {"nticks": CHART_YAXIS_MAX_TICKS}

    figure.update_layout(
        title=chart_title,
        xaxis={"title": "Season", "tickangle": 0, "tickmode": "array", "tickvals": tick_positions, "ticktext": tick_text},
        yaxis_title=yaxis_title,
        yaxis=yaxis,
        legend=CHART_LEGEND_TOP_RIGHT,
        margin={"t": 40, "b": 0, "l": 0, "r": 0},
    )

    for index, entry in enumerate(full_game_list):
        if index > 0 and entry["season"] != full_game_list[index - 1]["season"]:
            figure.add_vline(x=index - 0.5, line_dash="dash", line_color="#888888")

    st.plotly_chart(figure, width="stretch")


def _peer_season_totals(position: str, season: int, players_data: dict, ownership_data: dict) -> list[dict]:
    """{player_id, name, total, games, per_game} for every OTHER player at
    this position with at least one roster entry that season - "at least
    one entry" (not "at least one non-zero entry") is what "qualified"
    means here, same as ownership_data's own definition of being on a
    roster at all that week."""
    rows = []
    for player_id, info in players_data.items():
        if info["position"] != position:
            continue
        season_entries = [entry for entry in ownership_data.get(player_id, []) if entry["season"] == season]
        if not season_entries:
            continue
        total = sum(entry["points"] for entry in season_entries)
        games = len(season_entries)
        rows.append({"player_id": player_id, "name": info["name"], "total": total, "games": games, "per_game": total / games})
    return rows

def _calculate_percentile(peer_rows, selected_row, metric):
    all_values = [row[metric] for row in peer_rows]
    percentile = sum(1 for value in all_values if value <= selected_row[metric]) / len(all_values) * 100
    return percentile


def _calculate_rank(peer_rows, selected_row, metric):
    """1-indexed rank among peer_rows (ties share the best rank), 1 =
    highest value at this metric."""
    return sum(1 for row in peer_rows if row[metric] > selected_row[metric]) + 1


def _format_rank(rank: int) -> str:
    if rank > PERCENTILE_MAX_OTHER_DOTS_PER_SEASON:
        return f"{PERCENTILE_MAX_OTHER_DOTS_PER_SEASON}+"
    return str(rank)

def _render_percentiles_tab(
    selected_player_id: str,
    seasons: list[int],
    players_data: dict,
    ownership_data: dict,
    player_names_by_id: dict[str, str],
    timeline: list[dict],
    nfl_season_lengths: dict[str, int],
) -> None:
    """Scatter: one dot per qualified same-position player per season
    (their total or per-game points that season, selected via the
    metric toggle below), gray for every other player and red for the
    selected player - x-axis is Season, same "grouped at season level"
    shape as the other per-game charts on this page, just aggregated to
    one point per player per season instead of one point per game."""
    selected_position = players_data[selected_player_id]["position"]

    metric = st.selectbox(
        "Select Metric",
        list(PERCENTILE_METRIC_LABELS),
        format_func=lambda value: PERCENTILE_METRIC_LABELS[value],
        key="player_percentile_metric",
    )

    other_x, other_y, other_hover = [], [], []
    selected_x, selected_y, selected_hover = [], [], []
    table_rows = []
    for season in seasons:
        peer_rows = _peer_season_totals(selected_position, season, players_data, ownership_data)
        if not peer_rows:
            continue

        selected_row = next((row for row in peer_rows if row["player_id"] == selected_player_id), None)
        other_rows = [row for row in peer_rows if row["player_id"] != selected_player_id]

        # Cap the OTHER players' dots to the top 100 (by the selected
        # metric) per season if there are more than that - the selected
        # player's own dot is never capped/excluded, since showing it is
        # the entire point of this chart.
        other_rows.sort(key=lambda row: row[metric], reverse=True)
        other_rows = other_rows[:PERCENTILE_MAX_OTHER_DOTS_PER_SEASON]

        # Rank/percentile for every dot - even the capped/displayed
        # "Other Players" ones - is computed against the FULL qualified
        # peer_rows for that season, not just the capped top-100 subset.
        for row in other_rows:
            other_x.append(season)
            other_y.append(row[metric])
            other_rank = _calculate_rank(peer_rows, row, metric)
            other_percentile = _calculate_percentile(peer_rows, row, metric)
            other_hover.append(
                f"<b>{row['name']}</b><br>{season}<br>"
                f"{PERCENTILE_METRIC_LABELS[metric]}: {row[metric]:.2f}<br>"
                f"Rank: {_format_rank(other_rank)}/{len(peer_rows)}<br>"
                f"Percentile: {other_percentile:.0f}"
            )

        if selected_row:
            # Percentile rank against EVERY qualified peer that season
            # (not just the capped/displayed top 100) - the fraction of
            # peers this player's value is >= to.
            percentile = _calculate_percentile(peer_rows, selected_row, metric)
            rank = _calculate_rank(peer_rows, selected_row, metric)
            selected_x.append(season)
            selected_y.append(selected_row[metric])
            selected_hover.append(
                f"<b>{player_names_by_id[selected_player_id]}</b><br>"
                f"{season}<br>"
                f"{PERCENTILE_METRIC_LABELS[metric]}: {selected_row[metric]:.2f}<br>"
                f"Rank: {_format_rank(rank)}/{len(peer_rows)}<br>"
                f"Percentile: {percentile:.0f}"
            )
            table_rows.append(
                {
                    "Season": season,
                    "Total Fantasy Points": selected_row["total"],
                    "Total Fantasy Points Rank": f"{_format_rank(_calculate_rank(peer_rows, selected_row, 'total'))}/{len(peer_rows)}",
                    "Total Fantasy Points Percentile": f"{_calculate_percentile(peer_rows, selected_row, 'total'):.0f}",
                    "Per Game Fantasy Points": selected_row["per_game"],
                    "Per Game Fantasy Points Rank": f"{_format_rank(_calculate_rank(peer_rows, selected_row, 'per_game'))}/{len(peer_rows)}",
                    "Per Game Fantasy Points Percentile": f"{_calculate_percentile(peer_rows, selected_row, 'per_game'):.0f}",
                    "Fantasy Games Started": sum(1 for entry in timeline if entry["season"] == season and entry["status"] == "starter"),
                    "NFL Games Played": nfl_season_lengths.get(str(season), 0),
                }
            )

    if not other_x and not selected_x:
        st.info("No qualified same-position players found for this player's season(s).")
        return

    figure = go.Figure()
    figure.add_scatter(
        x=other_x, y=other_y, mode="markers", name="Other Players",
        marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": PERCENTILE_OTHER_COLOR, "opacity": 0.5},
        customdata=other_hover, hovertemplate="%{customdata}<extra></extra>",
    )
    figure.add_scatter(
        x=selected_x, y=selected_y, mode="markers", name=player_names_by_id[selected_player_id],
        marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": PERCENTILE_SELECTED_COLOR, "line": {"width": 1, "color": "#333333"}},
        customdata=selected_hover, hovertemplate="%{customdata}<extra></extra>",
    )
    figure.update_layout(
        title=f"{selected_position} {PERCENTILE_METRIC_LABELS[metric]} by Season",
        xaxis={"title": "Season", "tickmode": "array", "tickvals": seasons, "ticktext": [str(season) for season in seasons]},
        yaxis_title=PERCENTILE_METRIC_LABELS[metric],
        yaxis={"nticks": CHART_YAXIS_MAX_TICKS},
        legend=CHART_LEGEND_TOP_RIGHT,
        margin={"t": 40, "b": 0, "l": 0, "r": 0},
    )
    st.plotly_chart(figure, width="stretch")

    table_rows.sort(key=lambda row: row["Season"])
    st.dataframe(
        pd.DataFrame(table_rows),
        hide_index=True,
        width="stretch",
        height=38 + 35 * len(table_rows),
        column_config={
            "Total Fantasy Points": st.column_config.NumberColumn(format="%.2f"),
            "Per Game Fantasy Points": st.column_config.NumberColumn(format="%.2f"),
            "Percentile": st.column_config.NumberColumn(format="%.0f"),
            "NFL Games Played": st.column_config.NumberColumn(help=NFL_GAMES_PLAYED_HELP),
        },
    )


def _render_nfl_stat_metrics(timeline: list[dict], selected_stat_id: str, stat_label: str) -> None:
    """Same "per Fantasy Start"/"per Fantasy Bench" pair as
    _render_points_metrics above, for whichever raw NFL stat is
    currently selected - unlike that Points version, values here are
    NOT filtered to non-zero (a 0 rush yards or 0 receptions game is
    real, common box-score data for a raw counting stat, not a stand-in
    for a bye/injury the way a 0.00 fantasy-points game is)."""
    starter_values = [float(entry.get("stats", {}).get(selected_stat_id, 0) or 0) for entry in timeline if entry["status"] == "starter"]
    bench_values = [float(entry.get("stats", {}).get(selected_stat_id, 0) or 0) for entry in timeline if entry["status"] == "bench"]

    stat_per_start = sum(starter_values) / len(starter_values) if starter_values else 0.0
    stat_per_bench = sum(bench_values) / len(bench_values) if bench_values else 0.0

    start_column, bench_column, _, _ = st.columns([1, 1, 1, 1])
    start_column.metric(f"{stat_label} per Fantasy Start", f"{stat_per_start:.2f} ({len(starter_values)})", help=NFL_POINTS_GAME_HELP)
    bench_column.metric(f"{stat_label} per Fantasy Bench", f"{stat_per_bench:.2f} ({len(bench_values)})", help=NFL_POINTS_GAME_HELP)


def _render_nfl_stat_chart(
    timeline: list[dict], stat_id_labels: dict[str, str], nfl_season_lengths: dict[str, int], player_id: str, name_resolver: dict[str, str]
) -> None:
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

    # Only stats this specific player actually has data for, in
    # stat_id_labels.json's own order (roughly passing -> rushing ->
    # receiving -> kicking -> defense) - a QB shouldn't see "Rec Yds" as
    # an option at all.
    available_stat_ids = [stat_id for stat_id in stat_id_labels if any(stat_id in entry.get("stats", {}) for entry in timeline)]
    if not available_stat_ids:
        st.info("No detailed stat breakdown available for this player.")
        return

    selected_stat_id = st.selectbox(
        "Select NFL Stat to View",
        available_stat_ids,
        format_func=lambda stat_id: stat_id_labels.get(stat_id, stat_id),
        index=0,
        key="player_stat_chart_selection",
        # label_visibility="collapsed",
    )

    stat_label = stat_id_labels.get(selected_stat_id, selected_stat_id)
    _render_nfl_stat_metrics(timeline, selected_stat_id, stat_label)
    full_game_list = _build_full_game_list(timeline, nfl_season_lengths)
    bye_weeks_by_season = _bye_weeks_by_season(player_id)

    values, colors, hover_text, is_bye_week, bye_hover_text = [], [], [], [], []
    has_unrostered = False
    for entry in full_game_list:
        is_bye_week.append(bye_weeks_by_season.get(entry["season"]) == entry["week"])
        if entry.get("unrostered"):
            values.append(0.0)
            colors.append(UNROSTERED_GAME_COLOR)
            hover_text.append(
                f"<b>{entry['season']} · Week {entry['week']}</b><br>"
                "Not on a fantasy roster"
            )
            bye_hover_text.append(
                f"<b>{entry['season']} · Week {entry['week']}</b><br>"
                "Bye Week"
            )
            has_unrostered = True
            continue
        value = float(entry.get("stats", {}).get(selected_stat_id, 0) or 0)
        values.append(value)
        colors.append(STAT_CHART_COLOR)
        hover_text.append(f"<b>{entry['season']} · Week {entry['week']}</b><br>{stat_label}: {value:g}")
        bye_hover_text.append(f"<b>{entry['season']} · Week {entry['week']}</b><br>Bye Week")

    x_positions = list(range(len(full_game_list)))
    positions_by_season: dict[int, list[int]] = {}
    for index, entry in enumerate(full_game_list):
        positions_by_season.setdefault(entry["season"], []).append(index)
    tick_positions = [sum(positions) / len(positions) for positions in positions_by_season.values()]
    tick_text = [str(season) for season in positions_by_season]

    if stat_label in YARDAGE_STAT_LABELS:
        y_axis_config = {"nticks": CHART_YAXIS_MAX_TICKS}
    else:
        max_value = max(values, default=0)
        y_dtick = max(1, -(-int(max_value) // CHART_YAXIS_MAX_TICKS))
        y_axis_config = {"dtick": y_dtick, "tickformat": "d"}

    figure = go.Figure(
        go.Bar(x=x_positions, y=values, marker_color=colors, customdata=hover_text, hovertemplate="%{customdata}<extra></extra>", showlegend=False)
    )
    figure.add_scatter(x=[None], y=[None], mode="markers", marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": STAT_CHART_COLOR}, name=stat_label, showlegend=True)
    if any(is_bye_week):
        figure.add_scatter(x=[None], y=[None], mode="markers", marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": BYE_WEEK_COLOR}, name="Bye Week", showlegend=True)
    if has_unrostered:
        figure.add_scatter(x=[None], y=[None], mode="markers", marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": UNROSTERED_GAME_COLOR}, name="Not on a Fantasy Roster", showlegend=True)
    figure.update_layout(
        title=f"{stat_label} per Game",
        xaxis={"title": "Season", "tickangle": 0, "tickmode": "array", "tickvals": tick_positions, "ticktext": tick_text},
        yaxis_title=stat_label,
        yaxis=y_axis_config,
        legend=CHART_LEGEND_TOP_RIGHT,
        margin={"t": 40, "b": 0, "l": 0, "r": 0},
    )
    for index, entry in enumerate(full_game_list):
        if index > 0 and entry["season"] != full_game_list[index - 1]["season"]:
            figure.add_vline(x=index - 0.5, line_dash="dash", line_color="#888888")

    # A 0-value bar has no height to hover over, so it's otherwise
    # unreachable - a marker dot at y=0 (same color/hover text) keeps
    # every game hoverable regardless of value, same treatment as the
    # Fantasy Points per Game chart's zero-point/unrostered games. Bye
    # weeks are excluded here entirely - they get their own distinct blue
    # marker below instead of this one sitting underneath it.
    zero_indices = [index for index, value in enumerate(values) if value == 0 and not is_bye_week[index]]
    if zero_indices:
        figure.add_scatter(
            x=[x_positions[i] for i in zero_indices],
            y=[0] * len(zero_indices),
            mode="markers",
            marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": [colors[i] for i in zero_indices], "line": {"width": 1, "color": "#333333"}},
            customdata=[hover_text[i] for i in zero_indices],
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )

    # Bye-week marker - a blue dot at the player's own NFL team's real
    # bye week that season (see _bye_weeks_by_season), distinct from a
    # genuinely-mysterious red "unrostered" 0: this one's explained. Its
    # own hover is deliberately just "{season}-{week}, {manager if any},
    # Bye Week" - no stat value, since the bye itself is the point.
    bye_indices = [index for index, flag in enumerate(is_bye_week) if flag]
    if bye_indices:
        figure.add_scatter(
            x=[x_positions[i] for i in bye_indices],
            y=[values[i] for i in bye_indices],
            mode="markers",
            marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": BYE_WEEK_COLOR, "line": {"width": 1, "color": "#333333"}},
            customdata=[bye_hover_text[i] for i in bye_indices],
            hovertemplate="%{customdata}<extra></extra>",
            showlegend=False,
        )

    st.plotly_chart(figure, width="stretch")


def _render_summary_metrics(timeline: list[dict], nfl_season_lengths: dict[str, int], stints: list[dict]) -> None:
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
    #
    # Known limitation, not handled: this assumes exactly ONE bye week
    # per season, uniformly. A player traded mid-season between two NFL
    # teams could have two different real byes that year (or, in rare
    # scheduling overlaps, effectively skip having one at all) - archive
    # data doesn't currently track which NFL team a player belonged to
    # week-by-week (only which FANTASY team, if any, rostered them), so
    # there's no way to detect a mid-season NFL trade here. Left as a
    # deliberate simplification, not a bug - see instructions/
    # cool-features.md's "players" section for the related future
    # improvement (complementing this with real NFL play-by-play/roster
    # data so bye vs. genuinely-unrostered can be told apart exactly,
    # not just approximated one-bye-per-season).
    nfl_games = len(_build_full_game_list(timeline, nfl_season_lengths))

    starts = sum(1 for entry in timeline if entry["status"] == "starter")
    bench = sum(1 for entry in timeline if entry["status"] == "bench")
    start_pct = starts / len(timeline) if timeline else 0.0
    managers = len({entry["manager_id"] for entry in timeline if entry["manager_id"]})

    nfl_games_column, games_column, starts_column, bench_column, start_pct_column, managers_column, transfers_column = st.columns(7)
    nfl_games_column.metric("NFL Games", nfl_games, help=NFL_GAMES_HELP)
    games_column.metric("Fantasy Games", len(timeline), help="Number of appearances on a fantasy roster.")
    starts_column.metric("Fantasy Starts", starts, help="Number of fantasy appearances as a starter.")
    bench_column.metric("Fantasy Bench", bench, help="Number fantasy appearances on bench.")
    start_pct_column.metric("Fantasy Start %", f"{start_pct:.1%}", help="Fantasy start percentage.")
    managers_column.metric("Fantasy Managers", managers, help="Number of fantasy managers who had player on roster.")
    transfers_column.metric("# of Transfers", len(stints), help="Number of ownership stints shown in the Transfers flow chart. The start of the season counts as a new transfer.")


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

    # Same versioned-widget-key pattern as the Matchups tab's Clear
    # Filters: each filter's ACTUAL key includes a generation counter, so
    # Clear Filters can bump the counter and force brand-new widget
    # instances instead of relying on session_state deletion alone, which
    # left stale-looking dropdowns in some browsers even after the
    # underlying value was cleared (see pages_matchups.py's
    # _render_filters).
    generation = st.session_state.setdefault("player_filters_generation", 0)

    def versioned_key(base_key: str) -> str:
        return f"{base_key}_gen{generation}"

    for base_key in PLAYER_FILTER_WIDGET_BASE_KEYS:
        widget_key = versioned_key(base_key)
        if widget_key not in st.session_state and base_key in st.session_state:
            st.session_state[widget_key] = st.session_state[base_key]

    st.warning(body="Note - stats are incomplete when a player was not on a fantasy roster (nfl/fantasy data not yet available). also missing are stats on injuries/suspensions", icon="ℹ️")

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


    fantasy_stats_tab, nfl_stats_tab, managers_tab, percentiles_tab = st.tabs(["Fantasy Stats", "NFL Stats", "Manager Stats", "Percentiles"])
    with fantasy_stats_tab:
        selected_position = players_data[selected_player_id]["position"]
        points_view_mode = st.selectbox(
            "Select Fantasy Stat to View",
            list(POINTS_CHART_VIEW_LABELS),
            format_func=lambda value: POINTS_CHART_VIEW_LABELS[value],
            key="player_points_chart_view_mode",
        )
        if points_view_mode == "big_play_percentage":
            st.caption(body="Big Play % are the percent of points generated from TD plays (not the associated yards/reception). This is to highlight TD dependent players.")
        _render_points_metrics(timeline, selected_player_id, selected_position, points_view_mode)
        _render_fantasy_points_per_game_chart(
            timeline, name_resolver, manager_color_map, nfl_season_lengths, selected_player_id, selected_position, points_view_mode
        )
    with nfl_stats_tab:
        _render_nfl_stat_chart(timeline, stat_id_labels, nfl_season_lengths, selected_player_id, name_resolver)
    with managers_tab:
        _render_summary_metrics(timeline, nfl_season_lengths, stints)
        _render_manager_summary_chart(stints, name_resolver, manager_color_map)
        _render_flow_chart(stints, name_resolver, manager_color_map, flow_key=f"player_ownership_flow_{selected_player_id}", player_id=selected_player_id)
    with percentiles_tab:
        seasons = sorted({entry["season"] for entry in timeline})
        _render_percentiles_tab(selected_player_id, seasons, players_data, ownership_data, player_names_by_id, timeline, nfl_season_lengths)