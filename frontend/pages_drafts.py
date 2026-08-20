"""Drafts tab - draft recap/analysis and player-level draft analysis for
a single selected season. See execution-plan.md Phase G."""

# ========================================
# IMPORTS
# ========================================

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from colors import COLOR_CHART_STAT, COLOR_MANAGER_BACKUP, COLOR_POINTS_POSITIVE, COLOR_TABLE_ROSTER
from constants import AUCTION_BUDGET, BENCH_POSITION_COLOR, BENCH_POSITION_ORDER, NFL_TEAM_ABBREVIATIONS
from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    contrasting_text_color,
    discover_seasons,
    load_draft,
    resolve_manager_name,
    team_id_to_manager_map,
)
from helpers import manager_pill

# ========================================
# RENDER
# ========================================


def _render_draft_pick_card(
    pick: dict,
    draft_type: str,
    num_teams: int,
    team_info: dict[str, dict],
    name_resolver: dict[str, str],
    manager_color_map: dict[str, str],
) -> None:
    overall_pick = pick["overall_pick"]

    # "Round"/"pick within round" is only a meaningful concept for a
    # snake draft, where picks strictly alternate direction team-by-team
    # - an auction draft's overall_pick is just nomination order (any
    # team can nominate/win any pick), so it gets its own simpler badge
    # instead of a fabricated "round".
    if draft_type == "snake" and num_teams:
        round_number = ((overall_pick - 1) // num_teams) + 1
        pick_in_round = ((overall_pick - 1) % num_teams) + 1
        badge = f"Round {round_number} · Pick {pick_in_round} · Overall #{overall_pick}"
    else:
        badge = f"Overall #{overall_pick}"

    manager_id = team_info.get(pick["team_id"], {}).get("manager_id", "")

    with st.container(border=True):
        st.caption(badge)
        player_column, manager_column = st.columns([3, 4])

        with player_column:
            # DEF entries carry an empty nfl_team in the archived data
            # (see NFL_TEAM_ABBREVIATIONS' own docstring in constants.py)
            # - filled back in from the DEF's own player_name (e.g.
            # "49ers") same as the matchups roster table does.
            nfl_team = pick.get("nfl_team") or NFL_TEAM_ABBREVIATIONS.get(pick["player_name"].split(" ")[-1], "")
            st.markdown(
                f"<span style='color:{COLOR_TABLE_ROSTER}; font-weight:600; margin-right:8px;'>{pick['position']}</span><span style='font-weight:600;'>{pick['player_name']}</span> <span style='color:{COLOR_TABLE_ROSTER};'>({nfl_team})</span>",
                unsafe_allow_html=True,
            )

        with manager_column:
            # auction_amount is null both for a snake draft (the concept
            # doesn't apply) AND for a keeper pick within an auction draft
            # (set before the live auction starts, no bid ever happened -
            # see load_draft's docstring) - only the auction case with a
            # real amount gets the $ badge; everything else in an auction
            # draft is labeled "Keeper" so the two null-amount cases stay
            # visually distinguishable from each other.
            amount_html = ""
            if draft_type == "auction":
                if pick.get("auction_amount") is not None:
                    amount_html = f"Auction Price: <span style='color:{COLOR_POINTS_POSITIVE}; font-weight:600;'>${pick['auction_amount']}</span>"
                else:
                    amount_html = "<span style='color:#888888; font-style:italic;'>Keeper</span>"
            # Fixed-width first column (min-width, not width - lets an
            # unusually long name grow past it rather than clip) so the
            # $/Keeper text in the second column lines up at the same x
            # position across every card, regardless of how long each
            # manager's own name happens to be.
            st.markdown(
                f"<div style='display:grid; grid-template-columns:minmax(140px, max-content) 1fr; align-items:center; column-gap:8px;'><div>{manager_pill(manager_id, name_resolver, manager_color_map)}</div><div>{amount_html}</div></div>",
                unsafe_allow_html=True,
            )


DRAFTS_FILTER_WIDGET_BASE_KEYS = ["drafts_recap_search", "drafts_recap_manager", "drafts_recap_position", "drafts_recap_min_amount", "drafts_recap_max_amount"]


def _render_draft_recap_tab(season: int) -> None:
    draft = load_draft(season)
    if not draft:
        st.info("No draft data recorded for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()
    draft_type = draft["draft_type"]

    # Same versioned-widget-key pattern as the Matchups/Players tabs'
    # Clear Filters (see pages_matchups.py's _render_filters) - each
    # filter's ACTUAL key includes a generation counter, so Clear Filters
    # can force brand-new widget instances instead of relying on
    # session_state deletion alone.
    generation = st.session_state.setdefault("drafts_filters_generation", 0)

    def versioned_key(base_key: str) -> str:
        return f"{base_key}_gen{generation}"

    for base_key in DRAFTS_FILTER_WIDGET_BASE_KEYS:
        widget_key = versioned_key(base_key)
        if widget_key not in st.session_state and base_key in st.session_state:
            st.session_state[widget_key] = st.session_state[base_key]

    # Auction $ only means anything for an auction draft - a snake
    # draft's picks all carry a null auction_amount, so the filter would
    # just always empty the results.
    search_column, manager_column, position_column, min_amount_column, max_amount_column = st.columns([3, 2, 1, 1, 1])
    search_text = search_column.text_input("Search player name", key=versioned_key("drafts_recap_search"))
    manager_options = ["All"] + sorted({info["manager_id"] for info in team_info.values()}, key=lambda manager_id: resolve_manager_name(manager_id, name_resolver))
    selected_manager_id = manager_column.selectbox(
        "Manager",
        manager_options,
        format_func=lambda manager_id: "All" if manager_id == "All" else resolve_manager_name(manager_id, name_resolver),
        key=versioned_key("drafts_recap_manager"),
    )
    position_options = ["All"] + [position for position in BENCH_POSITION_ORDER if any(pick["position"] == position for pick in draft["picks"])]
    selected_position = position_column.selectbox("Position", position_options, key=versioned_key("drafts_recap_position"))
    min_amount = min_amount_column.number_input(
        "Min Auction $",
        min_value=0,
        step=1,
        value=None,
        disabled=draft_type != "auction",
        help="Only applies to auction drafts" if draft_type != "auction" else None,
        key=versioned_key("drafts_recap_min_amount"),
    )
    max_amount = max_amount_column.number_input(
        "Max Auction $",
        min_value=0,
        step=1,
        value=None,
        disabled=draft_type != "auction",
        help="Only applies to auction drafts" if draft_type != "auction" else None,
        key=versioned_key("drafts_recap_max_amount"),
    )

    st.session_state["drafts_recap_search"] = search_text
    st.session_state["drafts_recap_manager"] = selected_manager_id
    st.session_state["drafts_recap_position"] = selected_position
    st.session_state["drafts_recap_min_amount"] = min_amount
    st.session_state["drafts_recap_max_amount"] = max_amount

    # NOTE use same `apply_column, clear_column, _ = st.columns([1, 1, 6])` for any filtering pages
    apply_column, clear_column, _ = st.columns([1, 1, 6])
    with apply_column:
        applied = st.button("Apply Filters", use_container_width=True)
    with clear_column:
        if st.button("Clear Filters", use_container_width=True):
            for base_key in DRAFTS_FILTER_WIDGET_BASE_KEYS:
                st.session_state.pop(base_key, None)
            st.session_state.pop("drafts_applied_filters", None)
            st.session_state["drafts_filters_generation"] = generation + 1
            st.rerun()

    if applied:
        st.session_state["drafts_applied_filters"] = {
            "search_text": search_text,
            "manager_id": selected_manager_id,
            "position": selected_position,
            "min_amount": min_amount,
            "max_amount": max_amount,
        }

    applied_filters = st.session_state.get("drafts_applied_filters")
    if applied_filters is None:
        st.info("Set your filters above and click Apply Filters.")
        return

    picks = sorted(draft["picks"], key=lambda pick: pick["overall_pick"])
    if applied_filters["search_text"]:
        picks = [pick for pick in picks if applied_filters["search_text"].lower() in pick["player_name"].lower()]
    if applied_filters["manager_id"] != "All":
        picks = [pick for pick in picks if team_info.get(pick["team_id"], {}).get("manager_id") == applied_filters["manager_id"]]
    if applied_filters["position"] != "All":
        picks = [pick for pick in picks if pick["position"] == applied_filters["position"]]
    if draft_type == "auction" and applied_filters["min_amount"] is not None:
        picks = [pick for pick in picks if pick["auction_amount"] is not None and pick["auction_amount"] >= applied_filters["min_amount"]]
    if draft_type == "auction" and applied_filters["max_amount"] is not None:
        picks = [pick for pick in picks if pick["auction_amount"] is not None and pick["auction_amount"] <= applied_filters["max_amount"]]

    if not picks:
        st.info("No picks match these filters.")
        return

    st.caption(f"Showing {len(picks)} of {len(draft['picks'])} picks.")

    # Cards only fill half the page width - at full width a two-column
    # [player | manager] row leaves an awkward amount of empty space on
    # a wide monitor for content this short.
    _, cards_column, _ = st.columns([1, 2, 1])
    with cards_column:
        for pick in picks:
            _render_draft_pick_card(pick, draft_type, len(team_info), team_info, name_resolver, manager_color_map)


def _render_manager_recap_tab(season: int) -> None:
    draft = load_draft(season)
    if not draft:
        st.info("No draft data recorded for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()
    draft_type = draft["draft_type"]

    manager_ids = sorted({info["manager_id"] for info in team_info.values()}, key=lambda manager_id: resolve_manager_name(manager_id, name_resolver))
    selected_manager_id = st.selectbox(
        "Manager",
        manager_ids,
        format_func=lambda manager_id: resolve_manager_name(manager_id, name_resolver),
        key="drafts_manager_recap_manager",
    )
    if not selected_manager_id:
        return

    manager_picks = sorted(
        (pick for pick in draft["picks"] if team_info.get(pick["team_id"], {}).get("manager_id") == selected_manager_id),
        key=lambda pick: pick["overall_pick"],
    )

    picks_column, metrics_column = st.columns(2)

    with picks_column:
        st.subheader("Selections")
        position_options = ["All"] + [position for position in BENCH_POSITION_ORDER if any(pick["position"] == position for pick in manager_picks)]
        # A position picked for the PREVIOUS manager can fall outside
        # this manager's own position_options (e.g. no K picked this
        # draft) - same stale-selection guard used elsewhere (see
        # pages_matchups.py's _render_filters Season/Manager 2 guards),
        # since st.selectbox errors if its existing session_state value
        # isn't in the new options list.
        position_widget_key = "drafts_manager_recap_position"
        if st.session_state.get(position_widget_key) not in position_options:
            st.session_state[position_widget_key] = "All"
        selected_position = st.selectbox("Position", position_options, key=position_widget_key)
        selection_cards = manager_picks if selected_position == "All" else [pick for pick in manager_picks if pick["position"] == selected_position]

        for pick in selection_cards:
            _render_draft_pick_card(pick, draft_type, len(team_info), team_info, name_resolver, manager_color_map)

    with metrics_column:
        st.subheader("Metrics")

        if draft_type == "auction":
            with st.expander("Auction Metrics", expanded=False):
                total_spent = sum(pick["auction_amount"] for pick in manager_picks if pick.get("auction_amount") is not None)
                remaining_budget = AUCTION_BUDGET - total_spent
                one_dollar_pick_count = sum(1 for pick in manager_picks if pick.get("auction_amount") == 1)
                priced_picks = [pick for pick in manager_picks if pick.get("auction_amount") is not None]

                remaining_column, one_dollar_column = st.columns(2)
                remaining_column.metric("Remaining Salary Cap", f"${remaining_budget}", help="Remaining $ budget once all selections were made.")
                one_dollar_column.metric("$1 Picks", one_dollar_pick_count, help="The number of $1 picks made.")

                # Fisher-Pearson (bias-corrected) skewness of this
                # manager's own auction prices - pandas' Series.skew()
                # needs at least 3 points to be defined, same reason a
                # 1-2 pick manager wouldn't get a meaningful distribution
                # shape at all.
                skew_column, _ = st.columns(2)
                auction_price_skew = pd.Series([pick["auction_amount"] for pick in priced_picks]).skew() if len(priced_picks) >= 3 else None
                skew_column.metric("Auction Price Skew", f"{auction_price_skew:.2f}" if auction_price_skew is not None else "—", help="Right skewness of auction price selections. A higher number indicates extreme price selection and greater dependence on $1 picks. Fantasy range ~1-3")

                if priced_picks:
                    st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)

                    # Manually binned (rather than go.Histogram) so each
                    # bin's hover can list its own picks - a real
                    # go.Histogram trace only ever aggregates, it can't
                    # surface the underlying player/price pairs that made
                    # up a bin's count.
                    max_price = max(pick["auction_amount"] for pick in priced_picks)
                    bin_starts = list(range(0, ((max_price // 10) + 1) * 10, 10))
                    bin_labels = [f"${bin_start}-{bin_start + 9}" for bin_start in bin_starts]
                    bin_counts = []
                    bin_hover_text = []
                    for bin_start, bin_label in zip(bin_starts, bin_labels):
                        picks_in_bin = sorted(
                            (pick for pick in priced_picks if bin_start <= pick["auction_amount"] < bin_start + 10),
                            key=lambda pick: -pick["auction_amount"],
                        )  # NOTE sort by pick price descending
                        bin_counts.append(len(picks_in_bin))
                        bin_hover_text.append("<br>".join([f"<b>Bin {bin_label}</b>"] + [f"{pick['player_name']} ${pick['auction_amount']}" for pick in picks_in_bin]))

                    histogram_figure = go.Figure(
                        go.Bar(
                            x=bin_labels,
                            y=bin_counts,
                            marker={"color": COLOR_CHART_STAT},
                            customdata=bin_hover_text,
                            hovertemplate="%{customdata}<extra></extra>",
                        )
                    )
                    histogram_figure.update_layout(
                        title="Auction Price Distribution",
                        xaxis_title="Auction Price",
                        yaxis_title="Player Count",
                        margin={"t": 50, "l": 60, "r": 20, "b": 50},
                    )
                    st.plotly_chart(histogram_figure, width="stretch")

        with st.expander("Depth Chart Summary", expanded=False):
            for position in BENCH_POSITION_ORDER:
                position_picks = sorted((pick for pick in manager_picks if pick["position"] == position), key=lambda pick: pick["overall_pick"])
                if not position_picks:
                    continue

                position_background_color = BENCH_POSITION_COLOR.get(position, COLOR_TABLE_ROSTER)
                position_text_color = contrasting_text_color(position_background_color)
                st.markdown(
                    f"<span style='background-color:{position_background_color}; color:{position_text_color}; padding:2px 8px; border-radius:6px; font-weight:600;'>{position}</span>",
                    unsafe_allow_html=True,
                )
                rows = [
                    {
                        "Player": pick["player_name"],
                        "Team": pick.get("nfl_team") or NFL_TEAM_ABBREVIATIONS.get(pick["player_name"].split(" ")[-1], ""),
                        "Pick": pick["overall_pick"],
                        **({"Auction Value": f"${pick['auction_amount']}" if pick.get("auction_amount") is not None else "—"} if draft_type == "auction" else {}),
                    }
                    for pick in position_picks
                ]
                if draft_type == "auction":
                    total_auction_price = sum(pick["auction_amount"] for pick in position_picks if pick.get("auction_amount") is not None)
                    rows.append({"Player": "Total Auction Price", "Team": "", "Pick": "", "Auction Value": f"${total_auction_price}"})

                def _bold_total_row(row: pd.Series) -> list[str]:
                    return ["font-weight:bold"] * len(row) if row["Player"] == "Total Auction Price" else [""] * len(row)

                dataframe = pd.DataFrame(rows)
                st.dataframe(dataframe.style.apply(_bold_total_row, axis=1), hide_index=True, width="stretch")

        with st.expander("Depth Chart Breakdown", expanded=False):
            position_groups = [position for position in BENCH_POSITION_ORDER if any(pick["position"] == position for pick in manager_picks)]
            picks_by_position = {position: [pick for pick in manager_picks if pick["position"] == position] for position in position_groups}

            pie_figure = go.Figure(
                go.Pie(
                    labels=position_groups,
                    values=[len(picks_by_position[position]) for position in position_groups],
                    sort=False,
                    rotation=0,  # first slice starts at 12 o'clock
                    direction="clockwise",
                    marker={"colors": [BENCH_POSITION_COLOR.get(position) for position in position_groups]},
                    textinfo="label+value",
                    showlegend=False,
                    customdata=["<br>".join(pick["player_name"] for pick in picks_by_position[position]) for position in position_groups],
                    hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
                )
            )
            pie_figure.update_layout(title="Player Count by Position", margin={"t": 40, "b": 20, "l": 20, "r": 20})
            st.plotly_chart(pie_figure, width="stretch")

            st.markdown("<div style='height:2rem;'></div>", unsafe_allow_html=True)

            # Auction drafts get $ spent per pick (total position spend /
            # picks in that position) - a snake draft has no auction
            # amounts at all, so it gets the closest equivalent instead:
            # average overall_pick, i.e. how early that position group
            # tended to get drafted.
            if draft_type == "auction":
                bar_label = "Average Auction Price per Pick"
                bar_values = [sum(pick["auction_amount"] for pick in picks_by_position[position] if pick.get("auction_amount") is not None) / max(1, sum(1 for pick in picks_by_position[position] if pick.get("auction_amount") is not None)) for position in position_groups]
            else:
                bar_label = "Average Pick"
                bar_values = [sum(pick["overall_pick"] for pick in picks_by_position[position]) / len(picks_by_position[position]) for position in position_groups]

            bar_figure = go.Figure(
                go.Bar(
                    x=position_groups,
                    y=bar_values,
                    marker={"color": [BENCH_POSITION_COLOR.get(position) for position in position_groups]},
                    hovertemplate="<b>%{x}</b><br>" + bar_label + ": %{y:.2f}<extra></extra>",
                )
            )
            bar_figure.update_layout(
                title=f"{'Average Auction Price per Pick' if draft_type == 'auction' else 'Average Pick'}",
                xaxis_title="Position",
                yaxis_title=bar_label,
                margin={"t": 50, "l": 70, "r": 20, "b": 50},
            )
            st.plotly_chart(bar_figure, width="stretch")


def _render_keepers_tab() -> None:
    st.info("Keeper history is aggregated across every season in the archive.")

    # A "keeper" is only identifiable within an AUCTION season - its
    # picks carry a null auction_amount because no live bid ever
    # happened (see load_draft's docstring). A snake draft's picks are
    # ALSO all null-auction_amount (the field just doesn't apply there),
    # so including snake seasons here would wrongly count every single
    # snake pick as a keeper.
    # Tracks each player's own position alongside their keeper count - a
    # player's position is assumed stable across keeper seasons (last
    # occurrence wins if it somehow isn't), used to color/group bars by
    # position below.
    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()

    keeper_data: dict[str, dict] = {}
    for season in discover_seasons():
        draft = load_draft(season)
        if not draft or draft["draft_type"] != "auction":
            continue
        team_info = team_id_to_manager_map(season)
        for pick in draft["picks"]:
            if pick.get("auction_amount") is None:
                entry = keeper_data.setdefault(pick["player_name"], {"count": 0, "position": pick["position"], "years": [], "by_manager": {}})
                entry["count"] += 1
                entry["position"] = pick["position"]
                entry["years"].append(season)
                manager_id = team_info.get(pick["team_id"], {}).get("manager_id", "")
                manager_entry = entry["by_manager"].setdefault(manager_id, {"count": 0, "years": []})
                manager_entry["count"] += 1
                manager_entry["years"].append(season)

    chart_column, loyalty_column = st.columns(2)

    with chart_column:
        if not keeper_data:
            st.info("No keeper picks recorded in the archive yet.")
            return

        # Sorted descending by count - go.Bar's horizontal orientation
        # draws its y-categories bottom-to-top in list order, so the
        # sorted list is reversed here to put the LARGEST count at the
        # TOP of the chart (i.e. visually descending top-to-bottom).
        sorted_players = sorted(keeper_data.items(), key=lambda item: item[1]["count"], reverse=True)[::-1]
        all_players = [player for player, _ in sorted_players]

        bar_figure = go.Figure()
        # One real go.Bar trace per position (not a single trace with a
        # per-point color array) - same reasoning as the per-manager
        # legend traces elsewhere in this app: only a real trace per
        # legend entry makes clicking that entry in the legend actually
        # toggle just its own bars.
        for position in BENCH_POSITION_ORDER:
            position_players = [player for player, data in sorted_players if data["position"] == position]
            if not position_players:
                continue
            position_counts = [keeper_data[player]["count"] for player in position_players]
            position_years_text = [", ".join(str(year) for year in sorted(keeper_data[player]["years"])) for player in position_players]
            bar_figure.add_trace(
                go.Bar(
                    x=position_counts,
                    y=position_players,
                    orientation="h",
                    name=position,
                    marker={"color": BENCH_POSITION_COLOR.get(position)},
                    customdata=position_years_text,
                    hovertemplate=f"<b>%{{y}}</b><br>Frequency: %{{x}}<br>Years: %{{customdata}}<br>{position}<extra></extra>",
                )
            )
        bar_figure.update_layout(
            title="Keeper Frequency",
            xaxis_title="Frequency",
            yaxis_title="Player",
            # "total ascending" (not a fixed categoryarray) so the axis
            # recomputes from only the currently VISIBLE traces when a
            # position is hidden via the legend - ties in count aren't
            # guaranteed to break in any particular order.
            yaxis={"categoryorder": "total ascending"},
            legend_title_text="Position",
            margin={"t": 50, "l": 150, "r": 20, "b": 50},
            height=max(300, 30 * len(all_players)),
        )
        st.plotly_chart(bar_figure, width="stretch")

    with loyalty_column:
        # "loyalty" - the share of a player's total keeper count owned by
        # their single most-frequent manager (1.0 = always kept by the
        # same manager, lower = spread across managers) - not the same
        # ranking as the frequency chart on the left, so this needs its
        # own (loyalty, then count) sort rather than reusing sorted_players.
        for entry in keeper_data.values():
            entry["loyalty"] = max(manager_entry["count"] for manager_entry in entry["by_manager"].values()) / entry["count"]

        # Ascending, for the same bottom-to-top reasoning as the left
        # chart - the HIGHEST loyalty (then highest count as tiebreak)
        # needs to be LAST in this list to land at the TOP.
        loyalty_sorted_players = sorted(keeper_data.items(), key=lambda item: (item[1]["loyalty"], item[1]["count"]))
        loyalty_all_players = [player for player, _ in loyalty_sorted_players]

        # Reverse alphabetical (Z->A) - legend.traceorder="reversed" (a
        # layout-level property) didn't visibly change the on-screen
        # legend order, so the trace ADD order itself is reversed here
        # instead, which is guaranteed to control both the legend AND
        # the stack order together.
        manager_ids_present = sorted(
            {manager_id for data in keeper_data.values() for manager_id in data["by_manager"] if manager_id},
            key=lambda manager_id: resolve_manager_name(manager_id, name_resolver),
            reverse=True,
        )

        # One combined hover string per PLAYER (not per manager segment) -
        # every manager's trace reuses the exact same text at that
        # player's row, so hovering anywhere on the stacked bar shows the
        # full manager breakdown as a single tooltip rather than each
        # segment popping its own. Rows sorted by that manager's most
        # recent keeper year, descending.
        player_hover_text = {}
        for player in loyalty_all_players:
            data = keeper_data[player]
            managers_by_recency = sorted(data["by_manager"].items(), key=lambda item: max(item[1]["years"]), reverse=True)
            manager_lines = [f"{resolve_manager_name(manager_id, name_resolver)}: {', '.join(str(year) for year in sorted(manager_entry['years']))}" for manager_id, manager_entry in managers_by_recency]
            player_hover_text[player] = "<br>".join([f"<b>{player}</b>", f"Manager Count: {len(data['by_manager'])}", *manager_lines])

        loyalty_figure = go.Figure()
        for manager_id in manager_ids_present:
            manager_name = resolve_manager_name(manager_id, name_resolver)
            manager_counts = [keeper_data[player]["by_manager"].get(manager_id, {"count": 0})["count"] for player in loyalty_all_players]
            manager_customdata = [player_hover_text[player] for player in loyalty_all_players]

            loyalty_figure.add_trace(
                go.Bar(
                    x=manager_counts,
                    y=loyalty_all_players,
                    orientation="h",
                    name=manager_name,
                    marker={"color": manager_color_map.get(manager_id, COLOR_MANAGER_BACKUP)},
                    customdata=manager_customdata,
                    hovertemplate="%{customdata}<extra></extra>",
                )
            )

        loyalty_figure.update_layout(
            title="Keeper Loyalty",
            xaxis_title="Frequency",
            yaxis_title="Player",
            barmode="stack",
            yaxis={"categoryorder": "array", "categoryarray": loyalty_all_players},
            legend_title_text="Manager",
            # Legend is a color key only here (stacking makes hiding a
            # single manager's segment confusing to interpret) - both
            # click handlers are disabled so it can't toggle traces.
            legend={"itemclick": False, "itemdoubleclick": False},
            margin={"t": 50, "l": 150, "r": 20, "b": 50},
            height=max(300, 30 * len(loyalty_all_players)),
        )
        st.plotly_chart(loyalty_figure, width="stretch")


def render_drafts_page() -> None:
    seasons = discover_seasons()
    if not seasons:
        st.info("No seasons aggregated yet.")
        return

    # Single mandatory season (same pattern as pages_seasons.py) -
    # defaulting to the most recent one.
    selected_season = st.selectbox("Select Season", seasons, index=len(seasons) - 1, key="drafts_season")

    draft_recap_tab, manager_recap_tab, keepers_tab, draft_analysis_tab, player_analysis_tab = st.tabs(["Draft Recap", "Manager Recap", "Keepers", "Draft Analysis", "Player Analysis"])

    with draft_recap_tab:
        _render_draft_recap_tab(selected_season)

    with manager_recap_tab:
        _render_manager_recap_tab(selected_season)

    with keepers_tab:
        _render_keepers_tab()

    with draft_analysis_tab:
        pass

    with player_analysis_tab:
        pass
