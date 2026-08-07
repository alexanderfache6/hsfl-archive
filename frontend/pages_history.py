"""History tab - all-time champions, records, and career manager stats
across every season in the archive. See execution-plan.md Phase G.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    build_manager_name_resolver,
    load_all_time_champions,
    load_all_time_manager_stats,
    load_all_time_records,
    resolve_manager_name,
)

# Standard real-world medal colors - not a generated categorical palette,
# so not run through the dataviz skill's CVD validator (this exact
# 3-color convention is a fixed, universally recognized domain standard,
# and the three already differ sharply in lightness: bright yellow-gold,
# light neutral silver, dark orange-brown bronze).
CHAMPION_COLOR = "#d0b04e"
RUNNER_UP_COLOR = "#a7a7a7"
THIRD_PLACE_COLOR = "#9f724b"

def _full_table_height(row_count: int) -> int:
    """st.dataframe defaults to a fixed max height with internal
    scrolling once a table has more rows than fit - passing an explicit
    height sized to the actual row count instead shows every row with no
    fold/scroll. ~35px/row + ~38px header, based on Streamlit's default
    row height."""
    return 38 + 35 * row_count + 3


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
RECORD_ROW_PAIRS = [
    ("highest_weekly_score", "lowest_weekly_score"),
    ("highest_season_points_for", "lowest_season_points_for"),
    ("longest_win_streak", "longest_losing_streak"),
    ("best_coaching_season", "worst_coaching_season"),
    ("most_players_started_season", "fewest_players_started_season"),
]


def _render_champions_table(champions_data: dict, name_resolver: dict[str, str]) -> None:
    st.subheader("Champions by Season")
    rows = []
    for season_entry in sorted(champions_data["champions"], key=lambda c: c["season"], reverse=True):
        top_3 = {row["rank"]: row for row in season_entry["top_3"]}

        def name_for(entry: dict) -> str:
            return resolve_manager_name(entry.get("manager_id", ""), name_resolver, entry.get("display_name", ""))

        rows.append(
            {
                "Season": season_entry["season"],
                "Champion": name_for(top_3.get(1, {})),
                "Runner-Up": name_for(top_3.get(2, {})),
                "3rd Place": name_for(top_3.get(3, {})),
                "Last Place": name_for(season_entry["last_place"]),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=_full_table_height(len(rows)))


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


def _render_champion_charts(champions_data: dict, name_resolver: dict[str, str]) -> None:
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

        pie_figure = go.Figure(
            go.Pie(
                labels=labels,
                values=values,
                sort=False,  # preserve our own count-then-recency order, not plotly's default value sort
                rotation=0,  # first slice starts at 12 o'clock
                direction="clockwise",
                marker=dict(colors=[px.colors.qualitative.Set3[i % len(px.colors.qualitative.Set3)] for i in range(len(labels))]),
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
            title="Championship / Runner-Up / 3rd Place by Manager",
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
    parts = [display_name, f"{entry['season']}"]
    if "week" in entry:
        parts.append(f"Wk {entry['week']}")
    return " · ".join(parts)


def _render_record_cell(key: str, top_n: list[dict], name_resolver: dict[str, str]) -> None:
    if not top_n:
        st.metric(RECORD_LABELS[key], "-")
        return

    first = top_n[0]
    st.metric(RECORD_LABELS[key], f"{first['value']:g}")
    st.caption(_record_context_line(first, name_resolver))

    ordinal_labels = ["2nd", "3rd"]
    for ordinal_label, entry in zip(ordinal_labels, top_n[1:]):
        st.caption(f":gray[{ordinal_label}: {entry['value']:g} — {_record_context_line(entry, name_resolver)}]")


def _render_records(records_data: dict, name_resolver: dict[str, str]) -> None:
    st.subheader("All-Time Records")
    for high_key, low_key in RECORD_ROW_PAIRS:
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
    "Last Place",
    "Avg Reg. Finish",
    "Avg Post. Finish",
    "W",
    "L",
    "T",
    "Win %",
    "Points For",
    "Points Against",
    "Career Players Started",
]

# Full-length labels for chart titles/axes/dropdown - the table itself
# keeps the compact column headers above (space is tighter there).
MANAGER_STAT_FULL_LABELS = {
    "Seasons": "Seasons Played",
    "Championships": "Championships",
    "Runner-Ups": "Runner-Up Finishes",
    "3rd Place": "3rd Place Finishes",
    "Last Place": "Last Place Finishes",
    "Avg Reg. Finish": "Average Regular Season Finish",
    "Avg Post. Finish": "Average Postseason Finish",
    "W": "Wins",
    "L": "Losses",
    "T": "Ties",
    "Win %": "Win Percentage",
    "Points For": "Points For",
    "Points Against": "Points Against",
    "Career Players Started": "Career Players Started",
}


def _build_manager_standings_dataframe(manager_stats_data: dict, name_resolver: dict[str, str]) -> pd.DataFrame:
    rows = []
    for manager in manager_stats_data["managers"]:
        combined = manager["combined"]
        rows.append(
            {
                "Manager": resolve_manager_name(manager["manager_id"], name_resolver),
                "Seasons": len(manager["seasons_played"]),
                "Championships": manager["championships"],
                "Runner-Ups": manager["runner_ups"],
                "3rd Place": manager["third_place_finishes"],
                "Last Place": manager["last_place_finishes"],
                "Avg Reg. Finish": manager["average_regular_season_finish"],
                "Avg Post. Finish": manager["average_post_season_finish"],
                "W": combined["wins"],
                "L": combined["losses"],
                "T": combined["ties"],
                "Win %": combined["win_pct"],
                "Points For": combined["points_for"],
                "Points Against": combined["points_against"],
                "Career Players Started": manager["career_players_started_count"],
            }
        )
    return pd.DataFrame(rows).sort_values(["Seasons", "Manager"], ascending=[False, True])


def _render_manager_standings_table(dataframe: pd.DataFrame) -> None:
    st.subheader("Career Manager Standings")
    st.dataframe(
        dataframe,
        hide_index=True,
        width="stretch",
        height=_full_table_height(len(dataframe)),
        column_config={
            column: st.column_config.NumberColumn(format=fmt) for column, fmt in MANAGER_STAT_COLUMN_FORMATS.items()
        },
    )


def _render_manager_stat_chart(dataframe: pd.DataFrame) -> None:
    selected_stat = st.selectbox(
        "Stat to chart",
        MANAGER_STAT_COLUMNS,
        format_func=lambda column: MANAGER_STAT_FULL_LABELS[column],
        key="manager_stat_chart_selection",
    )
    selected_stat_label = MANAGER_STAT_FULL_LABELS[selected_stat]

    chart_data = dataframe[["Manager", selected_stat]].dropna(subset=[selected_stat]).sort_values(selected_stat, ascending=False)

    stat_figure = go.Figure(
        go.Bar(
            x=chart_data["Manager"],
            y=chart_data[selected_stat],
            marker_color="#4C78A8",
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

    if not champions_data["champions"]:
        st.info("No seasons aggregated yet.")
        return

    _render_champions_table(champions_data, name_resolver)
    _render_champion_charts(champions_data, name_resolver)
    st.divider()
    _render_records(records_data, name_resolver)
    st.divider()
    manager_standings_dataframe = _build_manager_standings_dataframe(manager_stats_data, name_resolver)
    _render_manager_standings_table(manager_standings_dataframe)
    _render_manager_stat_chart(manager_standings_dataframe)
