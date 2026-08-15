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


class Prediction(models.Model):
    """A single fixture prediction — one per fixture, directly linked."""
    fixture = models.OneToOneField(
        SeasonFixture, on_delete=models.CASCADE, related_name='prediction'
    )
    home_win_pct = models.FloatField()
    draw_pct = models.FloatField()
    away_win_pct = models.FloatField()
    predicted_result = models.CharField(max_length=10)  # 'HOME', 'DRAW', 'AWAY'
    confidence = models.FloatField()
    # Breakdown scores for transparency
    home_form_score = models.FloatField(default=0)
    away_form_score = models.FloatField(default=0)
    h2h_home_rate = models.FloatField(default=0)
    h2h_away_rate = models.FloatField(default=0)
    h2h_draw_rate = models.FloatField(default=0)
    home_venue_strength = models.FloatField(default=0)
    away_venue_strength = models.FloatField(default=0)
    manually_edited = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.fixture} -> {self.predicted_result} ({self.confidence:.1f}%)"


class MatchAnalysisReport(models.Model):
    """Per-fixture match analysis report — written by admin or AI-generated."""
    fixture = models.OneToOneField(
        SeasonFixture, on_delete=models.CASCADE, related_name='analysis_report'
    )
    report = models.TextField(blank=True)
    ai_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fixture__match_day']

    def __str__(self):
        status = 'AI' if self.ai_generated else 'Manual'
        return f"Report: {self.fixture} [{status}]"
