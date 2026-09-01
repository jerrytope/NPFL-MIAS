"""
NPFL Super Computer — Monte Carlo Simulation Engine

Simulates many independent 380-match seasons using:
- The same fitted Poisson attack/defense ratings and expected-goals function
  that drive per-match predictions (supercomputer/ratings.py + poisson_model.py)
  — previously this engine used a separate, simpler ratio-based lambda
  estimate than predictor.py's heuristic blend, and the two were found to
  disagree starkly (a team's predicted away record differed by ~6x between
  them). Both now derive from one calibrated model.
- Dynamic in-season momentum with a 1.3x away-win confidence booster
- Official NPFL tie-breaking: Points -> Goal Difference (GD) -> Goals For (GF)

Saves results into TeamSeasonProjection (leaves match predictions 100% untouched).
"""

from collections import defaultdict
import numpy as np
from django.db import transaction

from dashboard.utils import get_npfl_data
from dashboard.models import Team
from supercomputer.models import SeasonFixture, TeamSeasonProjection
from supercomputer.ratings import blend_ratings, compute_rating_components
from supercomputer.poisson_model import (
    expected_goals, MIN_LAMBDA_HOME, MAX_LAMBDA_HOME, MIN_LAMBDA_AWAY, MAX_LAMBDA_AWAY,
)
from supercomputer.predictor import get_team_transfer_rating


def calculate_match_expected_goals(home_team, away_team, ratings, league_avg_home_goals, league_avg_away_goals):
    """Thin wrapper over the shared expected_goals() model (see poisson_model.py)."""
    return expected_goals(
        home_team, away_team, ratings, league_avg_home_goals, league_avg_away_goals,
        get_team_transfer_rating(home_team), get_team_transfer_rating(away_team),
    )


def _apply_result(table, momentum, h, a, gh, ga):
    """
    Mutate `table`/`momentum` in place for one fixture's (gh, ga) result.
    Shared by the deterministic pre-pass over already-played fixtures and the
    per-iteration random draws over unplayed ones, so both use identical
    scoring/momentum rules.
    """
    table[h]['gf'] += gh
    table[h]['ga'] += ga
    table[a]['gf'] += ga
    table[a]['ga'] += gh

    if gh > ga:
        # Home Win
        table[h]['points'] += 3
        table[h]['won'] += 1
        table[a]['lost'] += 1

        # Momentum: Home win bonus, away loss penalty
        momentum[h] = min(1.25, momentum[h] + 0.05)
        momentum[a] = max(0.80, momentum[a] - 0.04)

    elif gh < ga:
        # Away Win — Crucial 1.3x momentum booster
        table[a]['points'] += 3
        table[a]['won'] += 1
        table[h]['lost'] += 1

        # Momentum: 1.3x booster for away victory!
        momentum[a] = min(1.35, momentum[a] * 1.30)
        momentum[h] = max(0.78, momentum[h] - 0.06)

    else:
        # Draw
        table[h]['points'] += 1
        table[a]['points'] += 1
        table[h]['drawn'] += 1
        table[a]['drawn'] += 1

        # Momentum decays toward 1.0
        momentum[h] = 1.0 + (momentum[h] - 1.0) * 0.5
        momentum[a] = 1.0 + (momentum[a] - 1.0) * 0.5


