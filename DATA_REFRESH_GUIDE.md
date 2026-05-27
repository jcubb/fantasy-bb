# Fantasy-BB Data Refresh Guide (2027 Season)

Step-by-step instructions to update this tool with fresh data for the next
fantasy baseball season. No knowledge of the project internals or fantasy
baseball is required — just follow the steps in order.

---

## Overview — What You're Doing

This tool combines four types of data for an AL-only fantasy baseball draft:

| Data | Source | How obtained | Script |
|------|--------|-------------|--------|
| **Depth charts** (who starts for each team) | CBS Sports | Automated scraper | `scrape.py` |
| **Rankings** (CBS top-300 AL players) | CBS Sports | Automated scraper | `scrape.py` |
| **Projections** (predicted season stats) | CBS league site | Automated scraper (or manual fallback) | `scrape_projections.py` |
| **Salary estimates** (projected auction values) | CBS league site | Manual copy-paste → text file | `parse_projections.py` |
| **Position eligibility** (which positions each player can play) | Lahman/SABR database | Manual CSV download | `build_eligibility.py` |
| **Team news** (recent MLB headlines) | MLB.com | Automated scraper | `scrape.py` |

All of these merge into one file — `docs/data.json` — which powers the web app.

**Order matters.** Run the scripts in this sequence:
1. Scraper first (creates depth charts + rankings that other scripts reference)
2. Projections + salaries second
3. Eligibility third (references names already in `data.json`)

---

## Prerequisites

### Software you need
- **Python 3.11+** with the project venv: `C:/Users/gcubb/OneDrive/Python/.venv`
- **Playwright** (browser automation, installed in the venv)
- **Git** (to push changes to GitHub)
- A web browser (Chrome, Edge, or Firefox) for the manual copy-paste steps

### Verify the venv works
```powershell
C:/Users/gcubb/OneDrive/Python/.venv/Scripts/Activate.ps1
cd C:/Users/gcubb/OneDrive/Python/fantasy-bb
python --version    # should be 3.11+
python -c "from playwright.async_api import async_playwright; print('OK')"
```

If Playwright is missing or outdated:
```powershell
pip install playwright
playwright install chromium
```

---

## Step 1: Update Year References in Code

Several files have hardcoded year numbers. Before doing anything else, update
them for the new season.

### 1a. `scrape_projections.py` and `parse_projections.py` — input file names

Both scripts reference the text file names:
```python
BATTER_FILE  = BASE_DIR / 'batters2026.txt'
PITCHER_FILE = BASE_DIR / 'pitchers2026.txt'
```
Change `2026` → `2027` (or whatever the draft year is) in both files.

### 1b. `build_eligibility.py` — eligibility year

This script uses fielding data from the *previous* season (the season that just
finished) to determine what positions each player qualifies at. For a 2027
draft, you want 2026 fielding data.

**Line 110** — the year filter:
```python
if year not in (2024, 2025):
```
Change to `(2025, 2026)` — i.e., last season and the one before it.

**Line 125** — which year is "current":
```python
if year == 2025:
```
Change to `2026`.

**Variable names throughout the file** say `2025` and `2024` (e.g.,
`games_2025`, `positions_2025`, `teams_2025`). You can either rename them to
`2026`/`2025`, or leave them as-is since only the year filter logic matters
for correctness. If you rename, also update the JSON keys at line 353:
```python
'positions_2025': positions_2025,
'games_2025':     games_2025_named,
'games_2024':     games_2024_named,
```
**Important**: if you change these JSON key names, you must also update
`docs/index.html`, which reads `positions_2025` and `games_2025` by name.
Search for `positions_2025` and `games_2025` in `index.html` (~15 references)
and update them. **Easier option**: keep the key names as `positions_2025` /
`games_2025` even though the underlying data is from 2026. The app doesn't
display these key names to users.

### 1c. `build_eligibility.py` — NAME_OVERRIDES

The `NAME_OVERRIDES` dict (line 54) maps CBS player names to Lahman playerIDs
for names the automatic matching can't resolve. **Review and update** after
running the script — it prints unmatched names. You may need to add new
overrides or remove stale ones for players who retired or changed leagues.

### 1d. Check for team changes

If any MLB team has relocated, rebranded, or changed its abbreviation since
last season:
- Update `AL_TEAMS` and `CANONICAL` in `scrape.py` (lines 27–53)
- Update `LAHMAN_TEAM` in `build_eligibility.py` (lines 42–47)
- Update `MLB_NEWS_SLUGS` in `scrape.py` (lines 73–79)

*As of 2026, the Oakland Athletics were transitioning to Sacramento. CBS used
both `ATH` and `OAK` — the scraper handles both. Verify CBS still does this.*

---

## Step 2: Run the Scraper (Depth Charts + Rankings + News)

This fetches current depth charts, player rankings, and team news from CBS
Sports and MLB.com. It takes about 5 minutes.

```powershell
C:/Users/gcubb/OneDrive/Python/.venv/Scripts/Activate.ps1
cd C:/Users/gcubb/OneDrive/Python/fantasy-bb
python scrape.py
```

