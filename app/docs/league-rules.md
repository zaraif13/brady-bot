# Dhaka Chamber of Football 2026 — League Rules
> Brady Bot reference document. Last updated: August 27, 2026.

---

## What's in This File

This document is Brady Bot's authoritative reference for the Dhaka Chamber of Football 2026 league. It covers everything Brady Bot needs to know about how this specific league operates — not general fantasy football strategy, but the exact rules, settings, and constraints of this 14-team Yahoo league.

The file is structured in the following order:

1. **League Identity** — League ID, platform, URL, keeper settings.
2. **Draft** — Draft format, pick timer, draft order, and Zaraif's pick position.
3. **Roster Construction** — Starting lineup slots, bench depth, and IR slot with Brady Bot allocation notes.
4. **Scoring Format** — Head-to-head structure and what it means for weekly optimization.
5. **Scoring Settings** — Full breakdown of offensive, kicker, and DST scoring with exact point values, comparison to Yahoo defaults, and module-specific implications for Brady Bot.
6. **Waiver Wire** — FAB system mechanics, waiver timing, acquisition limits, and FAB bid sizing guidance.
7. **Trades** — Deadline, veto rules, draft pick trade restrictions, and timing strategy.
8. **Playoffs** — Bracket structure, Week 17 risk flags, reseeding rules, and tiebreaker logic.
9. **Key Flags for Brady Bot Modules** — A consolidated quick-reference table summarising the most important scoring and rule adjustments that each Brady Bot module needs to account for.

---

## League Identity

| Setting | Value |
|---|---|
| League ID | 92544 |
| League Name | Dhaka Chamber of Football 2026 |
| Platform | Yahoo Fantasy Sports |
| Custom URL | https://football.fantasysports.yahoo.com/league/dhakachamber |
| Teams | 14 |
| Keeper League | Yes (2 keepers, cost = round drafted + 2) |
| Keeper Deadline | August 22, 2026 |

---

## Draft

| Setting | Value |
|---|---|
| Draft Type | Live Standard Draft (snake) |
| Draft Time | Thu Aug 27, 7:00pm +06 |
| Pick Timer | 1 minute, 30 seconds |
| Draft Order | Musti, Zaraif, Farzhad, Marc, Jamil, Imtiaz, Walid, Shahwaz, Arif, Misha, Shahan, Rahat, Armina, Sam |
| Zaraif's Pick | 2nd overall |
| Draft Pick Trades | Not allowed |
| Post-Draft Players | Follow waiver rules |

**Brady Bot note:** 90-second clock means the draft assistant must surface a ranked recommendation immediately. Priority list and tier breaks must be pre-loaded before the draft starts.

---

## Roster Construction

| Slot | Position |
|---|---|
| QB | 1 |
| WR | 2 |
| RB | 2 |
| TE | 1 |
| W/R/T (Flex) | 1 |
| K | 1 |
| DEF | 1 |
| BN | 6 |
| IR | 1 |

**Brady Bot notes:**
- One flex (W/R/T): RBs and WRs compete for it. Track flex EV weekly; TEs rarely win the slot unless elite.
- One IR slot: always move IR-eligible players there immediately to free a bench spot. Yahoo allows direct-to-IR adds from waivers for injured players.
- Six bench spots: target allocation — 2 handcuffs, 1 backup QB, 1 streaming DST, 1–2 breakout stashes.

---

## Scoring Format

### Head-to-Head
- Pure H2H, no median game, no second opponent, no divisions.
- Optimize for **beating the weekly opponent**, not maximizing raw point volume.
- Fractional points: yes. Negative points: yes.

---

## Scoring Settings

### Offense

