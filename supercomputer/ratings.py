"""
NPFL Super Computer — Team Strength Ratings

Computes recency-weighted attack/defense ratings for every team from the full
Match history in one pass, shared by both predictor.py (per-match percentages)
and simulator.py (Monte Carlo season simulation) so they can no longer disagree
with each other the way the old two-model design did.

Each team gets four ratios, all normalised so 1.0 == league average:
    home_attack   — goals scored at home, relative to league avg home goals
    home_defense  — goals conceded at home, relative to league avg away goals
    away_attack   — goals scored away, relative to league avg away goals
    away_defense  — goals conceded away, relative to league avg home goals

Recent matches count more than old ones (exponential decay per season), and
teams with little/no recent data are shrunk toward a prior: their own
TeamCareerStats all-time ratio if one exists, otherwise pure league average
(1.0). Credibility scales with how much recency-weighted data a team actually
has, so a brand-new club with a real, full recent season (e.g. Kun Khalifat,
Barau) is trusted more than one with zero history anywhere (Inter Lagos).
"""

from collections import namedtuple

from supercomputer.models import TeamCareerStats

# Both tuned by backtesting against completed seasons 23/24 and 24/25,
# minimizing Brier score (probability calibration) — not "prediction
# accuracy," which is a misleading metric in a home-dominant league (see
# poisson_model.py's module docstring for why). Squads change substantially
# season to season in a promotion/relegation league, so a fairly steep decay
# (~half credibility lost every season) and a large credibility threshold
# (most teams need several full seasons of data before their own ratios are
# trusted over league average) both improved calibration over more
# conservative starting guesses.
DECAY_RATE = 0.45
LEAGUE_AVERAGE_RATIO = 1.0

# Fallback used only if there is no completed match data at all to fit from
DEFAULT_LEAGUE_HOME_GOALS = 1.52
DEFAULT_LEAGUE_AWAY_GOALS = 0.51

# Recency-weighted "match-equivalents" of data at which a team's own recent
# ratios are treated as fully credible (0 weighted matches => 0% credibility).
FULL_CREDIBILITY_WEIGHT = 200.0

TeamRating = namedtuple('TeamRating', [
    'home_attack', 'home_defense', 'away_attack', 'away_defense',
])

_CAREER_STATS_CACHE = None


def get_all_career_stats():
    """{team_name_lower: TeamCareerStats}, cached in-process for this worker."""
    global _CAREER_STATS_CACHE
    if _CAREER_STATS_CACHE is not None:
        return _CAREER_STATS_CACHE

    stats = {}
    for cs in TeamCareerStats.objects.select_related('team').all():
        stats[cs.team.name.lower()] = cs
    _CAREER_STATS_CACHE = stats
    return _CAREER_STATS_CACHE


def get_team_career_stats(team_name):
    """
    A team's TeamCareerStats row, or None if it has no all-time record
    (brand-new club, or not yet folded into the all-time tables). Absence
    does NOT imply the team has no recent Match data.
    """
    return get_all_career_stats().get(team_name.lower())


def _season_weights(df):
    """{season_label: recency_weight}, most recent season in df == weight 1.0."""
    season_order = list(dict.fromkeys(df['season']))
    max_index = len(season_order) - 1
    return {
        season: DECAY_RATE ** (max_index - idx)
        for idx, season in enumerate(season_order)
    }


def _career_prior(team_name):
    """
    (home_attack, home_defense, away_attack, away_defense) prior derived from
    TeamCareerStats, or None if the team has no all-time record.
    """
    career = get_team_career_stats(team_name)
    if career is None or not career.played:
        return None

    home_played = career.home_win + career.home_draw + career.home_loss
    away_played = career.away_win + career.away_draw + career.away_loss

    return {
        'home_attack': career.home_gf / home_played if home_played else None,
        'home_defense': career.home_ga / home_played if home_played else None,
        'away_attack': career.away_gf / away_played if away_played else None,
        'away_defense': career.away_ga / away_played if away_played else None,
    }


def compute_team_ratings(df):
    """
    Compute recency-weighted attack/defense ratings for every team appearing
    in `df`, plus the league-wide home/away goal baselines used to normalise
    them.

    Returns:
        (ratings: dict[str, TeamRating], league_avg_home_goals: float, league_avg_away_goals: float)
    """
    completed = df.dropna(subset=['home_goal', 'away_goal']).copy()
    if completed.empty:
        return {}, DEFAULT_LEAGUE_HOME_GOALS, DEFAULT_LEAGUE_AWAY_GOALS

    weights = _season_weights(completed)
    completed['_weight'] = completed['season'].map(weights)

    league_avg_home_goals = (completed['home_goal'] * completed['_weight']).sum() / completed['_weight'].sum()
    league_avg_away_goals = (completed['away_goal'] * completed['_weight']).sum() / completed['_weight'].sum()

    teams = sorted(set(completed['home'].dropna().unique()) | set(completed['away'].dropna().unique()))
    ratings = {}

    for team in teams:
        home_games = completed[completed['home'] == team]
        away_games = completed[completed['away'] == team]

        home_weight = home_games['_weight'].sum()
        away_weight = away_games['_weight'].sum()

        raw = {
            'home_attack': (home_games['home_goal'] * home_games['_weight']).sum() / home_weight / league_avg_home_goals if home_weight else None,
            'home_defense': (home_games['away_goal'] * home_games['_weight']).sum() / home_weight / league_avg_away_goals if home_weight else None,
            'away_attack': (away_games['away_goal'] * away_games['_weight']).sum() / away_weight / league_avg_away_goals if away_weight else None,
            'away_defense': (away_games['home_goal'] * away_games['_weight']).sum() / away_weight / league_avg_home_goals if away_weight else None,
        }

        career_prior_raw = _career_prior(team)
        credibility_home = min(1.0, home_weight / FULL_CREDIBILITY_WEIGHT)
        credibility_away = min(1.0, away_weight / FULL_CREDIBILITY_WEIGHT)

        def shrunk(key, credibility, home_or_away_prior_denominator):
            prior = LEAGUE_AVERAGE_RATIO
            if career_prior_raw is not None and career_prior_raw[key] is not None:
                prior = career_prior_raw[key] / home_or_away_prior_denominator
            value = raw[key] if raw[key] is not None else prior
            return prior + (value - prior) * credibility

        ratings[team] = TeamRating(
            home_attack=shrunk('home_attack', credibility_home, league_avg_home_goals),
            home_defense=shrunk('home_defense', credibility_home, league_avg_away_goals),
            away_attack=shrunk('away_attack', credibility_away, league_avg_away_goals),
            away_defense=shrunk('away_defense', credibility_away, league_avg_home_goals),
        )

    return ratings, league_avg_home_goals, league_avg_away_goals


def get_team_rating(ratings, team_name):
    """Rating for a team not seen in the fitted data (e.g. brand new club with zero rows)."""
    return ratings.get(team_name, TeamRating(
        home_attack=LEAGUE_AVERAGE_RATIO, home_defense=LEAGUE_AVERAGE_RATIO,
        away_attack=LEAGUE_AVERAGE_RATIO, away_defense=LEAGUE_AVERAGE_RATIO,
    ))
