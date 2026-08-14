from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.utils import get_npfl_data
from supercomputer.models import SeasonFixture, PredictionSnapshot, Prediction
from supercomputer.predictor import predict_all_fixtures


class Command(BaseCommand):
    help = 'Run predictions for all fixtures and store as a new snapshot'

    def add_arguments(self, parser):
        parser.add_argument('--season', type=str, default='26/27',
                            help='Season identifier (default: 26/27)')
        parser.add_argument('--label', type=str, default='Pre-Season',
                            help='Version label for this snapshot (e.g. "Pre-Season", "After Match Day 5")')
        parser.add_argument('--match-day', type=int, default=0,
                            help='Match day this prediction is computed after (0 = pre-season)')
        parser.add_argument('--notes', type=str, default='',
                            help='Optional notes about this prediction run')

    def handle(self, *args, **options):
        season = options['season']
        label = options['label']
        match_day = options['match_day']
        notes = options['notes']

        # Load fixtures
        fixtures = SeasonFixture.objects.filter(season=season).select_related('home', 'away')
        fixture_count = fixtures.count()
        if fixture_count == 0:
            raise CommandError(
                f'No fixtures found for season {season}. '
                f'Run generate_fixtures first.'
            )

        self.stdout.write(f'Loading historical match data...')
        try:
            df = get_npfl_data(force_refresh=True)
        except ValueError as e:
            raise CommandError(str(e))

        self.stdout.write(f'Loaded {len(df)} historical matches')
        self.stdout.write(f'Running predictions for {fixture_count} fixtures...')

        # Run predictions
        results = predict_all_fixtures(fixtures, df)

        # Create snapshot (mark previous latest as not latest)
        with transaction.atomic():
            # Unset previous latest snapshots for this season
            PredictionSnapshot.objects.filter(
                season=season, is_latest=True
            ).update(is_latest=False)

            # Create new snapshot
            snapshot = PredictionSnapshot.objects.create(
                season=season,
                version_label=label,
                match_day_computed=match_day,
                is_latest=True,
                notes=notes,
            )

            # Create prediction records
            predictions = []
            for result in results:
                predictions.append(Prediction(
                    snapshot=snapshot,
                    fixture=result['fixture'],
                    home_win_pct=result['home_win_pct'],
                    draw_pct=result['draw_pct'],
                    away_win_pct=result['away_win_pct'],
                    predicted_result=result['predicted_result'],
                    confidence=result['confidence'],
                    home_form_score=result['home_form_score'],
                    away_form_score=result['away_form_score'],
                    h2h_home_rate=result['h2h_home_rate'],
                    h2h_draw_rate=result['h2h_draw_rate'],
                    h2h_away_rate=result['h2h_away_rate'],
                    home_venue_strength=result['home_venue_strength'],
                    away_venue_strength=result['away_venue_strength'],
                ))

            Prediction.objects.bulk_create(predictions)

        # Print summary
        home_wins = sum(1 for r in results if r['predicted_result'] == 'HOME')
        draws = sum(1 for r in results if r['predicted_result'] == 'DRAW')
        away_wins = sum(1 for r in results if r['predicted_result'] == 'AWAY')
        avg_confidence = sum(r['confidence'] for r in results) / len(results)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Snapshot "{label}" created (ID: {snapshot.id}, '
            f'MD{match_day}) with {len(predictions)} predictions'
        ))
        self.stdout.write(f'  Home wins predicted: {home_wins}')
        self.stdout.write(f'  Draws predicted:     {draws}')
        self.stdout.write(f'  Away wins predicted: {away_wins}')
        self.stdout.write(f'  Average confidence:  {avg_confidence:.1f}%')
