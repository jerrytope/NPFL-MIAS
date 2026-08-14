import sqlite3

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# 2026/27 teams are defined in views.py - 20 teams. 
# In NPFL with 20 teams, each team plays 38 games (19 home, 19 away)
# Total matches per season = 20 * 19 = 380 (each pair plays twice)
# Match days: 38 match days * 10 games per match day = 380

# Check 24/25 season structure - 20 teams, 380 matches
# Let's see if there's a pattern in match ordering
print("=== First 30 matches from 24/25 (by rowid) ===")
c.execute("""
    SELECT m.rowid, m.match_name, h.name, a.name, m.home_goal, m.away_goal
    FROM dashboard_match m
    JOIN dashboard_team h ON m.home_id = h.id
    JOIN dashboard_team a ON m.away_id = a.id
    WHERE season='24/25'
    ORDER BY m.rowid
    LIMIT 30
""")
for r in c.fetchall():
    print(r)

# Check what 2026/27 season looks like (if any)
print("\n=== 2026/27 season check ===")
c.execute("SELECT COUNT(*) FROM dashboard_match WHERE season LIKE '%26%'")
print('Matches with 26 in season:', c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM dashboard_match WHERE season LIKE '%27%'")
print('Matches with 27 in season:', c.fetchone()[0])

# Understanding the fixture format: 20 teams = 10 matches per matchday, 38 matchdays = 380 total
# The 2026/27 season will have the same 280 or 380 games. User said 280 - let's check
# With 20 teams: 20*19/2 = 190 unique fixtures, played home and away = 380 total
# But user said 280 games, so maybe 2026/27 has fewer teams?
# From views.py, NPFL_CLUBS_2026_2027 has 20 teams
# 20 teams * 19 opponents = 380 games, but user said 280
# Wait, maybe they have a different number of teams? Let me count from views.py
# I counted 20 teams in the list => 380 matches
# Let me check if they meant 280 in a different way

# Check how many incomplete matches there are in total DB 
print("\n=== Total uncompleted matches in DB ===")
c.execute("SELECT COUNT(*) FROM dashboard_match WHERE home_goal IS NULL")
print('Uncompleted:', c.fetchone()[0])

c.execute("""
    SELECT m.season, h.name, a.name
    FROM dashboard_match m
    JOIN dashboard_team h ON m.home_id = h.id
    JOIN dashboard_team a ON m.away_id = a.id
    WHERE m.home_goal IS NULL
    LIMIT 20
""")
for r in c.fetchall():
    print(r)

conn.close()
