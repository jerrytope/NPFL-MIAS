from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.utils import get_npfl_data
from supercomputer.models import SeasonFixture, Prediction
from supercomputer.predictor import predict_all_fixtures


class Command(BaseCommand):
    help = 'Run predictions for all fixtures (or from a match day onwards)'

    def add_arguments(self, parser):
        parser.add_argument('--season', type=str, default='26/27',
                            help='Season identifier (default: 26/27)')
        parser.add_argument('--from-match-day', type=int, default=0,
                            help='Start regenerating from this match day (0 = all). Earlier days stay untouched.')

    def handle(self, *args, **options):
        season = options['season']
        from_md = options['from_match_day']

        # Load fixtures
        fixtures = SeasonFixture.objects.filter(season=season).select_related('home', 'away')
        if from_md > 0:
            fixtures_to_predict = fixtures.filter(match_day__gte=from_md)
            mode_label = f'from MD{from_md} onwards'
        else:
            fixtures_to_predict = fixtures
            mode_label = 'all fixtures'

        fixture_count = fixtures_to_predict.count()
        if fixture_count == 0:
            raise CommandError(
                f'No fixtures found for season {season} {mode_label}. '
                f'Run generate_fixtures first.'
            )

        self.stdout.write(f'Loading historical match data...')
        try:
            df = get_npfl_data(force_refresh=True)
        except ValueError as e:
            raise CommandError(str(e))

        self.stdout.write(f'Loaded {len(df)} historical matches')
        self.stdout.write(f'Running predictions for {fixture_count} fixtures ({mode_label})...')

        # Run predictions
        results = predict_all_fixtures(fixtures_to_predict, df)

        # Apply 10% away-to-home/draw calibration
        for r in results:
            shift = min(10.0, r['away_win_pct'])
            half = shift / 2
            r['away_win_pct'] = round(r['away_win_pct'] - shift, 1)
            r['home_win_pct'] = round(r['home_win_pct'] + half, 1)
            r['draw_pct'] = round(r['draw_pct'] + half, 1)

            total = r['home_win_pct'] + r['draw_pct'] + r['away_win_pct']
            diff = round(100.0 - total, 1)
            if abs(diff) > 0.01:
                r['home_win_pct'] = round(r['home_win_pct'] + diff, 1)

            pcts = {'HOME': r['home_win_pct'], 'DRAW': r['draw_pct'], 'AWAY': r['away_win_pct']}
            r['predicted_result'] = max(pcts, key=pcts.get)
            r['confidence'] = pcts[r['predicted_result']]

        created = 0
        updated = 0
        with transaction.atomic():
            for r in results:
                obj, was_created = Prediction.objects.update_or_create(
                    fixture=r['fixture'],
                    defaults={
                        'home_win_pct': r['home_win_pct'],
                        'draw_pct': r['draw_pct'],
                        'away_win_pct': r['away_win_pct'],
                        'predicted_result': r['predicted_result'],
                        'confidence': r['confidence'],
                        'home_form_score': r['home_form_score'],
                        'away_form_score': r['away_form_score'],
                        'h2h_home_rate': r['h2h_home_rate'],
                        'h2h_draw_rate': r['h2h_draw_rate'],
                        'h2h_away_rate': r['h2h_away_rate'],
                        'home_venue_strength': r['home_venue_strength'],
                        'away_venue_strength': r['away_venue_strength'],
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        # Print summary
        home_wins = sum(1 for r in results if r['predicted_result'] == 'HOME')
        draws = sum(1 for r in results if r['predicted_result'] == 'DRAW')
        away_wins = sum(1 for r in results if r['predicted_result'] == 'AWAY')
        avg_confidence = sum(r['confidence'] for r in results) / len(results)

        total_preds = Prediction.objects.filter(fixture__season=season).count()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Predictions generated ({mode_label}): '
            f'{created} created, {updated} updated'
        ))
        self.stdout.write(f'  Total predictions in DB: {total_preds}')
        self.stdout.write(f'  Home wins predicted: {home_wins}')
        self.stdout.write(f'  Draws predicted:     {draws}')
        self.stdout.write(f'  Away wins predicted: {away_wins}')
        self.stdout.write(f'  Average confidence:  {avg_confidence:.1f}%')
