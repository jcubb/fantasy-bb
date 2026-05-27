#!/usr/bin/env python
"""
load_projections.py — Choose a projection snapshot and load it into data.json.

Scans for date-stamped projection files (batters_YYYY-MM-DD.txt /
pitchers_YYYY-MM-DD.txt) and legacy files (batters2026.txt etc.),
lists available snapshots, and lets you pick which one to load into
docs/data.json for the web app.

Usage: python load_projections.py
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
DOCS_DIR = BASE_DIR / 'docs'
OUT_FILE = DOCS_DIR / 'data.json'

BATTER_COLS  = ['AB','R','H','1B','2B','3B','HR','RBI','BB','K','SB','CS','AVG','OBP','SLG','Rank']
PITCHER_COLS = ['INNs','APP','GS','QS','CG','W','L','S','BS','HD','K','BB','H','ERA','WHIP','Rank']

PLAYER_RE = re.compile(r'^(.+?)\s+([\w,/]+)\s+•\s+([A-Z]{1,3})\s*$')

DATE_PATTERN = re.compile(r'^batters_(\d{4}-\d{2}-\d{2})\.txt$')
LEGACY_PATTERN = re.compile(r'^batters(\d{4})\.txt$')


def discover_snapshots() -> list[tuple[str, Path, Path]]:
    """
    Find all batter/pitcher file pairs in BASE_DIR.
    Returns [(label, batter_path, pitcher_path), ...] sorted by label.
    """
    snapshots = []

    for f in BASE_DIR.glob('batters_*.txt'):
        m = DATE_PATTERN.match(f.name)
        if not m:
            continue
        date_str = m.group(1)
        pitcher_file = BASE_DIR / f'pitchers_{date_str}.txt'
        if pitcher_file.exists():
            snapshots.append((date_str, f, pitcher_file))

    for f in BASE_DIR.glob('batters[0-9][0-9][0-9][0-9].txt'):
        m = LEGACY_PATTERN.match(f.name)
        if not m:
            continue
        year = m.group(1)
        pitcher_file = BASE_DIR / f'pitchers{year}.txt'
        if pitcher_file.exists():
            snapshots.append((f'{year} (legacy)', f, pitcher_file))

    snapshots.sort(key=lambda x: x[0])
    return snapshots


def parse_file(path: Path, cols: list[str]) -> dict:
    """Parse a CBS projection text file into {player_name: {stat: value}}."""
    projections = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) < 3:
            continue

        player_field = None
        player_idx = None
        for i, part in enumerate(parts):
            if '•' in part:
                player_field = part.strip()
                player_idx = i
                break

        if not player_field:
            continue

        m = PLAYER_RE.match(player_field)
        if not m:
            continue

        name = m.group(1).strip()
        pos  = m.group(2).strip()
        team = m.group(3).strip()

        stat_parts = parts[player_idx + 1:]
        stats = {'_team': team, '_pos': pos}
        for i, col in enumerate(cols):
            if i < len(stat_parts):
                val = stat_parts[i].strip()
                if val and val not in ('-', '—', 'N/A'):
                    stats[col] = val

        stats.pop('Rank', None)

        if name:
            projections[name] = stats

    return projections


def main():
    snapshots = discover_snapshots()

    if not snapshots:
        print('No projection files found.')
        print('Run scrape_projections.py first to download CBS projections.')
        return

    print('Available projection snapshots:\n')
    for i, (label, bf, pf) in enumerate(snapshots, 1):
        batters = parse_file(bf, BATTER_COLS)
        pitchers = parse_file(pf, PITCHER_COLS)
        print(f'  {i}. {label}  (batters: {len(batters)}, pitchers: {len(pitchers)})')

    default = len(snapshots)
    print()
    choice = input(f'Choose [{default}]: ').strip()

    if not choice:
        idx = default - 1
    else:
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(snapshots):
                raise ValueError
        except ValueError:
            print('Invalid choice.')
            return

    label, batter_path, pitcher_path = snapshots[idx]
    print(f'\nLoading snapshot: {label}')

    batters_proj = parse_file(batter_path, BATTER_COLS)
    pitchers_proj = parse_file(pitcher_path, PITCHER_COLS)

    print(f'  Batters:  {len(batters_proj)}')
    print(f'  Pitchers: {len(pitchers_proj)}')

    if batters_proj:
        sample = next(iter(batters_proj))
        print(f'  Sample batter  — {sample}: {batters_proj[sample]}')
    if pitchers_proj:
        sample = next(iter(pitchers_proj))
        print(f'  Sample pitcher — {sample}: {pitchers_proj[sample]}')

    if not batters_proj and not pitchers_proj:
        print('\nNo projection data parsed. data.json NOT modified.')
        return

    DOCS_DIR.mkdir(exist_ok=True)
    existing = {}
    if OUT_FILE.exists():
        existing = json.loads(OUT_FILE.read_text(encoding='utf-8'))

    existing['projections'] = {
        'batters':  batters_proj,
        'pitchers': pitchers_proj,
    }

    OUT_FILE.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    print(f'\nSaved -> {OUT_FILE}')
    print('Next: git add docs/data.json && git commit -m "Update projections" && git push')


if __name__ == '__main__':
    main()
