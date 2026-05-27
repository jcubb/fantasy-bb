#!/usr/bin/env python
"""
scrape_projections.py — Automated CBS projected stats scraper.

Navigates to the private CBS league stats page using Playwright,
extracts projection tables via clipboard copy, and writes date-stamped
files: batters_YYYY-MM-DD.txt / pitchers_YYYY-MM-DD.txt.

Does NOT write data.json — use load_projections.py to choose a snapshot
and load it into the app.

Login session is cached in .cbs_session.json (gitignored). First run
requires manual login in the browser window; subsequent runs reuse the
saved session until it expires.

Usage: python scrape_projections.py
"""

import asyncio
from datetime import date
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page, BrowserContext

STATS_URL    = 'https://pochicago.baseball.cbssports.com/stats/stats-main'
BASE_DIR     = Path(__file__).parent
SESSION_FILE = BASE_DIR / '.cbs_session.json'

TODAY        = date.today().isoformat()
BATTER_FILE  = BASE_DIR / f'batters_{TODAY}.txt'
PITCHER_FILE = BASE_DIR / f'pitchers_{TODAY}.txt'


# ── Session management ────────────────────────────────────────────────────

async def save_session(ctx: BrowserContext) -> None:
    """Save browser cookies/storage so we can skip login next time."""
    state = await ctx.storage_state()
    SESSION_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    print(f'  Session saved -> {SESSION_FILE.name}')


async def create_context(pw):
    """Create a headed browser context, restoring saved session if available."""
    browser = await pw.chromium.launch(headless=False, slow_mo=100)

    storage_state = None
    if SESSION_FILE.exists():
        try:
            storage_state = json.loads(SESSION_FILE.read_text(encoding='utf-8'))
            print(f'  Restored session from {SESSION_FILE.name}')
        except Exception:
            print(f'  Warning: could not read {SESSION_FILE.name}, starting fresh')

    ctx = await browser.new_context(
        storage_state=storage_state,
        user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0.0.0 Safari/537.36'
        ),
    )
    return browser, ctx


async def ensure_logged_in(page: Page) -> bool:
    """
    Navigate to CBS stats page. If redirected to login, wait for user
    to authenticate in the browser window, then save the session.
    Returns True if we're on the stats page, False on timeout.
    """
    print(f'\nNavigating to {STATS_URL}')
    await page.goto(STATS_URL, wait_until='domcontentloaded', timeout=60000)
    await page.wait_for_timeout(2000)

    if any(x in page.url.lower() for x in ('login', 'signin', 'auth')):
        print()
        print('=' * 60)
        print('  LOGIN REQUIRED')
        print('=' * 60)
        print('  Please log in to CBS Sports in the browser window.')
        print('  Your session will be saved for future runs.')
        print('  Waiting up to 3 minutes...')
        print()
        try:
            await page.wait_for_url('**/stats**', timeout=180000)
        except Exception:
            print('  Timed out waiting for login.')
            return False
        await page.wait_for_timeout(2000)
        await save_session(page.context)
    else:
        print('  Already logged in (session restored)')

    return 'stats' in page.url.lower()


# ── Select / click helpers ────────────────────────────────────────────────

def _normalize_ws(s: str) -> str:
    """Replace non-breaking spaces and collapse whitespace."""
    return re.sub(r'[\s\xa0]+', ' ', s).strip()


async def select_by_partial_label(sel_el, text: str) -> str | None:
    """Select the first <option> whose label contains `text` (case-insensitive)."""
    needle = _normalize_ws(text).lower()
    options = await sel_el.query_selector_all('option')
    for opt in options:
        label = (await opt.text_content() or '').strip()
        if needle in _normalize_ws(label).lower():
            val = await opt.get_attribute('value') or label
            await sel_el.select_option(value=val)
            return label
    return None


async def set_select(page: Page, selectors: list[str], text: str) -> str | None:
    """Try each CSS selector; pick the first option matching text."""
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
    """Click the first interactive element containing text."""
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


async def dump_selects(page: Page):
    """Debug: print all <select> elements and their options."""
    selects = await page.query_selector_all('select')
    print(f'    [{len(selects)} <select> elements]')
    for sel in selects:
        name = (await sel.get_attribute('name') or
                await sel.get_attribute('id') or '?')
        options = await sel.query_selector_all('option')
        labels  = [(await o.text_content() or '').strip() for o in options[:10]]
        sel_val = await sel.evaluate('el => el.value')
        print(f'      name={name!r} value={sel_val!r}: {labels}{"..." if len(options)>10 else ""}')


