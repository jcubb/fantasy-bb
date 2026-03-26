#!/usr/bin/env python
"""
parse_projections.py — Parse copied CBS projection text files into data.json.

Reads:  batters2026.txt   (pasted from CBS All Players - Batters projections)
        pitchers2026.txt  (pasted from CBS All Players - P projections)
Writes: docs/data.json    (merges projections into existing file)

Usage: python parse_projections.py
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
DOCS_DIR = BASE_DIR / 'docs'
OUT_FILE = DOCS_DIR / 'data.json'

BATTER_FILE  = BASE_DIR / 'batters2026.txt'
PITCHER_FILE = BASE_DIR / 'pitchers2026.txt'

# Column names after [action, player_info] fields
BATTER_COLS  = ['AB','R','H','1B','2B','3B','HR','RBI','BB','K','SB','CS','AVG','OBP','SLG','Rank']
PITCHER_COLS = ['INNs','APP','GS','QS','CG','W','L','S','BS','HD','K','BB','H','ERA','WHIP','Rank']

# Regex to split "Name POS • TEAM" (pos may include commas, e.g. "2B,3B")
PLAYER_RE = re.compile(r'^(.+?)\s+([\w,/]+)\s+•\s+([A-Z]{1,3})\s*$')


def parse_file(path: Path, cols: list[str]) -> dict:
    """
    Parse a CBS projection text file.
    Returns {player_name: {stat: value, ...}} (Rank excluded from stats dict).
    """
    projections = {}
    lines = path.read_text(encoding='utf-8').splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Data rows are tab-separated and have a player field containing "•"
        parts = line.split('\t')
        if len(parts) < 3 or '•' not in parts[1]:
            continue

        player_info = parts[1].strip()
        stat_parts  = parts[2:]

        # Parse player info: "Name POS • TEAM"
        m = PLAYER_RE.match(player_info)
        if not m:
            continue
        name = m.group(1).strip()

        # Map stat values to column names
        stats = {}
        for i, col in enumerate(cols):
            if i < len(stat_parts):
                val = stat_parts[i].strip()
                if val and val not in ('-', '—', 'N/A'):
                    stats[col] = val

        # Remove Rank from the stats dict (it's in the CBS rankings already)
        stats.pop('Rank', None)

        if name:
            projections[name] = stats

    return projections


def main():
    for f in (BATTER_FILE, PITCHER_FILE):
        if not f.exists():
            print(f'ERROR: {f.name} not found in {BASE_DIR}')
            return

    print(f'Parsing {BATTER_FILE.name}...')
    batters_proj = parse_file(BATTER_FILE, BATTER_COLS)
    print(f'  {len(batters_proj)} batters')

    print(f'Parsing {PITCHER_FILE.name}...')
    pitchers_proj = parse_file(PITCHER_FILE, PITCHER_COLS)
    print(f'  {len(pitchers_proj)} pitchers')

    # Sample output
    if batters_proj:
        sample = next(iter(batters_proj))
        print(f'\nSample batter  — {sample}: {batters_proj[sample]}')
    if pitchers_proj:
        sample = next(iter(pitchers_proj))
        print(f'Sample pitcher — {sample}: {pitchers_proj[sample]}')

    # Merge into data.json
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
    main()
