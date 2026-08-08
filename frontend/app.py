"""HSFL Archive - Streamlit entrypoint. Pure read-only view over the
committed archive/*.json output - no database, no live fetching. See
execution-plan.md Phase G.

Uses st.navigation/st.Page (not st.tabs) specifically so other pages can
st.switch_page() here with pre-set filters - e.g. clicking a record on
the History page to jump straight to the Games page already filtered to
that season/week/manager. st.tabs has no equivalent programmatic
switch, which is why this isn't a single-page st.tabs layout.

Run locally: streamlit run app.py
"""

import streamlit as st

from pages_games import render_games_page
from pages_history import render_history_page
from pages_players import render_players_page
from pages_yearly import render_yearly_page

st.set_page_config(page_title="The Music League", page_icon="🏈", layout="wide")


def render_managers_page() -> None:
    st.info("Coming soon - manager stats, web chart vs other managers, custom stats, etc.")


def render_drafts_page() -> None:
    st.info("Coming soon - draft results per season (full order, final rosters, most expensive auction stuff. across all drafts average pick, average cost).")


history_page = st.Page(render_history_page, title="History", url_path="history", default=True)
yearly_page = st.Page(render_yearly_page, title="Yearly", url_path="yearly")
games_page = st.Page(render_games_page, title="Games", url_path="games")
managers_page = st.Page(render_managers_page, title="Managers", url_path="managers")
drafts_page = st.Page(render_drafts_page, title="Drafts", url_path="drafts")
players_page = st.Page(render_players_page, title="Players", url_path="players")

# Stashed so other pages (e.g. pages_history.py's record links) can
# st.switch_page() straight to Games without app.py needing to pass
# page objects down through every render_*_page() call signature.
st.session_state["_games_page"] = games_page

st.title("The Music League")

navigation = st.navigation([history_page, yearly_page, managers_page, players_page, games_page, drafts_page])
navigation.run()
