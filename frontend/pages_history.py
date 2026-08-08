"""History tab - all-time champions, records, and career manager stats
across every season in the archive. See execution-plan.md Phase G.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    discover_seasons,
    load_all_time_champions,
    load_all_time_manager_stats,
    load_all_time_records,
    load_post_season_stats,
    resolve_manager_name,
    team_id_to_manager_map,
)

# Standard real-world medal colors - not a generated categorical palette,
# so not run through the dataviz skill's CVD validator (this exact
# 3-color convention is a fixed, universally recognized domain standard,
# and the three already differ sharply in lightness: bright yellow-gold,
# light neutral silver, dark orange-brown bronze).
CHAMPION_COLOR = "#d0b04e"
RUNNER_UP_COLOR = "#a7a7a7"
THIRD_PLACE_COLOR = "#9f724b"

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    red, green, blue = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _full_table_height(row_count: int) -> int:
    """st.dataframe defaults to a fixed max height with internal
    scrolling once a table has more rows than fit - passing an explicit
    height sized to the actual row count instead shows every row with no
    fold/scroll. ~35px/row + ~38px header, based on Streamlit's default
    row height - no extra padding beyond that, or the table shows a
    trailing sliver of empty space below the last row."""
    return 38 + 35 * row_count


RECORD_LABELS = {
    "highest_weekly_score": "Highest Weekly Score",
    "lowest_weekly_score": "Lowest Weekly Score",
    "highest_season_points_for": "Highest Season Points",
    "lowest_season_points_for": "Lowest Season Points",
    "longest_win_streak": "Longest Win Streak",
    "longest_losing_streak": "Longest Losing Streak",
    "best_coaching_season": "Best Coaching Season",
    "worst_coaching_season": "Worst Coaching Season",
    "most_players_started_season": "Most Players Started (Season)",
    "fewest_players_started_season": "Fewest Players Started (Season)",
}

# Each row pairs a "high" stat (left) with its "low" counterpart (right).
# The streak row is handled separately (see _render_streak_row) since it
# has a variant selector instead of being a fixed data key.
RECORD_ROW_PAIRS = [
    ("highest_weekly_score", "lowest_weekly_score"),
    ("highest_season_points_for", "lowest_season_points_for"),
    ("best_coaching_season", "worst_coaching_season"),
    ("most_players_started_season", "fewest_players_started_season"),
]

# variant key suffix ("" for the original per-season data keys) -> label.
STREAK_VARIANTS = {
    "": "Within Season",
    "regular_cross_season": "Spans Regular Seasons",
    "postseason_cross_season": "Spans Postseasons",
    "combined_cross_season": "Spans Regular and Postseason",
}


ORDINAL_WORDS = [
    "zeroth", "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
    "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
]


def _ordinal_word(n: int) -> str:
    if n < len(ORDINAL_WORDS):
        return ORDINAL_WORDS[n]
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _render_season_summary_paragraph(champions_data: dict, name_resolver: dict[str, str]) -> None:
    seasons_sorted = sorted(champions_data["champions"], key=lambda season_entry: season_entry["season"])
    first_year = seasons_sorted[0]["season"]
    season_count = len(seasons_sorted)

    # top_3 rows aren't guaranteed to be in rank order, so filter by
    # rank == 1 rather than indexing [0]. Walking seasons in chronological
    # order lets the same pass double as each manager's running
    # championship tally, used below for the reigning champion's ordinal.
    championship_count_by_manager: dict[str, int] = {}
    reigning_champion_entry = None
    for season_entry in seasons_sorted:
        champion_row = next((row for row in season_entry["top_3"] if row["rank"] == 1), None)
        if not champion_row:
            continue
        manager_id = champion_row.get("manager_id", "")
        championship_count_by_manager[manager_id] = championship_count_by_manager.get(manager_id, 0) + 1
        reigning_champion_entry = (manager_id, champion_row, championship_count_by_manager[manager_id])

    champion_count = len(championship_count_by_manager)

    

    if not championship_count_by_manager:
        return

    most_winning_manager_id = max(championship_count_by_manager, key=lambda manager_id: championship_count_by_manager[manager_id])
    most_wins = championship_count_by_manager[most_winning_manager_id]
    most_winning_manager_name = resolve_manager_name(most_winning_manager_id, name_resolver, "")

    reigning_manager_id, reigning_champion_row, reigning_ordinal = reigning_champion_entry
    reigning_manager_name = resolve_manager_name(
        reigning_manager_id, name_resolver, reigning_champion_row.get("display_name", "")
    )

    st.markdown(
        f"The Music League began in {first_year} and has run for {season_count} successive seasons, featuring {champion_count} champions. "
        f"The most winning manager is {most_winning_manager_name} with {most_wins} championships. "
        f"The reigning champion is {reigning_manager_name} who won their {_ordinal_word(reigning_ordinal)} championship."    
    )


def _render_champions_table(champions_data: dict, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    st.subheader("Wall of Champions")
    rows = []
    champion_manager_ids = []
    for season_entry in sorted(champions_data["champions"], key=lambda c: c["season"], reverse=True):
        top_3 = {row["rank"]: row for row in season_entry["top_3"]}

        def name_for(entry: dict) -> str:
            return resolve_manager_name(entry.get("manager_id", ""), name_resolver, entry.get("display_name", ""))

        champion_manager_ids.append(top_3.get(1, {}).get("manager_id", ""))
        rows.append(
            {
                "Season": season_entry["season"],
                "Champion 🏆": name_for(top_3.get(1, {})),
                "Runner-Up 🥈": name_for(top_3.get(2, {})),
                "3rd Place 🥉": name_for(top_3.get(3, {})),
                "Last Place 🥞": name_for(season_entry["last_place"]),
            }
        )
    dataframe = pd.DataFrame(rows)

    # Champion column background = the champion's own color (same map used
    # for the pie chart / flow-chart nodes elsewhere), so a manager's
    # championship seasons are visually traceable to their color at a
    # glance. 75% opacity per user request, so the text stays legible.
    def _highlight_champion_column(column: pd.Series) -> list[str]:
        if column.name != "Champion 🏆":
            return [""] * len(column)
        styles = []
        for manager_id in champion_manager_ids:
            hex_color = manager_color_map.get(manager_id, "")
            styles.append(f"background-color: {_hex_to_rgba(hex_color, 0.75)}" if hex_color else "")
        return styles

    styled_dataframe = dataframe.style.apply(_highlight_champion_column, axis=0)
    st.dataframe(styled_dataframe, hide_index=True, width="stretch", height=_full_table_height(len(rows)))


def _build_manager_placements(champions_data: dict) -> dict[str, dict]:
    """{manager_id: {"champion_years": [...], "runner_up_years": [...],
    "third_place_years": [...]}} - only managers who were ever top-3 in
    some season get an entry (built strictly from top_3 rows), so a
    manager who never placed doesn't show up as an all-zero row later."""
    placements: dict[str, dict] = {}
    for season_entry in champions_data["champions"]:
        season = season_entry["season"]
        for row in season_entry["top_3"]:
            manager_id = row.get("manager_id", "")
            if not manager_id:
                continue
            entry = placements.setdefault(manager_id, {"champion_years": [], "runner_up_years": [], "third_place_years": []})
            if row["rank"] == 1:
                entry["champion_years"].append(season)
            elif row["rank"] == 2:
                entry["runner_up_years"].append(season)
            elif row["rank"] == 3:
                entry["third_place_years"].append(season)
    return placements


