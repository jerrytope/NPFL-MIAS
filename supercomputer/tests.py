import pandas as pd
from django.test import TestCase

from dashboard.models import Team
from supercomputer import ratings as ratings_module
from supercomputer.models import (
    Prediction, SeasonFixture, TeamCareerStats, MatchDayVisibility,
)
from supercomputer.poisson_model import (
    expected_goals, goal_markets, most_likely_scoreline, score_probabilities, top_scorelines,
)
from supercomputer.predictor import predict_match
from supercomputer.ratings import compute_team_ratings, get_team_rating, LEAGUE_AVERAGE_RATIO
from supercomputer.standings import calculate_standings
from django.urls import reverse
from django.contrib.auth.models import User
from pathlib import Path


def empty_match_df():
    return pd.DataFrame(columns=['season', 'home', 'away', 'home_goal', 'away_goal'])


# CareerStatsCacheMixin used to live here, resetting ratings.py's in-process
# TeamCareerStats memo between tests. That memo is gone — career stats are read
# from the database on every call — so there is nothing left to reset.


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


class TopScorelinesTests(TestCase):
    def test_returns_requested_count_in_descending_probability_order(self):
        grid, _, _, _ = score_probabilities(1.7, 0.5)
        top = top_scorelines(grid, 5)

        self.assertEqual(len(top), 5)
        probs = [s['prob'] for s in top]
        self.assertEqual(probs, sorted(probs, reverse=True))

    def test_first_entry_matches_most_likely_scoreline(self):
        grid, _, _, _ = score_probabilities(1.7, 0.5)
        top = top_scorelines(grid, 5)[0]

        self.assertEqual(
            (top['home'], top['away'], top['prob']),
            most_likely_scoreline(grid),
        )


class GoalMarketsTests(TestCase):
    def test_complementary_markets_sum_to_one(self):
        grid, _, _, _ = score_probabilities(1.6, 1.1)
        markets = goal_markets(grid)

        self.assertAlmostEqual(markets['over_2_5'] + markets['under_2_5'], 1.0, places=6)
        self.assertAlmostEqual(markets['btts_yes'] + markets['btts_no'], 1.0, places=6)

    def test_high_scoring_fixture_has_higher_over_2_5(self):
        low_grid, _, _, _ = score_probabilities(0.8, 0.4)
        high_grid, _, _, _ = score_probabilities(2.6, 1.8)

        self.assertGreater(
            goal_markets(high_grid)['over_2_5'],
            goal_markets(low_grid)['over_2_5'],
        )

    def test_clean_sheet_probability_falls_as_opponent_attack_rises(self):
        weak_opponent, _, _, _ = score_probabilities(1.5, 0.3)
        strong_opponent, _, _, _ = score_probabilities(1.5, 1.9)

        self.assertGreater(
            goal_markets(weak_opponent)['home_clean_sheet'],
            goal_markets(strong_opponent)['home_clean_sheet'],
        )


class ExpectedGoalsTests(TestCase):
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


class ComputeTeamRatingsTests(TestCase):
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


class PredictMatchTests(TestCase):
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

    def test_returns_a_normalised_scoreline_grid(self):
        Team.objects.create(name='Alpha FC')
        Team.objects.create(name='Beta FC')
        ratings, league_h, league_a = compute_team_ratings(empty_match_df())
        grid = predict_match('Alpha FC', 'Beta FC', ratings, league_h, league_a)['scoreline_grid']

        self.assertEqual(len(grid), 9)
        self.assertTrue(all(len(row) == 9 for row in grid))
        self.assertAlmostEqual(sum(sum(row) for row in grid), 1.0, places=4)

    def test_scoreline_grid_agrees_with_the_reported_win_percentages(self):
        """The Scoreline Projections tab sums this grid; it must not contradict the cards."""
        Team.objects.create(name='Alpha FC')
        Team.objects.create(name='Beta FC')
        ratings, league_h, league_a = compute_team_ratings(empty_match_df())
        result = predict_match('Alpha FC', 'Beta FC', ratings, league_h, league_a)

        grid = result['scoreline_grid']
        home_win = sum(p for h, row in enumerate(grid) for a, p in enumerate(row) if h > a)
        self.assertAlmostEqual(home_win * 100, result['home_win_pct'], places=0)


