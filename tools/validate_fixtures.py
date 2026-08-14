"""Quick validation script for generated fixtures. Run via: python manage.py shell < tools/validate_fixtures.py"""
from supercomputer.models import SeasonFixture
from collections import Counter

season = '26/27'
fixtures = SeasonFixture.objects.filter(season=season)

print(f'Total fixtures: {fixtures.count()}')
print(f'Match days: {fixtures.values_list("match_day", flat=True).distinct().count()}')

# Count games per team
home_counts = Counter(fixtures.values_list('home__name', flat=True))
away_counts = Counter(fixtures.values_list('away__name', flat=True))
all_teams = set(home_counts.keys()) | set(away_counts.keys())

print(f'Total teams: {len(all_teams)}')
print()

# Verify each team plays 38 games (19 home + 19 away)
all_ok = True
for team in sorted(all_teams):
    h = home_counts.get(team, 0)
    a = away_counts.get(team, 0)
    total = h + a
    status = 'OK' if h == 19 and a == 19 else 'FAIL'
    if status == 'FAIL':
        all_ok = False
    print(f'  {team}: {h} home + {a} away = {total} total  [{status}]')

print()

# Verify every pair meets exactly twice (once home, once away)
pair_counts = Counter()
for f in fixtures:
    pair = tuple(sorted([f.home_id, f.away_id]))
    pair_counts[pair] += 1

bad_pairs = {k: v for k, v in pair_counts.items() if v != 2}
if bad_pairs:
    print(f'FAIL: {len(bad_pairs)} pairs do not meet exactly twice')
    all_ok = False
else:
    print(f'All {len(pair_counts)} pairs meet exactly twice: OK')

# Verify MD1 matches seed
print()
md1 = fixtures.filter(match_day=1).order_by('id')
print(f'Match Day 1 ({md1.count()} games):')
for f in md1:
    print(f'  {f.home.name} vs {f.away.name}')

print()
if all_ok:
    print('ALL CHECKS PASSED')
else:
    print('SOME CHECKS FAILED')