def _years_label(years: list[int], empty_placeholder: str = "😢") -> str:
    return ", ".join(str(year) for year in sorted(years)) if years else empty_placeholder


def _render_champion_charts(champions_data: dict, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    placements = _build_manager_placements(champions_data)
    pie_column, bar_column = st.columns(2)

    with pie_column:
        champion_managers = [
            (manager_id, len(data["champion_years"]), data["champion_years"])
            for manager_id, data in placements.items()
            if data["champion_years"]
        ]
        # Descending by count; ties broken by most-recent championship year first.
        champion_managers.sort(key=lambda item: (-item[1], -max(item[2])))

        labels = [resolve_manager_name(manager_id, name_resolver) for manager_id, _, _ in champion_managers]
        values = [count for _, count, _ in champion_managers]
        years_text = [_years_label(years) for _, _, years in champion_managers]
        colors = [manager_color_map.get(manager_id, "#CCCCCC") for manager_id, _, _ in champion_managers]

        pie_figure = go.Figure(
            go.Pie(
                labels=labels,
                values=values,
                sort=False,  # preserve our own count-then-recency order, not plotly's default value sort
                rotation=0,  # first slice starts at 12 o'clock
                direction="clockwise",
                marker=dict(colors=colors),
                textinfo="label+value",
                customdata=years_text,
                hovertemplate="%{label}<br>Championships: %{value}<br>Years: %{customdata}<extra></extra>",
                showlegend=False,
            )
        )
        pie_figure.update_layout(title="Championships by Manager", margin=dict(t=40, b=0, l=0, r=0))
        st.plotly_chart(pie_figure, width="stretch")

    with bar_column:
        bar_rows = []
        for manager_id, data in placements.items():
            bar_rows.append(
                {
                    "manager_id": manager_id,
                    "name": resolve_manager_name(manager_id, name_resolver),
                    "champion_count": len(data["champion_years"]),
                    "runner_up_count": len(data["runner_up_years"]),
                    "third_place_count": len(data["third_place_years"]),
                    "champion_years": data["champion_years"],
                    "runner_up_years": data["runner_up_years"],
                    "third_place_years": data["third_place_years"],
                }
            )
        bar_rows.sort(key=lambda row: (-row["champion_count"], -row["runner_up_count"], -row["third_place_count"]))

        names = [row["name"] for row in bar_rows]
        bar_figure = go.Figure()
        # Trace order is reversed from the visual Champion/Runner-Up/3rd
        # Place reading order intentionally: with barmode="stack" +
        # hovermode="x unified", Plotly's unified hover lists traces
        # top-to-bottom matching the visual stack top-to-bottom - the
        # LAST-added trace becomes the top segment (and hover's first
        # line). Adding 3rd Place first (bottom segment) and Champion
        # last (top segment) makes both the stack and the hover read
        # Champion, Runner-Up, 3rd Place from top to bottom.
        bar_figure.add_bar(
            name="3rd Place",
            x=names,
            y=[row["third_place_count"] for row in bar_rows],
            marker_color=THIRD_PLACE_COLOR,
            customdata=[f"3rd Place: {_years_label(row['third_place_years'], '☹️')}" for row in bar_rows],
            hovertemplate="%{customdata}<extra></extra>",
        )
        bar_figure.add_bar(
            name="Runner-Up",
            x=names,
            y=[row["runner_up_count"] for row in bar_rows],
            marker_color=RUNNER_UP_COLOR,
            customdata=[f"Runner-Up: {_years_label(row['runner_up_years'], '😢')}" for row in bar_rows],
            hovertemplate="%{customdata}<extra></extra>",
        )
        bar_figure.add_bar(
            name="Champion",
            x=names,
            y=[row["champion_count"] for row in bar_rows],
            marker_color=CHAMPION_COLOR,
            customdata=[f"Champion: {_years_label(row['champion_years'], '😭')}" for row in bar_rows],
            hovertemplate="%{customdata}<extra></extra>",
        )
        bar_figure.update_layout(
            title="Podiums by Manager",
            barmode="stack",
            hovermode="x unified",
            xaxis_title="Manager",
            yaxis_title="Count",
            yaxis=dict(dtick=1, tickformat="d"),  # counts are integers - no fractional ticks
            legend=dict(traceorder="reversed"),  # keep legend reading Champion/Runner-Up/3rd Place despite reversed trace order above
            margin=dict(t=40, b=0, l=0, r=0),
        )
        st.plotly_chart(bar_figure, width="stretch")


def _record_context_line(entry: dict, name_resolver: dict[str, str]) -> str:
    display_name = resolve_manager_name(entry.get("manager_id", ""), name_resolver, entry.get("display_name", ""))

    if "start_week" in entry:
        # Streak entries: show the full start->end range, not just the
        # peak week. start_season defaults to the (single) season for
        # per-season streaks, which don't carry their own start_season
        # field since it's always identical to "season" there.
        start_season = entry.get("start_season", entry["season"])
        end_season, end_week, start_week = entry["season"], entry["week"], entry["start_week"]
        if start_season == end_season:
            week_range = f"Wk {start_week}" if start_week == end_week else f"Wk {start_week}-{end_week}"
            return f"{display_name} · {end_season} {week_range}"
        return f"{display_name} · {start_season} Wk{start_week} – {end_season} Wk{end_week}"

    parts = [display_name, f"{entry['season']}"]
    if "week" in entry:
        parts.append(f"Wk {entry['week']}")
    return " · ".join(parts)


def _go_to_game(entry: dict) -> None:
    """Jumps to the Games page with Manager 1 (and Week, if this record
    is week-specific rather than season-long) pre-filled to this record's
    game, via st.switch_page() - the whole reason app.py uses
    st.navigation/st.Page instead of st.tabs, since st.tabs has no way to
    programmatically switch which tab is active. Must be called from the
    main script body, not a button's on_click callback - st.switch_page()
    (like st.rerun()) is a no-op/error when called from within a
    callback, since a callback runs before the script rerun it would
    need to trigger."""
    manager_id = entry.get("manager_id", "")
    # Pre-set every filter WIDGET's own key (not just the applied-filters
    # result used to query matchups) so the Season/Week/Manager 2/Matchup
    # Type controls visually reflect the record's filters too, not just
    # the results below them.
    st.session_state["games_team1_manager_id"] = manager_id
    st.session_state["games_season"] = entry["season"]
    st.session_state["games_week"] = entry.get("week")
    st.session_state["games_team2_manager_id"] = None
    st.session_state["games_matchup_type"] = "all"
    # Bump the same widget-key generation counter Clear Filters uses, so
    # the Games page mounts brand-new filter widgets that pick up these
    # values via their first-mount seeding, rather than showing whatever
    # was left over from a previous visit to that page.
    st.session_state["games_filters_generation"] = st.session_state.get("games_filters_generation", 0) + 1
    st.session_state["games_applied_filters"] = {
        "season": entry["season"],
        "week": entry.get("week"),
        "team1_manager_id": manager_id,
        "team2_manager_id": None,
        "matchup_type": "all",
    }
    st.switch_page(st.session_state["_games_page"])


# score | info | button - wide enough for the button column to fit
# "View Matchup"/"View Season" on one line without wrapping (each record row
# is itself in a half-width column, so this column only gets ~1/10 of
# the page width) - same ratio every row so all three still align
# vertically.
RECORD_ROW_COLUMN_RATIOS = [1, 2.3, 1.7]


def _render_record_row(key: str, ordinal: str, entry: dict, name_resolver: dict[str, str], row_height: str, score_size: str, info_size: str) -> None:
    # Both the score and info columns get their OWN identically-sized
    # flex box (same explicit row_height, align-items:center) rather
    # than only the info column being wrapped - two separate columns
    # each just holding a bare, differently-sized <span> stay top-aligned
    # relative to each other even if one box happens to be taller,
    # because each column's box height is independently determined by
    # its own (unwrapped) content, not shared with its neighbor.
    score_column, info_column, button_column = st.columns(RECORD_ROW_COLUMN_RATIOS)
    with score_column:
        st.markdown(
            f"<div style='display:flex; align-items:center; height:{row_height};'>"
            f"<span style='font-size:{score_size}; font-weight:700;'>{entry['value']:g}</span></div>",
            unsafe_allow_html=True,
        )
    with info_column:
        st.markdown(
            f"<div style='display:flex; align-items:center; height:{row_height};'>"
            f"<span style='font-size:{info_size}; color:gray;'>{_record_context_line(entry, name_resolver)}</span></div>",
            unsafe_allow_html=True,
        )
    button_label = "View Matchup" if "week" in entry else "View Season"
    if entry.get("manager_id") and button_column.button(button_label, key=f"record_link_{key}_{ordinal}", use_container_width=True):
        _go_to_game(entry)


def _render_record_cell(key: str, top_n: list[dict], name_resolver: dict[str, str], label: str | None = None, widget_key: str | None = None) -> None:
    # label/widget_key let a caller reuse this same rendering for a
    # record stored under a different underlying data key than its
    # displayed title - the streak row's variant selector swaps which
    # data key backs "Longest Win/Losing Streak" without changing the
    # title text.
    label = label or RECORD_LABELS[key]
    widget_key = widget_key or key

    # Custom label above a label-less metric, since st.metric's built-in
    # label font is smaller than we want here - still kept clearly
    # smaller than the metric's own value text (~2.25rem by default).
    st.markdown(f"<div style='font-size:1.15em; font-weight:600;'>{label}</div>", unsafe_allow_html=True)

    if not top_n:
        st.metric(label, "-", label_visibility="collapsed")
        return

    # 1st place's score/info render larger than 2nd/3rd's, but every row
    # shares the same [score, info, button] column ratio so the buttons
    # (and each column's content) stay vertically aligned across all
    # three rows regardless of that font-size difference.
    # row_height stays the SAME across all three rows - it has to match
    # the button's real rendered height (roughly constant regardless of
    # the row) for the score/info text to align with it, even though the
    # 2nd/3rd rows deliberately use smaller font sizes than the 1st.
    _render_record_row(widget_key, "1", top_n[0], name_resolver, row_height="2.4rem", score_size="1.75rem", info_size="1rem")
    for ordinal, entry in zip(("2nd", "3rd"), top_n[1:]):
        _render_record_row(widget_key, ordinal, entry, name_resolver, row_height="2.4rem", score_size="1.1rem", info_size="0.85rem")


def _render_streak_row(records_data: dict, name_resolver: dict[str, str]) -> None:
    with st.container(border=True):
        variant_suffix = st.selectbox(
            "Streak type",
            list(STREAK_VARIANTS),
            format_func=lambda suffix: STREAK_VARIANTS[suffix],
            key="streak_variant",
        )
        win_key = f"longest_win_streak_{variant_suffix}" if variant_suffix else "longest_win_streak"
        loss_key = f"longest_losing_streak_{variant_suffix}" if variant_suffix else "longest_losing_streak"

        left_column, right_column = st.columns(2)
        with left_column:
            _render_record_cell(win_key, records_data.get(win_key) or [], name_resolver, label=RECORD_LABELS["longest_win_streak"])
        with right_column:
            _render_record_cell(loss_key, records_data.get(loss_key) or [], name_resolver, label=RECORD_LABELS["longest_losing_streak"])


def _render_records(records_data: dict, name_resolver: dict[str, str]) -> None:
    st.subheader("All-Time Records")

    high_key, low_key = RECORD_ROW_PAIRS[0]
    with st.container(border=True):
        left_column, right_column = st.columns(2)
        with left_column:
            _render_record_cell(high_key, records_data.get(high_key) or [], name_resolver)
        with right_column:
            _render_record_cell(low_key, records_data.get(low_key) or [], name_resolver)

    _render_streak_row(records_data, name_resolver)

    for high_key, low_key in RECORD_ROW_PAIRS[1:]:
        with st.container(border=True):
            left_column, right_column = st.columns(2)
            with left_column:
                _render_record_cell(high_key, records_data.get(high_key) or [], name_resolver)
            with right_column:
                _render_record_cell(low_key, records_data.get(low_key) or [], name_resolver)


MANAGER_STAT_COLUMN_FORMATS = {
    "Win %": "%.3f",
    "Avg Reg. Finish": "%.2f",
    "Avg Post. Finish": "%.2f",
    "Points For": "%.2f",
    "Points Against": "%.2f",
}

# Every selectable stat for the chart below the standings table - all
# numeric columns of that table except "Manager" itself (the x-axis).
MANAGER_STAT_COLUMNS = [
    "Seasons",
    "Championships",
    "Runner-Ups",
    "3rd Place",
    "Podiums",
    "Last Place",
    "Best Finish",
    "Worst Finish",
    "Avg Reg. Finish",
    "Avg Post. Finish",
    "W",
    "L",
    "T",
    "Win %",
    "Points For",
    "Points Against",
    "Players Started",
]

# Full-length labels for chart titles/axes/dropdown - the table itself
# keeps the compact column headers above (space is tighter there).
MANAGER_STAT_FULL_LABELS = {
    "Seasons": "# Seasons Played",
    "Championships": "# Championships",
    "Runner-Ups": "# Runner-Up Finishes",
    "3rd Place": "# 3rd Place Finishes",
    "Podiums": "# Podium Finishes",
    "Last Place": "# Last Place Finishes",
    "Best Finish": "Best Finish",
    "Worst Finish": "Worst Finish",
    "Avg Reg. Finish": "Average Regular Season Finish",
    "Avg Post. Finish": "Average Postseason Finish",
    "W": "Wins",
    "L": "Losses",
    "T": "Ties",
    "Win %": "Win Percentage",
    "Points For": "Points For",
    "Points Against": "Points Against",
    "Players Started": "Players Started",
}


def _best_worst_finish_by_manager() -> dict[str, tuple[int, int]]:
    """{manager_id: (best final rank, worst final rank)} - the FINAL
    (post-season) standings rank each season, i.e.
    post_season_stats.json's final_placements (same source as the Yearly
    page's Final Standings tab), not the regular-season standings rank."""
    finishes: dict[str, list[int]] = {}
    for year in discover_seasons():
        post_season_stats = load_post_season_stats(year)
        if not post_season_stats:
            continue
        team_info = team_id_to_manager_map(year)
        for team_id, rank in post_season_stats["final_placements"].items():
            manager_id = team_info.get(team_id, {}).get("manager_id", "")
            if manager_id:
                finishes.setdefault(manager_id, []).append(rank)
    return {manager_id: (min(ranks), max(ranks)) for manager_id, ranks in finishes.items()}


def _build_manager_standings_dataframe(manager_stats_data: dict, name_resolver: dict[str, str]) -> pd.DataFrame:
    best_worst_finish = _best_worst_finish_by_manager()
    rows = []
    for manager in manager_stats_data["managers"]:
        combined = manager["combined"]
        best_finish, worst_finish = best_worst_finish.get(manager["manager_id"], (None, None))
        rows.append(
            {
                "manager_id": manager["manager_id"],
                "Manager": resolve_manager_name(manager["manager_id"], name_resolver),
                "Seasons": len(manager["seasons_played"]),
                "Championships": manager["championships"],
                "Runner-Ups": manager["runner_ups"],
                "3rd Place": manager["third_place_finishes"],
                "Podiums": manager["championships"] + manager["runner_ups"] + manager["third_place_finishes"],
                "Last Place": manager["last_place_finishes"],
                "Best Finish": best_finish,
                "Worst Finish": worst_finish,
                "Avg Reg. Finish": manager["average_regular_season_finish"],
                "Avg Post. Finish": manager["average_post_season_finish"],
                "W": combined["wins"],
                "L": combined["losses"],
                "T": combined["ties"],
                "Win %": combined["win_pct"],
                "Points For": combined["points_for"],
                "Points Against": combined["points_against"],
                "Players Started": manager["career_players_started_count"],
            }
        )
    return pd.DataFrame(rows).sort_values(["Seasons", "Manager"], ascending=[False, True])


def _render_manager_standings_table(dataframe: pd.DataFrame) -> None:
    st.subheader("Career Manager Standings")
    st.dataframe(
        dataframe.drop(columns=["manager_id"]),
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(dataframe)),
        column_config={
            "Manager": st.column_config.Column(pinned=True),
            **{column: st.column_config.NumberColumn(format=fmt) for column, fmt in MANAGER_STAT_COLUMN_FORMATS.items()},
        },
    )


