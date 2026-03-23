#!/usr/bin/env python
"""
scrape.py  —  CBS Sports AL depth chart + rankings scraper.
Outputs docs/data.json for the GitHub Pages draft tool.

Page structure (discovered):
  - Each position has its own URL: /fantasy/baseball/depth-chart/{POS}/
  - Table: teams are COLUMNS, depth levels are ROWS
  - First 2 rows = starter + backup
  - RP page first player per team = closer candidate

Usage: python scrape.py
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL  = 'https://www.cbssports.com'
DOCS_DIR  = Path(__file__).parent / 'docs'
OUT_FILE  = DOCS_DIR / 'data.json'

AL_TEAMS = {
    'ATH': 'Oakland Athletics',    # now Sacramento but CBS may still use ATH/OAK
    'OAK': 'Oakland Athletics',
    'BAL': 'Baltimore Orioles',
    'BOS': 'Boston Red Sox',
    'CHW': 'Chicago White Sox',
    'CWS': 'Chicago White Sox',
    'CLE': 'Cleveland Guardians',
    'DET': 'Detroit Tigers',
    'HOU': 'Houston Astros',
    'KC':  'Kansas City Royals',
    'KCR': 'Kansas City Royals',
    'LAA': 'Los Angeles Angels',
    'MIN': 'Minnesota Twins',
    'NYY': 'New York Yankees',
    'SEA': 'Seattle Mariners',
    'TB':  'Tampa Bay Rays',
    'TBR': 'Tampa Bay Rays',
    'TEX': 'Texas Rangers',
    'TOR': 'Toronto Blue Jays',
}

# Canonical abbreviations (normalise CBS variants)
CANONICAL = {
    'ATH': 'OAK', 'KCR': 'KC', 'CWS': 'CWS', 'CHW': 'CWS',
    'TBR': 'TB',
}

# Positions to scrape and their CBS URL slugs
POSITION_URLS = {
    'C':  '/fantasy/baseball/depth-chart/C/',
    '1B': '/fantasy/baseball/depth-chart/1B/',
    '2B': '/fantasy/baseball/depth-chart/2B/',
    '3B': '/fantasy/baseball/depth-chart/3B/',
    'SS': '/fantasy/baseball/depth-chart/SS/',
    'LF': '/fantasy/baseball/depth-chart/LF/',
    'CF': '/fantasy/baseball/depth-chart/CF/',
    'RF': '/fantasy/baseball/depth-chart/RF/',
    'DH': '/fantasy/baseball/depth-chart/DH/',
    'SP': '/fantasy/baseball/depth-chart/SP/',
    'RP': '/fantasy/baseball/depth-chart/RP/',   # first player = CL
}

RANKINGS_URL = 'https://www.cbssports.com/fantasy/baseball/rankings/roto/top300/AL/'


def norm(abbr: str) -> str:
    """Normalise CBS team abbreviation to our canonical key."""
    return CANONICAL.get(abbr, abbr)


def is_al(abbr: str) -> bool:
    return abbr in AL_TEAMS or norm(abbr) in AL_TEAMS


def norm_name(name: str) -> str:
    """Normalize a player name for fuzzy matching: lowercase, strip punctuation."""
    return re.sub(r"[^a-z0-9 ]", '', name.lower()).strip()


def reconcile_rankings(rankings: dict, depth_chart: dict) -> dict:
    """
    Re-key rankings dict so names match canonical depth chart names.
    Uses normalized (lowercase, no punctuation) matching.
    """
    # Build canonical name lookup from depth chart
    canonical: dict[str, str] = {}  # norm_name -> canonical
    for positions in depth_chart.values():
        for players in positions.values():
            for p in players:
                canonical[norm_name(p['name'])] = p['name']

    reconciled = {}
    for name, info in rankings.items():
        key = canonical.get(norm_name(name), name)
        reconciled[key] = info
    return reconciled


# ── Per-position scraper ──────────────────────────────────────────────────────

async def get_player_from_cell(cell) -> dict | None:
    """Extract player name and injury note from a depth-chart table cell."""
    name_el = await cell.query_selector('.CellPlayerName--long a')
    if not name_el:
        name_el = await cell.query_selector('.CellPlayerName--short a')
    if not name_el:
        name_el = await cell.query_selector('a[href*="/players/"]')
    if not name_el:
        return None
    name = (await name_el.text_content() or '').strip()
    if not name or name in ('-', '—'):
        return None

    injury = None
    for sel in ('.CellPlayerName-icon', '[class*="injury"]',
                '[class*="status"]', '[class*="il"]', 'abbr'):
        inj_el = await cell.query_selector(sel)
        if inj_el:
            title = await inj_el.get_attribute('title') or ''
            txt = (await inj_el.text_content() or '').strip()
            note = title or txt
            if note and len(note) < 60:
                injury = note
                break
    return {'name': name, 'injury': injury}


async def scrape_position(page, pos: str, url_path: str) -> dict:
    """
    Scrape one position page.
    Table structure: ROWS = teams, COLS = [Team | Starter | Backup | Reserves]
    AL and NL are separate tables; we identify AL by .TableBase-title text.
    Returns {team_abbr: [{'name':..., 'injury':...}, ...]}  (up to 2 players)
    """
    url = BASE_URL + url_path
    try:
        await page.goto(url, wait_until='load', timeout=45000)
    except Exception as e:
        print(f'    Warning: {e}')

    await page.wait_for_timeout(3000)

    # ── Find the American League table ────────────────────────────────────────
    al_table = None
    for wrapper in await page.query_selector_all(
        '.TableBaseWrapper, [class*="TableBase"], [id*="TableBase"]'
    ):
        title_el = await wrapper.query_selector(
            '.TableBase-title, [class*="TableBase-title"], h4, caption'
        )
        if title_el:
            title_txt = (await title_el.text_content() or '').strip()
            if 'American' in title_txt:
                al_table = await wrapper.query_selector('table')
                break

    # Fallback: first table on page (position pages may have only one table)
    if al_table is None:
        al_table = await page.query_selector('table')

    if al_table is None:
        print(f'    [{pos}] No table found')
        return {}

    # ── Iterate rows: each row = one team ─────────────────────────────────────
    result = {}
    rows = await al_table.query_selector_all('tbody tr')
    print(f'    [{pos}] {len(rows)} rows in AL table')

    for row in rows:
        cells = await row.query_selector_all('td')
        if len(cells) < 2:
            continue

        # Cell 0: team identity
        team_link = await cells[0].query_selector('a[href*="/mlb/teams/"]')
        if not team_link:
            continue
        href = await team_link.get_attribute('href') or ''
        m = re.search(r'/mlb/teams/([A-Z]+)/', href)
        if not m:
            continue
        team = norm(m.group(1))
        if not is_al(team):
            continue

        # Cells 1 = Starter, 2 = Backup
        players = []
        for cell in cells[1:3]:
            p = await get_player_from_cell(cell)
            if p:
                players.append(p)

        if players:
            result[team] = players

    return result


# ── Rankings ──────────────────────────────────────────────────────────────────

async def scrape_rankings(page) -> dict:
    """
    Scrape CBS AL roto top-300 rankings.
    Returns: {player_name: {'rank': int, 'team': str, 'pos': str}}
    """
    print('  Loading rankings page...')
    try:
        await page.goto(RANKINGS_URL, wait_until='load', timeout=45000)
    except Exception as e:
        print(f'  Warning: {e}')

    await page.wait_for_timeout(3000)

    rankings = {}

    # Page renders 4 identical copies of the 300-player list (1200 rows total).
    # Deduplicate by CBS player ID extracted from the href.
    rows = await page.query_selector_all('[class*="player-row"]')
    if not rows:
        print('  No player-row elements found')
        return {}

    seen_ids = set()
    for row in rows:
        try:
            rank_el = await row.query_selector('.rank')
            if not rank_el:
                continue
            rank_raw = re.sub(r'\D', '', (await rank_el.text_content() or '').strip())
            if not rank_raw:
                continue
            rank = int(rank_raw)

            # Full name from href slug: /mlb/players/2071264/aaron-judge/fantasy/
            a_el = await row.query_selector('a[href*="/mlb/players/"]')
            if not a_el:
                continue
            href = await a_el.get_attribute('href') or ''
            m = re.search(r'/mlb/players/(\d+)/([^/]+)/', href)
            if not m:
                continue
            player_id = m.group(1)
            if player_id in seen_ids:
                continue
            seen_ids.add(player_id)

            # Convert slug to title-case name: aaron-judge -> Aaron Judge
            name = ' '.join(p.capitalize() for p in m.group(2).split('-'))

            # Position from .team span (first word, e.g. "RF\n$46" -> "RF")
            tp_el = await row.query_selector('.team')
            pos = ''
            if tp_el:
                tp_txt = (await tp_el.text_content() or '').strip().split()[0].upper()
                if tp_txt in ('C','1B','2B','3B','SS','OF','LF','CF','RF',
                              'DH','SP','RP','CL','P'):
                    pos = tp_txt

            rankings[name] = {'rank': rank, 'pos': pos}

        except (ValueError, TypeError):
            continue

    print(f'  Found {len(rankings)} ranked players')
    return rankings


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    DOCS_DIR.mkdir(exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            )
        )
        page = await ctx.new_page()

        # ── Depth charts ──────────────────────────────────────────────────────
        print('\n[1/2] Depth charts')
        # depth_chart: {team: {pos: [players]}}
        depth_chart = {abbr: {} for abbr in set(CANONICAL.values()) | set(AL_TEAMS.keys())
                       if abbr not in CANONICAL}
        # Simpler: build from scratch
        depth_chart = {}

        for pos, url_path in POSITION_URLS.items():
            print(f'  Scraping {pos}...')
            pos_data = await scrape_position(page, pos, url_path)

            for team, players in pos_data.items():
                if team not in depth_chart:
                    depth_chart[team] = {}

                if pos == 'RP' and players:
                    # First reliever = closer
                    depth_chart[team]['CL'] = [players[0]]
                    if len(players) > 1:
                        depth_chart[team]['RP'] = [players[1]]
                else:
                    depth_chart[team][pos] = players

        # Filter to AL only and remove empty teams
        al_keys = {norm(k) for k in AL_TEAMS}
        depth_chart = {t: v for t, v in depth_chart.items()
                       if t in al_keys and v}

        print(f'  AL teams with data: {sorted(depth_chart.keys())}')

        # ── Rankings ──────────────────────────────────────────────────────────
        print('\n[2/2] Rankings')
        rankings = await scrape_rankings(page)

        await browser.close()

    if not depth_chart and not rankings:
        print('\nNothing scraped — data.json NOT overwritten. Check debug_*.html files.')
        return

    # Reconcile rankings names to canonical depth chart names
    if depth_chart and rankings:
        rankings = reconcile_rankings(rankings, depth_chart)

    output = {
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'depth_chart': depth_chart,
        'rankings': rankings,
    }

    OUT_FILE.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(f'\nSaved {len(depth_chart)} AL teams, {len(rankings)} ranked players -> {OUT_FILE}')


if __name__ == '__main__':
    asyncio.run(main())
