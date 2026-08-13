# history
- [x] add spreadsheet table stats views

# seasons
- [x] schedule tab, kinda similar games view but restricted
- [x] standings tab
- [x] breakdown tab
- [x] coach tab
- [x] true tab
- [x] transactions tab
- [x] create schedule tab for each week

# managers
- [ ] records and stats vs all other managers, filter all time or year
- [ ] show points for missed out on, players with 0 points
- [ ] show per player week of detailed stats for current roster
- [ ] show chart of all starts vs bench per week
- [ ] show depth order per week
- [ ] highlight missing depth
- [ ] highlight bye weeks and projected depth
- [ ] every where team name is listed created icon with logo/name/manager that can open modal showing historical stats/etc
- [ ] per week - starters, bench, injuried (NFL), optimal, bye, got injured (NFL)
- [ ] manager stats, web chart vs other managers, custom stats, etc
- [ ] 

# players
- [x] below fantasy points per game chart show stats per game
- [x] show all weeks as 0 if player not on fantasy roster across full nfl season
- [x] filter player stats per season

# matchups
- [x] fix defenses not having (TEAM)
- [x] once manager 1 selected, remove seasons they didn't participate in

# drafts
- [ ] adp
- [ ] adp/price compared to that season's stats
- [ ] nfl team stats
- [ ] draft value over years, see chart of all positions (ie WR) who is best value
- [ ] full order, final rosters, most expensive auction stuff. across all drafts average pick, average cost
- [ ] 

# feedback
- [x] feedback for new features/bugs/improvements, see github issues in table and chart




History
- All-time head-to-head matrix: every manager pair's career W-L-T in a heatmap/grid, clickable into that rivalry's game log.
- "Championship drought" tracker — years since each manager's last title, sorted longest-to-shortest.
- Rivalry page: pick two managers, see their full head-to-head history, biggest blowout, closest game, and swing in the standings each meeting caused.
- Auto-generated season "story" blurb per year (already have _render_season_summary_paragraph-style logic) extended into a short recap paragraph per season, not just all-time.
- Trophy case per manager — logos/years for 1st/2nd/3rd, visual rather than table-only.

Seasons — Season Summary / Schedule
- Weekly "Power Rankings" chart blending win%, points for, and all-play record into one index, tracked week over week.
- Auto-generated weekly awards: Coach of the Week (best/worst optimal-lineup gap), Upset of the Week (biggest win % underdog).
- Compare-two-seasons view: same manager (or same league) side by side across two years.
- Playoff-picture tracker: as-of-this-week standings plus "what they need" to make the postseason bracket.

Seasons — Regular Season / Post Season / Bracket
- Strength-of-schedule column: each team's average opponent win% for the season.
- Season-long "optimal lineup" total (points left on bench across the whole year), same idea as the Players tab's per-game version but aggregated.
- Bracket what-if: show the alternate bracket outcome if seeds had been reordered by points-for instead of win-loss.

Seasons — Season Settings
- Diff view between two seasons' settings (scoring rule/roster changes year over year) — useful since league rules clearly evolved over 14 years.
- Draft recap tied to draft_info: who drafted a future top scorer earliest, biggest reach/steal by pick position (needs Players page correlation).

Players
- ADP vs. performance ("steals and busts") once/if draft position data is available per player.
- Manager loyalty: which manager rostered a given player across the most seasons/teams.
- Breakout/decline flags: players whose points-per-game trended sharply up or down within a season.
- Positional trends across all 14 years (e.g., is RB scoring declining league-wide over time).

Games / Matchups
- Closest-games and biggest-blowouts all-time leaderboards, filterable by manager.
- "Revenge game" indicator — flag a matchup as a rematch following a previous loss between the same two managers.
- Margin-of-victory distribution chart (are games trending closer or more lopsided over the years).

Cross-page
- Global "jump to" search (manager, season, or player name) that routes to the right page/filter, extending the st.switch_page pattern already used for records and champions.
- Retroactive trade grader: compare a trade's two players' rest-of-season point totals to grade who "won" the trade.