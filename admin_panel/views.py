import json
import os

import pandas as pd
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST, require_http_methods

from dashboard.models import Team, TeamComparisonReport, Match
from dashboard.utils import get_npfl_data, perform_comparison, generate_expert_report, get_team_home_away_splits, get_all_seasons
from dashboard.views import NPFL_CLUBS_2026_2027, canonical_team_pair
from supercomputer.models import (
    SeasonFixture, Prediction, MatchAnalysisReport, MatchDayVisibility,
)
from supercomputer.predictor import predict_all_fixtures
from supercomputer.standings import calculate_standings, get_prediction_breakdown


SEASON = '26/27'


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

def admin_login(request):
    """Custom login page for admin panel."""
    if request.user.is_authenticated:
        return redirect('admin_panel:dashboard')
    
    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', 'admin_panel:dashboard')
            return redirect(next_url)
        else:
            error = 'Invalid username or password.'
    
    return render(request, 'admin_panel/login.html', {'error': error})


def admin_logout(request):
    """Logout and redirect to login page."""
    logout(request)
    return redirect('admin_login')


def _apply_calibration(results):
    """Ensure percentages sum to exactly 100.0%."""
    for r in results:
        total = r['home_win_pct'] + r['draw_pct'] + r['away_win_pct']
        diff = round(100.0 - total, 1)
        if abs(diff) > 0.01:
            r['home_win_pct'] = round(r['home_win_pct'] + diff, 1)

        pcts = {'HOME': r['home_win_pct'], 'DRAW': r['draw_pct'], 'AWAY': r['away_win_pct']}
        r['predicted_result'] = max(pcts, key=pcts.get)
        r['confidence'] = pcts[r['predicted_result']]
    return results


def _build_predictions_data(queryset):
    """Build a list of prediction dicts from a queryset."""
    data = []
    for p in queryset.select_related('fixture', 'fixture__home', 'fixture__away').order_by('fixture__match_day', 'fixture__id'):
        data.append({
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
            'manually_edited': p.manually_edited,
        })
    return data


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    """Admin panel landing page with summary stats."""
    fixture_count = SeasonFixture.objects.filter(season=SEASON).count()
    prediction_count = Prediction.objects.filter(fixture__season=SEASON).count()
    edited_count = Prediction.objects.filter(fixture__season=SEASON, manually_edited=True).count()

    match_days = (
        SeasonFixture.objects.filter(season=SEASON)
        .values_list('match_day', flat=True)
        .distinct()
        .order_by('match_day')
    )

    context = {
        'fixture_count': fixture_count,
        'prediction_count': prediction_count,
        'edited_count': edited_count,
        'match_day_count': len(match_days),
    }
    return render(request, 'admin_panel/dashboard.html', context)


# ---------------------------------------------------------------------------
# Feature 1 & 2: Predictions
# ---------------------------------------------------------------------------

@login_required
def predictions(request):
    """List all predictions with inline-edit support."""
    preds = Prediction.objects.filter(fixture__season=SEASON)
    predictions_data = _build_predictions_data(preds)
    match_days = sorted(set(p['match_day'] for p in predictions_data))

    # All match days available for regeneration
    all_match_days = sorted(
        SeasonFixture.objects.filter(season=SEASON)
        .values_list('match_day', flat=True)
        .distinct()
    )

    context = {
        'predictions_data': predictions_data,
        'match_days': match_days,
        'all_match_days': all_match_days,
        'has_predictions': len(predictions_data) > 0,
    }
    return render(request, 'admin_panel/predictions.html', context)


