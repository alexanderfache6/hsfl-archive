from datetime import datetime

import plotly.graph_objects as go
import streamlit as st
from colors import (
    COLOR_CHART_SCATTER_MARKER_OUTLINE,
    COLOR_CHART_STAT,
    COLOR_MANAGER_BACKUP,
    COLOR_PERCENTILE_OTHER_PLAYERS,
    COLOR_PERCENTILE_SELECTED_PLAYER,
    COLOR_PICK,
    COLOR_TABLE_ROSTER,
)
from constants import BENCH_POSITION_COLOR, CHART_LINE_WIDTH_LARGE, CHART_MARKER_SIZE_MEDIUM, MAX_YAXIS_TICKS, ORDINAL_WORDS
from data_loader import (
    FLEX_ELIGIBLE_POSITIONS,
    compute_optimal_lineup,
    contrasting_text_color,
    discover_seasons,
    load_draft,
    load_player_fantasy_value_metrics,
    load_player_ownership,
    load_starting_slot_counts,
    resolve_manager_name,
    team_id_to_manager_map,
)
from strings import SELECT_STAT_TO_VIEW


def manager_pill(manager_id: str, name_resolver: dict[str, str], manager_color_map: dict[str, str], label: str | None = None) -> str:
    name = resolve_manager_name(manager_id, name_resolver)
    text = f"{label} ({name})" if label else name
    background_color = manager_color_map.get(manager_id, COLOR_MANAGER_BACKUP)
    text_color = contrasting_text_color(background_color)
    return f"<span style='background-color:{background_color}; color:{text_color}; padding:2px 8px; border-radius:6px; font-weight:600; white-space:nowrap;'>{text}</span>"


def position_pill(position: str, margin_right: bool = False) -> str:
    background_color = BENCH_POSITION_COLOR.get(position, COLOR_TABLE_ROSTER)
    text_color = contrasting_text_color(background_color)
    margin = " margin-right:8px;" if margin_right else ""
    return f"<span style='background-color:{background_color}; color:{text_color}; padding:2px 8px; border-radius:6px; font-weight:600;{margin}'>{position}</span>"


def player_line(player_name: str, nfl_team: str | None, position: str | None = None, points: float | None = None, points_color: str | None = None, status_code: str | None = None, status_color: str | None = None) -> str:
    """[position pill] **name** (NFL team), with fantasy points (when
    given) right-aligned on the same line - the shared player line used
    on the Drafts selection cards and the Managers depth chart cards."""
    pill = position_pill(position, margin_right=True) if position else ""
    team_html = f" <span style='color:{COLOR_TABLE_ROSTER};'>({nfl_team})</span>" if nfl_team else ""
    status_html = f" <span style='font-size:0.75em; font-weight:700; color:{status_color};'>{status_code}</span>" if status_code else ""
    left_html = f"{pill}<span style='font-weight:600;'>{player_name}</span>{team_html}{status_html}"
    if points is None:
        return left_html
    color_style = f" color:{points_color};" if points_color else ""
    # <span>s (not <div>s) so Streamlit still wraps the line in its normal <p>, keeping the card's usual padding.
    return f"<span style='display:flex; justify-content:space-between; align-items:center; gap:8px;'><span>{left_html}</span><span style='font-weight:600;{color_style}'>{points:.2f}</span></span>"


# return st, nd, rd for a number
def ordinal_word(n: int) -> str:
    if 0 <= n < len(ORDINAL_WORDS):
        return ORDINAL_WORDS[n]
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# return singular or plural version of a word
def return_plural(check, singular, plural) -> str:
    return singular if check == 1 else plural


# add s depending on item length
def return_s(check):
    return "s" if check != 1 else ""


# check if a pick is a keeper
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
    Analysis tab and pages_player_analysis.py's Value Analysis tab - built once
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
    pages_drafts.py and pages_player_analysis.py's Value Analysis tab -
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
        SELECT_STAT_TO_VIEW,
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
        # pages_player_analysis.py's percentile chart - every OTHER player's own
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
                marker={"size": CHART_MARKER_SIZE_MEDIUM, "color": COLOR_PERCENTILE_OTHER_PLAYERS, "opacity": 0.5},
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
                marker={"size": CHART_MARKER_SIZE_MEDIUM, "color": COLOR_PERCENTILE_SELECTED_PLAYER, "line": {"width": 1, "color": COLOR_CHART_SCATTER_MARKER_OUTLINE}},
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
            line={"color": COLOR_PICK, "width": CHART_LINE_WIDTH_LARGE},
            marker={"color": COLOR_PICK, "size": CHART_MARKER_SIZE_MEDIUM},
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