class MatchDayLockTests(TestCase):
    """
    A locked match day must be unreachable from the public page by ANY route —
    the unfiltered list, a team filter, or a direct ?match_day= request. This
    replaced an automatic reveal rule that only hid the dropdown, leaving the
    whole season readable via "All Match Days".

    The one deliberate exception is season_totals, which spans every fixture
    regardless of lock state (see views._season_totals).
    """

    def setUp(self):
        self.alpha = Team.objects.create(name='Alpha FC')
        self.beta = Team.objects.create(name='Beta FC')
        self.gamma = Team.objects.create(name='Gamma FC')

        for md, (home, away) in enumerate(
            [(self.alpha, self.beta), (self.beta, self.alpha),
             (self.alpha, self.gamma), (self.gamma, self.alpha)], start=1):
            self._fixture(md, home, away)

        # Only Match Day 1 published; 2, 3 locked; 4 has NO row at all.
        MatchDayVisibility.objects.create(season='26/27', match_day=1, is_unlocked=True)
        MatchDayVisibility.objects.create(season='26/27', match_day=2, is_unlocked=False)
        MatchDayVisibility.objects.create(season='26/27', match_day=3, is_unlocked=False)

    def _fixture(self, match_day, home, away):
        fixture = SeasonFixture.objects.create(
            season='26/27', match_day=match_day, home=home, away=away,
        )
        Prediction.objects.create(
            fixture=fixture, home_win_pct=50.0, draw_pct=30.0, away_win_pct=20.0,
            predicted_result='HOME', confidence=50.0,
            scoreline_grid=[[0.5, 0.2, 0.0], [0.2, 0.1, 0.0], [0.0, 0.0, 0.0]],
        )
        return fixture

    def _match_days(self, url):
        return sorted({r['match_day'] for r in self.client.get(url).json()['results']})

    def test_unfiltered_request_returns_only_published_match_days(self):
        self.assertEqual(self._match_days('/supercomputer/api/predictions/'), [1])
        self.assertEqual(self._match_days('/supercomputer/api/scorelines/'), [1])

    def test_team_filter_cannot_reach_locked_match_days(self):
        """Alpha plays in all four match days; only the published one may show."""
        self.assertEqual(self._match_days('/supercomputer/api/predictions/?team=Alpha FC'), [1])
        self.assertEqual(self._match_days('/supercomputer/api/scorelines/?team=Alpha FC'), [1])

    def test_requesting_a_locked_match_day_directly_returns_nothing(self):
        for md in (2, 3):
            self.assertEqual(self.client.get(f'/supercomputer/api/predictions/?match_day={md}').json()['count'], 0)
            self.assertEqual(self.client.get(f'/supercomputer/api/scorelines/?match_day={md}').json()['count'], 0)

    def test_match_day_with_no_visibility_row_is_treated_as_locked(self):
        """MD4 has no MatchDayVisibility row — absent must mean locked, not open."""
        self.assertNotIn(4, self._match_days('/supercomputer/api/predictions/'))
        self.assertEqual(self.client.get('/supercomputer/api/predictions/?match_day=4').json()['count'], 0)

    def test_non_contiguous_unlocks_are_honoured(self):
        """The admin can publish in any order — 1 and 3 open, 2 still closed."""
        MatchDayVisibility.objects.filter(match_day=3).update(is_unlocked=True)
        self.assertEqual(self._match_days('/supercomputer/api/predictions/'), [1, 3])
        self.assertEqual(self._match_days('/supercomputer/api/scorelines/'), [1, 3])
        self.assertEqual(
            self.client.get('/supercomputer/api/predictions/').json()['unlocked_match_days'],
            [1, 3],
        )

    def test_season_totals_span_every_fixture_including_locked_ones(self):
        totals = self.client.get('/supercomputer/api/predictions/').json()['season_totals']
        self.assertEqual(totals['games'], 4)      # all four, though only one is published
        self.assertEqual(totals['home'], 2)       # 4 x 50% = 2.0 expected home wins
        self.assertEqual(totals['draw'], 1)       # 4 x 30% = 1.2
        self.assertEqual(totals['away'], 1)       # 4 x 20% = 0.8

    def test_locking_everything_hides_all_fixtures(self):
        MatchDayVisibility.objects.update(is_unlocked=False)
        payload = self.client.get('/supercomputer/api/predictions/').json()
        self.assertEqual(payload['count'], 0)
        self.assertEqual(payload['unlocked_match_days'], [])
        # ...but the season totals still know about the full season, so the UI
        # can tell "nothing published yet" apart from "no predictions exist".
        self.assertEqual(payload['season_totals']['games'], 4)

    def test_both_tabs_return_the_same_fixture_set(self):
        for url in ('', '?team=Alpha FC', '?match_day=1', '?match_day=2'):
            self.assertEqual(
                self._match_days(f'/supercomputer/api/predictions/{url}'),
                self._match_days(f'/supercomputer/api/scorelines/{url}'),
                msg=f'tabs disagree for {url!r}',
            )


