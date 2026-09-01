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
from dashboard.utils import team_recent_matches

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

# All-time games (home or away, counted separately) at which a team's
# TeamCareerStats ratio is trusted as a prior at face value. Below this the
# prior is itself shrunk toward league average, in proportion to how few games
# back it. Roughly one full season of home-or-away fixtures — enough that a
# promoted club with one real season counts, while a club carrying a one- or
# two-game all-time record does not get a wild prior treated as fact.
CAREER_PRIOR_FULL_CREDIBILITY_GAMES = 19.0

# A second, much faster-reacting signal layered on top of the long-run rating
# above: each team's last RECENT_FORM_GAMES completed matches (crossing season
# boundaries freely, so 1 new-season game + games from last season still fill
# the window). At a full window, recent form is blended in at
# RECENT_FORM_WEIGHT and the long-run rating only keeps (1 - RECENT_FORM_WEIGHT).
# For a team with fewer than RECENT_FORM_GAMES total completed matches ever,
# the weight is scaled down proportionally (e.g. 1 game out of 5 => 1/5 of
# RECENT_FORM_WEIGHT) so one result can't swing a brand-new club's whole
# rating.
#
# This is the weight for a fixture in the IMMEDIATE next match day. It used to
# apply unchanged to all 38 match days at once, which is why a flat 0.75
# projected a hot-starting side to ~93 season points — 16 past the best any
# NPFL team has ever managed. Form now decays with distance instead (see
# FORM_HORIZON_HALF_LIFE), so the near-term weight can stay high — recent
# results move the next match day a lot — without compounding across a season.
RECENT_FORM_GAMES = 5
RECENT_FORM_WEIGHT = 0.75

# Match days over which the recent-form weight halves. At 2.0 the next match
# day keeps ~71% of RECENT_FORM_WEIGHT, five match days out keeps ~18%, and by
# ten it is negligible — which matches how much a current hot streak really
# tells you about a fixture that far away.
FORM_HORIZON_HALF_LIFE = 2.0

# Winsorizes a single game's influence on the 5-game form average. Without
# this, one blowout scoreline (e.g. a 3-0 away win, ratio ~4.95x league
# average) can single-handedly drag the whole window's average far past any
# sustainable level — the long-run rating has FULL_CREDIBILITY_WEIGHT
# shrinkage to guard against exactly this kind of small-sample noise;
# RECENT_FORM_GAMES=5 is too small a window to rely on shrinkage alone.
# Applied symmetrically: a heavy loss is capped from cratering defense_form
# just as a heavy win is capped from inflating attack_form.
RECENT_FORM_MAX_GAME_RATIO = 2.5

TeamRating = namedtuple('TeamRating', [
    'home_attack', 'home_defense', 'away_attack', 'away_defense',
])


