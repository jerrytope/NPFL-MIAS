from django.db import models


class Team(models.Model):
	name = models.CharField(max_length=200, unique=True)
	short_name = models.CharField(max_length=50, blank=True)
	logo = models.CharField(max_length=500, blank=True)
	city = models.CharField(max_length=200, blank=True)

	def __str__(self):
		return self.name


class Match(models.Model):
	season = models.CharField(max_length=32, blank=True)
	match_name = models.CharField(max_length=255, blank=True)
	home = models.ForeignKey(Team, related_name='home_matches', on_delete=models.SET_NULL, null=True)
	away = models.ForeignKey(Team, related_name='away_matches', on_delete=models.SET_NULL, null=True)
	home_goal = models.IntegerField(null=True, blank=True)
	away_goal = models.IntegerField(null=True, blank=True)
	date = models.DateField(null=True, blank=True)
	stadium = models.CharField(max_length=255, blank=True)
	source = models.CharField(max_length=100, blank=True)

	class Meta:
		indexes = [
			models.Index(fields=['season']),
			models.Index(fields=['home']),
			models.Index(fields=['away']),
		]

	def __str__(self):
		return self.match_name or f"{self.home} vs {self.away} ({self.season})"


class TeamComparisonReport(models.Model):
	"""A generated report stored under a canonical (order-independent) team pair."""
	team_one = models.CharField(max_length=200)
	team_two = models.CharField(max_length=200)
	report = models.TextField()
	ai_generated = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['team_one', 'team_two'], name='unique_team_comparison_report'),
		]

	def __str__(self):
		return f"{self.team_one} vs {self.team_two}"
