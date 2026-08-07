# Execution Log — Terminal Commands

Commands the user needs to run manually, in order, as the archive process
progresses. Run each from the `hsfl-archive` project root unless noted.

## Running the pipeline on any season

**Updated 2026-08-07:** all fetch/parse code moved from `code/` to
`code/raw-parsing/` for organization (aggregation work lives in a
separate `code/stats-aggregation/` directory instead - see Phase F in
`execution-plan.md`). Run everything below from `code/raw-parsing/`, not
`code/`.

Once Phase A/B/C/D below have validated the approach (done for 2025 as of
2026-08-07), running a new year is 4 idempotent, resumable commands from
`code/raw-parsing/` - substitute `--year 2024` for whichever season. Each
step can be re-run safely; already-downloaded/parsed files are skipped or
overwritten in place, not duplicated.

```bash
# 1. Fetch all raw HTML (~350-450 live requests at a 1.5s polite delay,
#    roughly 10-15 min for a full season; skips anything already on disk
#    with a cached 2xx response)
conda run -n hsfl-archive python3 fetch_season.py --year 2024

# 2. Parse all raw HTML into archive/parsed/2024/*.json
conda run -n hsfl-archive python3 parse_season.py --year 2024

# 3. Rebuild archive/managers.json across ALL seasons parsed so far
#    (not just the new one - it auto-discovers every archive/parsed/{year}/
#    directory and merges them by persistent manager userId)
conda run -n hsfl-archive python3 managers.py

# 4. Rebuild archive/index.json and archive/progress/progress.html for the
#    new season (run once per season parsed; each call only touches that
#    season's entry in index.json, not the others)
conda run -n hsfl-archive python3 -c "
from manifest import update_season_manifest, generate_progress_html
update_season_manifest(2024)
generate_progress_html()
"
```

After any of these, it's worth a quick spot-check against `bugs.md`'s
"generalization risks" section before trusting the output blindly - those
are assumptions validated only against 2025 (auction draft, this league's
placement-game naming, this year's roster config, etc.) that could behave
differently on another season's actual markup.

## Phase A — Environment setup

1. Create the conda environment from `environment.yml`:
   ```bash
   conda env create -f environment.yml
   ```

2. Activate the environment:
   ```bash
   conda activate hsfl-archive
   ```

3. Install Playwright's browser binaries (needed for the JS-rendered
   fallback in `fetch.py`; not something conda/pip installs automatically):
   ```bash
   playwright install chromium
   ```

4. Syntax-check the scaffolded `code/` files (run by Claude, not the user,
   as a sanity check after the naming-convention rewrite):
   ```bash
   cd code && python3 -m py_compile utils.py fetch.py parse.py manifest.py run.py
   ```
   Re-confirmed later in the same session via `conda run` (no shell
   activation needed); the file list is unchanged since `fetch_season.py`
   (see Phase B, step 6) is validated by running it directly rather than
   through `py_compile`:
   ```bash
   conda run -n hsfl-archive python3 -m py_compile utils.py fetch.py parse.py manifest.py run.py
   ```

## Phase B — Fetch script development

5. Probe individual HSFL endpoints to confirm URL patterns before writing
   the consolidated fetch script (run by Claude only, interactively, not
   the user). One-off `python3 -c "..."` snippets against league_home,
   settings, standings, schedule, draft_results, playoffs,
   playoffs_consolation, teamhome, teamgamecenter, and transactions —
   superseded by `fetch_season.py` (step 6) and not needed verbatim.

6. Run the consolidated, resumable per-season fetch script — pulls static
   pages, discovers team_ids/weeks, then fetches team home pages, weekly
   rosters, weekly game centers, and paginated transactions, skipping
   anything already saved on disk (already running in the background for
   `--year 2025` as of this log update):
   ```bash
   conda run -n hsfl-archive python3 fetch_season.py --year 2025
   ```
   Reuse this same command for all other years (2012–2024) and for
   re-runs of 2025, just changing `--year`, once Phase B validation is
   complete.

