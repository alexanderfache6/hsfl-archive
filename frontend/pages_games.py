"""Games tab - filter matchups by season/week/manager/matchup-type and
page through them as box-score cards. Manager 1 is the "main" manager
the aggregate win/loss stat is computed against: with only Manager 1
set, that's their record across every opponent; with both set, it's
their head-to-head record. Filtering is gated behind an explicit "Apply
Filters" button (st.form) so widget changes don't re-scan matchup files
on every rerun - except Manager 1, which lives outside the form since
Manager 2's options depend on it and need an immediate rerun to update.
See execution-plan.md Phase G.
"""

import plotly.graph_objects as go
import streamlit as st

from data_loader import (
    FLEX_ELIGIBLE_POSITIONS,
    build_manager_color_map,
    build_manager_name_resolver,
    compute_optimal_lineup,
    contrasting_text_color,
    discover_seasons,
    load_all_time_manager_stats,
    load_matchups,
    resolve_manager_name,
)

MAX_WEEK = 17

# Same neutral gray used for the "Bench" segment in the Players tab's
# starts-vs-bench chart - reused here for a losing/negative-diff bar so
# the loss color is consistent with the rest of the app.
BENCH_COLOR = "#B0B0B0"

MATCHUP_TYPE_OPTIONS = ["all", "regular", "championship", "consolation"]
MATCHUP_TYPE_LABELS = {
    "all": "All",
    "regular": "Regular Season",
    "championship": "Championship Bracket",
    "consolation": "Consolation Bracket",
}


def _manager_options(name_resolver: dict[str, str]) -> list[tuple[str, str]]:
    """[(manager_id, display_name), ...] sorted by display name, for the
    Team 1 / Team 2 selectboxes."""
    manager_stats = load_all_time_manager_stats()
    options = [(manager["manager_id"], resolve_manager_name(manager["manager_id"], name_resolver)) for manager in manager_stats["managers"]]
    options.sort(key=lambda option: option[1])
    return options


def _seasons_played_by_manager() -> dict[str, list[int]]:
    manager_stats = load_all_time_manager_stats()
    return {manager["manager_id"]: manager["seasons_played"] for manager in manager_stats["managers"]}


FILTER_WIDGET_BASE_KEYS = ("games_team1_manager_id", "games_season", "games_week", "games_team2_manager_id", "games_matchup_type")


