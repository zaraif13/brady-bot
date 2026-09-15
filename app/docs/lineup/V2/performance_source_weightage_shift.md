# Weightage Shift for Player Performance Data

Here’s the exact weightage shift we outlined earlier for blending **previous season’s second-half data** with **current season data** as the season progresses. This applies to player performance metrics (target share, red-zone share, YPRR, etc.) and defensive metrics (EPA allowed, success rate).

## Weightage Shift by Gameweek

| Gameweek | Previous Season (Weeks 10–18) Weight | Current Season Weight | Notes |
|----------|--------------------------------------|------------------------|-------|
| **Week 1** | 100% | 0% | No current-season data exists. Use only the second half of the prior season. |
| **Week 2** | 75% | 25% | Week 1 data is incorporated but heavily discounted. |
| **Week 3** | 50% | 50% | Equal blend of prior season and current season. |
| **Week 4** | 25% | 75% | Current season now dominates. |
| **Week 5+** | 0% | 100% | Use only current-season data, with an internal decay so that more recent games are weighted more heavily than early-season games. |

## Internal Decay for Week 5 Onwards

Once you reach Week 5, you’re using 100% current-season data, but you shouldn’t weight Week 1 the same as Week 4. A simple exponential decay works well:

- **Half-life of 4 weeks**: A game played 4 weeks ago carries half the weight of a game played this week.
- **Formula**: `weight = 0.5 ^ (weeks_ago / 4)`

For example, in Week 8:
- Week 8 game: weight = 1.0
- Week 7 game: weight = 0.84
- Week 6 game: weight = 0.71
- Week 5 game: weight = 0.59
- Week 4 game: weight = 0.50
- Week 3 game: weight = 0.42
- Week 2 game: weight = 0.35
- Week 1 game: weight = 0.30

Then normalize the weights so they sum to 1.0 across all games played.

## Why This Schedule

- **Week 1** is purely a prior-season projection because no current data exists.
- **Weeks 2–4** gradually phase in current-season data while still respecting the larger sample from last season.
- **Week 5+** shifts entirely to current-season data because by then you have at least 4 games, which is enough to be more predictive than last season’s second half.
- **Internal decay** ensures that a player’s most recent form matters most, which is critical for injuries, role changes, and breakout performances.