7. `fetch_season.py --year 2025` completed (81 transactions pages fetched,
   170 rosters, 170 game centers, 10 team homes, 8 static pages). Post-run
   review found two bugs, both fixed by Claude (no user action needed):
   - The transactions pagination stop condition compared consecutive pages
     for exact-duplicate content, but every page (including empty ones)
     embeds volatile per-request ad-tracking fields (`AD_ORD`, `TIME`), so
     no two fetches were ever byte-identical. It ran to the 2000-offset
     safety cap instead of stopping at the real end of data (offset 1500,
     confirmed via the page's "No transactions" empty-state text). Fixed
     `fetch.py`'s `fetch_all_transactions_pages` to detect that text
     instead of diffing page content.
   - Deleted the 20 wasted empty-duplicate pages (offsets 1525–2000).
   - Re-ran the transactions fetch to confirm the fix (idempotent - all 61
     correct pages already on disk, 0 new network calls, stopped exactly
     at the empty page, no safety-cap error logged):
     ```bash
     conda run -n hsfl-archive python3 -c "
     import httpx
     from fetch import fetch_all_transactions_pages
     with httpx.Client(timeout=30) as client:
         print(fetch_all_transactions_pages(client, 2025))
     "
     ```

8. Reorganized transaction raw files into their own subdirectory (moved
   `transactions_page_*.html(.meta.json)` out of the flat `{year}/` dir
   into `{year}/transactions/`), and updated `utils.raw_path` /
   `fetch.fetch_all_transactions_pages` to write there going forward:
   ```bash
   cd archive/raw/2025 && mkdir -p transactions && mv transactions_page_*.html transactions_page_*.html.meta.json transactions/
   ```
   `instructions.md` §1 updated to reflect the new layout (no standalone
   scoreboard endpoint - matchups are per-team `gamecenter_week_{w}.html`
   files instead).

9. Re-compiled all `code/` files after the fixes above (run by Claude):
   ```bash
   conda run -n hsfl-archive python3 -m py_compile utils.py fetch.py parse.py manifest.py run.py fetch_season.py
   ```

## Phase C — Parser development (2025)

10. Fixed a Phase B fetch gap found while inspecting `draft_results.html`:
    the draft results page is paginated (`draftResultsDetail=1..16`, 10
    picks/page), so the Phase B fetch only captured picks 1-10 of 160.
    Replaced with two full-view URLs (`draftResultsDetail=0`, one per tab)
    and re-fetched (run by Claude):
    ```bash
    conda run -n hsfl-archive python3 -c "
    import httpx
    from fetch import fetch_page, SEASON_URL_TEMPLATES
    with httpx.Client(timeout=30) as client:
        for purpose in ('draft_results_by_nomination', 'draft_results_by_team'):
            relative_url_template, filename_template = SEASON_URL_TEMPLATES[purpose]
            print(purpose, fetch_page(client, 2025, relative_url_template, filename_template)[1])
    "
    ```

11. Wrote all 8 parsers in `parse.py` (metadata, standings, draft,
    playoffs, schedule, matchups, transactions, rosters) against the
    confirmed 2025 DOM structure, then validated them with a throwaway
    test script before wiring them into a real pipeline. Two real bugs
    found and fixed: `standings` crashed because a rank cell contains both
    a clean rank span and a nested rank-change badge (`"2" + "+1"` were
    concatenating into `"2+1"`); gamecenter box-score stats were silently
    empty because that page uses `<span class="statId-N">` instead of the
    roster page's `<td class="stat_N">`. (A third apparent bug - draft
    picks missing `auction_amount` - turned out to be correct: keeper
    picks have no `auctionCost` span in the source markup.)

12. Ran the reusable per-season parser (writes `archive/parsed/{year}/`
    from the raw HTML `fetch_season.py` already downloaded; reuse for all
    other years by changing `--year`):
    ```bash
    conda run -n hsfl-archive python3 parse_season.py --year 2025
    ```
    Output: `metadata.json`, `standings.json`, `draft.json` (160 picks),
    `playoffs.json`, `schedule.json`, 81 `matchups/*.json` (85 possible
    minus 4 bye-week gaps in weeks 15-16), `transactions.json` (1371
    transactions), 170 `rosters/*.json` - 257 files total, confirmed
    against expected counts.

