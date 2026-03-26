#!/usr/bin/env python
"""
scrape_projections.py — One-time CBS projected stats scraper.

URL: https://pochicago.baseball.cbssports.com/stats/stats-main
Settings: Projections | Timeframe = Rest of Season | Categories = Standard
Runs twice: All Players - Batters, then All Players - P

Merges results into docs/data.json under a "projections" key.

Usage: python scrape_projections.py
Note: Opens a real browser window. Follow the prompts.
"""

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page

STATS_URL = 'https://pochicago.baseball.cbssports.com/stats/stats-main'
DOCS_DIR  = Path(__file__).parent / 'docs'
OUT_FILE  = DOCS_DIR / 'data.json'


# ── Debug helper ───────────────────────────────────────────────────────────

async def dump_selects(page: Page):
    selects = await page.query_selector_all('select')
    print(f'    [{len(selects)} <select> elements]')
    for sel in selects:
        name = (await sel.get_attribute('name') or
                await sel.get_attribute('id') or '?')
        options = await sel.query_selector_all('option')
        labels  = [(await o.text_content() or '').strip() for o in options[:10]]
        sel_val = await sel.evaluate('el => el.value')
        print(f'      name={name!r} value={sel_val!r}: {labels}{"..." if len(options)>10 else ""}')


# ── Select helpers ─────────────────────────────────────────────────────────

async def select_by_partial_label(sel_el, text: str) -> str | None:
    """Select the first option whose label contains `text` (case-insensitive)."""
    options = await sel_el.query_selector_all('option')
    for opt in options:
        label = (await opt.text_content() or '').strip()
        if text.lower() in label.lower():
            val = await opt.get_attribute('value') or label
            await sel_el.select_option(value=val)
            return label
    return None


async def set_select(page: Page, selectors: list[str], text: str) -> str | None:
    """Try each CSS selector; on first match attempt to pick option by label."""
    for sel in selectors:
        try:
            for el in await page.query_selector_all(sel):
                result = await select_by_partial_label(el, text)
                if result:
                    return result
        except Exception:
            pass
    return None


async def click_text(page: Page, text: str) -> bool:
    for sel in [
        f'a:has-text("{text}")',
        f'button:has-text("{text}")',
        f'input[type="submit"][value*="{text}"]',
        f'input[type="button"][value*="{text}"]',
        f'[class*="tab"]:has-text("{text}")',
        f'li:has-text("{text}") > a',
        f'li > a:has-text("{text}")',
    ]:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                return True
        except Exception:
            pass
    return False


# ── Table scraper ──────────────────────────────────────────────────────────

async def scrape_table(page: Page) -> tuple[list[str], list[dict]]:
    """Extract headers and rows from the stats table on the current page."""
    await page.wait_for_timeout(800)

    table = None
    for sel in ['.TableBase table', 'table.data', '#stats-table',
                'table[class*="stats"]', 'table']:
        table = await page.query_selector(sel)
        if table:
            break
    if not table:
        return [], []

    # Headers
    headers: list[str] = []
    for h_sel in ['thead th', 'thead td']:
        cells = await table.query_selector_all(h_sel)
        if cells:
            headers = [(await c.text_content() or '').strip() for c in cells]
            if any(h for h in headers):
                break
    if not headers:
        rows_el = await table.query_selector_all('tr')
        if rows_el:
            cells = await rows_el[0].query_selector_all('td, th')
            headers = [(await c.text_content() or '').strip() for c in cells]

    # Rows
    rows: list[dict] = []
    row_els = await table.query_selector_all('tbody tr')
    if not row_els:
        all_rows = await table.query_selector_all('tr')
        row_els = all_rows[1:]

    for row_el in row_els:
        cells = await row_el.query_selector_all('td')
        if len(cells) < 2:
            continue

        # Player name — prefer link
        name = ''
        for name_sel in [
            'a[href*="/players/"]', 'a[href*="/player/"]',
            '.CellPlayerName a', '[class*="player-name"] a',
            '[class*="playerName"] a',
        ]:
            el = await row_el.query_selector(name_sel)
            if el:
                name = (await el.text_content() or '').strip()
                if name:
                    break

        if not name:
            for idx in (1, 0):
                if idx < len(cells):
                    candidate = (await cells[idx].text_content() or '').strip()
                    candidate = re.sub(r'^\d+\.?\s*', '', candidate).strip()
                    if candidate and not candidate.isdigit() and candidate not in ('-', '—'):
                        name = candidate
                        break

        if not name:
            continue

        row_data = {'name': name}
        for i, hdr in enumerate(headers):
            if i < len(cells) and hdr:
                row_data[hdr] = (await cells[i].text_content() or '').strip()
        rows.append(row_data)

    return headers, rows


