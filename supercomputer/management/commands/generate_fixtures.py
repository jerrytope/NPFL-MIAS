from django.core.management.base import BaseCommand
from django.db import transaction

from dashboard.models import Team
from supercomputer.models import SeasonFixture


# Confirmed Match Day 1 pairings (home vs away)
MD1_SEED = [
    ('Shooting Stars', 'Inter Lagos'),
    ('Rangers International', 'Katsina United'),
    ('Niger Tornadoes', 'Enyimba'),
    ('Rivers United', 'Plateau United'),
    ('Abia Warriors', 'Kun Khalifat FC'),
    ('Bendel Insurance', 'Warri Wolves'),
    ('Barau FC', 'Nasarawa United'),
    ('Doma United', 'Sporting Lagos'),
    ('Ikorodu City', 'Ranchers Bees'),
    ('Kwara United', 'Kano Pillars'),
]


class Command(BaseCommand):
    help = 'Auto-generate full season fixtures using round-robin from MD1 seed pairings'

    def add_arguments(self, parser):
        parser.add_argument('--season', type=str, default='26/27',
                            help='Season identifier (default: 26/27)')
        parser.add_argument('--force', action='store_true',
                            help='Clear existing fixtures without confirmation')

    def handle(self, *args, **options):
        season = options['season']
        force = options['force']

        # Check for existing fixtures
        existing = SeasonFixture.objects.filter(season=season).count()
        if existing > 0:
            if force:
                self.stdout.write(self.style.WARNING(
                    f'Clearing {existing} existing fixtures for season {season}...'
                ))
                SeasonFixture.objects.filter(season=season).delete()
            else:
                self.stdout.write(self.style.ERROR(
                    f'{existing} fixtures already exist for season {season}. '
                    f'Use --force to replace them.'
                ))
                return

        # Extract all 20 teams from MD1 seed
        teams = []
        for home, away in MD1_SEED:
            if home not in teams:
                teams.append(home)
            if away not in teams:
                teams.append(away)

        if len(teams) != 20:
            self.stdout.write(self.style.ERROR(
                f'Expected 20 teams from MD1 seed, found {len(teams)}'
            ))
            return

        self.stdout.write(f'Generating fixtures for {len(teams)} teams, season {season}...')

        # Generate round-robin schedule using circle method
        first_half = self._generate_round_robin(teams)

        # Build full season: first half (MD 1-19) + second half (MD 20-38, reversed)
        all_fixtures = []

        # First half (MD 1-19)
        for md_index, match_day in enumerate(first_half):
            match_day_num = md_index + 1
            for home, away in match_day:
                all_fixtures.append((match_day_num, home, away))

        # Second half (MD 20-38): reverse home/away
        for md_index, match_day in enumerate(first_half):
            match_day_num = md_index + 1 + len(first_half)  # MD 20-38
            for home, away in match_day:
                all_fixtures.append((match_day_num, away, home))  # Reversed

        # Ensure all teams exist in DB (create if missing)
        team_cache = {}
        for team_name in teams:
            team, created = Team.objects.get_or_create(name=team_name)
            team_cache[team_name] = team
            if created:
                self.stdout.write(f'  Created team: {team_name}')

        # Create SeasonFixture records
        created_count = 0
        with transaction.atomic():
            for match_day_num, home_name, away_name in all_fixtures:
                SeasonFixture.objects.create(
                    season=season,
                    match_day=match_day_num,
                    home=team_cache[home_name],
                    away=team_cache[away_name],
                )
                created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'{created_count} fixtures auto-generated for season {season} '
            f'({len(first_half)} match days × 10 games, first half + return leg)'
        ))

        # Print MD1 summary
        self.stdout.write('')
        self.stdout.write('Match Day 1:')
        for home, away in MD1_SEED:
            self.stdout.write(f'  {home} vs {away}')

    def _generate_round_robin(self, teams):
        """
        Generate a round-robin schedule using the circle method.

        The initial team ordering is derived from MD1_SEED so that round 1
        exactly matches the user-provided Match Day 1 pairings.

        Returns a list of match days, where each match day is a list of
        (home, away) tuples.
        """
        n = len(teams)
        num_rounds = n - 1  # 19 rounds for 20 teams

        # Build initial positions from MD1 seed
        # Circle method pairs position[i] with position[n-1-i]
        # So MD1 pairs determine: pos[0] vs pos[19], pos[1] vs pos[18], etc.
        positions = [''] * n
        for i, (home, away) in enumerate(MD1_SEED):
            positions[i] = home          # positions 0-9
            positions[n - 1 - i] = away  # positions 19-10

        # Fixed team is at position 0
        fixed = positions[0]
        rotating = list(positions[1:])  # positions 1-19

        rounds = []
        for r in range(num_rounds):
            # Current arrangement
            current = [fixed] + rotating

            # Create pairs: position[i] vs position[n-1-i]
            match_day = []
            for i in range(n // 2):
                home = current[i]
                away = current[n - 1 - i]
                match_day.append((home, away))
            rounds.append(match_day)

            # Rotate: move last element to front of rotating list
            rotating = [rotating[-1]] + rotating[:-1]

        return rounds
