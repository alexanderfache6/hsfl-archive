"""
Reusable "player stats for one week" modal (st.dialog) - triggered by
clicking a player anywhere in the app that shows them for a specific
(season, week), starting with the Games tab's roster tables. Player name/
position/team on the first row, that week's raw stat breakdown (decoded
via archive/stat_id_labels.json) as a table below it. See
execution-plan.md Phase G.
"""

# ========================================
# IMPORTS
# ========================================

import streamlit as st

from data_loader import compute_stat_fantasy_points, load_player_ownership, load_stat_id_labels

# ========================================
# CONSTANTS
# ========================================

MODAL_CONTEXT_KEY = "_player_stats_modal_context"

# ========================================
# RENDER
# ========================================


@st.dialog("Player Stats")
def _render_player_stats_dialog() -> None:
    context = st.session_state.get(MODAL_CONTEXT_KEY)
    if not context:
        return

    st.markdown(f"**{context['player_name']}** · {context['position']} · {context['nfl_team']}")
    st.caption(f"{context['season']} · Week {context['week']}")

    stat_id_labels = load_stat_id_labels()
    timeline = load_player_ownership()["player_ownership"].get(context["player_id"], [])
    entry = next((e for e in timeline if e["season"] == context["season"] and e["week"] == context["week"]), None)

    if not entry or not entry.get("stats"):
        st.info("No detailed stat breakdown available for this game.")
        return

    header_html = (
        "<tr style='background-color:#E0E0E0;'>"
        "<td style='padding:3px 8px; font-weight:700;'>Stat</td>"
        "<td style='padding:3px 8px; text-align:right; font-weight:700;'>Value</td>"
        "<td style='padding:3px 8px; text-align:right; font-weight:700;'>Fantasy Points</td></tr>"
    )
    row_cells = []
    for stat_id, value in entry["stats"].items():
        fantasy_points = compute_stat_fantasy_points(stat_id, value, context["position"], context["season"])
        points_text = f"{fantasy_points:+.2f}" if fantasy_points is not None else "—"
        row_cells.append(
            f"<tr><td style='padding:3px 8px; color:#666666;'>{stat_id_labels.get(stat_id, stat_id)}</td>"
            f"<td style='padding:3px 8px; text-align:right; font-weight:600;'>{value}</td>"
            f"<td style='padding:3px 8px; text-align:right; font-weight:600;'>{points_text}</td></tr>"
        )
    st.markdown(
        f"<table style='width:100%; border-collapse:separate; border-spacing:0; border-radius:6px; "
        f"overflow:hidden; background-color:#F0F0F0; font-size:0.9em; color:#333333;'>{header_html}{''.join(row_cells)}</table>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Fantasy Points is each stat line's own scoring contribution, decoded from that season's league rules - it won't "
        "always sum to the game's total points, since some scoring components (e.g. PPR reception bonuses) aren't captured "
        "as their own stat line in the archived box score data."
    )


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