13. Spot-checked parsed output against raw data by hand (run by Claude):
    champion (team_id 9, Sweeney's Genes, 11-3-0) matches across
    `standings.json` and `playoffs.json`; draft has exactly 160 picks
    ending at `overall_pick` 160; team 1's total auction spend sums to
    exactly $200, matching the league's budget cap from `settings.html`.

14. Built `archive/managers.json` (`code/raw-parsing/managers.py`) - much simpler than
    instructions.md section 2b originally called for, since NFL.com
    exposes a persistent per-manager `userId` (found embedded in
    `.userName` spans on schedule/gamecenter/transactions pages), so
    managers are grouped by that stable ID instead of fuzzy display-name
    matching. Result: 10/10 teams resolved, 0 unresolved.
    ```bash
    conda run -n hsfl-archive python3 managers.py
    ```

15. Generated `archive/index.json` and `archive/progress/progress.html`
    (`code/raw-parsing/manifest.py`, new `compute_season_manifest`/
    `update_season_manifest` functions) scoped to 2025. Found and fixed
    two bugs while validating the dashboard: the `transactions`/`rosters`
    status columns were never populated by `compute_season_manifest` (both
    showed "missing" despite being complete); the completion percentage
    double-counted rosters via both a binary ok/missing field and a
    fractional field, dragging 100% actual completion down to 82% on the
    dashboard. Also removed 18 stale log lines from
    `archive/progress/errors.log` left over from the already-fixed
    Phase B scoreboard-endpoint and transactions-pagination bugs, keeping
    1 genuine historical entry. Final result: 2025 shows 100% complete,
    all columns green, 10 managers resolved, 1 audit-trail error retained.
    ```bash
    conda run -n hsfl-archive python3 -c "
    from manifest import update_season_manifest, generate_progress_html
    update_season_manifest(2025)
    generate_progress_html()
    "
    ```

## Phase D — Bug fixes and end-to-end re-run (step 17)

Full findings in `instructions/bugs.md`. Three issues fixed:
1. `playoffs.json` never computed `consolation_winner_team_id` (schema
   required it, only championship bracket got a winner). Replaced the
   fragile "super bowl" keyword match with a generic "lowest placement
   number in the final round" detector (`_placement_number`,
   `_find_bracket_winner` in `code/raw-parsing/parse.py`) that works for both brackets.
2. Commissioner/league-change ("LM" type) transaction rows silently lost
   their entire message (free text in a colspan cell, no player link).
   Added a `message` field to `parse_transactions_page()`.
3. `already_fetched()` in `code/raw-parsing/utils.py` only checked file existence, so
   a cached 404/5xx response blocked retries forever, even after the URL
   bug causing it was fixed in code. Now checks the cached status code via
   the sidecar `.meta.json` and only treats 2xx as "done".

Verification (run by Claude): unit-tested the `already_fetched` fix in
isolation (200/404/500/no-meta/missing-file cases, all correct) before
touching real data.

Before re-running, snapshotted the pre-fix `archive/parsed/2025/`,
`managers.json`, `index.json`, `progress.html` to `/tmp/before_snapshot/`
for comparison:
```bash
cp -r archive/parsed/2025 /tmp/before_snapshot/parsed_2025
cp archive/managers.json archive/index.json archive/progress/progress.html /tmp/before_snapshot/
```

Full end-to-end re-run on already-downloaded raw files (idempotency
check, then re-parse, then rebuild managers/manifest):
```bash
conda run -n hsfl-archive python3 fetch_season.py --year 2025
conda run -n hsfl-archive python3 parse_season.py --year 2025
conda run -n hsfl-archive python3 managers.py
conda run -n hsfl-archive python3 -c "
from manifest import update_season_manifest, generate_progress_html
update_season_manifest(2025)
generate_progress_html()
"
```

**Results:**
- `fetch_season.py` re-run: all 419 pages returned `status=0` (cache hit,
  zero new network calls) - confirms idempotency held after the
  `already_fetched` fix, since all currently-cached 2025 files are valid
  2xx responses.
- File counts unchanged before/after: 257 files in `archive/parsed/2025/`
  both times - no data loss, no orphaned files.