# ── Filter navigation ─────────────────────────────────────────────────────

async def js_select_by_content(page: Page, option_text: str,
                               must_also_have: str | None = None) -> str | None:
    """
    Find the <select> whose options contain option_text, set its value
    via JS, and fire its onchange handler.

    If must_also_have is provided, only consider <select> elements that
    also contain an option matching that text (used to disambiguate when
    multiple dropdowns share an option label like "Standard").

    CBS dropdowns fail Playwright's visibility checks and use JS form
    submissions (the URL doesn't change), so we manipulate the DOM directly.
    """
    needle = _normalize_ws(option_text).lower()
    also = _normalize_ws(must_also_have).lower() if must_also_have else None
    result = await page.evaluate('''([needle, also]) => {
        const normalize = s => s.replace(/[\\s\\u00a0]+/g, ' ').trim().toLowerCase();
        for (const sel of document.querySelectorAll('select')) {
            if (also) {
                const labels = Array.from(sel.options).map(o => normalize(o.textContent));
                if (!labels.some(l => l.includes(also))) continue;
            }
            for (const opt of sel.options) {
                if (normalize(opt.textContent).includes(needle)) {
                    sel.value = opt.value;
                    var evt = document.createEvent('HTMLEvents');
                    evt.initEvent('change', true, false);
                    sel.dispatchEvent(evt);
                    return opt.textContent.trim();
                }
            }
        }
        return null;
    }''', [needle, also])

    if result:
        await page.wait_for_timeout(3000)
    return _normalize_ws(result) if result else None


async def navigate_to_projections(page: Page, player_type: str) -> bool:
    """
    Navigate the CBS stats page to show projections for the given player type.
    player_type: 'Batter' or 'P' (pitchers).
    Returns True if a data table is found after filtering.
    """
    print(f'  Setting up filters for {player_type}...')

    # Step 1: Click "Projections" tab/link
    clicked = await click_text(page, 'Projections')
    if clicked:
        print('    Clicked "Projections"')
        await page.wait_for_timeout(2500)
    else:
        for path in ['/stats/stats-main/projections/', '/stats/projections/']:
            try:
                base = '/'.join(STATS_URL.split('/')[:3])
                await page.goto(base + path, wait_until='domcontentloaded', timeout=20000)
                await page.wait_for_timeout(2000)
                break
            except Exception:
                pass

    # Step 2: Click the player type sidebar link ("Batter" or "P")
    # These are short sidebar links — need exact text matching to avoid
    # "P" matching every link on the page
    type_clicked = False
    for sel in [
        f'a >> text="{player_type}"',
        f'a:text-is("{player_type}")',
    ]:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.click(timeout=5000)
                type_clicked = True
                break
        except Exception:
            pass

    if not type_clicked:
        type_clicked = await click_text(page, player_type)

    if type_clicked:
        print(f'    Clicked "{player_type}" link')
        await page.wait_for_timeout(2500)
    else:
        print(f'    WARNING: Could not click "{player_type}" link')

    # Step 3: Click "All Players" to ensure we see everyone, not just free agents
    all_clicked = await click_text(page, 'All Players')
    if all_clicked:
        print('    Clicked "All Players"')
        await page.wait_for_timeout(2500)
    else:
        print('    WARNING: Could not click "All Players"')

    print(f'    Current URL: {page.url}')
    await dump_selects(page)

    # Step 4: Set timeframe to "Rest of Season" via the pulldown that has it
    r = await js_select_by_content(page, 'Rest of Season')
    print(f'    Timeframe: {r or "not set"}')
    if r:
        print(f'    URL after timeframe: {page.url}')

    # Step 5: Set categories to "Standard" (the dropdown that also has "Advanced")
    r = await js_select_by_content(page, 'Standard', must_also_have='Advanced')
    print(f'    Categories: {r or "not set"}')

    # Step 6: Click Go / Submit to apply any remaining filters
    for text in ('Go', 'Apply', 'Submit', 'Search'):
        if await click_text(page, text):
            print(f'    Submitted via "{text}"')
            await page.wait_for_timeout(2500)
            break

    # Step 7: Try to show all rows (page size selector)
    # First try the Playwright approach
    page_size_set = False
    for size_label in ('All', '500', '250'):
        r = await set_select(page,
            ['select[name*="size" i]', 'select[name*="per" i]',
             'select[name*="count" i]', 'select[name*="page" i]',
             'select[id*="size" i]'],
            size_label)
        if r:
            print(f'    Page size: {r}')
            await page.wait_for_timeout(2500)
            page_size_set = True
            break

    # Fallback: try JS to find any select with an "All" or large count option
    # (skip numbers > 999 to avoid matching year labels like "2025")
    if not page_size_set:
        r = await page.evaluate('''() => {
            const normalize = s => s.replace(/[\\s\\u00a0]+/g, ' ').trim().toLowerCase();
            for (const sel of document.querySelectorAll('select')) {
                for (const opt of sel.options) {
                    const label = normalize(opt.textContent);
                    const num = parseInt(label);
                    if (label === 'all' || (num >= 200 && num <= 999)) {
                        sel.value = opt.value;
                        var evt = document.createEvent('HTMLEvents');
                        evt.initEvent('change', true, false);
                        sel.dispatchEvent(evt);
                        return opt.textContent.trim();
                    }
                }
            }
            return null;
        }''')
        if r:
            print(f'    Page size (via JS): {r}')
            await page.wait_for_timeout(2500)
            page_size_set = True

    if not page_size_set:
        print('    WARNING: Could not set page size — will use pagination if needed')

    # Verify table exists
    row_count = await page.evaluate('''() => {
        const tables = document.querySelectorAll('table');
        let best = 0;
        for (const t of tables) {
            const rows = t.querySelectorAll('tbody tr');
            if (rows.length > best) best = rows.length;
        }
        return best;
    }''')
    print(f'    Table found with {row_count} rows')
    return row_count > 1