def pad_missing_starters(starters: list[dict], year: int) -> list[dict]:
    """Rebuilds the starters list in roster_settings' own slot order
    (QB, RB, RB, WR, WR, TE, FLEX, K, DEF, ...), inserting a blank
    placeholder row wherever that season's settings call for a slot this
    week's actual starters list is short on - e.g. settings call for 2 RB
    but only 1 RB actually started, so the second RB slot renders empty
    in its normal position rather than being silently omitted or tacked
    on at the end out of order. This is a real gap the manager likely
    just forgot to fill (as opposed to a bye/injury, which still shows an
    actual, if low-scoring, player)."""
    expected_slot_counts = load_starting_slot_counts(year)
    remaining_by_slot: dict[str, list[dict]] = {}
    for player in starters:
        slot = player.get("slot", player["position"])
        remaining_by_slot.setdefault(slot, []).append(player)

    ordered: list[dict] = []
    for slot, expected_count in expected_slot_counts.items():
        available = remaining_by_slot.get(slot, [])
        for _ in range(expected_count):
            ordered.append(available.pop(0) if available else {"position": slot, "is_empty_slot": True})
    return ordered


def optimal_lineup_details(side: dict, year: int) -> dict:
    """{"gains": {player_id: +points}, "losses": {player_id: +points},
    "optimal_points": float, "optimal_player_ids": set} - gains covers bench players who belong in
    the optimal lineup (compute_optimal_lineup - the same formula behind
    best_coaching_season/worst_coaching_season); losses is the mirror
    image, one displaced actual starter per gain, same magnitude, opposite
    sign when rendered.

    Two-pass attribution over "added" (optimal starters who weren't
    actually started) and "removed" (actual starters who aren't in the
    optimal lineup):

    Pass 1 matches each added player against a removed player at the SAME
    (or FLEX-eligible) position first, biggest added points vs weakest
    same-position removed - this is what correctly handles the common
    case of two or more INDEPENDENT simple swaps in the same week (e.g. a
    better bench DEF for the starting DEF, AND separately a better bench
    TE for the starting TE - each attributed to its own real position
    swap, not cross-matched by point value alone).

    Pass 2 pairs whatever's left over (added points descending vs removed
    points ascending) regardless of position - this covers the case a
    same-position match alone can't explain: the true optimal lineup
    reshuffled an EXISTING starter into a different slot (e.g. a starting
    RB moved into FLEX to make room for a stronger bench RB) rather than
    benching them outright, so pass 1 finds no same-position starter that
    "dropped out" to pair against. See bugs.md for the real examples that
    surfaced both failure modes this two-pass approach fixes (2022 Wk4/
    Wk13/Wk15, Jeremy vs Alex F). Neither pass claims to reconstruct the
    TRUE swap chain in multi-swap weeks - this is a display attribution
    convention, same as before - but pass 1 keeps genuinely independent
    swaps correctly attributed, and pass 2 guarantees no real gain is
    dropped to zero the way the original single-pass version could.

    A team's actual archived lineup can be genuinely short a starter
    (fewer real starter entries that week than that season's roster
    settings call for - the manager just never filled the slot). That
    slot is treated as a real, legitimate starter scoring 0 - the same
    "empty slot" placeholder pad_missing_starters() already synthesizes
    for display - so the optimizer can still consider the next-best
    available bench player for it exactly like any other slot, and (if
    no eligible bench player exists either) it correctly stays a 0-point
    swap with no gain/loss recorded at all, rather than the "added" list
    silently ending up longer than "removed" (see bugs.md bug 8).
    optimal_points is the true optimal lineup's total, for the bench
    table's summary row.

    DB (Defensive Back / IDP) position players are excluded from the
    optimizer entirely, on both sides of the comparison - 2012 is the
    only season with this roster slot, it's vestigial (no player ever
    legitimately fills it - see bugs.md bug 5's footnote), and trying to
    "optimize" a slot with no real candidate pool just produced a
    mismatched added/removed count. A DB starter is left untouched: never
    a swap candidate, never highlighted red/green, with their real points
    folded back into optimal_points unchanged so the displayed total
    still matches the team's actual score."""
    padded_starters = pad_missing_starters(side["starters"], year)
    for placeholder in padded_starters:
        if placeholder.get("is_empty_slot"):
            placeholder["points"] = 0.0
            placeholder["player_id"] = f"_empty_slot_{id(placeholder)}"
            # FLEX's slot label ("W/R") isn't a real position - flagged
            # separately rather than forcing "position" to a concrete
            # RB/WR guess, since it's genuinely either and the roster
            # table still needs to display the literal "W/R" label for
            # this row (see _render_roster_table/_cell).
            if placeholder["position"] == "W/R":
                placeholder["_flex_empty"] = True

    # optimizable_starters (padded, includes 0-point empty-slot
    # placeholders) is only used below for the "what changed" comparison
    # - the solver itself only ever sees REAL players. Feeding a
    # placeholder into the solver's own candidate pool would let it treat
    # a fake 0-point "player" as a real FLEX/position candidate, which
    # (combined with FLEX's position label not being a real position -
    # see _flex_empty above) risks the solver silently mishandling it.
    # Keeping the solver's input untouched also keeps its result
    # identical to what code/stats-aggregation/coaching.py already
    # computes from the same real-player pool.
    optimizable_starters = [p for p in padded_starters if p.get("position") != "DB"]
    real_starters = [p for p in side["starters"] if p.get("position") != "DB"]
    optimizable_bench = [p for p in side["bench"] if p.get("position") != "DB"]
    db_points = sum(p["points"] for p in side["starters"] if p.get("position") == "DB")

    all_players = real_starters + optimizable_bench
    optimal = compute_optimal_lineup(all_players, year)
    optimal_ids = {p["player_id"] for p in optimal["optimal_starters"] if p.get("player_id")}
    actual_starter_ids = {p["player_id"] for p in optimizable_starters if p.get("player_id")}

    added = [p for p in optimal["optimal_starters"] if p.get("player_id") and p["player_id"] not in actual_starter_ids]
    removed = [p for p in optimizable_starters if p.get("player_id") and p["player_id"] not in optimal_ids]
    added.sort(key=lambda p: p["points"], reverse=True)

    pairs: list[tuple[dict, dict]] = []

    # Pass 1: direct same-position/FLEX-eligible swaps. A gained player's
    # own EXACT position is tried first, before falling back to the
    # broader FLEX-eligible union (RB/WR) - a FLEX-slot bench player (say
    # a WR) greedily matching against the weakest candidate across BOTH
    # positions can steal the wrong position's removed starter (e.g. an
    # RB who happens to have fewer points than the actual same-position
    # WR it should have paired against), starving a later same-position
    # bench player of its own natural, same-position partner and forcing
    # a mismatched pass-2 pairing - which can even go NEGATIVE if the
    # only leftover "removed" starter outscores it. See bugs.md.
    unmatched_added: list[dict] = []
    remaining_removed = list(removed)
    for gained_player in added:
        eligible_positions = FLEX_ELIGIBLE_POSITIONS if gained_player["optimal_slot"] == "FLEX" else {gained_player["optimal_slot"]}
        same_position_candidates = [
            r
            for r in remaining_removed
            if r.get("position") == gained_player.get("position")
            # An empty FLEX slot's own "position" is the literal "W/R"
            # label, not a real position (see _flex_empty above) - any
            # FLEX-eligible gained player (RB or WR) can count it as a
            # same-slot match, since the empty slot was equally eligible
            # for either.
            or (r.get("_flex_empty") and gained_player.get("position") in FLEX_ELIGIBLE_POSITIONS)
        ]
        candidates = same_position_candidates or [r for r in remaining_removed if r.get("position") in eligible_positions]
        if not candidates:
            unmatched_added.append(gained_player)
            continue
        weakest_displaced = min(candidates, key=lambda r: r["points"])
        pairs.append((gained_player, weakest_displaced))
        remaining_removed.remove(weakest_displaced)

    # Pass 2: whatever's left (chain-reassignment case), paired by rank.
    remaining_removed.sort(key=lambda p: p["points"])
    for gained_player, lost_player in zip(unmatched_added, remaining_removed):
        pairs.append((gained_player, lost_player))

    gains: dict[str, float] = {}
    losses: dict[str, float] = {}
    for gained_player, lost_player in pairs:
        gain = gained_player["points"] - lost_player["points"]
        # A real starter already scoring 0.0, tied with an equally
        # 0.0-point bench "replacement," isn't a meaningful swap worth
        # flagging - skip it entirely (leave both un-highlighted) rather
        # than show a same-value green/red pair for what's functionally
        # no change at all. An EMPTY slot (is_empty_slot placeholder - no
        # real player rostered there at all) filled by a 0.0-point bench
        # player is NOT this case: going from no player to an actual
        # rostered player is a real, worth-showing change even when the
        # score happens to be 0 (conceptually NaN -> 0.0, not 0.0 -> 0.0)
        # - so only a real, already-rostered 0.0 starter is excluded here.
        if gain == 0.0 and lost_player["points"] == 0.0 and not lost_player.get("is_empty_slot"):
            continue
        gains[gained_player["player_id"]] = gain
        losses[lost_player["player_id"]] = gain

    return {"gains": gains, "losses": losses, "optimal_points": optimal["optimal_points"] + db_points, "optimal_player_ids": optimal_ids}