def _render_filters(name_resolver: dict[str, str]) -> dict | None:
    manager_options = _manager_options(name_resolver)
    manager_labels = {manager_id: name for manager_id, name in manager_options}

    # Each filter widget's ACTUAL key is versioned (base name + a
    # generation counter) rather than fixed - Clear Filters bumps the
    # counter instead of just deleting session_state, which forces
    # Streamlit to mount brand-new widget instances instead of reusing
    # the same DOM/component identity. Deleting session_state + rerun
    # alone left the visible dropdowns showing their old selections in
    # some browsers even though the underlying value was cleared, since
    # the widget component itself was never actually remounted. The
    # fixed base-name keys (games_team1_manager_id, games_season, etc)
    # stay as the canonical mirror other pages (e.g. pages_history.py's
    # "View Game" record links) read/write to pre-fill this page.
    generation = st.session_state.setdefault("games_filters_generation", 0)

    def versioned_key(base_key: str) -> str:
        return f"{base_key}_gen{generation}"

    # Seed each versioned widget's value from the canonical mirror, but
    # ONLY on that widget's first mount within this generation - syncing
    # unconditionally on every rerun would clobber the value Streamlit
    # just wrote from the user's own latest interaction (which lands in
    # session_state[versioned_key] BEFORE this function runs) with the
    # stale canonical value from the previous run's mirror. External
    # pre-fills (pages_history.py's "View Game" links) work correctly
    # despite this because they also bump games_filters_generation, so
    # they always land on a genuinely new, not-yet-mounted widget key.
    for base_key in FILTER_WIDGET_BASE_KEYS:
        widget_key = versioned_key(base_key)
        if widget_key not in st.session_state and base_key in st.session_state:
            st.session_state[widget_key] = st.session_state[base_key]

    # All five filters share one row now - none of them are wrapped in
    # st.form anymore. Manager 1 always needed to live outside a form (it
    # must rerun immediately so Manager 2's option list/disabled state
    # updates right away), and matchup filtering is now a cheap in-memory
    # operation over a single cached full-archive list (see
    # _load_all_matchups_enriched in data_loader.py) rather than a disk
    # scan, so there's no performance reason left to defer the other
    # widgets' reruns behind a form submit either. "Apply"/"Clear" are
    # now plain st.button widgets (form_submit_button can't sit next to a
    # regular button anyway) that read/reset the current widget values
    # directly.
    team1_col, season_col, week_col, team2_col, type_col = st.columns(5)
    with team1_col:
        team1_manager_id = st.selectbox(
            "Manager 1",
            [manager_id for manager_id, _ in manager_options],
            format_func=lambda mid: manager_labels[mid],
            index=None,
            placeholder="Any",
            key=versioned_key("games_team1_manager_id"),
        )
    team2_options = [manager_id for manager_id, _ in manager_options if manager_id != team1_manager_id]
    # Once Manager 1 is picked, only offer seasons they actually played -
    # a season they weren't in the league for can never have a matchup
    # for them anyway.
    season_options = _seasons_played_by_manager().get(team1_manager_id, discover_seasons()) if team1_manager_id else discover_seasons()
    # A previously-picked season can fall outside the new Manager 1's
    # season_options (e.g. Season=2015 picked before Manager 1 was set,
    # then a Manager 1 who never played 2015 gets chosen) - Streamlit
    # errors if a selectbox's existing session_state value isn't in its
    # options list, so clear it first rather than letting that happen.
    season_widget_key = versioned_key("games_season")
    if st.session_state.get(season_widget_key) not in season_options and st.session_state.get(season_widget_key) is not None:
        st.session_state[season_widget_key] = None
    with season_col:
        season = st.selectbox("Season", season_options, index=None, placeholder="Any", key=season_widget_key)
    with week_col:
        week = st.selectbox("Week", list(range(1, MAX_WEEK + 1)), index=None, placeholder="Any", key=versioned_key("games_week"))
    with team2_col:
        team2_manager_id = st.selectbox(
            "Manager 2",
            team2_options,
            format_func=lambda mid: manager_labels[mid],
            index=None,
            placeholder="Any",
            disabled=team1_manager_id is None,
            help="Select Manager 1 first" if team1_manager_id is None else None,
            key=versioned_key("games_team2_manager_id"),
        )
    with type_col:
        matchup_type = st.selectbox(
            "Matchup Type",
            MATCHUP_TYPE_OPTIONS,
            format_func=lambda value: MATCHUP_TYPE_LABELS[value],
            index=0,
            key=versioned_key("games_matchup_type"),
        )

    st.session_state["games_team1_manager_id"] = team1_manager_id
    st.session_state["games_season"] = season
    st.session_state["games_week"] = week
    st.session_state["games_team2_manager_id"] = team2_manager_id
    st.session_state["games_matchup_type"] = matchup_type

    apply_col, clear_col, _ = st.columns([1, 1, 3])
    with apply_col:
        applied = st.button(
            "Apply Filters",
            disabled=team1_manager_id is None,
            help="Select Manager 1 first" if team1_manager_id is None else None,
        )
    with clear_col:
        if st.button("Clear Filters"):
            for base_key in FILTER_WIDGET_BASE_KEYS:
                st.session_state.pop(base_key, None)
            st.session_state.pop("games_applied_filters", None)
            st.session_state["games_filters_generation"] = generation + 1
            st.rerun()

    if applied:
        st.session_state["games_applied_filters"] = {
            "season": season,
            "week": week,
            "team1_manager_id": team1_manager_id,
            "team2_manager_id": team2_manager_id if team1_manager_id else None,
            "matchup_type": matchup_type,
        }

    return st.session_state.get("games_applied_filters")