def manual_prompt(player_type_label: str) -> None:
    """Block until user signals they've set up the page manually."""
    print()
    print('=' * 60)
    print(f'  MANUAL SETUP NEEDED -- {player_type_label}')
    print('=' * 60)
    print('  In the browser window:')
    print('    1. Click "Projections"')
    print('    2. Set Timeframe  = Rest of Season')
    print('    3. Set Categories = Standard')
    print(f'    4. Set player filter = All Players - {player_type_label}')
    print('    5. Click Go / Apply / Submit')
    print('    6. Set page size to "All" if available')
    print('    7. Wait for the full stats table to appear')
    print()
    input('  >>> Press Enter here once the stats table is visible... ')
    print()


# ── Table extraction ──────────────────────────────────────────────────────

async def extract_table_text(page: Page) -> str:
    """
    Extract stats table content as tab-separated text, mimicking what
    a user gets when they select-all + copy from the page.

    Tries three strategies in order:
    1. Clipboard: Ctrl+A, Ctrl+C, read clipboard
    2. Selection API: select table contents, read selection.toString()
    3. Cell-by-cell: iterate rows/cells and build TSV manually
    """

    # Strategy 1: Clipboard copy (most faithful to manual copy-paste)
    try:
        # Grant clipboard permission via CDP
        cdp = await page.context.new_cdp_session(page)
        await cdp.send('Browser.grantPermissions', {
            'origin': page.url,
            'permissions': ['clipboardReadWrite', 'clipboardSanitizedWrite'],
        })
    except Exception:
        pass

    try:
        await page.keyboard.press('Control+a')
        await page.wait_for_timeout(200)
        await page.keyboard.press('Control+c')
        await page.wait_for_timeout(500)
        text = await page.evaluate('navigator.clipboard.readText()')
        if text and '\t' in text and len(text) > 200:
            print('    Extracted via clipboard copy')
            return text
    except Exception as e:
        print(f'    Clipboard copy failed ({e.__class__.__name__}), trying selection API...')

    # Strategy 2: Selection API on the table element
    try:
        text = await page.evaluate('''() => {
            const table = document.querySelector('.TableBase table') ||
                          document.querySelector('table.data') ||
                          document.querySelector('table');
            if (!table) return '';
            const sel = window.getSelection();
            sel.removeAllRanges();
            const range = document.createRange();
            range.selectNodeContents(table);
            sel.addRange(range);
            const result = sel.toString();
            sel.removeAllRanges();
            return result;
        }''')
        if text and '\t' in text and len(text) > 200:
            print('    Extracted via selection API')
            return text
    except Exception as e:
        print(f'    Selection API failed ({e.__class__.__name__}), trying cell-by-cell...')

    # Strategy 3: Build TSV from table cells directly
    try:
        text = await page.evaluate('''() => {
            const table = document.querySelector('.TableBase table') ||
                          document.querySelector('table.data') ||
                          document.querySelector('table');
            if (!table) return '';
            const rows = table.querySelectorAll('tr');
            const lines = [];
            for (const row of rows) {
                const cells = row.querySelectorAll('td, th');
                if (cells.length < 2) continue;
                const vals = [];
                for (const cell of cells) {
                    // Get visible text, collapse whitespace
                    let t = cell.innerText || cell.textContent || '';
                    t = t.replace(/\\n/g, ' ').replace(/\\s+/g, ' ').trim();
                    vals.push(t);
                }
                lines.push(vals.join('\\t'));
            }
            return lines.join('\\n');
        }''')
        if text and len(text) > 100:
            print('    Extracted via cell-by-cell')
            return text
    except Exception as e:
        print(f'    Cell-by-cell failed ({e.__class__.__name__})')

    return ''


