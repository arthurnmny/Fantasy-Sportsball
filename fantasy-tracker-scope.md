# Fantasy Sports Tracker — Project Scope (v3)

A multi-sport fantasy league for 8 people. Each person drafts one team per league (7 leagues, 7 teams each). Instead of weekly free-standing scores, members are paired head-to-head each month, round-robin style, culminating in playoffs.

## 1. League format

- **8 members**, each owning **one team per league** across **7 leagues**: NFL, NBA, MLB, NHL, NCAA Football, NCAA Basketball, MLS.
- **56 total teams** rostered — no two members share a team.
- **Matchup period = one calendar month** (not a week). Each month, members are paired head-to-head.

## 2. Scoring (per team, per game)

| Outcome | Points |
|---|---|
| Loss | -1 |
| Tie | 0 |
| Push (win/loss vs. spread lands exactly on the line) | +1 |
| Win, doesn't cover the spread | +1 |
| Win, covers the spread | +2 (replaces the +1, not additive) |

(Correction from the prior draft: tie is **0**, not +1 — matches your original spec. Push still scores like a plain win, +1.)

**Multi-game periods:** if a team plays multiple games within the month (true for NBA/NHL/MLB, occasionally others), **every game counts** — points are summed across all games played that month, not just the most recent. This also means a member's monthly total scales with how many games their teams happened to play, which mostly evens out over a full season since teams in the same league play roughly the same number of games — but note NFL/NCAAF/MLS teams will contribute far fewer scoring events per month than NBA/NHL/MLB teams, so a member's monthly total is heavily weighted toward whichever of their 7 teams plays the most games that month.

## 3. Head-to-head format

- Each month, members are paired up. Each member's **monthly point total** (summed across all 7 teams' games that month) is compared to their opponent's. **Higher total wins the matchup.**
- **Schedule: round-robin.** With 8 members (an even number), a full round-robin needs 7 rounds (everyone plays everyone once) — no bye is mathematically required for 8 players, but you asked for one bye slot to be available if needed (e.g., if membership ever changes to an odd number, or you want a buffer/rest month). The schedule design should support an optional bye round rather than assuming exactly 7 rounds every season.
- **Season standings** are based on head-to-head record (wins/losses/ties in matchups), the same way typical fantasy football standings work.
- **Playoffs: top 4 of 8 members** (by regular-season record) qualify, single-elimination bracket — semifinals then final, i.e. **2 playoff-round months** on top of the regular season. Seeding by record; ties in record need a tiebreaker (suggest: head-to-head result if the two tied members played each other, otherwise total points across the season) — flag if you want a different tiebreaker.

## 4. Sport seasons don't align — but this is fine, not a fairness problem

The 7 leagues have staggered, unequal seasons (e.g., NFL/NCAAF run roughly September–January, NBA/NHL roughly October–April, MLB roughly April–September/October, MLS roughly February–October), so total points scored will vary month to month — some months more teams are active than others.

**This isn't a competitive imbalance**, since every member owns exactly one team per league. If NFL is dormant in June, it's dormant for all 8 members' NFL teams equally — nobody gains an edge from the calendar. It just means some months will produce lower point totals league-wide than others, which is fine.

What's still an open decision, purely for scheduling purposes (not fairness):

- **How long is a season?** With the playoff format now fixed (top 4, semis + final = 2 rounds) and a full round-robin needing 7 rounds, the minimum is **9 monthly rounds** (7 regular season + 2 playoff), plus optionally the 1 bye round you wanted available — so **9-10 months total**. Starting in **March** puts the season at **March through November/December** (10 months with the bye, 9 without). That window picks up the tail of NBA/NHL (playoffs through June), all of MLB (April–September/October) and most of MLS (February–October), and the start of the NFL/NCAAF/NCAAB season (August/September onward) — a genuinely different mix than a Sept-start season, but still symmetric across all 8 members either way, so no fairness issue either way.
- Once this is set, standings (head-to-head record) naturally falls out of it — a 9-round regular season just means each member's record is out of at most 7 games (the round-robin), since the 2 playoff rounds only involve the top 4.