class PublicApiPayloadTests(TestCase):
    """
    What the public APIs expose per fixture: crest URLs in, and the internal
    `manually_edited` flag out.
    """

    def setUp(self):
        home = Team.objects.create(name='Doma United')      # crest is 'Doma United.png'
        away = Team.objects.create(name='Nonexistent Rovers')  # deliberately has none
        fixture = SeasonFixture.objects.create(
            season='26/27', match_day=1, home=home, away=away,
        )
        Prediction.objects.create(
            fixture=fixture, home_win_pct=50.0, draw_pct=30.0, away_win_pct=20.0,
            predicted_result='HOME', confidence=50.0,
            manually_edited=True,   # the flag that must NOT reach the public
            scoreline_grid=[[0.5, 0.2, 0.0], [0.2, 0.1, 0.0], [0.0, 0.0, 0.0]],
        )
        MatchDayVisibility.objects.create(season='26/27', match_day=1, is_unlocked=True)

    def _rows(self):
        return [
            self.client.get('/supercomputer/api/predictions/').json()['results'][0],
            self.client.get('/supercomputer/api/scorelines/').json()['results'][0],
        ]

    def test_both_apis_include_crest_urls(self):
        for row in self._rows():
            self.assertIsNotNone(row['home_logo'])
            self.assertIn('Doma%20United.png', row['home_logo'])

    def test_club_without_a_crest_gets_null_not_a_broken_path(self):
        """Null lets the UI fall back to an initials badge instead of a 404 image."""
        for row in self._rows():
            self.assertIsNone(row['away_logo'])

    def test_manually_edited_is_never_exposed_publicly(self):
        """
        Hiding only the UI note would leave the flag one devtools tab away, so
        the field must be absent from the payload entirely.
        """
        for row in self._rows():
            self.assertNotIn('manually_edited', row)

    def test_admin_panel_still_sees_the_edited_flag(self):
        """Removing it from the public API must not blind the admin to it."""
        from admin_panel.views import _build_predictions_data
        rows = _build_predictions_data(Prediction.objects.all())
        self.assertTrue(rows[0]['manually_edited'])


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