async def extract_all_pages(page: Page) -> str:
    """
    Extract table text from all pages of CBS stats.

    CBS uses numbered pagination links (1, 2, 3...) with URLs like
    /stats/data-stats-report/.../projections?start_row=101.
    We find these links and navigate to each page in order.
    """
    all_text = await extract_table_text(page)
    if not all_text:
        return ''

    # Find all numbered pagination links with start_row URLs
    page_urls = await page.evaluate('''() => {
        const urls = [];
        for (const a of document.querySelectorAll('a')) {
            const text = (a.textContent || '').trim();
            const href = a.href || '';
            if (/^\\d+$/.test(text) && href.includes('start_row=')) {
                const num = parseInt(text);
                if (num > 1) urls.push({num, href});
            }
        }
        urls.sort((a, b) => a.num - b.num);
        return urls;
    }''')

    if not page_urls:
        return all_text

    print(f'    Found {len(page_urls)} additional pages')

    for pu in page_urls:
        print(f'    Paginating to page {pu["num"]}...')
        await page.goto(pu['href'], wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)

        page_text = await extract_table_text(page)
        if not page_text:
            break

        # Keep only data rows (lines with the bullet character)
        data_lines = [l for l in page_text.splitlines() if '•' in l]
        if data_lines:
            all_text += '\n' + '\n'.join(data_lines)

    return all_text


# ── Main ──────────────────────────────────────────────────────────────────

async def main():
    async with async_playwright() as pw:
        browser, ctx = await create_context(pw)
        page = await ctx.new_page()

        # ── Login ─────────────────────────────────────────────────────────
        logged_in = await ensure_logged_in(page)
        if not logged_in:
            print('\nCould not reach the stats page. Exiting.')
            await browser.close()
            return

        # ── BATTERS ───────────────────────────────────────────────────────
        print('\n[1/2] BATTERS')
        success = await navigate_to_projections(page, 'Batter')
        if not success:
            manual_prompt('Batters')

        print('  Extracting table...')
        batter_text = await extract_all_pages(page)

        if batter_text:
            BATTER_FILE.write_text(batter_text, encoding='utf-8')
            print(f'  Wrote {BATTER_FILE.name} ({len(batter_text)} chars)')
        else:
            print('  WARNING: No batter data extracted.')

        # ── PITCHERS ──────────────────────────────────────────────────────
        print('\n[2/2] PITCHERS')
        print(f'  Navigating back to {STATS_URL}')
        await page.goto(STATS_URL, wait_until='domcontentloaded', timeout=60000)
        await page.wait_for_timeout(2000)

        success = await navigate_to_projections(page, 'P')
        if not success:
            manual_prompt('Pitchers (P)')

        print('  Extracting table...')
        pitcher_text = await extract_all_pages(page)

        if pitcher_text:
            PITCHER_FILE.write_text(pitcher_text, encoding='utf-8')
            print(f'  Wrote {PITCHER_FILE.name} ({len(pitcher_text)} chars)')
        else:
            print('  WARNING: No pitcher data extracted.')

        # Save session in case it was refreshed during navigation
        await save_session(ctx)
        await browser.close()

    print(f'\nDone. Files saved with date stamp {TODAY}.')
    print(f'Next: python load_projections.py')


if __name__ == '__main__':
    asyncio.run(main())
