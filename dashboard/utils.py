import pandas as pd
import numpy as np
import requests
from django.core.cache import cache

DOCUMENT_ID = '1rlP9mSfvJE73xK6Q5ddtDnk67U6D1DjVsJH-1dIXOXk'
SHEET_NAME = 'All-Time-Results'
URL = f'https://docs.google.com/spreadsheets/d/{DOCUMENT_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}'

def get_npfl_data(force_refresh=False):
    """
    Fetch data from Google Sheets and cache it in memory.
    If force_refresh is True, bypass the cache and fetch a new version.
    """
    data = None if force_refresh else cache.get('npfl_all_time_data')
    if data is None:
        try:
            # Fetch CSV from google sheets
            df = pd.read_csv(URL)
            # Rename first column if it's the index (season)
            if df.columns[0] == 'season' or df.columns[0] == 'Unnamed: 0':
                df.rename(columns={df.columns[0]: 'season'}, inplace=True)
            else:
                # If the first column doesn't have a name, set it to season
                df.index.name = 'season'
                df = df.reset_index()
            
            # Clean data types
            df['home_goal'] = pd.to_numeric(df['home_goal'], errors='coerce')
            df['away_goal'] = pd.to_numeric(df['away_goal'], errors='coerce')
            
            # Remove entirely empty columns
            df = df.loc[:, ~df.columns.str.startswith('Unnamed:')]
            
            # Cache it
            cache.set('npfl_all_time_data', df, 86400) # cache for 24 hours
            data = df
        except Exception as e:
            # Fallback in case of errors
            if not force_refresh:
                # Try to retrieve from cache even if expired
                data = cache.get('npfl_all_time_data')
            if data is None:
                raise e
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