def run_monte_carlo_simulations(season='26/27', iterations=1000, df=None):
    """
    Execute 1,000 full-season simulations and aggregate all probabilistic metrics.

    Returns:
        list: projections list sorted by xPts (descending)
    """
    if df is None:
        df = get_npfl_data(force_refresh=False)

    fixtures = list(
        SeasonFixture.objects.filter(season=season)
        .select_related('home', 'away')
        .order_by('match_day', 'id')
    )

    if not fixtures:
        raise ValueError(f"No fixtures found for season {season}")

    # Unique teams participating
    team_names = sorted(list(set(
        [f.home.name for f in fixtures] + [f.away.name for f in fixtures]
    )))
    total_teams = len(team_names)

    # Fit the expensive long-run model once, then re-blend recent form per
    # horizon below — cheap, and it keeps a hot streak from being projected at
    # full strength onto fixtures eight months away.
    long_run_ratings, form_signals, league_avg_home_goals, league_avg_away_goals = (
        compute_rating_components(df)
    )

    # Already-played fixtures have a real, known score — lock those in instead
    # of re-simulating them every iteration. Only fixtures still to be played
    # need a predicted lambda and a random draw per simulation.
    played_fixtures = [f for f in fixtures if f.is_played]
    unplayed_fixtures = [f for f in fixtures if not f.is_played]

    reference_match_day = max(
        (f.match_day for f in played_fixtures), default=0
    )

    fixture_lambdas = {}
    ratings_by_horizon = {}
    for f in unplayed_fixtures:
        horizon = max(0, f.match_day - reference_match_day)
        if horizon not in ratings_by_horizon:
            ratings_by_horizon[horizon] = blend_ratings(long_run_ratings, form_signals, horizon)

        lh, la = calculate_match_expected_goals(
            f.home.name, f.away.name, ratings_by_horizon[horizon],
            league_avg_home_goals, league_avg_away_goals,
        )
        fixture_lambdas[f.id] = (lh, la)

    # Deterministic base state from real results, computed once (not per
    # iteration): banked points/gf/ga plus the real momentum those results
    # produced, so the simulated remainder of the season starts from what's
    # actually known rather than from a fictional neutral restart.
    base_table = {t: {'points': 0, 'gf': 0, 'ga': 0, 'gd': 0, 'won': 0, 'drawn': 0, 'lost': 0} for t in team_names}
    base_momentum = {t: 1.0 for t in team_names}
    for f in played_fixtures:
        _apply_result(base_table, base_momentum, f.home.name, f.away.name, f.home_goal, f.away_goal)

    # Accumulators across all simulations
    team_sim_points = defaultdict(list)
    team_sim_gd = defaultdict(list)
    team_sim_gf = defaultdict(list)
    team_sim_rank = defaultdict(list)
    team_title_count = defaultdict(int)
    team_top3_count = defaultdict(int)
    team_relegation_count = defaultdict(int)

    # Run 1,000 independent season simulations
    for sim_idx in range(iterations):
        # In-season state for this run, seeded from the real, already-played
        # results — only the unplayed fixtures below are actually random.
        table = {t: dict(v) for t, v in base_table.items()}
        momentum = dict(base_momentum)

        for f in unplayed_fixtures:
            fid = f.id
            h = f.home.name
            a = f.away.name

            base_lh, base_la = fixture_lambdas[fid]
            # Momentum must respect the same "realistic bounds" expected_goals()
            # already clips to — otherwise a fixture already near the cap can
            # get pushed past it by the momentum multiplier (e.g. a base_lh at
            # 4.5 times a 1.25x home-win-streak momentum would reach 5.625).
            sim_lh = max(MIN_LAMBDA_HOME, min(MAX_LAMBDA_HOME, base_lh * momentum[h]))
            sim_la = max(MIN_LAMBDA_AWAY, min(MAX_LAMBDA_AWAY, base_la * momentum[a]))

            # Draw discrete goals from Poisson distribution
            gh = int(np.random.poisson(sim_lh))
            ga = int(np.random.poisson(sim_la))

            _apply_result(table, momentum, h, a, gh, ga)

        # Calculate final goal difference
        for t in team_names:
            table[t]['gd'] = table[t]['gf'] - table[t]['ga']

        # Official NPFL tie-break sorting: Points (desc), GD (desc), GF (desc)
        sorted_season = sorted(
            team_names,
            key=lambda t: (-table[t]['points'], -table[t]['gd'], -table[t]['gf'])
        )

        for pos, t in enumerate(sorted_season, start=1):
            pts = table[t]['points']
            gd = table[t]['gd']
            gf = table[t]['gf']

            team_sim_points[t].append(pts)
            team_sim_gd[t].append(gd)
            team_sim_gf[t].append(gf)
            team_sim_rank[t].append(pos)

            if pos == 1:
                team_title_count[t] += 1
            if pos <= 3:
                team_top3_count[t] += 1
            if pos > (total_teams - 4):  # Bottom 4 teams (17, 18, 19, 20)
                team_relegation_count[t] += 1

    # Aggregate final projections per team
    projections = []
    for t in team_names:
        pts_list = team_sim_points[t]
        gd_list = team_sim_gd[t]
        rank_list = team_sim_rank[t]

        projections.append({
            'team': t,
            'title_pct': round((team_title_count[t] / iterations) * 100, 1),
            'top3_pct': round((team_top3_count[t] / iterations) * 100, 1),
            'relegation_pct': round((team_relegation_count[t] / iterations) * 100, 1),
            'expected_points': round(float(np.mean(pts_list)), 1),
            'best_points': int(np.percentile(pts_list, 95)),
            'worst_points': int(np.percentile(pts_list, 5)),
            'avg_goal_diff': round(float(np.mean(gd_list)), 1),
            'avg_position': round(float(np.mean(rank_list)), 1),
            'simulations_count': iterations,
        })

    # Sort projections by expected_points (desc), then avg_goal_diff (desc)
    projections.sort(key=lambda p: (-p['expected_points'], -p['avg_goal_diff']))

    return projections


def save_simulation_results(season, projections):
    """
    Save simulation projections to TeamSeasonProjection.
    Leaves Prediction table 100% untouched.
    """
    with transaction.atomic():
        for p in projections:
            team_obj = Team.objects.get(name=p['team'])
            TeamSeasonProjection.objects.update_or_create(
                season=season,
                team=team_obj,
                defaults={
                    'title_pct': p['title_pct'],
                    'top3_pct': p['top3_pct'],
                    'relegation_pct': p['relegation_pct'],
                    'expected_points': p['expected_points'],
                    'best_points': p['best_points'],
                    'worst_points': p['worst_points'],
                    'avg_goal_diff': p['avg_goal_diff'],
                    'avg_position': p['avg_position'],
                    'simulations_count': p['simulations_count'],
                }
            )
