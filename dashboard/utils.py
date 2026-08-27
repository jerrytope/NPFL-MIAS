import datetime
import os
import traceback
from pathlib import Path
import pandas as pd
import numpy as np
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / '.env'

# The results workbook's 'season' column has gone through two rounds of Excel
# corruption: short codes like "02/03" were first misread as dates with no
# year (e.g. "2026-02-03"), then a manual fix reformatted those dates back to
# text but kept the stray "2026" year, producing "MM/26" labels instead of
# the true season code. Row counts confirm these are the same 9 real
# seasons, just mislabeled, so the remap is a straight lookup.
SEASON_REMAP = {
    '02/26': '02/03',
    '03/26': '03/04',
    '04/26': '04/05',
    '07/26': '07/08',
    '08/26': '08/09',
    '09/26': '09/10',
    '10/26': '10/11',
    '11/26': '11/12',
    '12/26': '12/13',
}


def normalize_season(value):
    """
    Normalize a raw 'season' cell from the results workbook to a clean
    season code, undoing known Excel corruption patterns.
    """
    if isinstance(value, datetime.date):
        # Covers datetime.date, datetime.datetime, and pd.Timestamp
        return f"{value.month:02d}/{value.day:02d}"

    text = str(value).strip()
    return SEASON_REMAP.get(text, text)


def load_dotenv(dotenv_path=None):
    path = Path(dotenv_path or DOTENV_PATH)
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()
ANTHROPIC_BASE_URL = os.getenv('ANTHROPIC_BASE_URL', 'https://agentrouter.org')
ANTHROPIC_FALLBACK_BASE_URL = os.getenv('ANTHROPIC_FALLBACK_BASE_URL', 'https://ps.air-outer.com')
ANTHROPIC_BASE_URLS = [
    ANTHROPIC_BASE_URL,
    ANTHROPIC_FALLBACK_BASE_URL,
]
ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-opus-4-8')
ANTHROPIC_MAX_TOKENS = int(os.getenv('ANTHROPIC_MAX_TOKENS', '3000'))


def get_agentrouter_api_key():
    api_key = os.getenv('ANTHROPIC_API_KEY', '').strip() or os.getenv('AGENTROUTER_API_KEY', '').strip()
    if not api_key:
        raise ValueError(
            'Anthropic/AgentRouter API key is not configured. Set ANTHROPIC_API_KEY or AGENTROUTER_API_KEY in your environment or .env before generating reports.'
        )
    return api_key

def get_npfl_data(force_refresh=False):
    """
    Load every NPFL match from the database as a DataFrame.

    Read fresh on every call. There used to be a 24-hour LocMem cache here,
    which is why edits took a day to appear — and worse, LocMem is per-process,
    so under gunicorn one worker could serve stale rows long after another had
    been refreshed.

    Caching is unnecessary now: `.values()` returns plain rows straight from the
    database instead of building ~8,000 Match and Team model instances that are
    immediately discarded, which is about four times faster (105ms vs 426ms on
    the current dataset). This is called once per comparison request.

    `force_refresh` is kept because eight call sites pass it, but every read is
    already fresh, so it does nothing.
    """
    from dashboard.models import Match

    if not Match.objects.exists():
        raise ValueError('No match data available in the database. Run the importer to populate Match records.')

    # order_by('id') states what the code already relied on: rows are inserted
    # in match order by the Excel importer and appended by the admin, so id
    # order IS chronological. Match.date is empty, so it cannot be used, and an
    # unordered queryset has no guaranteed SQL order at all — losing that order
    # would silently scramble every "last 5" form guide.
    qs = Match.objects.order_by('id').values(
        'season', 'match_name', 'home__name', 'away__name',
        'home_goal', 'away_goal', 'date', 'stadium',
    )
    df = pd.DataFrame.from_records(qs)
    if df.empty:
        raise ValueError('No match data available in the database. Run the importer to populate Match records.')

    df = df.rename(columns={'home__name': 'home', 'away__name': 'away'})
    df['home_goal'] = pd.to_numeric(df['home_goal'], errors='coerce')
    df['away_goal'] = pd.to_numeric(df['away_goal'], errors='coerce')
    return df

