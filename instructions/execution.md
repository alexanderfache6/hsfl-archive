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

## Phase F — implementation (2026-08-07)

24. Implemented all 8 `code/stats-aggregation/` modules (previously
    stubs): `optimal_lineup.py` (greedy strict-positions-then-flex
    solver, proven optimal for this problem shape - see the module
    docstring's exchange-argument sketch), `standings.py`,
    `breakdown.py`, `coaching.py`, `true_ranking.py`,
    `players_started.py`, and the `aggregate_season.py` orchestrator.
    Two documented simplifications (not bugs): standings rank ties are
    broken by win_pct then cumulative points_for, not this league's real
    "Head to Head Record" tiebreaker (full pairwise reconciliation judged
    not worth the complexity); FLEX eligibility is hardcoded to RB/WR for
    now (confirmed correct for 2024/2025, flagged as a generalization
    risk for other years in the code same as `bugs.md`'s pattern).

    Found and fixed one real bug during first run: `load_regular_season_weeks()`
    initially treated "any week with a matchup" as regular season, but
    playoff weeks (15-17) still have real (bye-reduced) matchups, so the
    first run wrongly produced 17 weeks instead of 14. Fixed by parsing
    the actual playoff start week out of `metadata.json`'s
    `settings.playoff_teams_and_weeks` string and filtering to weeks
    before it.

    ```bash
    conda run -n hsfl-archive python3 aggregate_season.py --year 2025
    conda run -n hsfl-archive python3 aggregate_season.py --year 2024
    ```

25. Validated against both seasons (run by Claude): confirmed 14 regular-
    season weeks for both years (post-fix); cross-checked final-week
    cumulative `standings` rows against the already-verified
    `standings.json` - wins/losses/ties/points_for/points_against matched
    exactly for every team in both seasons, with the only discrepancies
    being rank order among teams tied on win_pct (verified these are
    exactly the documented tiebreaker-simplification cases, not bugs -
    e.g. 2024 team 1 has the *highest* points_for among a 3-way tie but
    ranks worst officially, confirming the real site tiebreaker isn't
    points_for-based). Ran a structural integrity sweep across every
    week/team in both seasons: coaching diff never positive (optimal
    lineup is never worse than actual - would indicate a solver bug),
    all-play weekly game counts always equal `team_count - 1`,
    `true_ranking_score` always equals the sum of its 4 sub-ranks, and
    every rank column is a clean 1..N permutation with no gaps/dupes.
    **0 issues found** across both seasons. `players_started` counts
    landed in a plausible 18-31 range per team per season.

## Phase E begins — 2012 (first pre-2024 season, run by Claude)

26. Ran the full pipeline for 2012 for the first time:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2012   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2012
    conda run -n hsfl-archive python3 aggregate_season.py --year 2012   # from code/stats-aggregation/
    conda run -n hsfl-archive python3 all_time.py
    ```
    Fetch: all static pages 200 (no legacy-URL issues despite the
    pre-2013 warning in `instructions.md` section 0), 4 teams / 15 weeks
    discovered (vs 2024/2025's 10/17), 60 roster + 60 gamecenter + 39
    transactions pages.

    Found and fixed bug 5 (see `bugs.md`): champion detection failed
    because 2012's title game used the literal label "Championship"
    instead of "Fantasy Super Bowl" - `_placement_number()` didn't
    recognize it, so the wrong team (3rd-place-game winner) was crowned
    champion instead of the real winner (verified by comparing scores
    directly). Fixed in both `code/raw-parsing/parse.py` and
    `code/stats-aggregation/utils.py` (duplicate copy, per package
    independence). Re-parsed 2012 and re-verified 2024/2025 for
    regression (both still correct).

    Also confirmed (not bugs, real findings): 2012 used a **snake**
    draft (first real test of that previously-unverified code path - 60
    picks, correctly ordered, 0 duplicates/missing fields); a
    "Defensive Back" roster slot was declared in settings but never
    actually used by any rostered player all season (solver correctly
    leaves it unfilled); the consolation bracket is genuinely empty
    (all 4 teams made the single championship bracket that year) and
    parses to an empty-but-valid structure rather than erroring.

    Validation: 0 anomalies across the full Phase D suite (standings,
    draft, matchups/rosters, transactions, coaching-sign check) and the
    all-time integrity suite (0 combined-sum mismatches, 0 H2H symmetry
    issues, 3 total championships across 2012+2024+2025, 0 unresolved
    lookups). Manager Ashwin (`userId 2772924`) correctly linked across
    the 12-year gap between 2012 and 2024 - his 2012 championship counts
    correctly in `career.championships` (1, matching that he wasn't
    champion in 2024 or 2025).

27. **2013 delegated to a background agent** (per user request, run in
    parallel with 2012) - same pipeline and validation checks. See its
    own report for results once it completes.

28. **2013 background agent results.** Ran the full pipeline:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2013   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2013
    conda run -n hsfl-archive python3 aggregate_season.py --year 2013   # from code/stats-aggregation/
    conda run -n hsfl-archive python3 all_time.py
    ```
    Fetch: all static season pages returned status=200 (no legacy-URL-
    scheme issues despite the pre-2013-boundary warning in
    `instructions.md` section 0 - 2013 fetched exactly like 2024/2025).
    Discovered 8 teams / 16 weeks (a third distinct league size, after
    2012's 4/15 and 2024/2025's 10/17) - 8 team home pages, 128 roster
    pages, 128 game center pages, 67 transactions pages, 680 raw files
    total (html + meta sidecars). No non-2xx statuses anywhere in the
    fetch log.

    Parse: 0 `WARNING` lines (no unresolved teams, no team-count
    mismatches). Draft: 120 picks, 15/team, perfectly even across all 8
    teams, 0 missing `team_id`/`player_id`, 0 duplicate `player_id`s.
    Playoffs: `champion_team_id: "7"` correctly identified from a
    round labeled literally "Championship" (same label style as 2012,
    confirming bug 5's generalized placement-number detector handles
    this label too, not just 2012) - winner's score (125.78) exceeds the
    loser's (63.34) in that game, consistent with a correct pick.

    Aggregate: 0 `WARNING` lines (no unresolved team_id-to-manager
    lookups in `records.json`).

    **Validation - all checks passed, 0 anomalies:**
    - `standings.json` `final_standings`: 0 rows with any `None` value.
    - `draft.json`: 0 missing fields, 0 duplicate `player_id`s, exactly
      even picks-per-team (15 x 8).
    - Matchup/roster anomaly scan: 0/64 matchup files and 0/128 roster
      files with empty starters or a missing score.
    - `transactions.json`: 1538 rows (1521 non-LM, 17 LM); 0 non-LM rows
      missing `player_name`, 0 LM rows missing `message`.
    - `all_time_manager_stats.json`: 0 combined-sum mismatches (checked
      every manager x every stat: wins/losses/ties/points_for/
      points_against, `combined` == sum of the 3 season-type buckets).
    - Head-to-head symmetry: 0 issues across every manager pair in the
      `combined` block.
    - `all_time_unresolved.json`: empty (`{"unresolved": []}`) after
      folding in 2013, as expected.

    No new bugs found - 2013 reproduced the already-fixed bugs 1-5
    correctly (via the generalized detectors) and hit none of the open
    "generalization risk" items in `bugs.md`. `draft.json`'s
    `draft_type` is `"snake"` (all 120 picks have `auction_amount: null`)
    - a second real-world confirmation of the previously-unverified
    snake-draft code path alongside 2012, no unusual roster slot labels,
    week 1 had a full 8-team slate. Phase E now covers
    2012 and 2013 (both pre-2024) alongside the original 2024/2025 -
    four seasons folded into the all-time files with 0 unresolved
    entries and 0 integrity issues.

29. **2014 (background agent, immediately following 2013).** Ran the
    full pipeline:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2014   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2014
    conda run -n hsfl-archive python3 aggregate_season.py --year 2014   # from code/stats-aggregation/
    conda run -n hsfl-archive python3 all_time.py
    ```
    Fetch: all static pages status=200, no legacy-URL issues. Same
    8 teams / 16 weeks league size as 2013 (8 team home, 128 roster,
    128 gamecenter, 65 transactions pages, 676 raw files total).

    Parse: 0 `WARNING` lines. Draft: `draft_type: "snake"`, 120 picks,
    15/team exactly even, 0 missing fields, 0 duplicate `player_id`s -
    a third real-world confirmation of the snake-draft path (after 2012
    and 2013). Playoffs: champion detection correctly picked
    `champion_team_id: "2"` from a round again literally labeled
    "Championship" (not "Fantasy Super Bowl") - winner's score (85.78)
    correctly exceeds the loser's (68.98), confirming bug 5's fix keeps
    generalizing.

    Aggregate: 0 `WARNING` lines.

    **Validation - all checks passed, 0 anomalies:**
    - `standings.json`: 0 `None`-value rows.
    - `draft.json`: 0 missing fields, 0 duplicate `player_id`s, even
      15-per-team picks.
    - Matchup/roster scan: 0/64 matchup files, 0/128 roster files with
      empty starters or missing scores.
    - `transactions.json`: 1501 rows (1490 non-LM, 11 LM), 0 missing
      `player_name`/`message`.
    - `all_time_manager_stats.json`: 0 combined-sum mismatches.
    - Head-to-head symmetry: 0 issues.
    - `all_time_unresolved.json`: empty.
    - `post_season_stats.json`'s `final_placements` forms a clean 1..N
      permutation in **every** season parsed so far (2012: 1-4, 2013/
      2014: 1-8, 2024/2025: 1-10) - checked as part of this run.

    No new bugs. Phase E now covers 2012, 2013, 2014 plus 2024/2025 -
    five seasons folded into the all-time files, still 0 unresolved
    entries and 0 integrity issues.

30. **2015 and 2016 (background agent).** User asked to run 2016-2018;
    noted that this would leave 2015 ungapped/unfetched with no
    verification it was unreachable, so - per user confirmation - ran
    2015 too rather than silently skipping it. Fetched 2015 and 2016
    concurrently:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2015   # from code/raw-parsing/
    conda run -n hsfl-archive python3 fetch_season.py --year 2016
    conda run -n hsfl-archive python3 parse_season.py --year 2015
    conda run -n hsfl-archive python3 parse_season.py --year 2016
    conda run -n hsfl-archive python3 aggregate_season.py --year 2015   # from code/stats-aggregation/
    conda run -n hsfl-archive python3 aggregate_season.py --year 2016
    ```
    Both fetches clean: all static pages status=200, 8 teams / 16 weeks
    for both years (630 raw files for 2015, 608 for 2016 - 2015 had 42
    transactions pages, 2016 had 31, both well below 2013/2014's ~65-67,
    plausible year-to-year league-activity variance, not an error).

    Parse: 0 `WARNING` lines for either year. Both `draft_type: "snake"`,
    120 picks/15-per-team exactly even, 0 missing fields, 0 duplicate
    `player_id`s. Champion detection verified directly against game
    scores, not just trusted: 2015 `champion_team_id: "2"` (114.92 vs
    79.2, correct); 2016 `champion_team_id: "2"` (98.48 vs 98.28, correct
    - a near-tie final, worth double-checking and confirmed right).

    Aggregate: 0 `WARNING` lines for either year.

    **Validation - 0 anomalies for both seasons:** standings (0 None
    rows), draft (as above), matchup/roster scan (0/64 matchup files,
    0/128 roster files each), transactions (2015: 988 total/979 non-LM/9
    LM, 0 missing fields; 2016: 699 total/688 non-LM/11 LM, 0 missing
    fields), and `post_season_stats.json`'s `final_placements` is a
    clean 1-8 permutation for both years. No new bugs.

31. **2017 (background agent, continuing 2016-2018 request).** Ran the
    full pipeline:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2017   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2017
    conda run -n hsfl-archive python3 aggregate_season.py --year 2017   # from code/stats-aggregation/
    ```
    Fetch: all static pages status=200, 8 teams / 16 weeks (628 raw
    files, 41 transactions pages). Parse: 0 `WARNING` lines,
    `draft_type: "snake"`, 120 picks/15-per-team even, 0 missing/dup
    fields. Champion detection verified against scores directly:
    `champion_team_id: "2"` (75.76 vs 71.32, correct). Aggregate: 0
    `WARNING` lines.

    **Validation - 0 anomalies:** standings (0 None rows), draft (as
    above), matchup/roster scan (0/64, 0/128), transactions (936 total,
    all non-LM, 0 with this season having 0 LM-type rows at all - not an
    error, just no lineup-change transactions logged that way this
    year), `final_placements` a clean 1-8 permutation. No new bugs.

32. **2018 (background agent, completing the 2016-2018 request).** Ran
    the full pipeline:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2018   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2018
    conda run -n hsfl-archive python3 aggregate_season.py --year 2018   # from code/stats-aggregation/
    conda run -n hsfl-archive python3 all_time.py
    ```
    Fetch: all static pages status=200, 8 teams / 16 weeks (618 raw
    files, 36 transactions pages). Parse: 0 `WARNING` lines,
    `draft_type: "snake"`, 120 picks/15-per-team even, 0 missing/dup
    fields. Champion detection verified against scores directly:
    `champion_team_id: "5"` (102.86 vs 98.28, correct). Aggregate: 0
    `WARNING` lines.

    **Validation - 0 anomalies:** standings (0 None rows), draft (as
    above), matchup/roster scan (0/64, 0/128), transactions (842 total,
    836 non-LM/6 LM, 0 missing fields), `final_placements` a clean 1-8
    permutation. No new bugs.

    **All-time fold-in (`all_time.py`, run once after 2018):**
    `seasons=[2012, 2013, 2014, 2015, 2016, 2017, 2018, 2024, 2025]` -
    all 9 seasons parsed so far now folded together. Integrity suite:
    0 combined-sum mismatches (every manager x every stat, `combined` ==
    sum of the 3 season-type buckets), 0 head-to-head symmetry issues
    across every manager pair, `all_time_unresolved.json` empty, and
    `final_placements` forms a clean 1..N permutation in every one of
    the 9 seasons (checked all of them again here, not just 2018).

    Phase E status: 2012-2018 plus 2024/2025 all done and validated
    (2019-2023 remain unfetched). No open bugs from this batch - all
    fixes from earlier seasons (esp. bug 5's champion-detection fix)
    continue to generalize cleanly across every additional year tried.

33. **2019 (background agent) - fetch/parse/aggregate, plus a real fix
    (bug 6).** Ran the full pipeline:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2019   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2019
    conda run -n hsfl-archive python3 aggregate_season.py --year 2019   # from code/stats-aggregation/
    ```
    Fetch: all static pages status=200, **10 teams / 16 weeks** (a new
    config combo vs the 8-team years just done - 770 raw files, 46
    transactions pages). Parse: 0 `WARNING` lines, `draft_type: "snake"`,
    150 picks/15-per-team even, 0 missing/dup fields. Champion detection
    verified against scores: `champion_team_id: "8"` (97.92 vs 85.52,
    correct) - this season's title game reverted to the original
    "Fantasy Super Bowl" label (not "Championship"), confirming both
    label variants still resolve correctly. Aggregate: 0 `WARNING`
    lines. Matchup/roster scan (0/78, 0/160) and transactions (1033
    total, 1029 non-LM/4 LM, 0 missing fields) both clean.

    **Found bug 7 (real gap, now fixed):** `post_season_stats.json`'s
    `final_placements` initially had only 8 entries for this 10-team
    league - team_ids 4 and 7 were completely missing. Root cause:
    `metadata.json.settings.playoff_teams_and_weeks` for 2019 is
    literally `"Weeks 15 & 16 - 4 teams"` - only the top 4 teams made
    the championship bracket and only the next 4 made the consolation
    bracket, so the bottom 2 of 10 teams (team 4 "Duct Tape Crusaders"/
    Jeremy, 4-10 regular season record; team 7 "Mom I peed the bed
    again"/Forrest, 5-9 record) never played *any* bracket game. This is
    exactly the edge case `compute_final_placements()`'s docstring had
    already flagged as "should be rare/nonexistent... but not guaranteed"
    - now confirmed to happen for real. Per user direction ("preserve
    their regular season order"), fixed `code/stats-aggregation/
    post_season_stats.py`: `compute_final_placements()` now takes an
    optional `regular_season_final_standings` param (a list of
    `{team_id, rank, ...}` rows - the last regular-season week's
    cumulative standings row from `standings.py`) and, after placing
    every team that did play a bracket game, assigns any leftover teams
    consecutive placements starting right after the last bracket
    placement, ordered by regular-season rank (best record among the
    unplaced teams gets the better remaining placement). `aggregate_season.py`
    now passes `standings_by_week[weeks[-1]]` into
    `compute_post_season_stats()` at the call site. Result: 2019's
    `final_placements` is now a genuine 10-entry, clean 1-10 permutation
    (team 7 -> 9th, team 4 -> 10th, matching their regular-season order).
    Full entry added to `bugs.md`.

    **Regression check:** re-ran `aggregate_season.py` for every other
    season already on disk (2012-2018, 2024, 2025) after the fix - every
    one still produces a clean 1..N `final_placements` permutation with
    the *same* team count as before (the new fallback only adds teams
    that were missing, so seasons where every team already had a bracket
    game are byte-for-byte unaffected in placement coverage). Re-ran
    `all_time.py` after the fix:
    `seasons=[2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2024, 2025]`
    - 0 combined-sum mismatches, 0 head-to-head symmetry issues,
    `all_time_unresolved.json` still empty.

    (Note: a separate background agent was concurrently fetching 2020 in
    parallel - not touched by this entry, see its own log entry once it
    finishes.)

34. **2020 - full pipeline (fetch/parse/aggregate/fold-in), clean run.**
    Ran the full pipeline:
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2020   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2020
    conda run -n hsfl-archive python3 aggregate_season.py --year 2020   # from code/stats-aggregation/
    conda run -n hsfl-archive python3 all_time.py
    ```
    Fetch: all static pages status=200 (cached/idempotent re-run
    confirmed status=0 on second pass), **10 teams / 16 weeks** (same
    combo as 2019). 758 raw files: 10 team home pages, 160 roster pages,
    160 game center pages, 86 transactions pages. (Operational note, not
    a data issue: an earlier attempt to background the fetch process hit
    a tool-permission snag and briefly left two fetch processes running
    concurrently against the same `archive/raw/2020` directory before
    one was killed - final fetch output was re-verified clean via a
    subsequent idempotent re-run with no anomalies, so no corruption.)

    Parse: 0 `WARNING` lines. `draft_type: "auction"`, 160 picks, 16 per
    team (perfectly even across all 10 teams), 0 missing team_id/player_id,
    0 duplicate player_ids. 78 matchup files, 160 roster files, 1952
    transactions.

    **Validation - 0 anomalies:** `standings.json` (0 `None` values across
    10 `final_standings` rows), draft integrity clean (as above),
    matchup/roster scan clean (0/78 matchups missing score or starters,
    0/160 rosters with empty starters), transactions clean (1952 total,
    types {Lineup, LM, Drop, Add, Trade}, 0 rows missing required
    `player_name`/`message` fields). Champion detection verified against
    raw scores, not just `champion_team_id`: 2020's title game round is
    labeled `"Fantasy Super Bowl"` (team 2 172.7 vs team 3 133.92,
    `winner_team_id: "2"` matches `champion_team_id: "2"` - correct).
    Bug 5's fix continues to generalize; no repeat of the "Championship"-
    label edge case this season. `post_season_stats.json`'s
    `final_placements` forms a clean 1-10 permutation with no gaps or
    duplicates.

    **All-time fold-in (`all_time.py`):**
    `seasons=[2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2024, 2025]`
    - 2019 (concurrent agent) had already landed by the time this ran, so
    all 11 seasons parsed so far are folded together in one pass. Integrity
    suite: 0 combined-sum mismatches (every manager x every stat,
    `combined` == sum of `regular_season` + `post_season_championship` +
    `post_season_consolation`), 0 head-to-head symmetry issues across
    every manager pair (`combined.head_to_head`, checked both directions),
    `all_time_unresolved.json` empty.

    No new bugs found for 2020 - clean season, no bugs.md entry needed.

35. **2021 - full pipeline (fetch/parse/aggregate/validate/fold-in).**
    ```bash
    conda run -n hsfl-archive python3 fetch_season.py --year 2021   # from code/raw-parsing/
    conda run -n hsfl-archive python3 parse_season.py --year 2021
    conda run -n hsfl-archive python3 aggregate_season.py --year 2021   # from code/stats-aggregation/
    conda run -n hsfl-archive python3 all_time.py
    ```
    Fetch: all static pages status=200, **10 teams / 17 weeks** (first
    17-week season since 2024/2025 - this league's playoff/roster window
    grew from 16 to 17 weeks starting 2021, consistent with the real
    NFL's 2021 schedule expansion to 18 games). 860 raw files, 71
    transactions pages. Parse: 0 `WARNING` lines, `draft_type: "auction"`,
    160 picks/16-per-team exactly even, 0 missing/dup fields. Champion
    detection verified against scores: `champion_team_id: "3"` (135.6 vs
    128.06, correct), title round labeled "Fantasy Super Bowl". Aggregate:
    0 `WARNING` lines (14 regular season weeks, correctly excluding the
    new 17th week from the regular-season count).

    **Validation - 0 anomalies:** standings (0 None rows), draft (as
    above), matchup/roster scan (0/83, 0/170), transactions (1615 total,
    1614 non-LM/1 LM, 0 missing fields), `final_placements` a clean 1-10
    permutation. **Bug 7's regular-season-rank fallback fired again
    here** - 2021's `playoff_teams_and_weeks` is also `"Weeks 16 & 17 -
    4 teams"` (same 4-team-bracket format as 2019), so the bottom 2 of
    10 teams (team 10 "I'm Cummins", 5-10; team 9 "CummingInCole", 3-12)
    played no bracket game and got their placements (9th, 10th
    respectively) from the fallback, correctly preserving their
    regular-season order (team 10's better record placed it 9th ahead of
    team 9's worse record at 10th) - confirms the bug 7 fix generalizes
    beyond the season it was written for.

    **All-time fold-in:**
    `seasons=[2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2024, 2025]`
    - 0 combined-sum mismatches, 0 head-to-head symmetry issues,
    `all_time_unresolved.json` empty. No new bugs.

36. **2022 - full pipeline (fetch/parse/aggregate/validate/fold-in).**
    Same commands as entry 35, `--year 2022`. Fetch: all static pages
    status=200, 10 teams / 17 weeks (898 raw files, 90 transactions
    pages). Parse: 0 `WARNING` lines, `draft_type: "auction"`, 160
    picks/16-per-team even, 0 missing/dup fields. This season's playoff
    bracket final round is labeled `["Fantasy Super Bowl", "3rd Place
    Game", "5th Place Game"]` - a 6-team combined bracket (up from 2019's
    4-team) - champion detection verified against scores:
    `champion_team_id: "5"` (113.4 vs 112.38, correct, a near-tie final).
    Aggregate: 0 `WARNING` lines.

    **Validation - 0 anomalies:** standings (0 None rows), draft (as
    above), matchup/roster scan (0/81, 0/170), transactions (1993 total,
    1981 non-LM/12 LM, 0 missing fields), `final_placements` a clean
    1-10 permutation (6-team bracket + the remaining 4 teams still all
    resolved to placements - worth double-checking given bug 7's 2019
    case, but this year every team's `final_placements` entry came from
    an actual bracket game, not the regular-season-rank fallback: all 10
    team_ids appeared directly in a labeled placement game across the
    championship/consolation brackets' final rounds).

    **All-time fold-in:**
    `seasons=[2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2024, 2025]`
    - 0 combined-sum mismatches, 0 head-to-head symmetry issues,
    `all_time_unresolved.json` empty. No new bugs.

37. **2023 - full pipeline (fetch/parse/aggregate/validate/fold-in) -
    Phase E complete, full archive now covers every season 2012-2025.**
    Same commands as entry 35, `--year 2023`. Fetch: all static pages
    status=200, 10 teams / 17 weeks (872 raw files, 77 transactions
    pages). Parse: 0 `WARNING` lines, `draft_type: "auction"`, 160
    picks/16-per-team even, 0 missing/dup fields. Final round again
    `["Fantasy Super Bowl", "3rd Place Game", "5th Place Game"]` -
    champion detection verified: `champion_team_id: "5"` (112.48 vs
    102.58, correct). Aggregate: 0 `WARNING` lines.

    **Validation - 0 anomalies:** standings (0 None rows), draft (as
    above), matchup/roster scan (0/81, 0/170), transactions (1662 total,
    1661 non-LM/1 LM, 0 missing fields), `final_placements` a clean
    1-10 permutation.

    **Final all-time fold-in (`all_time.py`):**
    `seasons=[2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]`
    - **all 14 seasons of the league's history are now fetched, parsed,
    aggregated, and folded into the cross-season files.** Integrity
    suite: 0 combined-sum mismatches, 0 head-to-head symmetry issues, 0
    entries in `all_time_unresolved.json`, and `final_placements` forms
    a clean 1..N permutation with the right team count in every single
    one of the 14 seasons (re-verified all 14 again as part of this run,
    not just 2023). No new bugs found in this batch (2021-2023) - bug
    7's regular-season-rank fallback fired again for 2021 (see entry 35;
    same 4-team-bracket league format as 2019) but not for 2022 or 2023
    (both had a 6-team bracket covering enough teams that every team_id
    got a real placement game), confirming the fix generalizes correctly
    to every format seen so far rather than being a 2019-only patch.
    Phase E is now complete: every season from 2012 through 2025 has
    been fetched and validated with 0 outstanding anomalies.

38. **Full-history re-run of all stats aggregations (user-requested,
    2026-08-07 evening).** With Phase E complete (all 14 seasons parsed),
    re-ran every aggregation step across the entire archive to make sure
    everything reflects the final 14-season dataset, not a partial state
    from mid-crawl:
    ```bash
    # from code/stats-aggregation/, once per year 2012-2025:
    conda run -n hsfl-archive python3 aggregate_season.py --year {year}
    conda run -n hsfl-archive python3 all_time.py
    conda run -n hsfl-archive python3 player_ownership.py
    ```
    `player_ownership.py` in particular had gone stale - it's a
    standalone cross-season script (same pattern as `all_time.py`, not
    invoked by `aggregate_season.py`) that auto-discovers every season
    under `archive/parsed/` and builds `archive/player_ownership.json`
    (per-player weekly ownership/starter-bench timeline across all
    seasons, used by the frontend Players tab per `execution-plan.md`
    Phase G). Its on-disk file was last written mid-crawl and so didn't
    include 2015-2023's data. Re-ran it: now correctly reports
    `seasons=[2012..2023, 2024, 2025]` (all 14) and 860 players tracked
    total.

    Re-ran `aggregate_season.py` for all 14 years (regenerates
    `weekly_tables.json`, `players_started.json`, `head_to_head.json`,
    `post_season_stats.json`, `records.json` per season) - 0 `WARNING`
    lines across every single year, confirming no regressions from the
    bug 7 fix or any other change made during today's crawl. Re-ran
    `all_time.py` last (after every season's aggregate was current) -
    still `seasons=[2012, 2013, ..., 2023, 2024, 2025]`, 0 combined-sum
    mismatches, 0 head-to-head symmetry issues, `all_time_unresolved.json`
    still empty. Confirmed via `execution-plan.md`'s Phase G section that
    `all_time.py` and `player_ownership.py` are the only two cross-season
    (as opposed to per-season) aggregation scripts in
    `code/stats-aggregation/` - nothing else needed a separate full-history
    re-run beyond what's covered above.

39. **Team logo images downloaded and attached to `managers.json`
    (user-requested, 2026-08-07 evening).** No new HTML fetches needed -
    each team's logo `<img>` URL was already sitting in the already-
    fetched `archive/raw/{year}/team_{id}/team_home.html`
    (`<a class="teamImg teamId-N"><img src="...">`), confirmed present
    and consistent across 2012/2019/2024 samples before building
    anything (some teams that never uploaded a custom logo get a generic
    NFL placeholder image URL instead, e.g. `.../logos/avatar/240x240/
    DEF.png` - still a valid downloadable URL, just not custom art).

    New `code/raw-parsing/team_logos.py`: regexes the logo URL out of
    each season's `team_home.html`, downloads it (idempotent - skips if
    already on disk, same pattern as the HTML fetchers, 1.5s polite
    delay between live requests), and writes both `logo_url` and
    `logo_path` (relative to `archive/`) onto that manager's matching
    season entry in `archive/managers.json`. Images land in
    `archive/team_logos/{year}/team_{team_id}.{ext}`.

    Note this script *enriches* the existing `managers.json` rather than
    rebuilding it from scratch like `managers.py` does - so it must run
    *after* `managers.py` any time that gets re-run, or the logo fields
    get wiped by `managers.py`'s full overwrite.

    Ran it once against the full 14-season archive: **122/122 season
    entries got a logo attached, 0 failures** (`archive/team_logos/` -
    122 files, ~552KB total).
