"""
Feedback tab - lets an approved (Streamlit Cloud viewer-list) user file
a bug/improvement/new-feature note as a GitHub Issue on this repo,
tagged with the submitter's authenticated email, then lists the repo's
issues (filterable by state/type/page) below the form. See
execution-plan.md Phase G.
"""

# ========================================
# IMPORTS
# ========================================

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from data_loader import CHART_XAXIS_MAX_TICKS, CHART_YAXIS_MAX_TICKS

# ========================================
# CONSTANTS
# ========================================

PACIFIC_TIMEZONE = ZoneInfo("America/Los_Angeles")

GITHUB_REPO = "alexanderfache6/hsfl-archive"
GITHUB_API_BASE = "https://api.github.com"

FEEDBACK_TYPES = ["Bug", "Improvement", "New Feature"]
REAL_PAGES = ["History", "Seasons", "Players", "Matchups", "Feedback"]
KNOWN_PAGES = {*REAL_PAGES, "Other"}
TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 400

ISSUE_LABELS_BY_TYPE = {"Bug": ["bug"], "Improvement": ["enhancement"], "New Feature": ["feature"]}

FEEDBACK_WIDGET_BASE_KEYS = ("feedback_type", "feedback_page", "feedback_title", "feedback_description")

# Issues filed by this form always have "**Type:**"/"**Page:**"/
# "**Description:**" lines in the body (see _render_feedback_form).
# Type is always parsed from the body, not labels, since "Improvement"
# and "New Feature" both map to the same "enhancement" label so can't be
# told apart from labels alone. Page prefers the title's own "[...]"
# bracket (the current naming format is "[Page] Title") but falls back
# to the body's "**Page:**" line when the bracket isn't a recognized
# page - older issues filed before this naming format held the TYPE in
# that bracket instead (see _parse_issue's KNOWN_PAGES check).
ISSUE_TITLE_PATTERN = re.compile(r"^\[(.*?)\]\s*(.*)$")
ISSUE_TYPE_PATTERN = re.compile(r"\*\*Type:\*\*\s*(.+)")
ISSUE_PAGE_PATTERN = re.compile(r"\*\*Page:\*\*\s*(.+)")
ISSUE_DESCRIPTION_PATTERN = re.compile(r"\*\*Description:\*\*\s*(.+)")

ISSUES_PAGE_SIZE = 10

ISSUES_OPENED_COLOR = "#2E7D32"
ISSUES_CLOSED_COLOR = "#1E88E5"

# ========================================
# FUNCTIONS
# ========================================


def _viewer_email() -> str:
    """The Streamlit Cloud-authenticated viewer's email - only populated
    when actually running on Community Cloud with viewer access control
    enabled (empty in local dev, since there's no login to read)."""
    user = getattr(st, "user", None) or getattr(st, "experimental_user", None)
    return getattr(user, "email", "") or ""


def _github_token() -> str:
    try:
        return st.secrets.get("GITHUB_ISSUES_TOKEN", "")
    except Exception:
        return ""


