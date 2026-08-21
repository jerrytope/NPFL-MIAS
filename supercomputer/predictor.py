"""
NPFL Super Computer — Prediction Engine

Computes win/draw/loss probabilities for each fixture using a weighted algorithm:
- 25% Recent Form (last 5 games, with 1.3x away win multiplier)
- 20% Head-to-Head Record
- 20% Home/Away Venue Strength
- 15% Goal-Scoring Form
- 20% Transfer Window & Squad Strength (from npfl_2026-27_transfer_metrics)
"""

import os
from pathlib import Path
import pandas as pd
import numpy as np
from django.conf import settings


# ---------------------------------------------------------------------------
# Constants & Weights
# ---------------------------------------------------------------------------

WEIGHT_FORM = 0.25
WEIGHT_H2H = 0.20
WEIGHT_VENUE = 0.20
WEIGHT_GOALS = 0.15
WEIGHT_TRANSFER = 0.20

AWAY_WIN_MULTIPLIER = 1.3
HOME_WIN_MULTIPLIER = 1.0

# Max possible form score: 5 wins × 3 pts × 1.3 multiplier = 19.5
MAX_FORM_SCORE = 5 * 3 * AWAY_WIN_MULTIPLIER

# Default split when no H2H history exists
DEFAULT_H2H_HOME_RATE = 0.40
DEFAULT_H2H_DRAW_RATE = 0.25
DEFAULT_H2H_AWAY_RATE = 0.35

# Fallback transfer metrics dictionary for the 2026/27 season (score out of 10.0)
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

_TRANSFER_CACHE = None


def get_all_transfer_metrics():
    """
    Load transfer metrics dictionary {team_name: float_metric} from plans file if present,
    falling back to DEFAULT_TRANSFER_METRICS.
    """
    global _TRANSFER_CACHE
    if _TRANSFER_CACHE is not None:
        return _TRANSFER_CACHE

    metrics = dict(DEFAULT_TRANSFER_METRICS)

    # Attempt to load from plans folder
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

    _TRANSFER_CACHE = metrics
    return _TRANSFER_CACHE


def get_team_transfer_rating(team_name):
    """
    Get raw transfer rating (e.g. 9.5, 4.0) for a team.
    Defaults to 5.0 (league average) if unknown.
    """
    metrics = get_all_transfer_metrics()
    return metrics.get(team_name, 5.0)


# ---------------------------------------------------------------------------
# Factor Functions
# ---------------------------------------------------------------------------

def get_team_form_score(team_name, df, n=5):
    """
    Compute weighted form score for a team from their last n completed matches.

    Returns:
        float: Normalised form score in 0-1 range.
    """
    team_games = df[(df['home'] == team_name) | (df['away'] == team_name)].copy()
    completed = team_games.dropna(subset=['home_goal', 'away_goal']).tail(n)

    if completed.empty:
        return 0.5  # League-average fallback

    score = 0.0
    for _, row in completed.iterrows():
        is_home = (row['home'] == team_name)
        team_goals = int(row['home_goal']) if is_home else int(row['away_goal'])
        opp_goals = int(row['away_goal']) if is_home else int(row['home_goal'])

        if team_goals > opp_goals:
            # Win — apply venue multiplier
            multiplier = HOME_WIN_MULTIPLIER if is_home else AWAY_WIN_MULTIPLIER
            score += 3 * multiplier
        elif team_goals == opp_goals:
            score += 1  # Draw
        # Loss = 0

    return score / MAX_FORM_SCORE


