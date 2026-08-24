from django.core.management.base import BaseCommand
import pandas as pd

from dashboard.utils import get_npfl_data


class Command(BaseCommand):
    help = (
        "Reconcile Match-derived win/draw/loss totals against the "
        "2002-2026 era all-time table (the same era window Match covers). "
        "Catches spreadsheet corruption (like the season-label bug found "
        "earlier) before it silently skews predictions."
    )

    def add_arguments(self, parser):
        parser.add_argument('--file', '-f', dest='file', required=False,
                            default='plans/All time table 2002-2026.xlsx',
                            help='Era-specific all-time table to reconcile against')
        parser.add_argument('--exclude-seasons', dest='exclude_seasons', type=str,
                            default='',
                            help=(
                                'Comma-separated season labels to exclude from the Match-derived '
                                'side because they are not yet folded into --file. Update this as '
                                'the all-time tables are refreshed with newer seasons.'
                            ))
        parser.add_argument('--tolerance', dest='tolerance', type=int, default=0,
                            help='Allowed absolute difference (games) before flagging a mismatch')

    def handle(self, *args, **options):
        path = options['file']
        tolerance = options['tolerance']
        exclude_seasons = {s.strip() for s in options['exclude_seasons'].split(',') if s.strip()}

        self.stdout.write(f'Reading reference table: {path}')
        ref = pd.read_excel(path, sheet_name=0)
        ref.columns = [c.strip() for c in ref.columns]

        df = get_npfl_data(force_refresh=True)
        if exclude_seasons:
            df = df[~df['season'].isin(exclude_seasons)]
            self.stdout.write(f'Excluding season(s) not yet in the reference table: {sorted(exclude_seasons)}')

        mismatches = []
        no_match_data = []
        checked = 0

        for _, row in ref.iterrows():
            team = str(row['Teams']).strip()
            expected_win = int(row['Total Win'])
            expected_draw = int(row['Total Draw'])
            expected_loss = int(row['Total Loss'])

            home_games = df[df['home'] == team].dropna(subset=['home_goal', 'away_goal'])
            away_games = df[df['away'] == team].dropna(subset=['home_goal', 'away_goal'])

            if home_games.empty and away_games.empty:
                no_match_data.append(team)
                continue

            checked += 1
            actual_win = int((home_games['home_goal'] > home_games['away_goal']).sum() +
                              (away_games['away_goal'] > away_games['home_goal']).sum())
            actual_draw = int((home_games['home_goal'] == home_games['away_goal']).sum() +
                               (away_games['away_goal'] == away_games['home_goal']).sum())
            actual_loss = int((home_games['home_goal'] < home_games['away_goal']).sum() +
                               (away_games['away_goal'] < away_games['home_goal']).sum())

            diff_win = actual_win - expected_win
            diff_draw = actual_draw - expected_draw
            diff_loss = actual_loss - expected_loss

            if max(abs(diff_win), abs(diff_draw), abs(diff_loss)) > tolerance:
                mismatches.append({
                    'team': team,
                    'expected': (expected_win, expected_draw, expected_loss),
                    'actual': (actual_win, actual_draw, actual_loss),
                    'diff': (diff_win, diff_draw, diff_loss),
                })

        self.stdout.write(f'Checked {checked} team(s) against {path}')

        if no_match_data:
            self.stdout.write(self.style.WARNING(
                f'{len(no_match_data)} team(s) in the reference table have no Match rows at all '
                f'(expected for pure pre-2002 clubs no longer in the league): {", ".join(sorted(no_match_data))}'
            ))

        if not mismatches:
            self.stdout.write(self.style.SUCCESS(
                'No mismatches. Match-derived win/draw/loss totals agree with the all-time table for every reconciled team.'
            ))
            return

        self.stdout.write('')
        self.stdout.write(self.style.ERROR(f'{len(mismatches)} mismatch(es) found:'))
        for m in mismatches:
            ew, ed, el = m['expected']
            aw, ad, al = m['actual']
            dw, dd, dl = m['diff']
            self.stdout.write(
                f"  - {m['team']}: table W/D/L={ew}/{ed}/{el}  Match-derived W/D/L={aw}/{ad}/{al}  "
                f"diff={dw:+d}/{dd:+d}/{dl:+d}"
            )
