import traceback
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from dashboard import utils
from dashboard.models import TeamComparisonReport


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
    return render(request, 'dashboard/index.html', {'teams': NPFL_CLUBS_2026_2027})

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
    JSON API endpoint to generate a BBC-style expert report for the selected teams.
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
        error_trace = traceback.format_exc()
        return JsonResponse(
            {
                'error': f'Failed to generate report: {str(e)}',
                'debug': error_trace,
            },
            status=500,
        )


@require_GET
def refresh_data(request):
    """
    JSON API endpoint to refresh the cached DB-derived NPFL data.
    """
    try:
        utils.get_npfl_data(force_refresh=True)
        return JsonResponse({
            'status': 'success',
            'message': 'Database-derived NPFL cache refreshed successfully!'
        })
    except Exception as e:
        return JsonResponse({'error': f'Failed to refresh data: {str(e)}'}, status=500)
