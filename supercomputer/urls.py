from django.urls import path
from supercomputer import views

app_name = 'supercomputer'

urlpatterns = [
    path('', views.index, name='index'),
    path('api/predictions/', views.predictions_api, name='predictions_api'),
]
