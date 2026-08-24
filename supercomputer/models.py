from django.db import models
from dashboard.models import Team


class SeasonFixture(models.Model):
    """A fixture in the 2026/27 season schedule. Auto-generated or imported from official document."""
    season = models.CharField(max_length=32, default='26/27')
    match_day = models.IntegerField()           # 1-38 (auto-assigned or from import)
    home = models.ForeignKey(Team, related_name='sc_home_fixtures', on_delete=models.CASCADE)
    away = models.ForeignKey(Team, related_name='sc_away_fixtures', on_delete=models.CASCADE)
    # Set once the match is actually played (admin-entered). Mirrored into a
    # Match row so the prediction engine picks it up as real recent form on
    # the next regeneration — see admin_panel/views.py::fixture_result_update.
    home_goal = models.IntegerField(null=True, blank=True)
    away_goal = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['match_day']
        unique_together = ['season', 'home', 'away']

    @property
    def is_played(self):
        return self.home_goal is not None and self.away_goal is not None

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
    # Breakdown fields for transparency — from the Poisson attack/defense model
    home_lambda = models.FloatField(default=0)
    away_lambda = models.FloatField(default=0)
    home_attack = models.FloatField(default=1)
    home_defense = models.FloatField(default=1)
    away_attack = models.FloatField(default=1)
    away_defense = models.FloatField(default=1)
    home_transfer_score = models.FloatField(default=0)
    away_transfer_score = models.FloatField(default=0)
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


class TeamCareerStats(models.Model):
    """
    All-time (1990-2026) career-cumulative record for a team, imported from
    the merged 'npfl all time table.xlsx' workbook. Provides a historical
    pedigree/tenure signal the match-level Match table can't derive on its
    own, since it includes the pre-2002 era for which no match-level data
    exists anywhere in this project.
    """
    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name='career_stats')
    parts = models.IntegerField(default=0)  # season-halves participated — tenure/experience proxy
    played = models.IntegerField(default=0)
    home_win = models.IntegerField(default=0)
    home_draw = models.IntegerField(default=0)
    home_loss = models.IntegerField(default=0)
    away_win = models.IntegerField(default=0)
    away_draw = models.IntegerField(default=0)
    away_loss = models.IntegerField(default=0)
    home_gf = models.IntegerField(default=0)
    home_ga = models.IntegerField(default=0)
    away_gf = models.IntegerField(default=0)
    away_ga = models.IntegerField(default=0)
    total_win = models.IntegerField(default=0)
    total_draw = models.IntegerField(default=0)
    total_loss = models.IntegerField(default=0)
    total_gf = models.IntegerField(default=0)
    total_ga = models.IntegerField(default=0)
    total_gd = models.IntegerField(default=0)
    points = models.IntegerField(default=0)
    source_rank = models.IntegerField(null=True, blank=True)  # Excel-computed all-time Rank, kept for reference
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-points', '-total_gd']
        verbose_name_plural = 'Team career stats'

    @property
    def win_rate(self):
        return self.total_win / self.played if self.played else 0.5

    @property
    def ppg(self):
        return self.points / self.played if self.played else 1.0

    @property
    def gd_per_game(self):
        return self.total_gd / self.played if self.played else 0.0

    def __str__(self):
        return f"{self.team.name} — {self.played} played, {self.points} pts (all-time)"


class TeamSeasonProjection(models.Model):
    """Aggregate probabilistic outcomes across 1,000 Monte Carlo season simulation runs."""
    season = models.CharField(max_length=32, default='26/27')
    team = models.ForeignKey(Team, related_name='season_projections', on_delete=models.CASCADE)
    title_pct = models.FloatField(default=0.0)          # % chance of finishing 1st
    top3_pct = models.FloatField(default=0.0)           # % chance of finishing 1st - 3rd (CAF Continental spots)
    relegation_pct = models.FloatField(default=0.0)     # % chance of finishing 17th - 20th (bottom 4)
    expected_points = models.FloatField(default=0.0)    # Average simulated points (xPts) across 1,000 seasons
    best_points = models.IntegerField(default=0)        # 95th percentile points
    worst_points = models.IntegerField(default=0)       # 5th percentile points
    avg_goal_diff = models.FloatField(default=0.0)      # Average simulated GD
    avg_position = models.FloatField(default=0.0)       # Average simulated rank (1-20)
    simulations_count = models.IntegerField(default=1000)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-expected_points', '-avg_goal_diff']
        unique_together = ['season', 'team']

    def __str__(self):
        return f"{self.team.name} ({self.season}) - xPts: {self.expected_points:.1f}, Title: {self.title_pct:.1f}%"