| Category | League Value | Yahoo Default |
|---|---|---|
| Passing Yards | 30 yards per point | 25 yards per point |
| Passing Touchdowns | 5 | 4 |
| Interceptions | -2 | -1 |
| Pick Sixes Thrown | -2 | 0 |
| Rushing Yards | 10 yards per point | — |
| Rushing Touchdowns | 6 | — |
| Receptions | 0.5 | — |
| Receiving Yards | 10 yards per point | — |
| Receiving Touchdowns | 6 | — |
| Return Touchdowns | 6 | — |
| 2-Point Conversions | 2 | — |
| Fumbles | -1 | 0 |
| Fumbles Lost | -2 | — |
| Offensive Fumble Return TD | 6 | — |

**Brady Bot notes:**
- **QB:** Efficiency over volume. A pick six costs -4 total (-2 INT + -2 pick six). Prioritize high TD:INT ratio and ball security over raw yardage. Avoid turnover-prone QBs (Stafford-type profiles).
- **Passing yards are nerfed** (30 yds/pt vs 25 default): a 300-yd game = 10pts here vs 12pts default. TD rate matters more than volume.
- **Half-PPR confirmed:** reception value is moderate. Target efficiency (yards/target, TD rate) matters slightly more than raw target volume vs full PPR.
- **Fumble lost = -2** applies to all skill positions. Flag fumble-prone RBs at roster construction.

### Kickers

| Category | League Value | Yahoo Default |
|---|---|---|
| FG 0–19 yards | 1 | 3 |
| FG 20–29 yards | 2 | 3 |
| FG 30–39 yards | 3 | — |
| FG 40–49 yards | 4 | — |
| FG 50+ yards | 5 | — |
| FG Missed 0–19 yards | -2 | 0 |
| FG Missed 20–29 yards | -1 | 0 |
| PAT Made | 1 | — |
| PAT Missed | -1 | 0 |

**Brady Bot notes:**
- **Distance-premium system.** Two 50-yard FGs = 10pts before PATs. Long-range kickers are significantly more valuable than in standard leagues.
- **Short-range FGs are nearly worthless** (1pt) and missing them is costly (-2). Avoid kickers on red zone-efficient offenses that convert short FGs frequently.
- **Ideal kicker profile:** strong leg (50+ yard range), high FG attempt volume, offense that stalls mid-range rather than scoring TDs from close in, dome or good-weather market.
- **PAT volume is real:** 1pt per PAT adds up on high-TD offenses.
- **EP Phenom screen:** tune to weight 50+ yard attempt rate and mid-range stall rate, not just raw attempt volume.

### Defense / Special Teams

| Category | League Value | Yahoo Default |
|---|---|---|
| Sack | 1 | 1 |
| Interception | 2 | 2 |
| Fumble Recovery | 2 | 2 |
| Touchdown | 6 | 6 |
| Safety | 3 | 2 |
| Block Kick | 3 | 2 |
| Return Yards | 30 yards per point | 0 |
| Kickoff and Punt Return TDs | 6 | 6 |
| 4th Down Stops | 2 | 0 |
| Three and Outs Forced | 0.5 | 0 |
| Extra Point Returned | 2 | — |
| Points Allowed 0 | 10 | 10 |
| Points Allowed 1–6 | 8 | 7 |
| Points Allowed 7–13 | 5 | 4 |
| Points Allowed 14–20 | 2 | 1 |
| Points Allowed 21–27 | -1 | 0 |
| Points Allowed 28–34 | -4 | -1 |
| Points Allowed 35+ | -7 | -4 |

**Brady Bot notes:**
- **Points-allowed cliff is steep and punishing.** A DST giving up 28–34 pts costs -4; 35+ costs -7. Never start a DST in a projected blowout or high over/under game.
- **Matchup filtering is critical.** DST variance is high in both directions — great games score more, bad games cost much more. Amplifies the case for streaming over hero DST holds.
- **Three and outs forced (0.5) + 4th down stops (2) are unique.** Rewards elite pass-rush defenses that force quick punts even without turnovers or TDs.
- **Return yards (30 yds/pt) adds a small floor boost** to DSTs on teams with elite returners. Track this as a tiebreaker between otherwise equal streaming options.
- **Stream-trigger model** must heavily weight the points-allowed penalty curve. A DST projected to face a 28+ point offense is almost certainly a bench/drop regardless of talent floor.

