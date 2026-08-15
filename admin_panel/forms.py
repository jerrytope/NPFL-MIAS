from django import forms


class FixtureUploadForm(forms.Form):
    file = forms.FileField(
        label='Fixture File',
        help_text='Upload an Excel (.xlsx/.xls) or CSV file containing fixtures.',
    )
    season = forms.CharField(
        max_length=32,
        initial='26/27',
        required=True,
    )
    home_col = forms.CharField(max_length=100, initial='home', required=True)
    away_col = forms.CharField(max_length=100, initial='away', required=True)
    md_col = forms.CharField(max_length=100, initial='match_day', required=True)
    mode = forms.ChoiceField(
        choices=[('append', 'Append to existing'), ('replace', 'Replace all existing')],
        initial='append',
    )
