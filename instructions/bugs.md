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

## Phase E begins — bug 5 found and fixed in 2012 (first pre-2024 season)

Fetched/parsed/aggregated 2012 for the first time 2026-08-07 - first real
test of a season with a genuinely different league configuration: **4
teams** (not 10), **15 weeks** (not 17), **snake draft** (not auction,
first real test of that previously-unverified code path), a roster
setting for an unused "Defensive Back" IDP slot, and all 4 teams making
a single "championship" playoff bracket (no consolation bracket that
year - correctly parsed as empty, not a bug).

### 5. [FIXED] Champion detection failed on the literal label "Championship"
`_placement_number()` (in both `code/raw-parsing/parse.py` and its
duplicate in `code/stats-aggregation/utils.py`) only recognized "super
bowl" or an "Nth Place Game" pattern as placement-1 signals. 2012's
bracket used the literal label **"Championship"** for the title game
instead of "Fantasy Super Bowl" - exactly the risk flagged in this
file's "generalization risks" section back when bug 1 was fixed. Since
"Championship" matched neither pattern, `_find_bracket_winner()` fell
through to the only other placement-labeled game that round ("3rd Place
Game") and crowned *its* winner (team 3) as season champion, when the
real title game (team 1 beat team 2, 139.70-139.38) gave the title to
team 1.
- **Confirmed real bug, not a data artifact:** verified by reading the
  actual bracket scores directly - team 1's score exceeded team 2's in
  the game literally labeled "Championship".
- **Fix:** added `"championship" in label_lower` as an additional
  placement-1 synonym alongside `"super bowl"`, in both copies of the
  function.
- **Verified no regression:** re-parsed 2024/2025 after the fix - both
  still correctly show their known champions (team 8 / team 9).
- **Everything else in 2012 was clean:** 0 anomalies across all the
  usual Phase D checks (standings None-values, draft integrity - 60
  snake picks, 0 duplicates, 0 missing team_id/player_id - matchup/
  roster scans, transactions, coaching-diff sign check); all-time
  integrity checks (combined-sum, H2H symmetry, unresolved list) also
  0 issues after folding 2012 into the cross-season files. Manager
  Ashwin (`userId 2772924`) correctly linked across a 12-year gap -
  played in 2012, reappears in 2024/2025, with his 2012 championship
  correctly counted in `career.championships`.
- **Confirmed real, not a bug:** the "Defensive Back" roster slot
  declared in 2012's `settings.html` never had a single player with
  that position value anywhere in the season's actual roster/matchup
  data - the optimal-lineup solver correctly leaves it unfilled (0
  players match) rather than crashing or fabricating a match. Likely a
  vestigial/unused slot in the league's settings that year, not a
  parsing gap.

### 6. [FIXED] `last_place` empty for seasons with no real consolation bracket
User-reported: 2012's `all_time_champions.json` entry had an empty
`last_place` (team_id/manager_id/display_name all `""`). Root cause:
`_find_last_place()` only ever looked at the consolation bracket, and
2012 (4 teams, all 4 made the single championship bracket - see bug 5's
entry above) has a genuinely empty consolation bracket, so there were no
candidates to pick a loser from. But "last place" is still meaningful
even without a consolation bracket - it's just whichever team finished
worst in the regular season.
- **Fix:** `_find_last_place()` now takes `final_standings` as a second
  argument and falls back to the worst-ranked (`max(rank)`) team there
  when the consolation bracket yields no candidates. Both call sites in
  `all_time.py` updated - one already had `standings.json` loaded, the
  other reuses `weekly_tables.json`'s final-week cumulative standings
  (already loaded there) rather than reading `standings.json` again.
- **Verified:** 2012's `last_place` now correctly shows team 4
  ("bontenators", manager Jeremy, 6-7-0) - confirmed this matches
  `standings.json`'s actual worst-ranked (rank 4) team exactly. Re-ran
  the full all-time integrity suite across all 4 seasons (2012, 2013,
  2024, 2025) folded in so far: 0 combined-sum mismatches, 0 H2H
  symmetry issues, 4 championships total (1 per season, correct), 0
  unresolved lookups.

### 7. [FIXED] `final_placements` silently dropped teams that played no bracket game at all
`compute_final_placements()` in `code/stats-aggregation/post_season_stats.py`
only ever assigned a placement to a team that appeared in a labeled
placement game (e.g. "Fantasy Super Bowl", "3rd Place Game") in either
bracket's final round. The function's own docstring had already flagged
this as a real possibility ("A team with no labeled placement game...
should be rare/nonexistent given the pattern above, but not guaranteed
for every possible season") - 2019 is the season where it actually
happened. That season's `metadata.json.settings.playoff_teams_and_weeks`
is literally `"Weeks 15 & 16 - 4 teams"`: only the top 4 of 10 teams made
the championship bracket, and only the next 4 made the consolation
bracket, leaving the bottom 2 teams (team 4 "Duct Tape Crusaders"/
Jeremy, 4-10 regular season; team 7 "Mom I peed the bed again"/Forrest,
5-9 regular season) with zero bracket appearances all postseason.
- **Impact:** `archive/aggregated/2019/post_season_stats.json`'s
  `final_placements` had only 8 entries for a 10-team league - teams 4
  and 7 missing entirely. Downstream, `all_time.py`'s
  `career[...]["_post_season_ranks"]` (which feeds
  `average_post_season_finish` in `all_time_manager_stats.json`) silently
  skipped 2019 for whichever managers owned those two teams, understating
  their sample size for that stat with no error or warning anywhere.
- **File:** `code/stats-aggregation/post_season_stats.py`
  (`compute_final_placements`, `compute_post_season_stats`) /
  `code/stats-aggregation/aggregate_season.py` (call site).
- **Fix (per explicit user direction - "preserve their regular season
  order"):** `compute_final_placements()` now takes an optional
  `regular_season_final_standings` param (a list of `{team_id, rank,
  ...}` rows, e.g. the last regular-season week's cumulative standings
  row from `standings.py`). After placing every team that did play a
  bracket game, any leftover teams get consecutive placements starting
  right after the last bracket placement, ordered by regular-season rank
  (the better remaining record gets the better remaining placement) -
  i.e. their relative order is preserved from the regular season rather
  than being dropped. `aggregate_season.py` now passes
  `standings_by_week[weeks[-1]]` into `compute_post_season_stats()`.
- **Verified 2026-08-07:** 2019's `final_placements` went from 8 entries
  to a genuine 10-entry, clean 1-10 permutation - team 7 -> 9th
  (better record of the two unplaced teams), team 4 -> 10th, matching
  their actual regular-season order exactly. Re-ran `aggregate_season.py`
  for every other season already on disk (2012-2018, 2024, 2025): every
  one still produces the *same* placement count and a clean 1..N
  permutation as before the fix (the new fallback only fires when a team
  is missing, so seasons where the bracket already covered every team
  are unaffected). Re-ran `all_time.py` after the fix across
  `[2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2024, 2025]`: 0
  combined-sum mismatches, 0 head-to-head symmetry issues,
  `all_time_unresolved.json` still empty.

### 8. [FIXED] Frontend Matchups tab's optimal-lineup "gains" understated the true diff, sometimes to zero (or cross-attributed between unrelated swaps)
User-reported in two rounds against 2022 Jeremy vs Alex F matchups:
1. Week 4 and Week 15 (Jeremy's side): the green per-player "+X.XX" gain
   amounts didn't sum to the "Optimal Lineup Total" diff on the same
   card - Week 4 showed +8.5 and +0.3 (sums to 8.8) next to a total of
   +16.5; Week 15 showed a +13.8 total with **no players highlighted at
   all**.
2. After the first fix below, Week 13 (Alex F's side): a 49ers DEF
   (18.0 pts) benched in favor of a starting Ravens DEF (6.0 pts) should
   swap for exactly +12.0, and a separate C. Kmet TE (10.2 pts) for H.
   Hurst TE (2.2 pts) swap should be +8.0 - instead the UI showed the DEF
   swap as +15.8 and the TE swap as +4.2 (still summing correctly to the
   true +20.0 total, but the individual numbers were wrong/"made up").

- **Root cause 1 (original bug):** `_optimal_lineup_details()`
  (`frontend/pages_matchups.py`) tried to explain each bench player's
  gain as a simple 1-for-1 swap: find the weakest ACTUAL starter at that
  same position (or FLEX-eligible position, if the bench player's
  optimal slot was FLEX) who isn't in the optimal lineup, and attribute
  the point difference to that pair. This breaks whenever the true
  optimal lineup reshuffles an EXISTING starter into a different slot
  rather than benching them outright - both Wk4 and Wk15 had the same
  pattern: the optimizer moves a starting RB (J. Conner) from his own RB
  slot into the FLEX slot to make room for a stronger bench RB (R.
  Stevenson) in the now-open RB slot. Since Conner is still a starter in
  the optimal lineup (just relocated), the heuristic's search for "a real
  RB starter who dropped out of the lineup" finds nobody at RB, so
  Stevenson's entire contribution (10.9 pts in Wk4, 23.8 pts in Wk15) was
  silently dropped from `gains` - fully in Wk4 (leaving only the two
  genuine simple swaps, summing to 8.8 instead of 16.5) and completely in
  Wk15 (leaving `gains` empty entirely, since that week's ENTIRE diff was
  this one chain move).
- **First fix attempt (introduced root cause 2 below):** replaced the
  position/FLEX-eligibility matching entirely with a single rank-based
  pass: `added` (optimal starters not in the actual lineup) sorted by
  points descending, zipped against `removed` (actual starters not in
  the optimal lineup) sorted ascending. Mathematically this always sums
  to the true diff (see root cause 2's real counter-example, where it
  still summed correctly, just wrongly distributed) - but it ignores
  POSITION entirely, so it can cross-attribute value between two
  genuinely INDEPENDENT same-position swaps happening in the same week.
- **Root cause 2 (regression from the first fix, caught by the user's
  Wk13 report):** Wk13 has two unrelated real swaps: DEF (49ers bench for
  Ravens starter, true value +12.0) and TE (Kmet bench for Hurst starter,
  true value +8.0). Rank-only pairing sorted `added` = [49ers DEF 18.0,
  Kmet TE 10.2] and `removed` ascending = [Hurst TE 2.2, Ravens DEF 6.0],
  then zipped index-for-index - pairing the DEF add against the TE
  remove (18.0 - 2.2 = 15.8) and the TE add against the DEF remove
  (10.2 - 6.0 = 4.2). The total (20.0) was still correct by construction,
  but both individual numbers were attributed to the wrong swap entirely.
- **File:** `frontend/pages_matchups.py`, `_optimal_lineup_details()`
- **Final fix - two passes, combining both previous approaches'
  strengths:**
  - **Pass 1** matches each `added` player (biggest points first) against
    a same-position (or FLEX-eligible) `removed` player (weakest first) -
    this is the original heuristic's logic, which is exactly right for
    genuinely independent same-position swaps like Wk13's DEF and TE.
  - **Pass 2** takes whatever's left over after pass 1 (added players
    with no same-position removed candidate) and pairs them by rank
    (added descending vs removed ascending) - this is what correctly
    catches Wk4/Wk15's chain-reassignment case, which pass 1 alone can't
    explain (no starter "dropped out" at RB, since Conner just moved to
    FLEX).
  - Neither pass claims to reconstruct the TRUE swap chain in every
    multi-swap week - this remains a display attribution convention, not
    a literal step-by-step reconstruction - but pass 1 keeps genuinely
    independent swaps correctly attributed, and pass 2 still guarantees
    no real gain silently drops to zero.
- **Verified:**
  - Wk4 (Jeremy): gains now Woods +8.5, Gesicki +0.3, Stevenson +7.7 -
    sums to 16.5, matching the true total exactly.
  - Wk15 (Jeremy): Stevenson +13.8 alone, matching the true total exactly.
  - Wk13 (Alex F): 49ers DEF +12.0, Kmet TE +8.0 - **exactly** the values
    the user expected, both now correctly isolated to their own swap.
  - Wk15 (Alex F): gains sum to 18.2, matching the true total exactly.
  - Swept every matchup side across every fetched season (1954
    team-weeks) comparing `sum(gains)` against the true
    `optimal_points - actual_total` diff: **1909/1954 now match exactly**
    (up from 1885/1954 after the first, flawed fix - pass 1 correctly
    resolves several cases pass-2-only left as accidental mismatches
    too). The remaining 45 mismatches split into two known, unrelated,
    pre-existing edge cases where `added`/`removed` end up different
    lengths (so pass 2's `zip()` stops at the shorter list and
    understates `sum(gains)` slightly - `optimal_points`, the number
    actually shown as the card's total, is unaffected either way):
    1. Seasons carrying 2012's vestigial "Defensive Back" IDP roster slot
       (already documented as "not a bug" under bug 5's footnote above) -
       that slot's occupant has no real counterpart in the optimal
       lineup, which has one fewer filled slot than the actual lineup.
    2. A small number of individual weeks (seen in 2017/2018/2020/2021/
       2022/2023/2024) where a team's ARCHIVED actual lineup has fewer
       real starter entries than that season's roster settings call for
       (e.g. one team fielded only 8 of 9 starting slots in
       `archive/parsed/2022/matchups/week_13_9_10.json`'s away side) -
       the optimal solver still fills every slot from the full player
       pool, so `added` ends up longer than `removed`. Not investigated
       further here (out of scope of the reported bug) - worth a
       follow-up to determine whether this reflects a genuinely
       unfilled/empty lineup slot that week or a parsing gap.

3. User-reported (2022 Week 1, Alex F vs Forrest, Alex F's side): after
   the two-pass fix above, the bench WR M. Thomas (20.2 pts) was shown as
   gaining +13.4 against a benched RB (D. Harris, 6.8 pts), and separately
   a bench RB (D. Singletary, 7.2 pts) was shown as gaining **-4.4**
   (paired against WR D. Samuel, 11.6 pts) - a NEGATIVE "gain" rendered in
   the same green-highlight style as a real improvement, which should be
   structurally impossible (the optimizer never adds a player who scores
   less than who they're replacing).
   - **Root cause 3:** Pass 1's same-position search used the full
     FLEX-eligible union (`{RB, WR}`) whenever a gained player's own
     `optimal_slot` was "FLEX" - even though the player's own actual
     `position` is a single concrete value (here, M. Thomas is a WR who
     happened to be SOLVED into the FLEX slot). Searching the union let
     Thomas's "weakest displaced" search grab D. Harris (RB, 6.8 pts) -
     the weaker of the two candidates across both positions - instead of
     D. Samuel (WR, 11.6 pts), who was the actual FLEX-slot occupant
     Thomas effectively replaced. That left D. Singletary (RB, needing an
     RB partner) with no same-position candidate remaining, so it fell
     through to pass 2, which paired it against the only leftover -
     Samuel (WR, 11.6 pts, who outscores Singletary's 7.2) - producing
     the impossible negative "gain."
   - **Fix:** pass 1 now tries an EXACT position match first (Thomas's
     own position, "WR", against `removed` candidates) before falling
     back to the broader FLEX-eligible union - only relevant when no
     same-position candidate exists at all. `frontend/pages_matchups.py`,
     `_optimal_lineup_details()`.
   - **Verified:** Wk1 (Alex F) now shows M. Thomas +8.6 (correctly
     paired against D. Samuel, the real FLEX occupant it replaced),
     Buccaneers DEF +8.0, D. Singletary +0.4 (correctly paired against D.
     Harris, the real RB it replaced) - sums to 17.0, matching the true
     total exactly, no negative numbers. Re-verified every previously
     reported case (Wk4/Wk13/Wk15) still correct after this change.
     Re-swept all 1954 team-weeks: **1911/1954 now match exactly** (up
     from 1909), **0 negative gains anywhere in the archive** (this is
     the key invariant this fix specifically targets - checked
     explicitly, not just the sum-matching check). The remaining 43
     mismatches are the same two pre-existing, out-of-scope edge cases
     from root cause 2's verification above (2012's vestigial DB slot;
     weeks with a genuinely short archived lineup) - full itemized list
     (season/week/team/manager/numbers/reason) generated at
     `code/debugging/incorrect-matchups.csv` via
     `code/debugging/build_incorrect_matchups.py` for manual review.

4. Per explicit user direction: rather than continue chasing edge cases
   caused by 2012's vestigial "Defensive Back" IDP slot (already known to
   have no real candidate pool - bug 5's footnote), DB-position players
   are now excluded from the optimizer entirely, on both sides of the
   comparison. `_optimal_lineup_details()` filters `position == "DB"`
   players out of BOTH the actual-starters list and the bench pool passed
   to `compute_optimal_lineup()` before doing anything else - a DB
   starter is left completely untouched (never a swap candidate, never
   highlighted red/green), with their real points folded back into the
   returned `optimal_points` unchanged so the card's displayed total
   still matches the team's real score.
   - **Verified:** re-ran the earlier vestigial-slot example
     (`archive/parsed/2012/matchups/week_6_1_4.json`, home side) - gains
     now sum to exactly 44.48, matching the true diff exactly (previously
     understated by exactly the unfilled DB slot's absence), and the DB
     starter's `player_id` confirmed absent from both `gains` and
     `losses`. Re-swept all 1954 team-weeks: **1927/1954 now match
     exactly** (up from 1911), **0 negative gains** (unchanged/still
     holds). The remaining 27 mismatches were re-checked individually -
     all are the OTHER known edge case (a genuinely short archived
     lineup that week, unrelated to DB - see root cause 2 above), 0 are
     DB-related. Regenerated `code/debugging/incorrect-matchups.csv` (down
     to 27 rows, "Vestigial 'Defensive Back'..." reason category now
     empty/obsolete).

5. Per explicit user direction: the remaining 27 mismatches (a team's
   ARCHIVED actual lineup genuinely short a starter that week - see root
   cause 2 above) needed the missing slot treated as a real, legitimate
   0-point starter - i.e. the optimizer should still consider the
   next-best available bench player for it like any other slot, and (if
   no eligible bench player exists either) it should just stay a 0-point
   swap with nothing highlighted, rather than silently leaving `added`
   longer than `removed`.
   - **Fix:** `_optimal_lineup_details()` now calls the SAME
     `_pad_missing_starters()` helper the roster table already uses for
     display, inserting a `points: 0.0`, synthetic-`player_id` placeholder
     for any slot the archived lineup is short on, and uses that PADDED
     list (not the raw one) for the actual/removed side of the
     comparison. Crucially, the solver itself (`compute_optimal_lineup`)
     is still only ever given REAL players - the placeholders never enter
     its candidate pool, so its own output (and thus `optimal_points`,
     and backend `coaching.py`'s already-correct diff_sum) is completely
     unaffected; padding only changes what the display-attribution
     comparison treats as "already there." An empty FLEX slot's
     placeholder carries the literal "W/R" slot label as its `position`
     (matching what the roster table already shows for it) rather than a
     guessed concrete RB/WR value, since it's genuinely eligible for
     either - pass 1's same-position matching was extended with a
     dedicated `_flex_empty` check so an RB or WR bench player can still
     match it directly instead of falling through to pass 2.
   - **Verified:** re-ran a previously-mismatched short-lineup example
     (`archive/parsed/2012/matchups/week_2_1_3.json`, home side, 8 real
     starters against a 9-slot lineup) - gains now sum to exactly 22.2,
     matching the true diff exactly (previously 12.3, missing the empty
     RB slot's swap entirely). Re-verified every previously reported case
     (Wk1/Wk4/Wk13/Wk15) still correct. Re-swept all 1954 team-weeks:
     **1954/1954 now match exactly, 0 negative gains anywhere in the
     entire archive** - every previously-known edge case (2012's
     vestigial DB slot, short archived lineups) is now fully resolved.
     `code/debugging/incorrect-matchups.csv` regenerated - **0 rows**.

6. Per explicit user direction (using
   `archive/parsed/2012/matchups/week_2_2_4.json`'s away side, Jeremy vs
   Michael, as the illustrating example - Jeremy's empty RB slot getting
   filled by a 0.0-point bench RB was confirmed CORRECT/intentional, "NaN
   -> 0.0" being a real change worth showing): a REAL, already-rostered
   starter scoring 0.0 should never be shown swapped for an equally
   0.0-point bench "replacement" - that's not a meaningful change (0.0 ->
   0.0), unlike an empty slot going from no player at all to an actual
   0.0-point player.
   - **Fix:** `_optimal_lineup_details()` now collects every pass-1/
     pass-2 pair before turning any of them into `gains`/`losses` entries,
     then skips recording a pair where the computed gain is exactly 0.0
     AND the displaced player is a REAL starter (`not is_empty_slot`) -
     both sides simply stay un-highlighted. Since a skipped pair always
     contributes exactly 0 to the sum either way, `sum(gains)` still
     matches `optimal_points - actual_total` exactly even with pairs
     excluded this way.
   - **Verified:** re-ran the illustrating example
     (`week_2_2_4.json`, away/Jeremy) - completely unchanged, the empty
     RB slot's 0.0 swap is still shown exactly as before, confirming the
     "real starter" exclusion doesn't touch the empty-slot case. Traced
     every pair the two-pass algorithm considers across all 1954
     team-weeks directly (before either pass turns anything into
     `gains`/`losses`) looking for a pair matching this exact exclusion
     condition: **0 found anywhere in the archive** - `solve_optimal_lineup`'s
     stable sort already keeps a tied real starter in place by construction
     (starters are ordered before bench in its candidate pool, so a tie
     never favors swapping one out), so this fix doesn't change any
     currently-displayed number; it's a correctness safeguard for a
     combination that could theoretically arise from a different
     candidate ordering, not an active bug in today's output. Re-swept
     all 1954 team-weeks after the change: still 1954/1954 match exactly,
     0 negative gains, `code/debugging/incorrect-matchups.csv` still 0 rows.

### 9. [NOT A BUG IN THIS CODEBASE - upstream source data error] Justin Fields' 2023 season is mislabeled "PIT" (Pittsburgh) instead of "CHI" (Chicago) throughout NFL.com's own fantasy site data, breaking the new bye-week overlay
User-reported: the Players tab's bye-week feature (the blue "Bye Week"
marker on the Fantasy Points/NFL Stats per Game charts, backed by
`pages_players.py`'s `_bye_weeks_by_season`) flags Justin Fields' 2023
Week 6 as his NFL team's bye week, but he's ALSO shown as a fantasy
STARTER that week with real points (4.92) - a real player can't score
points during his own team's bye, so these two facts directly contradict
each other on screen.
- **Root cause, confirmed via the actual archived data (not
  speculation):** every single one of Justin Fields' 17 real
  `archive/parsed/2023/matchups/week_*.json` entries that season -
  all 17 weeks, no exceptions - has `"nfl_team": "PIT"`. He was
  genuinely on the Chicago Bears for all of 2023 (real-world fact - he
  was only traded to Pittsburgh in 2024), so this is wrong for the
  entire season, not just a stray week or two. Confirmed this is
  NFL.com's OWN fantasy site data being wrong, not a scraping/parsing
  bug in this project: the archived `"opp"` field for his week 6 entry
  even literally says `"Bye"` - fully self-consistent with treating him
  as a Pittsburgh player (Pittsburgh's real 2023 bye WAS week 6, per
  `archive/nfl_bye_weeks.json`), just wrong about which team he was
  actually on. Chicago's real 2023 bye was week 13, not 6.
- **Why this broke the new feature specifically:**
  `data_loader.player_nfl_team_by_season()` derives a player's NFL team
  per season from the most-common `nfl_team` value across their real
  matchup appearances that season - with Fields' entire 2023 unanimously
  (17/17) saying "PIT", there's no ambiguity for that function to get
  "right" from this input; it faithfully reports what the archived data
  says. The bug is entirely upstream, in what NFL.com's fantasy site
  itself recorded for this player that season.
- **Not fixed - deliberately left as-is:** there's no reliable way to
  detect or correct this kind of single-player, whole-season mislabeling
  from data already IN the archive (it's internally self-consistent, not
  contradictory in a way a validation pass could flag). This is exactly
  the class of problem `instructions/cool-features.md`'s "players"
  section future-feature note already anticipates - real NFL
  play-by-play/roster data (an actual per-week team assignment,
  independent of this league's own fantasy site) would be needed to
  catch and correct this kind of source error. Filed here for the
  record rather than silently patched with a one-player special case.
