from django.urls import path
from admin_panel import views

app_name = 'admin_panel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('predictions/', views.predictions, name='predictions'),
    path('predictions/generate/', views.generate_predictions, name='generate_predictions'),
    path('api/predictions/<int:prediction_id>/', views.prediction_update, name='prediction_update'),
    path('access/', views.match_day_access, name='match_day_access'),
    path('api/match-day/<int:match_day>/visibility/', views.match_day_visibility_update, name='match_day_visibility_update'),
    path('api/match-day/visibility/bulk/', views.match_day_visibility_bulk, name='match_day_visibility_bulk'),
    path('fixtures/', views.fixtures, name='fixtures'),
    path('fixtures/preview/', views.preview_fixtures, name='preview_fixtures'),
    path('fixtures/confirm/', views.confirm_import, name='confirm_import'),
    path('api/fixtures/<int:fixture_id>/result/', views.fixture_result_update, name='fixture_result_update'),
    path('reports/', views.reports, name='reports'),
    path('standings/', views.standings, name='standings'),
    path('team-splits/', views.team_splits, name='team_splits'),
    path('prediction-breakdown/', views.prediction_breakdown, name='prediction_breakdown'),
    path('api/reports/<int:fixture_id>/', views.report_update, name='report_update'),
    path('api/reports/<int:fixture_id>/generate/', views.report_generate, name='report_generate'),
]
