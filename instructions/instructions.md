# NFL Fantasy League Archive — Execution Instructions

## Goal
Archive the complete public history of NFL.com Fantasy Football league
`1401993` (https://fantasy.nfl.com/league/1401993/) for seasons **2012–2025**
before the site is taken down. Preserve stats, results, games, transactions,
and metadata in a durable, structured, re-parseable format — not just raw
HTML dumps (though those should be kept too, as a fallback source of truth).

This file is the spec. A Claude Code session should execute it end-to-end:
crawl → parse → structure → verify → report.

---

## 0. Ground rules
- **Be polite to the server.** Add a delay (1–2s) between requests. This is
  a small public league site, not an API — no need to hammer it.
- **Save raw HTML alongside parsed JSON.** NFL.com's markup/JS rendering has
  changed across the ~13 year span this league covers; if a parser is wrong
  for some era, we need the raw page to re-parse later without re-fetching.
- **Idempotent / resumable.** Every fetch should check **whether** the raw file
  already exists on disk before hitting the network again. This lets the
  job be stopped and restarted freely.
- **Some older seasons may not use the same URL scheme** (NFL.com has
  redesigned fantasy several times; pre-2013 or so may redirect to an
  archived/legacy path, or may not be reachable at all). Detect and log
  this per season rather than assuming uniformity.
- **JS-rendered pages:** fantasy.nfl.com has historically required a
  headless browser (Playwright/Puppeteer) for some views (live scoring,
  transactions feed) rather than plain HTML. Use `requests`/`httpx` first;
  fall back to a headless browser per-page-type if content is empty/JS-shell.

---

## 1. Output directory structure

**Updated 2026-08-06 (Phase B, 2025 test):** there is no standalone
"scoreboard" endpoint (`.../scoreboard?week={w}` 404s) - matchup/box-score
pages are fetched per team via `teamgamecenter`, one file per
`(team_id, week)` pair, alongside that team's roster. Transaction pages
are grouped under their own `transactions/` subdirectory since a season
can have 50+ pages of them (lineup changes count as transactions here).

```
archive/
├── raw/
│   └── {year}/
│       ├── league_home.html            # same content as standings.html - see §3 note
│       ├── settings.html
│       ├── standings.html
│       ├── standings_regular.html      # ?historyStandingsType=regular
│       ├── schedule.html
│       ├── draft_results.html
│       ├── playoffs.html               # championship bracket
│       ├── playoffs_consolation.html   # ?bracketType=consolation&standingsTab=playoffs
│       ├── draft_results_by_nomination.html   # draftResultsDetail=0&draftResultsTab=nomination
│       ├── draft_results_by_team.html         # draftResultsDetail=0&draftResultsTab=team ($ bid amounts)
│       ├── transactions/
│       │   └── transactions_page_{n}.html
│       └── team_{team_id}/
│           ├── team_home.html
│           ├── roster_week_{w}.html       # teamhome?teamId={id}&week={w}
│           └── gamecenter_week_{w}.html   # teamgamecenter?teamId={id}&week={w}
├── parsed/
│   └── {year}/
│       ├── metadata.json        # settings, managers, draft info, scoring rules for that season
│       ├── standings.json       # final standings + regular-season-only standings
│       ├── draft.json           # full draft board (overall pick order, player, team, auction $)
│       ├── playoffs.json        # championship + consolation bracket structure/results
│       ├── schedule.json        # weekly matchup schedule (who played who)
│       ├── matchups/
│       │   └── week_{w}_{team_id_home}_{team_id_away}.json  # per-matchup box scores: starters/bench, points
│       ├── transactions.json    # adds/drops/waiver claims/lineup changes/league changes, with timestamps
│       └── rosters/
│           └── team_{team_id}_week_{w}.json   # composition only - stats are season-cumulative, see §2 warning
├── managers.json                # league-wide manager registry — see §2b
├── index.json                   # master manifest — see §4 (doubles as the "progress.json" originally planned; no separate file)
└── progress/
    ├── errors.log                # fetch failures, timestamp/url/status/error, for audit
    └── progress.html             # visual dashboard (see §5)
```

---

## 2. Data schema (per season, `parsed/{year}/`)

### metadata.json
Scoped strictly to: **settings, managers, draft info, scoring rules** for the
season. (Standings and playoffs live in their own files — see below.)

**Updated 2026-08-07 to match `code/raw-parsing/parse.py`'s actual output** (verified
against `archive/parsed/2025/metadata.json`):
```json
{
  "season": 2025,
  "league_id": "1401993",
  "league_name": "TheMusicLeague",
  "commissioner": "Ashwin",
  "settings": {
    "num_teams": 10,
    "roster_settings": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BENCH": 7, "RESERVE": 1},
    "waiver_type": "Resets to Inverse Standings Order",
    "trade_deadline": "November 21, 2025",
    "playoff_teams_and_weeks": "Weeks 15, 16 & 17 - 6 teams"
  },
  "scoring_rules": {"Passing Yards": "1 point per 25 yards", "...": "one entry per stat label found on settings.html - flat, not grouped by Offense/Kicking/Defense/IDP section"},
  "draft_info": {
    "draft_type": "auction",
    "draft_date": "Sep 3, 2025",
    "draft_format_raw": "Salary Cap"
  },
  "teams": [
    {"team_id": "1", "team_name": "The Nosehares", "manager_id": "2772924", "manager_display_name": "Ashwin"}
  ],
  "source_urls": [],
  "fetch_status": "ok",
  "notes": ""
}
```
Differences from the original spec:
- `roster_settings` keys are whatever `ROSTER_POSITION_LABEL_TO_KEY` in
  `parse.py` maps to (QB/RB/WR/TE/FLEX/K/DEF/BENCH/RESERVE) - an
  unrecognized label (e.g. a different flex/IDP config in another year)
  falls back to the raw NFL.com label text as the key instead of a
  normalized one (see `bugs.md`'s generalization risks).
- `settings.playoff_teams_and_weeks` replaces the originally-planned
  separate `playoff_teams`/`playoff_weeks`/`regular_season_weeks` fields -
  the source page only exposes this as one combined string (e.g. "Weeks
  15, 16 & 17 - 6 teams"); splitting it into structured fields wasn't
  implemented.
- `draft_info.draft_order` (planned) isn't populated - the full pick-by-pick
  order lives in `draft.json` instead (see below); `draft_date` is a
  best-effort regex extraction from a free-text scheduling string.
- `manager_id` is a real, persistent NFL.com `userId` (confirmed
  2026-08-06 via `.userName` spans on schedule/gamecenter/transactions
  pages) - not a synthetic key. `manager_display_name` was added since it
  comes for free from the same lookup and `managers.json` needs it.
- `commissioner` was added (available on settings.html, wasn't in the
  original spec).

### standings.json
Two views are required per season, since NFL.com separates them:
- **Final standings** — from `.../standings` — reflects postseason result
  (accounts for playoff bracket outcome, i.e. final rank/champion).
- **Regular season standings** — from `.../standings?historyStandingsType=regular`
  — reflects regular-season-only record/points, before playoffs.
**Updated 2026-08-07 to match actual output** (`archive/parsed/2025/standings.json`):
```json
{
  "season": 2025,
  "final_standings": [
    {"rank": 1, "team_id": "9", "team_name": "Sweeney's Genes", "wins": 11, "losses": 3, "ties": 0,
     "points_for": 1764.74, "points_against": 1282.82, "champion": true}
  ],
  "regular_season_standings": [
    {"rank": 1, "team_id": "9", "team_name": "Sweeney's Genes", "wins": 11, "losses": 3, "ties": 0,
     "points_for": 1764.74, "points_against": 1282.82}
  ],
  "notes": ""
}
```
Differences from the original spec:
- No `manager_id` per standings row - join against `metadata.json`'s
  `teams` list (or `managers.json`) by `team_id` if a manager needs to be
  attached; standings.json only carries what the standings page itself
  exposes.
- `final_standings`' wins/losses/ties/points_for/points_against are
  actually **regular-season figures merged in from
  `regular_season_standings`**, not true postseason win-loss - the
  standings page's final/postseason view only shows rank + team name +
  (for the top 3 only) a "Reg. Season: W-L-T, Points For" string, so full
  stats for all 10 teams have to come from the regular-season view
  instead. `notes` on the real output explains this; see `playoffs.json`
  for actual postseason bracket results.

### playoffs.json
Captures the postseason bracket structure and results, both championship
and consolation sides. Source pages:
- `.../history/{year}/playoffs` — championship bracket
- `.../history/{year}/playoffs?bracketType=consolation&standingsTab=playoffs` — consolation bracket

Bracket shape (number of rounds, byes, seeding) varies by season/league
size — parse whatever round/matchup structure is actually present rather
than assuming a fixed number of rounds; record it generically as an ordered
list of rounds, each containing matchups in bracket order.

**Structural notes confirmed 2026-08-06 (user domain knowledge, applies to
all seasons, not just the 2025 test case):**
- Both brackets are **single elimination**.
- The **championship bracket** seeds the top teams from regular-season
  standings; the **consolation bracket** seeds the bottom teams. The cutoff
  (how many teams go to each bracket) varies by season/league size — derive
  it from the actual bracket contents per season, don't hardcode a split.
- **Byes** for top seeds occur in some years but not others (seen in the
  2025 test: team `teamId-9` and `teamId-1` had byes in the first round).
  Don't assume byes are present or absent — detect them per season from
  whether a `matchups[].seed_away`/`team_id_away` side is empty/"BYE" in
  the source markup.
- A single week can contain multiple **placement games** rather than a
  strict binary tree advancing one match per round — e.g. 2025 week 17
  had "Fantasy Super Bowl", "3rd Place Game", and "5th Place Game" all as
  separate matchups in the same `round`. `round_name` should capture the
  game's actual label, not an inferred round number/name.
**Updated 2026-08-07 to match actual output** (`archive/parsed/2025/playoffs.json`) -
each bracket's matchup entries carry more fields than originally specced,
and the winner detection uses a generic "lowest placement number in the
final round" rule (`_placement_number`/`_find_bracket_winner` in
`parse.py`) that works for both brackets, since "Fantasy Super Bowl"
(placement 1) and "7th/9th/11th Place Game" labels are really the same
naming scheme continued past the championship side:
```json
{
  "season": 2025,
  "championship_bracket": {
    "rounds": [
      {
        "round_name": "Week 15",
        "round_order": 1,
        "matchups": [
          {
            "bracket_position": 1,
            "round_label": "Quarterfinal",
            "week_label": "Week 15",
            "seed_home": 1, "team_id_home": "9", "score_home": null,
            "seed_away": null, "team_id_away": "", "score_away": null,
            "is_bye": true,
            "winner_team_id": ""
          }
        ]
      }
    ],
    "champion_team_id": "9",
    "runner_up_team_id": "2"
  },
  "consolation_bracket": {
    "rounds": ["... same shape as championship_bracket.rounds ..."],
    "consolation_winner_team_id": "5"
  },
  "source_urls": [],
  "fetch_status": "ok",
  "notes": "Byes and placement-game structure vary by season - see instructions.md section 2 notes."
}
```
Differences from the original spec:
- `round_name` (on the round object) is the **week label** (e.g. "Week
  15"), not a bracket-round name like "Quarterfinal" - that name lives on
  each individual matchup as `round_label` instead, since (as noted
  above) a single week/round can contain multiple differently-labeled
  placement games rather than one uniform round name.
- Added `week_label` (duplicate of the round's `round_name`, included per
  matchup for convenience) and `is_bye` (explicit boolean, rather than
  relying on callers to infer a bye from an empty `team_id_away`).
- A bye matchup's `score_home`/`seed_away` are `null` and
  `team_id_away`/`score_away` are `""`/`null` respectively -
  `winner_team_id` is also `""` for byes (a bye isn't "won", the team
  just advances).

### draft.json
Source: **full-view URLs, not the paginated default** - `draftresults`
alone only returns 10 picks (page 1 of a paginated view). Fetch
`draftResultsDetail=0` for both `draftResultsTab=nomination` (pick
order/player/team) and `draftResultsTab=team` (auction bid amounts) - see
§3.

**Updated 2026-08-07 to match actual output** (`archive/parsed/2025/draft.json`):
```json
{
  "season": 2025,
  "draft_type": "auction",
  "picks": [
    {"overall_pick": 1, "player_id": "2564148", "player_name": "Jonathan Taylor",
     "position": "RB", "nfl_team": "IND", "team_id": "4", "auction_amount": null}
  ],
  "notes": "auction_amount is null for keeper picks (no auctionCost span in source markup)."
}
```
Differences from the original spec:
- No separate `round`/`pick` fields - only `overall_pick` (nomination
  order for auction drafts; would be the true round-by-round pick number
  for snake drafts, though that code path is unverified - see
  `bugs.md`'s generalization risks).
- Added `player_id` (NFL.com's internal player ID) since it's a more
  reliable join key than player name across pages, and is what's used to
  match nomination-order picks to their auction bid amount.
- `auction_amount` is `null` for both snake drafts (field doesn't apply)
  and auction-draft keeper picks (no cost - set before the live auction).

### schedule.json
Source: **derived from already-fetched gamecenter pages, not
schedule.html.** `schedule.html` without a `?week=` parameter only
returns week 1 - rather than fetch 17 more pages, `parse_schedule_from_gamecenters()`
reads each team's already-downloaded `gamecenter_week_{w}.html` and pairs
up both sides' `team_id` from the matchup header, de-duplicating by team
pair per week.
```json
{
  "season": 2025,
  "weeks": [
    {"week": 1, "matchups": [{"team_id_home": "1", "team_id_away": "2", "matchup_id": "2025_w1_1_2"}]}
  ]
}
```
A week's `matchups` list will have fewer than a full slate during bye
weeks (playoff weeks with byes) - a bye team's gamecenter page shows only
one team, so it's correctly excluded rather than represented as a
one-sided matchup.

### matchups/week_{w}.json
Filename in practice: `week_{w}_{team_id_home}_{team_id_away}.json` (one
file per real matchup that week, not per team). Source: one team's
`gamecenter_week_{w}.html` per matchup - that single page's box score
already contains both sides' starters and bench with real per-week stats.
```json
{
  "season": 2025, "week": 10, "matchup_id": "2025_w10_1_2",
  "home": {"team_id": "1", "score": 104.34, "starters": [], "bench": []},
  "away": {"team_id": "2", "score": 114.98, "starters": [], "bench": []}
}
```
Each roster slot entry:
`{"slot": "QB", "player_name": "", "position": "", "nfl_team": "", "opp": "", "points": 0.0, "stats": {"stat_5": "306", "stat_6": "2"}}`
- `stats` keys are `stat_{N}` where N is the scoring-rule stat ID (see
  `metadata.json`'s `scoring_rules` - the gamecenter page's `<span
  class="statId-N">` and the roster page's `<td class="stat_N">` both use
  the same numbering, confirmed 2026-08-06).
- Added `position` (per-player NFL position, distinct from `slot` which
  is the *roster slot* the player occupied, e.g. slot "FLEX" but position
  "RB") - wasn't in the original per-slot-entry shape.
- **This is the source of truth for per-week fantasy performance** - see
  the rosters/ caveat below, which does NOT have correct weekly stats.

### transactions.json
```json
{
  "season": 2012,
  "transactions": [
    {"date": "", "type": "add | drop | trade | waiver", "team_id": "",
     "players_in": [], "players_out": [], "waiver_priority": null, "trade_partner_team_id": null}
  ]
}
```
**Updated 2026-08-07 to match actual output** (`archive/parsed/2025/transactions.json`):
```json
{
  "season": 2025,
  "transactions": [
    {"date": "Dec 27, 2:52pm", "week": 17, "type": "Lineup", "player_name": "Eddy Pineiro",
     "from": "BN", "to": "K", "message": "", "by_manager_id": "4771952", "by_manager_display_name": "Forrest"}
  ]
}
```
Differences from the original spec:
- Single-player-per-row shape (`player_name`/`from`/`to`), not the
  planned `players_in`/`players_out`/`trade_partner_team_id` batch shape -
  the source table is one row per player action, so a trade shows up as
  multiple linked rows rather than one combined record.
- `type` values observed so far: `Lineup`, `Add`, `Drop`, and `LM`
  (commissioner/league-setting change - see `message` below). `Trade` and
  `Waiver` are listed as filter options in the page nav but weren't
  observed in the 2025 data pulled.
- `team_id` replaced with `by_manager_id`/`by_manager_display_name` (the
  persistent NFL.com `userId`, same as `metadata.json`'s `teams[].manager_id`) -
  more useful than a season-scoped team_id for cross-season queries.
- `waiver_priority` isn't populated (not present in the confirmed row
  shape).
- **Confirmed 2026-08-06:** `"LM"` rows have no player and no from/to,
  just a free-text description (e.g. "Ashwin changed Draft Time to 'Sep 3,
  2025 8:00pm PDT'") in a `message` field; empty string for normal player
  transactions.

### rosters/team_{team_id}_week_{w}.json
Weekly full roster snapshot (starters + bench), same slot schema as matchups.

**⚠️ Known bug, unfixed as of 2026-08-07 (see `bugs.md` #4):** the
`points`/`stats` values on this page are season-cumulative totals, NOT
that week's performance, despite the page being labeled per-week and
matching this schema's original intent - confirmed by comparing the same
player's stats across multiple weeks (identical every time). Roster
*composition* (which players/slots) does appear to be correct per week.
**Use `matchups/week_{w}.json` for actual weekly stats/points** - its
gamecenter source already includes full starters+bench for both teams in
a matchup with genuinely week-specific numbers.

---

## 2b. Manager registry (`archive/managers.json`)
**Assumption to build around:** `team_id` values are not stable across
seasons, and are tied to whichever manager owned that team slot that year
— which may also change year to year (a manager can leave, a new manager
can take over an existing "team" slot, etc). So team identity and manager
identity must be tracked as two separate, cross-referenced entities:

- Every season's `metadata.json` teams list records `team_id` (season-scoped)
  + `manager_id` (persistent).
- `managers.json` is the reverse index: one entry per unique manager,
  listing every `(season, team_id, team_name)` they held.

**Updated 2026-08-06 - resolution is simpler than originally planned:**
NFL.com exposes a persistent per-manager `userId` (found embedded in
`.userName` spans on schedule/gamecenter/transactions pages, e.g.
`<span class="userName userId-2772924">Ashwin</span>`), so managers are
grouped directly by that stable ID (`code/raw-parsing/managers.py`) - no fuzzy
display-name matching needed. A team only lands in `unresolved` if its
`metadata.json` entry has no `manager_id` at all (i.e. the schedule page
didn't expose one for that team that season), not because of an
ambiguous name match. Verified 2026-08-07 against 2025: 10/10 teams
resolved, 0 unresolved.

**Updated 2026-08-07 to match actual output** (`archive/managers.json`):
```json
{
  "managers": [
    {
      "manager_id": "2772924",
      "display_names_seen": ["Ashwin"],
      "seasons": [
        {"season": 2025, "team_id": "1", "team_name": "The Nosehares"}
      ],
      "notes": ""
    }
  ],
  "unresolved": [
    {"season": 2016, "team_id": "5", "display_name": "", "reason": "no manager_id found in metadata.json for this team"}
  ]
}
```

---

## 3. URL inventory to crawl (per season, 2012–2025)

Base: `https://fantasy.nfl.com/league/1401993/history/{year}/`
(For the **current** season only — likely 2025 or whichever is active —
some of these live at `https://fantasy.nfl.com/league/1401993/...` without
the `/history/{year}/` prefix. Try history path first; fall back to
current-season path if 404/redirect.)

**Confirmed 2026-08-06 (Phase B test, 2025 season):** `.../history/{year}/`
alone is **not** a valid endpoint — it 404s ("Page Not Found"). The season
"home" page is the standings page: `.../history/{year}/standings`. Archive
this response under both `league_home.html` and `standings.html` (§1) since
it's the same content serving two roles. `.../history/{year}/settings`
confirmed working and returns real static (non-JS-shell) markup.

**Updated 2026-08-06/07 - table below is the confirmed-working set** (see
`code/raw-parsing/fetch.py`'s `SEASON_URL_TEMPLATES`/`TEAM_HOME_TEMPLATE`/
`TEAM_ROSTER_TEMPLATE`/`TEAM_GAME_CENTER_TEMPLATE`/`TRANSACTIONS_TEMPLATE`
for the authoritative source):

| Purpose | URL pattern |
|---|---|
| League home | `.../history/{year}/standings` (same page as Standings final — see note above) |
| Settings | `.../history/{year}/settings` |
| Standings (final) | `.../history/{year}/standings` |
| Standings (regular season) | `.../history/{year}/standings?historyStandingsType=regular` |
| Schedule | `.../history/{year}/schedule` (only returns week 1 without a `?week=` param — see schedule.json note in §2; not actually re-fetched per week) |
| Draft results (by nomination order) | `.../history/{year}/draftresults?draftResultsDetail=0&draftResultsTab=nomination&draftResultsType=results` |
| Draft results (by team, with $ bid amounts) | `.../history/{year}/draftresults?draftResultsDetail=0&draftResultsTab=team&draftResultsType=results` |
| Playoffs — championship bracket | `.../history/{year}/playoffs` |
| Playoffs — consolation bracket | `.../history/{year}/playoffs?bracketType=consolation&standingsTab=playoffs` |
| Transactions (paginated) | `.../history/{year}/transactions?offset={n}` |
| Team home | `.../history/{year}/teamhome?teamId={team_id}` |
| Team roster by week | `.../history/{year}/teamhome?teamId={team_id}&week={w}` |
| Team matchup / box score by week | `.../history/{year}/teamgamecenter?teamId={team_id}&week={w}` |

Notes:
- ~~`.../history/{year}/scoreboard?week={w}`~~ **does not exist** (404s) -
  confirmed 2026-08-06. There is no standalone weekly scoreboard page;
  matchup data is fetched per-team via `teamgamecenter` instead (used for
  both `matchups/week_{w}.json` and to derive `schedule.json`, since
  `schedule.html` itself only returns week 1).
- ~~`.../history/{year}/team?teamId={team_id}`~~ is **wrong** - the real
  endpoint is `teamhome`, not `team` (confirmed via the playoffs bracket
  page's team links).
- **Draft results pagination gotcha:** `.../draftresults` alone (no query
  params) only returns picks 1-10 (page 1 of a 10-per-page paginated
  view) - use `draftResultsDetail=0` for the full draft in one request,
  for both tabs (nomination gives pick order + team; team gives auction $
  amounts, needed since they're not shown in the nomination view).
- `team_id` values must first be discovered from the standings or schedule
  page for that season (they are not guaranteed stable across years).
- Regular season length: 13 weeks through ~2020, 14 weeks 2021+ (NFL moved
  to 17 regular-season games in 2021) — verify against each season's
  schedule page rather than hardcoding; also detect actual playoff weeks
  from the settings/schedule page. `code/raw-parsing/fetch.py`'s
  `discover_team_ids_and_weeks()` does this automatically per season by
  regex-scanning the standings/schedule raw HTML.
- Transactions pagination: keep requesting `offset` in increments of 25
  until a page shows the "No transactions" empty-state text - **do not**
  compare consecutive pages for exact-duplicate content to detect the
  end, since every page (including empty ones) embeds volatile
  per-request ad-tracking fields (`AD_ORD`, `TIME`), so no two fetches
  are ever byte-identical (confirmed 2026-08-06, see `bugs.md`).

---

## 4. Master manifest (`archive/index.json`)
One row per (season × page-type) so completion can be checked at a glance:
```json
{
  "generated_at": "",
  "seasons": {
    "2012": {
      "metadata": "ok",
      "standings_final": "ok", "standings_regular": "ok",
      "draft": "missing",
      "playoffs_championship": "ok", "playoffs_consolation": "ok",
      "schedule": "ok", "weeks_fetched": [1,2,3], "weeks_total": 13,
      "transactions_pages_fetched": 4, "transactions_complete": true,
      "rosters_fetched": 130, "rosters_expected": 156,
      "errors": []
    }
  },
  "managers_registry": {
    "total_managers": null,
    "unresolved_count": 0
  }
}
```
Update this file after every successful parse (not just at the end) so
progress survives interruption.

---

## 5. Progress visualization
Generate `archive/progress/progress.html`: a single self-contained HTML
file (no external deps) that reads `progress.json` (inline or fetched) and
renders:
- A grid: rows = seasons (2012–2025), columns = data types (metadata,
  standings_final, standings_regular, draft, playoffs_championship,
  playoffs_consolation, schedule, weekly matchups, transactions, rosters) —
  green/yellow/red cell per status.
- A manager registry summary: total unique managers resolved, and a count
  of `unresolved` entries needing manual review.
- Per-season completion % bar.
- Overall completion %.
- A list of specific errors/gaps (e.g. "2015 week 9 scoreboard: 404").

Regenerate this file each time `index.json` is updated so it can be opened
in a browser at any point to check status without re-running anything.

---

## 6. Execution order
1. Fetch league home + settings for **one** known-good recent season first
   to confirm URL patterns/markup still match assumptions above — **adjust
   this instructions file if NFL.com's structure differs** before mass
   crawling.
2. For each season 2012→2025:
   a. Fetch + parse metadata (settings, managers, draft info, scoring rules),
      standings (both final and regular-season views), draft board, schedule,
      and playoffs (both championship and consolation brackets).
   b. Discover team_ids and week count from the above.
   c. Reconcile each season's managers into `managers.json` (match by
      display name / profile id where available; add unresolved entries
      rather than guessing when ambiguous).
   d. Fetch + parse each week's scoreboard/matchups.
   e. Fetch + parse each team's weekly roster.
   f. Fetch + parse all transaction pages.
   g. Update `index.json` after each sub-step.
3. Regenerate `progress.html` after each season completes.
4. Final pass: scan `index.json` for any `missing`/`partial` entries and
   retry those specifically. Also review `managers.json.unresolved` for
   any manager identities needing manual confirmation.
5. Produce a final summary report (`archive/SUMMARY.md`): total seasons
   archived, total games/matchups, total transactions, total unique
   managers found, any permanently unreachable pages, and file counts.

---

## 7. Tooling suggestions (for the Claude Code session)
- Python: `httpx` or `requests` + `BeautifulSoup4` for static HTML;
  `playwright` for any JS-rendered views.
- Store fetch timestamps and HTTP status codes with every raw file (e.g. a
  sidecar `.meta.json`) for auditability.
- Log all failures to `archive/progress/errors.log` with URL, timestamp,
  status code, and exception text.