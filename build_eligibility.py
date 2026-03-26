#!/usr/bin/env python
"""
build_eligibility.py — Build position eligibility from Lahman/SABR data.

Before running, download from the SABR Box link in CLAUDE.md and place in
this directory:
  People.csv   — playerID <-> name mapping
  Fielding.csv — games by position per year

Eligibility rules (AL roto league):
  - 20+ games at a position in 2025 → eligible there
  - LF / CF / RF / OF all collapse to OF
  - Everyone is eligible at DH
  - If no position reaches the threshold in 2025 → DH only

2024 game counts are stored in data.json for future use (e.g. injury exceptions)
but do NOT affect current eligibility logic.

Usage: python build_eligibility.py
"""

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
DOCS_DIR = BASE_DIR / 'docs'
OUT_FILE = DOCS_DIR / 'data.json'

PEOPLE_CSV   = BASE_DIR / 'People.csv'
FIELDING_CSV = BASE_DIR / 'Fielding.csv'

THRESHOLD = 20          # games in 2025 to qualify at a position
OF_VARIANTS = {'LF', 'CF', 'RF', 'OF'}
TRACKED    = {'C', '1B', '2B', '3B', 'SS', 'OF'}   # positions we care about
POS_ORDER  = ['C', '1B', '2B', '3B', 'SS', 'OF', 'DH']

# Lahman teamID → our canonical abbreviation
LAHMAN_TEAM = {
    'NYA': 'NYY', 'TBA': 'TB',  'CHA': 'CWS', 'KCA': 'KC',
    'BAL': 'BAL', 'BOS': 'BOS', 'TOR': 'TOR', 'CLE': 'CLE',
    'DET': 'DET', 'MIN': 'MIN', 'HOU': 'HOU', 'LAA': 'LAA',
    'OAK': 'OAK', 'ATH': 'OAK', 'SEA': 'SEA', 'TEX': 'TEX',
}


def norm(name: str) -> str:
    return re.sub(r'[^a-z0-9 ]', '', name.lower()).strip()


def sort_positions(positions: list[str]) -> list[str]:
    return sorted(set(positions), key=lambda p: POS_ORDER.index(p) if p in POS_ORDER else 99)


# ── Load People.csv ────────────────────────────────────────────────────────

def load_people(path: Path) -> dict[str, str]:
    """Returns {playerID: 'First Last'}"""
    result = {}
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            first = (row.get('nameFirst') or '').strip()
            last  = (row.get('nameLast')  or '').strip()
            name  = f'{first} {last}'.strip()
            if name:
                result[row['playerID']] = name
    print(f'  {len(result):,} players in People.csv')
    return result


# ── Load Fielding.csv ──────────────────────────────────────────────────────

def load_fielding(path: Path) -> tuple[dict, dict, dict]:
    """
    Returns:
      games_2025: {playerID: {pos: games}}
      games_2024: {playerID: {pos: games}}
      teams_2025: {playerID: set of canonical team abbrs}
    """
    games_2025: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    games_2024: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    teams_2025: dict[str, set[str]]       = defaultdict(set)

    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            year = int(row.get('yearID') or 0)
            if year not in (2024, 2025):
                continue

            pid = row['playerID']
            pos = row.get('POS', '').strip().upper()
            if pos in OF_VARIANTS:
                pos = 'OF'
            if pos not in TRACKED:
                continue

            try:
                g = int(row.get('G') or 0)
            except ValueError:
                g = 0

            if year == 2025:
                games_2025[pid][pos] += g
                tid = LAHMAN_TEAM.get(row.get('teamID', ''), row.get('teamID', ''))
                teams_2025[pid].add(tid)
            else:
                games_2024[pid][pos] += g

    print(f'  {len(games_2025):,} players with 2025 fielding data')
    print(f'  {len(games_2024):,} players with 2024 fielding data')
    return dict(games_2025), dict(games_2024), dict(teams_2025)


# ── Name matching ──────────────────────────────────────────────────────────

def build_norm_index(id_to_name: dict, relevant_ids: set) -> dict[str, list[tuple]]:
    """norm_name → [(playerID, fullName)]  (only for players with relevant data)"""
    index: dict[str, list] = defaultdict(list)
    for pid, name in id_to_name.items():
        if pid in relevant_ids:
            index[norm(name)].append((pid, name))
    return index


