from django.core.management.base import BaseCommand
from django.db import transaction
import pandas as pd

from dashboard.models import Team
from supercomputer.models import TeamCareerStats


def to_int(val, default=0):
    try:
        if pd.isna(val):
            return default
    except Exception:
        pass
    try:
        return int(val)
    except Exception:
        return default


class Command(BaseCommand):
    help = "Import all-time (1990-2026) career stats from the merged NPFL all-time table workbook."

    def add_arguments(self, parser):
        parser.add_argument('--file', '-f', dest='file', required=False,
                            default='plans/npfl all time table.xlsx')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run',
                            help='Run without saving to DB')

    def handle(self, *args, **options):
        path = options['file']
        dry_run = options['dry_run']

        self.stdout.write(f'Reading Excel: {path}')
        df = pd.read_excel(path, sheet_name=0)
        df.columns = [c.strip() for c in df.columns]

        required_cols = [
            'Teams', 'Part', 'Played', 'H win', 'H draw', 'H loss',
            'A win', 'A draw', 'A loss', 'Home GF', 'Home GA', 'Away GF', 'Away GA',
            'Total Win', 'Total Draw', 'Total Loss', 'Total GF', 'Total GA', 'Total GD',
            'Points', 'Rank',
        ]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            self.stderr.write(f'Missing expected column(s): {missing}')
            return

        # Case-insensitive team lookup — reuse the same normalization as import_npfl_excel.py
        existing_teams = {t.name.lower(): t for t in Team.objects.all()}

        created_teams = 0
        updated = 0
        created = 0
        no_home_away_split = []

        with transaction.atomic():
            for _, row in df.iterrows():
                name = str(row['Teams']).strip()
                team = existing_teams.get(name.lower())

                if team is None:
                    if dry_run:
                        # Can't persist a placeholder Team in dry-run; skip stats for it
                        self.stdout.write(f'  [dry-run] would create Team: {name}')
                        continue
                    team = Team.objects.create(name=name)
                    existing_teams[name.lower()] = team
                    created_teams += 1

                if pd.isna(row['H win']):
                    no_home_away_split.append(name)

                defaults = {
                    'parts': to_int(row['Part']),
                    'played': to_int(row['Played']),
                    'home_win': to_int(row['H win']),
                    'home_draw': to_int(row['H draw']),
                    'home_loss': to_int(row['H loss']),
                    'away_win': to_int(row['A win']),
                    'away_draw': to_int(row['A draw']),
                    'away_loss': to_int(row['A loss']),
                    'home_gf': to_int(row['Home GF']),
                    'home_ga': to_int(row['Home GA']),
                    'away_gf': to_int(row['Away GF']),
                    'away_ga': to_int(row['Away GA']),
                    'total_win': to_int(row['Total Win']),
                    'total_draw': to_int(row['Total Draw']),
                    'total_loss': to_int(row['Total Loss']),
                    'total_gf': to_int(row['Total GF']),
                    'total_ga': to_int(row['Total GA']),
                    'total_gd': to_int(row['Total GD']),
                    'points': to_int(row['Points']),
                    'source_rank': to_int(row['Rank'], default=None),
                }

                if dry_run:
                    continue

                obj, was_created = TeamCareerStats.objects.update_or_create(
                    team=team, defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            f'Import finished. Teams created: {created_teams}, '
            f'TeamCareerStats created: {created}, updated: {updated}'
        )
        if no_home_away_split:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'{len(no_home_away_split)} team(s) with no home/away split (pre-2002-only clubs — '
                f'Total W/D/L still populated):'
            ))
            for n in no_home_away_split:
                self.stdout.write(f'  - {n}')