def get_unique_teams():
    """
    Get a sorted list of all unique teams.
    """
    try:
        df = get_npfl_data()
        home_teams = df['home'].dropna().unique()
        away_teams = df['away'].dropna().unique()
        all_teams = sorted(list(set(home_teams) | set(away_teams)))
        return all_teams
    except Exception:
        return []

def get_all_seasons():
    """
    Get a sorted list of all season codes present in the match data.
    """
    try:
        df = get_npfl_data()
        return sorted(df['season'].dropna().unique().tolist())
    except Exception:
        return []

def get_team_home_away_splits(season=None):
    """
    Compute each team's real home/away Played/Win/Draw/Loss/Goals counts from
    completed matches, plus season totals and points, optionally restricted
    to a single season.
    """
    df = get_npfl_data()
    df = df.dropna(subset=['home_goal', 'away_goal'])
    if season:
        df = df[df['season'] == season]

    splits = []
    for team in get_unique_teams():
        home_df = df[df['home'] == team]
        away_df = df[df['away'] == team]

        home_win = int((home_df['home_goal'] > home_df['away_goal']).sum())
        home_draw = int((home_df['home_goal'] == home_df['away_goal']).sum())
        home_loss = int((home_df['home_goal'] < home_df['away_goal']).sum())
        home_gf = int(home_df['home_goal'].sum())
        home_ga = int(home_df['away_goal'].sum())

        away_win = int((away_df['away_goal'] > away_df['home_goal']).sum())
        away_draw = int((away_df['away_goal'] == away_df['home_goal']).sum())
        away_loss = int((away_df['away_goal'] < away_df['home_goal']).sum())
        away_gf = int(away_df['away_goal'].sum())
        away_ga = int(away_df['home_goal'].sum())

        total_win = home_win + away_win
        total_draw = home_draw + away_draw
        total_loss = home_loss + away_loss
        total_gf = home_gf + away_gf
        total_ga = home_ga + away_ga

        splits.append({
            'team': team,
            'home_played': len(home_df),
            'home_win': home_win,
            'home_draw': home_draw,
            'home_loss': home_loss,
            'home_gf': home_gf,
            'home_ga': home_ga,
            'away_played': len(away_df),
            'away_win': away_win,
            'away_draw': away_draw,
            'away_loss': away_loss,
            'away_gf': away_gf,
            'away_ga': away_ga,
            'total_win': total_win,
            'total_draw': total_draw,
            'total_loss': total_loss,
            'total_gf': total_gf,
            'total_ga': total_ga,
            'total_gd': total_gf - total_ga,
            'points': total_win * 3 + total_draw,
        })

    return splits

def determine_match_result(row, team):
    """
    Determine W/D/L for a team in a given match row.
    """
    if pd.isna(row['home_goal']) or pd.isna(row['away_goal']):
        return None
    
    home_g = int(row['home_goal'])
    away_g = int(row['away_goal'])
    
    if row['home'] == team:
        if home_g > away_g:
            return 'W'
        elif home_g < away_g:
            return 'L'
        else:
            return 'D'
    elif row['away'] == team:
        if away_g > home_g:
            return 'W'
        elif away_g < home_g:
            return 'L'
        else:
            return 'D'
    return None

def get_team_form(df, team, n=5):
    """
    Retrieve the last n completed matches for a team and compute their form string (e.g. WWDLD).
    """
    team_games = df[(df['home'] == team) | (df['away'] == team)].copy()
    completed = team_games.dropna(subset=['home_goal', 'away_goal']).tail(n)
    
    results = []
    games_list = []
    for idx, row in completed.iterrows():
        res = determine_match_result(row, team)
        results.append(res)
        games_list.append({
            'season': str(row['season']),
            'home': row['home'],
            'away': row['away'],
            'home_goal': int(row['home_goal']),
            'away_goal': int(row['away_goal']),
            'result': res
        })
    
    form_string = ''.join([r for r in results if r])
    return form_string, games_list