def get_h2h_record(team_a, team_b, df):
    """
    Compute head-to-head win/draw/loss rates between two teams.

    Args:
        team_a: The home team name.
        team_b: The away team name.
        df: Historical match DataFrame.

    Returns:
        tuple: (home_rate, draw_rate, away_rate) — rates from team_a's perspective.
    """
    h2h = df[
        ((df['home'] == team_a) & (df['away'] == team_b)) |
        ((df['home'] == team_b) & (df['away'] == team_a))
    ].dropna(subset=['home_goal', 'away_goal'])

    if h2h.empty:
        return (DEFAULT_H2H_HOME_RATE, DEFAULT_H2H_DRAW_RATE, DEFAULT_H2H_AWAY_RATE)

    team_a_wins = 0
    team_b_wins = 0
    draws = 0

    for _, row in h2h.iterrows():
        h_g = int(row['home_goal'])
        a_g = int(row['away_goal'])

        if h_g == a_g:
            draws += 1
        elif row['home'] == team_a:
            if h_g > a_g:
                team_a_wins += 1
            else:
                team_b_wins += 1
        else:  # row['home'] == team_b
            if h_g > a_g:
                team_b_wins += 1
            else:
                team_a_wins += 1

    total = len(h2h)
    return (team_a_wins / total, draws / total, team_b_wins / total)


def get_venue_strength(team_name, df, venue='home'):
    """
    Compute a team's historical win rate at a given venue.

    Returns:
        float: Win rate in 0-1 range.
    """
    if venue == 'home':
        venue_games = df[df['home'] == team_name].dropna(subset=['home_goal', 'away_goal'])
        if venue_games.empty:
            return 0.5
        wins = (venue_games['home_goal'] > venue_games['away_goal']).sum()
        return wins / len(venue_games)
    else:
        venue_games = df[df['away'] == team_name].dropna(subset=['home_goal', 'away_goal'])
        if venue_games.empty:
            return 0.5
        wins = (venue_games['away_goal'] > venue_games['home_goal']).sum()
        return wins / len(venue_games)


def get_goal_form(team_name, df, n=5):
    """
    Compute average goals scored and conceded in last n completed matches.

    Returns:
        tuple: (avg_scored, avg_conceded)
    """
    team_games = df[(df['home'] == team_name) | (df['away'] == team_name)].copy()
    completed = team_games.dropna(subset=['home_goal', 'away_goal']).tail(n)

    if completed.empty:
        return (1.0, 1.0)  # Neutral fallback

    scored = []
    conceded = []
    for _, row in completed.iterrows():
        is_home = (row['home'] == team_name)
        scored.append(int(row['home_goal']) if is_home else int(row['away_goal']))
        conceded.append(int(row['away_goal']) if is_home else int(row['home_goal']))

    return (np.mean(scored), np.mean(conceded))


# ---------------------------------------------------------------------------
# Prediction Functions
# ---------------------------------------------------------------------------

