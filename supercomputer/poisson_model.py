"""
NPFL Super Computer — Shared Poisson Scoreline Model

Single source of truth for expected goals and score probabilities. Both
predictor.py (closed-form per-match percentages) and simulator.py (Monte
Carlo season simulation, sampling random scorelines from these same lambdas)
call into this module, so they can no longer disagree with each other the
way the old two-separate-models design did.
"""

import math
import numpy as np

from supercomputer.ratings import get_team_rating

MAX_GOALS = 8

# Small multiplicative adjustment to attack strength from the transfer rating
# gap (0-10 scale). Transfer ratings are subjective/qualitative signal that
# goal history can't capture — most valuable for brand-new signings with
# little or no match history, where the ratings model alone has nothing to
# go on. Deliberately small relative to the ratings model itself.
TRANSFER_ADJUSTMENT_MAX = 0.20

# Realistic bounds so a single extreme fixture can't produce a degenerate lambda
MIN_LAMBDA_HOME = 0.15
MAX_LAMBDA_HOME = 4.5
MIN_LAMBDA_AWAY = 0.10
MAX_LAMBDA_AWAY = 3.5

# A draw-inflation correction (the standard Dixon-Coles motivation — plain
# independent Poisson often under-predicts draws) was tried and rejected here.
# It looked necessary when judged by "how often is DRAW the single most-likely
# outcome" (near 0% uninflated), but that's the wrong test in a home-dominant
# league: HOME being the plurality pick in most individual matches is CORRECT
# behavior when home really does win ~2/3 of games, not a sign of miscalibrated
# draw probability. Judged properly (Brier score against 23/24+24/25), any
# inflation made calibration strictly worse — the uninflated model was best.


def transfer_adjustment(team_transfer_rating, opponent_transfer_rating):
    """Multiplicative attack adjustment from the transfer-rating gap (0-10 scale)."""
    diff = (team_transfer_rating - opponent_transfer_rating) / 10.0
    return 1.0 + diff * TRANSFER_ADJUSTMENT_MAX


def expected_goals(home_team, away_team, ratings, league_avg_home_goals, league_avg_away_goals,
                    home_transfer_rating, away_transfer_rating):
    """Compute (lambda_home, lambda_away) for a fixture from fitted team ratings."""
    home_rating = get_team_rating(ratings, home_team)
    away_rating = get_team_rating(ratings, away_team)

    home_adj = transfer_adjustment(home_transfer_rating, away_transfer_rating)
    away_adj = transfer_adjustment(away_transfer_rating, home_transfer_rating)

    lambda_home = league_avg_home_goals * home_rating.home_attack * away_rating.away_defense * home_adj
    lambda_away = league_avg_away_goals * away_rating.away_attack * home_rating.home_defense * away_adj

    lambda_home = max(MIN_LAMBDA_HOME, min(MAX_LAMBDA_HOME, lambda_home))
    lambda_away = max(MIN_LAMBDA_AWAY, min(MAX_LAMBDA_AWAY, lambda_away))

    return lambda_home, lambda_away


def _poisson_pmf_vector(lam, max_goals=MAX_GOALS):
    """P(X=k) for k=0..max_goals, X ~ Poisson(lam)."""
    ks = np.arange(max_goals + 1)
    factorials = np.array([math.factorial(int(k)) for k in ks], dtype=float)
    return np.exp(-lam) * (lam ** ks) / factorials


def score_probabilities(lambda_home, lambda_away, max_goals=MAX_GOALS):
    """
    Full P(home_goals=h, away_goals=a) grid via independent Poisson (renormalised
    for the truncated tail beyond max_goals), plus the summed (p_home, p_draw, p_away).
    """
    home_pmf = _poisson_pmf_vector(lambda_home, max_goals)
    away_pmf = _poisson_pmf_vector(lambda_away, max_goals)
    grid = np.outer(home_pmf, away_pmf)
    grid = grid / grid.sum()

    rows, cols = np.indices(grid.shape)
    p_home = float(grid[rows > cols].sum())
    p_draw = float(grid[rows == cols].sum())
    p_away = float(grid[rows < cols].sum())

    return grid, p_home, p_draw, p_away


def top_scorelines(grid, n=5):
    """
    The n most likely exact scorelines, highest probability first.

    Returns a list of {'home': int, 'away': int, 'prob': float}. Note that in a
    low-scoring, home-dominant league the single top scoreline carries very
    little information — 1-0 is the peak for ~86% of NPFL fixtures at only ~20%
    probability. It's the shape of the top few, and the goal markets derived
    from the same grid, that actually distinguish one fixture from another.
    """
    flat_order = np.argsort(grid, axis=None)[::-1][:n]
    return [
        {'home': int(h), 'away': int(a), 'prob': float(grid[h, a])}
        for h, a in zip(*np.unravel_index(flat_order, grid.shape))
    ]


def most_likely_scoreline(grid):
    """(home_goals, away_goals, probability) of the single most likely exact scoreline."""
    top = top_scorelines(grid, 1)[0]
    return top['home'], top['away'], top['prob']


def goal_markets(grid):
    """
    Goal-based market probabilities summed from the same scoreline grid, so they
    can never disagree with the scorelines shown alongside them.

    Returns floats in [0, 1] for over/under 2.5 goals, both-teams-to-score, and
    each side keeping a clean sheet.
    """
    rows, cols = np.indices(grid.shape)
    totals = rows + cols

    return {
        'over_2_5': float(grid[totals > 2].sum()),
        'under_2_5': float(grid[totals <= 2].sum()),
        'btts_yes': float(grid[(rows > 0) & (cols > 0)].sum()),
        'btts_no': float(grid[(rows == 0) | (cols == 0)].sum()),
        'home_clean_sheet': float(grid[cols == 0].sum()),
        'away_clean_sheet': float(grid[rows == 0].sum()),
    }
