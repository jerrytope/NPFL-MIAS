import json

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Prefetch

from dashboard.utils import get_npfl_data
from supercomputer.models import SeasonFixture, PredictionSnapshot, Prediction
from supercomputer.predictor import predict_all_fixtures


def index(request):
    """Render the Super Computer dashboard."""
    latest_snapshot = PredictionSnapshot.objects.filter(
        season='26/27', is_latest=True
    ).first()

    snapshots = PredictionSnapshot.objects.filter(season='26/27').order_by('-created_at')

    context = {
        'latest_snapshot': latest_snapshot,
        'snapshots': snapshots,
    }
    return render(request, 'supercomputer/index.html', context)


def predictions_api(request):
    """
    JSON API — predictions from latest or specified snapshot.

    Query params:
        ?match_day=5     — filter by fixture match day (1-38)
        ?team=Enyimba    — filter by team name
        ?snapshot=3      — view predictions from a specific snapshot ID
        ?season=26/27    — season (default: 26/27)
    """
    season = request.GET.get('season', '26/27')
    snapshot_id = request.GET.get('snapshot')
    match_day = request.GET.get('match_day')
    team = request.GET.get('team')

    # Get snapshot
    if snapshot_id:
        try:
            snapshot = PredictionSnapshot.objects.get(id=snapshot_id, season=season)
        except PredictionSnapshot.DoesNotExist:
            return JsonResponse({'error': f'Snapshot {snapshot_id} not found'}, status=404)
    else:
        snapshot = PredictionSnapshot.objects.filter(
            season=season, is_latest=True
        ).first()
        if not snapshot:
            return JsonResponse({'results': [], 'snapshot': None, 'message': 'No predictions available yet'})

    # Build query
    predictions = Prediction.objects.filter(snapshot=snapshot).select_related(
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

    # Serialise
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
        })

    return JsonResponse({
        'snapshot': {
            'id': snapshot.id,
            'version_label': snapshot.version_label,
            'match_day_computed': snapshot.match_day_computed,
            'created_at': snapshot.created_at.isoformat(),
            'is_latest': snapshot.is_latest,
        },
        'count': len(results),
        'results': results,
    })


def models_Q_home_or_away(team):
    """Return a Q object that matches fixtures where team is home or away."""
    from django.db.models import Q
    return Q(fixture__home__name=team) | Q(fixture__away__name=team)


def snapshots_api(request):
    """JSON API — list all available prediction snapshots."""
    season = request.GET.get('season', '26/27')

    snapshots = PredictionSnapshot.objects.filter(season=season).order_by('-created_at')

    data = []
    for s in snapshots:
        data.append({
            'id': s.id,
            'version_label': s.version_label,
            'match_day_computed': s.match_day_computed,
            'created_at': s.created_at.isoformat(),
            'is_latest': s.is_latest,
            'notes': s.notes,
            'prediction_count': s.predictions.count(),
        })

    return JsonResponse({'snapshots': data})


@require_POST
def recalculate(request):
    """POST — create new snapshot with fresh predictions."""
    season = request.POST.get('season', '26/27')
    label = request.POST.get('label', 'Recalculated')
    match_day = int(request.POST.get('match_day', 0))
    notes = request.POST.get('notes', '')

    # Load fixtures
    fixtures = SeasonFixture.objects.filter(season=season).select_related('home', 'away')
    if not fixtures.exists():
        return JsonResponse({'error': f'No fixtures found for season {season}'}, status=400)

    # Load historical data
    try:
        df = get_npfl_data(force_refresh=True)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    # Run predictions
    results = predict_all_fixtures(fixtures, df)

    # Create snapshot
    from django.db import transaction
    with transaction.atomic():
        PredictionSnapshot.objects.filter(
            season=season, is_latest=True
        ).update(is_latest=False)

        snapshot = PredictionSnapshot.objects.create(
            season=season,
            version_label=label,
            match_day_computed=match_day,
            is_latest=True,
            notes=notes,
        )

        predictions = []
        for result in results:
            predictions.append(Prediction(
                snapshot=snapshot,
                fixture=result['fixture'],
                home_win_pct=result['home_win_pct'],
                draw_pct=result['draw_pct'],
                away_win_pct=result['away_win_pct'],
                predicted_result=result['predicted_result'],
                confidence=result['confidence'],
                home_form_score=result['home_form_score'],
                away_form_score=result['away_form_score'],
                h2h_home_rate=result['h2h_home_rate'],
                h2h_draw_rate=result['h2h_draw_rate'],
                h2h_away_rate=result['h2h_away_rate'],
                home_venue_strength=result['home_venue_strength'],
                away_venue_strength=result['away_venue_strength'],
            ))

        Prediction.objects.bulk_create(predictions)

    home_wins = sum(1 for r in results if r['predicted_result'] == 'HOME')
    draws = sum(1 for r in results if r['predicted_result'] == 'DRAW')
    away_wins = sum(1 for r in results if r['predicted_result'] == 'AWAY')

    return JsonResponse({
        'message': f'Snapshot "{label}" created with {len(predictions)} predictions',
        'snapshot': {
            'id': snapshot.id,
            'version_label': snapshot.version_label,
            'match_day_computed': snapshot.match_day_computed,
            'is_latest': snapshot.is_latest,
        },
        'summary': {
            'total': len(predictions),
            'home_wins': home_wins,
            'draws': draws,
            'away_wins': away_wins,
        }
    })