async def scrape_all_pages(page: Page) -> list[dict]:
    """Scrape all paginated pages of the stats table."""
    # Try to set page size to All / large number first
    for size_label in ('All', '500', '250', '100'):
        r = await set_select(page,
            ['select[name*="size" i]', 'select[name*="per" i]',
             'select[name*="page" i]', 'select[id*="size" i]'],
            size_label)
        if r:
            print(f'    Page size set to: {r}')
            await page.wait_for_timeout(1500)
            break

    all_rows: list[dict] = []
    seen:     set[str]   = set()
    page_num = 1

    while True:
        print(f'    Page {page_num}...')
        _, rows = await scrape_table(page)
        if not rows:
            print('    No rows found on this page.')
            break

        added = 0
        for row in rows:
            n = row.get('name', '')
            if n and n not in seen:
                seen.add(n)
                all_rows.append(row)
                added += 1

        print(f'      +{added} new rows (total {len(all_rows)})')
        if added == 0:
            break

        # Pagination
        next_el = None
        for sel in [
            'a[class*="next"]:not([class*="disabled"])',
            'a:has-text("Next"):not([class*="disabled"])',
            'button:has-text("Next"):not(:disabled)',
            '[aria-label="Next page"]',
        ]:
            next_el = await page.query_selector(sel)
            if next_el:
                break

        if not next_el:
            break

        cls = (await next_el.get_attribute('class') or '').lower()
        if 'disabled' in cls or 'inactive' in cls:
            break

        await next_el.click()
        await page.wait_for_timeout(2000)
        page_num += 1
        if page_num > 30:
            break

    return all_rows


# ── Auto-filter attempt ────────────────────────────────────────────────────

async def try_auto_filters(page: Page, player_type: str) -> bool:
    """
    Try to navigate to the Projections section and set filters automatically.
    Returns True if we think it worked (table found with >1 row).
    """
    print('  Attempting auto-filter...')

    # Step 1: Click "Projections" tab/link if not already there
    clicked = await click_text(page, 'Projections')
    if clicked:
        print('    Clicked "Projections" tab')
        await page.wait_for_timeout(2000)
    else:
        # Try URL fragments
        for path in ['/stats/stats-main/projections/', '/stats/projections/']:
            try:
                base = '/'.join(STATS_URL.split('/')[:3])
                await page.goto(base + path, wait_until='domcontentloaded', timeout=20000)
                await page.wait_for_timeout(1500)
                break
            except Exception:
                pass

    await dump_selects(page)

    # Step 2: Set Timeframe = Rest of Season
    r = await set_select(page,
        ['select[name="timeframe"]', 'select[name="pulldown"]',
         'select[id*="time" i]', 'select[id*="period" i]'],
        'Rest of Season')
    print(f'    Timeframe: {r or "not set"}')
    if r:
        await page.wait_for_timeout(500)

    # Step 3: Categories = Standard
    r = await set_select(page,
        ['select[name="pulldown"]', 'select[id*="cat" i]',
         'select[id*="group" i]'],
        'Standard')
    print(f'    Categories: {r or "not set"}')
    if r:
        await page.wait_for_timeout(500)

    # Step 4: Player type (Batters / P)
    for text in (f'All Players - {player_type}', player_type, 'Batters' if player_type == 'Batters' else 'Pitchers'):
        r = await set_select(page,
            ['select[name="pulldown"]', 'select[name*="split" i]',
             'select[name*="player" i]', 'select[id*="split" i]'],
            text)
        if r:
            break
    print(f'    Player type: {r or "not set"}')
    if r:
        await page.wait_for_timeout(500)

    # Step 5: Submit / Go
    for text in ('Go', 'Apply', 'Submit', 'Search'):
        if await click_text(page, text):
            print(f'    Submitted via "{text}"')
            await page.wait_for_timeout(2500)
            break

    # Check if we got a real stats table
    _, rows = await scrape_table(page)
    return len(rows) > 1


