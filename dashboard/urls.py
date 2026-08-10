from django.urls import path
from dashboard import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.index, name='index'),
    path('compare/', views.compare_teams, name='compare_teams'),
    path('generate-report/', views.generate_report, name='generate_report'),
    path('refresh/', views.refresh_data, name='refresh_data'),
]