def perform_comparison(team1, team2):
    """
    Perform a complete head-to-head analysis between team1 and team2.
    """
    df = get_npfl_data()
    
    # Filter matches between team1 and team2
    h2h_df = df[((df['home'] == team1) & (df['away'] == team2)) | 
                ((df['home'] == team2) & (df['away'] == team1))].copy()
    
    # Exclude matches that are not played yet (missing scores)
    completed_h2h = h2h_df.dropna(subset=['home_goal', 'away_goal']).copy()
    
    # 1. H2H record counts
    team1_wins = 0
    team2_wins = 0
    draws = 0
    
    for idx, row in completed_h2h.iterrows():
        h_g = int(row['home_goal'])
        a_g = int(row['away_goal'])
        if h_g == a_g:
            draws += 1
        elif row['home'] == team1:
            if h_g > a_g:
                team1_wins += 1
            else:
                team2_wins += 1
        elif row['home'] == team2:
            if h_g > a_g:
                team2_wins += 1
            else:
                team1_wins += 1
                
    total_matches = len(completed_h2h)
    
    # 2. Total Goals Scored against each other
    team1_goals = 0
    team2_goals = 0
    
    for idx, row in completed_h2h.iterrows():
        h_g = int(row['home_goal'])
        a_g = int(row['away_goal'])
        if row['home'] == team1:
            team1_goals += h_g
            team2_goals += a_g
        else:
            team2_goals += h_g
            team1_goals += a_g
            
    # 3. Average goals
    avg_scored_t1 = team1_goals / total_matches if total_matches > 0 else 0.0
    avg_conceded_t1 = team2_goals / total_matches if total_matches > 0 else 0.0
    avg_scored_t2 = team2_goals / total_matches if total_matches > 0 else 0.0
    avg_conceded_t2 = team1_goals / total_matches if total_matches > 0 else 0.0
    
    # 4. Goals Distribution by Season
    # Sum the goals for each season in matches between the two
    completed_h2h['total_goals'] = completed_h2h['home_goal'] + completed_h2h['away_goal']
    season_goals = completed_h2h.groupby('season')['total_goals'].sum().reset_index()
    season_goals['total_goals'] = season_goals['total_goals'].astype(int)
    season_goals_sorted = season_goals.sort_values(by='total_goals', ascending=False).to_dict(orient='records')
    
    # 5. Goals Distribution by Season per Team
    # We want to see how many goals team1 scored and team2 scored in each season
    team1_season_goals = {}
    team2_season_goals = {}
    all_seasons = sorted(completed_h2h['season'].unique())
    
    for season in all_seasons:
        t1_s_g = 0
        t2_s_g = 0
        season_matches = completed_h2h[completed_h2h['season'] == season]
        for idx, row in season_matches.iterrows():
            h_g = int(row['home_goal'])
            a_g = int(row['away_goal'])
            if row['home'] == team1:
                t1_s_g += h_g
                t2_s_g += a_g
            else:
                t2_s_g += h_g
                t1_s_g += a_g
        team1_season_goals[season] = t1_s_g
        team2_season_goals[season] = t2_s_g
        
    # Get last 10 seasons for the side-by-side comparison
    last_10_seasons = all_seasons[-10:]
    goals_per_team_season = []
    for s in last_10_seasons:
        goals_per_team_season.append({
            'season': s,
            f'{team1}_goals': team1_season_goals.get(s, 0),
            f'{team2}_goals': team2_season_goals.get(s, 0)
        })
        
    # 6. Team Forms (Overall)
    t1_form_str, t1_recent_games = get_team_form(df, team1)
    t2_form_str, t2_recent_games = get_team_form(df, team2)
    
    # 7. Raw match details
    raw_matches = []
    for idx, row in completed_h2h.iterrows():
        raw_matches.append({
            'season': str(row['season']),
            'home': row['home'],
            'away': row['away'],
            'home_goal': int(row['home_goal']),
            'away_goal': int(row['away_goal']),
            'match_name': row.get('match_name', f"{row['home']} vs {row['away']}")
        })
        
    # Reverse raw_matches to show latest first
    raw_matches.reverse()
    
    return {
        'team1': team1,
        'team2': team2,
        'total_matches': total_matches,
        'team1_wins': team1_wins,
        'team2_wins': team2_wins,
        'draws': draws,
        'team1_goals': team1_goals,
        'team2_goals': team2_goals,
        'avg_scored_t1': avg_scored_t1,
        'avg_conceded_t1': avg_conceded_t1,
        'avg_scored_t2': avg_scored_t2,
        'avg_conceded_t2': avg_conceded_t2,
        'season_goals': season_goals_sorted,
        'goals_per_team_season': goals_per_team_season,
        'team1_form': t1_form_str,
        'team1_recent_games': t1_recent_games,
        'team2_form': t2_form_str,
        'team2_recent_games': t2_recent_games,
        'raw_matches': raw_matches
    }