def resolve(cbs_name: str, norm_index: dict, cbs_team: str,
            teams_2025: dict) -> str | None:
    """Return best-matching Lahman playerID for a CBS player name."""
    candidates = norm_index.get(norm(cbs_name), [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    # Disambiguate by team
    if cbs_team:
        team_match = [c for c in candidates
                      if cbs_team in teams_2025.get(c[0], set())]
        if len(team_match) == 1:
            return team_match[0][0]

    return candidates[0][0]   # best guess: take first


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    for f in (PEOPLE_CSV, FIELDING_CSV):
        if not f.exists():
            print(f'ERROR: {f.name} not found in {BASE_DIR}')
            print('Download People.csv and Fielding.csv from the SABR Box link in CLAUDE.md.')
            return

    print('Loading People.csv...')
    id_to_name = load_people(PEOPLE_CSV)

    print('Loading Fielding.csv...')
    games_2025, games_2024, teams_2025 = load_fielding(FIELDING_CSV)

    relevant_ids = set(games_2025) | set(games_2024)
    norm_index   = build_norm_index(id_to_name, relevant_ids)

    # ── Load CBS names from data.json ──────────────────────────────────────
    print('\nLoading data.json...')
    existing = json.loads(OUT_FILE.read_text(encoding='utf-8'))

    cbs_team: dict[str, str] = {}   # name → team abbr
    cbs_names: set[str] = set()

    for team, positions in existing.get('depth_chart', {}).items():
        for players in positions.values():
            for p in players:
                cbs_names.add(p['name'])
                cbs_team[p['name']] = team

    for name in existing.get('rankings', {}):
        cbs_names.add(name)

    print(f'  {len(cbs_names)} CBS player names to match')

    # ── Match & compute eligibility ────────────────────────────────────────
    print('\nMatching names and computing eligibility...')
    positions_2025: dict[str, list[str]] = {}
    games_2024_named: dict[str, dict[str, int]] = {}

    unmatched: list[str] = []
    dh_only:   list[str] = []
    ambiguous: list[str] = []

    for name in sorted(cbs_names):
        team = cbs_team.get(name, '')
        pid  = resolve(name, norm_index, team, teams_2025)

        # Check for ambiguity (for logging)
        candidates = norm_index.get(norm(name), [])
        if len(candidates) > 1:
            ambiguous.append(
                f'{name!r} → chose {id_to_name.get(pid,"")} '
                f'from {[c[1] for c in candidates]}'
            )

        if pid is None:
            unmatched.append(name)
            positions_2025[name] = ['DH']
            continue

        # 2025 eligibility
        g2025 = games_2025.get(pid, {})
        elig  = [pos for pos, g in g2025.items() if g >= THRESHOLD]
        elig  = sort_positions(elig)

        if not elig:
            dh_only.append(name)

        elig.append('DH')   # everyone gets DH; if elig was empty → DH only
        positions_2025[name] = elig

        # 2024 raw game counts (stored for future use)
        g2024 = games_2024.get(pid, {})
        if g2024:
            games_2024_named[name] = {p: int(g) for p, g in g2024.items()}

    # ── Report ─────────────────────────────────────────────────────────────
    multi_pos = sum(1 for v in positions_2025.values() if len(v) > 1)
    print(f'\nResults:')
    print(f'  Total CBS players:          {len(cbs_names)}')
    print(f'  Matched to Lahman:          {len(cbs_names) - len(unmatched)}')
    print(f'  Multi-position eligible:    {multi_pos}')
    print(f'  DH-only (< {THRESHOLD}g at any pos): {len(dh_only)}')
    print(f'  No Lahman match (DH only):  {len(unmatched)}')

    if ambiguous:
        print(f'\nAmbiguous matches ({len(ambiguous)} — used first/team candidate):')
        for a in ambiguous[:15]:
            print(f'  {a}')
        if len(ambiguous) > 15:
            print(f'  ... and {len(ambiguous)-15} more')

    if unmatched:
        print(f'\nUnmatched CBS names (DH-only):')
        for n in unmatched[:20]:
            print(f'  {n!r}')

    # ── Sample ─────────────────────────────────────────────────────────────
    print('\nSample eligibility (multi-position players):')
    shown = 0
    for name, pos in positions_2025.items():
        if len(pos) > 2:   # more than just DH + one position
            print(f'  {name}: {pos}')
            shown += 1
            if shown >= 10:
                break

    # ── Save ───────────────────────────────────────────────────────────────
    existing['eligibility'] = {
        'positions_2025': positions_2025,
        'games_2024':     games_2024_named,
    }
    OUT_FILE.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    print(f'\nSaved -> {OUT_FILE}')
    print('Next: git add docs/data.json && git commit && git push')


if __name__ == '__main__':
    main()
