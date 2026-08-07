# HSFL Archive — Execution Plan

Staged so the 2025 season validates the approach before the full 2012–2025 run.
See `instructions.md` for the full spec this plan implements.

## Phase A — Environment setup
1. Create a Python virtual environment (conda env `hsfl-archive`, see `environment.yml`) and install `httpx`, `beautifulsoup4`, `playwright` (+ `playwright install` for browser binaries).
2. Scaffold a project structure: `fetch.py` (raw HTML fetcher), `parse.py` (HTML → JSON parsers per page type), `manifest.py` (index.json/progress.html generation), `run.py` (orchestrator).
3. Add a shared `utils.py` for: polite rate-limiting (1–2s delay), idempotent fetch-if-not-exists-on-disk, sidecar `.meta.json` writer (timestamp + HTTP status), and `archive/progress/errors.log` logger.

## Phase B — Single-season test run (2025)
4. Fetch `league_home.html` and `settings.html` for 2025 only; manually inspect the raw HTML to confirm current NFL.com markup matches the assumptions in the instructions (selectors, JS-shell vs static content, URL scheme).
5. Note any discrepancies and update `instructions.md` §1–3 (schema/URL notes) before writing parsers, per §6 step 1.
6. Fetch remaining 2025 static pages: standings (final + regular), schedule, draft results, playoffs (championship + consolation).
7. Discover `team_id` list from standings/schedule for 2025.
8. Determine actual week count (regular season + playoff weeks) from the settings/schedule page rather than assuming 14.
9. Fetch weekly scoreboards for all discovered weeks; check whether scoring/roster data needs the Playwright fallback (JS-rendered) or works via `httpx`.
10. Fetch team home + weekly rosters for each discovered `team_id`.
11. Fetch all transaction pages for 2025, paginating by `offset` until an empty page.

## Phase C — Parse and validate 2025
12. Write/parse `metadata.json`, `standings.json`, `draft.json`, `playoffs.json`, `schedule.json`, `matchups/week_{w}.json`, `transactions.json`, `rosters/team_{id}_week_{w}.json` against the raw HTML fetched above.
13. Validate each parsed file against the schemas in `instructions.md` §2 (spot-check a few records by hand against the live site).
14. Populate `managers.json` for 2025's teams (§2b), flagging any ambiguous manager matches in `unresolved` rather than guessing.
15. Generate `index.json` and `progress.html` scoped to 2025 and visually confirm the dashboard renders correctly and reflects true completion status.

## Phase D — Review before scaling
16. Review Phase B/C output for parser bugs, missing fields, or rate-limit/blocking issues (CAPTCHAs, 429s) encountered against the live site.
17. Fix parsers/fetch logic and re-run 2025 end-to-end to confirm idempotency (re-running should skip already-fetched raw files and reuse them).
18. Once 2025 is clean and fully green in `progress.html`, decide whether to run seasons sequentially (2012→2025 or reverse) or in small batches, and confirm delay/politeness settings are acceptable before the long unattended run.

## Phase F — Season-level aggregation for visualization (built before Phase E)

Runs on `archive/parsed/{year}/` output only, independent of Phase E's
mass crawl — validated against the two seasons already fully parsed
(2024, 2025) rather than waiting on all 13. Lives entirely in a new
`code/stats-aggregation/` directory, kept separate from the fetch/parse
pipeline in `code/` so it can be re-run or reworked without touching
the archiving code.

**Design constraints (per user instruction, 2026-08-07):**
- Independent of all other code in `code/` — reads only the finished
  `archive/parsed/{year}/*.json` files, never raw HTML, never re-derives
  anything the parsers haven't already produced.
- Runs one year at a time (e.g. `python aggregate_season.py --year 2025`),
  matching the same per-season pattern as `fetch_season.py`/`parse_season.py`.
- Output is intended to eventually back an **interactive** view: pick a
  year, see week-by-week stats, cumulative stats, and end-of-season
  aggregates. This phase produces the underlying data files; the
  interactive UI itself is a separate, later concern.

**Stats to compute per season, per team (from `standings.json`,
`schedule.json`, `matchups/*.json`, `rosters/*.json`, `playoffs.json`):**
- Weekly and cumulative points scored / points against, week over week.
- Weekly rank/standing changes (how a team's position in the standings
  moved week to week, not just the final rank).
- Count of distinct players started over the full season (union of
  `starters` across all weeks' `matchups/*.json`/`rosters/*.json` for
  that team).
- **Optimal lineup per week**: given that week's full roster (starters +
  bench, from `matchups/*.json`/`rosters/*.json` — both already carry
  each player's actual `points` for that week post-bug-4-fix), compute
  the highest-scoring legal lineup under that season's
  `metadata.json.settings.roster_settings` slot counts, then:
  - **Points difference** = optimal lineup points − actual starters
    points (points left on the bench that week from a suboptimal call).
  - **Cumulative difference** = running sum of that weekly difference
    across the season, to see if a manager's lineup-setting improves,
    worsens, or stays flat over time.
  - **FLEX-eligibility note (confirmed 2026-08-07, this league):** the
    `FLEX` roster slot is RB/WR only — NOT also TE, per the actual
    settings label ("Wide Receiver / Running Back:") already captured in
    `metadata.json.settings.roster_settings`. The optimal-lineup solver
    must read slot eligibility from that season's actual
    `roster_settings` rather than hardcoding FLEX = RB/WR/TE (a common
    default in other leagues) — a different year's league config could
    differ, and this data is already parsed per-season, so there's no
    reason to assume rather than read it.
