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


class TextBlock:
    """Stands in for an SDK TextBlock in the mocked responses below."""

    type = 'text'

    def __init__(self, text):
        self.text = text


class ThinkingBlock:
    """Reasoning block — carries no `.text`, and must never reach the report."""

    type = 'thinking'
    thinking = 'weighing the head-to-head record'


class FakeResponse:
    def __init__(self, blocks):
        self.content = blocks


COMPARISON_STUB = {
    'total_matches': 10, 'team1_wins': 4, 'team2_wins': 3, 'draws': 3,
    'team1_goals': 12, 'team2_goals': 11,
    'avg_scored_t1': 1.2, 'avg_conceded_t1': 1.1,
    'avg_scored_t2': 1.1, 'avg_conceded_t2': 1.2,
    'team1_form': 'WWDLW', 'team2_form': 'LDWWL',
    'season_goals': [{'season': '24/25', 'total_goals': 5}],
    'team1_recent_games': [], 'team2_recent_games': [],
}


class ExpertReportGenerationTests(TestCase):
    """
    Reports are generated by calling the Anthropic API directly. These pin the
    things that broke, or would silently break, when the AgentRouter proxy was
    removed.
    """

    def setUp(self):
        patcher = patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-test'})
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch('dashboard.utils.Anthropic')
    def test_the_client_is_built_with_no_base_url(self, mock_anthropic):
        """A base_url is how the removed proxy was addressed — it must not return."""
        mock_anthropic.return_value.messages.create.return_value = FakeResponse(
            [TextBlock('A tidy preview.')]
        )

        utils.generate_expert_report('Team A', 'Team B', COMPARISON_STUB)

        self.assertNotIn('base_url', mock_anthropic.call_args.kwargs)

    @patch('dashboard.utils.Anthropic')
    def test_the_request_sends_no_sampling_parameters(self, mock_anthropic):
        """
        temperature/top_p are rejected outright by current Claude models. The
        SDK still accepts the kwarg locally, so only a live call would catch
        this — hence the test.
        """
        create = mock_anthropic.return_value.messages.create
        create.return_value = FakeResponse([TextBlock('A tidy preview.')])

        utils.generate_expert_report('Team A', 'Team B', COMPARISON_STUB)

        sent = create.call_args.kwargs
        self.assertNotIn('temperature', sent)
        self.assertNotIn('top_p', sent)
        self.assertNotIn('top_k', sent)
        self.assertEqual(sent['model'], utils.ANTHROPIC_MODEL)

    def test_the_default_model_is_a_claude_model(self):
        """
        Asserted against the default rather than the live value, because
        ANTHROPIC_MODEL is env-overridable: a deployment carrying a stale
        non-Anthropic id from the proxy era would fail every call, and that is
        a config problem to fix in .env rather than a code regression.
        """
        self.assertTrue(utils.DEFAULT_ANTHROPIC_MODEL.startswith('claude-'))

    @patch('dashboard.utils.Anthropic')
    def test_every_text_block_is_kept(self, mock_anthropic):
        """The old scraper took the first block with text and stopped."""
        mock_anthropic.return_value.messages.create.return_value = FakeResponse([
            ThinkingBlock(),
            TextBlock('First paragraph.'),
            TextBlock('Second paragraph.'),
        ])

        report = utils.generate_expert_report('Team A', 'Team B', COMPARISON_STUB)

        self.assertIn('First paragraph.', report)
        self.assertIn('Second paragraph.', report)
        self.assertNotIn('weighing the head-to-head', report)

    @patch('dashboard.utils.Anthropic')
    def test_an_empty_reply_is_reported_not_saved(self, mock_anthropic):
        mock_anthropic.return_value.messages.create.return_value = FakeResponse([])

        with self.assertRaises(ValueError):
            utils.generate_expert_report('Team A', 'Team B', COMPARISON_STUB)

    def test_a_missing_key_names_only_anthropic(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            with self.assertRaises(ValueError) as caught:
                utils.get_anthropic_api_key()

        message = str(caught.exception)
        self.assertIn('ANTHROPIC_API_KEY', message)
        self.assertNotIn('AgentRouter', message)

    def test_provider_selection_uses_the_env_value(self):
        with patch.dict(os.environ, {'AI_PROVIDER': 'openai', 'OPENAI_API_KEY': 'sk-openai-test'}, clear=False):
            self.assertEqual('openai', utils.get_ai_provider())
            self.assertEqual('sk-openai-test', utils.get_api_key_for_provider())

        with patch.dict(os.environ, {'AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'gemini-test-key'}, clear=False):
            self.assertEqual('gemini', utils.get_ai_provider())
            self.assertEqual('gemini-test-key', utils.get_api_key_for_provider())

    def test_the_prompt_asks_for_a_short_unrepetitive_preview(self):
        """The length and no-restating steer is the actual fix for the padding."""
        with patch('dashboard.utils.Anthropic') as mock_anthropic:
            create = mock_anthropic.return_value.messages.create
            create.return_value = FakeResponse([TextBlock('A tidy preview.')])
            utils.generate_expert_report('Team A', 'Team B', COMPARISON_STUB)

        prompt = create.call_args.kwargs['messages'][0]['content']
        self.assertIn('400-550 words', prompt)
        self.assertIn('no headings', prompt)
        self.assertIn('Use each fact once', prompt)

    @patch('dashboard.utils.Anthropic')
    def test_the_report_output_uses_one_sentence_per_paragraph(self, mock_anthropic):
        """Readers want a full sentence, then a visible gap before the next one."""
        create = mock_anthropic.return_value.messages.create
        create.return_value = FakeResponse([
            TextBlock('First sentence here. Second sentence here. Third sentence here.')
        ])

        report = utils.generate_expert_report('Team A', 'Team B', COMPARISON_STUB)

        self.assertIn('First sentence here.\n\nSecond sentence here.', report)
        self.assertTrue(all(sentence.strip().endswith('.') for sentence in report.split('\n\n') if sentence.strip()))

    @patch('dashboard.utils.Anthropic')
    def test_the_prompt_uses_the_made_in_africa_sport_writing_guide(self, mock_anthropic):
        """The AI preview should follow the MIAS newsroom style guide, not generic AI filler."""
        create = mock_anthropic.return_value.messages.create
        create.return_value = FakeResponse([TextBlock('A preview.')])

        utils.generate_expert_report('Team A', 'Team B', COMPARISON_STUB)
        prompt = create.call_args.kwargs['messages'][0]['content']

        self.assertIn('Oxford British English', prompt)
        self.assertIn('short paragraphs', prompt)
        self.assertIn('one main idea per paragraph', prompt)
        self.assertIn('no obvious AI transitions', prompt)

    @patch('dashboard.utils.Anthropic')
    def test_the_prompt_carries_both_recent_form_and_recent_h2h(self, mock_anthropic):
        """
        The aggregate record and the recent meetings are different signals —
        a long historical edge can sit alongside a poor recent run against the
        same side, so both have to reach the model.
        """
        create = mock_anthropic.return_value.messages.create
        create.return_value = FakeResponse([TextBlock('A preview.')])

        data = dict(COMPARISON_STUB)
        data['raw_matches'] = [
            {'season': '24/25', 'home': 'Team A', 'away': 'Team B',
             'home_goal': 3, 'away_goal': 0},
            {'season': '23/24', 'home': 'Team B', 'away': 'Team A',
             'home_goal': 1, 'away_goal': 1},
        ]
        data['team1_recent_games'] = [
            {'season': '24/25', 'home': 'Team A', 'away': 'Team C',
             'home_goal': 2, 'away_goal': 0, 'result': 'W'},
        ]

        utils.generate_expert_report('Team A', 'Team B', data)
        prompt = create.call_args.kwargs['messages'][0]['content']

        # The actual recent meetings, by scoreline
        self.assertIn('Their most recent meetings', prompt)
        self.assertIn('24/25: Team A 3-0 Team B', prompt)
        self.assertIn('23/24: Team B 1-1 Team A', prompt)
        # Each side's own recent form
        self.assertIn('last five league matches', prompt)
        self.assertIn('24/25: Team A 2-0 Team C (W)', prompt)
        # And the model is told to use both, separately
        self.assertIn('separate points', prompt)

    def test_recent_meetings_are_listed_newest_first_and_capped(self):
        matches = [
            {'season': f'2{n}/2{n+1}', 'home': 'A', 'away': 'B',
             'home_goal': n, 'away_goal': 0}
            for n in range(8)
        ]
        formatted = utils._format_recent_meetings(matches, limit=5)

        lines = formatted.splitlines()
        self.assertEqual(len(lines), 5)
        # perform_comparison hands this list over already newest-first
        self.assertIn('A 0-0 B', lines[0])
        self.assertIn('A 4-0 B', lines[4])

    def test_no_meetings_on_record_is_stated_not_faked(self):
        self.assertIn('no completed meetings', utils._format_recent_meetings([]))


class ReportDataSourceTests(TestCase):
    """
    Reports must read live database rows, never the Excel workbook — the admin
    keeps entering results, and they land in the Match table.
    """

    def test_comparison_data_is_read_from_the_match_table(self):
        with patch('dashboard.utils.get_npfl_data') as mock_data:
            mock_data.return_value = SAMPLE_DATA
            utils.perform_comparison('Team A', 'Team B')

        self.assertTrue(mock_data.called)

    def test_get_npfl_data_queries_the_orm_and_reads_no_file(self):
        from dashboard.models import Match

        with patch.object(Match, 'objects') as mock_objects:
            mock_objects.exists.return_value = False
            with self.assertRaises(ValueError):
                utils.get_npfl_data()

        # Reaching the ORM at all is the point: if this ever went back to
        # reading a workbook, Match.objects would never be touched.
        self.assertTrue(mock_objects.exists.called)


class ReportEndpointErrorTests(TestCase):
    """/generate-report/ is public and unauthenticated."""

    @patch('dashboard.utils.perform_comparison', side_effect=RuntimeError('boom'))
    def test_a_failure_does_not_leak_a_traceback_to_the_public(self, _mock):
        response = self.client.get(
            reverse('dashboard:generate_report'),
            {'team1': 'Team A', 'team2': 'Team B'},
        )

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertNotIn('debug', payload)
        self.assertNotIn('Traceback', response.content.decode())
