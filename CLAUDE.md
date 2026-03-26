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
  },
  "projections": {
    "batters":  {"Aaron Judge": {"AB": "522", "R": "124", "HR": "50", ...}, ...},
    "pitchers": {"Tarik Skubal": {"INNs": "180", "W": "14", "ERA": "2.85", ...}, ...}
  },
  "eligibility": {
    "positions_2025": {"Aaron Judge": ["OF", "DH"], "Jose Ramirez": ["3B", "DH"], ...},
    "games_2025":     {"Aaron Judge": {"OF": 140}, ...},
    "games_2024":     {"Aaron Judge": {"OF": 130}, ...}
  }
}
```

### Web App (`docs/index.html`)

**Batters tab** — columns: C, 1B, 2B, 3B, SS, LF, CF, RF, DH
- Each cell: starter (bold) + 1 backup (gray/small)

**Pitchers tab** — 9 columns: SP1, SP2, SP3, SP4, SP5, CL1, CL2, SU1, SU2
- Each cell: one player; `PITCHER_COL_MAP` maps column name to `[data_key, index]`

**Features:**
- Checkbox per player → marks as drafted + opens Assign modal to place on roster
- Unchecking a checkbox → undrafts and removes from roster
- Injury `!` flag in grid — only shown for real injuries (keyword-matched); all notes still appear in hover tooltip
- Tooltip shows CBS AL rank, projection stats, eligibility, and injury note
- "Hide drafted" toggle for the grid
- Ranked list below grid: filtered to current tab (batters on Batters tab, pitchers on Pitchers tab), with search, position filter, and hide-drafted toggle
- Position filter rebuilds on tab switch (only shows relevant positions)
- Batter ranked list columns: Rank, Name, Pos, Eligible (with 2025 games count), AVG, HR, RBI, SB, R, Injury
- Pitcher ranked list columns: Rank, Name, Pos, ERA, W, S, WHIP, K, Injury
- **Injuries tab**: lists all players with real injury notes, sorted by CBS rank; shows likely replacement (first healthy player at same position, with MI/CI/OF/CL overlaps)
- **Last Week tab**: MLB.com news from the past 7 days, organized by team; only player-relevant headlines (blocklist filters out TV/streaming/tickets/nostalgia/odds); deduplicated by normalized headline; shows "as of" timestamp
- **Run Scraper** button in header → opens GitHub Actions page to trigger a fresh scrape
- **Reset Draft** button clears all drafted marks and the full roster

**Teams displayed** (AL_ORDER): BAL, BOS, NYY, TB, TOR, CWS, CLE, DET, KC, MIN, HOU, LAA, OAK, SEA, TEX

### Roster Panel

Fixed 220px panel on the right side of the screen showing your roster in progress.

**Slots (23 total):**
- Batters: C, C, 1B, 2B, 3B, SS, OF, OF, OF, OF, OF, MI, CI, Util
- Pitchers: SP, SP, SP, SP, SP, CL, CL, SU, SU
- Unassigned section at the bottom for players not yet placed

**Interactions:**
- Click a player name in the panel → opens Assign modal for reassignment
- **Clear Roster** button in panel removes all slot assignments (keeps drafted marks)
- Roster state persisted in `localStorage` (`ff_roster` key): `{ slots: {slotId: name}, unassigned: [name, ...] }`
- `ROSTER_SLOTS` constant defines all slots with `{id, label, type, elig}` — `elig` lists which positions can play that slot (used to color-code the assign modal)

### Quick Search (`/` key)

Press `/` anywhere (not while typing in another input) to open the floating search overlay.

- Type part of a player name; results update instantly (up to 8 matches)
- Results show team, position, CBS rank, and drafted/rostered status tags
- ↑/↓ to navigate, Enter to select; Escape to close
- Selecting a player: marks as drafted, pre-adds to Unassigned, opens Assign modal

### Assign Modal

Opens when: checking a checkbox, selecting from quick search, or clicking a name in the roster panel.

- Shows player name and position eligibility at the top
- Batter slots and pitcher slots shown in separate groups
- **Slot color coding:**
  - Blue = eligible for this slot and currently empty (best pick)
  - Orange = eligible but slot is occupied (will bump that player to Unassigned)
  - Grey = player is not eligible for this slot (still clickable for flexibility)
  - Dark blue = player's current slot (when reassigning)
  - Yellow `?/TBD` = Unassigned (always available)
- **Remove from roster** button visible only when reassigning an already-rostered player (keeps drafted mark, removes slot assignment)
- Cancel is always safe — player stays in their current state

---

## One-Time Data Scripts (run locally, do NOT add to daily scrape)

### Projections (`parse_projections.py`)

Parses tab-separated text copied from CBS projected stats pages into `data.json`.

**Setup:**
1. Go to https://pochicago.baseball.cbssports.com/stats/stats-main
2. Click Projections → set Timeframe = Rest of Season, Categories = Standard
3. Run "All Players - Batters" → select all → copy → paste into `batters2026.txt`
4. Run "All Players - P" → select all → copy → paste into `pitchers2026.txt`

**Run:**
```
python parse_projections.py
git add docs/data.json && git commit -m "Add projections" && git push
```

Row format in the text files: `{action}\t{Name POS • TEAM}\t{stat1}\t...\t{Rank}`
- Batter columns: AB, R, H, 1B, 2B, 3B, HR, RBI, BB, K, SB, CS, AVG, OBP, SLG, Rank
- Pitcher columns: INNs, APP, GS, QS, CG, W, L, S, BS, HD, K, BB, H, ERA, WHIP, Rank
- Rank is excluded from stored stats (already in CBS rankings)

Note: `scrape_projections.py` is a Playwright-based alternative that was attempted but abandoned — CBS page JS polluted the columns. Use `parse_projections.py` (text copy-paste approach) instead.

### Position Eligibility (`build_eligibility.py`)

Builds position eligibility from Lahman/SABR data and merges into `data.json`.

**One-time download** (not committed to repo): https://sabr.app.box.com/s/y1prhc795jk8zvmelfd3jq7tl389y6cd
Place `People.csv` and `Fielding.csv` in the project root.

**Run:**
```
python build_eligibility.py
git add docs/data.json && git commit -m "Update eligibility" && git push
```

**Eligibility rules:**
- 20+ games at a position in 2025 → eligible there
- LF / CF / RF / OF all collapse to OF
- Everyone is eligible at DH
- If no position reaches the threshold in 2025 → DH-only
- 2024 game counts are stored in `data.json` for future use (e.g. injury exceptions) but do NOT affect current eligibility logic

**Name matching** (CBS names → Lahman playerIDs):
- `norm()`: NFKD unicode normalization (ñ→n, é→e), strip Jr./Sr./II/III/IV suffixes, replace all non-alphanumeric with spaces, collapse whitespace — handles accents, initials (C.J., J.P.), hyphens (Kiner-Falefa)
- Two-pass: primary search (players with 2024/2025 fielding data), secondary fallback (all of People.csv) — handles pitchers and recent acquisitions with no fielding data
- `best_candidate()`: prefers players with recent data, eliminates already-claimed PIDs, tries team match
- `NAME_OVERRIDES` dict for cases `norm()` can't resolve (nicknames, middle initials):
  - `'Joshua Lowe'` → `'lowejo01'` (Lahman: "Josh Lowe")
  - `'Jt Ginn'` → `'ginnjt01'` (Lahman: "J. T. Ginn")
  - `'Josh H. Smith'` → `'smithjo09'` (TEX infielder; middle initial needed to disambiguate)
- Lahman team map: NYA→NYY, TBA→TB, CHA→CWS, KCA→KC, ATH→OAK

---

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
- Does NOT run `parse_projections.py` or `build_eligibility.py` — those are one-time local scripts
