"""
Adjust predictions by shifting 10% from away win to home win for each game,
then recalculate the predicted result and show the new summary.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'npfl_project.settings')
django.setup()

from supercomputer.models import Prediction

predictions = Prediction.objects.all()
total = predictions.count()

if total == 0:
    print("No predictions found!")
    exit()

print(f"Total predictions: {total}")
print()

# Count original
orig_home = 0
orig_draw = 0
orig_away = 0

# Count adjusted
adj_home = 0
adj_draw = 0
adj_away = 0

for pred in predictions:
    # Original
    if pred.predicted_result == 'HOME':
        orig_home += 1
    elif pred.predicted_result == 'DRAW':
        orig_draw += 1
    elif pred.predicted_result == 'AWAY':
        orig_away += 1
    
    # Adjust: shift 10% from away to home (5%) and draw (5%)
    new_home = pred.home_win_pct + 5.0
    new_draw = pred.draw_pct + 5.0
    new_away = pred.away_win_pct - 10.0
    
    # Ensure away doesn't go negative
    if new_away < 0:
        shift = pred.away_win_pct
        new_home = pred.home_win_pct + (shift * 0.5)
        new_draw = pred.draw_pct + (shift * 0.5)
        new_away = 0.0
    
    # Determine new predicted result
    percentages = {'HOME': new_home, 'DRAW': new_draw, 'AWAY': new_away}
    new_result = max(percentages, key=percentages.get)
    
    if new_result == 'HOME':
        adj_home += 1
    elif new_result == 'DRAW':
        adj_draw += 1
    elif new_result == 'AWAY':
        adj_away += 1

print("ORIGINAL PREDICTIONS:")
print(f"  Home wins: {orig_home} ({orig_home/total*100:.1f}%)")
print(f"  Draws:     {orig_draw} ({orig_draw/total*100:.1f}%)")
print(f"  Away wins: {orig_away} ({orig_away/total*100:.1f}%)")
print()
print("ADJUSTED PREDICTIONS (shift 10% from away: 5% to home, 5% to draw for each game):")
print(f"  Home wins: {adj_home} ({adj_home/total*100:.1f}%)")
print(f"  Draws:     {adj_draw} ({adj_draw/total*100:.1f}%)")
print(f"  Away wins: {adj_away} ({adj_away/total*100:.1f}%)")
print()
print("CHANGE:")
print(f"  Home wins: {adj_home - orig_home:+d}")
print(f"  Draws:     {adj_draw - orig_draw:+d}")
print(f"  Away wins: {adj_away - orig_away:+d}")
