from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from dashboard import utils

def index(request):
    """
    Render main dashboard landing page.
    """
    teams = utils.get_unique_teams()
    return render(request, 'dashboard/index.html', {'teams': teams})

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
def refresh_data(request):
    """
    JSON API endpoint to purge the cached Google Sheets data and fetch fresh records.
    """
    try:
        utils.get_npfl_data(force_refresh=True)
        return JsonResponse({
            'status': 'success',
            'message': 'Google Sheets data synchronized and cache updated successfully!'
        })
    except Exception as e:
        return JsonResponse({'error': f'Failed to refresh data: {str(e)}'}, status=500)
