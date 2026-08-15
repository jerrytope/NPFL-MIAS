from django.contrib import admin
from dashboard.models import Team, Match, TeamComparisonReport


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'city')
    search_fields = ('name',)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('match_name', 'home', 'away', 'home_goal', 'away_goal', 'season')
    list_filter = ('season',)
    search_fields = ('match_name',)


@admin.register(TeamComparisonReport)
class TeamComparisonReportAdmin(admin.ModelAdmin):
    list_display = ('team_one', 'team_two', 'created_at', 'updated_at')
    search_fields = ('team_one', 'team_two')