@require_http_methods(["PUT", "POST"])
@login_required
def prediction_update(request, prediction_id):
    """API: update a single prediction's percentages."""
    try:
        body = json.loads(request.body) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    try:
        pred = Prediction.objects.select_related(
            'fixture', 'fixture__home', 'fixture__away'
        ).get(id=prediction_id)
    except Prediction.DoesNotExist:
        return JsonResponse({'error': 'Prediction not found'}, status=404)

    home_pct = float(body.get('home_win_pct', pred.home_win_pct))
    draw_pct = float(body.get('draw_pct', pred.draw_pct))
    away_pct = float(body.get('away_win_pct', pred.away_win_pct))

    # Clamp
    home_pct = max(0, min(100, home_pct))
    draw_pct = max(0, min(100, draw_pct))
    away_pct = max(0, min(100, away_pct))

    # Normalise to 100
    total = home_pct + draw_pct + away_pct
    if total <= 0:
        return JsonResponse({'error': 'Percentages must be positive'}, status=400)

    if abs(total - 100) > 0.5:
        factor = 100.0 / total
        home_pct = round(home_pct * factor, 1)
        draw_pct = round(draw_pct * factor, 1)
        away_pct = round(away_pct * factor, 1)

    # Fix rounding
    home_pct = round(home_pct, 1)
    draw_pct = round(draw_pct, 1)
    away_pct = round(away_pct, 1)
    diff = round(100.0 - (home_pct + draw_pct + away_pct), 1)
    if abs(diff) > 0:
        max_val = max(home_pct, draw_pct, away_pct)
        if max_val == home_pct:
            home_pct = round(home_pct + diff, 1)
        elif max_val == away_pct:
            away_pct = round(away_pct + diff, 1)
        else:
            draw_pct = round(draw_pct + diff, 1)

    percentages = {'HOME': home_pct, 'DRAW': draw_pct, 'AWAY': away_pct}
    predicted_result = max(percentages, key=percentages.get)
    confidence = percentages[predicted_result]

    pred.home_win_pct = home_pct
    pred.draw_pct = draw_pct
    pred.away_win_pct = away_pct
    pred.predicted_result = predicted_result
    pred.confidence = confidence
    pred.manually_edited = True
    pred.save()

    return JsonResponse({
        'id': pred.id,
        'home_win_pct': home_pct,
        'draw_pct': draw_pct,
        'away_win_pct': away_pct,
        'predicted_result': predicted_result,
        'confidence': confidence,
        'manually_edited': True,
    })


