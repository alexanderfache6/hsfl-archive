"""Yearly tab - weekly stat tables/charts and season aggregates for a
single selected season. See execution-plan.md Phase G.
"""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    discover_seasons,
    load_transactions,
    load_weekly_tables,
    resolve_manager_name,
    team_id_to_manager_map,
)


def _full_table_height(row_count: int) -> int:
    """Same sizing rule as the History tab's tables - st.dataframe
    defaults to a fixed max height with internal scrolling once a table
    has more rows than fit; passing an explicit height instead shows
    every row with no fold/scroll."""
    return 38 + 35 * row_count


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


def _parse_transaction_date(date_text: str, season: int) -> datetime:
    """"Dec 28, 4:33pm" + season -> a real datetime. A season's playoffs
    can run into January of the FOLLOWING calendar year (confirmed for
    2012, 2021, 2022) - only "Jan" dates get season+1, everything else
    (Aug-Dec) uses the season's own year."""
    month_text = date_text.split(" ", 1)[0]
    year = season + 1 if month_text == "Jan" else season
    return datetime.strptime(f"{date_text} {year}", "%b %d, %I:%M%p %Y")


TRANSACTIONS_PAGE_SIZE = 10


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
            key="yearly_transactions_team",
        )
    with type_column:
        selected_type = st.selectbox(
            "Transaction",
            transaction_types,
            index=None,
            placeholder="Any",
            key="yearly_transactions_type",
        )
    with date_column:
        selected_range = st.date_input(
            "Date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="yearly_transactions_date_range",
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
    if st.session_state.get("yearly_transactions_page", 1) > total_pages:
        st.session_state["yearly_transactions_page"] = 1
    # page_column was created up front alongside the other filters (same
    # st.columns row) so Page visually sits on their right, even though
    # its max_value can only be computed after those filters are applied.
    with page_column:
        page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="yearly_transactions_page")
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


def render_yearly_page() -> None:
    seasons = discover_seasons()
    if not seasons:
        st.info("No seasons aggregated yet.")
        return

    # Single mandatory season (not an "Any" filter like Players/Games -
    # this whole tab is inherently scoped to one season at a time),
    # defaulting to the most recent one.
    selected_season = st.selectbox("Season", seasons, index=len(seasons) - 1, key="yearly_season")

    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()

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