def _render_filter_description(applied_filters: dict, name_resolver: dict[str, str]) -> None:
    """A plain-language recap of exactly which filters are in effect,
    e.g. "Season: 2013 · Week: 11 · Manager 1: Alex F vs Manager 2:
    Ashwin · Championship Bracket" - each piece is left out entirely
    when that filter wasn't set, rather than showing an "Any" placeholder."""
    parts = []
    if applied_filters["season"]:
        parts.append(f"Season: {applied_filters['season']}")
    if applied_filters["week"]:
        parts.append(f"Week: {applied_filters['week']}")

    team1_manager_id = applied_filters["team1_manager_id"]
    team2_manager_id = applied_filters["team2_manager_id"]
    if team1_manager_id and team2_manager_id:
        parts.append(f"Manager 1 ({resolve_manager_name(team1_manager_id, name_resolver)}) vs Manager 2 ({resolve_manager_name(team2_manager_id, name_resolver)})")
    elif team1_manager_id:
        parts.append(f"Manager 1 ({resolve_manager_name(team1_manager_id, name_resolver)})")

    if applied_filters["matchup_type"] and applied_filters["matchup_type"] != "all":
        parts.append(MATCHUP_TYPE_LABELS[applied_filters["matchup_type"]])

    st.subheader(" · ".join(parts) if parts else "All matchups")


def _render_aggregate(matchups: list[dict], team1_manager_id: str | None) -> None:
    if not team1_manager_id:
        st.metric("Matchups", len(matchups))
        return

    wins = losses = ties = 0
    points_for = points_against = 0.0
    for matchup in matchups:
        home, away = matchup["home"], matchup["away"]
        team1_side, other_side = (home, away) if home["manager_id"] == team1_manager_id else (away, home)
        points_for += team1_side["score"]
        points_against += other_side["score"]
        if team1_side["score"] > other_side["score"]:
            wins += 1
        elif team1_side["score"] < other_side["score"]:
            losses += 1
        else:
            ties += 1

    win_pct = wins / len(matchups) if matchups else 0.0

    total_column, win_column, loss_column, tie_column, win_pct_column, points_for_column, points_against_column = st.columns(7)
    total_column.metric("Matchups", len(matchups))
    win_column.metric("Wins", wins)
    loss_column.metric("Losses", losses)
    tie_column.metric("Ties", ties)
    win_pct_column.metric("Win %", f"{win_pct:.1%}")
    points_for_column.metric("Points For", f"{points_for:.2f}")
    points_against_column.metric("Points Against", f"{points_against:.2f}")