## 4a. Draft-team availability caveat

One real (non-fairness) wrinkle: not every league's *entire slate* of teams is engaged at once — NCAAF/NCAAB playoffs/bowl seasons are short and top-heavy, MLB has 162 games spread over 6 months so scoring is steady, NFL has only ~17 games per team over ~4-5 months so scoring is sparse per team relative to NBA/NHL/MLB. This doesn't need solving now, just worth knowing that different leagues will contribute very different game *volumes* per team over a season — MLB/NBA/NHL teams will rack up far more scoring events than NFL/NCAAF teams over the full year.

## 5. Data source: The Odds API

Confirmed as the single data source for both spreads and results (see prior scope notes) — `/odds` (markets=spreads) for pre-game lines, `/scores` for final results, matched by event ID.

## 6. Data model

```
Member
  id, name

League
  id, name, odds_api_sport_key

OwnedTeam
  id, member_id, league_id, team_name, odds_api_team_id
  -- 56 rows once fully drafted

GameLine
  id, owned_team_id, odds_api_event_id, spread_for_team, captured_at

GameResult
  id, owned_team_id, odds_api_event_id, opponent_name,
  team_score, opponent_score, game_date, points, outcome
  -- 'points' is the per-game score from section 2, computed at ingest

Matchup
  id, period (e.g. "2026-11"), member_a_id, member_b_id,
  member_a_points, member_b_points, winner_id, is_playoff, round_name

Schedule
  id, period, round_number, member_a_id, member_b_id, is_bye
  -- generated once per season from the round-robin algorithm
```

`Matchup.member_a_points` / `member_b_points` are aggregates: the sum of `GameResult.points` across all of that member's 7 `OwnedTeam`s for games falling within that `period`.

## 7. Architecture

Same two-job shape as before (capture lines pre-game, score results post-game), with a third piece added for the head-to-head layer:

```
The Odds API → [capture lines job] → GameLine
             → [score results job] → GameResult (per-game points)
                                    ↓
                    [monthly aggregation job] → Matchup (sums GameResult
                                                 into each member's monthly
                                                 total, resolves winner)
                                    ↓
                              SQLite database
                                    ↓
                          FastAPI backend → Web dashboard
```

The monthly aggregation job only needs to run after each period closes (or on-demand for a live in-progress standings view).

## 8. Dashboard (MVP)

- **Standings**: head-to-head record (W-L-T) across all 8 members, playoff seeding position.
- **This month's matchups**: each pairing, running point totals for both sides, per-team breakdown.
- **Team detail**: game-by-game history, spread, cover/no-cover, points earned.
- **Schedule view**: full round-robin schedule for the season, including bye and playoff rounds.
- **Manual refresh** for line-capture / scoring / aggregation jobs.

## 9. Build order

1. Resolve the calendar/season-length question (section 4) — this determines how many months the schedule needs and where playoffs land.
2. Confirm playoff format (# of teams, bracket length, tiebreakers).
3. Get The Odds API working for all 7 sport keys; verify spread coverage on the thinner markets (NCAAB, MLS).
4. Build DB models.
5. Build the round-robin schedule generator (8 members, optional bye, into however many months section 4 lands on, plus playoff rounds).
6. Build the roster/draft seed (56 owned-team rows).
7. Build line-capture job.
8. Build scoring job (per-game points, per section 2's table).
9. Build monthly aggregation job (sums into `Matchup` rows, resolves winners).
10. Build read endpoints (`/standings`, `/schedule`, `/matchups/current`, `/teams/{id}`).
11. Build dashboard UI.
12. Wire up per-sport scheduling cadence for jobs 7–8, and period-end triggering for job 9.

## 10. Confirm before building

- [x] Season calendar: **10 months, March–December**, using the bye round.
- [x] Playoff seeding tiebreaker: **total points** (not head-to-head) when records are level.
- [ ] The Odds API quota — confirm your plan supports the request volume across 7 sports at whatever cadence the jobs end up running.
