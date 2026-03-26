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
import unicodedata
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

# Manual overrides: CBS name → Lahman playerID
# Add entries here for cases norm() can't resolve automatically:
#   - Nickname vs. formal name (Josh vs. Joshua, Mike vs. Michael, etc.)
#   - Hyphenated names CBS drops the hyphen from
#   - Middle initials present in one source but not the other
NAME_OVERRIDES: dict[str, str] = {
    'Joshua Lowe':  'lowejo01',  # Lahman: "Josh Lowe"
    'Jt Ginn':      'ginnjt01',  # Lahman: "J. T. Ginn"
    'Josh H. Smith': 'smithjo09', # Lahman: "Josh Smith" (TEX infielder; middle initial needed)
}


_SUFFIX_RE = re.compile(r'\b(jr|sr|ii|iii|iv)\b\.?', re.IGNORECASE)

def norm(name: str) -> str:
    # Decompose accented chars to base + diacritic, then drop diacritics (n~->n, e'->e, etc.)
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    # Strip generational suffixes
    name = _SUFFIX_RE.sub('', name)
    # Replace all non-alphanumeric chars with spaces (handles C.J., J.P., Kiner-Falefa, etc.)
    name = re.sub(r'[^a-z0-9]', ' ', name.lower())
    return re.sub(r'\s+', ' ', name).strip()


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


def best_candidate(candidates: list[tuple], cbs_team: str,
                   teams_2025: dict, claimed_pids: set,
                   relevant_ids: set) -> str | None:
    """
    From a list of (pid, name) candidates, pick the best match using:
      1. Team match against 2025 Lahman team
      2. Prefer candidates with recent (2024/2025) fielding data
      3. Process of elimination: remove already-claimed PIDs
      4. Fall back to first remaining candidate
    Returns playerID or None.
    """
    if not candidates:
        return None

    pool = candidates

    # Prefer candidates with recent fielding data over retired players
    with_data = [c for c in pool if c[0] in relevant_ids]
    if with_data:
        pool = with_data

    # Remove PIDs already claimed by another CBS player
    unclaimed = [c for c in pool if c[0] not in claimed_pids]
    if unclaimed:
        pool = unclaimed

    if len(pool) == 1:
        return pool[0][0]

    # Try team match
    if cbs_team:
        team_match = [c for c in pool
                      if cbs_team in teams_2025.get(c[0], set())]
        if len(team_match) == 1:
            return team_match[0][0]

    return pool[0][0]  # best guess: take first


def resolve(cbs_name: str, norm_index: dict, full_norm_index: dict,
            cbs_team: str, teams_2025: dict,
            claimed_pids: set, relevant_ids: set) -> tuple[str | None, str]:
    """
    Return (playerID, source) for a CBS player name.
    source: 'override' | 'primary' | 'secondary' | 'none'

    Two-pass strategy:
      Primary  — search only players with 2024/2025 fielding data
      Secondary — search all of People.csv (handles team changes, missing data)
    """
    if cbs_name in NAME_OVERRIDES:
        return NAME_OVERRIDES[cbs_name], 'override'

    key = norm(cbs_name)

    # Pass 1: players with fielding data
    candidates = norm_index.get(key, [])
    if candidates:
        pid = best_candidate(candidates, cbs_team, teams_2025,
                             claimed_pids, relevant_ids)
        return pid, 'primary'

    # Pass 2: all People.csv (player may have changed teams or have sparse data)
    all_candidates = full_norm_index.get(key, [])
    if all_candidates:
        pid = best_candidate(all_candidates, cbs_team, teams_2025,
                             claimed_pids, relevant_ids)
        return pid, 'secondary'

    return None, 'none'


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

    relevant_ids     = set(games_2025) | set(games_2024)
    norm_index       = build_norm_index(id_to_name, relevant_ids)
    full_norm_index  = build_norm_index(id_to_name, set(id_to_name.keys()))

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
    positions_2025:   dict[str, list[str]]       = {}
    games_2025_named: dict[str, dict[str, int]]  = {}
    games_2024_named: dict[str, dict[str, int]]  = {}

    unmatched:  list[str] = []
    dh_only:    list[str] = []
    ambiguous:  list[str] = []
    secondary:  list[str] = []   # matched only via full People.csv fallback
    claimed_pids: set[str] = set()

    for name in sorted(cbs_names):
        team = cbs_team.get(name, '')
        pid, source = resolve(name, norm_index, full_norm_index,
                              team, teams_2025, claimed_pids, relevant_ids)

        # Log ambiguity
        key = norm(name)
        primary_candidates = norm_index.get(key, [])
        all_candidates     = full_norm_index.get(key, [])
        if len(primary_candidates) > 1 or (not primary_candidates and len(all_candidates) > 1):
            chosen_from = primary_candidates or all_candidates
            ambiguous.append(
                f'{name!r} ({source}) -> chose {id_to_name.get(pid, "?")} '
                f'from {[c[1] for c in chosen_from]}'
            )

        if pid is None:
            unmatched.append(name)
            positions_2025[name] = ['DH']
            continue

        claimed_pids.add(pid)
        if source == 'secondary':
            secondary.append(f'{name!r} -> {id_to_name.get(pid, pid)}')

        # 2025 eligibility
        g2025 = games_2025.get(pid, {})
        elig  = [pos for pos, g in g2025.items() if g >= THRESHOLD]
        elig  = sort_positions(elig)

        if not elig:
            dh_only.append(name)

        elig.append('DH')   # everyone gets DH; if elig was empty → DH only
        positions_2025[name] = elig

        # 2025 raw game counts (used to display total games played)
        if g2025:
            games_2025_named[name] = {p: int(g) for p, g in g2025.items()}

        # 2024 raw game counts (stored for future use)
        g2024 = games_2024.get(pid, {})
        if g2024:
            games_2024_named[name] = {p: int(g) for p, g in g2024.items()}

    # ── Report ─────────────────────────────────────────────────────────────
    multi_pos = sum(1 for v in positions_2025.values() if len(v) > 1)
    print(f'\nResults:')
    print(f'  Total CBS players:          {len(cbs_names)}')
    print(f'  Matched to Lahman:          {len(cbs_names) - len(unmatched)}')
    print(f'    via primary (fielding data): {len(cbs_names) - len(unmatched) - len(secondary)}')
    print(f'    via secondary (all People):  {len(secondary)}')
    print(f'  Multi-position eligible:    {multi_pos}')
    print(f'  DH-only (< {THRESHOLD}g at any pos): {len(dh_only)}')
    print(f'  No Lahman match (DH only):  {len(unmatched)}')
    if secondary:
        print(f'\nSecondary matches (no fielding data, matched via People.csv):')
        for s in secondary:
            print(f'  {s}')

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
        'games_2025':     games_2025_named,
        'games_2024':     games_2024_named,
    }
    OUT_FILE.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    print(f'\nSaved -> {OUT_FILE}')
    print('Next: git add docs/data.json && git commit && git push')


if __name__ == '__main__':
    main()
