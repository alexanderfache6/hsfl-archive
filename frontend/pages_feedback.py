"""Feedback tab - lets an approved (Streamlit Cloud viewer-list) user file
a bug/improvement/new-feature note as a GitHub Issue on this repo,
tagged with the submitter's authenticated email, then lists the repo's
issues (filterable by state/type/page) below the form. See
execution-plan.md Phase G.
"""

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

PACIFIC_TIMEZONE = ZoneInfo("America/Los_Angeles")

GITHUB_REPO = "alexanderfache6/hsfl-archive"
GITHUB_API_BASE = "https://api.github.com"

FEEDBACK_TYPES = ["Bug", "Improvement", "New Feature"]
REAL_PAGES = ["History", "Seasons", "Matchups", "Managers", "Players", "Drafts"]
TITLE_MAX_CHARS = 50
DESCRIPTION_MAX_CHARS = 400


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


ISSUE_LABELS_BY_TYPE = {"Bug": ["bug"], "Improvement": ["enhancement"], "New Feature": ["enhancement"]}


FEEDBACK_WIDGET_BASE_KEYS = ("feedback_type", "feedback_page", "feedback_title", "feedback_description")


def _render_feedback_form() -> None:
    st.subheader("Submit Feedback")

    viewer_email = _viewer_email()
    if viewer_email:
        st.caption(f"Submitting as {viewer_email}")
    else:
        st.caption("Submitting anonymously (no Streamlit Cloud login detected - expected in local dev).")

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
    description = st.text_input("Description", max_chars=DESCRIPTION_MAX_CHARS, key=versioned_key("feedback_description"))

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

    submit_column, clear_column, _ = st.columns([1, 1, 3])
    with submit_column:
        submit_clicked = st.button("Submit", disabled=not (title.strip() and description.strip()))
    with clear_column:
        if st.button("Clear Feedback"):
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

        issue_title = f"[{feedback_type}] {title}"
        body_lines = [
            f"**Type:** {feedback_type}",
            f"**Page:** {selected_page}",
            f"**Title:** {title}",
            f"**Description:** {description}",
            f"**Submitted by:** {viewer_email or '_unknown (local/dev)_'}",
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


# Issues filed by this form always have a title of "[{feedback_type}]
# {description}" and a "**Page:** {page}" line in the body (see
# _render_feedback_form above) - parsed back out here rather than relying
# on labels, since "Improvement" and "New Feature" both map to the same
# "enhancement" label and so can't be told apart from labels alone.
ISSUE_TITLE_PATTERN = re.compile(r"^\[(.*?)\]\s*(.*)$")
ISSUE_PAGE_PATTERN = re.compile(r"\*\*Page:\*\*\s*(.+)")
ISSUE_DESCRIPTION_PATTERN = re.compile(r"\*\*Description:\*\*\s*(.+)")


def _format_pacific(iso_timestamp: str | None) -> str:
    """GitHub's timestamps are ISO 8601 UTC ("...Z") - converted to
    Pacific wall-clock time here, but always labeled "PST" per request
    (not a dynamic PST/PDT label based on whether daylight saving is
    actually in effect for that date)."""
    if not iso_timestamp:
        return "—"
    utc_time = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    pacific_time = utc_time.astimezone(PACIFIC_TIMEZONE)
    return pacific_time.strftime("%Y-%m-%d %H:%M:%S") + " PST"


def _parse_issue(issue: dict) -> dict:
    title_match = ISSUE_TITLE_PATTERN.match(issue["title"])
    issue_type, title = title_match.groups() if title_match else ("", issue["title"])
    body = issue.get("body") or ""
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


ISSUES_PAGE_SIZE = 10


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
    # to its right - same layout as the Yearly page's Transactions table.
    search_column, page_counter_column = st.columns([3, 1])
    with search_column:
        title_options = sorted({issue["title"] for issue in issues})
        searched_title = st.selectbox(
            "Search titles", title_options, index=None, placeholder="Type to search titles...", key="feedback_search_title"
        )

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
                "Issue Type": issue["issue_type"],
                "Page": issue["page"],
                "Title": issue["title"],
                "Submitted": issue["submitted_at"],
                "Closed": issue["closed_at"],
                "URL": issue["url"],
            }
        )

    if not rows:
        st.info("No issues match these filters.")
        return

    rows.sort(key=lambda row: row["Issue #"], reverse=True)

    # Same pagination pattern as the Yearly page's Transactions table - a
    # filter change can shrink total_pages below whatever page was
    # previously selected, so that's clamped back to page 1 before the
    # widget mounts rather than letting st.number_input raise on an
    # out-of-range session_state value.
    total_pages = -(-len(rows) // ISSUES_PAGE_SIZE)
    if st.session_state.get("feedback_issues_page", 1) > total_pages:
        st.session_state["feedback_issues_page"] = 1
    with page_counter_column:
        page = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="feedback_issues_page")
    st.caption(f"Page {page} of {total_pages} ({len(rows)} issues)")

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


def _pacific_date(iso_timestamp: str | None) -> str | None:
    if not iso_timestamp:
        return None
    utc_time = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return utc_time.astimezone(PACIFIC_TIMEZONE).strftime("%Y-%m-%d")


OPENED_COLOR = "#2E7D32"
CLOSED_COLOR = "#1E88E5"


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
        marker_color=OPENED_COLOR,
        customdata=closed_values,
        hovertemplate="Date: %{x}<br>Opened Issues: %{y}<br>Closed Issues: %{customdata}<extra></extra>",
    )
    figure.add_bar(
        name="Closed",
        x=all_dates,
        y=closed_values,
        marker_color=CLOSED_COLOR,
        customdata=opened_values,
        hovertemplate="Date: %{x}<br>Opened Issues: %{customdata}<br>Closed Issues: %{y}<extra></extra>",
    )
    figure.update_layout(
        barmode="group",  # side by side per day, not stacked
        xaxis_title="Date",
        yaxis_title="Number of Issues",
        xaxis=dict(type="category"),  # plain "yyyy-mm-dd" tick labels, no time-of-day
        yaxis=dict(dtick=1),
        legend_title_text="",
    )
    st.plotly_chart(figure, width="stretch")


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


def render_feedback_page() -> None:
    _render_feedback_form()
    st.divider()

    issues = _issues_with_pending_merged()
    if issues is None:
        st.info("Couldn't load issues right now.")
        return

    _render_issues_table(issues)
    _render_issue_activity_chart(issues)
