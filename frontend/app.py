"""HSFL Archive - Streamlit entrypoint. Pure read-only view over the
committed archive/*.json output - no database, no live fetching. See
execution-plan.md Phase G.

Run locally: streamlit run app.py
"""

import streamlit as st

from data_loader import discover_seasons
from pages_history import render_history_page

st.set_page_config(page_title="The Music League - Archives", page_icon="🏈", layout="wide")

st.title("The Music League - Archives")

history_tab, yearly_tab, managers_tab, players_tab, games_tab = st.tabs(["History", "Yearly", "Managers", "Players", "Games"])

with history_tab:
    render_history_page()

with yearly_tab:
    seasons = discover_seasons()
    st.selectbox("Season", seasons, index=len(seasons) - 1 if seasons else 0, key="yearly_season_placeholder")
    st.info("Coming soon - weekly stat graphs and season aggregates for the selected year.")

with managers_tab:
    st.info("Coming soon - pick a manager, see their stats across every season they've played.")

with players_tab:
    st.info("Coming soon - which manager(s) rostered a player, and how often.")

with games_tab:
    st.info("Coming soon - individual gamecenter/matchup views.")
