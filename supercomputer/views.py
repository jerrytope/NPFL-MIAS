import json

import numpy as np
from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Count, Prefetch, Sum

from dashboard.team_logos import get_logo_url_map
from dashboard.utils import get_npfl_data
from supercomputer.models import (
    SeasonFixture, Prediction, TeamSeasonProjection, MatchDayVisibility,
)
from supercomputer.poisson_model import goal_markets, top_scorelines
from supercomputer.predictor import predict_all_fixtures
from supercomputer.standings import calculate_standings


def get_unlocked_match_days(season):
    """
    The match days the admin has published, as a sorted list.

    Visibility is set explicitly per match day from the admin panel's Access
    Control page (MatchDayVisibility). A match day with no row is treated as
    locked, so a newly imported one is never public by accident.

    This replaced an automatic rule that unlocked Match Day N once every
    Match Day N-1 result had been entered. That tied publishing to
    bookkeeping, and it only ever hid the match day dropdown — the fixtures
    themselves stayed readable through "All Match Days" and by paging forward
    through the unpaginated list. Locks now apply to the data itself.
    """
    return sorted(
        MatchDayVisibility.objects
        .filter(season=season, is_unlocked=True)
        .values_list('match_day', flat=True)
    )


def _logo_urls_for(predictions):
    """
    {lowercased_team_name: crest_url_or_None} for the clubs in `predictions`.

    Resolved once per request rather than per row — a match day repeats the
    same 20 clubs across every fixture.
    """
    names = set()
    for p in predictions:
        names.add(p.fixture.home.name)
        names.add(p.fixture.away.name)
    return get_logo_url_map(names)


def _season_totals(season):
    """
    Season-wide expected outcome counts across EVERY fixture, locked or not.

    The stats banner is deliberately not restricted by locks: it sums each
    match's win/draw/loss probability over all 380 fixtures, so it reveals no
    individual matchup — only the aggregate shape of the season, which is the
    figure the page is meant to headline. The cards are what locks restrict.
    """
    totals = Prediction.objects.filter(fixture__season=season).aggregate(
        games=Count('id'),
        home=Sum('home_win_pct'),
        draw=Sum('draw_pct'),
        away=Sum('away_win_pct'),
    )
    return {
        'games': totals['games'] or 0,
        'home': round((totals['home'] or 0) / 100),
        'draw': round((totals['draw'] or 0) / 100),
        'away': round((totals['away'] or 0) / 100),
    }


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
    JSON API — predictions for the match days the admin has published.

    Locked match days are absent from EVERY route into this endpoint: the
    unfiltered "All Match Days" view, a ?team= filter, and an explicit
    ?match_day= request alike. A locked ?match_day= returns an empty result
    rather than an error, so the UI can just show nothing selected.

    `season_totals` is the one deliberate exception — see _season_totals().

    Query params:
        ?match_day=5     — filter by fixture match day (1-38); locked ones return no results
        ?team=Enyimba    — filter by team name
        ?season=26/27    — season (default: 26/27)
    """
    season = request.GET.get('season', '26/27')
    match_day = request.GET.get('match_day')
    team = request.GET.get('team')

    unlocked = get_unlocked_match_days(season)

    predictions = Prediction.objects.select_related(
        'fixture', 'fixture__home', 'fixture__away'
    ).filter(fixture__season=season, fixture__match_day__in=unlocked)

    if match_day:
        try:
            match_day_int = int(match_day)
        except ValueError:
            return JsonResponse({'error': 'match_day must be an integer'}, status=400)
        predictions = predictions.filter(fixture__match_day=match_day_int)

    if team:
        predictions = predictions.filter(
            models_Q_home_or_away(team)
        )

    predictions = list(predictions.order_by('fixture__match_day', 'fixture__id'))
    logos = _logo_urls_for(predictions)

    results = []
    for p in predictions:
        results.append({
            'id': p.id,
            'fixture_id': p.fixture_id,
            'match_day': p.fixture.match_day,
            'home': p.fixture.home.name,
            'away': p.fixture.away.name,
            'home_logo': logos.get(p.fixture.home.name.strip().lower()),
            'away_logo': logos.get(p.fixture.away.name.strip().lower()),
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
            # `manually_edited` is deliberately NOT exposed publicly — whether an
            # admin hand-adjusted a prediction is internal bookkeeping. Omitting
            # the field rather than just hiding the UI note keeps it out of the
            # JSON too. The admin panel has its own copy (admin_panel/views.py).
        })

    total_match_days = (
        SeasonFixture.objects.filter(season=season)
        .values_list('match_day', flat=True).distinct().count()
    )

    return JsonResponse({
        'count': len(results),
        'results': results,
        'unlocked_match_days': unlocked,
        'total_match_days': total_match_days,
        'season_totals': _season_totals(season),
    })


def scorelines_api(request):
    """
    JSON API — exact scoreline projections per fixture, for the Super Computer
    page's "Scoreline Projections" tab.

    Every number here is summed from the stored Prediction.scoreline_grid (the
    exact independent-Poisson probability of each scoreline), NOT sampled from
    the Monte Carlo runs: closed-form is exact rather than approximate, needs no
    simulation pass, and — unlike the simulator, which warps lambdas with its
    momentum multipliers — is guaranteed to agree with the win/draw/loss
    percentages already shown on the Match Predictions tab.

    Takes the same params as predictions_api and honours the same match day
    locks, so the two tabs never show different sets of fixtures.

    Query params:
        ?match_day=5     — filter by fixture match day (1-38); locked ones return no results
        ?team=Enyimba    — filter by team name
        ?season=26/27    — season (default: 26/27)
    """
    season = request.GET.get('season', '26/27')
    match_day = request.GET.get('match_day')
    team = request.GET.get('team')

    unlocked = get_unlocked_match_days(season)

    predictions = Prediction.objects.select_related(
        'fixture', 'fixture__home', 'fixture__away'
    ).filter(fixture__season=season, fixture__match_day__in=unlocked)

    if match_day:
        try:
            match_day_int = int(match_day)
        except ValueError:
            return JsonResponse({'error': 'match_day must be an integer'}, status=400)
        predictions = predictions.filter(fixture__match_day=match_day_int)

    if team:
        predictions = predictions.filter(models_Q_home_or_away(team))

    predictions = list(predictions.order_by('fixture__match_day', 'fixture__id'))
    logos = _logo_urls_for(predictions)

    results = []
    missing_grid = 0
    for p in predictions:
        if not p.scoreline_grid:
            # Predicted before scoreline_grid existed — regenerate to backfill.
            missing_grid += 1
            continue

        grid = np.array(p.scoreline_grid, dtype=float)
        results.append({
            'id': p.id,
            'fixture_id': p.fixture_id,
            'match_day': p.fixture.match_day,
            'home': p.fixture.home.name,
            'away': p.fixture.away.name,
            'home_logo': logos.get(p.fixture.home.name.strip().lower()),
            'away_logo': logos.get(p.fixture.away.name.strip().lower()),
            'home_lambda': p.home_lambda,
            'away_lambda': p.away_lambda,
            'top_scorelines': top_scorelines(grid, 5),
            'markets': goal_markets(grid),
            'grid': p.scoreline_grid,
            # `manually_edited` deliberately omitted — see predictions_api.
        })

    return JsonResponse({
        'count': len(results),
        'results': results,
        'missing_grid': missing_grid,
        'unlocked_match_days': unlocked,
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

