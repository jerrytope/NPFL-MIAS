import os

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
import pandas as pd

from dashboard import team_logos, utils
from dashboard.views import NPFL_CLUBS_2026_2027

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
    def test_refresh_data_reports_how_many_matches_loaded(self, mock_get_data):
        """There is no cache left to clear; the endpoint now just proves the
        data loads and says how much of it there is."""
        mock_get_data.return_value = SAMPLE_DATA
        response = self.client.get(reverse('dashboard:refresh_data'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertIn(str(len(SAMPLE_DATA)), response.json()['message'])

    @patch('dashboard.utils.get_npfl_data', side_effect=ValueError('No match data available'))
    def test_refresh_data_surfaces_an_empty_table(self, mock_get_data):
        response = self.client.get(reverse('dashboard:refresh_data'))
        self.assertEqual(response.status_code, 500)
        self.assertIn('error', response.json())


class TeamLogoResolverTests(TestCase):
    """
    Guards the resolver against the bug it was built to fix: the old hardcoded
    JS mapping named files that didn't exist with that exact case, which worked
    on Windows but 404'd on the Ubuntu production box.
    """

    def setUp(self):
        team_logos.get_logo_index(force_refresh=True)

    def test_resolves_regardless_of_filename_case(self):
        """'Doma United' must find 'Doma United.png' even though the club name
        and the file are capitalised differently from the lookup key."""
        for name in ('Doma United', 'doma united', '  DOMA UNITED  '):
            self.assertIsNotNone(team_logos.get_logo_url(name), msg=name)

    def test_unknown_club_returns_none_for_initials_fallback(self):
        self.assertIsNone(team_logos.get_logo_url('Nonexistent Rovers'))
        self.assertIsNone(team_logos.get_logo_url(''))
        self.assertIsNone(team_logos.get_logo_url(None))

    def test_every_indexed_file_exists_with_exact_case(self):
        """
        The regression test for the production bug. Windows resolves a
        mis-cased filename happily, so compare against a real directory
        listing rather than trusting os.path.exists.
        """
        directory = settings.STATICFILES_DIRS[0]
        on_disk = set(os.listdir(directory))
        for filename in team_logos.get_logo_index().values():
            self.assertIn(filename, on_disk)

    def test_every_current_season_club_has_a_crest(self):
        missing = [c for c in NPFL_CLUBS_2026_2027 if not team_logos.get_logo_url(c)]
        self.assertEqual(missing, [], msg=f'clubs with no crest file: {missing}')

    def test_url_map_covers_every_requested_name(self):
        urls = team_logos.get_logo_url_map(['Doma United', 'Nonexistent Rovers'])
        self.assertIsNotNone(urls['doma united'])
        self.assertIsNone(urls['nonexistent rovers'])


class NoCachingTests(TestCase):
    """
    The dashboard used to hold the whole Match table in a 24-hour LocMem cache,
    so an edit took a day to appear — and because LocMem is per-process, one
    gunicorn worker could keep serving stale rows after another was refreshed.
    These guard against it coming back.
    """

    def test_cache_backend_stores_nothing(self):
        from django.core.cache import cache
        cache.set('canary', 'value')
        self.assertIsNone(
            cache.get('canary'),
            'CACHES is not the dummy backend — something will start caching again.',
        )

    def test_get_npfl_data_sees_a_new_match_immediately(self):
        """The behaviour the whole change exists for: no restart, no wait."""
        from dashboard.models import Match, Team

        home = Team.objects.create(name='Cache Test United')
        away = Team.objects.create(name='Cache Test City')
        Match.objects.create(season='25/26', home=home, away=away,
                             home_goal=1, away_goal=0)

        first = utils.get_npfl_data()
        self.assertEqual(len(first), 1)

        Match.objects.create(season='25/26', home=away, away=home,
                             home_goal=3, away_goal=2)

        second = utils.get_npfl_data()
        self.assertEqual(len(second), 2, 'a newly inserted match was not picked up')

    def test_rows_come_back_in_insertion_order(self):
        """
        Chronology here is insertion order — the Excel import loads matches in
        match order and the admin appends new results. Match.date is empty, so
        it cannot be used. An unordered queryset has no guaranteed SQL order,
        which would silently scramble every 'last 5' form guide.
        """
        from dashboard.models import Match, Team

        a = Team.objects.create(name='Alpha FC')
        b = Team.objects.create(name='Beta FC')
        for goals in range(5):
            Match.objects.create(season='25/26', home=a, away=b,
                                 home_goal=goals, away_goal=0)

        df = utils.get_npfl_data()
        self.assertEqual(
            list(df['home_goal']), [0, 1, 2, 3, 4],
            'rows did not come back in insertion order',
        )

    def test_form_puts_the_most_recent_match_last(self):
        """The last letter of the form string is the latest result."""
        from dashboard.models import Match, Team

        a = Team.objects.create(name='Alpha FC')
        b = Team.objects.create(name='Beta FC')
        # Four wins, then a loss — the loss is the most recent.
        for _ in range(4):
            Match.objects.create(season='25/26', home=a, away=b, home_goal=2, away_goal=0)
        Match.objects.create(season='25/26', home=b, away=a, home_goal=1, away_goal=0)

        df = utils.get_npfl_data()
        form, games = utils.get_team_form(df, 'Alpha FC')

        self.assertEqual(form, 'WWWWL')
        self.assertEqual(games[-1]['result'], 'L')
        self.assertEqual(games[-1]['home'], 'Beta FC')


class MatchSummaryBlockTests(TestCase):
    """The summary block the admin downloads as one social-media image."""

    def test_block_and_form_containers_render(self):
        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertIn('id="matchSummaryCapture"', html)
        self.assertIn('id="summaryT1Form"', html)
        self.assertIn('id="summaryT2Form"', html)
        self.assertIn('id="kpiTotalMatches"', html)

    def test_download_button_is_hidden_from_the_public(self):
        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertNotIn('match-summary', html)

    def test_download_button_appears_for_a_signed_in_admin(self):
        from django.contrib.auth.models import User
        User.objects.create_user(username='owner', password='OwnerPass!2026')
        self.client.login(username='owner', password='OwnerPass!2026')

        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertIn("downloadElementAsPNG('matchSummaryCapture', 'match-summary')", html)

    def test_the_shared_exporter_is_loaded(self):
        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertIn('png_export.js', html)
        self.assertIn('html2canvas', html)

    def test_the_cache_label_is_gone(self):
        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertNotIn('Cache Synced', html)
        self.assertIn('Live Data', html)

    def test_the_summary_block_opts_into_the_narrow_export_layout(self):
        """
        The four KPI cards are one wide row on screen, which exports as a thin
        strip. png_export.js applies this class to the live element for the
        duration of the capture so the PNG comes out roughly 3:2.
        """
        html = self.client.get(reverse('dashboard:index')).content.decode()
        self.assertIn('data-export-class="export-narrow"', html)


class RecentMatchesDownloadTests(TestCase):
    """Each team's profile card is downloadable as its own image."""

    def _html(self):
        return self.client.get(reverse('dashboard:index')).content.decode()

    def _sign_in(self):
        from django.contrib.auth.models import User
        User.objects.create_user(username='owner', password='OwnerPass!2026')
        self.client.login(username='owner', password='OwnerPass!2026')

    def test_each_profile_card_is_targetable(self):
        """The capture targets the whole card, so the image carries the club's
        crest, name and form — not just a nameless table."""
        html = self._html()
        self.assertIn('id="t1ProfileCard"', html)
        self.assertIn('id="t2ProfileCard"', html)

    def test_both_download_buttons_are_hidden_from_the_public(self):
        html = self._html()
        self.assertNotIn('recent-matches', html)

    def test_both_download_buttons_appear_for_a_signed_in_admin(self):
        self._sign_in()
        html = self._html()
        self.assertIn("downloadElementAsPNG('t1ProfileCard', 'recent-matches'", html)
        self.assertIn("downloadElementAsPNG('t2ProfileCard', 'recent-matches'", html)

    def test_the_filename_is_named_after_the_team_being_downloaded(self):
        """Without a hint the exporter prefixes 'team1-vs-team2-', which reads
        wrong on a single-club image."""
        self._sign_in()
        html = self._html()
        self.assertIn("document.getElementById('t1Name').innerText", html)
        self.assertIn("document.getElementById('t2Name').innerText", html)
