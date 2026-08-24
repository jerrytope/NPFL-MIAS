from django.core.management.base import BaseCommand
from django.db import transaction
from dashboard.models import Team, Match
from dashboard.utils import normalize_season
import pandas as pd


def to_int(val):
    try:
        if pd.isna(val):
            return None
    except Exception:
        pass
    try:
        return int(val)
    except Exception:
        return None


class Command(BaseCommand):
    help = 'Import NPFL matches from the Excel workbook into the database.'

    def add_arguments(self, parser):
        parser.add_argument('--file', '-f', dest='file', required=False,
                            default='plans/all time results 2002-2026.xlsx')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run',
                            help='Run without saving to DB')
        parser.add_argument('--batch-size', dest='batch_size', type=int, default=500,
                            help='Batch size for bulk_create')
        parser.add_argument('--replace', action='store_true', dest='replace',
                            help='Delete all existing Match rows before importing (clean cutover to a new source file)')

    def handle(self, *args, **options):
        path = options['file']
        dry_run = options['dry_run']
        batch_size = options['batch_size']
        replace = options['replace']

        if replace and not dry_run:
            existing_match_count = Match.objects.count()
            self.stdout.write(self.style.WARNING(
                f'--replace: deleting {existing_match_count} existing Match rows before import...'
            ))
            with transaction.atomic():
                Match.objects.all().delete()

        self.stdout.write(f'Reading Excel: {path}')
        df = pd.read_excel(path, sheet_name=0)

        # Normalize column names
        df.columns = [c.strip() for c in df.columns]

        required_cols = ['season', 'match_name', 'home', 'away', 'home_goal', 'away_goal']
        for c in required_cols:
            if c not in df.columns:
                self.stderr.write(f'Missing expected column: {c}')
                return

        # Create/get teams — normalize to lowercase to avoid MySQL case-insensitive collisions
        raw_names = set(df['home'].dropna().astype(str).str.strip().unique()) | set(df['away'].dropna().astype(str).str.strip().unique())
        # Deduplicate case-insensitively, keeping the first occurrence
        seen_lower = {}
        for n in raw_names:
            low = n.lower()
            if low not in seen_lower:
                seen_lower[low] = n
        team_names = list(seen_lower.values())
        self.stdout.write(f'Found {len(team_names)} unique teams in sheet')

        existing_teams = {t.name.lower(): t for t in Team.objects.all()}
        new_teams = []
        for name in team_names:
            if name.lower() not in existing_teams:
                new_teams.append(Team(name=name))

        if new_teams and not dry_run:
            Team.objects.bulk_create(new_teams, ignore_conflicts=True)
            self.stdout.write(f'Created {len(new_teams)} Team records')

        # Reload mapping (case-insensitive lookup)
        teams = {t.name.lower(): t for t in Team.objects.all()}

        matches_to_create = []
        created = 0
        skipped = 0
        no_score_rows = []

        for idx, row in df.iterrows():
            season = normalize_season(row.get('season'))
            match_name = str(row.get('match_name') or '').strip()
            home_name = str(row.get('home') or '').strip()
            away_name = str(row.get('away') or '').strip()
            home_goal = to_int(row.get('home_goal'))
            away_goal = to_int(row.get('away_goal'))

            if home_goal is None or away_goal is None:
                no_score_rows.append(f'{season}: {match_name or f"{home_name} vs {away_name}"}')

            home = teams.get(home_name.lower())
            away = teams.get(away_name.lower())

            if not home or not away:
                skipped += 1
                continue

            # Idempotency check
            exists = Match.objects.filter(season=season, match_name=match_name, home=home, away=away).exists()
            if exists:
                skipped += 1
                continue

            m = Match(
                season=season,
                match_name=match_name,
                home=home,
                away=away,
                home_goal=home_goal,
                away_goal=away_goal,
                source='excel',
            )
            matches_to_create.append(m)

            if len(matches_to_create) >= batch_size:
                if not dry_run:
                    Match.objects.bulk_create(matches_to_create)
                created += len(matches_to_create)
                matches_to_create = []

        # flush remaining
        if matches_to_create:
            if not dry_run:
                Match.objects.bulk_create(matches_to_create)
            created += len(matches_to_create)

        self.stdout.write(f'Import finished. Created: {created}, Skipped: {skipped}')

        if no_score_rows:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'{len(no_score_rows)} row(s) with no score (imported with null goals, excluded from form/H2H calculations):'
            ))
            for line in no_score_rows:
                self.stdout.write(f'  - {line}')
