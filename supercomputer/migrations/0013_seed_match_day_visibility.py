"""
Seed one MatchDayVisibility row per existing match day.

Match Day 1 starts unlocked so the public page keeps showing something the
moment this ships; every other match day starts locked, and the admin opens
them from the Access Control page when they're ready to publish.
"""

from django.db import migrations

SEASON = '26/27'
INITIALLY_UNLOCKED = {1}


def seed_visibility(apps, schema_editor):
    SeasonFixture = apps.get_model('supercomputer', 'SeasonFixture')
    MatchDayVisibility = apps.get_model('supercomputer', 'MatchDayVisibility')

    match_days = (
        SeasonFixture.objects.filter(season=SEASON)
        .values_list('match_day', flat=True).distinct()
    )

    for match_day in match_days:
        # get_or_create keeps this idempotent — re-running never flips a lock
        # the admin has already set by hand.
        MatchDayVisibility.objects.get_or_create(
            season=SEASON,
            match_day=match_day,
            defaults={'is_unlocked': match_day in INITIALLY_UNLOCKED},
        )


def unseed_visibility(apps, schema_editor):
    """Reversing drops the rows; the model itself goes with migration 0012."""
    MatchDayVisibility = apps.get_model('supercomputer', 'MatchDayVisibility')
    MatchDayVisibility.objects.filter(season=SEASON).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('supercomputer', '0012_matchdayvisibility'),
    ]

    operations = [
        migrations.RunPython(seed_visibility, unseed_visibility),
    ]