- **Before → after diff:**
  - `playoffs.json` `consolation_bracket` keys: `['rounds']` →
    `['rounds', 'consolation_winner_team_id']`, value `5` (team_id 5,
    "Los Chunches" - winner of the "7th Place Game"). Championship
    `champion_team_id` unchanged at `9`, confirming the winner-detection
    rewrite didn't regress the already-working side.
  - `transactions.json`: 4/4 "LM" rows went from empty
    `player_name`/`from`/`to` with no record of what happened, to a
    populated `message` field (e.g. "Ashwin changed Draft Time to 'Sep 3,
    2025 8:00pm PDT'"). All 1367 non-LM rows unaffected.
- Re-ran the full Phase D validation suite (None-value check, draft
  integrity, matchup/roster anomaly scan, transaction integrity) against
  the post-fix output: **0 anomalies/exceptions** across all 257 files -
  no regressions introduced by the fixes.

## Phase D — second validation season: 2024 (first full run + review)

19. Ran the full pipeline against 2024 for the first time (fetch, then
    parse) - see "Running the pipeline on any season" above for the exact
    commands. Fetch took ~14 min (419 live requests: 8 static, 10 team
    home, 170 rosters, 170 game centers, 67 transactions pages - 6 more
    than 2025's 61). All requests succeeded on the first try (no errors
    logged for 2024). Parse produced the same file-count shape as 2025:
    160 draft picks, 81 matchup files, 170 roster files, 1469 transactions.

20. Ran the same Phase D validation suite used for 2025 against 2024's
    output (None-value check, draft integrity, matchup/roster anomaly
    scan, transaction integrity - findings appended to
    `instructions/bugs.md` under "Phase D review — 2024 season"):
    **0 anomalies.** Confirms bugs 1-3 (fixed for 2025) didn't regress and
    no new parser bugs surfaced on a second season with the same league
    config (10 teams, auction draft - the `snake` draft path is still
    untested). Also confirmed bug 4 (season-cumulative roster stats, still
    unfixed) reproduces identically in 2024.

21. Regenerated `managers.json` (now spans both seasons - 10/10 managers
    resolved across 2024+2025, no churn) and `index.json`/`progress.html`
    for both seasons:
    ```bash
    conda run -n hsfl-archive python3 managers.py
    conda run -n hsfl-archive python3 -c "
    from manifest import update_season_manifest, generate_progress_html
    update_season_manifest(2024)
    update_season_manifest(2025)
    generate_progress_html()
    "
    ```

22. Added a raw/parsed file-count summary to `progress.html`
    (`code/raw-parsing/manifest.py`'s `_count_season_files()`, new table columns +
    an overall total line). Result: 2024 = 852 raw / 257 parsed files;
    2025 = 840 raw / 257 parsed files; **2,206 files total** across both
    seasons. Both seasons show 100% completion, all page types green.

## Phase D — bug 4 fix and re-run (2026-08-07)

23. Fixed the last open bug (`bugs.md` #4: roster page stats/points are
    season-cumulative, not week-specific). Added `player_id` extraction to
    `_parse_box_score_table()` (both roster and gamecenter pages use the
    same `playerNameId-N` marker), and `parse_roster()` now takes an
    optional `gamecenter_html` param to override each player's
    `points`/`stats` from that team's own already-fetched gamecenter page
    (genuinely week-specific) instead of trusting the roster page's own
    (season-cumulative) values. `parse_season.py` updated to pass the
    matching gamecenter file in.

    Verified the fix in isolation before the full re-run: Josh Allen week 1
    `points` went from 368.62 (season total) to 38.76 (matches the known
    gamecenter value), and correctly varied across weeks 1/5/10
    afterward (38.76/19.42/19.34) where it had been constant before.

    Snapshotted pre-fix `rosters/` output to `.snapshots/before_bug4_fix/`
    before re-running (moved from a `/tmp` scratch location into the
    project per user request, along with all other session scratch
    files/scripts, into `.snapshots/`).

    Re-ran the full pipeline for both seasons:
    ```bash
    conda run -n hsfl-archive python3 parse_season.py --year 2025
    conda run -n hsfl-archive python3 parse_season.py --year 2024
    conda run -n hsfl-archive python3 managers.py
    conda run -n hsfl-archive python3 -c "
    from manifest import update_season_manifest, generate_progress_html
    update_season_manifest(2024)
    update_season_manifest(2025)
    generate_progress_html()
    "
    ```

    **Validation:** scanned every roster file in both seasons (720
    player-team pairs total) for the bug's signature (identical non-zero
    `points` across 4+ weeks) - **0 found in either season** after the
    fix (one legitimate all-zero case was individually verified against
    its gamecenter source, not a bug). Re-ran the full standard Phase D
    checks (None-values, draft integrity, matchup/roster anomaly scan,
    transaction integrity) against both re-parsed seasons: 0 anomalies,
    no regressions. All 4 confirmed bugs are now fixed - only the
    "generalization risks" (untested-year assumptions) in `bugs.md`
    remain open.
