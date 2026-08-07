"""archive/index.json (machine-readable manifest) and progress.html (dashboard). See instructions.md sections 4-5."""

import json
from datetime import datetime, timezone

from fetch import discover_team_ids_and_weeks
from utils import ERROR_LOG_PATH, INDEX_PATH, MANAGERS_PATH, PARSED_DIRECTORY, PROGRESS_DIRECTORY, RAW_DIRECTORY

PAGE_TYPES = [
    "metadata",
    "standings_final",
    "standings_regular",
    "draft",
    "playoffs_championship",
    "playoffs_consolation",
    "schedule",
    "weekly_matchups",
    "transactions",
    "rosters",
]


def load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text())
    return {"generated_at": "", "seasons": {}, "managers_registry": {"total_managers": None, "unresolved_count": 0}}


def save_index(index: dict) -> None:
    index["generated_at"] = datetime.now(timezone.utc).isoformat()
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2))


def update_index(year: int, page_type: str, status: str) -> None:
    """status: 'ok' | 'partial' | 'missing'"""
    index = load_index()
    season = index["seasons"].setdefault(str(year), {"errors": []})
    season[page_type] = status
    save_index(index)


def compute_season_manifest(year: int) -> dict:
    """Inspects archive/parsed/{year}/ and archive/raw/{year}/ on disk to
    build a full section-4 manifest entry, rather than relying on the
    lighter-weight per-page status updates written during fetching."""
    parsed_directory = PARSED_DIRECTORY / str(year)
    raw_directory = RAW_DIRECTORY / str(year)

    def parsed_exists(filename: str) -> str:
        return "ok" if (parsed_directory / filename).exists() else "missing"

    team_ids, weeks = discover_team_ids_and_weeks(year)

    schedule_path = parsed_directory / "schedule.json"
    weeks_fetched = []
    if schedule_path.exists():
        schedule = json.loads(schedule_path.read_text())
        weeks_fetched = [w["week"] for w in schedule["weeks"] if w["matchups"]]

    transactions_directory = raw_directory / "transactions"
    transactions_pages_fetched = len(list(transactions_directory.glob("transactions_page_*.html"))) if transactions_directory.exists() else 0
    transactions_complete = (parsed_directory / "transactions.json").exists()

    rosters_directory = parsed_directory / "rosters"
    rosters_fetched = len(list(rosters_directory.glob("*.json"))) if rosters_directory.exists() else 0

    season_errors = []
    if ERROR_LOG_PATH.exists():
        for line in ERROR_LOG_PATH.read_text().splitlines():
            entry = json.loads(line)
            if f"/history/{year}/" in entry.get("url", ""):
                season_errors.append(entry)

    return {
        "metadata": parsed_exists("metadata.json"),
        "standings_final": parsed_exists("standings.json"),
        "standings_regular": parsed_exists("standings.json"),
        "draft": parsed_exists("draft.json"),
        "playoffs_championship": parsed_exists("playoffs.json"),
        "playoffs_consolation": parsed_exists("playoffs.json"),
        "schedule": parsed_exists("schedule.json"),
        "weeks_fetched": weeks_fetched,
        "weeks_total": len(weeks),
        "transactions": "ok" if transactions_complete else "missing",
        "transactions_pages_fetched": transactions_pages_fetched,
        "transactions_complete": transactions_complete,
        "rosters": "ok" if rosters_fetched and rosters_fetched == len(team_ids) * len(weeks) else ("partial" if rosters_fetched else "missing"),
        "rosters_fetched": rosters_fetched,
        "rosters_expected": len(team_ids) * len(weeks),
        "errors": season_errors,
    }


def update_season_manifest(year: int) -> None:
    index = load_index()
    index["seasons"][str(year)] = compute_season_manifest(year)
    index["managers_registry"] = load_managers_summary()
    save_index(index)


def load_managers_summary() -> dict:
    if MANAGERS_PATH.exists():
        managers_data = json.loads(MANAGERS_PATH.read_text())
        return {
            "total_managers": len(managers_data.get("managers", [])),
            "unresolved_count": len(managers_data.get("unresolved", [])),
        }
    return {"total_managers": 0, "unresolved_count": 0}


def _count_season_files(year: int) -> tuple[int, int]:
    """Total files (recursive) under archive/raw/{year} and archive/parsed/{year}."""
    raw_directory = RAW_DIRECTORY / str(year)
    parsed_directory = PARSED_DIRECTORY / str(year)
    raw_count = sum(1 for _ in raw_directory.rglob("*") if _.is_file()) if raw_directory.exists() else 0
    parsed_count = sum(1 for _ in parsed_directory.rglob("*") if _.is_file()) if parsed_directory.exists() else 0
    return raw_count, parsed_count