@require_POST
@login_required
def generate_predictions(request):
    """Generate or regenerate predictions starting from a given match day."""
    start_match_day = int(request.POST.get('start_match_day', 1))
    mode = request.POST.get('mode', 'all')  # 'all' or 'from_md'

    fixtures = SeasonFixture.objects.filter(season=SEASON).select_related('home', 'away')
    if not fixtures.exists():
        return JsonResponse({'error': 'No fixtures found for this season'}, status=400)

    if mode == 'from_md':
        # Only regenerate from start_match_day onwards, leave earlier predictions untouched
        fixtures_to_predict = fixtures.filter(match_day__gte=start_match_day)
    else:
        # Regenerate all — delete existing predictions first
        fixtures_to_predict = fixtures
        Prediction.objects.filter(fixture__season=SEASON).delete()

    try:
        df = get_npfl_data(force_refresh=True)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    results = predict_all_fixtures(fixtures_to_predict, df)
    results = _apply_calibration(results)

    created = 0
    updated = 0
    with transaction.atomic():
        for r in results:
            obj, was_created = Prediction.objects.update_or_create(
                fixture=r['fixture'],
                defaults={
                    'home_win_pct': r['home_win_pct'],
                    'draw_pct': r['draw_pct'],
                    'away_win_pct': r['away_win_pct'],
                    'predicted_result': r['predicted_result'],
                    'confidence': r['confidence'],
                    'home_lambda': r['home_lambda'],
                    'away_lambda': r['away_lambda'],
                    'home_attack': r['home_attack'],
                    'home_defense': r['home_defense'],
                    'away_attack': r['away_attack'],
                    'away_defense': r['away_defense'],
                    'home_transfer_score': r.get('home_transfer_score', 0),
                    'away_transfer_score': r.get('away_transfer_score', 0),
                    'scoreline_grid': r.get('scoreline_grid'),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

    all_preds = Prediction.objects.filter(fixture__season=SEASON)
    total_preds = all_preds.count()
    # Expected values (sum of each match's probability), not a count of how
    # often that outcome is the single most-likely pick — see script.js's
    # updateStats() for why that distinction matters in a home-dominant league.
    home_wins = round(sum(p.home_win_pct for p in all_preds) / 100)
    draws = round(sum(p.draw_pct for p in all_preds) / 100)
    away_wins = round(sum(p.away_win_pct for p in all_preds) / 100)

    return JsonResponse({
        'message': f'Generated {created + updated} predictions ({created} new, {updated} updated)',
        'summary': {
            'total': total_preds,
            'home_wins': home_wins,
            'draws': draws,
            'away_wins': away_wins,
            'generated': created + updated,
        },
    })


# ---------------------------------------------------------------------------
# Feature 3: Fixtures
# ---------------------------------------------------------------------------

@login_required
def fixtures(request):
    """Show current fixtures and upload form."""
    season_fixtures = (
        SeasonFixture.objects.filter(season=SEASON)
        .select_related('home', 'away')
        .order_by('match_day', 'id')
    )

    grouped = {}
    for f in season_fixtures:
        grouped.setdefault(f.match_day, []).append(f)

    context = {
        'grouped_fixtures': grouped,
        'fixture_count': season_fixtures.count(),
        'season': SEASON,
    }
    return render(request, 'admin_panel/fixtures.html', context)


# ---------------------------------------------------------------------------
# Access Control — which match days are public
# ---------------------------------------------------------------------------

@login_required
def match_day_access(request):
    """
    Publish/unpublish each match day's predictions and scorelines.

    A locked match day is absent from the public API entirely, so it can't be
    reached from /supercomputer/ by any filter. This replaced an automatic
    rule that unlocked a match day once the previous one's results had been
    entered — publishing is an editorial decision, not a side effect of
    bookkeeping.
    """
    match_days = sorted(
        SeasonFixture.objects.filter(season=SEASON)
        .values_list('match_day', flat=True).distinct()
    )

    # Any match day without a row yet (e.g. freshly imported fixtures) is
    # created locked, so a new import is never public by accident.
    existing = {
        v.match_day: v
        for v in MatchDayVisibility.objects.filter(season=SEASON)
    }
    for md in match_days:
        if md not in existing:
            existing[md] = MatchDayVisibility.objects.create(
                season=SEASON, match_day=md, is_unlocked=False,
            )

    fixtures = SeasonFixture.objects.filter(season=SEASON)
    rows = []
    for md in match_days:
        md_fixtures = [f for f in fixtures if f.match_day == md]
        rows.append({
            'match_day': md,
            'fixture_count': len(md_fixtures),
            'played_count': sum(1 for f in md_fixtures if f.is_played),
            'is_unlocked': existing[md].is_unlocked,
        })

    unlocked_count = sum(1 for r in rows if r['is_unlocked'])

    return render(request, 'admin_panel/match_day_access.html', {
        'rows': rows,
        'season': SEASON,
        'unlocked_count': unlocked_count,
        'locked_count': len(rows) - unlocked_count,
        'total_count': len(rows),
    })


@require_POST
@login_required
def match_day_visibility_update(request, match_day):
    """API: lock or unlock one match day."""
    try:
        body = json.loads(request.body) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    is_unlocked = body.get('is_unlocked')
    if isinstance(is_unlocked, str):
        is_unlocked = is_unlocked.lower() in ('true', '1', 'yes')
    if is_unlocked is None:
        return JsonResponse({'error': 'is_unlocked is required'}, status=400)

    if not SeasonFixture.objects.filter(season=SEASON, match_day=match_day).exists():
        return JsonResponse({'error': f'No fixtures for match day {match_day}'}, status=404)

    visibility, _ = MatchDayVisibility.objects.update_or_create(
        season=SEASON, match_day=match_day,
        defaults={'is_unlocked': bool(is_unlocked)},
    )

    return JsonResponse({
        'match_day': visibility.match_day,
        'is_unlocked': visibility.is_unlocked,
        'unlocked_count': MatchDayVisibility.objects.filter(season=SEASON, is_unlocked=True).count(),
    })


@require_POST
@login_required
def match_day_visibility_bulk(request):
    """API: lock or unlock every match day at once."""
    try:
        body = json.loads(request.body) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    action = str(body.get('action', '')).lower()
    if action not in ('lock_all', 'unlock_all'):
        return JsonResponse({'error': "action must be 'lock_all' or 'unlock_all'"}, status=400)

    unlock = action == 'unlock_all'
    match_days = sorted(
        SeasonFixture.objects.filter(season=SEASON)
        .values_list('match_day', flat=True).distinct()
    )

    with transaction.atomic():
        for md in match_days:
            MatchDayVisibility.objects.update_or_create(
                season=SEASON, match_day=md, defaults={'is_unlocked': unlock},
            )

    return JsonResponse({
        'action': action,
        'affected': len(match_days),
        'unlocked_count': len(match_days) if unlock else 0,
    })


@require_http_methods(["PUT", "POST"])
@login_required
def fixture_result_update(request, fixture_id):
    """
    API: record (or clear) a fixture's actual result. Mirrors the result into
    a Match row so the prediction engine picks it up as real recent form on
    the next regeneration — SeasonFixture itself is not read by predictor.py.
    """
    try:
        body = json.loads(request.body) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    fixture = get_object_or_404(SeasonFixture.objects.select_related('home', 'away'), id=fixture_id)

    home_goal_raw = body.get('home_goal')
    away_goal_raw = body.get('away_goal')

    match_query = {'season': fixture.season, 'home': fixture.home, 'away': fixture.away}

    if home_goal_raw is None and away_goal_raw is None:
        # Clear the result — the fixture reverts to "upcoming"
        fixture.home_goal = None
        fixture.away_goal = None
        fixture.save(update_fields=['home_goal', 'away_goal'])
        Match.objects.filter(**match_query).delete()
        return JsonResponse({
            'id': fixture.id, 'is_played': False, 'home_goal': None, 'away_goal': None,
        })

    if home_goal_raw is None or away_goal_raw is None:
        return JsonResponse({'error': 'Both home_goal and away_goal are required (or both omitted to clear)'}, status=400)

    try:
        home_goal = int(home_goal_raw)
        away_goal = int(away_goal_raw)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Scores must be integers'}, status=400)

    if home_goal < 0 or away_goal < 0:
        return JsonResponse({'error': 'Scores cannot be negative'}, status=400)

    with transaction.atomic():
        fixture.home_goal = home_goal
        fixture.away_goal = away_goal
        fixture.save(update_fields=['home_goal', 'away_goal'])

        Match.objects.update_or_create(
            **match_query,
            defaults={
                'match_name': f'{fixture.home.name} vs {fixture.away.name}',
                'home_goal': home_goal,
                'away_goal': away_goal,
                'source': 'admin_entry',
            },
        )

    return JsonResponse({
        'id': fixture.id, 'is_played': True, 'home_goal': home_goal, 'away_goal': away_goal,
    })


@require_POST
@login_required
def preview_fixtures(request):
    """API: parse uploaded file and return preview data."""
    uploaded = request.FILES.get('file')
    if not uploaded:
        return JsonResponse({'error': 'No file uploaded'}, status=400)

    home_col = request.POST.get('home_col', 'home')
    away_col = request.POST.get('away_col', 'away')
    md_col = request.POST.get('md_col', 'match_day')

    ext = os.path.splitext(uploaded.name)[1].lower()
    try:
        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(uploaded)
        elif ext == '.csv':
            df = pd.read_csv(uploaded)
        else:
            return JsonResponse({'error': 'Unsupported format. Use .xlsx, .xls, or .csv'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Failed to read file: {e}'}, status=400)

    missing = [c for c in [md_col, home_col, away_col] if c not in df.columns]
    if missing:
        return JsonResponse({
            'error': f'Missing columns: {missing}. Found: {list(df.columns)}'
        }, status=400)

    rows = []
    unknown_teams = set()
    for _, row in df.iterrows():
        try:
            md = int(row[md_col])
        except (ValueError, TypeError):
            continue
        home = str(row[home_col]).strip()
        away = str(row[away_col]).strip()

        if home not in NPFL_CLUBS_2026_2027:
            unknown_teams.add(home)
        if away not in NPFL_CLUBS_2026_2027:
            unknown_teams.add(away)

        rows.append({'match_day': md, 'home': home, 'away': away})

    return JsonResponse({
        'rows': rows,
        'total': len(rows),
        'unknown_teams': sorted(unknown_teams),
        'match_days': sorted(set(r['match_day'] for r in rows)),
    })


@require_POST
@login_required
def confirm_import(request):
    """API: commit parsed fixture data to the database."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    rows = body.get('rows', [])
    mode = body.get('mode', 'append')
    season = body.get('season', SEASON)

    if not rows:
        return JsonResponse({'error': 'No fixture data provided'}, status=400)

    if mode == 'replace':
        SeasonFixture.objects.filter(season=season).delete()

    team_names = set()
    for r in rows:
        team_names.add(r['home'])
        team_names.add(r['away'])

    team_cache = {}
    for name in team_names:
        team, _ = Team.objects.get_or_create(name=name)
        team_cache[name] = team

    created = 0
    skipped = 0
    with transaction.atomic():
        for r in rows:
            home = team_cache.get(r['home'])
            away = team_cache.get(r['away'])
            if not home or not away:
                skipped += 1
                continue

            exists = SeasonFixture.objects.filter(
                season=season, match_day=r['match_day'], home=home, away=away
            ).exists()
            if exists:
                skipped += 1
                continue

            SeasonFixture.objects.create(
                season=season,
                match_day=r['match_day'],
                home=home,
                away=away,
            )
            created += 1

    return JsonResponse({
        'created': created,
        'skipped': skipped,
        'total_parsed': len(rows),
    })


# ---------------------------------------------------------------------------
# Feature 4: Match Reports
# ---------------------------------------------------------------------------

@login_required
def reports(request):
    """List all fixtures with their report status."""
    all_fixtures = (
        SeasonFixture.objects.filter(season=SEASON)
        .select_related('home', 'away')
        .order_by('match_day', 'id')
    )

    if not all_fixtures.exists():
        return render(request, 'admin_panel/reports.html', {
            'grouped_reports': {},
            'has_fixtures': False,
            'match_days': [],
        })

    grouped = {}
    for f in all_fixtures:
        md = f.match_day
        if md not in grouped:
            grouped[md] = []

        try:
            report = f.analysis_report
            report_text = report.report
            ai_generated = report.ai_generated
        except MatchAnalysisReport.DoesNotExist:
            report_text = ''
            ai_generated = False

        status = 'empty'
        if report_text:
            status = 'ai' if ai_generated else 'written'

        grouped[md].append({
            'fixture_id': f.id,
            'home': f.home.name,
            'away': f.away.name,
            'report_text': report_text,
            'status': status,
        })

    match_days = sorted(grouped.keys())

    context = {
        'grouped_reports': grouped,
        'has_fixtures': True,
        'match_days': match_days,
    }
    return render(request, 'admin_panel/reports.html', context)


@require_http_methods(["PUT", "POST"])
@login_required
def report_update(request, fixture_id):
    """API: save/update report text for a fixture."""
    try:
        body = json.loads(request.body) if request.body else request.POST
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    fixture = get_object_or_404(SeasonFixture.objects.select_related('home', 'away'), id=fixture_id)
    report_text = body.get('report', '')

    obj, created = MatchAnalysisReport.objects.update_or_create(
        fixture=fixture,
        defaults={
            'report': report_text,
            'ai_generated': False,
        },
    )

    # Sync to TeamComparisonReport for dashboard display
    team1 = fixture.home.name
    team2 = fixture.away.name
    canonical_one, canonical_two = canonical_team_pair(team1, team2)
    TeamComparisonReport.objects.update_or_create(
        team_one=canonical_one,
        team_two=canonical_two,
        defaults={'report': report_text, 'ai_generated': False},
    )

    return JsonResponse({
        'id': obj.id,
        'fixture_id': fixture.id,
        'report': obj.report,
        'ai_generated': obj.ai_generated,
        'status': 'written',
    })


@require_POST
@login_required
def report_generate(request, fixture_id):
    """API: AI-generate a report for a fixture's team pair."""
    fixture = get_object_or_404(
        SeasonFixture.objects.select_related('home', 'away'),
        id=fixture_id,
    )

    team1 = fixture.home.name
    team2 = fixture.away.name

    try:
        comparison = perform_comparison(team1, team2)
        report_text = generate_expert_report(team1, team2, comparison)
    except Exception as e:
        return JsonResponse({'error': f'Failed to generate report: {e}'}, status=500)

    obj, created = MatchAnalysisReport.objects.update_or_create(
        fixture=fixture,
        defaults={
            'report': report_text,
            'ai_generated': True,
        },
    )

    canonical_one, canonical_two = canonical_team_pair(team1, team2)
    TeamComparisonReport.objects.update_or_create(
        team_one=canonical_one,
        team_two=canonical_two,
        defaults={'report': report_text, 'ai_generated': True},
    )

    return JsonResponse({
        'id': obj.id,
        'fixture_id': fixture.id,
        'report': obj.report,
        'ai_generated': obj.ai_generated,
        'status': 'ai',
    })


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

@login_required
def standings(request):
    """Predicted league standings with optional match day filter."""
    max_md = request.GET.get('match_day')
    max_match_day = None
    if max_md:
        try:
            max_match_day = int(max_md)
        except ValueError:
            pass

    all_match_days = list(
        SeasonFixture.objects.filter(season=SEASON)
        .values_list('match_day', flat=True)
        .distinct()
        .order_by('match_day')
    )

    standings_data = calculate_standings(SEASON, max_match_day=max_match_day)
    return render(request, 'admin_panel/standings.html', {
        'standings': standings_data,
        'all_match_days': all_match_days,
        'selected_md': max_match_day,
    })


@login_required
def team_splits(request):
    """Real home/away Played/Win/Draw/Loss breakdown per team, from completed matches."""
    season = request.GET.get('season') or None
    splits = get_team_home_away_splits(season=season)
    return render(request, 'admin_panel/team_splits.html', {
        'splits': splits,
        'all_seasons': get_all_seasons(),
        'selected_season': season,
    })


@login_required
def prediction_breakdown(request):
    """Per-team expected home/away W/D/L, with each fixture's opponent and
    the model's per-match favorite (win/draw/loss) grouped for browsing."""
    breakdown = get_prediction_breakdown(SEASON)

    for row in breakdown:
        fixtures = (
            [dict(f, venue='H') for f in row['home_fixtures']]
            + [dict(f, venue='A') for f in row['away_fixtures']]
        )
        fixtures.sort(key=lambda f: f['match_day'])

        likely_wins, likely_draws, likely_losses = [], [], []
        for f in fixtures:
            best = max(f['win_pct'], f['draw_pct'], f['loss_pct'])
            if f['win_pct'] == best:
                likely_wins.append(f)
            elif f['draw_pct'] == best:
                likely_draws.append(f)
            else:
                likely_losses.append(f)

        row['likely_wins'] = likely_wins
        row['likely_draws'] = likely_draws
        row['likely_losses'] = likely_losses

    return render(request, 'admin_panel/prediction_breakdown.html', {
        'breakdown': breakdown,
        'season': SEASON,
    })
