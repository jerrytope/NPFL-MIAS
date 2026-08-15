from django.urls import path, include
from admin_panel import views as admin_views

urlpatterns = [
    path('admin/login/', admin_views.admin_login, name='admin_login'),
    path('admin/logout/', admin_views.admin_logout, name='admin_logout'),
    path('', include('dashboard.urls')),
    path('supercomputer/', include('supercomputer.urls')),
    path('admin/', include('admin_panel.urls')),
]
