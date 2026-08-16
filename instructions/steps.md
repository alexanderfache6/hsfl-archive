# HSFL Archive — Pipeline Steps


```bash
conda env create -f environment.yml   # one-time
conda run -n hsfl-archive playwright install   # one-time, for Playwright-based fetchers
```

```bash
conda env export --no-builds -f environment.yml
```

---

## Step 1 — Load raw fantasy football info

From `code/raw-parsing/`, fetch every raw page for one season (static
pages, team homes, weekly rosters, weekly game centers, transactions):

```bash
cd code/raw-parsing
conda run -n hsfl-archive python3 fetch_season.py --year 2025
```

Loop across every season to (re)fetch the whole archive:

```bash
cd code/raw-parsing
for year in $(seq 2012 2025); do
  conda run -n hsfl-archive python3 fetch_season.py --year "$year"
done
```

Output: raw HTML under `archive/raw/{year}/...`, each with a
`*.meta.json` sidecar recording URL/status/fetch time. Already-fetched
pages are skipped on re-run (see `utils.already_fetched`) — a page
cached with a failed status is retried automatically.

---

## Step 2 — Parse

From `code/raw-parsing/`, parse one season's raw HTML into
`archive/parsed/{year}/*.json` (metadata, standings, draft, playoffs,
schedule, rosters, matchups, transactions):

```bash
cd code/raw-parsing
conda run -n hsfl-archive python3 parse_season.py --year 2025
```

Loop across every season:

```bash
cd code/raw-parsing
for year in $(seq 2012 2025); do
  conda run -n hsfl-archive python3 parse_season.py --year "$year"
done
```

Requires Step 1 to have already run for that year.

Then build the cross-season registries (each reads every already-parsed
season, no arguments needed):

```bash
cd code/raw-parsing
conda run -n hsfl-archive python3 managers.py       # archive/managers.json
conda run -n hsfl-archive python3 players.py        # archive/players.json
conda run -n hsfl-archive python3 team_logos.py     # downloads fantasy team logos, augments managers.json
```

---

## Step 3 — Aggregate

From `code/stats-aggregation/`, aggregate one season's parsed data into
`archive/aggregated/{year}/*.json` (standings, breakdown, coaching, true
ranking, players started, post-season stats, head-to-head, records):

```bash
cd code/stats-aggregation
conda run -n hsfl-archive python3 aggregate_season.py --year 2025
```

Loop across every season:

```bash
cd code/stats-aggregation
for year in $(seq 2012 2025); do
  conda run -n hsfl-archive python3 aggregate_season.py --year "$year"
done
```

Requires Step 2 to have already run for that year (reads only
`archive/parsed/{year}/*.json`).

Then build the cross-season ("History" tab) files — run these LAST,
after every season's `aggregate_season.py` has completed, since they
combine per-season output rather than re-deriving it:

```bash
cd code/stats-aggregation
conda run -n hsfl-archive python3 all_time.py             # all_time_champions.json, all_time_manager_stats.json, all_time_records.json
conda run -n hsfl-archive python3 player_ownership.py     # archive/player_ownership.json (per-player weekly ownership timeline)
```

---

## Step 4 — Get NFL stats

From `code/raw-parsing/nfl/`. Two independent, one-time-ish real-NFL
data sources (ESPN), plus the newer player-level backfill pipeline:

```bash
cd code/raw-parsing/nfl
conda run -n hsfl-archive python3 nfl_bye_weeks.py     # archive/nfl_bye_weeks.json - every team's bye week per season
conda run -n hsfl-archive python3 nfl_team_logos.py    # real NFL team logos (one-time; re-run only on a rebrand)
```

