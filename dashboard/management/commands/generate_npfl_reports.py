from itertools import combinations
from time import sleep

from django.core.management.base import BaseCommand, CommandError

from dashboard.models import TeamComparisonReport
from dashboard.utils import generate_expert_report, perform_comparison
from dashboard.views import NPFL_CLUBS_2026_2027, canonical_team_pair


class Command(BaseCommand):
    help = 'Generate and save AI reports for every unique pair of 2026/27 NPFL clubs.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate and replace reports that are already saved.',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Seconds to wait between AI requests (default: 1).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Only process this many missing pairs; useful for a trial run.',
        )
        parser.add_argument(
            '--retries',
            type=int,
            default=3,
            help='Retry each failed AI generation this many times (default: 3).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List the pairs that would be processed without calling the AI service.',
        )

    def handle(self, *args, **options):
        force = options['force']
        delay = options['delay']
        limit = options['limit']
        retries = options['retries']
        dry_run = options['dry_run']

        if delay < 0:
            raise CommandError('--delay cannot be negative.')
        if limit is not None and limit < 1:
            raise CommandError('--limit must be at least 1.')
        if retries < 0:
            raise CommandError('--retries cannot be negative.')

        pairs = list(combinations(NPFL_CLUBS_2026_2027, 2))
        self.stdout.write(f'Found {len(pairs)} unique club pairings.')

        generated = skipped = failed = processed = 0
        for team1, team2 in pairs:
            canonical_team_one, canonical_team_two = canonical_team_pair(team1, team2)
            existing = TeamComparisonReport.objects.filter(
                team_one=canonical_team_one,
                team_two=canonical_team_two,
            ).first()

            if existing and not force:
                skipped += 1
                continue

            if limit is not None and processed >= limit:
                break
            processed += 1

            label = f'{team1} vs {team2}'
            if dry_run:
                self.stdout.write(f'Would generate: {label}')
                continue

            try:
                comparison = perform_comparison(team1, team2)
                report = None
                for attempt in range(retries + 1):
                    try:
                        report = generate_expert_report(team1, team2, comparison)
                        break
                    except Exception as exc:
                        if attempt == retries:
                            raise

                        wait_time = delay * (2 ** attempt)
                        self.stdout.write(
                            self.style.WARNING(
                                f'Retrying {label} in {wait_time:g}s '
                                f'(attempt {attempt + 2}/{retries + 1}): {exc}'
                            )
                        )
                        if wait_time:
                            sleep(wait_time)

                if existing:
                    existing.report = report
                    existing.save(update_fields=['report', 'updated_at'])
                else:
                    TeamComparisonReport.objects.create(
                        team_one=canonical_team_one,
                        team_two=canonical_team_two,
                        report=report,
                    )

                generated += 1
                self.stdout.write(self.style.SUCCESS(f'Saved ({generated}): {label}'))
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f'Failed: {label} — {exc}'))

            if delay and (limit is None or processed < limit):
                sleep(delay)

        if dry_run:
            self.stdout.write(self.style.WARNING(f'Dry run complete. Pairs to process: {processed}; already saved: {skipped}.'))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Finished. Saved: {generated}; skipped existing: {skipped}; failed: {failed}.'
            )
        )
