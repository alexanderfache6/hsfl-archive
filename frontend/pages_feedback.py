"""Feedback tab - lets an approved (Streamlit Cloud viewer-list) user file
a bug/improvement/new-feature note as a GitHub Issue on this repo,
tagged with the submitter's authenticated email, then lists the repo's
currently open issues below the form. See execution-plan.md Phase G.
"""

import requests
import streamlit as st

GITHUB_REPO = "alexanderfache6/hsfl-archive"
GITHUB_API_BASE = "https://api.github.com"

FEEDBACK_TYPES = ["Bug", "Improvement", "New Feature"]
REAL_PAGES = ["History", "Seasons", "Matchups", "Managers", "Players", "Drafts"]
DESCRIPTION_MAX_CHARS = 200


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


def _render_feedback_form() -> None:
    st.subheader("Submit Feedback")

    viewer_email = _viewer_email()
    if viewer_email:
        st.caption(f"Submitting as {viewer_email}")
    else:
        st.caption("Submitting anonymously (no Streamlit Cloud login detected - expected in local dev).")

    feedback_type = st.radio("Type", FEEDBACK_TYPES, key="feedback_type", horizontal=True)

    page_options = [*REAL_PAGES, "Other"] if feedback_type == "New Feature" else REAL_PAGES
    if st.session_state.get("feedback_page") not in page_options:
        st.session_state["feedback_page"] = page_options[0]
    selected_page = st.radio("Page", page_options, key="feedback_page", horizontal=True)

    description = st.text_input("Description", max_chars=DESCRIPTION_MAX_CHARS, key="feedback_description")

    if st.button("Submit"):
        if not description.strip():
            st.warning("Description can't be empty.")
            return
        if not _github_token():
            st.error("GitHub integration isn't configured (missing the 'github_token' secret) - can't submit right now.")
            return

        title = f"[{feedback_type}] {description}"
        body_lines = [
            f"**Type:** {feedback_type}",
            f"**Page:** {selected_page}",
            f"**Description:** {description}",
            f"**Submitted by:** {viewer_email or '_unknown (local/dev)_'}",
        ]

        try:
            issue = _create_github_issue(title, "\n\n".join(body_lines), ISSUE_LABELS_BY_TYPE[feedback_type])
        except requests.RequestException as error:
            st.error(f"Couldn't submit feedback - GitHub API error: {error}")
            return

        st.success(f"Thanks! Filed as [#{issue['number']}]({issue['html_url']}).")


@st.cache_data(ttl=60)
def _open_issues() -> list[dict]:
    """The repo's currently open issues, PRs excluded (GitHub's issues
    endpoint returns both - a PR's payload carries its own "pull_request"
    key, which is what's used to tell them apart). Cached for 60s so a
    page rerun (e.g. after submitting feedback) doesn't refetch every
    time - open issues don't change that fast.
    """
    token = _github_token()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(
        f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/issues",
        headers=headers,
        params={"state": "open", "per_page": 100},
        timeout=10,
    )
    response.raise_for_status()
    return [issue for issue in response.json() if "pull_request" not in issue]


def _render_open_issues() -> None:
    st.subheader("Open Issues")
    try:
        issues = _open_issues()
    except requests.RequestException as error:
        st.info(f"Couldn't load open issues right now ({error}).")
        return

    if not issues:
        st.info("No open issues.")
        return

    for issue in issues:
        label_text = ", ".join(label["name"] for label in issue["labels"]) if issue["labels"] else ""
        st.markdown(f"**[#{issue['number']} {issue['title']}]({issue['html_url']})**" + (f" · {label_text}" if label_text else ""))


def render_feedback_page() -> None:
    _render_feedback_form()
    st.divider()
    _render_open_issues()
