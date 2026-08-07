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

    **Status 2026-08-07: scaffolded.** Module layout (all stubs, no logic
    yet - raise `NotImplementedError`, matching how `parse.py` started in
    Phase A):
    - `utils.py` — paths only (`archive/parsed/` read, `archive/aggregated/`
      write); deliberately does not import anything from `code/raw-parsing/`.
    - `optimal_lineup.py` — `solve_optimal_lineup(players, roster_settings)`,
      the lineup solver tables 3/4 depend on.
    - `standings.py` / `breakdown.py` / `coaching.py` / `true_ranking.py` —
      one module per sub-table, each a `compute_*_table(year, week)` (or,
      for true_ranking, a pure function over the other three tables' rows).
    - `players_started.py` — the season-long distinct-players stat.
    - `aggregate_season.py` — orchestrator entrypoint (`--year`), matching
      `fetch_season.py`/`parse_season.py`'s pattern; wires the above into
      `archive/aggregated/{year}/weekly_tables.json` +
      `players_started.json`.

24. Design the output file shape (likely `archive/aggregated/{year}/*.json` -
    mirroring the `archive/parsed/{year}/` convention) before writing code.

    **Status 2026-08-07: confirmed.**
    ```
    archive/aggregated/{year}/
    ├── weekly_tables.json     # tables 1-4, one entry per regular-season week
    └── players_started.json  # season-long distinct-players-started per team
    ```
    `weekly_tables.json` shape:
    ```json
    {
      "season": 2025,
      "weeks": [
        {
          "week": 1,
          "standings": [
            {"team_id": "9", "rank": 1, "wins": 1, "losses": 0, "ties": 0,
             "win_pct": 1.0, "win_streak": "W1", "points_for": 130.2, "points_against": 98.4,
             "weekly": {"result": "W", "points_for": 130.2, "points_against": 98.4}}
          ],
          "breakdown": [
            {"team_id": "9",
             "weekly": {"wins": 8, "losses": 1, "ties": 0, "win_pct": 0.889, "rank": 1},
             "cumulative": {"wins": 8, "losses": 1, "ties": 0, "win_pct": 0.889, "rank": 1}}
          ],
          "coaching": [
            {"team_id": "9",
             "weekly": {"actual_points": 130.2, "optimal_points": 135.6, "diff": -5.4, "rank": 3},
             "cumulative": {"diff_sum": -5.4, "rank": 3}}
          ],
          "true_ranking": [
            {"team_id": "9", "record_rank": 1, "points_for_rank": 1,
             "breakdown_rank": 1, "coaching_rank": 3,
             "true_ranking_score": 6, "true_rank": 1}
          ]
        }
      ]
    }
    ```
    `players_started.json` shape:
    ```json
    {"season": 2025, "teams": [{"team_id": "9", "player_count": 24, "player_ids": ["2560955", "..."]}]}
    ```
    Notes:
    - `weekly_tables.json` is regular-season only (playoff weeks use the
      bracket format in `playoffs.json`, not a standings table, per §2).
    - `standings[].rank` uses that season's actual tiebreaker from
      `metadata.json.settings` — not hardcoded — since Phase D's
      generalization risks already flagged league config can vary by year.
    - Deliberately no separate "final standings" file - week N's row in
      `weekly_tables.json` (where N = last regular-season week) already
      **is** the cumulative end-of-regular-season table; re-deriving it
      would duplicate `standings.json`.

25. Implement the per-season aggregation script and validate it against
    2024 and 2025's already-parsed data.

## Phase E — Full run (2012–2025)

**Paused 2026-08-07** — deliberately not started yet. User wants to build
out Phase G (the interactive layer) first, against the two seasons
already fully archived/aggregated (2024, 2025), before committing to the
full 12-season crawl. Resume this phase once Phase G's structure has
proven out.

19. Execute §6 step 2 (a–g) per remaining season, updating `index.json` after each sub-step.
20. Regenerate `progress.html` after each season completes so status is checkable mid-run.
21. Final pass: retry any `missing`/`partial` entries in `index.json`; resolve remaining `managers.json.unresolved` entries.
22. Produce `archive/SUMMARY.md` per §6 step 5.

## Phase G — Interactive layer (2026-08-07, moved from Phase F step 26)

26. Decide how/when the interactive layer consumes Phase F's aggregated
    output.

**Confirmed design so far:**
- New `frontend/` directory at the project root (a sibling of `code/`,
  not nested under it) - holds all UI-related code, kept separate from
  both `code/raw-parsing/` and `code/stats-aggregation/`.
- **Data flow:** download → archive (raw HTML) → process (parse to JSON)
  → aggregate (Phase F stats) happens for **all years first**, offline,
  using the existing `code/raw-parsing/` and `code/stats-aggregation/`
  pipelines. Output is committed to the GitHub repo (`archive/parsed/`,
  `archive/aggregated/`). The frontend reads those committed static
  files directly - **no external database**, for simplicity.
- **Hosting: Streamlit Community Cloud** (confirmed 2026-08-07). GitHub
  Pages can't run a Streamlit server (static files only), so the
  original "GitHub Pages via Streamlit" framing was resolved to Streamlit
  Community Cloud instead - free, deploys directly from the GitHub repo,
  auto-redeploys on push, full Streamlit feature set. The repo itself
  (with committed `archive/parsed/`/`archive/aggregated/` data) remains
  on GitHub as the single source of truth; Streamlit Community Cloud
  just points at it and runs `frontend/`'s app.

**Page structure (confirmed 2026-08-07, starting set - more pages to be
filled in incrementally, page by page, in future sessions):**
1. **History** — all-time champions list, all-time records, stats
   aggregated across every season.
2. **Yearly** — pick a year, see weekly-stat graphs and season aggregates
   (maps directly onto Phase F's `weekly_tables.json`/`players_started.json`
   for that year - no new data needed).
3. **Managers** — pick a single manager, see in-depth stats for that
   manager's team across every season they've played (joins across
   years via `managers.json`'s persistent manager_id).
4. **Players** — which manager(s) have rostered a given player, and how
   often (cross-season roster/draft history per player).

**Cross-season data (confirmed 2026-08-07):** tabs 1/3/4 all need data
joined *across* seasons, which Phase F doesn't produce (it's strictly
per-season, run one year at a time). Resolved as **pre-computed, not
computed live in Streamlit** — add a new cross-season step to
`code/stats-aggregation/` that reads every year's already-aggregated
output and writes combined all-time files (e.g.
`archive/aggregated/all_time_*.json`), committed to the repo the same
way as everything else. Keeps the frontend reading only static files
(consistent with the Yearly tab, fast page loads, no logic duplicated
between `stats-aggregation` and `frontend`). Not yet implemented - to be
scoped alongside the pages that need it.

**Status 2026-08-07: cross-season aggregation implemented** —
`code/stats-aggregation/all_time.py`, sourcing stats from each season's
already-computed `aggregate_season.py` output (not re-derived from
`archive/parsed/`), with manager identity/championship results pulled
from `metadata.json`/`playoffs.json` only (the two things Phase F
doesn't produce). Writes 3 files directly under `archive/aggregated/`
(not per-year): `all_time_champions.json` (one row per season - champion/
runner-up/consolation winner, team + manager), `all_time_manager_stats.json`
(one row per manager - career wins/losses/points/championships/
career_players_started, cumulative from first season played to last),
`all_time_records.json` (record-book superlatives: highest/lowest weekly
score, highest/lowest season points_for, longest win/loss streak, best/
worst coaching season, most players started in a season).

Validated against 2024+2025: total championships across all managers
sums to 2 (matches 2 seasons run so far), total games across all
managers sums to 280 (= 2 years × 10 teams × 14 games, exact), and
spot-checked `highest_season_points_for` / `most_players_started_season`
against values already confirmed correct in earlier phases - both
matched exactly. Note: two different managers happen to both be named
"Alex" (manager_id 22089610 and 5049083) - correctly kept as separate
career records via persistent manager_id, not merged by display name.

```bash
conda run -n hsfl-archive python3 all_time.py
```

**Status 2026-08-07: expanded and re-implemented per user confirmation.**
- `all_time_champions.json`: now top 3 final standings per season (was
  champion/runner-up only) + `last_place` ("consolation_loser" for
  punishments - the loser of the consolation bracket's highest-
  placement-number game, e.g. the "9th Place Game" loser in a 10-team
  league); consolation *winner* removed entirely.
- New per-season file `archive/aggregated/{year}/head_to_head.json`
  (`code/stats-aggregation/head_to_head.py`, wired into
  `aggregate_season.py`): `regular_season` matrix (from weekly matchups)
  + `post_season` matrix split into `championship`/`consolation`
  sub-matrices (the "flag that separates these 2 brackets") from
  `playoffs.json`.
- New per-season file `archive/aggregated/{year}/records.json`
  (`code/stats-aggregation/records.py`, refactored out of the old
  all-time-only scan): that season's own record book, so the Yearly UI
  page can show it without waiting on the all-time file.
- `all_time_manager_stats.json` restructured: each manager now has
  `regular_season`/`post_season`/`combined` blocks (wins/losses/ties/
  win_pct/points_for/points_against/head_to_head each), built from the
  new per-season `head_to_head.json` files (not re-derived), plus
  career-level `championships`/`runner_ups`/`last_place_finishes`/
  `career_players_started_count`.
- `all_time_records.json` rewritten to combine each season's `records.json`
  (not re-scan `weekly_tables.json`).

```bash
conda run -n hsfl-archive python3 aggregate_season.py --year 2025  # now also writes head_to_head.json, records.json
conda run -n hsfl-archive python3 aggregate_season.py --year 2024
conda run -n hsfl-archive python3 all_time.py
```

**Validated** (run by Claude): all-time records output identical to the
pre-restructure version (confirms the records.json-based rewrite is
correct); H2H matrix fully symmetric across all 10×9 manager pairs (0
issues); combined = regular_season + post_season for every manager and
every stat (0 mismatches); total regular-season team-game entries = 280
exactly (2 years × 10 teams × 14 weeks); total championships/runner_ups/
last_place_finishes across all managers each sum to exactly 2 (matches 2
seasons run so far); top-3/last-place matched all previously-confirmed
champion data for both seasons.

**Status 2026-08-07 (second revision, per further user feedback):**
post-season stats split into two separate blocks instead of one merged
`post_season` - championship and consolation are different competitive
contexts and shouldn't be blended.
- New per-season file `archive/aggregated/{year}/post_season_stats.json`
  (`code/stats-aggregation/post_season_stats.py`, wired into
  `aggregate_season.py`): per-team win/loss/points, split into
  `championship`/`consolation` sections, refactored out of what used to
  be inline logic in `all_time.py`.
- `all_time_manager_stats.json`: each manager now has 4 blocks -
  `regular_season`, `post_season_championship`, `post_season_consolation`,
  `combined` (= sum of the other 3) - each with the full wins/losses/
  ties/win_pct/points_for/points_against/head_to_head shape.
- `all_time_champions.json`: `top_3` entries and `last_place` now each
  carry both `regular_season` (from `standings.json`) and `post_season`
  (from the new `post_season_stats.json` - championship side for top_3,
  consolation side for last_place, since that's unambiguously which
  bracket each played in) blocks, instead of one flat record.

```bash
conda run -n hsfl-archive python3 aggregate_season.py --year 2025  # now also writes post_season_stats.json
conda run -n hsfl-archive python3 aggregate_season.py --year 2024
conda run -n hsfl-archive python3 all_time.py
```

**Validated** (run by Claude): combined = sum of all 3 blocks for every
manager/stat (0 mismatches); H2H symmetry holds across the full combined
matrix (0 issues); championships/runner_ups/last_place_finishes/regular-
season-games totals unchanged at 2/2/2/280 (no regression from the
restructure); `all_time_records.json` unaffected and still correct.
Found one genuinely interesting real result while validating: manager
Liam has entries in *both* `post_season_championship` (2-0, won the
2025 title) and `post_season_consolation` (2-0, won the 2024 consolation
bracket - matches the already-confirmed 2024 `consolation_winner_team_id: 9`)
- correctly tracked as two separate career lines rather than merged.

**Status 2026-08-07 (third revision): "do not silently drop anything" hardening.**
User flagged a real risk: 2024/2025 happened to share an identical
manager roster, but team/manager counts will genuinely vary once Phase E
covers 2012-2023. Three fixes:
1. **Root fix** - `code/raw-parsing/parse.py`'s `parse_metadata()` used to
   derive the entire team list from `schedule.html`'s week-1 matchups,
   which silently omits any team with a week-1 bye. Changed to source the
   team list from `standings.html` (guaranteed complete regardless of any
   single week) and manager identity from each team's own
   `team_home.html` (fetched once per team, independent of week) instead
   of the week-1 matchup header. `metadata.json` gained `unresolved_teams`
   (any team with no discoverable manager) and a `notes` warning if the
   parsed team count doesn't match `settings.html`'s own "Teams: N" figure.
2. Verified for 2024/2025: identical manager mapping, zero
   `unresolved_teams`, no count-mismatch notes - the fix is a no-op for
   already-clean data, as expected, while now being robust going forward.
3. **Hardened every cross-season aggregation function** in
   `code/stats-aggregation/all_time.py` and `records.py` - every place
   that used to silently `continue`/default-to-`{}` on a failed
   team_id→manager lookup now appends to an `unresolved` list instead.
   Per-season `records.json` carries its own `unresolved` key; all-time
   aggregation writes a new `archive/aggregated/all_time_unresolved.json`
   combining every season's findings, plus a printed warning if non-empty.

```bash
conda run -n hsfl-archive python3 parse_season.py --year 2025  # from code/raw-parsing/
conda run -n hsfl-archive python3 parse_season.py --year 2024
conda run -n hsfl-archive python3 aggregate_season.py --year 2025  # from code/stats-aggregation/
conda run -n hsfl-archive python3 aggregate_season.py --year 2024
conda run -n hsfl-archive python3 all_time.py
```

**Validated** (run by Claude): zero warnings printed for either season
(confirms the fix is a clean no-op on already-good data); re-ran the full
integrity suite - 0 combined-sum mismatches, 0 H2H symmetry issues, 2
championships / 280 regular-season games (unchanged, no regression);
`all_time_unresolved.json` correctly empty.

**Status 2026-08-07: frontend scaffolded, History tab (page 1) built.**
- `frontend/requirements.txt` (streamlit, pandas, plotly - the pip file
  Streamlit Community Cloud actually deploys from), `frontend/app.py`
  (4-tab nav: History built, Yearly/Managers/Players stubbed),
  `frontend/data_loader.py` (`@st.cache_data`-wrapped readers over the
  committed `archive/aggregated/*.json` - no database, no live fetch),
  `frontend/pages_history.py` (champions-by-season table, all-time
  records as stat tiles, career manager standings table).
- Verified with `streamlit.testing.v1.AppTest` (headless script-execution
  check - no browser available in this environment) and a live
  `streamlit run` process health-checked over HTTP: 0 exceptions, all
  expected tables/metrics render with correct values.
- Per further user request, extended the underlying aggregation (not
  just the UI) with three new stats:
  - `third_place_finishes` per manager (career standings table).
  - `fewest_players_started_season` (per-season `records.json` and
    all-time `all_time_records.json`), alongside the existing "most".
  - `average_regular_season_finish` / `average_post_season_finish` per
    manager - the latter required a new generalized
    `compute_final_placements()` in `post_season_stats.py` that derives
    a full 1..N overall postseason ranking from both brackets' final-
    round placement games (winner of a "Nth Place" game = rank N, loser
    = N+1) - validated to produce a clean gapless 1..N permutation
    across all 4 seasons fetched so far (4/8/10/10 teams respectively),
    confirming consolation-bracket placement numbers already continue
    globally from the championship bracket without manual offsetting.
- Re-ran the full pipeline for all 4 seasons (2012/2013/2024/2025) +
  `all_time.py` after these additions: 0 warnings, 0 unresolved lookups,
  all new stats validated against known-correct values.

**Status 2026-08-07: manager name disambiguation + table styling.**
- `archive/managers.json` (`code/raw-parsing/managers.py`) gained
  `display_names_seen_alternate` per manager - manually set to "Alex K"
  (manager_id 22089610) and "Alex F" (manager_id 5049083), the two
  managers sharing the display name "Alex"; empty string for everyone
  else.
- Propagated into `all_time_manager_stats.json` via a new
  `load_display_name_alternates()` in `code/stats-aggregation/utils.py`
  (reads `archive/managers.json` - the one place stats-aggregation reads
  a raw-parsing *output* file outside `archive/parsed/`, consistent with
  its existing "reads only finished outputs" principle).
- `frontend/data_loader.py` gained a single shared
  `build_manager_name_resolver()` / `resolve_manager_name()` - prefers
  the alternate name whenever set, used everywhere a manager name is
  displayed (champions table, record stat tiles, career standings), not
  just the table it was first requested for.
- New `frontend/ui_helpers.py` with `render_left_aligned_table()`:
  switched all tables from `st.dataframe` to `st.table` + a pandas
  Styler, since `st.dataframe` renders through a canvas-based grid
  (glide-data-grid) that right-aligns numeric columns by default with no
  public per-column alignment API - CSS/Styler text-align doesn't
  reliably reach canvas-drawn cells. `st.table` renders a real HTML
  table where left-alignment is guaranteed (verified: the rendered HTML
  contains explicit `text-align: left` on every header/cell). Tradeoff:
  loses `st.dataframe`'s built-in sort/resize/scroll - fine at current
  table sizes (~12 rows), worth reconsidering if a future page needs
  hundreds of rows.
- Verified via `AppTest`: both "Alex" managers now show correctly as
  "Alex K"/"Alex F" everywhere (champions table's 2024 entry, career
  standings table) instead of ambiguous "Alex" in both places.

27+ (not yet numbered): remaining frontend pages (Yearly, Managers,
Players) - not yet built.

---

## Status
- [x] Phase A, step 1 (partial): `environment.yml` created for conda env `hsfl-archive`. Env creation + `playwright install` commands logged in `instructions/execution.md` — user still needs to run them.
- [x] Phase A, step 2: scaffolded `fetch.py`, `parse.py` (stubs — real parsing deferred to Phase C per markup verification in Phase B), `manifest.py`, `run.py`.
- [x] Phase A, step 3: shared `utils.py` with rate limiting, idempotent fetch helpers, sidecar `.meta.json` writer, and `archive/progress/errors.log` logger.
- [x] Phase B–D: complete for 2025 and 2024 (both fully fetched, parsed, bug-reviewed — see `instructions/bugs.md` and `instructions/execution.md`). All 4 confirmed bugs fixed and verified across both seasons.
- [x] Phase F, step 23: `code/stats-aggregation/` module scaffold complete (8 files).
- [x] Phase F, step 24: output shape confirmed — `archive/aggregated/{year}/weekly_tables.json` + `players_started.json`, schemas documented above.
- [x] Phase F, step 25: implemented and validated against both 2024 and 2025 (see `instructions/execution.md` steps 24-25). 0 structural issues found; wins/losses/ties/points/points_against match `standings.json` exactly, only rank ties differ (documented tiebreaker simplification: win_pct + points_for, not true head-to-head). Two documented simplifications to revisit if Phase E surfaces a different league config: FLEX = RB/WR hardcoded, tiebreaker isn't the real head-to-head rule.
- [ ] Phase F, step 26: interactive layer — not scoped yet.
- [x] Reorganization (2026-08-07): all fetch/parse code moved from `code/` into `code/raw-parsing/` (see `instructions/execution.md`'s "Running the pipeline on any season" section for updated commands); `code/aggregation/` renamed to `code/stats-aggregation/`.
- [ ] Phase E: not yet started (2012–2023 remaining, 12 seasons).
