from django.urls import path
from admin_panel import views

app_name = 'admin_panel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('predictions/', views.predictions, name='predictions'),
    path('predictions/generate/', views.generate_predictions, name='generate_predictions'),
    path('api/predictions/<int:prediction_id>/', views.prediction_update, name='prediction_update'),
    path('fixtures/', views.fixtures, name='fixtures'),
    path('fixtures/preview/', views.preview_fixtures, name='preview_fixtures'),
    path('fixtures/confirm/', views.confirm_import, name='confirm_import'),
    path('reports/', views.reports, name='reports'),
    path('standings/', views.standings, name='standings'),
    path('api/reports/<int:fixture_id>/', views.report_update, name='report_update'),
    path('api/reports/<int:fixture_id>/generate/', views.report_generate, name='report_generate'),
]
