import json

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Prefetch

from dashboard.utils import get_npfl_data
from supercomputer.models import SeasonFixture, Prediction
from supercomputer.predictor import predict_all_fixtures
from supercomputer.standings import calculate_standings


def index(request):
    """Render the Super Computer dashboard."""
    prediction_count = Prediction.objects.count()

    context = {
        'prediction_count': prediction_count,
    }
    return render(request, 'supercomputer/index.html', context)


def predictions_api(request):
    """
    JSON API — all predictions.

    Query params:
        ?match_day=5     — filter by fixture match day (1-38)
        ?team=Enyimba    — filter by team name
        ?season=26/27    — season (default: 26/27)
    """
    season = request.GET.get('season', '26/27')
    match_day = request.GET.get('match_day')
    team = request.GET.get('team')

    predictions = Prediction.objects.select_related(
        'fixture', 'fixture__home', 'fixture__away'
    )

    if match_day:
        try:
            predictions = predictions.filter(fixture__match_day=int(match_day))
        except ValueError:
            return JsonResponse({'error': 'match_day must be an integer'}, status=400)

    if team:
        predictions = predictions.filter(
            models_Q_home_or_away(team)
        )

    results = []
    for p in predictions.order_by('fixture__match_day', 'fixture__id'):
        results.append({
            'id': p.id,
            'fixture_id': p.fixture_id,
            'match_day': p.fixture.match_day,
            'home': p.fixture.home.name,
            'away': p.fixture.away.name,
            'home_win_pct': p.home_win_pct,
            'draw_pct': p.draw_pct,
            'away_win_pct': p.away_win_pct,
            'predicted_result': p.predicted_result,
            'confidence': p.confidence,
            'home_form_score': p.home_form_score,
            'away_form_score': p.away_form_score,
            'h2h_home_rate': p.h2h_home_rate,
            'h2h_draw_rate': p.h2h_draw_rate,
            'h2h_away_rate': p.h2h_away_rate,
            'home_venue_strength': p.home_venue_strength,
            'away_venue_strength': p.away_venue_strength,
            'home_transfer_score': p.home_transfer_score,
            'away_transfer_score': p.away_transfer_score,
            'manually_edited': p.manually_edited,
        })

    return JsonResponse({
        'count': len(results),
        'results': results,
    })


def models_Q_home_or_away(team):
    """Return a Q object that matches fixtures where team is home or away."""
    from django.db.models import Q
    return Q(fixture__home__name=team) | Q(fixture__away__name=team)


def standings(request):
    """Render the predicted league standings page with optional match day filter."""
    max_md = request.GET.get('match_day')
    max_match_day = None
    if max_md:
        try:
            max_match_day = int(max_md)
        except ValueError:
            pass

    # Get all available match days for the selector
    all_match_days = list(
        SeasonFixture.objects.filter(season='26/27')
        .values_list('match_day', flat=True)
        .distinct()
        .order_by('match_day')
    )

    standings_data = calculate_standings(max_match_day=max_match_day)
    return render(request, 'supercomputer/standings.html', {
        'standings': standings_data,
        'all_match_days': all_match_days,
        'selected_md': max_match_day,
    })