def _create_github_issue(title: str, body: str, labels: list[str]) -> dict:
    response = requests.post(
        f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues",
        headers={"Authorization": f"Bearer {_github_token()}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body, "labels": labels},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _format_pacific(iso_timestamp: str | None) -> str:
    """GitHub's timestamps are ISO 8601 UTC ("...Z") - converted to
    Pacific wall-clock time here (so the date shown matches the Pacific
    calendar day, not UTC's) and truncated to just yyyy-mm-dd, no
    time-of-day."""
    if not iso_timestamp:
        return "—"
    utc_time = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    pacific_time = utc_time.astimezone(PACIFIC_TIMEZONE)
    return pacific_time.strftime("%Y-%m-%d")


def _parse_issue(issue: dict) -> dict:
    title_match = ISSUE_TITLE_PATTERN.match(issue["title"])
    bracket, title = title_match.groups() if title_match else ("", issue["title"])
    body = issue.get("body") or ""
    type_match = ISSUE_TYPE_PATTERN.search(body)
    issue_type = type_match.group(1).strip() if type_match else ""
    if bracket in KNOWN_PAGES:
        page = bracket
    else:
        # Older issue, filed before the "[Page] Title" naming format -
        # the bracket holds the type instead, so fall back to the body's
        # own "**Page:**" line.
        page_match = ISSUE_PAGE_PATTERN.search(body)
        page = page_match.group(1).strip() if page_match else ""
    description_match = ISSUE_DESCRIPTION_PATTERN.search(body)
    description = description_match.group(1).strip() if description_match else ""
    return {
        "state": issue["state"],
        "issue_type": issue_type,
        "page": page,
        "title": title,
        "description": description,
        "number": issue["number"],
        "url": issue["html_url"],
        "submitted_at": _format_pacific(issue.get("created_at")),
        "closed_at": _format_pacific(issue.get("closed_at")),
        "created_at_raw": issue.get("created_at"),
        "closed_at_raw": issue.get("closed_at"),
    }


@st.cache_data(ttl=60)
def _all_issues() -> list[dict]:
    """Every issue on the repo (both states - the State filter below
    needs Closed available too), PRs excluded (GitHub's issues endpoint
    returns both - a PR's payload carries its own "pull_request" key,
    which is what's used to tell them apart), pre-parsed into this form's
    own Type/Page/Description fields. Cached for 60s so a page rerun
    doesn't refetch every time - issues don't change that fast outside of
    right after a fresh submission (see the cache-clear above)."""
    token = _github_token()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues",
        headers=headers,
        params={"state": "all", "per_page": 100},
        timeout=10,
    )
    response.raise_for_status()
    return [_parse_issue(issue) for issue in response.json() if "pull_request" not in issue]


def _pacific_date(iso_timestamp: str | None) -> str | None:
    if not iso_timestamp:
        return None
    utc_time = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return utc_time.astimezone(PACIFIC_TIMEZONE).strftime("%Y-%m-%d")


def _issues_with_pending_merged() -> list[dict] | None:
    """_all_issues()'s real fetch, with any just-submitted issue
    (recorded in session_state - see the submit handler above) merged in
    if GitHub's own list endpoint hasn't caught up to include it yet.
    Returns None on a fetch failure."""
    try:
        issues = _all_issues()
    except requests.RequestException:
        return None

    pending_issues = st.session_state.get("feedback_pending_issues", [])
    if not pending_issues:
        return issues

    known_numbers = {issue["number"] for issue in issues}
    still_pending = [issue for issue in pending_issues if issue["number"] not in known_numbers]
    st.session_state["feedback_pending_issues"] = still_pending
    return issues + still_pending


# ========================================
# RENDER
# ========================================


def _render_feedback_form() -> None:
    st.subheader("Submit Feedback")

    # Same versioned-widget-key pattern as the Matchups/Players tabs'
    # Clear Filters - Clear Feedback (and a successful Submit) bumps this
    # counter instead of just deleting session_state, forcing Streamlit
    # to mount brand-new widget instances (deleting session_state alone
    # can leave a widget showing its old value in some browsers, since
    # the component itself never actually remounts).
    generation = st.session_state.setdefault("feedback_form_generation", 0)

    def versioned_key(base_key: str) -> str:
        return f"{base_key}_gen{generation}"

    for base_key in FEEDBACK_WIDGET_BASE_KEYS:
        widget_key = versioned_key(base_key)
        if widget_key not in st.session_state and base_key in st.session_state:
            st.session_state[widget_key] = st.session_state[base_key]

    feedback_type = st.radio("Type", FEEDBACK_TYPES, key=versioned_key("feedback_type"), horizontal=True)

    page_options = [*REAL_PAGES, "Other"] if feedback_type == "New Feature" else REAL_PAGES
    page_widget_key = versioned_key("feedback_page")
    if st.session_state.get(page_widget_key) not in page_options:
        st.session_state[page_widget_key] = page_options[0]
    selected_page = st.radio("Page", page_options, key=page_widget_key, horizontal=True)

    title = st.text_input("Title", max_chars=TITLE_MAX_CHARS, key=versioned_key("feedback_title"))
    description = st.text_area("Description", max_chars=DESCRIPTION_MAX_CHARS, key=versioned_key("feedback_description"))

    st.session_state["feedback_type"] = feedback_type
    st.session_state["feedback_page"] = selected_page
    st.session_state["feedback_title"] = title
    st.session_state["feedback_description"] = description

    def _reset_form_fields() -> None:
        st.session_state["feedback_type"] = FEEDBACK_TYPES[0]
        st.session_state["feedback_page"] = REAL_PAGES[0]
        st.session_state["feedback_title"] = ""
        st.session_state["feedback_description"] = ""
        st.session_state["feedback_form_generation"] = generation + 1

    # gap=0 AND use_container_width=True on both buttons - gap=0 alone
    # still leaves the columns' own width wider than each button's
    # hug-content size, so the buttons wouldn't actually touch; stretching
    # each button to fill its whole column (same as how the filter
    # selectboxes above already fill theirs) is what closes that gap.
    submit_column, clear_column, _ = st.columns([1, 1, 6])
    with submit_column:
        submit_clicked = st.button("Submit", disabled=not (title.strip() and description.strip()), use_container_width=True)
    with clear_column:
        if st.button("Clear Feedback", use_container_width=True):
            _reset_form_fields()
            st.rerun()

    # A successful submit resets the form on the SAME rerun it triggers
    # (below) - the success message can't be shown before that rerun (it
    # would just be wiped by it), so it's stashed in session_state and
    # displayed here instead, one rerun later. Cleared after 3 seconds -
    # this blocks the script for that long, but only on the one rerun
    # right after a submit, not on every normal rerun.
    if "feedback_last_submitted" in st.session_state:
        submitted = st.session_state.pop("feedback_last_submitted")
        message_placeholder = st.empty()
        message_placeholder.success(f"Issue [#{submitted['number']}]({submitted['url']}) submitted.")
        time.sleep(3)
        message_placeholder.empty()

    if submit_clicked:
        if not _github_token():
            st.error("GitHub integration isn't configured (missing the 'github_token' secret) - can't submit right now.")
            return

        issue_title = f"[{selected_page}] {title}"
        body_lines = [
            f"**Type:** {feedback_type}",
            f"**Page:** {selected_page}",
            f"**Title:** {title}",
            f"**Description:** {description}",
        ]

        try:
            issue = _create_github_issue(issue_title, "\n\n".join(body_lines), ISSUE_LABELS_BY_TYPE[feedback_type])
        except requests.RequestException as error:
            st.error(f"Couldn't submit feedback - GitHub API error: {error}")
            return

        # GitHub's list-issues endpoint (what _all_issues/the chart read)
        # isn't guaranteed to reflect a create instantly - it goes through
        # a separate index from the create endpoint, which is why the
        # issue shows up on github.com right away but can lag here for a
        # few seconds even after clearing our own cache. The create
        # response itself IS immediately correct, so it's stashed and
        # merged into the rendered list below (see render_feedback_page)
        # until GitHub's list endpoint catches up on its own.
        st.session_state.setdefault("feedback_pending_issues", []).append(_parse_issue(issue))

        # Bust the 60s cache too, so once GitHub's list DOES catch up the
        # next load reflects it rather than serving a stale cached list
        # for up to another 60s.
        _all_issues.clear()

        st.session_state["feedback_last_submitted"] = {"number": issue["number"], "url": issue["html_url"]}
        _reset_form_fields()
        st.rerun()


def _render_issues_table(issues: list[dict]) -> None:
    st.subheader("Issues")
    if not issues:
        st.info("No issues yet.")
        return

    state_column, type_column, page_column = st.columns(3)
    with state_column:
        selected_state = st.selectbox("State", ["Open", "Closed"], index=None, placeholder="Any", key="feedback_filter_state")
    with type_column:
        selected_type = st.selectbox("Issue Type", FEEDBACK_TYPES, index=None, placeholder="Any", key="feedback_filter_type")
    with page_column:
        selected_page = st.selectbox("Page", [*REAL_PAGES, "Other"], index=None, placeholder="Any", key="feedback_filter_page")

    # Same searchable-selectbox pattern as the Players tab's player
    # search - typing narrows the list via Streamlit's own built-in
    # substring matching in the dropdown. Page counter shares this row,
    # to its right - same layout as the Seasons page's Transactions table.
    search_column, page_counter_column = st.columns([3, 1])
    with search_column:
        title_options = sorted({issue["title"] for issue in issues})
        searched_title = st.selectbox(
            "Search titles", title_options, index=None, placeholder="Type to search titles...", key="feedback_search_title"
        )

    # Any filter change (including unchecking one back to "Any") jumps
    # back to page 1 of the results - otherwise a filter narrowing the
    # list while the user is on, say, page 3 can land them on a page that
    # no longer makes sense for the new result set.
    filter_signature = (selected_state, selected_type, selected_page, searched_title)
    if st.session_state.get("feedback_issues_filter_signature") != filter_signature:
        st.session_state["feedback_issues_filter_signature"] = filter_signature
        st.session_state["feedback_issues_page"] = 1

    rows = []
    for issue in issues:
        if selected_state and issue["state"] != selected_state.lower():
            continue
        if selected_type and issue["issue_type"] != selected_type:
            continue
        if selected_page and issue["page"] != selected_page:
            continue
        if searched_title and issue["title"] != searched_title:
            continue
        rows.append(
            {
                "Issue #": issue["number"],
                "State": issue["state"].capitalize(),
                "Type": issue["issue_type"],
                "Page": issue["page"],
                "Title": issue["title"],
                "Submission Date": issue["submitted_at"],
                "Closed Date": issue["closed_at"],
                "URL": issue["url"],
            }
        )

    if not rows:
        st.info("No issues match these filters.")
        return

    rows.sort(key=lambda row: row["Issue #"], reverse=True)

    # Same pagination pattern as the Seasons page's Transactions table - a
    # filter change can shrink total_pages below whatever page was
    # previously selected, so that's clamped back to page 1 before the
    # widget mounts rather than letting st.number_input raise on an
    # out-of-range session_state value.
    total_pages = -(-len(rows) // ISSUES_PAGE_SIZE)
    if st.session_state.get("feedback_issues_page", 1) > total_pages:
        st.session_state["feedback_issues_page"] = 1
    with page_counter_column:
        # Labeled "Pagination" (not "Page") to avoid reading like a
        # second "Page" filter alongside the actual Page dropdown above.
        page = st.number_input("Pagination", min_value=1, max_value=total_pages, value=1, step=1, key="feedback_issues_page")
    st.caption(f"Pagination {page} of {total_pages} ({len(rows)} issues)")

    start_index = (page - 1) * ISSUES_PAGE_SIZE
    page_rows = rows[start_index : start_index + ISSUES_PAGE_SIZE]

    dataframe = pd.DataFrame(page_rows)
    # LinkColumn's display_text can only be a fixed string or a regex
    # capturing a substring of the URL itself - "Issue #{n}" mixes in
    # literal text alongside the number, which needs a real per-cell
    # formatter, so this goes through pandas Styler instead (left
    # unset on the LinkColumn config below, since column_config text
    # formatting - i.e. an explicit display_text - would otherwise take
    # precedence over the Styler's).
    styled_dataframe = dataframe.style.format({"URL": lambda url: f"Issue #{url.rsplit('/', 1)[-1]}"})
    st.dataframe(
        styled_dataframe,
        hide_index=True,
        width="stretch",
        column_config={"URL": st.column_config.LinkColumn("Link")},
    )


def _render_issue_activity_chart(issues: list[dict]) -> None:
    opened_dates = [_pacific_date(issue["created_at_raw"]) for issue in issues]
    closed_dates = [_pacific_date(issue["closed_at_raw"]) for issue in issues if issue["closed_at_raw"]]
    if not opened_dates and not closed_dates:
        return

    opened_counts = pd.Series(opened_dates).value_counts()
    closed_counts = pd.Series(closed_dates).value_counts() if closed_dates else pd.Series(dtype=int)
    all_dates = sorted(set(opened_counts.index) | set(closed_counts.index))
    opened_values = [int(opened_counts.get(date, 0)) for date in all_dates]
    closed_values = [int(closed_counts.get(date, 0)) for date in all_dates]

    figure = go.Figure()
    # Both traces carry the SAME combined Date/Opened/Closed tooltip for a
    # given day - each just reaches its own value via %{y} and the OTHER
    # series' value via customdata, so hovering either bar (not just
    # Opened, which is all hoverinfo="skip" on Closed used to allow)
    # shows identical, complete info for that date.
    figure.add_bar(
        name="Opened",
        x=all_dates,
        y=opened_values,
        marker_color=ISSUES_OPENED_COLOR,
        customdata=closed_values,
        hovertemplate="Date: %{x}<br>Opened Issues: %{y}<br>Closed Issues: %{customdata}<extra></extra>",
    )
    figure.add_bar(
        name="Closed",
        x=all_dates,
        y=closed_values,
        marker_color=ISSUES_CLOSED_COLOR,
        customdata=opened_values,
        hovertemplate="Date: %{x}<br>Opened Issues: %{customdata}<br>Closed Issues: %{y}<extra></extra>",
    )
    figure.update_layout(
        barmode="group",  # side by side per day, not stacked
        xaxis_title="Date",
        yaxis_title="Number of Issues",
        xaxis=dict(type="category", nticks=CHART_XAXIS_MAX_TICKS),  # plain "yyyy-mm-dd" tick labels, no time-of-day
        yaxis=dict(nticks=CHART_YAXIS_MAX_TICKS),
        legend_title_text="",
    )
    st.plotly_chart(figure, width="stretch")


def render_feedback_page() -> None:
    _render_feedback_form()
    st.divider()

    issues = _issues_with_pending_merged()
    if issues is None:
        st.info("Couldn't load issues right now.")
        return

    _render_issues_table(issues)
    _render_issue_activity_chart(issues)
