"""
NPFL Super Computer — Standings Calculator

Computes predicted league standings from Prediction results using EXPECTED
points/wins per fixture (e.g. E[home_wins] = home_win_pct/100), not by
treating each fixture's single most-likely outcome as a certainty.

The previous version tallied whichever of HOME/DRAW/AWAY had the highest
percentage as a guaranteed result. That structurally inflates the best team's
season total regardless of how accurate the underlying per-match percentages
are: being even a narrow 35% favorite in every match still adds up to "wins
almost everything" once tallied as a certainty over 38 games. Real backtest
evidence: the league's strongest team came out with a 32-3-3 / 99-point
record under the old method (no NPFL champion has scored above 77 points in
the last decade) — using expectation instead fixes this at the root, using
the exact same underlying percentages.
"""

from collections import defaultdict

from supercomputer.models import Prediction, SeasonFixture


SEASON = '26/27'


def calculate_standings(season=SEASON, max_match_day=None):
    """
    Calculate predicted league standings from predictions up to a given match day,
    using expected points/wins/draws/losses per fixture.

    Args:
        season: Season identifier string.
        max_match_day: If set, only include predictions for fixtures with
                       match_day <= this value. None = all match days.

    Returns a list of dicts sorted by expected points (desc), each containing:
        position, team, played, won, drawn, lost, points
        (won/drawn/lost/points are expectations, not literal counts —
        rounded to 1 decimal place to keep that visible)
    """
    predictions = Prediction.objects.filter(
        fixture__season=season,
    ).select_related('fixture__home', 'fixture__away')

    if max_match_day is not None:
        predictions = predictions.filter(fixture__match_day__lte=max_match_day)

    stats = defaultdict(lambda: {
        'played': 0, 'won': 0.0, 'drawn': 0.0, 'lost': 0.0, 'points': 0.0,
    })

    for p in predictions:
        home_name = p.fixture.home.name
        away_name = p.fixture.away.name

        home_win_p = p.home_win_pct / 100.0
        draw_p = p.draw_pct / 100.0
        away_win_p = p.away_win_pct / 100.0

        stats[home_name]['played'] += 1
        stats[away_name]['played'] += 1

        stats[home_name]['won'] += home_win_p
        stats[home_name]['drawn'] += draw_p
        stats[home_name]['lost'] += away_win_p
        stats[home_name]['points'] += 3 * home_win_p + 1 * draw_p

        stats[away_name]['won'] += away_win_p
        stats[away_name]['drawn'] += draw_p
        stats[away_name]['lost'] += home_win_p
        stats[away_name]['points'] += 3 * away_win_p + 1 * draw_p

    # Sort: expected points desc, then expected wins desc, then played asc
    sorted_teams = sorted(
        stats.items(),
        key=lambda x: (-x[1]['points'], -x[1]['won'], x[1]['played']),
    )

    standings = []
    for pos, (team_name, s) in enumerate(sorted_teams, start=1):
        standings.append({
            'position': pos,
            'team': team_name,
            'played': s['played'],
            'won': round(s['won'], 1),
            'drawn': round(s['drawn'], 1),
            'lost': round(s['lost'], 1),
            'points': round(s['points'], 1),
        })

    return standings


