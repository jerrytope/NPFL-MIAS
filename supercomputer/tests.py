import pandas as pd
from django.test import TestCase

from dashboard.models import Team
from supercomputer import ratings as ratings_module
from supercomputer.models import Prediction, SeasonFixture, TeamCareerStats
from supercomputer.poisson_model import expected_goals, score_probabilities
from supercomputer.predictor import predict_match
from supercomputer.ratings import compute_team_ratings, get_team_rating, LEAGUE_AVERAGE_RATIO
from supercomputer.standings import calculate_standings


def empty_match_df():
    return pd.DataFrame(columns=['season', 'home', 'away', 'home_goal', 'away_goal'])


class CareerStatsCacheMixin:
    """Reset ratings.py's in-process TeamCareerStats cache before each test."""

    def setUp(self):
        ratings_module._CAREER_STATS_CACHE = None
        super().setUp()

    def tearDown(self):
        ratings_module._CAREER_STATS_CACHE = None
        super().tearDown()


class ScoreProbabilitiesTests(TestCase):
    def test_probabilities_sum_to_one(self):
        _, p_home, p_draw, p_away = score_probabilities(1.5, 0.9)
        self.assertAlmostEqual(p_home + p_draw + p_away, 1.0, places=6)

    def test_equal_lambdas_give_symmetric_home_away_probability(self):
        _, p_home, p_draw, p_away = score_probabilities(1.3, 1.3)
        self.assertAlmostEqual(p_home, p_away, places=6)

    def test_stronger_home_lambda_favors_home(self):
        _, p_home, p_draw, p_away = score_probabilities(2.5, 0.6)
        self.assertGreater(p_home, p_away)
        self.assertGreater(p_home, p_draw)


class ExpectedGoalsTests(CareerStatsCacheMixin, TestCase):
    def test_better_attack_rating_produces_higher_lambda(self):
        ratings = {
            'Strong': ratings_module.TeamRating(home_attack=1.8, home_defense=1.0, away_attack=1.5, away_defense=1.0),
            'Weak': ratings_module.TeamRating(home_attack=0.6, home_defense=1.0, away_attack=0.5, away_defense=1.0),
        }
        lh_strong, _ = expected_goals('Strong', 'Weak', ratings, 1.5, 0.5, 5.0, 5.0)
        lh_weak, _ = expected_goals('Weak', 'Strong', ratings, 1.5, 0.5, 5.0, 5.0)
        self.assertGreater(lh_strong, lh_weak)

    def test_unknown_team_falls_back_to_league_average_rating(self):
        rating = get_team_rating({}, 'Nobody FC')
        self.assertEqual(rating.home_attack, LEAGUE_AVERAGE_RATIO)
        self.assertEqual(rating.away_defense, LEAGUE_AVERAGE_RATIO)


class ComputeTeamRatingsTests(CareerStatsCacheMixin, TestCase):
    def setUp(self):
        super().setUp()
        # A small, self-consistent league: two seasons, three teams
        self.df = pd.DataFrame([
            {'season': '24/25', 'home': 'Strong FC', 'away': 'Weak FC', 'home_goal': 3, 'away_goal': 0},
            {'season': '24/25', 'home': 'Weak FC', 'away': 'Strong FC', 'home_goal': 0, 'away_goal': 2},
            {'season': '24/25', 'home': 'Mid FC', 'away': 'Weak FC', 'home_goal': 1, 'away_goal': 1},
            {'season': '24/25', 'home': 'Weak FC', 'away': 'Mid FC', 'home_goal': 1, 'away_goal': 1},
            {'season': '24/25', 'home': 'Strong FC', 'away': 'Mid FC', 'home_goal': 2, 'away_goal': 1},
            {'season': '24/25', 'home': 'Mid FC', 'away': 'Strong FC', 'home_goal': 0, 'away_goal': 2},
        ])

    def test_strong_team_gets_above_average_attack_rating(self):
        ratings, _, _ = compute_team_ratings(self.df)
        self.assertGreater(ratings['Strong FC'].home_attack, LEAGUE_AVERAGE_RATIO)
        self.assertGreater(ratings['Strong FC'].away_attack, LEAGUE_AVERAGE_RATIO)

    def test_weak_team_gets_below_average_attack_rating(self):
        ratings, _, _ = compute_team_ratings(self.df)
        self.assertLess(ratings['Weak FC'].home_attack, LEAGUE_AVERAGE_RATIO)

    def test_team_with_no_data_and_no_career_stats_is_pure_league_average(self):
        Team.objects.create(name='Ghost United')
        ratings, _, _ = compute_team_ratings(self.df)
        self.assertNotIn('Ghost United', ratings)  # never appeared in df at all
        rating = get_team_rating(ratings, 'Ghost United')
        self.assertEqual(rating.home_attack, LEAGUE_AVERAGE_RATIO)
        self.assertEqual(rating.home_defense, LEAGUE_AVERAGE_RATIO)

    def test_thin_data_team_shrinks_toward_career_stats_prior_not_pure_average(self):
        # "Debutant FC" has exactly one (weak) recent match, but a strong all-time record
        team = Team.objects.create(name='Debutant FC')
        TeamCareerStats.objects.create(
            team=team, parts=20, played=600,
            home_win=250, home_draw=50, home_loss=0,
            home_gf=750, home_ga=150,  # 2.5 goals/game at home historically — well above average
            away_win=100, away_draw=100, away_loss=100,
            away_gf=300, away_ga=300,
            total_win=350, total_draw=150, total_loss=100,
            total_gf=1050, total_ga=450, total_gd=600, points=1200,
        )
        df = pd.concat([self.df, pd.DataFrame([
            {'season': '25/26', 'home': 'Debutant FC', 'away': 'Weak FC', 'home_goal': 0, 'away_goal': 0},
        ])], ignore_index=True)

        ratings, _, _ = compute_team_ratings(df)
        rating = ratings['Debutant FC']
        # Should sit between pure league average (1.0) and a naive "0 goals scored" reading —
        # i.e. shrunk toward the strong career prior, not collapsed to a single bad game.
        self.assertGreater(rating.home_attack, LEAGUE_AVERAGE_RATIO)


