import time
from django.core.management.base import BaseCommand, CommandError

from dashboard.utils import get_npfl_data
from supercomputer.simulator import run_monte_carlo_simulations, save_simulation_results


class Command(BaseCommand):
    help = 'Run 1,000 Monte Carlo Season Simulations for NPFL Super Computer'

    def add_arguments(self, parser):
        parser.add_argument('--season', type=str, default='26/27',
                            help='Season identifier (default: 26/27)')
        parser.add_argument('--iterations', type=int, default=100000,
                            help='Number of simulation runs (default: 100000)')

    def handle(self, *args, **options):
        season = options['season']
        iterations = options['iterations']

        self.stdout.write('Loading NPFL historical match data for simulation...')
        start_time = time.time()
        try:
            df = get_npfl_data(force_refresh=False)
        except Exception as e:
            raise CommandError(f'Failed to load match data: {e}')

        self.stdout.write(f'Running {iterations:,} Monte Carlo season simulations for season {season}...')
        try:
            projections = run_monte_carlo_simulations(
                season=season, iterations=iterations, df=df
            )
            save_simulation_results(season, projections)
        except Exception as e:
            raise CommandError(f'Simulation error: {e}')

        elapsed = time.time() - start_time
        total_matches = 380 * iterations

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'[OK] Successfully completed {iterations:,} season simulations ({total_matches:,} simulated matches) in {elapsed:.2f}s'
        ))
        self.stdout.write('')
        self.stdout.write('=' * 92)
        self.stdout.write(f'{"#":<3} {"Team":<22} {"xPts":<7} {"Range":<12} {"Title %":<10} {"Top 3 %":<10} {"Relegation %":<12}')
        self.stdout.write('-' * 92)
        for i, p in enumerate(projections, start=1):
            range_str = f"{p['worst_points']}-{p['best_points']}"
            self.stdout.write(
                f"{i:<3} {p['team']:<22} {p['expected_points']:<7.1f} {range_str:<12} {p['title_pct']:<9.1f}% {p['top3_pct']:<9.1f}% {p['relegation_pct']:<11.1f}%"
            )
        self.stdout.write('=' * 92)
