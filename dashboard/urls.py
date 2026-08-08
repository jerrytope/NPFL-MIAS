from django.urls import path
from dashboard import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.index, name='index'),
    path('compare/', views.compare_teams, name='compare_teams'),
    path('refresh/', views.refresh_data, name='refresh_data'),
]
