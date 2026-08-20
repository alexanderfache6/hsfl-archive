"""Drafts tab - draft recap/analysis and player-level draft analysis for
a single selected season. See execution-plan.md Phase G."""

# ========================================
# IMPORTS
# ========================================

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from colors import COLOR_CHART_STAT, COLOR_POINTS_POSITIVE, COLOR_TABLE_ROSTER
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


def render_drafts_page() -> None:
    seasons = discover_seasons()
    if not seasons:
        st.info("No seasons aggregated yet.")
        return

    # Single mandatory season (same pattern as pages_seasons.py) -
    # defaulting to the most recent one.
    selected_season = st.selectbox("Select Season", seasons, index=len(seasons) - 1, key="drafts_season")

    draft_recap_tab, manager_recap_tab, draft_analysis_tab, player_analysis_tab = st.tabs(["Draft Recap", "Manager Recap", "Draft Analysis", "Player Analysis"])

    with draft_recap_tab:
        _render_draft_recap_tab(selected_season)

    with manager_recap_tab:
        _render_manager_recap_tab(selected_season)

    with draft_analysis_tab:
        pass

    with player_analysis_tab:
        pass
