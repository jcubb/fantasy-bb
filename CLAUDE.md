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
    "batters":  {"Aaron Judge": {"_team": "NYY", "_pos": "OF", "AB": "522", "HR": "50", ...}, ...},
    "pitchers": {"Tarik Skubal": {"_team": "DET", "_pos": "P", "INNs": "191", "ERA": "2.83", ...}, ...}
  },
  "salaries": {
    "Aaron Judge": "$46",
    "Tarik Skubal": "$39",
    ...
  },
  "eligibility": {
    "positions_2025": {"Aaron Judge": ["OF", "DH"], "Jose Ramirez": ["3B", "DH"], ...},
    "games_2025":     {"Aaron Judge": {"OF": 140}, ...},
    "games_2024":     {"Aaron Judge": {"OF": 130}, ...}
  }
}
```

### Web App (`docs/index.html`)

**Tab order:** Read Me | Player | League | Batters | Pitchers | Drafted | Injuries | Last Week | My Team | Draft Setup | Notes

**Read Me tab** — static documentation page (no JS needed):
- Usage guide covering all features, keyboard shortcuts, and the roster panel
- Data sources section: depth charts, rankings, projections, eligibility, injury notes
- Warnings callout: eligibility is approximate (Lahman, not official CBS), projections may be stale, scraper fragility, name-matching edge cases, no independent data validation
- Draft state localStorage note (local to each browser, not shared)

**Player tab** — combined batter + pitcher search and position-pool view:
- **Top table (Available Players)**: all players (batters and pitchers) filtered by the search box; columns: Rank, Starting, Name, Team, Pos, Eligible, Sal, batter stats (AVG/HR/RBI/SB/R), pitcher stats (ERA/W/S/WHIP/K)
- **Bottom table (Remaining Available — POS (N))**: all non-drafted players at the union of positions of the matched players; same columns minus Eligible; title updates dynamically with position group(s) and count
- OF is grouped (LF/CF/RF all → OF) for the position pool; SP/CL/RP stay separate
- Search box is synced bidirectionally with the Batters/Pitchers tab search box — switching tabs carries the value over
- Typical use: type enough of a name to uniquely identify a player being bid on; top table shows that player, bottom table shows the full remaining pool at their position(s)

**League tab** — grid of roster cards for every league team (one card per member defined in Draft Setup):
- Cards laid out in a wrapping flex grid; each card is 330px wide
- Card header: team name + filled slots count (e.g. `21/23`) + `$spent` + `$left` remaining vs $260 budget
- Card body: two columns — Batters (14 slots) on left, Pitchers (9 slots) on right
  - Each slot row: slot label + player last name + draft price in green; empty slots shown as `—`
  - For pitcher slots, the label shows the player's actual position (`SP` or `RP`) instead of the slot type
  - Pitchers sorted SP first, then RP within each card
- Unassigned section at card bottom (orange pills) for any players who couldn't be fit into a slot
- Display order: league members list first (even if empty/undrafted), then any extra teams found in `draftedBy`, then a `— No Drafter —` card for players with no team assigned
- Summary line above grid: `N teams · M players drafted`

**League tab — auto-assignment logic (`autoAssignRoster`):**
- Bipartite matching via augmenting-path DFS (same algorithm as `fantasy_bb.py`)
- Players processed most-constrained first (fewest eligible slots) for better slot coverage
- `playerSlotElig(name)` maps each player to eligible ROSTER_SLOT IDs:
  - Pitchers: eligible for all 9 pitcher slots (type = 'p') regardless of SP/RP/CL distinction
  - Batters: uses union of `positions_2025` eligibility AND the player's natural position from rankings/projections (so a player like Murakami listed at 1B but with only DH calculated eligibility is still placed at 1B)
  - LF/CF/RF normalized to OF for slot matching
- `pitcherDisplayPos(name)`: uses `DATA.rankings[name].pos` as the source for SP vs RP display (projections `_pos` is always the generic `'P'` for all pitchers and cannot be used)
- `getPitcherPos(name)`: determines whether a player is a pitcher at all (for matching); checks projections → rankings → depth chart; treats `'P'` and `'SP'` both as pitcher

**League tab — next planned features:**
- Supply/demand view: for a given position, how many teams have open slots + budget to spend vs. how many undrafted quality players remain

**Batters tab** — columns: C, 1B, 2B, 3B, SS, LF, CF, RF, DH
- Each cell: starter (bold) + 1 backup (gray/small)
- **Search highlight**: as the user types in the ranked-list search box, matching players in the depth chart grid get a yellow highlight — starters and backups both highlighted

**Pitchers tab** — 9 columns: SP1, SP2, SP3, SP4, SP5, CL1, CL2, SU1, SU2
- Each cell: one player; `PITCHER_COL_MAP` maps column name to `[data_key, index]`

**Features (Batters/Pitchers tabs):**
- Checkbox per player → marks as drafted + opens Assign modal to place on roster
- Unchecking a checkbox → undrafts and removes from roster
- Injury `!` flag in grid — only shown for real injuries (keyword-matched); all notes still appear in hover tooltip
- Tooltip shows CBS AL rank, projection stats, eligibility, and injury note
- "Hide drafted" toggle for the grid
- Ranked list below grid: filtered to current tab (batters on Batters tab, pitchers on Pitchers tab), with search, position filter, and hide-drafted toggle
- Position filter rebuilds on tab switch (only shows relevant positions)
- Batter ranked list columns: Rank, Starting, Name, Team, Pos, Eligible (with 2025 games count), Sal, AVG, HR, RBI, SB, R, Injury
- Pitcher ranked list columns: Rank, Starting, Name, Team, Pos, Sal, ERA, W, S, WHIP, K, Injury
- **Starting column**: bold green "Yes" if the player appears anywhere in the depth chart; gray "No" if ranking/projection-only
- **Sal column**: AL-only salary projection from `data.json` salaries; shown in green/bold; missing = `—`
- **Team fallback**: if a player is missing from the depth chart (e.g. projection-only), team and pos are filled from `_team`/`_pos` fields stored in the projections entry
- **Click-to-sort**: all columns in the ranked list are sortable by clicking the header; active column shows ▲/▼ arrow; sort resets to Rank on tab switch; missing values always sort to the end

**Drafted tab** — log of all drafted players across the whole league:
- Sorted newest-first (most recently drafted at the top)
- Columns: Rank, Starting, Name, Team, Pos, Eligible, Draft $, Sal, batter stats, pitcher stats, Time, Drafter
- **Name** is a clickable link — opens the Assign modal pre-filled with existing price and drafter for editing
- **Draft $**: auction price paid (entered via Assign modal); plain text display
- **Drafter**: league team that drafted them (entered via Assign modal); plain text display
- **Time**: time of day the player was marked as drafted (HH:MM AM/PM), formatted by `fmtDraftTime()`
- To undraft a player, uncheck them in the Batters/Pitchers/Player tab

**Injuries tab**: lists all players with real injury notes, sorted by CBS rank; shows likely replacement (first healthy player at same position, with MI/CI/OF/CL overlaps)

**Last Week tab**: MLB.com news from the past 7 days, organized by team; only player-relevant headlines (blocklist filters out TV/streaming/tickets/nostalgia/odds); deduplicated by normalized headline; shows "as of" timestamp

**Draft Setup tab** — league configuration and one-time data imports:
- **League members textarea**: one name per line; persists to `localStorage` (`ff_league_members`); used to populate the Drafter dropdown in the Assign modal and Drafted tab
- **Import Draft Prices / Teams button**: reads a JSON file (format below) and *merges* prices, team assignments, and drafted status into existing state without touching roster, notes, or sal_paid for already-set players
  - `importDraftPrices()` — merges `drafted`, `draft_price`, `drafted_by`; pre-fills `sal_paid` only where not already set
  - Import file format: `{ "drafted": [...], "draft_price": {"Name": price}, "drafted_by": {"Name": "Team"} }`
  - `docs/draft_import_2026.json`: pre-built import file for the 2026 draft (230 players, 10 teams), generated from `draft_results_2026.txt` via Python

**Notes tab** — free-text scratch pad for draft-day notes:
- Single `<textarea>` that auto-saves to `localStorage` (`ff_notes` key) on every keystroke
- Persists across page refreshes; **Clear** button with confirmation prompt
- Notes are browser-local (not shared)

**My Team tab** — projects drafted players' stats against a weighted pool of AL starters:
- Two tables: Batting (HR, RBI, BA, SB, R) and Pitching (W, S, ERA, WHIP, K)
- Columns: Stat | My Team | Avg | Q1 | Median | Q3 | Drafted Avg | Undrafted Avg | %ile All | %ile Dft | %ile Und
- **My Team** = per-player average of all drafted players with projection data
  - BA: H/AB-weighted; ERA/WHIP: innings-weighted; all others: simple average
- **Pool**: weighted sample of AL starters from the depth chart
  - Batter weights (sum = 14): C×2, 1B/2B/3B/SS×1.5 each (absorbs MI/CI half-shares), LF/CF/RF×5/3, DH×1
  - Pitcher weights (sum = 9): all equal (SP1–5 + CL1–2 + SU1–2, weight 1/15 each)
  - Only players with projection data are included in the pool
- **Q1/Q3 orientation**: Q1 = better-end threshold, Q3 = worse-end, for ALL stats
  - For HR/RBI/etc (higher = better): Q1 value > Q3 value (Q1 is the 75th-percentile threshold)
  - For ERA/WHIP (lower = better): Q1 value < Q3 value (Q1 is the 25th-percentile threshold, i.e. the best ERA)
  - Internally `wStats()` always returns natural order (q1=25th, q3=75th); display swaps Q1↔Q3 for `hb:true` stats
- **Percentile columns** (%ile All/Dft/Und): where My Team's value ranks in each population; lower = better (1 = best); computed via `wPercentile()` — for `hb:true` returns `100*(1-CDF)`, for `hb:false` returns `100*CDF`
- **Color coding on My Team cell**: green = above Q1 (top quartile), light green = Q1–Median, orange = Median–Q3, red = below Q3
- Drafted/Undrafted columns use same pool filtered to `x.drafted` flag (set at pool-build time)
- Counting stats display as whole numbers; BA to 3dp; ERA/WHIP to 2dp

**Other header controls:**
- **Run Scraper** button → opens GitHub Actions page to trigger a fresh scrape
- **Save Draft** button → downloads `fantasy-bb-draft-YYYY-MM-DD.json` snapshot of all draft state
- **Load Draft** button → file picker; shows save timestamp and confirmation before restoring; fully replaces current draft state in memory and localStorage
- **Reset Draft** button → clears all drafted marks, roster assignments, salaries paid, draft prices, timestamps, and drafter assignments

**Draft snapshot format** (`fantasy-bb-draft-YYYY-MM-DD.json`):
```json
{
  "saved_at":    "2026-03-29T...",
  "drafted":     ["Aaron Judge", ...],
  "roster":      { "slots": {"C1": "Austin Wells", ...}, "unassigned": [...] },
  "sal_paid":    {"Aaron Judge": 46, ...},
  "draft_price": {"Aaron Judge": 65, ...},
  "draft_times": {"Aaron Judge": "2026-03-29T14:23:00Z", ...},
  "drafted_by":  {"Aaron Judge": "Merda", ...},
  "notes":       "..."
}
```

**Teams displayed** (AL_ORDER): BAL, BOS, NYY, TB, TOR, CWS, CLE, DET, KC, MIN, HOU, LAA, OAK, SEA, TEX

### Roster Panel

Fixed 220px panel on the right side of the screen showing your roster in progress.

**Slots (23 total):**
- Batters: C, C, 1B, 2B, 3B, SS, OF, OF, OF, OF, OF, MI, CI, Util
- Pitchers: SP, SP, SP, SP, SP, CL, CL, SU, SU
- Unassigned section at the bottom for players not yet placed

**Interactions:**
- Click a player name in the panel → opens Assign modal for reassignment
- **Salary input**: each filled slot has a compact number input on the right for entering the actual auction price paid; CBS projected salary shown as placeholder; green text
- **Budget footer**: always visible above the buttons — shows `$X spent` (green) and `$Y left` (gray; red if over budget) plus `($Z/slot)` — average remaining budget per unfilled slot
  - Budget = $260 total; open slot count = `ROSTER_SLOTS.length` minus filled slots (unassigned players don't count as filling a slot)
  - Salary state persisted in `localStorage` (`ff_sal_paid` key): `{playerName: amountPaid}`
  - Salary cleared when player is removed from roster or draft is reset
- **Download Roster** button → exports `fantasy-bb-roster.csv` with columns: Slot, Player, Rank, Pos, AVG, HR, RBI, SB, R, ERA, W, S, WHIP, K; all 23 slots included (empty slots have blank player row); unassigned players appended at bottom
- **Clear Roster** button removes all slot assignments (keeps drafted marks)
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

### Projections + Salaries (`parse_projections.py`)

Parses tab-separated text copied from CBS projected stats pages and salary projections into `data.json`. Also stores `_team` and `_pos` from the player info field so the web app can show team/pos for players not in the AL depth chart.

**Setup:**
1. Go to https://pochicago.baseball.cbssports.com/stats/stats-main
2. Click Projections → set Timeframe = Rest of Season, Categories = Standard
3. Run "All Players - Batters" → select all → copy → paste into `batters2026.txt`
4. Run "All Players - P" → select all → copy → paste into `pitchers2026.txt`
5. Copy CBS salary projections (AL-only column) into `salproj.txt`

**Run:**
```
python parse_projections.py
git add docs/data.json && git commit -m "Add projections" && git push
```

**Row format — projections** (`{action}\t{Name POS • TEAM}\t{stat1}\t...\t{Rank}`):
- Batter columns: AB, R, H, 1B, 2B, 3B, HR, RBI, BB, K, SB, CS, AVG, OBP, SLG, Rank
- Pitcher columns: INNs, APP, GS, QS, CG, W, L, S, BS, HD, K, BB, H, ERA, WHIP, Rank
- Rank is excluded from stored stats (already in CBS rankings)
- `_team` and `_pos` are extracted from the player info field and stored alongside stats

**Row format — salaries** (`salproj.txt`, tab-separated: `Name POS • TEAM\tPos\tTeam\tMixed\tAL-Only`):
- AL-Only column (index 4) stored as string e.g. `"$46"`
- `parse_salaries()` uses the same `PLAYER_RE` regex as projections
- Stored under top-level `salaries` key in `data.json`; ~275 players

**`scrape.py` field ownership:** does NOT touch `projections`, `salaries`, or `eligibility` — those are carried forward from the existing file on each scrape run.

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

- Triggers: `workflow_dispatch` only (manual, via Run Scraper button in the app or Actions page) — daily cron was disabled
- Runs on `ubuntu-latest`: installs Python 3.11, playwright + chromium, runs `scrape.py`
- Commits updated `docs/data.json` with message `Auto-refresh data YYYY-MM-DD HH:MM UTC`
- Does `git pull --rebase` before pushing to avoid race condition when local changes were pushed since the workflow started
- Does NOT run `parse_projections.py` or `build_eligibility.py` — those are one-time local scripts

**⚠ Important — `scrape.py` field ownership:**
`scrape.py` only owns `scraped_at`, `depth_chart`, `rankings`, `news`, `news_scraped_at`. Before writing `data.json` it reads the existing file and carries forward any keys it doesn't own (`projections`, `salaries`, `eligibility`). This prevents the daily auto-scrape from wiping manually-added projection, salary, and eligibility data. If `data.json` doesn't exist yet, those keys are simply omitted.