def get_all_career_stats():
    """{team_name_lower: TeamCareerStats}, read fresh from the database.

    This used to be memoised in a module global with no way to invalidate it,
    so running import_career_stats appeared to do nothing until the server was
    restarted. There are ~75 rows; the query costs far less than that confusion.
    """
    return {
        cs.team.name.lower(): cs
        for cs in TeamCareerStats.objects.select_related('team').all()
    }


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
    {rating_key: (raw_goals_per_game, games_behind_it)} derived from
    TeamCareerStats, or None if the team has no all-time record.

    The game count travels alongside each ratio because the prior itself has
    to be shrunk toward league average when it rests on very few games — see
    compute_team_ratings. A club whose entire all-time record is a single away
    game in which it scored 5 would otherwise be handed an away-attack prior
    of 8x league average, which its own sparse recent data can barely pull
    back and which the simulator then turns into a runaway title favourite.
    """
    career = get_team_career_stats(team_name)
    if career is None or not career.played:
        return None

    home_played = career.home_win + career.home_draw + career.home_loss
    away_played = career.away_win + career.away_draw + career.away_loss

    return {
        'home_attack': (career.home_gf / home_played, home_played) if home_played else None,
        'home_defense': (career.home_ga / home_played, home_played) if home_played else None,
        'away_attack': (career.away_gf / away_played, away_played) if away_played else None,
        'away_defense': (career.away_ga / away_played, away_played) if away_played else None,
    }


def _recent_form(df, team, league_avg_home_goals, league_avg_away_goals, n=RECENT_FORM_GAMES):
    """
    (attack_form, defense_form, sample_size) from a team's last n completed
    matches, or (None, None, 0) if the team has no completed matches in df at
    all. Both ratios use the same 1.0-==-league-average convention as the
    long-run ratings, but are pooled across home and away games into one
    unified pair rather than split by venue — a 5-game window is too sparse
    (~2-3 of each) to fit a credible separate home-only/away-only form ratio.
    """
    recent = team_recent_matches(df, team, n)
    if recent.empty:
        return None, None, 0

    attack_ratios, defense_ratios = [], []
    for _, row in recent.iterrows():
        is_home = row['home'] == team
        gf = row['home_goal'] if is_home else row['away_goal']
        ga = row['away_goal'] if is_home else row['home_goal']
        attack_ratio = gf / (league_avg_home_goals if is_home else league_avg_away_goals)
        defense_ratio = ga / (league_avg_away_goals if is_home else league_avg_home_goals)
        attack_ratios.append(min(RECENT_FORM_MAX_GAME_RATIO, attack_ratio))
        defense_ratios.append(min(RECENT_FORM_MAX_GAME_RATIO, defense_ratio))

    return (
        sum(attack_ratios) / len(attack_ratios),
        sum(defense_ratios) / len(defense_ratios),
        len(recent),
    )


def form_horizon_factor(horizon):
    """
    Fraction of the recent-form weight still applying `horizon` match days out.

    Form tells you a lot about a team's next fixture and very little about one
    eight months away, but the blend used to apply today's form at full weight
    to every remaining fixture equally. Over a 38-game season that compounded a
    hot streak into season totals no NPFL side has ever actually reached, so
    the weight now decays with distance instead.
    """
    if horizon <= 0:
        return 1.0
    return 0.5 ** (horizon / FORM_HORIZON_HALF_LIFE)


def _blend_recent_form(long_run, attack_form, defense_form, sample_size,
                       games=RECENT_FORM_GAMES, horizon=0):
    """
    Replace `long_run` with a weighted average of itself and the recent-form
    ratios — a replacement, not an accumulation. The blended value is the
    only rating expected_goals() ever sees; nothing from `long_run` survives
    separately once this returns.
    """
    if attack_form is None:
        return long_run

    w = RECENT_FORM_WEIGHT * min(1.0, sample_size / games) * form_horizon_factor(horizon)
    return TeamRating(
        home_attack=long_run.home_attack * (1 - w) + attack_form * w,
        away_attack=long_run.away_attack * (1 - w) + attack_form * w,
        home_defense=long_run.home_defense * (1 - w) + defense_form * w,
        away_defense=long_run.away_defense * (1 - w) + defense_form * w,
    )


def blend_ratings(long_run_ratings, form_signals, horizon=0):
    """
    {team: TeamRating} with recent form blended into the long-run ratings at
    the weight appropriate for a fixture `horizon` match days ahead.

    Split out from compute_team_ratings so a caller can fit the expensive
    long-run model once and then cheaply re-blend it per fixture — see
    predictor.predict_all_fixtures and simulator.run_monte_carlo_simulations.
    """
    return {
        team: _blend_recent_form(
            long_run, *form_signals.get(team, (None, None, 0)), horizon=horizon
        )
        for team, long_run in long_run_ratings.items()
    }


def compute_rating_components(df):
    """
    The pieces of the rating model, before recent form has been blended in.

    Returns:
        (long_run_ratings: dict[str, TeamRating],
         form_signals: dict[str, (attack_form, defense_form, sample_size)],
         league_avg_home_goals: float,
         league_avg_away_goals: float)

    Pair with blend_ratings() to get usable ratings at a given horizon.
    """
    completed = df.dropna(subset=['home_goal', 'away_goal']).copy()
    if completed.empty:
        return {}, {}, DEFAULT_LEAGUE_HOME_GOALS, DEFAULT_LEAGUE_AWAY_GOALS

    weights = _season_weights(completed)
    completed['_weight'] = completed['season'].map(weights)

    league_avg_home_goals = (completed['home_goal'] * completed['_weight']).sum() / completed['_weight'].sum()
    league_avg_away_goals = (completed['away_goal'] * completed['_weight']).sum() / completed['_weight'].sum()

    teams = sorted(set(completed['home'].dropna().unique()) | set(completed['away'].dropna().unique()))
    long_run_ratings = {}
    form_signals = {}

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
                career_ratio, career_games = career_prior_raw[key]
                career_prior = career_ratio / home_or_away_prior_denominator
                # The career prior is only as trustworthy as the number of
                # games behind it, so shrink it toward league average the same
                # way the team's own recent data is shrunk toward the prior.
                # Without this a one-game career record is treated as gospel.
                prior_credibility = min(1.0, career_games / CAREER_PRIOR_FULL_CREDIBILITY_GAMES)
                prior = LEAGUE_AVERAGE_RATIO + (career_prior - LEAGUE_AVERAGE_RATIO) * prior_credibility
            value = raw[key] if raw[key] is not None else prior
            return prior + (value - prior) * credibility

        long_run_ratings[team] = TeamRating(
            home_attack=shrunk('home_attack', credibility_home, league_avg_home_goals),
            home_defense=shrunk('home_defense', credibility_home, league_avg_away_goals),
            away_attack=shrunk('away_attack', credibility_away, league_avg_away_goals),
            away_defense=shrunk('away_defense', credibility_away, league_avg_home_goals),
        )
        form_signals[team] = _recent_form(
            completed, team, league_avg_home_goals, league_avg_away_goals,
        )

    return long_run_ratings, form_signals, league_avg_home_goals, league_avg_away_goals


def compute_team_ratings(df, horizon=0):
    """
    Compute recency-weighted attack/defense ratings for every team appearing
    in `df`, plus the league-wide home/away goal baselines used to normalise
    them.

    `horizon` is how many match days ahead the fixture being rated is; recent
    form fades with distance (see form_horizon_factor). The default of 0 keeps
    the full form weight, which is what a single next-match prediction wants.

    Returns:
        (ratings: dict[str, TeamRating], league_avg_home_goals: float, league_avg_away_goals: float)
    """
    long_run_ratings, form_signals, league_avg_home_goals, league_avg_away_goals = (
        compute_rating_components(df)
    )
    return (
        blend_ratings(long_run_ratings, form_signals, horizon),
        league_avg_home_goals,
        league_avg_away_goals,
    )


def last_played_match_day(season):
    """
    Highest match day with a completed fixture, or 0 if none have been played.

    This is the reference point form decays away from: a fixture on the match
    day right after it is "1 ahead", and gets nearly the full form weight.
    """
    if not season:
        return 0

    from django.db.models import Max
    from supercomputer.models import SeasonFixture

    return SeasonFixture.objects.filter(
        season=season, home_goal__isnull=False, away_goal__isnull=False,
    ).aggregate(latest=Max('match_day'))['latest'] or 0


def get_team_rating(ratings, team_name):
    """Rating for a team not seen in the fitted data (e.g. brand new club with zero rows)."""
    return ratings.get(team_name, TeamRating(
        home_attack=LEAGUE_AVERAGE_RATIO, home_defense=LEAGUE_AVERAGE_RATIO,
        away_attack=LEAGUE_AVERAGE_RATIO, away_defense=LEAGUE_AVERAGE_RATIO,
    ))