Real per-player, per-week NFL stats (independent of fantasy roster
status — backfills weeks a player wasn't rostered) is a four-stage
pipeline built around one file rename. **Run these in order, and do not
run stage 4 (stat generation) until stage 3's manual review is fully
resolved:**

```bash
cd code/raw-parsing/nfl

# 1. Fresh full pull: resolve every rostered-at-least-once player to an
#    ESPN athlete ID. Long-running (~1 request per rostered player,
#    politely rate-limited). Writes archive/nfl_player_id_map_to_review_original.json
#    (NOT archive/nfl_player_id_map.json - see stage 3).
conda run -n hsfl-archive python3 nfl_player_id_map.py

# 2. Print every "ambiguous" player (multiple ESPN candidates) and make
#    your editable working copy, archive/nfl_player_id_map_to_review.json
#    (a full copy of every player, not just the ambiguous ones) - only
#    created the first time, never overwritten on a later run.
conda run -n hsfl-archive python3 nfl_player_id_map_review.py

# 3. STOP HERE: hand-edit archive/nfl_player_id_map_to_review.json - for
#    each ambiguous player, set their "espn_id" field directly to the
#    correct one (pick it from the printed "candidates" list, or look it
#    up externally if none of them are right). Leave "candidates"
#    untouched - it stays as a record for later spot-checking. Then
#    confirm:
conda run -n hsfl-archive python3 nfl_player_id_map_review_check.py

# 4. Once stage 3 reports every ambiguous player resolved, it renames
#    nfl_player_id_map_to_review.json -> archive/nfl_player_id_map.json
#    automatically - THAT rename is what makes stage 4 runnable. Fetch
#    each resolved player's real NFL regular-season stats, per week,
#    for a season range:
conda run -n hsfl-archive python3 nfl_player_stats.py --start-season 2012 --end-season 2025

# Or the full default range (2012 through the current season):
conda run -n hsfl-archive python3 nfl_player_stats.py
```

Notes:
- `archive/nfl_player_id_map.json` is a special, protected filename —
  it is ONLY ever written by stage 3's automatic rename, once every
  ambiguous player is resolved. Neither `nfl_player_id_map.py` nor
  `nfl_player_id_map_review.py` writes it directly.
- `nfl_player_stats.py` only fetches players with a resolved
  `"matched"`/`"matched_manual"` entry in `archive/nfl_player_id_map.json`
  — if that file doesn't exist yet, stage 3 hasn't fully completed.
- Re-running `nfl_player_id_map.py` later (e.g. to pick up newly-
  rostered players) prefers the confirmed `archive/nfl_player_id_map.json`
  over its own fresh pull for anyone already resolved there, so a
  completed manual review is never lost or re-queried.
- `"unmatched"` players (zero candidates found) aren't part of stage
  2/3's ambiguous-review flow, but can still be resolved the same way
  by hand-editing their entry in `archive/nfl_player_id_map_to_review.json`
  before running stage 3.
- Safe to re-run `nfl_player_stats.py` weekly during an active season —
  every completed past season stays cached forever; only the current
  in-progress season is force-refetched each run.
- Output: `archive/nfl_player_stats.json`. Raw scoring-conversion to
  this league's own fantasy points (via `data_loader.py`'s
  `compute_stat_fantasy_points`) is a separate, not-yet-built step —
  this pipeline only collects the raw NFL stat categories.

---

## Step 5 — Run the Streamlit app

From `frontend/`:

```bash
cd frontend
conda run -n hsfl-archive streamlit run app.py
```

Or, with the conda env already activated (`conda activate hsfl-archive`):

```bash
cd frontend
streamlit run app.py
```

Opens at `http://localhost:8501`. Pure read-only view over the
committed `archive/*.json` output — no live fetching or database, so it
only reflects whatever Steps 1–4 have already produced on disk.

---

## Weekly Update (during an active season)

Once a new week's games/transactions have happened, run just this
subset to pick them up — every command below is idempotent, so it's
safe to run every week without re-doing prior weeks' work. Substitute
the current season's year for `$YEAR` (e.g. `YEAR=2026`).

```bash
YEAR=$(date +%Y)   # or the active league season, if different from the calendar year

# 1. Fetch this week's new raw pages for the current season (already-
#    fetched weeks/pages are skipped automatically).
cd code/raw-parsing
conda run -n hsfl-archive python3 fetch_season.py --year "$YEAR"

# 2. Re-parse the current season (only the newly-fetched raw pages
#    produce new/changed parsed output).
conda run -n hsfl-archive python3 parse_season.py --year "$YEAR"

# 3. Refresh the cross-season player/manager registries in case a new
#    player was rostered/dropped for the first time this week.
conda run -n hsfl-archive python3 players.py
conda run -n hsfl-archive python3 managers.py

# 4. Re-aggregate the current season's fantasy stats, then rebuild the
#    cross-season ("History" tab) files on top of it.
cd ../stats-aggregation
conda run -n hsfl-archive python3 aggregate_season.py --year "$YEAR"
conda run -n hsfl-archive python3 all_time.py
conda run -n hsfl-archive python3 player_ownership.py

# 5. Pick up any newly-rostered player's ESPN ID. Then check for new
#    ambiguous matches and hand-resolve them (see Step 4 above) BEFORE
#    refreshing real NFL stats - nfl_player_stats.py only runs against
#    the confirmed archive/nfl_player_id_map.json, which stage 3 below
#    only (re)writes once every ambiguous player is resolved.
#    nfl_player_stats.py itself only force-refetches the CURRENT active
#    season (see its own docstring) - every completed past season stays
#    cached, so this step is cheap week to week, not a full re-crawl.
cd ../raw-parsing/nfl
conda run -n hsfl-archive python3 nfl_player_id_map.py
conda run -n hsfl-archive python3 nfl_player_id_map_review.py         # review any new ambiguous players
# ...hand-edit archive/nfl_player_id_map_to_review.json if it printed any...
conda run -n hsfl-archive python3 nfl_player_id_map_review_check.py   # confirms + renames to archive/nfl_player_id_map.json once clean
conda run -n hsfl-archive python3 nfl_player_stats.py
```

Nothing needs re-running against the Streamlit app itself — it reads
`archive/*.json` fresh on every page load (subject to its own
`st.cache_resource` caching, cleared on a process restart).