def _season_completion_fraction(season: dict) -> float:
    # rosters is excluded here since rosters_fraction below already covers
    # it more precisely (partial roster completion, not just ok/missing)
    binary_fields = [season.get(pt, "missing") == "ok" for pt in PAGE_TYPES if pt not in ("weekly_matchups", "rosters")]
    weeks_fraction = (len(season.get("weeks_fetched", [])) / season["weeks_total"]) if season.get("weeks_total") else 0
    rosters_fraction = (season.get("rosters_fetched", 0) / season["rosters_expected"]) if season.get("rosters_expected") else 0
    all_fractions = [1.0 if b else 0.0 for b in binary_fields] + [weeks_fraction, rosters_fraction]
    return sum(all_fractions) / len(all_fractions) if all_fractions else 0.0


def generate_progress_html() -> None:
    index = load_index()
    managers_summary = load_managers_summary()
    seasons_sorted = sorted(index["seasons"].keys())

    table_rows = []
    all_errors = []
    completion_fractions = []
    total_raw_files = 0
    total_parsed_files = 0
    for year in seasons_sorted:
        season = index["seasons"][year]
        table_cells = "".join(
            f'<td class="{season.get(page_type, "missing")}">{season.get(page_type, "missing")}</td>'
            for page_type in PAGE_TYPES
            if page_type != "weekly_matchups"
        )
        weeks_fetched = len(season.get("weeks_fetched", []))
        weeks_total = season.get("weeks_total", 0)
        rosters_fetched = season.get("rosters_fetched", 0)
        rosters_expected = season.get("rosters_expected", 0)
        completion_fraction = _season_completion_fraction(season)
        completion_fractions.append(completion_fraction)
        completion_percent = round(completion_fraction * 100)
        raw_file_count, parsed_file_count = _count_season_files(int(year))
        total_raw_files += raw_file_count
        total_parsed_files += parsed_file_count

        table_rows.append(
            f"<tr><th>{year}</th>{table_cells}"
            f'<td>{weeks_fetched}/{weeks_total}</td>'
            f'<td>{rosters_fetched}/{rosters_expected}</td>'
            f'<td>{raw_file_count}</td>'
            f'<td>{parsed_file_count}</td>'
            f'<td><div class="bar"><div class="bar-fill" style="width:{completion_percent}%"></div></div> {completion_percent}%</td>'
            "</tr>"
        )
        all_errors.extend({**e, "season": year} for e in season.get("errors", []))

    table_headers = "".join(f"<th>{page_type}</th>" for page_type in PAGE_TYPES if page_type != "weekly_matchups")
    overall_percent = round(100 * sum(completion_fractions) / len(completion_fractions)) if completion_fractions else 0

    errors_html = "".join(
        f"<li><code>{e.get('url', '')}</code> - {e.get('error', '')} (season {e.get('season')})</li>" for e in all_errors
    ) or "<li>None</li>"

    html_content = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>HSFL Archive Progress</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: center; font-size: 0.85rem; }}
td.ok {{ background: #c8f7c5; }}
td.partial {{ background: #fff3b0; }}
td.missing {{ background: #f7c5c5; }}
.summary {{ margin-bottom: 1rem; }}
.bar {{ display: inline-block; width: 80px; height: 10px; background: #eee; vertical-align: middle; }}
.bar-fill {{ height: 100%; background: #4caf50; }}
ul.errors {{ font-size: 0.85rem; }}
</style></head>
<body>
<h1>HSFL Archive Progress</h1>
<p class="summary">Generated: {index['generated_at']}</p>
<p class="summary">Overall completion: <strong>{overall_percent}%</strong></p>
<p class="summary">Managers resolved: {managers_summary['total_managers']} &mdash;
Unresolved: {managers_summary['unresolved_count']}</p>
<p class="summary">Total files on disk across all seasons: <strong>{total_raw_files}</strong> raw
&mdash; <strong>{total_parsed_files}</strong> parsed
(<strong>{total_raw_files + total_parsed_files}</strong> total)</p>
<table>
<tr><th>Season</th>{table_headers}<th>Weeks</th><th>Rosters</th><th>Raw files</th><th>Parsed files</th><th>Completion</th></tr>
{''.join(table_rows)}
</table>
<h2>Errors ({len(all_errors)})</h2>
<ul class="errors">{errors_html}</ul>
</body></html>
"""
    PROGRESS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (PROGRESS_DIRECTORY / "progress.html").write_text(html_content)