**What to check:**
- Output should list 15 AL teams with data
- ~200–300 ranked players found
- News for each team (some teams may have 0 articles if it's the offseason)

**If the scraper fails**, it's usually because CBS or MLB.com changed their
HTML structure. Common fixes:
- Check that the URLs in `POSITION_URLS` and `RANKINGS_URL` still work in a
  browser
- Check that the CSS selectors (`.CellPlayerName--long`, `[class*="player-row"]`,
  etc.) still match the page structure
- Run with `headless=False` (change line 443) to watch the browser and debug

After a successful scrape, commit:
```powershell
git add docs/data.json
git commit -m "Refresh depth charts and rankings for 2027"
git push
```

---

## Step 3: Scrape Projections

Projections come from the **league-specific** CBS stats page. The scraper
saves date-stamped snapshot files that accumulate over time — pre-season
projections are preserved even after mid-season re-scrapes.

```powershell
C:/Users/gcubb/OneDrive/Python/.venv/Scripts/Activate.ps1
cd C:/Users/gcubb/OneDrive/Python/fantasy-bb
python scrape_projections.py
```

**First run:** A browser window will open and prompt you to log in to CBS
Sports. Log in manually — the session will be saved to `.cbs_session.json`
for future runs.

**Subsequent runs:** The saved session is restored automatically. The script:
1. Navigates to the CBS stats page
2. Clicks Projections → sets filters (Batter, Rest of Season, Standard)
3. Extracts the table via clipboard copy
4. Repeats for Pitchers
5. Saves `batters_YYYY-MM-DD.txt` and `pitchers_YYYY-MM-DD.txt`

**What to check:**
- Should write two date-stamped files (check the file sizes)
- If the session has expired, the browser will prompt for login again

**If automated navigation fails:** The script falls back to showing manual
setup instructions and waits for you to configure the page in the browser
before extracting.

---

## Step 4: Load Projections into the App

Choose which projection snapshot to load into `data.json`:

```powershell
python load_projections.py
```

The script lists all available snapshots with player counts:
```
Available projection snapshots:

  1. 2027-03-15  (batters: 100, pitchers: 100)
  2. 2027-06-10  (batters: 100, pitchers: 100)

Choose [2]:
```

Press Enter to accept the default (latest), or type a number to pick an
older snapshot. The selected data is merged into `docs/data.json`.

After success, commit:
```powershell
git add docs/data.json
git commit -m "Update projections"
git push
```

### Manual fallback (if scraper breaks)

If `scrape_projections.py` stops working (CBS changed their page structure),
use `parse_projections.py` with manual copy-paste:

1. Go to: **https://pochicago.baseball.cbssports.com/stats/stats-main**
2. Click Projections → set Timeframe = Rest of Season, Categories = Standard
3. Run "All Players - Batters" → Ctrl+A → Ctrl+C → paste into `batters2027.txt`
4. Run "All Players - P" → Ctrl+A → Ctrl+C → paste into `pitchers2027.txt`
5. Run: `python parse_projections.py`

---

## Step 5: Copy CBS Salary Projections (Manual)

Salary projections are not yet automated. They may not be available mid-season.

1. On the same CBS stats page, find the **salary projections** view
   (the page that shows projected auction values for each player)
2. Make sure it includes an **AL-Only** salary column
3. Select all → copy → paste into `fantasy-bb/salproj.txt`
4. Run: `python parse_projections.py` (it reads `salproj.txt` if present)

After success, commit:
```powershell
git add docs/data.json
git commit -m "Add salary projections"
git push
```

---

## Step 6: Download Lahman Database Files

The Lahman Baseball Database is a free, comprehensive historical database of
MLB statistics maintained by SABR (Society for American Baseball Research).

1. Go to: **https://sabr.app.box.com/s/y1prhc795jk8zvmelfd3jq7tl389y6cd**
   *(If this link is broken, search for "Lahman Baseball Database download"
   or "SABR Lahman database" — it's a well-known public dataset.)*
2. Download **`People.csv`** (~20,000 rows, maps player IDs to real names)
3. Download **`Fielding.csv`** (~100,000+ rows, games played by position per year)
4. Place both files in the `fantasy-bb/` project root directory
   (same folder as `build_eligibility.py`)

**Note**: These files are NOT committed to the git repo (they're large and
publicly available). You need fresh copies each year because the latest season's
data won't be in older downloads.

**Timing**: Lahman data for a given season is typically available several months
after the season ends (around January–February of the following year). For a
2027 draft, you need the version that includes 2026 fielding data. If the
latest Lahman release doesn't include the most recent season yet, the script
will still work but eligibility will be based on older data.

---

## Step 7: Run the Eligibility Builder

```powershell
C:/Users/gcubb/OneDrive/Python/.venv/Scripts/Activate.ps1
cd C:/Users/gcubb/OneDrive/Python/fantasy-bb
python build_eligibility.py
```

**What to check:**
- Should match ~90%+ of CBS player names to Lahman records
- "Unmatched CBS names" list should be short (< 20); these players get DH-only
  eligibility, which is a safe default
- "Ambiguous matches" are resolved automatically but worth scanning — if a
  well-known player is matched to the wrong person, add an entry to
  `NAME_OVERRIDES`
- Multi-position eligible players should include recognizable names

**If many names are unmatched**, common causes:
- Lahman CSV is outdated (doesn't include recent season's players)
- CBS changed player name formatting
- A player changed their legal name (add to `NAME_OVERRIDES`)

After success, commit:
```powershell
git add docs/data.json
git commit -m "Update position eligibility for 2027"
git push
```

---

## Step 8: Verify the Web App

1. Open **https://jcubb.github.io/fantasy-bb/** in a browser
   (wait a minute after pushing for GitHub Pages to deploy)
2. Check these things:
   - **Batters tab**: depth chart grid shows players for all 15 AL teams
   - **Pitchers tab**: SP and RP columns populated
   - **Player tab**: search for a well-known player (e.g., Aaron Judge) —
     should show rank, salary, projected stats, and position eligibility
   - **Injuries tab**: should list players with injury notes (if any exist
     this early in the season)
   - **Last Week tab**: should show recent MLB.com headlines

3. If something is missing or broken, check `docs/data.json` directly —
   it should have all six top-level keys:
   ```
   scraped_at, depth_chart, rankings, news, news_scraped_at,
   projections, salaries, eligibility
   ```

---

## Step 9: Clear Old Draft State (On Draft Day)

The web app stores draft state in your browser's localStorage. Old state from
the previous year's draft will still be there.

1. Open the app in your browser
2. Click the **Reset Draft** button in the header bar
3. Confirm the reset when prompted
4. Go to the **Draft Setup** tab and re-enter your league member names
   (one per line in the textarea)

---

## Step 10: (After the Draft) Record Draft Results

After the auction draft is complete, save the results so they can be imported
next year or reviewed later.

1. Click **Save Draft** in the app header — this downloads a JSON snapshot
2. Optionally, create a `draft_results_2027.txt` file with the raw auction
   results (same format as `draft_results_2026.txt`: team name header, then
   `Pos	Player info	Salary	Rank	Overall Rank` per player)
3. Optionally, create a `draft_import_2027.json` and `import_draft_2027.js`
   for archival — these aren't needed until you want to re-import the draft

---

## Quick Reference: File Checklist

Before the draft, verify these files are present and up-to-date:

| File | Status |
|------|--------|
| `docs/data.json` | Must have all 6 data sections |
| `batters_YYYY-MM-DD.txt` | At least one snapshot from `scrape_projections.py` |
| `pitchers_YYYY-MM-DD.txt` | Matching pitcher snapshot |
| `salproj.txt` | Updated this year (from CBS, if available) |
| `People.csv` | Fresh download (not in git) |
| `Fielding.csv` | Fresh download (not in git) |

---

## Troubleshooting

### Scraper returns 0 teams or 0 rankings
CBS Sports changes their HTML layout periodically. Open the URL in a browser,
inspect the page structure, and update the CSS selectors in `scrape.py`.

### CBS league URL doesn't work
The league URL (`pochicago.baseball.cbssports.com`) may change if the league
is renamed or restructured. Log in to CBS Sports and navigate to your league's
stats page to find the current URL. Update the comment in `parse_projections.py`
and the instructions in `CLAUDE.md`.

### Lahman download link is broken
Search for "Lahman Baseball Database" — the dataset is hosted by SABR and is
widely mirrored. You need the CSV version (not the SQL version). The two files
you need are `People.csv` and `Fielding.csv`.

### build_eligibility.py shows many "secondary" matches
This means the player wasn't found in the 2025/2026 Fielding.csv data but was
found in People.csv. This is normal for pitchers (who appear in Pitching.csv,
not Fielding.csv) and for newly called-up players. They get DH-only eligibility
unless they appear in the fielding data.

### The web app shows stale data after pushing
GitHub Pages can take 1–5 minutes to deploy. Hard-refresh the page (Ctrl+Shift+R)
to bypass the browser cache.

### A player's name doesn't match between systems
Add the player to `NAME_OVERRIDES` in `build_eligibility.py`. The key is the
CBS name (exactly as it appears in the depth chart or rankings), and the value
is the Lahman `playerID` (find it in `People.csv`). Example:
```python
'Joshua Lowe': 'lowejo01',   # CBS says "Joshua", Lahman says "Josh"
```

---

## Timeline Suggestion

| When | What to do |
|------|-----------|
| **January–February** | Download fresh Lahman CSVs (once 2026 season data is available) |
| **2–3 weeks before draft** | Run the scraper; copy CBS projections + salaries; run all three scripts |
| **1 week before draft** | Run the scraper again for fresh depth charts and news |
| **Draft day morning** | Run the scraper one final time; reset old draft state; verify the app |
| **During the draft** | Use the "Run Scraper" button in the app header to trigger a GitHub Actions scrape if needed |
| **After the draft** | Save the draft snapshot; optionally record results to text file |