---

## Waiver Wire

| Setting | Value |
|---|---|
| Waiver Type | FAB (Free Agent Bid) with reverse standings tiebreak |
| Waiver Clears | Tuesday (game time) |
| Waiver Wait | 2 days |
| Max Acquisitions per Week | No limit |
| Max Acquisitions per Season | No limit |
| Injured player to IR | Allowed directly from waivers |

**Brady Bot notes:**
- **FAB is a finite, non-resetting budget.** Brady Bot must track remaining FAB for all 14 teams (available via Yahoo API) and bid strategically — not just "is this player worth adding?" but "what's the minimum bid to win this player given competitive bids?"
- **Bid sizing framework:**
  - Large bids (significant FAB): confirmed RB1 vacated role, elite WR2 promotion, must-have injury replacements.
  - Small bids ($1–5): speculative stashes, handcuffs with low competition, one-week streamers.
  - Zero bids ($0): backup DSTs, kickers no one else wants, insurance adds.
- **No acquisition limits:** be as aggressive as needed. Streaming is unconstrained.
- **2-day waiver window:** players dropped Monday are available Wednesday. Useful for picking up reactive drops after bad weeks.

---

## Trades

| Setting | Value |
|---|---|
| Trade Deadline | November 28, 2026 (approx. Week 12) |
| Draft Pick Trades | Not allowed |
| Trade Review | League votes |
| Veto Threshold | Default (Yahoo: 4 votes in a 14-team league) |
| Trade Reject Time | 1 day |

**Brady Bot notes:**
- **No draft pick trades:** pure player-for-player only. Simplifies the trade engine.
- **Veto risk is real:** league votes on all trades. Flag trades that look one-sided to outside observers — high-value lopsided deals are veto-prone. Brady Bot should score veto risk before sending any offer.
- **Deadline is Week 12:** flag urgency as it approaches. The buy-low window tightens significantly after Week 10.
- **1-day reject time:** send trade offers early in the week for maximum response window.

---

## Playoffs

| Setting | Value |
|---|---|
| Playoff Teams | 7 of 14 |
| Playoff Weeks | Week 15, 16, 17 (ends Mon Jan 4, 2027) |
| Tiebreaker | Best regular season record vs common opponents |
| Reseeding | No |
| Divisions | No |

**Brady Bot notes:**
- **Top half (7/14) makes playoffs.** Positioning matters from Week 1 — never treat a loss as acceptable.
- **Week 17 is a landmine.** Teams with nothing to play for rest starters. Brady Bot must flag all playoff roster spots for Week 17 schedule risk: avoid players on teams who have clinched or are eliminated by then.
- **No reseeding:** bracket locks at end of Week 14. Seeding at that point is final — track playoff bracket implications from Week 10 onward.
- **Tiebreaker is head-to-head record vs common opponents:** track this for seeding races in tight standings.

---

## Key Flags for Brady Bot Modules

| Module | Key Adjustment |
|---|---|
| QB ranking | Weight TD:INT ratio and ball security heavily. Pick six = -4 total. Penalize fumble-prone mobile QBs. |
| WR/RB/TE ranking | Half-PPR as specced. Add fumble-prone flag (-2 per fumble lost). |
| Kicker module | Distance-premium scoring. Rebuild EP Phenom screen around 50+ yard rate and mid-range stall rate. |
| DST module | Steep points-allowed penalty curve. Stream-trigger must filter for projected points allowed first. Add 3-and-out and pass-rush metrics as tiebreakers. |
| Waiver wire | FAB budget manager required. Non-resetting budget. Bid sizing must account for competitive landscape per player. |
| Trade module | Veto risk scorer needed. No draft pick trades. Deadline urgency flag from Week 10. |
| Playoff module | Week 17 roster risk flag. Seeding tracker from Week 10. No reseeding after Week 14. |
