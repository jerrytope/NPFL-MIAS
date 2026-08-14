from django.urls import path
from supercomputer import views

app_name = 'supercomputer'

urlpatterns = [
    path('', views.index, name='index'),
    path('api/predictions/', views.predictions_api, name='predictions_api'),
    path('api/snapshots/', views.snapshots_api, name='snapshots_api'),
    path('api/recalculate/', views.recalculate, name='recalculate'),
]