def integer_yaxis_nticks(values: list[int]) -> int:
    """MAX_YAXIS_TICKS is a CEILING, not a target - passing it straight
    through as Plotly's nticks forces that many ticks even over a tiny
    integer range (e.g. 0-5), which makes Plotly fall back to a
    fractional dtick and repeat rounded integer labels. Capping nticks
    at the data's own distinct-integer-value count (max_value + 1, for a
    0-based count axis) keeps every tick unique."""
    if not values:
        return MAX_YAXIS_TICKS
    return min(max(values) + 1, MAX_YAXIS_TICKS)


def render_record_metrics(matchups: list[dict], manager_id: str) -> None:
    """Matchups / Wins / Losses / Ties / Win % / Points For / Points
    Against for one manager across the given matchups - shared by the
    Matchups page and the Managers page's Historical Stats tab."""
    wins = losses = ties = 0
    points_for = points_against = 0.0
    for matchup in matchups:
        home, away = matchup["home"], matchup["away"]
        manager_side, other_side = (home, away) if home["manager_id"] == manager_id else (away, home)
        points_for += manager_side["score"]
        points_against += other_side["score"]
        if manager_side["score"] > other_side["score"]:
            wins += 1
        elif manager_side["score"] < other_side["score"]:
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


def render_season_qualification_metrics(matchups: list[dict]) -> None:
    """Seasons competed in, and seasons that reached the championship /
    consolation bracket, across the given matchups - shared by the
    Matchups page and the Managers page's Historical Stats tab."""
    seasons_competed = {matchup["season"] for matchup in matchups}
    championship_seasons = {matchup["season"] for matchup in matchups if matchup["matchup_type"] == "championship"}
    consolation_seasons = {matchup["season"] for matchup in matchups if matchup["matchup_type"] == "consolation"}

    seasons_column, championship_column, consolation_column = st.columns(3)
    seasons_column.metric("Seasons", len(seasons_competed))
    championship_column.metric("Championship Qualifying Seasons", len(championship_seasons))
    consolation_column.metric("Consolation Qualifying Seasons", len(consolation_seasons))