def _render_diff_chart(matchups: list[dict], team1_manager_id: str | None, season_filter: int | None, name_resolver: dict[str, str], manager_color_map: dict[str, str]) -> None:
    """One bar per matchup: Manager 1's point differential (their score
    minus the opponent's). Only meaningful relative to Manager 1, so this
    is skipped entirely when Manager 1 isn't set. Win bars use Manager
    1's own color; loss/tie bars use the same neutral gray as the Bench
    segment elsewhere in the app."""
    if not team1_manager_id:
        return

    manager1_name = resolve_manager_name(team1_manager_id, name_resolver)
    manager1_color = manager_color_map.get(team1_manager_id, "#4C78A8")

    x_labels, diffs, colors, hover_text = [], [], [], []
    for matchup in matchups:
        home, away = matchup["home"], matchup["away"]
        team1_side, team2_side = (home, away) if home["manager_id"] == team1_manager_id else (away, home)
        diff = team1_side["score"] - team2_side["score"]
        manager2_name = resolve_manager_name(team2_side["manager_id"], name_resolver, team2_side.get("display_name", ""))

        x_labels.append(f"{matchup['season']} Wk{matchup['week']}")
        diffs.append(diff)
        colors.append(manager1_color if diff > 0 else BENCH_COLOR)
        hover_text.append(
            f"{matchup['season']} · Week {matchup['week']}<br>{manager1_name} vs {manager2_name}"
            f"<br>{team1_side['team_name']} vs {team2_side['team_name']}"
            f"<br>{team1_side['score']:g} vs {team2_side['score']:g}<br>Diff: {diff:+.2f}"
        )

    # Numeric x positions (0, 1, 2, ...) with the season/week strings
    # supplied as tick labels instead - a true category axis's mapping
    # from category to integer position isn't reliably addressable by a
    # shape/vline's numeric x, but an explicitly numeric axis is.
    x_positions = list(range(len(matchups)))

    if not season_filter:
        # All years together: one centered, horizontal tick label per
        # season (its year) rather than a per-week label - positioned at
        # the average x of that season's bars.
        positions_by_season: dict[int, list[int]] = {}
        for index, matchup in enumerate(matchups):
            positions_by_season.setdefault(matchup["season"], []).append(index)
        tick_positions = [sum(positions) / len(positions) for positions in positions_by_season.values()]
        tick_text = [str(season) for season in positions_by_season]
        tick_angle = 0
    else:
        # Single season: keep the per-week labels, thinned to at most
        # MAX_TICK_LABELS so they don't overlap.
        MAX_TICK_LABELS = 20
        tick_step = max(1, -(-len(x_positions) // MAX_TICK_LABELS))
        tick_positions = x_positions[::tick_step]
        tick_text = x_labels[::tick_step]
        tick_angle = 0

    figure = go.Figure(
        go.Bar(x=x_positions, y=diffs, marker_color=colors, customdata=hover_text, hovertemplate="%{customdata}<extra></extra>")
    )
    figure.update_layout(
        title="Point Differential",
        xaxis=dict(title="Season / Week", tickangle=tick_angle, tickmode="array", tickvals=tick_positions, ticktext=tick_text),
        yaxis_title="Point Differential",
        margin=dict(t=40, b=0, l=0, r=0),
    )

    # With every season shown together (no Season filter), mark each
    # season boundary with a dashed vertical line at the midpoint between
    # the last bar of one season and the first bar of the next.
    if not season_filter:
        for index, matchup in enumerate(matchups):
            if index > 0 and matchup["season"] != matchups[index - 1]["season"]:
                figure.add_vline(x=index - 0.5, line_dash="dash", line_color="#888888")

    st.plotly_chart(figure, width="stretch")


ROSTER_CARD_COLOR = "#F0F0F0"

BENCH_POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]

# DEF entries carry an empty "nfl_team" in the archived data - it was
# never captured during parsing (only individual players' teams were),
# so this display-only lookup fills it back in from the DEF's own
# player_name (e.g. "49ers") rather than requiring a full re-parse of
# every season just for this one field.
DEF_TEAM_ABBREVIATIONS = {
    "49ers": "SF", "Bears": "CHI", "Bengals": "CIN", "Bills": "BUF",
    "Broncos": "DEN", "Browns": "CLE", "Buccaneers": "TB", "Cardinals": "ARI",
    "Chargers": "LAC", "Chiefs": "KC", "Colts": "IND", "Commanders": "WAS",
    "Cowboys": "DAL", "Dolphins": "MIA", "Eagles": "PHI", "Falcons": "ATL",
    "Giants": "NYG", "Jaguars": "JAX", "Jets": "NYJ", "Lions": "DET",
    "Packers": "GB", "Panthers": "CAR", "Patriots": "NE", "Raiders": "LV",
    "Rams": "LAR", "Ravens": "BAL", "Redskins": "WAS", "Saints": "NO",
    "Seahawks": "SEA", "Steelers": "PIT", "Texans": "HOU", "Titans": "TEN",
    "Vikings": "MIN",
}


def _bench_sort_key(player: dict) -> int:
    # Any position not in the named order (e.g. IDP slots like "DB")
    # falls into a catch-all "RESERVE" bucket at the end.
    try:
        return BENCH_POSITION_ORDER.index(player["position"])
    except ValueError:
        return len(BENCH_POSITION_ORDER)


def _optimal_lineup_details(side: dict, year: int) -> dict:
    """{"gains": {player_id: +points}, "optimal_points": float} - gains
    covers bench players who belong in the optimal lineup
    (compute_optimal_lineup - the same formula behind
    best_coaching_season/worst_coaching_season); each gain is against the
    WEAKEST actual starter eligible for that same slot (same position, or
    RB/WR for FLEX) - not a full reconstruction of an exact multi-slot
    swap chain, which stays simpler and more directly explainable ("this
    bench player beats your worst eligible starter by X") at the cost of
    not always summing exactly to the aggregate coaching diff in rare
    multi-swap weeks. optimal_points is the true optimal lineup's total,
    for the bench table's summary row."""
    all_players = side["starters"] + side["bench"]
    optimal = compute_optimal_lineup(all_players, year)
    optimal_by_id = {p["player_id"]: p for p in optimal["optimal_starters"] if p.get("player_id")}
    actual_starter_ids = {p["player_id"] for p in side["starters"] if p.get("player_id")}

    gains: dict[str, float] = {}
    for bench_player in side["bench"]:
        player_id = bench_player.get("player_id")
        optimal_entry = optimal_by_id.get(player_id) if player_id else None
        if not player_id or optimal_entry is None or player_id in actual_starter_ids:
            continue

        slot = optimal_entry["optimal_slot"]
        eligible_positions = FLEX_ELIGIBLE_POSITIONS if slot == "FLEX" else {slot}
        displaced_candidates = [
            starter
            for starter in side["starters"]
            if starter.get("position") in eligible_positions and starter.get("player_id") not in optimal_by_id
        ]
        if not displaced_candidates:
            continue

        weakest_displaced = min(displaced_candidates, key=lambda starter: starter["points"])
        gains[player_id] = bench_player["points"] - weakest_displaced["points"]

    return {"gains": gains, "optimal_points": optimal["optimal_points"]}


def _render_roster_table(
    players: list[dict],
    sort_by_position: bool = False,
    optimal_gains: dict[str, float] | None = None,
    optimal_total_points: float | None = None,
    actual_total_points: float | None = None,
) -> None:
    if sort_by_position:
        players = sorted(players, key=_bench_sort_key)

    def _name_cell(player: dict) -> str:
        nfl_team = player["nfl_team"] or DEF_TEAM_ABBREVIATIONS.get(player["player_name"], "")
        return f"{player['player_name']} ({nfl_team})"

    def _gain_cell(player: dict) -> str:
        if optimal_gains is None:
            return ""
        gain = optimal_gains.get(player.get("player_id"))
        if gain is None:
            return "<td style='padding:3px 8px; text-align:right; color:#999999;'>—</td>"
        return f"<td style='padding:3px 8px; text-align:right; font-weight:600; color:#2E7D32;'>+{gain:.2f}</td>"

    rows_html = "".join(
        f"<tr><td style='padding:3px 8px; color:#666666;'>{player['position']}</td>"
        f"<td style='padding:3px 8px;'>{_name_cell(player)}</td>"
        f"<td style='padding:3px 8px; text-align:right; font-weight:600;'>{player['points']:.2f}</td>"
        f"{_gain_cell(player)}</tr>"
        for player in players
    )
    if optimal_total_points is not None:
        # colspan spans Position+Player so the label and the total line
        # up with the Points/±Pts columns like a normal totals row. The
        # trailing cell shows the total points the optimal lineup would
        # have added over the actual lineup's score, in the same green
        # "+" styling as each individual bench player's gain above it.
        if optimal_gains is not None and actual_total_points is not None:
            total_diff = optimal_total_points - actual_total_points
            trailing_cell = f"<td style='padding:3px 8px; text-align:right; font-weight:600; color:#2E7D32;'>+{total_diff:.2f}</td>"
        elif optimal_gains is not None:
            trailing_cell = "<td></td>"
        else:
            trailing_cell = ""
        column_count = 4 if optimal_gains is not None else 3
        # A visibly blank spacer row (not just the border-top above)
        # makes it unambiguous that "Optimal Lineup Total" is a separate
        # summary, not just the last bench player's row.
        rows_html += f"<tr><td colspan='{column_count}' style='padding:6px;'></td></tr>"
        rows_html += (
            "<tr style='border-top:1px solid #CCCCCC;'>"
            "<td colspan='2' style='padding:3px 8px; font-weight:600;'>Optimal Lineup Total</td>"
            f"<td style='padding:3px 8px; text-align:right; font-weight:600;'>{optimal_total_points:.2f}</td>"
            f"{trailing_cell}</tr>"
        )
    st.markdown(
        # border-collapse:collapse ignores border-radius entirely - the
        # radius only takes effect (on all 4 corners) with
        # border-collapse:separate + border-spacing:0 + overflow:hidden
        # directly on the <table>, which also lets the table carry its
        # own background rather than a separate wrapper div.
        f"<table style='width:100%; border-collapse:separate; border-spacing:0; border-radius:6px; "
        f"overflow:hidden; background-color:{ROSTER_CARD_COLOR}; font-size:0.85em; color:#333333;'>"
        f"{rows_html}</table>",
        unsafe_allow_html=True,
    )


def _render_matchup_card(
    matchup: dict, team1_manager_id: str | None, name_resolver: dict[str, str], manager_color_map: dict[str, str], show_optimal: bool
) -> None:
    home, away = matchup["home"], matchup["away"]
    # Team 1's side always renders on the left when Team 1 is filtered,
    # regardless of whether they were actually home or away in this
    # matchup; falls back to home-left/away-right when Team 1 isn't set.
    left, right = (home, away) if (not team1_manager_id or home["manager_id"] == team1_manager_id) else (away, home)

    with st.container(border=True):
        st.caption(f"{matchup['season']} · Week {matchup['week']} · {MATCHUP_TYPE_LABELS[matchup['matchup_type']]}")
        left_column, right_column = st.columns(2)

        for column, side, is_left_side in ((left_column, left, True), (right_column, right, False)):
            with column:
                display_name = resolve_manager_name(side["manager_id"], name_resolver, side.get("display_name", ""))
                background_color = manager_color_map.get(side["manager_id"], "#CCCCCC")
                text_color = contrasting_text_color(background_color)
                # Computed once per side and reused for both the header
                # score and the bench table below, rather than solving
                # the optimal lineup twice.
                optimal_details = _optimal_lineup_details(side, matchup["season"]) if show_optimal else None
                optimal_score_html = (
                    f" <span style='font-size:0.5em; font-weight:400;'>({optimal_details['optimal_points']:.2f})</span>"
                    if optimal_details
                    else ""
                )
                # Name/team block aligns to its own side of the card; the
                # score joins the same colored block but anchors to the
                # OPPOSITE side - flex-direction reverses which child (name
                # vs score) lands on which edge while keeping the name
                # block's own text left/right-aligned within itself.
                name_align = "left" if is_left_side else "right"
                flex_direction = "row" if is_left_side else "row-reverse"
                st.markdown(
                    f"<div style='background-color:{background_color}; color:{text_color}; padding:6px 10px; "
                    f"border-radius:6px; display:flex; flex-direction:{flex_direction}; justify-content:space-between; "
                    f"align-items:center;'>"
                    f"<div style='text-align:{name_align};'><span style='font-weight:600; font-size:1em;'>{display_name}</span><br>"
                    f"<span style='font-weight:400; font-size:0.85em;'>{side['team_name']}</span></div>"
                    f"<div style='font-weight:600; font-size:2em;'>{side['score']:.2f}{optimal_score_html}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
                _render_roster_table(side["starters"])
                with st.expander(f"Bench ({len(side['bench'])})"):
                    _render_roster_table(
                        side["bench"],
                        sort_by_position=True,
                        optimal_gains=optimal_details["gains"] if optimal_details else None,
                        optimal_total_points=optimal_details["optimal_points"] if optimal_details else None,
                        actual_total_points=side["score"],
                    )


def render_games_page() -> None:
    name_resolver = build_manager_name_resolver()
    manager_color_map = build_manager_color_map()

    applied_filters = _render_filters(name_resolver)
    if applied_filters is None:
        st.info("Set your filters above and click Apply Filters.")
        return

    matchups = load_matchups(
        applied_filters["season"],
        applied_filters["week"],
        applied_filters["team1_manager_id"],
        applied_filters["team2_manager_id"],
        applied_filters["matchup_type"],
    )

    if not matchups:
        st.info("No matchups found for these filters.")
        return

    _render_filter_description(applied_filters, name_resolver)
    st.divider()
    _render_aggregate(matchups, applied_filters["team1_manager_id"])
    st.divider()
    _render_diff_chart(matchups, applied_filters["team1_manager_id"], applied_filters["season"], name_resolver, manager_color_map)
    st.divider()

    show_optimal = st.toggle(
        "Show Optimal Lineup",
        key="games_show_optimal",
        help="Adds a +Pts column to each bench table for players who belong in that week's optimal lineup - "
        "the gain shown is against the weakest actual starter eligible for that slot.",
    )

    for matchup in matchups:
        # Cards capped at 75% width: a 1/6/1-ratio column layout, middle
        # column centered and 6/8 = 75% wide.
        _, card_column, _ = st.columns([1, 6, 1])
        with card_column:
            _render_matchup_card(matchup, applied_filters["team1_manager_id"], name_resolver, manager_color_map, show_optimal)
