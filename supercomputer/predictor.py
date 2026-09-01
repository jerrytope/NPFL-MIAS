"""
NPFL Super Computer — Prediction Engine

Computes win/draw/loss probabilities for each fixture from a single Poisson
attack/defense model (see ratings.py + poisson_model.py). This replaced an
earlier design built from six separately-weighted heuristic factors (recent
form, head-to-head, venue strength, goal form, transfer rating, all-time
pedigree) combined via hand-tuned weights and flat "boost" adjustments.

That heuristic design was retired after backtesting against completed past
seasons (23/24, 24/25 — see claude_plans/) found it was miscalibrated in ways
that kept needing new patches: a flat away-win boost inflated the predicted
away-win rate to ~18% against a real historical rate of ~9.6%, and a flat
pedigree weight measurably reduced accuracy for teams with rich recent
history. Both symptoms of the same root problem — hand-tuned weights aren't
statistically grounded. The Poisson model derives win/draw/loss probabilities
directly from each team's fitted attack/defense strength, with no separate
"boost" terms to miscalibrate.

It also unifies what used to be two disagreeing models: the old heuristic
blend drove per-match percentages and the "Predicted Standings" tab, while a
*different*, simpler ratio-based Poisson estimate in simulator.py drove the
Monte Carlo tab — they were found to disagree starkly (a team's predicted
away record differed by 6x between the two). Now both call the exact same
ratings + expected_goals() functions.
"""

from pathlib import Path
import pandas as pd
from django.conf import settings

from supercomputer.ratings import (
    blend_ratings, compute_rating_components, compute_team_ratings, get_team_rating,
    last_played_match_day,
)
from supercomputer.poisson_model import expected_goals, score_probabilities


# ---------------------------------------------------------------------------
# Transfer Window & Squad Strength ratings
# ---------------------------------------------------------------------------
# Kept as-is from the previous design: subjective/qualitative signal about
# squad strength for the upcoming season that goal history can't capture,
# most valuable for brand-new signings with no match history at all.

DEFAULT_TRANSFER_METRICS = {
    'Rivers United': 9.5,
    'Shooting Stars': 9.0,
    'Rangers International': 7.0,
    'Bendel Insurance': 6.0,
    'Ikorodu City': 6.0,
    'Kano Pillars': 6.0,
    'Sporting Lagos': 6.0,
    'Barau': 5.0,
    'Kwara United': 5.0,
    'Enyimba': 4.5,
    'Niger Tornadoes': 4.5,
    'Plateau United': 4.0,
    'Kun Khalifat': 4.0,
    'Ranchers Bees': 4.0,
    'Nasarawa United': 4.0,
    'Abia Warriors': 4.0,
    'Inter Lagos': 4.0,
    'Katsina United': 4.0,
    'Doma United': 4.0,
    'Warri Wolves': 3.0,
}


def get_all_transfer_metrics():
    """
    Load transfer metrics dictionary {team_name: float_metric} from plans file if present,
    falling back to DEFAULT_TRANSFER_METRICS.

    Read from the file on every call. This used to be memoised in a module
    global with no invalidation, so editing the transfer metrics workbook had
    no effect until the server restarted.
    """
    metrics = dict(DEFAULT_TRANSFER_METRICS)

    base_dir = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent)
    csv_path = Path(base_dir) / 'plans' / 'npfl_2026-27_transfer_metrics.csv'
    xltx_path = Path(base_dir) / 'plans' / 'npfl_2026-27_transfer_metrics.xltx'

    target_file = None
    if csv_path.exists():
        target_file = csv_path
    elif xltx_path.exists():
        target_file = xltx_path

    if target_file:
        try:
            if str(target_file).endswith('.csv'):
                df = pd.read_csv(target_file)
            else:
                df = pd.read_excel(target_file)
            if 'team' in df.columns and 'metric' in df.columns:
                for _, row in df.iterrows():
                    team = str(row['team']).strip()
                    try:
                        metrics[team] = float(row['metric'])
                    except (ValueError, TypeError):
                        pass
        except Exception:
            pass

    return metrics


