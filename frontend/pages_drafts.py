"""Drafts tab - draft recap/analysis and player-level draft analysis for
a single selected season. See execution-plan.md Phase G."""

# ========================================
# IMPORTS
# ========================================

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from colors import (
    COLOR_CHART_AUCTION,
    COLOR_CHART_PICK,
    COLOR_CHART_SCATTER_MARKER_OUTLINE,
    COLOR_CHART_STAT,
    COLOR_MANAGER_BACKUP,
    COLOR_PERCENTILE_OTHER_PLAYERS,
    COLOR_PERCENTILE_SELECTED_PLAYER,
    COLOR_POINTS_NEGATIVE,
    COLOR_POINTS_POSITIVE,
    COLOR_TABLE_ROSTER,
)
from constants import (
    AUCTION_BUDGET,
    BENCH_POSITION_COLOR,
    BENCH_POSITION_ORDER,
    CHART_LINE_AUCTION_WIDTH,
    CHART_LINE_OTHER_WIDTH,
    MAX_YAXIS_TICKS,
    NFL_TEAM_ABBREVIATIONS,
    SCATTER_PLOT_DRAFT_MARKER_SIZE,
    SCATTER_PLOT_MARKER_SIZE,
)
from data_loader import (
    build_manager_color_map,
    build_manager_name_resolver,
    contrasting_text_color,
    discover_seasons,
    load_draft,
    load_player_fantasy_value_metrics,
    load_player_ownership,
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
        player_column, manager_column = st.columns([4, 5])

        with player_column:
            # DEF entries carry an empty nfl_team in the archived data
            # (see NFL_TEAM_ABBREVIATIONS' own docstring in constants.py)
            # - filled back in from the DEF's own player_name (e.g.
            # "49ers") same as the matchups roster table does.
            nfl_team = pick.get("nfl_team") or NFL_TEAM_ABBREVIATIONS.get(pick["player_name"].split(" ")[-1], "")
            position_background_color = BENCH_POSITION_COLOR.get(pick["position"], COLOR_TABLE_ROSTER)
            position_text_color = contrasting_text_color(position_background_color)
            st.markdown(
                f"<span style='background-color:{position_background_color}; color:{position_text_color}; padding:2px 8px; border-radius:6px; font-weight:600; margin-right:8px;'>{pick['position']}</span><span style='font-weight:600;'>{pick['player_name']}</span> <span style='color:{COLOR_TABLE_ROSTER};'>({nfl_team})</span>",
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


def _render_pick_distribution_chart(
    picks: list[dict],
    value_fn,
    bucket_size: int,
    bucket_label_fn,
    subheader: str,
    xaxis_title: str,
    widget_key: str,
    empty_message: str,
    reverse_buckets: bool = False,
) -> None:
    """Shared by the Auction Price Distribution (auction seasons) and
    Draft Position Distribution (snake seasons) charts in the Stats tab -
    both are "bucket some per-pick numeric value, count players per
    bucket, let a Position selectbox overlay that position's own bars
    (BENCH_POSITION_COLOR) on top of the whole draft's (faded gray)"
    chart, just with a different value/bucket-size/label source.
    reverse_buckets=True (used for the snake Round chart) puts the
    LOWEST-value bucket on the right instead of the left, so "more
    valuable" reads right-to-left the same way it already does on the
    auction chart (higher $ bins sit further right there, and Round 1 -
    the most valuable snake picks - needs that same visual position)."""
    st.subheader(subheader)
    position_options = ["All"] + [position for position in BENCH_POSITION_ORDER if any(pick["position"] == position for pick in picks)]
    selected_position = st.selectbox("Select position", position_options, key=widget_key)

    all_values = [value_fn(pick) for pick in picks if value_fn(pick) is not None]
    values = [value_fn(pick) for pick in picks if value_fn(pick) is not None and (selected_position == "All" or pick["position"] == selected_position)]
    if not values:
        st.info(empty_message)
        return

    # Every bucket from 1 up to the highest value is shown even if empty
    # (no skipped buckets). The bucket range comes from the WHOLE draft's
    # max value (all_values), not the filtered position's own max, so
    # switching Position doesn't rescale the axis out from under you.
    max_value = max(all_values)
    bucket_starts = list(range(1, max_value + 1, bucket_size))
    if reverse_buckets:
        bucket_starts = bucket_starts[::-1]
    bucket_labels = [bucket_label_fn(bucket_start, bucket_size) for bucket_start in bucket_starts]

    def _bucket_counts(bucket_values: list[float]) -> list[int]:
        counts = {bucket_start: 0 for bucket_start in bucket_starts}
        for value in bucket_values:
            counts[1 + ((value - 1) // bucket_size) * bucket_size] += 1
        return [counts[bucket_start] for bucket_start in bucket_starts]

    is_filtered = selected_position != "All"
    figure = go.Figure()
    if is_filtered:
        # Series 1 - the whole draft, faded gray, drawn UNDERNEATH
        # series 2 (added first, in barmode "overlay" - Plotly draws
        # later traces on top of earlier ones) so the selected position's
        # own bars are still fully visible on top of it.
        figure.add_trace(
            go.Bar(
                x=bucket_labels,
                y=_bucket_counts(all_values),
                name="All",
                marker={"color": COLOR_PERCENTILE_OTHER_PLAYERS, "opacity": 0.5},
                hovertemplate="<b>%{x}</b><br>All Player Count: %{y}<extra></extra>",
            )
        )
    # Series 2's own color: the position's real BENCH_POSITION_COLOR when
    # filtered (matches that same color used everywhere else this app
    # plots positions), or the same faded gray as "All" when not filtered
    # - unfiltered, series 2 IS the "All" data, so it should look like
    # it, not like a real position's own color.
    series_2_marker = {"color": BENCH_POSITION_COLOR.get(selected_position)} if is_filtered else {"color": COLOR_PERCENTILE_OTHER_PLAYERS, "opacity": 0.5}
    figure.add_trace(
        go.Bar(
            x=bucket_labels,
            y=_bucket_counts(values),
            name=selected_position if is_filtered else "All",
            marker=series_2_marker,
            hovertemplate=f"<b>%{{x}}</b><br>{selected_position if is_filtered else 'All'} Player Count: %{{y}}<extra></extra>",
        )
    )
    figure.update_layout(
        barmode="overlay",
        xaxis={"title": xaxis_title, "type": "category"},
        yaxis={"title": "Player Count", "tickformat": "d", "nticks": MAX_YAXIS_TICKS},
        showlegend=is_filtered,
        margin={"t": 20, "l": 60, "r": 20, "b": 50},
    )
    st.plotly_chart(figure, width="stretch")


def _render_draft_recap_tab(season: int) -> None:
    draft = load_draft(season)
    if not draft:
        st.info("No draft data recorded for this season yet.")
        return

    team_info = team_id_to_manager_map(season)
    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()
    draft_type = draft["draft_type"]

    draft_type_article = "an" if draft_type == "auction" else "a"
    st.markdown(f"The {season} draft consisted of {len(team_info)} teams, drafting {len(draft['picks'])} players. Draft followed {draft_type_article} {draft_type} format.")

    selections_tab, stats_tab = st.tabs(["Selections", "Stats"])

    with selections_tab:
        # Same versioned-widget-key pattern as the Matchups/Players tabs'
        # Clear Filters (see pages_matchups.py's _render_filters) - each
        # filter's ACTUAL key includes a generation counter, so Clear
        # Filters can force brand-new widget instances instead of relying
        # on session_state deletion alone.
        generation = st.session_state.setdefault("drafts_filters_generation", 0)

        def versioned_key(base_key: str) -> str:
            return f"{base_key}_gen{generation}"

        for base_key in DRAFTS_FILTER_WIDGET_BASE_KEYS:
            widget_key = versioned_key(base_key)
            if widget_key not in st.session_state and base_key in st.session_state:
                st.session_state[widget_key] = st.session_state[base_key]

        # Auction $ only means anything for an auction draft - a snake
        # draft's picks all carry a null auction_amount, so the filter
        # would just always empty the results.
        search_column, manager_column, position_column, min_amount_column, max_amount_column = st.columns([3, 2, 1, 1, 1])
        # Same "Search for a player" selectbox pattern as pages_players.py
        # - pre-filtered to only players actually picked in THIS draft,
        # rather than every player in the archive.
        drafted_player_names = sorted({pick["player_name"] for pick in draft["picks"]})
        selected_player_name = search_column.selectbox(
            "Search for a player",
            drafted_player_names,
            index=None,
            placeholder="Type a player's name...",
            key=versioned_key("drafts_recap_search"),
        )
        manager_options = ["All"] + sorted({info["manager_id"] for info in team_info.values()}, key=lambda manager_id: resolve_manager_name(manager_id, name_resolver))
        selected_manager_id = manager_column.selectbox(
            "Manager",
            manager_options,
            format_func=lambda manager_id: "All" if manager_id == "All" else resolve_manager_name(manager_id, name_resolver),
            key=versioned_key("drafts_recap_manager"),
        )
        position_options = ["All"] + [position for position in BENCH_POSITION_ORDER if any(pick["position"] == position for pick in draft["picks"])]
        selected_position = position_column.selectbox("Position", position_options, key=versioned_key("drafts_recap_position"))
        # Auction $ has no meaning at all for a snake draft (every pick's
        # auction_amount is null) - rather than a disabled/greyed-out
        # input explaining that, the columns are just left blank.
        min_amount = max_amount = None
        if draft_type == "auction":
            min_amount = min_amount_column.number_input(
                "Min Auction $",
                min_value=0,
                step=5,
                value=None,
                key=versioned_key("drafts_recap_min_amount"),
            )
            max_amount = max_amount_column.number_input(
                "Max Auction $",
                min_value=0,
                step=5,
                value=None,
                key=versioned_key("drafts_recap_max_amount"),
            )

        st.session_state["drafts_recap_search"] = selected_player_name
        st.session_state["drafts_recap_manager"] = selected_manager_id
        st.session_state["drafts_recap_position"] = selected_position
        st.session_state["drafts_recap_min_amount"] = min_amount
        st.session_state["drafts_recap_max_amount"] = max_amount

        # NOTE use same `apply_column, clear_column, _ = st.columns([1, 1, 6])` for any filtering pages
        apply_column, clear_column, _ = st.columns([1, 1, 6])
        with apply_column:
            applied = st.button("Apply Filters", use_container_width=True, key="drafts_recap_apply_filters")
        with clear_column:
            if st.button("Clear Filters", use_container_width=True, key="drafts_recap_clear_filters"):
                for base_key in DRAFTS_FILTER_WIDGET_BASE_KEYS:
                    st.session_state.pop(base_key, None)
                st.session_state.pop("drafts_applied_filters", None)
                st.session_state["drafts_filters_generation"] = generation + 1
                st.rerun()

        if applied:
            st.session_state["drafts_applied_filters"] = {
                "player_name": selected_player_name,
                "manager_id": selected_manager_id,
                "position": selected_position,
                "min_amount": min_amount,
                "max_amount": max_amount,
            }

        # Defaults to every pick shown (not "Set your filters above and
        # click Apply Filters." like the other filtering tabs) - Draft
        # Recap's own whole point is a browsable list of the season's
        # picks, so it should be populated on first load rather than
        # gated behind an Apply click.
        applied_filters = st.session_state.get(
            "drafts_applied_filters",
            {"player_name": None, "manager_id": "All", "position": "All", "min_amount": None, "max_amount": None},
        )

        picks = sorted(draft["picks"], key=lambda pick: pick["overall_pick"])
        if applied_filters["player_name"]:
            picks = [pick for pick in picks if pick["player_name"] == applied_filters["player_name"]]
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
        else:
            st.caption(f"Showing {len(picks)} of {len(draft['picks'])} picks.")

            # Cards only fill half the page width - at full width a
            # two-column [player | manager] row leaves an awkward amount
            # of empty space on a wide monitor for content this short.
            _, cards_column, _ = st.columns([1, 2, 1])
            with cards_column:
                for pick in picks:
                    _render_draft_pick_card(pick, draft_type, len(team_info), team_info, name_resolver, manager_color_map)

    with stats_tab:
        # Counted from the FULL draft (draft["picks"]), not whatever the
        # Selections tab's own filters currently have applied - "number
        # of {position}s in this year's draft" is a fact about the draft
        # itself.
        position_counts = {position: sum(1 for pick in draft["picks"] if pick["position"] == position) for position in BENCH_POSITION_ORDER}
        # st.metric's own label doesn't support unsafe_allow_html, so the
        # position pill is a separate st.markdown right above a metric
        # whose own label is now just "Drafted" - the pill is what
        # identifies which position each number belongs to.
        position_metric_columns = st.columns(len(BENCH_POSITION_ORDER))
        for position_metric_column, position in zip(position_metric_columns, BENCH_POSITION_ORDER):
            position_background_color = BENCH_POSITION_COLOR.get(position, COLOR_TABLE_ROSTER)
            position_text_color = contrasting_text_color(position_background_color)
            with position_metric_column:
                st.markdown(
                    f"<span style='background-color:{position_background_color}; color:{position_text_color}; padding:2px 8px; border-radius:6px; font-weight:600;'>{position}</span>",
                    unsafe_allow_html=True,
                )
                st.metric("Drafted", position_counts[position], help=f"The number of {position}s in this year's draft.")

        if draft_type == "auction":
            # Skew computed separately PER POSITION GROUP - a QB-only
            # skew can read very differently than the overall skew below
            # (e.g. a position with a few $50+ studs and a long $1 tail
            # skews harder than one where everyone landed mid-range).
            skew_help = "Right skewness of auction price selections. A higher number indicates extreme price selection and greater dependence on $1 picks. Fantasy range ~1-3"
            position_skew_columns = st.columns(len(BENCH_POSITION_ORDER))
            for position_skew_column, position in zip(position_skew_columns, BENCH_POSITION_ORDER):
                position_priced_picks = [pick for pick in draft["picks"] if pick["position"] == position and pick.get("auction_amount") is not None]
                position_skew = pd.Series([pick["auction_amount"] for pick in position_priced_picks]).skew() if len(position_priced_picks) >= 3 else None
                position_skew_column.metric(f"{position} Price Skew", f"{position_skew:.2f}" if position_skew is not None else "—", help=skew_help)

            # Same trio as Manager Recap's own "Auction Metrics" (see
            # _render_manager_recap_tab), just aggregated across the
            # WHOLE draft (every manager combined) instead of one
            # manager's own picks.
            total_spent = sum(pick["auction_amount"] for pick in draft["picks"] if pick.get("auction_amount") is not None)
            total_remaining_budget = len(team_info) * AUCTION_BUDGET - total_spent
            total_one_dollar_pick_count = sum(1 for pick in draft["picks"] if pick.get("auction_amount") == 1)
            all_priced_picks = [pick for pick in draft["picks"] if pick.get("auction_amount") is not None]

            remaining_column, one_dollar_column, skew_column, _ = st.columns(4)
            remaining_column.metric("Total Remaining Salary Cap", f"${total_remaining_budget}", help="Remaining $ budget once all selections were made.")
            one_dollar_column.metric("Total $1 Picks", total_one_dollar_pick_count, help="The number of $1 picks made.")

            # Fisher-Pearson (bias-corrected) skewness - pandas'
            # Series.skew() needs at least 3 points to be defined.
            overall_auction_price_skew = pd.Series([pick["auction_amount"] for pick in all_priced_picks]).skew() if len(all_priced_picks) >= 3 else None
            skew_column.metric(
                "Overall Auction Price Skew",
                f"{overall_auction_price_skew:.2f}" if overall_auction_price_skew is not None else "—",
                help=skew_help,
            )

        if draft_type == "auction":
            # $5-wide bins starting at 1 (1-5, 6-10, ...), not 0-4/5-9.
            _render_pick_distribution_chart(
                draft["picks"],
                value_fn=lambda pick: pick.get("auction_amount"),  # None (keepers) excluded - no real bid ever happened, see load_draft's docstring
                bucket_size=5,
                bucket_label_fn=lambda bucket_start, bucket_size: f"${bucket_start}-{bucket_start + bucket_size - 1}",
                subheader="Auction Price Distribution",
                xaxis_title="Auction Price",
                widget_key="drafts_stats_auction_price_position",
                empty_message="No auction picks match this filter.",
            )
        elif draft_type == "snake":
            # Bucket size = that season's own team count, so each bucket
            # is exactly one real snake round - "Round 1", "Round 2", ...
            # not an arbitrary price-style range label.
            num_teams = len(team_info)
            _render_pick_distribution_chart(
                draft["picks"],
                value_fn=lambda pick: pick["overall_pick"],
                bucket_size=num_teams,
                bucket_label_fn=lambda bucket_start, bucket_size: f"Round {((bucket_start - 1) // bucket_size) + 1}",
                subheader="Draft Position Distribution",
                xaxis_title="Round",
                widget_key="drafts_stats_pick_position",
                empty_message="No picks match this filter.",
                reverse_buckets=True,
            )


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
                        # Pick is a STRING here (not overall_pick's real
                        # int) - keeping the whole column string-typed
                        # avoids the pandas/pyarrow int64-vs-NaN dance
                        # entirely (a mixed int/None column upcasts to
                        # float64, which either breaks pyarrow serialization
                        # outright or - even once "fixed" - still needs a
                        # Styler.format() call that st.dataframe doesn't
                        # reliably honor for text formatting, rendering
                        # the total row's blank as literal "None"/"nan").
                        # A plain "" string sidesteps all of that.
                        "Pick": str(pick["overall_pick"]),
                        **({"Auction Value": f"${pick['auction_amount']:.0f}" if pick.get("auction_amount") is not None else "—"} if draft_type == "auction" else {}),
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


def _render_entire_player_analysis_chart(picks_by_player: dict[str, list[dict]], selected_player: str | None) -> None:
    """Every player's own Pick-by-year line, all at once - only Pick (no
    Auction Price/y2, "only picks" per the request), lines only (no
    markers), the searched player highlighted in
    COLOR_PERCENTILE_SELECTED_PLAYER, everyone else who shares that same
    position in COLOR_PERCENTILE_OTHER_PLAYERS - other positions are
    excluded entirely, not just dimmed, since a WR's pick history isn't a
    meaningful comparison for a QB. No click interactivity - just the
    selected player against everyone else at that position."""
    if not selected_player:
        st.info("Search for a player above to compare them against others at their position.")
        return

    entire_figure = go.Figure()

    selected_position = None
    if selected_player and selected_player in picks_by_player:
        selected_picks = sorted(picks_by_player[selected_player], key=lambda pick: pick["season"])
        selected_position = selected_picks[-1]["position"]
        entire_figure.add_trace(
            go.Scatter(
                x=[pick["season"] for pick in selected_picks],
                y=[pick["overall_pick"] for pick in selected_picks],
                name=selected_player,
                mode="lines+markers",
                line={"color": COLOR_PERCENTILE_SELECTED_PLAYER, "width": CHART_LINE_AUCTION_WIDTH},
                marker={"color": COLOR_PERCENTILE_SELECTED_PLAYER, "size": SCATTER_PLOT_DRAFT_MARKER_SIZE},
                legendgroup="selected",
                hovertemplate=f"<b>%{{x}}</b><br>{selected_player}<br>Pick: %{{y}}<extra></extra>",
            )
        )

    other_players = [player for player in picks_by_player if player != selected_player and (selected_position is None or picks_by_player[player][-1]["position"] == selected_position)]
    other_legend_shown = False
    for player in other_players:
        player_picks = sorted(picks_by_player[player], key=lambda pick: pick["season"])
        entire_figure.add_trace(
            go.Scatter(
                x=[pick["season"] for pick in player_picks],
                y=[pick["overall_pick"] for pick in player_picks],
                name=f"Other {selected_position}",
                mode="lines",
                line={"color": COLOR_PERCENTILE_OTHER_PLAYERS, "width": CHART_LINE_OTHER_WIDTH},
                legendgroup="other",
                showlegend=not other_legend_shown,
                hovertemplate=f"<b>%{{x}}</b><br>{player}<br>Pick: %{{y}}<extra></extra>",
            )
        )
        other_legend_shown = True

    entire_figure.update_layout(
        title=f"Draft History - All {selected_position}",
        xaxis={"title": "Year", "dtick": 1},
        yaxis={"title": "Pick", "range": [165, -5], "tickvals": [1, 20, 40, 60, 80, 100, 120, 140, 160]},
        legend={"orientation": "h", "y": 1.1, "yanchor": "bottom", "x": 0.5, "xanchor": "center"},
        margin={"t": 70, "l": 60, "r": 20, "b": 50},
    )
    st.plotly_chart(entire_figure, width="stretch")


def _render_player_analysis_individual_tab(picks_by_player: dict[str, list[dict]], selected_player: str | None) -> None:
    if not selected_player:
        st.info("Search for a player above to see their draft history.")
        return

    player_picks = sorted(picks_by_player[selected_player], key=lambda pick: pick["season"])

    # A "1st round" selection is either an actual Round 1 pick in a snake
    # draft, OR a keeper in an auction draft (auction_amount null - see
    # load_draft's docstring) - a keeper is set before the live auction
    # even starts, occupying what's effectively that team's top pick, so
    # it's counted here the same as a real Round 1 selection.
    first_round_count = sum(1 for pick in player_picks if (pick["draft_type"] == "snake" and pick["num_teams"] and ((pick["overall_pick"] - 1) // pick["num_teams"]) + 1 == 1) or (pick["draft_type"] == "auction" and pick["auction_amount"] is None))
    years_drafted_count = len({pick["season"] for pick in player_picks})
    keeper_pick_count = sum(1 for pick in player_picks if pick["draft_type"] == "auction" and pick["auction_amount"] is None)

    metric_column, _ = st.columns(2)
    with metric_column:
        first_round_metric_column, years_drafted_metric_column, keeper_metric_column = st.columns(3)
        first_round_metric_column.metric("1st Round Selections", first_round_count, help="Number of 1st round selections.")
        years_drafted_metric_column.metric("Years Drafted", years_drafted_count, help="Number of years drafted.")
        keeper_metric_column.metric("Keeper Pick", keeper_pick_count, help="Number of years selected as keeper.")

    # Pick covers EVERY year regardless of draft_type (a real overall_pick
    # exists no matter how that year's draft ran) - Auction Price is still
    # only for auction seasons that had a real bid, and a separate red-dot
    # Keeper series marks auction seasons with NO real bid (auction_amount
    # null - see load_draft's docstring); a keeper's own point already
    # sits on the Pick line too, the red dot just flags it.
    auction_picks = [pick for pick in player_picks if pick["draft_type"] == "auction" and pick["auction_amount"] is not None]
    keeper_picks = [pick for pick in player_picks if pick["draft_type"] == "auction" and pick["auction_amount"] is None]

    line_figure = go.Figure()
    line_figure.add_trace(
        go.Scatter(
            x=[pick["season"] for pick in player_picks],
            y=[pick["overall_pick"] for pick in player_picks],
            name="Pick",
            mode="lines+markers",
            line={"color": COLOR_CHART_PICK, "width": CHART_LINE_AUCTION_WIDTH},
            marker={"color": COLOR_CHART_PICK, "size": SCATTER_PLOT_DRAFT_MARKER_SIZE},
            yaxis="y",
            hovertemplate="<b>%{x}</b><br>Pick: %{y}<extra></extra>",
        )
    )
    if auction_picks:
        line_figure.add_trace(
            go.Scatter(
                x=[pick["season"] for pick in auction_picks],
                y=[pick["auction_amount"] for pick in auction_picks],
                name="Auction Price",
                mode="markers",
                marker={"color": COLOR_CHART_AUCTION, "size": SCATTER_PLOT_DRAFT_MARKER_SIZE},
                yaxis="y2",
                hovertemplate="<b>%{x}</b><br>Auction Price: $%{y}<extra></extra>",
            )
        )
    if keeper_picks:
        line_figure.add_trace(
            go.Scatter(
                x=[pick["season"] for pick in keeper_picks],
                y=[pick["overall_pick"] for pick in keeper_picks],
                name="Keeper",
                mode="markers",
                marker={"color": COLOR_POINTS_NEGATIVE, "size": SCATTER_PLOT_DRAFT_MARKER_SIZE},
                yaxis="y",
                hovertemplate="<b>%{x}</b><br>Pick: %{y} (Keeper)<extra></extra>",
            )
        )

    line_figure.update_layout(
        title="Draft History",
        xaxis={"title": "Year", "dtick": 1},
        # range=[160, 1] (not autorange="reversed") - Plotly maps
        # range[0] to the axis's bottom and range[1] to its top
        # regardless of numeric order, so this fixes Pick 1 at the top
        # and Pick 160 at the bottom on a set scale (rather than a scale
        # that rescales to whatever this one player's own picks span).
        # Padded 5 past each end (165/-5, not 160/1) - a marker sitting
        # exactly ON the range boundary (e.g. an actual Pick 160) renders
        # half-clipped by the plot's own edge otherwise.
        yaxis={"title": "Pick", "range": [165, -5], "tickvals": [1, 20, 40, 60, 80, 100, 120, 140, 160]},
        # Padded 5 past the bottom end (-5, not 1) so a marker sitting
        # exactly at $1 doesn't render half-clipped by the plot's own
        # edge, same reasoning as Pick's padding above - $100 stays
        # unpadded at the top.
        # Explicit tickvals starting at 1 (not Plotly's own automatic
        # "nice round number" ticks, which would include a $0 label - not
        # a real possible auction price, the minimum bid is $1).
        yaxis2={
            "title": "Auction Price ($)",
            "overlaying": "y",
            "side": "right",
            "range": [-5, 100],
            "tickvals": [1, 20, 40, 60, 80, 100],
            "showgrid": False,
            "showline": False,
            "zeroline": False,
        },
        # Plotly's default legend position (top-right, inside the plot
        # area) sits right on top of yaxis2's title/ticks, which also
        # live on the right - moved above the plot as a horizontal strip
        # instead, clear of both y-axes.
        legend={"orientation": "h", "y": 1.15, "yanchor": "bottom", "x": 0.5, "xanchor": "center"},
        margin={"t": 80, "l": 60, "r": 60, "b": 50},
    )
    st.plotly_chart(line_figure, width="stretch")

    _render_fantasy_value_section(selected_player, player_picks)


FANTASY_VALUE_STAT_FIELDS = {
    ("Total Fantasy Points", False): "total_fantasy_points",
    ("Total Fantasy Points", True): "fantasy_value_per_season",
    ("Per Game Fantasy Points", False): "fantasy_points_per_game",
    ("Per Game Fantasy Points", True): "fantasy_value_per_game",
    ("Per Game Fantasy Points Box Plots", False): "fantasy_points_per_game",
    ("Per Game Fantasy Points Box Plots", True): "fantasy_value_per_game",
}


def _render_fantasy_value_section(selected_player: str, player_picks: list[dict]) -> None:
    """Reads code/stats-aggregation/generate_player_fantasy_value_metrics.py's
    precomputed archive/player_fantasy_value_metrics.json (run weekly,
    not recomputed here) rather than deriving fantasy value from
    player_ownership.json/draft.json directly - that script already
    resolves per-season cost (real $ for auction, a pseudo-cost for
    snake, KEEPER_DEFAULT_COST for keepers) once for every drafted
    player, not just the one being viewed here."""
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
        key="drafts_player_analysis_fantasy_stat",
    )
    selected_adjustment = adjustment_column.selectbox(
        "Adjustment",
        ["Fantasy Points", "Adjusted Fantasy Points"],
        key="drafts_player_analysis_fantasy_adjustment",
        help="Adjusted fantasy points try to take into account draft position and cost to assess fantasy value. Fantasy value is fantasy points divided by cost. Auction draft cost (1) auction price or (2) $50 if keeper. Snake draft cost (3) number of players - pick.",
    )
    is_box_plot = selected_stat == "Per Game Fantasy Points Box Plots"
    # Box Plots ONLY work for the searched player individually (one box
    # per season of THEIR OWN weekly points) - "The Field" has no
    # meaning here. Forced back to "Individual" in session_state (not
    # just disabled in the UI) so switching Stat to Box Plots can't leave
    # a stale "The Field" selection sitting underneath the disabled
    # widget, which would still be what gets read below.
    if is_box_plot:
        st.session_state["drafts_player_analysis_fantasy_view"] = "Individual"
    selected_view = view_column.selectbox(
        "View",
        ["Individual", "The Field"],
        disabled=is_box_plot,
        help="View detailed individual stats or stats vs all players in same position." if is_box_plot else None,
        key="drafts_player_analysis_fantasy_view",
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
                marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": COLOR_PERCENTILE_OTHER_PLAYERS, "opacity": 0.5},
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
                marker={"size": SCATTER_PLOT_MARKER_SIZE, "color": COLOR_PERCENTILE_SELECTED_PLAYER, "line": {"width": 1, "color": COLOR_CHART_SCATTER_MARKER_OUTLINE}},
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
            marker={"color": COLOR_CHART_PICK, "size": SCATTER_PLOT_MARKER_SIZE},
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


def _render_player_analysis_tab() -> None:
    # Aggregated once across every season - "this will apply for all
    # archive" - not scoped to the season selected at the top of the page.
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

    if not picks_by_player:
        st.info("No draft data recorded in the archive yet.")
        return

    # Search sits above the tab layout - both tabs react to the same
    # selected player, no separate Apply/Clear step needed (the tabs
    # themselves are the navigation, unlike the versioned-key filter rows
    # elsewhere in this page).
    selected_player = st.selectbox(
        "Search for a player",
        sorted(picks_by_player),
        index=None,
        placeholder="Type a player's name...",
        key="drafts_player_analysis_player",
    )

    individual_tab, vs_position_tab = st.tabs(["Individual", "Vs Position"])

    with individual_tab:
        _render_player_analysis_individual_tab(picks_by_player, selected_player)

    with vs_position_tab:
        _render_entire_player_analysis_chart(picks_by_player, selected_player)


def render_drafts_page() -> None:
    seasons = discover_seasons()
    if not seasons:
        st.info("No seasons aggregated yet.")
        return

    # Single mandatory season (same pattern as pages_seasons.py) -
    # defaulting to the most recent one.
    selected_season = st.selectbox("Select Season", seasons, index=len(seasons) - 1, key="drafts_season")

    draft_recap_tab, manager_recap_tab, keepers_tab, player_analysis_tab = st.tabs(["Draft Recap", "Manager Recap", "Keepers", "Player Analysis"])

    with draft_recap_tab:
        _render_draft_recap_tab(selected_season)

    with manager_recap_tab:
        _render_manager_recap_tab(selected_season)

    with keepers_tab:
        _render_keepers_tab()

    with player_analysis_tab:
        _render_player_analysis_tab()
