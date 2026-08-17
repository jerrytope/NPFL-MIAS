"""
NPFL Super Computer — Standings Calculator

Computes predicted league standings from Prediction results.
Win = 3 pts, Draw = 1 pt, Loss = 0 pts.
"""

from collections import defaultdict

from supercomputer.models import Prediction


SEASON = '26/27'


def calculate_standings(season=SEASON):
    """
    Calculate predicted league standings from all predictions for a season.

    Returns a list of dicts sorted by points (desc), each containing:
        position, team, played, won, drawn, lost, points
    """
    predictions = Prediction.objects.filter(
        fixture__season=season,
    ).select_related('fixture__home', 'fixture__away')

    # Team stats accumulator
    stats = defaultdict(lambda: {
        'played': 0, 'won': 0, 'drawn': 0, 'lost': 0, 'points': 0,
    })

    for p in predictions:
        home_name = p.fixture.home.name
        away_name = p.fixture.away.name

        # Ensure both teams exist in stats
        stats[home_name]  # touch
        stats[away_name]  # touch

        stats[home_name]['played'] += 1
        stats[away_name]['played'] += 1

        if p.predicted_result == 'HOME':
            stats[home_name]['won'] += 1
            stats[home_name]['points'] += 3
            stats[away_name]['lost'] += 1
        elif p.predicted_result == 'AWAY':
            stats[away_name]['won'] += 1
            stats[away_name]['points'] += 3
            stats[home_name]['lost'] += 1
        elif p.predicted_result == 'DRAW':
            stats[home_name]['drawn'] += 1
            stats[home_name]['points'] += 1
            stats[away_name]['drawn'] += 1
            stats[away_name]['points'] += 1

    # Sort: points desc, then won desc, then played asc
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
            'won': s['won'],
            'drawn': s['drawn'],
            'lost': s['lost'],
            'points': s['points'],
        })

    return standings
