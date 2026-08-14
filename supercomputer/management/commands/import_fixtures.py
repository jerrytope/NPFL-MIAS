import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
import pandas as pd

from dashboard.models import Team
from supercomputer.models import SeasonFixture


class Command(BaseCommand):
    help = 'Import fixtures from an Excel/CSV file (replaces auto-generated fixtures)'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, required=True,
                            help='Path to the fixture file (Excel or CSV)')
        parser.add_argument('--season', type=str, default='26/27',
                            help='Season identifier (default: 26/27)')
        parser.add_argument('--home-col', type=str, default='home',
                            help='Column name for home team (default: home)')
        parser.add_argument('--away-col', type=str, default='away',
                            help='Column name for away team (default: away)')
        parser.add_argument('--md-col', type=str, default='match_day',
                            help='Column name for match day (default: match_day)')
        parser.add_argument('--force', action='store_true',
                            help='Clear existing fixtures without confirmation')

    def handle(self, *args, **options):
        file_path = options['file']
        season = options['season']
        home_col = options['home_col']
        away_col = options['away_col']
        md_col = options['md_col']
        force = options['force']

        # Validate file exists
        if not os.path.exists(file_path):
            raise CommandError(f'File not found: {file_path}')

        # Check for existing fixtures
        existing = SeasonFixture.objects.filter(season=season).count()
        if existing > 0 and not force:
            raise CommandError(
                f'{existing} fixtures already exist for season {season}. '
                f'Use --force to replace them.'
            )

        # Read file
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path)
        elif ext == '.csv':
            df = pd.read_csv(file_path)
        else:
            raise CommandError(f'Unsupported file format: {ext}. Use .xlsx, .xls, or .csv')

        # Validate required columns
        missing = [c for c in [md_col, home_col, away_col] if c not in df.columns]
        if missing:
            raise CommandError(
                f'Missing columns: {missing}. '
                f'Found columns: {list(df.columns)}'
            )

        # Clean data
        df[md_col] = df[md_col].astype(int)
        df[home_col] = df[home_col].astype(str).str.strip()
        df[away_col] = df[away_col].astype(str).str.strip()

        # Build team cache
        team_names = set(df[home_col].tolist() + df[away_col].tolist())
        team_cache = {}
        for name in team_names:
            team, created = Team.objects.get_or_create(name=name)
            team_cache[name] = team
            if created:
                self.stdout.write(f'  Created team: {name}')

        # Clear existing fixtures if --force
        if existing > 0 and force:
            self.stdout.write(self.style.WARNING(
                f'Clearing {existing} existing fixtures for season {season}...'
            ))
            SeasonFixture.objects.filter(season=season).delete()

        # Create fixtures
        created_count = 0
        with transaction.atomic():
            for _, row in df.iterrows():
                SeasonFixture.objects.create(
                    season=season,
                    match_day=int(row[md_col]),
                    home=team_cache[row[home_col]],
                    away=team_cache[row[away_col]],
                )
                created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'{created_count} official fixtures imported for season {season}'
        ))