# Only these totals make sense divided by a manager's season/game count -
# the rest (Championships, Win %, Avg Finish, etc) are either already
# per-season/per-game rates or counts that don't mean anything normalized
# this way. Per Game deliberately excludes Players Started (unlike Per
# Season) - a career "players started per game" rate isn't a meaningful
# stat the way a per-season rate is.
PER_SEASON_ELIGIBLE_STATS = {"W", "L", "T", "Points For", "Points Against", "Players Started"}
PER_GAME_ELIGIBLE_STATS = {"W", "L", "T", "Points For", "Points Against"}

NORMALIZATION_LABELS = {"all_time": "All Time", "per_season": "Per Season", "per_game": "Per Game"}
NORMALIZATION_HELP = "Per Season/Per Game are only offered for stats where that normalization is meaningful: W, L, T, Points For, Points Against (Per Season also covers Players Started)."


def _render_manager_stat_chart(dataframe: pd.DataFrame, manager_color_map: dict[str, str]) -> None:
    st.subheader("Stats to Chart")
    selectbox_column, normalization_column, tooltip_column = st.columns([3, 1, 0.2])
    with selectbox_column:
        selected_stat = st.selectbox(
            "Stat to chart",
            MANAGER_STAT_COLUMNS,
            format_func=lambda column: MANAGER_STAT_FULL_LABELS[column],
            index=0,
            key="manager_stat_chart_selection",
            label_visibility="collapsed",
        )
        # The widget always has index=0 as a fallback, but a stale
        # session_state value from a prior rerun (e.g. before a code
        # change altered MANAGER_STAT_COLUMNS) can otherwise land here as
        # None and crash the whole page below instead of the chart just
        # re-rendering.
        if selected_stat is None:
            selected_stat = MANAGER_STAT_COLUMNS[0]

    # Available normalization options depend on the selected stat - built
    # fresh each run rather than disabling individual options, since
    # st.selectbox has no per-option disabled state.
    normalization_options = ["all_time"]
    if selected_stat in PER_SEASON_ELIGIBLE_STATS:
        normalization_options.append("per_season")
    if selected_stat in PER_GAME_ELIGIBLE_STATS:
        normalization_options.append("per_game")

    # A stat switch can make the previously-selected normalization
    # invalid for the new stat (e.g. switching away from Points For while
    # Per Game was selected) - reset to "All Time" before the widget is
    # instantiated rather than letting Streamlit raise on an out-of-range
    # session_state value.
    if st.session_state.get("manager_stat_normalization") not in normalization_options:
        st.session_state["manager_stat_normalization"] = "all_time"

    with normalization_column:
        normalization = st.selectbox(
            "Normalization",
            normalization_options,
            format_func=lambda value: NORMALIZATION_LABELS[value],
            key="manager_stat_normalization",
            label_visibility="collapsed",
        )
    with tooltip_column:
        # st.selectbox's built-in help icon renders next to its LABEL,
        # which is collapsed here for layout reasons - so it silently
        # disappears rather than just moving. st.popover gives a proper
        # native Streamlit icon button (not a raw unicode glyph) that
        # opens the same explanation on click, placed in its own narrow
        # column to the dropdown's right.
        with st.popover("ℹ️", use_container_width=False):
            st.markdown(NORMALIZATION_HELP)

    selected_stat_label = MANAGER_STAT_FULL_LABELS[selected_stat]

    columns = list(dict.fromkeys(["manager_id", "Manager", "Seasons", "W", "L", "T", selected_stat]))
    chart_data = dataframe[columns].dropna(subset=[selected_stat]).copy()
    if normalization == "per_season":
        chart_data[selected_stat] = chart_data[selected_stat] / chart_data["Seasons"]
        selected_stat_label = f"{selected_stat_label} per Season"
    elif normalization == "per_game":
        games_played = chart_data["W"] + chart_data["L"] + chart_data["T"]
        chart_data[selected_stat] = chart_data[selected_stat] / games_played.replace(0, pd.NA)
        selected_stat_label = f"{selected_stat_label} per Game"
    # Lower is better for finish stats (1st place beats 10th), so those
    # two sort ascending; every other stat sorts descending (higher is
    # better/more).
    ascending = selected_stat in ("Avg Reg. Finish", "Avg Post. Finish", "Best Finish", "Worst Finish")
    chart_data = chart_data.sort_values(selected_stat, ascending=ascending)
    bar_colors = [manager_color_map.get(manager_id, "#4C78A8") for manager_id in chart_data["manager_id"]]

    stat_figure = go.Figure(
        go.Bar(
            x=chart_data["Manager"],
            y=chart_data[selected_stat],
            marker_color=bar_colors,
            hovertemplate="%{x}<br>" + selected_stat_label + ": %{y}<extra></extra>",
        )
    )
    stat_figure.update_layout(
        title=f"{selected_stat_label} by Manager",
        xaxis_title="Manager",
        yaxis_title=selected_stat_label,
        margin=dict(t=40, b=0, l=0, r=0),
    )
    st.plotly_chart(stat_figure, width="stretch")


def render_history_page() -> None:
    champions_data = load_all_time_champions()
    manager_stats_data = load_all_time_manager_stats()
    records_data = load_all_time_records()
    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()

    if not champions_data["champions"]:
        st.info("No seasons aggregated yet.")
        return

    _render_season_summary_paragraph(champions_data, name_resolver)
    _render_champions_table(champions_data, name_resolver, manager_color_map)
    _render_champion_charts(champions_data, name_resolver, manager_color_map)
    _render_records(records_data, name_resolver)
    manager_standings_dataframe = _build_manager_standings_dataframe(manager_stats_data, name_resolver)
    _render_manager_standings_table(manager_standings_dataframe)
    _render_manager_stat_chart(manager_standings_dataframe, manager_color_map)
