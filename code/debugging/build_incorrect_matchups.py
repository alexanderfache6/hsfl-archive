"""One-off diagnostic script (not part of the regular pipeline) - sweeps
every archived matchup and writes code/debugging/incorrect-matchups.csv
listing every team-week where the Matchups tab's optimal-lineup "gains"
breakdown (frontend/pages_matchups.py's _optimal_lineup_details) doesn't
sum to the true optimal/actual point diff. See instructions/bugs.md bug 8
for the full history. DB-position players (2012's vestigial IDP slot) are
excluded from the optimizer entirely by _optimal_lineup_details itself -
this script's own diagnostic "optimal"/count computation mirrors that
exclusion, so the remaining rows should be confined to the one
still-open, pre-existing edge case: a week where a team's archived
lineup is genuinely short a starter.

Run from anywhere (paths are resolved from this file's own location, not
the working directory):
    python3 code/debugging/build_incorrect_matchups.py
"""

import csv
import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "frontend"))
from data_loader import build_manager_name_resolver, compute_optimal_lineup, team_id_to_manager_map
from pages_matchups import _optimal_lineup_details

resolver = build_manager_name_resolver()

rows = []
for f in sorted(glob.glob(str(REPO_ROOT / "archive/parsed/*/matchups/*.json"))):
    d = json.load(open(f))
    season = d["season"]
    week = d["week"]
    team_map = team_id_to_manager_map(season)
    for side_key in ("home", "away"):
        side = d[side_key]
        if not side.get("starters"):
            continue
        actual_total = sum(p["points"] for p in side["starters"])

        # Mirrors _optimal_lineup_details' own DB exclusion, so this
        # diagnostic's counts/reason match what the frontend actually
        # computes rather than reflecting the now-irrelevant DB slot.
        optimizable_starters = [p for p in side["starters"] if p.get("position") != "DB"]
        optimizable_bench = [p for p in side["bench"] if p.get("position") != "DB"]
        optimal = compute_optimal_lineup(optimizable_starters + optimizable_bench, season)
        actual_ids = {p["player_id"] for p in optimizable_starters if p.get("player_id")}
        optimal_ids = {p["player_id"] for p in optimal["optimal_starters"] if p.get("player_id")}
        added = [p for p in optimal["optimal_starters"] if p.get("player_id") and p["player_id"] not in actual_ids]

        details = _optimal_lineup_details(side, season)
        true_diff = details["optimal_points"] - actual_total
        gains_sum = sum(details["gains"].values())
        if abs(true_diff - gains_sum) <= 0.01:
            continue

        team_id = side["team_id"]
        manager_name = resolver.get(team_map.get(team_id, {}).get("manager_id", ""), team_map.get(team_id, {}).get("display_name", ""))
        team_name = team_map.get(team_id, {}).get("team_name", "")

        if len(optimizable_starters) < len(optimal["optimal_starters"]):
            reason = f"Actual lineup has only {len(optimizable_starters)} non-DB starter(s) listed but the optimal solve fills {len(optimal['optimal_starters'])} slots (that week's archived roster is short a starter)"
        else:
            reason = "Unknown - added/removed count mismatch not explained by known causes"

        unattributed = [p["player_name"] for p in added if p["player_id"] not in details["gains"]]

        rows.append(
            {
                "season": season,
                "week": week,
                "team_id": team_id,
                "manager": manager_name,
                "team_name": team_name,
                "true_diff": round(true_diff, 2),
                "gains_sum": round(gains_sum, 2),
                "difference": round(true_diff - gains_sum, 2),
                "num_actual_starters": len(optimizable_starters),
                "num_optimal_starters": len(optimal["optimal_starters"]),
                "unattributed_added_players": "; ".join(unattributed),
                "reason": reason,
            }
        )

out_path = Path(__file__).resolve().parent / "incorrect-matchups.csv"
with open(out_path, "w", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=[
            "season", "week", "team_id", "manager", "team_name", "true_diff", "gains_sum",
            "difference", "num_actual_starters", "num_optimal_starters", "unattributed_added_players", "reason",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

print("wrote", len(rows), "rows to", out_path)