class PredictMatchTests(CareerStatsCacheMixin, TestCase):
    def test_percentages_sum_to_100_with_no_data_for_either_team(self):
        Team.objects.create(name='Alpha FC')
        Team.objects.create(name='Beta FC')
        ratings, league_h, league_a = compute_team_ratings(empty_match_df())
        result = predict_match('Alpha FC', 'Beta FC', ratings, league_h, league_a)
        total = result['home_win_pct'] + result['draw_pct'] + result['away_win_pct']
        self.assertAlmostEqual(total, 100.0, places=1)

    def test_percentages_sum_to_100_with_real_data(self):
        df = pd.DataFrame([
            {'season': '24/25', 'home': 'Alpha FC', 'away': 'Beta FC', 'home_goal': 2, 'away_goal': 1},
            {'season': '24/25', 'home': 'Beta FC', 'away': 'Alpha FC', 'home_goal': 0, 'away_goal': 0},
            {'season': '25/26', 'home': 'Alpha FC', 'away': 'Beta FC', 'home_goal': 1, 'away_goal': 1},
        ])
        ratings, league_h, league_a = compute_team_ratings(df)
        result = predict_match('Alpha FC', 'Beta FC', ratings, league_h, league_a)
        total = result['home_win_pct'] + result['draw_pct'] + result['away_win_pct']
        self.assertAlmostEqual(total, 100.0, places=1)
        self.assertIn(result['predicted_result'], ('HOME', 'DRAW', 'AWAY'))


class StandingsExpectedPointsTests(TestCase):
    def test_standings_use_expected_points_not_winner_take_all(self):
        """
        A team favored (but not certain) in every fixture must NOT be tallied
        as winning every fixture outright — this was the exact bug that
        produced Rivers United's unrealistic 32-3-3 / 99-point record.
        """
        home = Team.objects.create(name='Favorite FC')
        away = Team.objects.create(name='Underdog FC')
        fixture = SeasonFixture.objects.create(season='26/27', match_day=1, home=home, away=away)
        Prediction.objects.create(
            fixture=fixture,
            home_win_pct=40.0, draw_pct=35.0, away_win_pct=25.0,
            predicted_result='HOME', confidence=40.0,
        )

        standings = calculate_standings(season='26/27')
        favorite_row = next(r for r in standings if r['team'] == 'Favorite FC')

        # Expected points = 3*0.40 + 1*0.35 = 1.55 (rounds to 1.6 at the
        # 1-decimal display precision standings.py returns), NOT the full 3
        # points a "winner-take-all" tally would have assigned.
        self.assertAlmostEqual(favorite_row['points'], 1.6, places=1)
        self.assertLess(favorite_row['points'], 3.0)

    def test_expected_points_sum_correctly_across_two_fixtures(self):
        team_a = Team.objects.create(name='Team A')
        team_b = Team.objects.create(name='Team B')
        team_c = Team.objects.create(name='Team C')

        f1 = SeasonFixture.objects.create(season='26/27', match_day=1, home=team_a, away=team_b)
        f2 = SeasonFixture.objects.create(season='26/27', match_day=2, home=team_c, away=team_a)

        Prediction.objects.create(fixture=f1, home_win_pct=60.0, draw_pct=25.0, away_win_pct=15.0,
                                   predicted_result='HOME', confidence=60.0)
        Prediction.objects.create(fixture=f2, home_win_pct=20.0, draw_pct=30.0, away_win_pct=50.0,
                                   predicted_result='AWAY', confidence=50.0)

        standings = calculate_standings(season='26/27')
        team_a_row = next(r for r in standings if r['team'] == 'Team A')

        # Team A: home leg (3*0.60 + 1*0.25 = 2.05) + away leg (3*0.50 + 1*0.30 = 1.80)
        # = 3.85, rounds to 3.8 at the 1-decimal display precision standings.py returns.
        self.assertAlmostEqual(team_a_row['points'], 3.8, places=1)
        self.assertEqual(team_a_row['played'], 2)