def _format_recent_games(games):
    if not games:
        return 'No recent completed games available.'

    lines = []
    for game in games[:5]:
        lines.append(
            f"{game['season']}: {game['home']} {game['home_goal']}-{game['away_goal']} {game['away']} ({game['result']})"
        )
    return '\n'.join(lines)


def generate_expert_report(team1, team2, comparison_data):
    api_key = get_agentrouter_api_key()

    recent_team1 = _format_recent_games(comparison_data.get('team1_recent_games', []))
    recent_team2 = _format_recent_games(comparison_data.get('team2_recent_games', []))
    season_summaries = comparison_data.get('season_goals', [])[:5]
    season_summary_text = ', '.join(
        [f"{item['season']} ({item['total_goals']} goals)" for item in season_summaries]
    ) or 'No season goal summary available.'

    prompt = f"""
You are a veteran BBC football analyst with 20 years of NPFL coverage, writing for a Nigerian audience. You know the history, culture, and tactical flavor of the league.

Write a polished expert report for a head-to-head analysis between {team1} and {team2}. Use the facts below and frame the narrative around rivalry, recent form, scoring patterns, and the tactical outlook for both teams.

Facts:
- Total H2H matches: {comparison_data['total_matches']}
- {team1} wins: {comparison_data['team1_wins']}
- {team2} wins: {comparison_data['team2_wins']}
- Draws: {comparison_data['draws']}
- Goals scored by {team1}: {comparison_data['team1_goals']}
- Goals scored by {team2}: {comparison_data['team2_goals']}
- {team1} average goals scored: {comparison_data['avg_scored_t1']:.2f}
- {team1} average goals conceded: {comparison_data['avg_conceded_t1']:.2f}
- {team2} average goals scored: {comparison_data['avg_scored_t2']:.2f}
- {team2} average goals conceded: {comparison_data['avg_conceded_t2']:.2f}
- {team1} recent form: {comparison_data['team1_form']}
- {team2} recent form: {comparison_data['team2_form']}
- Top seasons by H2H goals: {season_summary_text}

Recent form details for {team1}:
{recent_team1}

Recent form details for {team2}:
{recent_team2}

Write the report in engaging BBC analyst prose. Avoid generic filler; make it feel specific to the NPFL and these two teams.
"""

    last_exception = None
    for base_url in ANTHROPIC_BASE_URLS:
        try:
            client = Anthropic(api_key=api_key, base_url=base_url)
            response = client.messages.create(
                model=ANTHROPIC_MODEL,
                # Claude Opus 5 may spend part of its output budget on reasoning.
                # 700 tokens can be exhausted by a ThinkingBlock before any report
                # text is emitted, so leave room for both thinking and the report.
                max_tokens=ANTHROPIC_MAX_TOKENS,
                temperature=0.8,
                system='You are a BBC football analyst with extensive NPFL expertise.',
                messages=[
                    {
                        'role': 'user',
                        'content': prompt
                    }
                ],
            )

            report_text = ''
            if hasattr(response, 'content'):
                content = response.content
                if isinstance(content, str):
                    report_text = content
                elif isinstance(content, list):
                    for block in content:
                        if hasattr(block, 'text') and block.text:
                            report_text = block.text
                            break
                        if isinstance(block, dict) and block.get('text'):
                            report_text = block['text']
                            break
                elif isinstance(content, dict):
                    report_text = content.get('text', '') or content.get('content', '')

            if not report_text and isinstance(response, dict):
                report_text = response.get('content', '')
                if isinstance(report_text, list):
                    for block in report_text:
                        if isinstance(block, dict) and block.get('text'):
                            report_text = block['text']
                            break
                    else:
                        report_text = ''

            report_text = report_text.strip() if isinstance(report_text, str) else ''

            if not report_text:
                raise ValueError('Anthropic returned an empty report.')

            return report_text
        except Exception as exc:
            last_exception = exc
            continue

    error_details = ''.join(traceback.format_exception_only(type(last_exception), last_exception)).strip()
    raise ValueError(f'Could not generate report via Anthropic/AgentRouter. Last error: {error_details}')
