# history
- [x] add spreadsheet table stats views
- [ ] Auto-generated season "story" blurb per year (already have _render_season_summary_paragraph-style logic) extended into a short recap paragraph per season, not just all-time.

# seasons
- [x] schedule tab, kinda similar games view but restricted
- [x] standings tab
- [x] breakdown tab
- [x] coach tab
- [x] true tab
- [x] transactions tab
- [x] create schedule tab for each week
- [ ] season stats tab - Margin-of-victory distribution chart (are games trending closer or more lopsided over the years).
- [ ] Weekly "Power Rankings" chart blending win%, points for, and all-play record into one index, tracked week over week.

# managers
- [ ] records and stats vs all other managers, filter all time or year, head to head matrix heatmap, click into matchups page
- [ ] show points for missed out on, players with 0 points
- [ ] show per player week of detailed stats for current roster
- [ ] show chart of all starts vs bench per week
- [ ] show depth order per week
- [ ] highlight missing depth
- [ ] highlight bye weeks and projected depth
- [ ] every where team name is listed created icon with logo/name/manager that can open modal showing historical stats/etc
- [ ] per week - starters, bench, injuried (NFL), optimal, bye, got injured (NFL)
- [ ] manager stats, web chart vs other managers, custom stats, etc
- [ ] All-time head-to-head matrix: every manager pair's career W-L-T in a heatmap/grid, clickable into that rivalry's game log.
- [ ] biggest blowout, closest game - rivalries
- [ ] championship drought
- [ ] "Revenge game" indicator — flag a matchup as a rematch following a previous loss between the same two managers.
- [ ] 

# players
- [x] below fantasy points per game chart show stats per game
- [x] show all weeks as 0 if player not on fantasy roster across full nfl season
- [x] filter player stats per season
- [ ] complement fantasy-roster availability with REAL NFL stats/roster data for weeks a player wasn't on any fantasy roster - currently a week with no fantasy owner just shows as a flat red "unrostered" 0, even if the player actually played (or was on their real NFL team's bye) that week; pulling in real NFL play-by-play/roster status would let the chart distinguish "genuinely unrostered but played" from "bye week" from "actually inactive/injured," and would also let "NFL Games"/bye-week logic handle a mid-season NFL trade correctly (two different real byes in one season) instead of the current one-bye-per-season assumption (see pages_players.py's _render_summary_metrics)
- [ ] analysis tab - shows player usage, trends, breakout/decline

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

# global
- [ ] search/jump/filter to manager/season/player

# trade
- [ ] trade grader: compare a trade's two players' rest-of-season point totals to grade who "won" the trade.
- [ ] trade proposer
- [ ] 

# fun zone
- [ ] be prompted a players transfer history, try to guess the player
- [ ] guess league stats
- [ ]