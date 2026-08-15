"""Reads archive/nfl_player_id_map_to_review_original.json (the fresh
full pull written by nfl_player_id_map.py) and prints every player whose
status is "ambiguous" - more than one NFL/football candidate came back
from the ESPN search, so it couldn't be auto-resolved.

Also makes your editable working copy: archive/nfl_player_id_map_to_review.json
- a COPY OF THE FULL MAP (every player, not just the ambiguous ones),
since that file eventually becomes archive/nfl_player_id_map.json
itself (see nfl_player_id_map_review_check.py) once every ambiguous
player in it is resolved. Only created the FIRST time (i.e. if it
doesn't already exist) - a later run of this script never overwrites
it, so in-progress manual edits always survive a rerun.

To resolve a player: edit their entry in
archive/nfl_player_id_map_to_review.json so its "candidates" list holds
EXACTLY ONE entry - the correct one (delete the wrong candidates; if
none of them are right, replace the list with a single hand-looked-up
{"espn_id", "name", "team"}). Once every ambiguous player you want
resolved is down to one candidate, run
nfl_player_id_map_review_check.py - it promotes each one to
"matched_manual" and, once none are left unresolved, renames this
working copy to become the real archive/nfl_player_id_map.json.

This script itself never writes to archive/nfl_player_id_map.json or
archive/nfl_player_id_map_to_review_original.json (the latter is only
ever (re)written by nfl_player_id_map.py).

Usage:
    python nfl_player_id_map_review.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import ARCHIVE_DIRECTORY, write_json  # noqa: E402

TO_REVIEW_ORIGINAL_PATH = ARCHIVE_DIRECTORY / "nfl_player_id_map_to_review_original.json"
TO_REVIEW_PATH = ARCHIVE_DIRECTORY / "nfl_player_id_map_to_review.json"


def _load_to_review_original() -> dict[str, dict]:
    if not TO_REVIEW_ORIGINAL_PATH.exists():
        raise SystemExit(f"{TO_REVIEW_ORIGINAL_PATH} not found - run nfl_player_id_map.py first.")
    return json.loads(TO_REVIEW_ORIGINAL_PATH.read_text())


def list_ambiguous(id_map: dict[str, dict]) -> list[tuple[str, dict]]:
    return sorted(
        ((player_id, entry) for player_id, entry in id_map.items() if entry.get("status") == "ambiguous"),
        key=lambda pair: pair[1]["name"],
    )


def main() -> None:
    id_map = _load_to_review_original()
    ambiguous = list_ambiguous(id_map)

    if not ambiguous:
        print("No ambiguous players - nothing to review.")
    else:
        print(f"{len(ambiguous)} player(s) need manual review (multiple ESPN candidates):\n")
        for player_id, entry in ambiguous:
            print(f"[{player_id}] {entry['name']} ({entry['position']})")
            for candidate in entry.get("candidates", []):
                print(f"    espn_id={candidate['espn_id']:<10} {candidate['name']} - {candidate['team']}")
            print()
        print(f"{len(ambiguous)} total.\n")

    if TO_REVIEW_PATH.exists():
        print(f"{TO_REVIEW_PATH} already exists - left untouched (your in-progress edits are safe).")
    else:
        write_json(TO_REVIEW_PATH, id_map)
        print(
            f"wrote {TO_REVIEW_PATH} ({len(id_map)} players, full copy) - edit the ambiguous players' "
            f"\"candidates\" down to one each, then run nfl_player_id_map_review_check.py"
        )


if __name__ == "__main__":
    main()
