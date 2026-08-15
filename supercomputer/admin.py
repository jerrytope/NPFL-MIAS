from django.contrib import admin
from supercomputer.models import SeasonFixture, Prediction, MatchAnalysisReport


@admin.register(SeasonFixture)
class SeasonFixtureAdmin(admin.ModelAdmin):
    list_display = ('match_day', 'home', 'away', 'season')
    list_filter = ('season', 'match_day')


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ('fixture', 'predicted_result', 'confidence', 'manually_edited')
    list_filter = ('predicted_result', 'manually_edited')


@admin.register(MatchAnalysisReport)
class MatchAnalysisReportAdmin(admin.ModelAdmin):
    list_display = ('fixture', 'ai_generated', 'updated_at')
    list_filter = ('ai_generated',)
