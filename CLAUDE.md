# fantasy-bb

AL-only rotisserie fantasy baseball draft tools. GitHub repo: `jcubb/fantasy-bb`.
GitHub Pages app: https://jcubb.github.io/fantasy-bb/

---

## Open Slots Tool (`fantasy_bb.py` + `fantasy_bb.xlsx`)

Solves: given a partially drafted roster, which positions are currently open (or could be opened by rearranging players)?

### League rules
- AL teams only
- Roster slots: C×2, 1B, 2B, 3B, SS, OF×5, MI (2B or SS), CI (1B or 3B), Util (any)
- Position eligibility: 20+ games at a position in 2025, or 5+ games in 2026

### How it works
Uses **bipartite matching** (augmenting-path DFS). For each output position (C, 1B, 2B, 3B, SS, OF, DH), the algorithm tries removing each slot that could serve that position and checks whether a full matching of the remaining players still holds. If not, that position is open.

MI/CI/Util bleed-through is handled correctly:
- If MI is free → both 2B and SS show as open
- If CI is free → both 1B and 3B show as open
- If Util is free → DH shows as open
- DH-eligible-only players can only go in the Util slot

### Output
- Excel file (`fantasy_bb.xlsx`) with a Roster sheet (Open? row + player eligibility grid) and a Candidates sheet (Can Fit? + # Open Positions for any player you're considering)
- Run: `python fantasy_bb.py`

---

## Draft Day Web App (`scrape.py` + `docs/`)

### Architecture
- **`scrape.py`**: Playwright scraper — writes `docs/data.json`
- **`docs/index.html`**: Static GitHub Pages app — reads `data.json` at runtime
- **`docs/data.json`**: Scraped data (committed to repo so the app works without running scrape.py)

### Scraper (`scrape.py`)

**Depth charts** — one CBS page per position (`/fantasy/baseball/depth-chart/{POS}/`):
- Table structure: ROWS = teams, COLS = [Team | Starter | Backup | SP3 | SP4 | SP5]
- AL table identified by `.TableBase-title` containing "American"
- Team extracted from `a[href*="/mlb/teams/"]` in cells[0]
- Players extracted from `.CellPlayerName--long a` in subsequent cells
- Depth captured: batters = starter + 1 backup; SP = 5; RP = 4 (first 2 → CL, next 2 → SU)

**Rankings** — CBS AL roto top-300 (`/fantasy/baseball/rankings/roto/top300/AL/`):
- Page renders 4 identical copies of the list (1200 `[class*="player-row"]` elements total)
- Deduplicated by CBS player ID from href
- Full name extracted from URL slug (`aaron-judge` → `Aaron Judge`)
- Post-scrape: names reconciled to canonical depth chart names via normalized matching (handles "Jr." vs "Jr", "deGrom" vs "Degrom", etc.)

**To refresh data:**
```
python scrape.py
git add docs/data.json && git commit -m "Refresh data" && git push
```
Takes ~5 minutes. Uses the project venv: `C:/Users/gcubb/OneDrive/Python/.venv`

**`data.json` structure:**
```json
{
  "scraped_at": "...",
  "news_scraped_at": "...",
  "depth_chart": {
    "NYY": {
      "C":  [{"name": "Austin Wells", "injury": null}, ...],
      "SP": [{"name": "Max Fried", "injury": null}, ...],   // up to 5
      "CL": [{"name": "David Bednar", "injury": null}, ...], // up to 2
      "RP": [{"name": "Camilo Doval", "injury": null}, ...]  // up to 2 (setup men)
    }
  },
  "rankings": {
    "Aaron Judge": {"rank": 1, "pos": "RF"},
    ...
  },
  "news": {
    "NYY": [
      {"headline": "Yankees option Smith to Triple-A", "date": "2026-03-23T...", "blurb": ""}
    ],
    ...
  }
}
```

### Web App (`docs/index.html`)

**Batters tab** — columns: C, 1B, 2B, 3B, SS, LF, CF, RF, DH
- Each cell: starter (bold) + 1 backup (gray/small)

**Pitchers tab** — 9 columns: SP1, SP2, SP3, SP4, SP5, CL1, CL2, SU1, SU2
- Each cell: one player; `PITCHER_COL_MAP` maps column name to `[data_key, index]`

**Features:**
- Checkbox per player → marks as drafted (persisted in `localStorage`)
- Injury `!` flag in grid — only shown for real injuries (keyword-matched); all notes still appear in hover tooltip
- Tooltip shows CBS AL rank + injury note
- "Hide drafted" toggle for the grid
- Ranked list below grid: filtered to current tab (batters on Batters tab, pitchers on Pitchers tab), with search, position filter, and hide-drafted toggle
- Position filter rebuilds on tab switch (only shows relevant positions)
- **Injuries tab**: lists all players with real injury notes, sorted by CBS rank; shows likely replacement (first healthy player at same position, with MI/CI/OF/CL overlaps)
- **Last Week tab**: MLB.com news from the past 7 days, organized by team; only player-relevant headlines (blocklist filters out TV/streaming/tickets/nostalgia/odds); deduplicated by normalized headline; shows "as of" timestamp
- **Run Scraper** button in header → opens GitHub Actions page to trigger a fresh scrape
- Reset Draft button clears all checkboxes

**Teams displayed** (AL_ORDER): BAL, BOS, NYY, TB, TOR, CWS, CLE, DET, KC, MIN, HOU, LAA, OAK, SEA, TEX

---

## Phase 2 (deferred)

- **SABR/Lahman data** for position eligibility calculation
  - `People.csv` for player ID ↔ name mapping (handle same-name disambiguation by team/age)
  - `Fielding.csv` for games-by-position in 2025/2026
  - Data files: https://sabr.app.box.com/s/y1prhc795jk8zvmelfd3jq7tl389y6cd
- Hovering a player name shows position eligibility (currently placeholder)


### News scraper (`scrape_team_news` in `scrape.py`)

Scrapes `https://www.mlb.com/{slug}/news` for each AL team using Playwright.

- `MLB_NEWS_SLUGS` maps team abbr → MLB.com slug (e.g. `NYY` → `yankees`)
- Captures up to 30 most recent articles per team, filters to last 7 days by parsed date
- **Deduplication**: normalizes headline (lowercase, strip punctuation) and skips repeats
- **Blocklist** (`_NEWS_BLOCKLIST` regex): skips TV/streaming, tickets, nostalgic/historical, odds/betting, fantasy rankings, draft, etc. — only player-action stories pass through
- Dates from MLB.com are sometimes just times ("10:05 AM EDT") rather than full ISO dates; date parsing handles multiple formats with a fallback
- Blurbs often empty (MLB.com DOM structure); headlines are the primary content

### GitHub Actions (`/.github/workflows/scrape.yml`)

- Triggers: `workflow_dispatch` (manual, via Run Scraper button) + daily cron at 11am UTC (7am ET)
- Runs on `ubuntu-latest`: installs Python 3.11, playwright + chromium, runs `scrape.py`
- Commits updated `docs/data.json` with message `Auto-refresh data YYYY-MM-DD HH:MM UTC`
- Does `git pull --rebase` before pushing to avoid race condition when local changes were pushed since the workflow started

