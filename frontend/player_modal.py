"""
Reusable "player stats for one week" modal (st.dialog) - triggered by
clicking a player anywhere in the app that shows them for a specific
(season, week), starting with the Matchups tab's roster tables. Player
name/position/team on the first row, then two expandable sections below
it: this league's own fantasy box score (decoded via
archive/stat_id_labels.json, expanded by default) and the real ESPN NFL
stats for that same week (archive/nfl_player_stats.json, collapsed by
default) - kept as two SEPARATE tables for now rather than cross-
referenced/merged (see nfl_stat_consistency_check.py for the existing
offline mismatch-detection logic, not wired into this modal yet). See
execution-plan.md Phase G.
"""

# ========================================
# IMPORTS
# ========================================

import streamlit as st
from data_loader import (
    NFL_STAT_FIELD_LABELS,
    compute_stat_fantasy_points,
    load_nfl_player_stats,
    load_player_ownership,
    load_stat_id_labels,
)

# ========================================
# CONSTANTS
# ========================================

MODAL_CONTEXT_KEY = "_player_stats_modal_context"

CAPTION_FANTASY_POINTS = "Fantasy Points includes each stat line's own scoring contribution, decoded from that season's league rules."
CAPTION_PPR_POINTS = "Some scoring components such as PPR are not yet integrated."
CAPTION_POINTS_SOURCE = "Per game NFL stats sourced from ESPN."
INFO_NO_FANTASY_DATA = "No stat breakdown available for this player."
INFO_NO_ESPN_DATA = "No ESPN NFL stats available for this player."

# ========================================
# RENDER
# ========================================


def _render_stat_table(column_labels: list[str], rows: list[tuple]) -> None:
    """column_labels[0] is the (left-aligned) stat-name column; every
    other column is right-aligned. rows entries must match column_labels'
    arity - shared HTML table styling for both the Fantasy Stats (3
    columns: Stat/Value/Fantasy Points) and NFL Stats (2 columns: NFL
    Stat/Value - no fantasy-point conversion for raw ESPN fields) sections."""
    header_cells = "".join(f"<td style='padding:3px 8px; font-weight:700;{'' if index == 0 else ' text-align:right;'}'>{label}</td>" for index, label in enumerate(column_labels))
    row_html = "".join("<tr>" + "".join(f"<td style='padding:3px 8px;{' color:#666666;' if index == 0 else ' text-align:right; font-weight:600;'}'>{value}</td>" for index, value in enumerate(row)) + "</tr>" for row in rows)
    st.markdown(
        f"<table style='width:100%; border-collapse:separate; border-spacing:0; border-radius:6px; overflow:hidden; background-color:#F0F0F0; font-size:0.9em; color:#333333;'><tr style='background-color:#E0E0E0;'>{header_cells}</tr>{row_html}</table>",
        unsafe_allow_html=True,
    )


@st.dialog("Game Stats")
def _render_player_stats_dialog() -> None:
    context = st.session_state.get(MODAL_CONTEXT_KEY)
    if not context:
        return

    nfl_player_stats = load_nfl_player_stats()
    espn_player_entry = nfl_player_stats.get(context["player_id"])
    espn_week_entry = (espn_player_entry.get("seasons", {}).get(str(context["season"]), {}).get("weeks", {}).get(str(context["week"]))) if espn_player_entry else None

    # Prefer ESPN's own name (archive/nfl_player_stats.json) when a
    # resolved ESPN mapping exists - falls back to context["player_name"]
    # (the fantasy archive's own name, always present) for anyone
    # unmatched/not yet backfilled.
    player_name = (espn_player_entry or {}).get("name") or context["player_name"]
    opponent_suffix = f" vs {espn_week_entry['opponent']}" if espn_week_entry and espn_week_entry.get("opponent") else ""

    st.markdown(f"**{player_name}** · {context['position']} · {context['nfl_team']}{opponent_suffix}")
    st.caption(f"{context['season']} · Week {context['week']}")

    with st.expander("Fantasy Stats", expanded=True):
        stat_id_labels = load_stat_id_labels()
        timeline = load_player_ownership()["player_ownership"].get(context["player_id"], [])
        entry = next((e for e in timeline if e["season"] == context["season"] and e["week"] == context["week"]), None)

        if not entry or not entry.get("stats"):
            st.info(f"{INFO_NO_FANTASY_DATA}")
        else:
            rows = []
            for stat_id, value in entry["stats"].items():
                fantasy_points = compute_stat_fantasy_points(stat_id, value, context["position"], context["season"])
                points_text = f"{fantasy_points:+.2f}" if fantasy_points is not None else "—"
                rows.append((stat_id_labels.get(stat_id, stat_id), value, points_text))
            # entry["points"] is this league's own REPORTED total for the
            # week (from the box score itself), not a sum of the
            # per-stat computed values above - those can disagree (e.g.
            # PPR/other components compute_stat_fantasy_points doesn't
            # yet integrate, see the caption below), so the real
            # reported total is shown here rather than a recomputed one.
            rows.append(("<b>Total</b>", "", f"<b>{entry['points']:+.2f}<sup>2</sup></b>"))
            _render_stat_table(["Stat", "Value", "Fantasy Points<sup>1</sup>"], rows)
            st.caption(
                f"<sup>1</sup>{CAPTION_FANTASY_POINTS}",
                unsafe_allow_html=True,
            )
            st.caption(f"<sup>2</sup>{CAPTION_PPR_POINTS}", unsafe_allow_html=True)

    with st.expander("NFL Stats", expanded=False):
        espn_week_stats = espn_week_entry["stats"] if espn_week_entry else None
        if not espn_week_stats:
            st.info(f"{INFO_NO_ESPN_DATA}")
        else:
            rows = [(NFL_STAT_FIELD_LABELS.get(field, field), value) for field, value in espn_week_stats.items() if value not in (None, "-")]
            _render_stat_table(["NFL Stat", "Value<sup>3</sup>"], rows)
            st.caption(f"<sup>3</sup>{CAPTION_POINTS_SOURCE}", unsafe_allow_html=True)


def open_player_stats_modal(player_id: str, player_name: str, position: str, nfl_team: str, season: int, week: int) -> None:
    st.session_state[MODAL_CONTEXT_KEY] = {
        "player_id": player_id,
        "player_name": player_name,
        "position": position,
        "nfl_team": nfl_team,
        "season": season,
        "week": week,
    }
    _render_player_stats_dialog()