def parse_transaction_date(date_text: str, season: int) -> datetime:
    """ "Dec 28, 4:33pm" + season -> a real datetime. A season's playoffs
    can run into January of the FOLLOWING calendar year (confirmed for
    2012, 2021, 2022) - only "Jan" dates get season+1, everything else
    (Aug-Dec) uses the season's own year."""
    month_text = date_text.split(" ", 1)[0]
    year = season + 1 if month_text == "Jan" else season
    return datetime.strptime(f"{date_text} {year}", "%b %d, %I:%M%p %Y")  # noqa: DTZ007


def render_pagination_input(state_key: str, total_pages: int) -> int:
    """The "Pagination" number input shared by the Feedback issues table,
    the Seasons transactions table and the Drafts auction table. Labeled
    "Pagination" (not "Page") so it never reads like a "Page" filter.
    A filter change can shrink total_pages below the page already in
    session_state, which st.number_input rejects, so that's clamped back
    to page 1 first. Returns the 1-based page."""
    if st.session_state.get(state_key, 1) > total_pages:
        st.session_state[state_key] = 1
    return st.number_input("Pagination", min_value=1, max_value=total_pages, step=1, key=state_key)


def render_html_table(headers: list[str], rows: list[list[str]]) -> None:
    """Left-aligned table whose cells may contain HTML (e.g. position
    pills), which st.dataframe can't render. Uses translucent borders and
    inherited text color so it works in light and dark themes."""
    header_html = "".join(f"<th style='text-align:left; padding:6px 10px; border-bottom:2px solid rgba(128,128,128,0.4);'>{header}</th>" for header in headers)
    body_html = "".join("<tr>" + "".join(f"<td style='padding:6px 10px; border-bottom:1px solid rgba(128,128,128,0.2);'>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    st.markdown(f"<table style='width:100%; border-collapse:collapse;'><tr>{header_html}</tr>{body_html}</table>", unsafe_allow_html=True)