def get_team_transfer_rating(team_name):
    """Raw transfer rating (e.g. 9.5, 4.0) for a team. Defaults to 5.0 (league average) if unknown."""
    metrics = get_all_transfer_metrics()
    return metrics.get(team_name, 5.0)


# ---------------------------------------------------------------------------
# Prediction Functions
# ---------------------------------------------------------------------------

def predict_match(home_team, away_team, ratings, league_avg_home_goals, league_avg_away_goals):
    """
    Predict the outcome of a single fixture from the fitted Poisson model.

    Returns:
        dict with keys:
            home_win_pct, draw_pct, away_win_pct,
            predicted_result, confidence,
            home_lambda, away_lambda,
            home_attack, home_defense, away_attack, away_defense,
            home_transfer_score, away_transfer_score,
            scoreline_grid
    """
    home_transfer_raw = get_team_transfer_rating(home_team)
    away_transfer_raw = get_team_transfer_rating(away_team)

    lambda_home, lambda_away = expected_goals(
        home_team, away_team, ratings, league_avg_home_goals, league_avg_away_goals,
        home_transfer_raw, away_transfer_raw,
    )

    grid, p_home, p_draw, p_away = score_probabilities(lambda_home, lambda_away)

    total = p_home + p_draw + p_away
    home_pct = round((p_home / total) * 100, 1)
    draw_pct = round((p_draw / total) * 100, 1)
    away_pct = round((p_away / total) * 100, 1)

    # Fix rounding so the three always sum to exactly 100%
    diff = round(100.0 - (home_pct + draw_pct + away_pct), 1)
    if abs(diff) > 0.01:
        max_val = max(home_pct, draw_pct, away_pct)
        if max_val == home_pct:
            home_pct = round(home_pct + diff, 1)
        elif max_val == away_pct:
            away_pct = round(away_pct + diff, 1)
        else:
            draw_pct = round(draw_pct + diff, 1)

    percentages = {'HOME': home_pct, 'DRAW': draw_pct, 'AWAY': away_pct}
    predicted_result = max(percentages, key=percentages.get)
    confidence = percentages[predicted_result]

    home_rating = get_team_rating(ratings, home_team)
    away_rating = get_team_rating(ratings, away_team)

    return {
        'home_win_pct': home_pct,
        'draw_pct': draw_pct,
        'away_win_pct': away_pct,
        'predicted_result': predicted_result,
        'confidence': confidence,
        'home_lambda': round(lambda_home, 3),
        'away_lambda': round(lambda_away, 3),
        'home_attack': round(home_rating.home_attack, 3),
        'home_defense': round(home_rating.home_defense, 3),
        'away_attack': round(away_rating.away_attack, 3),
        'away_defense': round(away_rating.away_defense, 3),
        'home_transfer_score': round(home_transfer_raw, 1),
        'away_transfer_score': round(away_transfer_raw, 1),
        'scoreline_grid': [[round(float(p), 6) for p in row] for row in grid],
    }


def predict_all_fixtures(fixtures, df):
    """
    Run predictions for a list of SeasonFixture objects.

    Fits the expensive long-run rating model once from `df`, then re-blends
    recent form per fixture at the weight appropriate for how far ahead that
    fixture is (see ratings.form_horizon_factor) — a match day away leans
    heavily on current form, one late in the season barely at all.

    Args:
        fixtures: QuerySet or list of SeasonFixture instances.
        df: Historical match DataFrame.

    Returns:
        list of dicts, each containing fixture + prediction data.
    """
    long_run_ratings, form_signals, league_avg_home_goals, league_avg_away_goals = (
        compute_rating_components(df)
    )

    fixtures = list(fixtures)
    reference_match_day = last_played_match_day(
        fixtures[0].season if fixtures else None
    )

    results = []
    ratings_by_horizon = {}
    for fixture in fixtures:
        horizon = max(0, fixture.match_day - reference_match_day)
        if horizon not in ratings_by_horizon:
            ratings_by_horizon[horizon] = blend_ratings(
                long_run_ratings, form_signals, horizon,
            )

        prediction = predict_match(
            fixture.home.name, fixture.away.name,
            ratings_by_horizon[horizon], league_avg_home_goals, league_avg_away_goals,
        )
        prediction['fixture'] = fixture
        results.append(prediction)

    return results
