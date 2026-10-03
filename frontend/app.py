"""
uses st.Page instead of st.tabs so that st.switch_page can be used

Usage: streamlit run app.py
"""

# ========================================
# IMPORTS
# ========================================

import streamlit as st
from pages_drafts import render_drafts_page
from pages_feedback import render_feedback_page
from pages_history import render_history_page
from pages_managers import render_managers_page
from pages_matchups import render_matchups_page
from pages_player_analysis import render_player_analysis_page
from pages_seasons import render_seasons_page
from pages_trade_analysis import render_trade_analysis_page
from strings import PAGE_DRAFTS, PAGE_FEEDBACK, PAGE_HISTORY, PAGE_MANAGERS, PAGE_MATCHUPS, PAGE_PLAYER_ANALYSIS, PAGE_SEASONS, PAGE_TRADE_ANALYSIS, THE_MUSIC_LEAGUE

# ========================================
# RENDER
# ========================================

st.set_page_config(page_title=THE_MUSIC_LEAGUE, page_icon="🏈", layout="wide")

history_page = st.Page(render_history_page, title=PAGE_HISTORY, url_path="history", default=True)
seasons_page = st.Page(render_seasons_page, title=PAGE_SEASONS, url_path="seasons")
managers_page = st.Page(render_managers_page, title=PAGE_MANAGERS, url_path="managers")
matchups_page = st.Page(render_matchups_page, title=PAGE_MATCHUPS, url_path="matchups")
drafts_page = st.Page(render_drafts_page, title=PAGE_DRAFTS, url_path="drafts")
trade_analysis_page = st.Page(render_trade_analysis_page, title=PAGE_TRADE_ANALYSIS, url_path="trade-analysis")
player_analysis_page = st.Page(render_player_analysis_page, title=PAGE_PLAYER_ANALYSIS, url_path="player-analysis")
feedback_page = st.Page(render_feedback_page, title=PAGE_FEEDBACK, url_path="feedback")

# Stashed so other pages (e.g. pages_history.py's record links) can
# st.switch_page() straight to Matchups without app.py needing to pass
# page objects down through every render_*_page() call signature.
st.session_state["_matchups_page"] = matchups_page
st.session_state["_seasons_page"] = seasons_page

st.title(THE_MUSIC_LEAGUE)

navigation = st.navigation([history_page, seasons_page, managers_page, matchups_page, drafts_page, trade_analysis_page, player_analysis_page, feedback_page])
navigation.run()