class DownloadButtonTests(TestCase):
    """
    The prediction and scoreline cards are built in JavaScript, not by a
    template loop, so the admin flag has to be handed to the page rather than
    wrapped around markup. These guard that plumbing.
    """

    def _html(self):
        return self.client.get(reverse('supercomputer:index')).content.decode()

    def test_admin_flag_is_false_for_the_public(self):
        self.assertIn('<script id="is-admin" type="application/json">false</script>', self._html())

    def test_admin_flag_is_true_once_signed_in(self):
        User.objects.create_user(username='owner', password='OwnerPass!2026')
        self.client.login(username='owner', password='OwnerPass!2026')
        self.assertIn('<script id="is-admin" type="application/json">true</script>', self._html())

    def test_export_libraries_are_loaded(self):
        html = self._html()
        self.assertIn('html2canvas', html)
        self.assertIn('png_export.js', html)

    def test_cards_carry_the_id_the_exporter_needs(self):
        """
        The exporter finds a card by id. Both builders derive that id from the
        Prediction primary key, so the API must keep returning it.
        """
        js = (
            Path(__file__).resolve().parent / 'static' / 'supercomputer' / 'script.js'
        ).read_text(encoding='utf-8')
        self.assertIn('card.id = `prediction-card-${p.id}`', js)
        self.assertIn('card.id = `scoreline-card-${s.id}`', js)
        self.assertIn('downloadButton(', js)

    def test_both_card_types_anchor_their_download_button(self):
        """
        .card-download-btn is position:absolute, so its card must be a
        positioned ancestor. .scoreline-card was not, and the button rendered
        into the DOM but appeared nowhere near the card — present in the HTML,
        invisible on the page, which no markup assertion would have caught.
        """
        import re

        css = (
            Path(__file__).resolve().parent / 'static' / 'supercomputer' / 'style.css'
        ).read_text(encoding='utf-8')

        for selector in ('.prediction-card', '.scoreline-card'):
            block = re.search(
                re.escape(selector) + r'\s*\{(.*?)\}', css, re.S
            )
            self.assertIsNotNone(block, selector + ' rule not found')
            self.assertIn(
                'position: relative', block.group(1),
                selector + ' must be positioned or its download button floats away',
            )

    def test_the_button_is_absolutely_positioned(self):
        css = (
            Path(__file__).resolve().parent / 'static' / 'supercomputer' / 'style.css'
        ).read_text(encoding='utf-8')
        self.assertIn('.card-download-btn', css)

    def test_buttons_use_data_attributes_not_inline_onclick(self):
        """
        The filename label is a club name. Interpolated into an inline
        handler attribute it would break on any name containing an
        apostrophe, and the hand-written escape that used to be there did
        nothing at all: in JavaScript a backslash-quote inside a
        double-quoted string is just a quote. Delegation via data
        attributes removes the whole class of bug.
        """
        import re

        js = (
            Path(__file__).resolve().parent / 'static' / 'supercomputer' / 'script.js'
        ).read_text(encoding='utf-8')

        # Strip block and line comments, which discuss the attribute by name.
        code = re.sub(r'/\*.*?\*/', '', js, flags=re.S)
        code = re.sub(r'^\s*//.*$', '', code, flags=re.M)

        # No inline handler belongs on a card button. Checked across the
        # whole file rather than per line: the button is a multi-line
        # template literal, so a stray handler can easily sit on a
        # different line from the class name.
        self.assertNotIn(
            'onclick=', code,
            'an inline onclick handler crept back into the Super Computer JS',
        )
        self.assertIn('data-dl-label', code)
        self.assertIn("closest('.card-download-btn')", code)


class CareerStatsFreshnessTests(TestCase):
    """
    get_all_career_stats used to memoise in a module global with no way to
    invalidate it, so running import_career_stats did nothing until the server
    restarted. It now reads the database every call.
    """

    def test_a_newly_imported_team_is_visible_without_a_restart(self):
        from dashboard.models import Team
        from supercomputer.models import TeamCareerStats

        self.assertEqual(ratings_module.get_all_career_stats(), {})

        team = Team.objects.create(name='Freshness FC')
        TeamCareerStats.objects.create(
            team=team, parts=2, played=10,
            home_win=3, home_draw=1, home_loss=1,
            away_win=2, away_draw=2, away_loss=1,
            home_gf=9, home_ga=4, away_gf=6, away_ga=6,
        )

        stats = ratings_module.get_all_career_stats()
        self.assertIn('freshness fc', stats)
