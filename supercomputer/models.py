from django.db import models
from dashboard.models import Team


class SeasonFixture(models.Model):
    """A fixture in the 2026/27 season schedule. Auto-generated or imported from official document."""
    season = models.CharField(max_length=32, default='26/27')
    match_day = models.IntegerField()           # 1-38 (auto-assigned or from import)
    home = models.ForeignKey(Team, related_name='sc_home_fixtures', on_delete=models.CASCADE)
    away = models.ForeignKey(Team, related_name='sc_away_fixtures', on_delete=models.CASCADE)

    class Meta:
        ordering = ['match_day']
        unique_together = ['season', 'home', 'away']

    def __str__(self):
        return f"MD{self.match_day}: {self.home} vs {self.away} ({self.season})"


class PredictionSnapshot(models.Model):
    """
    A single prediction run. Each time predictions are recalculated,
    a new snapshot is created. This allows comparing predictions from
    different points in the season (e.g. pre-season vs after match day 10).
    """
    season = models.CharField(max_length=32, default='26/27')
    version_label = models.CharField(max_length=100)  # e.g. "Pre-Season", "After Match Day 5"
    match_day_computed = models.IntegerField(default=0)  # 0 = pre-season, 5 = after MD5
    created_at = models.DateTimeField(auto_now_add=True)
    is_latest = models.BooleanField(default=True)  # Quick flag for "current" predictions
    notes = models.TextField(blank=True)  # Optional notes about this run

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.version_label} (MD{self.match_day_computed})"


class Prediction(models.Model):
    """A single fixture prediction within a snapshot."""
    snapshot = models.ForeignKey(PredictionSnapshot, on_delete=models.CASCADE, related_name='predictions')
    fixture = models.ForeignKey(SeasonFixture, on_delete=models.CASCADE, related_name='predictions')
    home_win_pct = models.FloatField()          # e.g. 45.2
    draw_pct = models.FloatField()              # e.g. 28.1
    away_win_pct = models.FloatField()          # e.g. 26.7
    predicted_result = models.CharField(max_length=10)  # 'HOME', 'DRAW', 'AWAY'
    confidence = models.FloatField()            # max of the three percentages
    # Breakdown scores for transparency
    home_form_score = models.FloatField(default=0)
    away_form_score = models.FloatField(default=0)
    h2h_home_rate = models.FloatField(default=0)
    h2h_away_rate = models.FloatField(default=0)
    h2h_draw_rate = models.FloatField(default=0)
    home_venue_strength = models.FloatField(default=0)
    away_venue_strength = models.FloatField(default=0)

    class Meta:
        unique_together = ['snapshot', 'fixture']

    def __str__(self):
        return f"{self.fixture} -> {self.predicted_result} ({self.confidence:.1f}%)"
