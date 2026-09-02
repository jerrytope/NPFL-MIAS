import logging

from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from dashboard import utils
from dashboard.models import TeamComparisonReport
from dashboard.team_logos import get_logo_url_map

logger = logging.getLogger(__name__)


# The clubs eligible for selection in the current 2026/27 NPFL season.
NPFL_CLUBS_2026_2027 = [
    "Abia Warriors",
    "Barau",
    "Bendel Insurance",
    "Doma United",
    "Rangers International",
    "Enyimba",
    "Ikorodu City",
    "Inter Lagos",
    "Kano Pillars",
    "Katsina United",
    "Kun Khalifat",
    "Kwara United",
    "Nasarawa United",
    "Niger Tornadoes",
    "Plateau United",
    "Ranchers Bees",
    "Rivers United",
    "Shooting Stars",
    "Sporting Lagos",
    "Warri Wolves",
]


def canonical_team_pair(team1, team2):
    """Return names in a stable order so A-v-B and B-v-A share a report."""
    return tuple(sorted((team1, team2), key=str.casefold))

def index(request):
    """
    Render main dashboard landing page.
    """
    return render(request, 'dashboard/index.html', {
        'teams': NPFL_CLUBS_2026_2027,
        # Resolved from the files actually on disk (dashboard/team_logos.py)
        # rather than a hardcoded name->filename dict in the JS, which had
        # drifted and served 404s for three clubs on the case-sensitive
        # production filesystem.
        'team_logos': get_logo_url_map(NPFL_CLUBS_2026_2027),
    })

@require_GET
def compare_teams(request):
    """
    JSON API endpoint for fetching comparison stats between two teams.
    """
    team1 = request.GET.get('team1')
    team2 = request.GET.get('team2')
    
    if not team1 or not team2:
        return JsonResponse({'error': 'Two teams must be selected for comparison.'}, status=400)
    
    if team1 == team2:
        return JsonResponse({'error': 'Please select two different teams.'}, status=400)
    
    try:
        data = utils.perform_comparison(team1, team2)
        canonical_team_one, canonical_team_two = canonical_team_pair(team1, team2)
        report_obj = TeamComparisonReport.objects.filter(
            team_one=canonical_team_one,
            team_two=canonical_team_two,
        ).first()
        data['saved_report'] = report_obj.report if report_obj else None
        data['report_ai_generated'] = report_obj.ai_generated if report_obj else None
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({'error': f'Failed to calculate analytics: {str(e)}'}, status=500)

@require_GET
def generate_report(request):
    """
    JSON API endpoint to generate a MIAS analytical preview for the selected teams.
    """
    team1 = request.GET.get('team1')
    team2 = request.GET.get('team2')

    if not team1 or not team2:
        return JsonResponse({'error': 'Two teams must be selected for report generation.'}, status=400)

    if team1 == team2:
        return JsonResponse({'error': 'Please select two different teams.'}, status=400)

    try:
        canonical_team_one, canonical_team_two = canonical_team_pair(team1, team2)
        saved_report = TeamComparisonReport.objects.filter(
            team_one=canonical_team_one,
            team_two=canonical_team_two,
        ).first()
        if saved_report:
            return JsonResponse({'report': saved_report.report, 'cached': True})

        comparison = utils.perform_comparison(team1, team2)
        report_text = utils.generate_expert_report(team1, team2, comparison)
        TeamComparisonReport.objects.create(
            team_one=canonical_team_one,
            team_two=canonical_team_two,
            report=report_text,
        )
        return JsonResponse({'report': report_text, 'cached': False})
    except Exception as e:
        # This endpoint is public and unauthenticated. It used to return the
        # full server traceback in a `debug` key, which handed any visitor the
        # project's file layout and internals — the trace belongs in the server
        # log, and only the short message goes back to the caller.
        logger.exception('Preview generation failed for %s vs %s', team1, team2)
        return JsonResponse(
            {'error': f'Failed to generate preview: {e}'},
            status=500,
        )


@require_GET
def refresh_data(request):
    """
    Re-read the match data and confirm it loads.

    There is no cache to clear any more — every request reads the database
    fresh. The endpoint is kept because the UI calls it, and it still does
    something useful: it surfaces a broken or empty Match table as an error
    instead of leaving the page silently blank.
    """
    try:
        df = utils.get_npfl_data()
        return JsonResponse({
            'status': 'success',
            'message': f'Loaded {len(df):,} matches from the database.'
        })
    except Exception as e:
        return JsonResponse({'error': f'Failed to refresh data: {str(e)}'}, status=500)
