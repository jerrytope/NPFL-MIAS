from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
import pandas as pd

from dashboard import utils

SAMPLE_DATA = pd.DataFrame([
    {
        'season': '20/21',
        'match_name': 'Team A vs Team B',
        'home': 'Team A',
        'away': 'Team B',
        'home_goal': 2,
        'away_goal': 1,
        'home_result': 'H Win',
        'away_result': 'A Loss',
        'match_name': 'Team A vs Team B',
    },
    {
        'season': '20/21',
        'match_name': 'Team B vs Team A',
        'home': 'Team B',
        'away': 'Team A',
        'home_goal': 1,
        'away_goal': 1,
        'home_result': 'Draw',
        'away_result': 'Draw',
        'match_name': 'Team B vs Team A',
    }
])

class DashboardUtilsTests(TestCase):
    @patch('dashboard.utils.get_npfl_data')
    def test_perform_comparison_returns_expected_structure(self, mock_get_data):
        mock_get_data.return_value = SAMPLE_DATA

        result = utils.perform_comparison('Team A', 'Team B')

        self.assertEqual(result['team1'], 'Team A')
        self.assertEqual(result['team2'], 'Team B')
        self.assertIn('total_matches', result)
        self.assertIn('team1_wins', result)
        self.assertIn('team2_wins', result)
        self.assertEqual(result['total_matches'], 2)
        self.assertEqual(result['team1_wins'], 1)
        self.assertEqual(result['draws'], 1)
        self.assertEqual(result['team1_form'], 'WD')
        self.assertEqual(result['team2_form'], 'LD')

class DashboardViewsTests(TestCase):
    @patch('dashboard.utils.get_unique_teams', return_value=['Team A', 'Team B'])
    def test_index_view_renders_main_dashboard(self, mock_get_unique):
        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'NPFL All-Time Analytics')
        self.assertContains(response, 'Select Team 1')
        self.assertContains(response, 'Select Team 2')

    @patch('dashboard.utils.perform_comparison')
    def test_compare_teams_endpoint_returns_json(self, mock_compare):
        mock_compare.return_value = {
            'team1': 'Team A',
            'team2': 'Team B',
            'total_matches': 2,
            'team1_wins': 1,
            'team2_wins': 0,
            'draws': 1,
            'team1_goals': 2,
            'team2_goals': 2,
            'avg_scored_t1': 1.0,
            'avg_conceded_t1': 1.0,
            'avg_scored_t2': 1.0,
            'avg_conceded_t2': 1.0,
            'season_goals': [],
            'goals_per_team_season': [],
            'team1_form': 'WD',
            'team1_recent_games': [],
            'team2_form': 'DW',
            'team2_recent_games': [],
            'raw_matches': [],
        }
        response = self.client.get(reverse('dashboard:compare_teams'), {'team1': 'Team A', 'team2': 'Team B'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['team1'], 'Team A')
        self.assertEqual(response.json()['team2'], 'Team B')

    def test_compare_teams_endpoint_requires_two_teams(self):
        response = self.client.get(reverse('dashboard:compare_teams'), {'team1': 'Team A'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    @patch('dashboard.utils.get_npfl_data')
    def test_refresh_data_clears_and_refetches_cache(self, mock_get_data):
        mock_get_data.return_value = SAMPLE_DATA
        response = self.client.get(reverse('dashboard:refresh_data'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