def calculate_actual_table(season=SEASON):
    """
    The real league table, built only from results the admin has actually
    entered — no predictions or projections involved.

    Reads SeasonFixture rather than the Match table: it is scoped to the
    season, carries match_day, has a real uniqueness constraint, and is
    already the source simulator.py uses for played fixtures. A fixture counts
    once both goals are set (SeasonFixture.is_played).

    Every club in the season's fixture list gets a row, so all 20 appear with
    zeros before their opening game instead of vanishing from the table.

    Returns a list of dicts sorted by the official NPFL tie-break, each with:
        position, team, played, won, drawn, lost, gf, ga, gd, points
    """
    fixtures = (
        SeasonFixture.objects.filter(season=season)
        .select_related('home', 'away')
    )

    def new_row(team_name):
        return {
            'team': team_name, 'played': 0, 'won': 0, 'drawn': 0, 'lost': 0,
            'gf': 0, 'ga': 0, 'points': 0,
        }

    stats = {}
    for f in fixtures:
        for name in (f.home.name, f.away.name):
            stats.setdefault(name, new_row(name))

        if not f.is_played:
            continue

        home, away = stats[f.home.name], stats[f.away.name]
        home_goal, away_goal = f.home_goal, f.away_goal

        home['played'] += 1
        away['played'] += 1
        home['gf'] += home_goal
        home['ga'] += away_goal
        away['gf'] += away_goal
        away['ga'] += home_goal

        if home_goal > away_goal:
            home['won'] += 1
            home['points'] += 3
            away['lost'] += 1
        elif home_goal < away_goal:
            away['won'] += 1
            away['points'] += 3
            home['lost'] += 1
        else:
            home['drawn'] += 1
            away['drawn'] += 1
            home['points'] += 1
            away['points'] += 1

    for row in stats.values():
        row['gd'] = row['gf'] - row['ga']

    # Official NPFL tie-break: Points -> Goal Difference -> Goals For. Kept
    # identical to the simulated table's ordering in simulator.py so the real
    # and projected tables can never rank the same records differently. Team
    # name is a final tiebreak purely so equal records (every team, before a
    # ball is kicked) come out in a stable order rather than an arbitrary one.
    ordered = sorted(
        stats.values(),
        key=lambda r: (-r['points'], -r['gd'], -r['gf'], r['team']),
    )

    for position, row in enumerate(ordered, start=1):
        row['position'] = position

    return ordered


def get_prediction_breakdown(season=SEASON):
    """
    Break down each team's predicted home/away win/draw/loss using EXPECTED
    values (sum of each fixture's own win/draw/loss percentage), the same
    methodology as calculate_standings() and the /supercomputer/ stat banner
    — not a count of how often that outcome is the single most-likely pick,
    which is a different, easily-confused number (see calculate_standings()'s
    docstring for why the two diverge in a home-dominant league).

    Returns a list of dicts sorted by team name, each with:
        home_played, home_win, home_draw, home_loss (expected, rounded to 1dp)
        away_played, away_win, away_draw, away_loss (expected, rounded to 1dp)
        home_fixtures, away_fixtures: per-fixture detail so opponents are
            still visible — each entry is {'team', 'match_day', 'win_pct',
            'draw_pct', 'loss_pct'} using the team's own win/draw/loss chance
            for that fixture (already reoriented for the away side).
    """
    predictions = Prediction.objects.filter(
        fixture__season=season,
    ).select_related('fixture__home', 'fixture__away')

    def new_entry(team_name):
        return {
            'team': team_name,
            'home_played': 0, 'home_win': 0.0, 'home_draw': 0.0, 'home_loss': 0.0,
            'away_played': 0, 'away_win': 0.0, 'away_draw': 0.0, 'away_loss': 0.0,
            'home_fixtures': [], 'away_fixtures': [],
        }

    stats = {}
    for p in predictions:
        home_name = p.fixture.home.name
        away_name = p.fixture.away.name
        match_day = p.fixture.match_day

        home_win_p = p.home_win_pct / 100.0
        draw_p = p.draw_pct / 100.0
        away_win_p = p.away_win_pct / 100.0

        home_entry = stats.setdefault(home_name, new_entry(home_name))
        home_entry['home_played'] += 1
        home_entry['home_win'] += home_win_p
        home_entry['home_draw'] += draw_p
        home_entry['home_loss'] += away_win_p
        home_entry['home_fixtures'].append({
            'team': away_name, 'match_day': match_day,
            'win_pct': p.home_win_pct, 'draw_pct': p.draw_pct, 'loss_pct': p.away_win_pct,
        })

        away_entry = stats.setdefault(away_name, new_entry(away_name))
        away_entry['away_played'] += 1
        away_entry['away_win'] += away_win_p
        away_entry['away_draw'] += draw_p
        away_entry['away_loss'] += home_win_p
        away_entry['away_fixtures'].append({
            'team': home_name, 'match_day': match_day,
            'win_pct': p.away_win_pct, 'draw_pct': p.draw_pct, 'loss_pct': p.home_win_pct,
        })

    result = []
    for entry in stats.values():
        for key in ('home_win', 'home_draw', 'home_loss', 'away_win', 'away_draw', 'away_loss'):
            entry[key] = round(entry[key], 1)
        entry['home_fixtures'].sort(key=lambda f: f['match_day'])
        entry['away_fixtures'].sort(key=lambda f: f['match_day'])
        result.append(entry)

    return sorted(result, key=lambda x: x['team'])
