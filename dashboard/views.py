import traceback
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from dashboard import utils


# The clubs eligible for selection in the current 2026/27 NPFL season.
NPFL_CLUBS_2026_2027 = [
    "Abia Warriors",
    "Barau",
    "Bendel Insurance",
    "Doma United",
    "Enugu Rangers",
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
        comparison = utils.perform_comparison(team1, team2)
        report_text = utils.generate_expert_report(team1, team2, comparison)
        return JsonResponse({'report': report_text})
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
