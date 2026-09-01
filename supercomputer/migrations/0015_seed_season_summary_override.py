"""
Seed the initial SeasonSummaryOverride row for the 26/27 season.

Freezes the public "Season Games / Home Wins / Draws / Away Wins" card at the
numbers it showed in production before this override existed, with the
override active by default — the admin can toggle it off later from the
Season Summary page to go back to the live-computed totals.
"""

from django.db import migrations

SEASON = '26/27'


def seed_override(apps, schema_editor):
    SeasonSummaryOverride = apps.get_model('supercomputer', 'SeasonSummaryOverride')
    SeasonSummaryOverride.objects.get_or_create(
        season=SEASON,
        defaults={
            'is_active': True,
            'games': 380,
            'home_wins': 236,
            'draws': 97,
            'away_wins': 47,
        },
    )


def unseed_override(apps, schema_editor):
    SeasonSummaryOverride = apps.get_model('supercomputer', 'SeasonSummaryOverride')
    SeasonSummaryOverride.objects.filter(season=SEASON).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('supercomputer', '0014_seasonsummaryoverride'),
    ]

    operations = [
        migrations.RunPython(seed_override, unseed_override),
    ]
