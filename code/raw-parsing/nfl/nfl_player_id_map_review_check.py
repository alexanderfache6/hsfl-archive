"""Reads archive/nfl_player_id_map_to_review.json (your hand-edited copy
from nfl_player_id_map_review.py) and confirms every "ambiguous" player
has been resolved - resolution here means you set "espn_id" directly on
the entry (picked from its "candidates" list, or looked up externally),
NOT trimming "candidates" down to one. "candidates" is left completely
untouched either way, so the original search results stay available for
later spot-checking.

Every ambiguous player with a non-empty "espn_id" is PROMOTED in place:
"status" becomes "matched_manual" - this is what nfl_player_stats.py
actually looks for. The (possibly-partially-promoted) file is always
written back to archive/nfl_player_id_map_to_review.json, so partial
progress across multiple review sessions is never lost.

If EVERY ambiguous player now has an espn_id, this file is then renamed
to become the real archive/nfl_player_id_map.json - the confirmed,
authoritative map nfl_player_stats.py reads and nfl_player_id_map.py
treats as already-resolved on its own next rerun. If any are still
unresolved (no espn_id set), no rename happens -
archive/nfl_player_id_map.json (if it already exists from an earlier,
fully-clean review) is left exactly as-is.

Usage:
    python nfl_player_id_map_review_check.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils import ARCHIVE_DIRECTORY, write_json  # noqa: E402

TO_REVIEW_PATH = ARCHIVE_DIRECTORY / "nfl_player_id_map_to_review.json"
CONFIRMED_ID_MAP_PATH = ARCHIVE_DIRECTORY / "nfl_player_id_map.json"


def _load_to_review() -> dict[str, dict]:
    if not TO_REVIEW_PATH.exists():
        raise SystemExit(f"{TO_REVIEW_PATH} not found - run nfl_player_id_map_review.py first.")
    return json.loads(TO_REVIEW_PATH.read_text())


def check_and_promote(to_review: dict[str, dict]) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """(promoted, unresolved) - promoted = ambiguous entries with a
    hand-set espn_id, mutated in place to "matched_manual" (candidates
    left untouched); unresolved = ambiguous entries still with no
    espn_id set. Non-ambiguous entries (already
    "matched"/"matched_manual"/"unmatched") are left untouched and
    appear in neither list."""
    promoted, unresolved = [], []
    for player_id, entry in to_review.items():
        if entry.get("status") != "ambiguous":
            continue
        if entry.get("espn_id"):
            entry["status"] = "matched_manual"
            promoted.append((player_id, entry))
        else:
            unresolved.append((player_id, entry))
    return promoted, unresolved


def main() -> None:
    to_review = _load_to_review()
    promoted, unresolved = check_and_promote(to_review)

    if promoted:
        print(f"Resolved this run ({len(promoted)}):")
        for player_id, entry in sorted(promoted, key=lambda pair: pair[1]["name"]):
            espn_id = entry["espn_id"]
            matches_candidate = any(candidate["espn_id"] == espn_id for candidate in entry.get("candidates", []))
            note = "" if matches_candidate else "  (NOTE: not in original candidates list - double check)"
            print(f"  [{player_id}] {entry['name']} -> espn_id={espn_id} (matched_manual){note}")
        print()

    if unresolved:
        print(f"Still need editing ({len(unresolved)} - set \"espn_id\" by hand for each):")
        for player_id, entry in sorted(unresolved, key=lambda pair: pair[1]["name"]):
            print(f"  [{player_id}] {entry['name']} ({entry['position']}) - no espn_id set")
            for candidate in entry.get("candidates", []):
                print(f"      espn_id={candidate['espn_id']:<10} {candidate['name']} - {candidate['team']}")
        print()

    write_json(TO_REVIEW_PATH, to_review)

    if unresolved:
        print(f"{len(unresolved)} player(s) not yet resolved - keep editing {TO_REVIEW_PATH.name}, then re-run this script.")
        return

    os.replace(TO_REVIEW_PATH, CONFIRMED_ID_MAP_PATH)
    print(f"All ambiguous players resolved. Renamed {TO_REVIEW_PATH.name} -> {CONFIRMED_ID_MAP_PATH.name} (now the confirmed id map).")


if __name__ == "__main__":
    main()
