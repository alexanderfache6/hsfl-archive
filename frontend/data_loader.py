"""Reads the committed archive/*.json output directly - no database, no
API calls. See execution-plan.md Phase G for the architecture (data is
fetched/parsed/aggregated offline and committed to the repo; the
frontend is a pure read-only view over those static files).
"""

import json
from pathlib import Path

import streamlit as st

PROJECT_ROOT_DIRECTORY = Path(__file__).resolve().parent.parent
ARCHIVE_DIRECTORY = PROJECT_ROOT_DIRECTORY / "archive"
AGGREGATED_DIRECTORY = ARCHIVE_DIRECTORY / "aggregated"
PARSED_DIRECTORY = ARCHIVE_DIRECTORY / "parsed"


def _read_json(path: Path):
    return json.loads(path.read_text())


@st.cache_data
def load_all_time_champions() -> dict:
    return _read_json(AGGREGATED_DIRECTORY / "all_time_champions.json")


@st.cache_data
def load_all_time_manager_stats() -> dict:
    return _read_json(AGGREGATED_DIRECTORY / "all_time_manager_stats.json")


@st.cache_data
def load_all_time_records() -> dict:
    return _read_json(AGGREGATED_DIRECTORY / "all_time_records.json")


@st.cache_data
def discover_seasons() -> list[int]:
    if not PARSED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in PARSED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


@st.cache_data
def load_weekly_tables(year: int) -> dict:
    return _read_json(AGGREGATED_DIRECTORY / str(year) / "weekly_tables.json")


@st.cache_data
def load_players_started(year: int) -> dict:
    return _read_json(AGGREGATED_DIRECTORY / str(year) / "players_started.json")


@st.cache_data
def build_manager_name_resolver() -> dict[str, str]:
    """{manager_id: display name to actually show in the UI}. Prefers
    display_names_seen_alternate (set in archive/managers.json for
    managers who share a display_name with someone else, e.g. two
    different manager_ids both named "Alex") over the raw
    display_names_seen, per user instruction 2026-08-07: "for all UI
    items first check if display_names_seen_alternate is not "" and if
    so use [it]". Every UI element that shows a manager's name should
    resolve through this rather than reading a raw display_name field
    directly, so the disambiguation is applied consistently everywhere -
    not just the one table it was first requested for."""
    manager_stats = load_all_time_manager_stats()
    resolver = {}
    for manager in manager_stats["managers"]:
        alternate = manager.get("display_names_seen_alternate", "")
        if alternate:
            resolver[manager["manager_id"]] = alternate
        elif manager["display_names_seen"]:
            resolver[manager["manager_id"]] = manager["display_names_seen"][-1]
    return resolver


def resolve_manager_name(manager_id: str, resolver: dict[str, str], fallback: str = "") -> str:
    return resolver.get(manager_id, fallback)