def predict_match(home_team, away_team, df):
    """
    Predict the outcome of a single fixture.

    Returns:
        dict with keys:
            home_win_pct, draw_pct, away_win_pct,
            predicted_result, confidence,
            home_form_score, away_form_score,
            h2h_home_rate, h2h_draw_rate, h2h_away_rate,
            home_venue_strength, away_venue_strength
    """
    # 1. Recent Form (35%)
    form_home = get_team_form_score(home_team, df)
    form_away = get_team_form_score(away_team, df)

    # 2. Head-to-Head (25%)
    h2h_home_rate, h2h_draw_rate, h2h_away_rate = get_h2h_record(home_team, away_team, df)

    # 3. Venue Strength (25%)
    venue_home = get_venue_strength(home_team, df, venue='home')
    venue_away = get_venue_strength(away_team, df, venue='away')

    # 4. Goal-Scoring Form (15%)
    scored_home, conceded_home = get_goal_form(home_team, df)
    scored_away, conceded_away = get_goal_form(away_team, df)

    # Expected goals ratio for each team
    # Home team's attack vs away team's defence, and vice versa
    home_attack = scored_home / max(conceded_away, 0.1)
    away_attack = scored_away / max(conceded_home, 0.1)
    total_attack = home_attack + away_attack
    if total_attack > 0:
        goals_home = home_attack / total_attack
        goals_away = away_attack / total_attack
    else:
        goals_home = 0.5
        goals_away = 0.5
    goals_draw = 1 - abs(goals_home - goals_away)  # Closer = more draw-like

    # Normalise goal factors
    goals_total = goals_home + goals_draw + goals_away
    if goals_total > 0:
        goals_home /= goals_total
        goals_draw /= goals_total
        goals_away /= goals_total

    # 5. Transfer Window & Squad Strength (20%)
    t_home_raw = get_team_transfer_rating(home_team)
    t_away_raw = get_team_transfer_rating(away_team)

    # Normalize 0-10 metric to 0.0-1.0
    t_home_norm = t_home_raw / 10.0
    t_away_norm = t_away_raw / 10.0

    t_diff = t_home_norm - t_away_norm
    transfer_h = (1 + t_diff) / 2
    transfer_a = (1 - t_diff) / 2
    transfer_d = 1 - abs(t_diff)
    transfer_total = transfer_h + transfer_d + transfer_a
    transfer_h /= transfer_total
    transfer_d /= transfer_total
    transfer_a /= transfer_total

    # 6. Combine & Normalise
    # Form factor: convert form difference to home/draw/away
    form_diff = form_home - form_away
    form_h = (1 + form_diff) / 2  # 0-1 scale
    form_a = (1 - form_diff) / 2
    form_d = 1 - abs(form_diff)   # More similar form = higher draw chance
    form_total = form_h + form_d + form_a
    form_h /= form_total
    form_d /= form_total
    form_a /= form_total

    raw_home = (WEIGHT_FORM * form_h +
                WEIGHT_H2H * h2h_home_rate +
                WEIGHT_VENUE * venue_home +
                WEIGHT_GOALS * goals_home +
                WEIGHT_TRANSFER * transfer_h)

    raw_away = (WEIGHT_FORM * form_a +
                WEIGHT_H2H * h2h_away_rate +
                WEIGHT_VENUE * venue_away +
                WEIGHT_GOALS * goals_away +
                WEIGHT_TRANSFER * transfer_a)

    raw_draw = (WEIGHT_FORM * form_d +
                WEIGHT_H2H * h2h_draw_rate +
                WEIGHT_VENUE * (1 - max(venue_home, venue_away)) +
                WEIGHT_GOALS * goals_draw +
                WEIGHT_TRANSFER * transfer_d)

    # Normalise to 100%
    total = raw_home + raw_draw + raw_away
    if total == 0:
        raw_home = raw_draw = raw_away = 1 / 3
        total = 1

    home_pct = round((raw_home / total) * 100, 1)
    draw_pct = round((raw_draw / total) * 100, 1)
    away_pct = round((raw_away / total) * 100, 1)

    # Ensure they sum to exactly 100% (fix rounding)
    diff = 100.0 - (home_pct + draw_pct + away_pct)
    if abs(diff) > 0.01:
        # Add the rounding difference to the largest component
        max_val = max(home_pct, draw_pct, away_pct)
        if max_val == home_pct:
            home_pct = round(home_pct + diff, 1)
        elif max_val == away_pct:
            away_pct = round(away_pct + diff, 1)
        else:
            draw_pct = round(draw_pct + diff, 1)

    # Determine prediction
    percentages = {'HOME': home_pct, 'DRAW': draw_pct, 'AWAY': away_pct}
    predicted_result = max(percentages, key=percentages.get)
    confidence = percentages[predicted_result]

    return {
        'home_win_pct': home_pct,
        'draw_pct': draw_pct,
        'away_win_pct': away_pct,
        'predicted_result': predicted_result,
        'confidence': confidence,
        'home_form_score': round(form_home, 4),
        'away_form_score': round(form_away, 4),
        'h2h_home_rate': round(h2h_home_rate, 4),
        'h2h_draw_rate': round(h2h_draw_rate, 4),
        'h2h_away_rate': round(h2h_away_rate, 4),
        'home_venue_strength': round(venue_home, 4),
        'away_venue_strength': round(venue_away, 4),
        'home_transfer_score': round(t_home_raw, 1),
        'away_transfer_score': round(t_away_raw, 1),
    }


def predict_all_fixtures(fixtures, df):
    """
    Run predictions for a list of SeasonFixture objects.

    Args:
        fixtures: QuerySet or list of SeasonFixture instances.
        df: Historical match DataFrame.

    Returns:
        list of dicts, each containing fixture + prediction data.
    """
    results = []
    for fixture in fixtures:
        home_name = fixture.home.name
        away_name = fixture.away.name

        prediction = predict_match(home_name, away_name, df)
        prediction['fixture'] = fixture
        results.append(prediction)

    return results
