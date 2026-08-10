import os
import sys
import django

# Ensure project root is on path so DJANGO_SETTINGS_MODULE imports correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'npfl_project.settings')
django.setup()
from dashboard.models import Team, Match


print('TEAMS:', Team.objects.count())
print('MATCHES:', Match.objects.count())
