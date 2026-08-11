import os
import traceback
from pathlib import Path
import pandas as pd
import numpy as np
from anthropic import Anthropic
from django.core.cache import cache

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / '.env'


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
    Load NPFL data from the local Django database and cache it in memory.
    If force_refresh is True, bypass the cache and rebuild it from the DB.
    """
    data = None if force_refresh else cache.get('npfl_all_time_data_db')

    # Prefer DB-backed data when available
    if data is None:
        try:
            from dashboard.models import Match

            if Match.objects.exists():
                qs = Match.objects.select_related('home', 'away').all()
                rows = []
                for m in qs:
                    rows.append({
                        'season': m.season,
                        'match_name': m.match_name,
                        'home': m.home.name if m.home else None,
                        'away': m.away.name if m.away else None,
                        'home_goal': m.home_goal,
                        'away_goal': m.away_goal,
                        'date': m.date,
                        'stadium': m.stadium,
                    })
                df = pd.DataFrame(rows)
                # Ensure numeric types
                if 'home_goal' in df.columns:
                    df['home_goal'] = pd.to_numeric(df['home_goal'], errors='coerce')
                if 'away_goal' in df.columns:
                    df['away_goal'] = pd.to_numeric(df['away_goal'], errors='coerce')

                cache.set('npfl_all_time_data_db', df, 86400)
                data = df
        except Exception:
            data = None

    # If DB fetch failed or there are no Match rows, surface an error
    if data is None:
        raise ValueError('No match data available in the database. Run the importer to populate Match records.')
    return data

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
