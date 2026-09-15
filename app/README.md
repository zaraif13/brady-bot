# Brady Bot

Dark-mode Atlas web app for fantasy football. One FastAPI host, one nav bar, two
sections today:

| Section | Route | What it does |
|---|---|---|
| Lineup Picker | `/` | Weekly optimal lineup from your roster |
| True Depth Chart | `/true-depth` | Published depth chart, toggleable to usage-derived order |

## Run locally

```bash
cd app
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # set ODDS_API_KEY if available
uvicorn brady_bot.api:app --reload --port 8000
```

Open http://127.0.0.1:8000/ — or `./run.sh` once the venv exists.

## Adding a section

The nav is generated from `js/sections.js`. A new section needs:

1. A page at `app/<section>.html` (nav element: `data-nav-root data-nav-active="<id>"`)
2. Front-end modules under `js/<id>/`
3. API routes under `/api/<id>/` in `src/brady_bot/api.py`
4. Specs under `docs/<id>/`
5. One entry appended to `SECTIONS` in `js/sections.js`

Nothing else renders the nav, so no page-level header edits are needed.

## Layout

```
app/
  index.html, true-depth.html, login.html   # section pages
  js/            api.js, nav.js, sections.js + js/<section>/
  src/brady_bot/ shared Python package (sources, derive, pickers, api)
  docs/          lineup/, depth-chart/ specs
  config/        league, weights, overrides
  tests/
  deploy/
```

## Production (zaraifhossain.com/brady-bot)

- Serve this directory at `/brady-bot/`
- Proxy `/brady-bot/api/` to uvicorn/gunicorn on the API port
- See `deploy/nginx-snippet.conf` and `deploy/brady-bot.service`

## CLI (optional)

```bash
brady-bot lineup pick --week 5
brady-bot lineup validate
```

## Operational notes

**`TeamRanksError` early in a season is expected, not a regression.** Team ranks
require all 32 teams to have enough S3 weeks on the books. Before the league is
fully represented (and outside the Weeks 1–4 prior-season blend window),
`derive_team_ranks` halts loudly instead of inventing placeholder teams. Wait
until coverage is complete or run inside a blended early week.

**Weeks 1–4 lean on depth chart position, and that is deliberate.** `pos_rank` is
the early-season anchor for RB Step 3 (30%), WR Step 3 (20%) and FLEX Step 2
(40%), fading 100% → 75% → 50% → 25% → 0% across Weeks 1–4. From Week 5 real snap
share and target share carry those factors alone and `pos_rank` contributes
nothing to any score — it is still read to identify starters for the QB/TE gates
and injury unit counts. Scores are RB 1.00/0.30/0.00, WR 1.00/0.60/0.25/0.00, TE
1.00/0.00. Full tables in `docs/lineup/lineup-picker-depth-chart.md`.

**Stale preseason depth charts are corrected in `config/committee_overrides.yaml`.**
The file keeps its old name but holds `depth_overrides` entries now — a manual
`pos_rank` for a player whose published chart is known wrong, typically a late
free-agent signing or a post-cuts chart that has not caught up. Overrides are
checked before the published chart and always win. A rostered RB/WR/TE the chart
omits scores 0.00 and is listed under `NO DEPTH ENTRY`, because absence can mean a
data gap rather than a real demotion. From Week 5 the risk disappears on its own.

**The committee-change rule is retired.** The 0.50 neutral substitution and
automatic committee-change detection are gone (D16, superseded by D19): `pos_rank`
reads the player's current team's current depth chart, so it already reflects a new
situation. The per-game denominator rule — rates divide by games the player was
healthy and played — is unaffected and still in force. See
`docs/lineup/lineup-picker-committee.md` for the retirement record.

**True Depth Chart is computed live from nflreadpy**, not stored. The published
grid comes from `load_depth_charts` (pinned to each team's latest `dt`) plus
`load_injuries`; the usage reordering comes from season-to-date target share
(WR/TE) and rush share (RB). Specs in `docs/depth-chart/`.