- Final standings, both the regular-season table and the postseason
  bracket result (championship + consolation), already available in
  `standings.json`/`playoffs.json` but reshaped/joined for this purpose.

**Weekly standings table (confirmed 2026-08-07) — 4 sub-tables, computed
for every week of the regular season, each with a weekly-snapshot value
and a cumulative-through-that-week value (except table 4, which is
cumulative-only per user confirmation):**

1. **Standings** — `wins`/`losses`/`ties` (cumulative through week N),
   `win_pct`, `win_streak` (e.g. "W3" — derived by walking backward
   through each team's week-by-week win/loss results), `points_for`/
   `points_against` (cumulative through week N), `rank` (sorted by
   record using that season's actual tiebreaker rule from
   `metadata.json.settings` — e.g. "Head to Head Record" for 2025/2024 -
   read per-season, not hardcoded). Weekly variant: that single week's
   result (W/L/T) and that week's points_for/against before accumulation.

2. **Breakdown (all-play)** — for a given week, compare a team's score
   against every other team's score that same week (from
   `matchups/*.json`) to get an all-play `W-L-T` for that week alone;
   cumulative version sums those weekly all-play records through week N.
   `all_play_win_pct` and `breakdown_rank` (teams ranked by all-play
   win_pct) computed both weekly and cumulative.

3. **Coaching** — uses the optimal-lineup solver above: `coaching_diff`
   = actual starters' points − optimal lineup points for that week
   (always ≤ 0). Weekly = that week's diff; cumulative = running sum of
   weekly diffs through week N. `coaching_rank` = teams ranked by diff,
   closest-to-zero (least points wasted on the bench) is best, both
   weekly and cumulative.

4. **True ranking (cumulative-only, per user confirmation)** — through
   week N: `record_rank` (from table 1's cumulative rank),
   `points_for_rank` (teams sorted purely by cumulative `points_for`,
   independent of win-loss), `breakdown_rank` (table 2's cumulative
   rank), `coaching_rank` (table 3's cumulative rank).
   `true_ranking_score` = sum of those 4 sub-ranks (golf-style, lower is
   better). `true_rank` = teams sorted ascending by that sum — a power
   ranking through week N that strips out scheduling luck, distinct from
   the actual standings rank in table 1.

23. Create `code/stats-aggregation/` (empty scaffold, first step - implementation
    comes after this plan is confirmed).
24. Design the output file shape (likely `archive/aggregated/{year}/*.json` -
    mirroring the `archive/parsed/{year}/` convention) before writing code.
25. Implement the per-season aggregation script and validate it against
    2024 and 2025's already-parsed data.
26. Decide how/when the interactive layer consumes this output (separate,
    later phase - not scoped yet).

## Phase E — Full run (2012–2025)
19. Execute §6 step 2 (a–g) per remaining season, updating `index.json` after each sub-step.
20. Regenerate `progress.html` after each season completes so status is checkable mid-run.
21. Final pass: retry any `missing`/`partial` entries in `index.json`; resolve remaining `managers.json.unresolved` entries.
22. Produce `archive/SUMMARY.md` per §6 step 5.

---

## Status
- [x] Phase A, step 1 (partial): `environment.yml` created for conda env `hsfl-archive`. Env creation + `playwright install` commands logged in `instructions/execution.md` — user still needs to run them.
- [x] Phase A, step 2: scaffolded `fetch.py`, `parse.py` (stubs — real parsing deferred to Phase C per markup verification in Phase B), `manifest.py`, `run.py`.
- [x] Phase A, step 3: shared `utils.py` with rate limiting, idempotent fetch helpers, sidecar `.meta.json` writer, and `archive/progress/errors.log` logger.
- [x] Phase B–D: complete for 2025 and 2024 (both fully fetched, parsed, bug-reviewed — see `instructions/bugs.md` and `instructions/execution.md`). All 4 confirmed bugs fixed and verified across both seasons.
- [x] Phase F, step 23: `code/stats-aggregation/` directory created (empty scaffold).
- [ ] Phase F, steps 24–26: output shape design + implementation — not yet started. Weekly standings table spec (4 sub-tables: standings/breakdown/coaching/true ranking) confirmed 2026-08-07, documented above.
- [x] Reorganization (2026-08-07): all fetch/parse code moved from `code/` into `code/raw-parsing/` (see `instructions/execution.md`'s "Running the pipeline on any season" section for updated commands); `code/aggregation/` renamed to `code/stats-aggregation/`.
- [ ] Phase E: not yet started (2012–2023 remaining, 12 seasons).
