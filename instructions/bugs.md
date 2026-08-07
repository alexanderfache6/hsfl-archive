# Phase D — Bug Review (2025 test season)

Findings from reviewing Phase B/C output before scaling to all seasons
(execution-plan.md Phase D, step 16). Verified against actual parsed
output and raw HTML, not just code inspection.

**Status update 2026-08-07:** all 4 confirmed bugs (1-4) are fixed and
verified (see `instructions/execution.md` steps 18 and 23 for the
fix/re-run logs and before/after data). The "generalization risks"
section remains open - those are untested assumptions to watch when
Phase E runs against other years, not yet-reproduced bugs.

## Confirmed bugs (FIXED - real data loss in current 2025 output)

### 1. [FIXED] `consolation_winner_team_id` missing from playoffs.json
`instructions.md` section 2's schema requires
`consolation_bracket.consolation_winner_team_id`, matching the
`championship_bracket.champion_team_id` field that *is* populated. But
`_parse_playoff_bracket()` only builds `rounds` - `parse_playoffs()` adds
`champion_team_id`/`runner_up_team_id` to the championship bracket only
and never computes an equivalent winner for the consolation bracket.
Confirmed: `archive/parsed/2025/playoffs.json`'s `consolation_bracket` has
only a `rounds` key.
- **File:** `code/raw-parsing/parse.py`, `parse_playoffs()`
- **Fix:** derive `consolation_winner_team_id` the same way as the
  championship winner (final round's winning team), using an
  appropriate final-round detector for the consolation side (the
  "super bowl" keyword heuristic won't match the consolation bracket's
  round names - needs its own detection, e.g. just the last round's
  matchup winner rather than a name-keyword match).

### 2. [FIXED] Commissioner/league-change transactions lose all descriptive content
Rows with `type == "LM"` (League Message, i.e. commissioner/league-setting
changes - shown as "League Changes" in the transactions page nav) render
their entire message in `<td class="playerNameAndInfo" colspan="3">free
text</td>` instead of a player link. `parse_transactions_page()` only
looks for `a.playerName` in that cell, finds nothing, and silently drops
the message. Confirmed 4/1371 rows affected in 2025 (e.g. "Ashwin changed
Draft Time to 'Sep 3, 2025 8:00pm PDT'"), all with `week: null` and
completely empty `player_name`/`from`/`to`.
- **File:** `code/raw-parsing/parse.py`, `parse_transactions_page()`
- **Fix:** when no player link is found in `playerNameAndInfo`, fall back
  to capturing that cell's raw text as a `message` field instead of
  leaving player_name/from/to empty with no record of what happened.

## Design risk (FIXED - not yet triggered, but would have mattered once Phase E hits real years)

### 3. [FIXED] Non-2xx fetch responses are cached as "done" forever
`fetch_static()` in `code/raw-parsing/fetch.py` writes the raw HTML and sidecar meta
unconditionally on any successful HTTP round-trip, regardless of status
code - a 404 error page gets written to disk exactly like a real page.
`already_fetched()` only checks file existence, not the cached status
code. Once a bad response is cached, the idempotent "skip if already on
disk" logic means it is *never* retried, even after a URL-pattern bug is
fixed in code (this is exactly why the `league_home` and `draft_results`
fixes earlier in Phase B/C required manually deleting the stale cached
files - the code itself would not have self-healed).
- **Why this matters for Phase E specifically:** `instructions.md` section
  0 explicitly warns that pre-2013 seasons may use different/legacy URL
  schemes or redirect/404. Running 13 more years unattended means this
  will very likely happen again, silently, with no automatic recovery.
- **Currently:** verified no cached 404/5xx files exist in `archive/raw/2025/`
  right now (both known instances were manually cleaned up already), so
  this hasn't caused visible damage yet - it's a latent gap, not an active
  data error.
- **File:** `code/raw-parsing/utils.py` (`already_fetched`, `write_raw`) /
  `code/raw-parsing/fetch.py` (`fetch_static`)
- **Suggested fix:** only treat a cached file as "already fetched" if its
  sidecar meta shows a 2xx status; otherwise re-fetch. Keep the bad
  response on disk for audit purposes (don't delete), just don't let it
  block a retry.

## Generalization risks for other years (not bugs against 2025, untested elsewhere)

These aren't wrong for 2025, but the code was written and validated
against exactly one season, so scaling to 13 more years carries real risk
that the site's markup or league configuration varies enough to break
these assumptions:

- **Draft type:** `parse_draft()`'s snake-vs-auction detection and pick
  numbering were only exercised against 2025's auction draft. The `snake`
  code path (`is_auction` false, no `auctionCost`/nomination structure)
  is unverified against any real page.
- **Champion detection heuristic:** `parse_playoffs()` finds the
  championship winner by searching for `"super bowl"` in the final
  round's game label. This is this league's specific naming
  ("Fantasy Super Bowl") - other years/leagues may label it
  "Championship" or something else entirely, silently falling back to
  `final_round_matchups[0]` which may not be the actual title game.
- **Roster position labels:** `ROSTER_POSITION_LABEL_TO_KEY` in
  `parse.py` is a fixed dict (QB/RB/WR/TE/FLEX/K/DEF/BENCH/RESERVE).
  A year with a different flex configuration (e.g. a WR/RB/TE flex, IDP
  slots, or a 2-QB league) would fall back to using the raw NFL.com label
  text as the dict key instead of a normalized one, producing
  inconsistent `roster_settings` keys across seasons.
- **Week-1-derives-all-managers assumption:** `parse_metadata()` gets the
  full team/manager list from `schedule.html` week 1's matchups. This
  assumes week 1 always has a full slate (true for 2025's 10-team,
  no-bye regular season) - an odd team count or a first-week bye in some
  other season would produce an incomplete team list.
- **Bench/reserve slot labels:** `parse_roster()` treats `BN` and `RES` as
  the only bench-type slot labels. An `IR` (injured reserve) label,
  which some years/leagues use, is not currently recognized as bench.

## Confirmed bugs (found 2026-08-07, FIXED same day)

### 4. [FIXED] `rosters/team_{id}_week_{w}.json` stats/points are season-cumulative, not week-specific
The roster page (`teamhome?teamId={id}&week={w}`) labels its stat columns
"Fantasy Points" and per-stat categories (Passing/Rushing/Receiving/etc),
implying week-specific performance, matching the schema's intent
(`rosters/team_{team_id}_week_{w}.json`: "Weekly full roster snapshot").
But the values are actually season-to-date cumulative totals: confirmed
by comparing Josh Allen's `points` and `stat_5` (passing yards) across
`roster_week_1.html`, `roster_week_5.html`, and `roster_week_10.html` for
the same team - identical every time (368.62 pts, 3668 yds), even though
his week-to-week performance obviously varies and other bench players on
the same page changed as they were added/dropped. By contrast, the
gamecenter/matchup box score for the same player across the same weeks
correctly varies (38.76, 19.42, 19.34) - confirming gamecenter is the
genuinely week-specific data source and the roster page is not.
- **Impact:** `rosters/*.json`'s `points` and `stats` fields are wrong for
  every week except whichever one the season-to-date snapshot happens to
  reflect (effectively meaningless per-week, especially for early-season
  weeks where they'd show much-later full-season numbers).
- **What's still correct on the roster page:** the roster *composition*
  (which players were in which slot that week, `slot`/`BN`/`RES`) does
  appear to reflect that week's actual lineup, since players who were
  added/dropped differ between week 1 and week 10 snapshots - only the
  per-player stat numbers are wrong, not which players are listed.
- **File:** `code/raw-parsing/parse.py`, `parse_roster()` / `code/raw-parsing/fetch.py`,
  `TEAM_ROSTER_TEMPLATE`
- **Fix applied (option 1 from the original two options):** roster page
  still supplies composition (which players/slots that week), but
  `points`/`stats` are now overridden per-player from that team's own
  already-fetched `gamecenter_week_{w}.html` (genuinely week-specific),
  joined by `player_id` (added to `_parse_box_score_table()`'s output -
  both pages use the same `playerNameId-N` marker). Falls back to the
  roster page's own (wrong) value only if no gamecenter page exists for
  that team/week (shouldn't happen in practice - gamecenter is fetched
  for every team/week the roster page is).
- **Verified 2026-08-07:** Josh Allen's week 1 `points` went from 368.62
  (season total) to 38.76 (matches the known-correct gamecenter value
  exactly); re-checked across weeks 1/5/10 for the same player - now
  38.76/19.42/19.34, correctly varying. Ran a full-scale check across
  both fetched seasons (720 player-team pairs total) for any player with
  an identical non-zero `points` value across 4+ weeks (the bug 4
  signature) - **0 found in either season** after the fix. One legitimate
  0.0-across-3-weeks case (a bench player who didn't score) was verified
  directly against its gamecenter source before being ruled out as
  real, not a bug. Re-ran the full Phase D validation suite (None-values,
  draft integrity, matchup/roster anomaly scan, transaction integrity)
  against both re-parsed seasons: 0 anomalies, no regressions.
- Before/after snapshots of the affected `rosters/` output kept at
  `.snapshots/before_bug4_fix/` for reference.

## Not a bug (confirmed correct, investigated during Phase C)
- Draft picks missing `auction_amount` (10/160) are keeper picks with no
  `auctionCost` span in the source markup - correct, not a parsing gap.
- Fewer than 5 matchups/week in weeks 15-16 are real playoff byes (teams
  with no opponent that week have single-team gamecenter pages) - correctly
  excluded from schedule.json, not a missed matchup.

## Phase D review — 2024 season (second validation season)

Fetched (`fetch_season.py --year 2024`) and parsed (`parse_season.py --year 2024`)
for the first time 2026-08-07, then run through the same validation suite
used for 2025. Same league config as 2025 (10 teams, 17 weeks, auction
draft) - **the `snake` draft code path is still unverified**, this wasn't
a different-config season.

**Results: 0 anomalies.** Draft (160 picks, 16/team, no duplicate
player_ids), standings (no None values), matchups (0/81 anomalies),
rosters (0/170 low-count anomalies), and transactions (1469 rows, 0
missing player_name on non-LM rows, 0 missing message on the 1 LM row) all
came back clean - none of bugs 1-3 (already fixed before this run)
regressed, and no *new* parser bugs surfaced on a second season.

**Confirmed bug 4 (season-cumulative roster stats) reproduces identically
in 2024:** Jordan Love's roster-page total is 237.86 across weeks 1, 8,
and 17 without variation - same site behavior as 2025, not a 2025-only
quirk. Still unfixed - see bug 4 above.

Playoff winner detection produced plausible, distinct results
(`champion_team_id: "8"`, `runner_up_team_id: "6"`,
`consolation_winner_team_id: "9"` - all different team_ids from 2025's
9/2/5, as expected for a different season/champion), giving some
confidence the generic placement-number detector (fix for bug 1)
generalizes beyond the exact season it was written against.