# ── Manual fallback ────────────────────────────────────────────────────────

def manual_prompt(player_type_label: str) -> None:
    """Block until user signals they've set up the page."""
    print()
    print('=' * 60)
    print(f'MANUAL SETUP NEEDED — {player_type_label}')
    print('=' * 60)
    print('In the browser window:')
    print('  1. Click "Projections" (in the navigation)')
    print('  2. Set Timeframe  = Rest of Season')
    print('  3. Set Categories = Standard')
    print(f'  4. Set player filter = All Players - {player_type_label}')
    print('  5. Click Go / Apply / Submit')
    print('  6. Wait for the stats table to appear')
    print()
    input('>>> Press Enter here once the stats table is visible... ')
    print()


# ── Conversion ─────────────────────────────────────────────────────────────

def rows_to_projections(rows: list[dict]) -> dict:
    skip = {'rank', '#', 'rk', 'no.', 'player', 'name',
            'team', 'tm', 'pos', 'position', ''}
    result = {}
    for row in rows:
        name = row.get('name', '').strip()
        if not name:
            continue
        stats = {k: v for k, v in row.items()
                 if k.lower().strip() not in skip
                 and k != 'name'
                 and v not in ('', '-', '—')}
        result[name] = stats
    return result


# ── Main ────────────────────────────────────────────────────────────────────

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=120)
        ctx = await browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            )
        )
        page = await ctx.new_page()

        # ── Navigate & login ───────────────────────────────────────────────
        print(f'\nNavigating to {STATS_URL}')
        await page.goto(STATS_URL, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(2000)

        if any(x in page.url.lower() for x in ('login', 'signin', 'auth')):
            print('\n*** Please log in in the browser window. ***')
            print('    Waiting up to 3 minutes...')
            try:
                await page.wait_for_url('**/stats**', timeout=180000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)

        # ── BATTERS ────────────────────────────────────────────────────────
        print('\n[1/2] BATTERS')
        success = await try_auto_filters(page, 'Batters')
        if not success:
            manual_prompt('Batters')

        batter_rows = await scrape_all_pages(page)
        print(f'  Batter rows scraped: {len(batter_rows)}')

        if not batter_rows:
            print('  WARNING: No batter rows found. Check the browser and re-run if needed.')

        # ── PITCHERS ───────────────────────────────────────────────────────
        print('\n[2/2] PITCHERS')
        print(f'  Navigating back to {STATS_URL}')
        await page.goto(STATS_URL, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(2000)

        success = await try_auto_filters(page, 'P')
        if not success:
            manual_prompt('Pitchers (P)')

        pitcher_rows = await scrape_all_pages(page)
        print(f'  Pitcher rows scraped: {len(pitcher_rows)}')

        if not pitcher_rows:
            print('  WARNING: No pitcher rows found.')

        await browser.close()

    # ── Save ───────────────────────────────────────────────────────────────
    batters_proj  = rows_to_projections(batter_rows)
    pitchers_proj = rows_to_projections(pitcher_rows)

    print(f'\nProjections: {len(batters_proj)} batters, {len(pitchers_proj)} pitchers')

    if batters_proj:
        sample = next(iter(batters_proj))
        print(f'  Sample batter  — {sample}: {batters_proj[sample]}')
    if pitchers_proj:
        sample = next(iter(pitchers_proj))
        print(f'  Sample pitcher — {sample}: {pitchers_proj[sample]}')

    existing = {}
    if OUT_FILE.exists():
        existing = json.loads(OUT_FILE.read_text(encoding='utf-8'))

    existing['projections'] = {
        'batters':  batters_proj,
        'pitchers': pitchers_proj,
    }

    OUT_FILE.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    print(f'\nSaved -> {OUT_FILE}')
    print('Next: git add docs/data.json && git commit -m "Add projections" && git push')


if __name__ == '__main__':
    asyncio.run(main())
