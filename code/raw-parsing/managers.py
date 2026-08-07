"""Builds archive/managers.json, the cross-season manager registry. See instructions.md section 2b.

Reconciliation note confirmed 2026-08-06: NFL.com exposes a persistent
per-manager userId (see parse.py's manager_id extraction), so unlike the
fuzzy display-name matching instructions.md originally called for, managers
here are grouped by that stable ID directly - no guessing needed. A team
only lands in `unresolved` if its metadata.json entry has no manager_id at
all (the schedule page didn't expose one for that team).
"""

import json

from utils import MANAGERS_PATH, PARSED_DIRECTORY, write_json

# Manual disambiguation for managers who share a display_name with someone
# else in the league (confirmed 2026-08-07: two different persistent
# manager_ids are both named "Alex"). Empty string = no disambiguation
# needed. UI code should prefer this over display_names_seen whenever
# it's non-empty - see frontend/data_loader.py's resolve_manager_name().
DISPLAY_NAME_ALTERNATES = {
    "5049083": "Alex F",
    "22089610": "Alex K",
}


def discover_parsed_seasons() -> list[int]:
    if not PARSED_DIRECTORY.exists():
        return []
    return sorted(int(child.name) for child in PARSED_DIRECTORY.iterdir() if child.is_dir() and child.name.isdigit())


def build_managers_registry(years: list[int]) -> dict:
    managers_by_id = {}
    unresolved = []

    for year in years:
        metadata_path = PARSED_DIRECTORY / str(year) / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = json.loads(metadata_path.read_text())
        for team in metadata.get("teams", []):
            manager_id = team.get("manager_id")
            team_id = team.get("team_id")
            team_name = team.get("team_name")
            display_name = team.get("manager_display_name")

            if not manager_id:
                unresolved.append({"season": year, "team_id": team_id, "display_name": display_name, "reason": "no manager_id found in metadata.json for this team"})
                continue

            entry = managers_by_id.setdefault(
                manager_id,
                {
                    "manager_id": manager_id,
                    "display_names_seen": [],
                    "display_names_seen_alternate": DISPLAY_NAME_ALTERNATES.get(manager_id, ""),
                    "seasons": [],
                    "notes": "",
                },
            )
            if display_name and display_name not in entry["display_names_seen"]:
                entry["display_names_seen"].append(display_name)
            entry["seasons"].append({"season": year, "team_id": team_id, "team_name": team_name})

    managers = sorted(managers_by_id.values(), key=lambda m: m["manager_id"])
    return {"managers": managers, "unresolved": unresolved}


def main() -> None:
    years = discover_parsed_seasons()
    registry = build_managers_registry(years)
    write_json(MANAGERS_PATH, registry)
    print(f"wrote {MANAGERS_PATH}: {len(registry['managers'])} managers, {len(registry['unresolved'])} unresolved, seasons={years}")


if __name__ == "__main__":
    main()
