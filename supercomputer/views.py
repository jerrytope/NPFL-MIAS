import json

from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Prefetch

from dashboard.utils import get_npfl_data
from supercomputer.models import SeasonFixture, Prediction, TeamSeasonProjection
from supercomputer.predictor import predict_all_fixtures
from supercomputer.standings import calculate_standings


def _max_visible_match_day(season):
    """
    Match Day N is visible once every fixture in Match Day N-1 has a result
    entered (progressive reveal — predictions for a match day shouldn't be
    browsable until the previous one has actually played out). Match Day 1
    is always visible. Returns the highest visible match day, or 0 if the
    season has no fixtures at all.
    """
    from django.db.models import Q

    match_days = list(
        SeasonFixture.objects.filter(season=season)
        .values_list('match_day', flat=True).distinct().order_by('match_day')
    )
    if not match_days:
        return 0

    visible = match_days[0]
    for md in match_days:
        incomplete = SeasonFixture.objects.filter(season=season, match_day=md).filter(
            Q(home_goal__isnull=True) | Q(away_goal__isnull=True)
        ).exists()
        if incomplete:
            visible = md
            break
        visible = md
    return visible


def index(request):
    """Render the Super Computer dashboard."""
    season = request.GET.get('season', '26/27')
    prediction_count = Prediction.objects.count()

    total_match_days = (
        SeasonFixture.objects.filter(season=season)
        .values_list('match_day', flat=True).distinct().count()
    )

    context = {
        'prediction_count': prediction_count,
        'total_match_days': total_match_days,
    }
    return render(request, 'supercomputer/index.html', context)


def predictions_api(request):
    """
    JSON API — all predictions by default (the full season, matching the
    Standings page). Progressive reveal only applies to an explicit
    ?match_day= request: you can't jump ahead to browse a specific match day
    until every fixture in the one before it has a result entered (see
    _max_visible_match_day) — asking for a locked match day returns an empty
    result rather than an error, so the UI can just show nothing selected.

    Query params:
        ?match_day=5     — filter by fixture match day (1-38); locked ones return no results
        ?team=Enyimba    — filter by team name
        ?season=26/27    — season (default: 26/27)
    """
    season = request.GET.get('season', '26/27')
    match_day = request.GET.get('match_day')
    team = request.GET.get('team')

    max_visible_md = _max_visible_match_day(season)

    predictions = Prediction.objects.select_related(
        'fixture', 'fixture__home', 'fixture__away'
    ).filter(fixture__season=season)

    if match_day:
        try:
            match_day_int = int(match_day)
        except ValueError:
            return JsonResponse({'error': 'match_day must be an integer'}, status=400)
        predictions = predictions.filter(fixture__match_day=match_day_int) if match_day_int <= max_visible_md else predictions.none()

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
            'home_lambda': p.home_lambda,
            'away_lambda': p.away_lambda,
            'home_attack': p.home_attack,
            'home_defense': p.home_defense,
            'away_attack': p.away_attack,
            'away_defense': p.away_defense,
            'home_transfer_score': p.home_transfer_score,
            'away_transfer_score': p.away_transfer_score,
            'manually_edited': p.manually_edited,
        })

    total_match_days = (
        SeasonFixture.objects.filter(season=season)
        .values_list('match_day', flat=True).distinct().count()
    )

    return JsonResponse({
        'count': len(results),
        'results': results,
        'max_visible_match_day': max_visible_md,
        'total_match_days': total_match_days,
    })


def models_Q_home_or_away(team):
    """Return a Q object that matches fixtures where team is home or away."""
    from django.db.models import Q
    return Q(fixture__home__name=team) | Q(fixture__away__name=team)


def standings(request):
    """Render the predicted league standings page with 2 tabs: Predicted Standings and 1,000 Monte Carlo Simulations."""
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

    # Tab 1: Predicted standings from individual match predictions
    standings_data = calculate_standings(max_match_day=max_match_day)

    # Tab 2: 1,000-run Monte Carlo Simulation projections
    projections = list(
        TeamSeasonProjection.objects.filter(season='26/27')
        .select_related('team')
        .order_by('-expected_points', '-avg_goal_diff')
    )

    return render(request, 'supercomputer/standings.html', {
        'standings': standings_data,
        'projections': projections,
        'all_match_days': all_match_days,
        'selected_md': max_match_day,
    })

