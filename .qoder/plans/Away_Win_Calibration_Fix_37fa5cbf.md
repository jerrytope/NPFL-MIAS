# Fixing Away-Win Over-Estimation in the Super Computer

## Summary

Your instinct was correct. Across 7,567 completed matches the real NPFL split is **71.4% home / 21.2% draw / 7.3% away**, but the current engine outputs away percentages in the low-to-mid 20s — roughly **3x too high**.

Root cause (established in discussion): the model builds probabilities from a near-**symmetric** base and only 25% of its weight (venue strength) actually knows about home advantage. Two "smart" features leak probability into the away bucket:
1. **Venue-blind H2H** — a team's historical wins (mostly earned *at home*) are credited to the *away* bucket when they visit.
2. **The 1.3x away multiplier** — inflates a team's form and then feeds that inflated form straight into its away-win chance.

The fix is to stop building probabilities from neutral and instead **anchor to the real league baseline, then adjust** only when evidence justifies it.

---

## New Algorithm: Anchor-and-Adjust (log-odds)

Instead of `raw = 0.35*form + 0.25*h2h + ...` normalised to 100%, we:

1. **Start from the league baseline** (computed live from the DB, not hardcoded): `P_base = (0.714, 0.212, 0.073)` → convert to reference logits `L_home, L_draw, L_away = ln(P_base)`.
2. **Each factor contributes a signed delta** to the home/away logits based on how far the two teams deviate from an *average* team, using **venue-specific** stats.
3. **Softmax back to probabilities.** Because we start at the baseline, away only climbs when a genuinely strong away side meets a weak home side — exactly the rare real-world case.

```
home_logit = L_home
           + β_strength * (home_home_edge - away_away_edge)
           + β_form     * (home_form_delta - away_form_delta)
           + β_h2h      * h2h_home_delta

away_logit = L_away
           + β_strength * (away_away_edge - home_home_edge)
           + β_form     * (away_form_delta - home_form_delta)
           + β_h2h      * h2h_away_delta

draw_logit = L_draw + β_draw * (evenness_bonus)   # rises when teams are closely matched

P = softmax(home_logit, draw_logit, away_logit)
```

Starting coefficients (to be calibrated by backtest): `β_strength=0.9, β_form=0.5, β_h2h=0.4, β_draw=0.3`. All live in a `COEFFS` dict at the top of `predictor.py` for easy tuning.

---

## Key Changes (supercomputer/predictor.py)

### 1. Add dynamic league baseline
- New `get_league_baseline(df)` → returns `(home_rate, draw_rate, away_rate)` from all completed matches, cached per call. Replaces the hardcoded `40/25/35` default.

### 2. Replace venue strength with venue-specific "edge"
- `get_venue_strength()` stays but is reframed as **points-per-game (PPG) at that venue** relative to the league's average home/away PPG:
  - `home_home_edge = (team home PPG) - (league avg home PPG)`
  - `away_away_edge = (team away PPG) - (league avg away PPG)`
- This is the primary driver and is inherently home-aware.

### 3. Make H2H venue-specific (biggest single fix)
- `get_h2h_record(home, away, df)` now filters to **matches played at the home team's ground only** (home==A & away==B). Wins there → home bucket, losses there → away bucket.
- **Small-sample shrinkage**: blend toward baseline with weight `n/(n+k)`, `k=4`. With few venue-specific meetings, it leans on the baseline instead of overreacting.

### 4. Fix the away multiplier
- **Remove** the 1.3x multiplier from the form→probability path (it was the leak).
- Optionally repurpose the "away wins are impressive" idea as a **small, capped bonus** to a team's `away_away_edge` only — so a great away record slightly raises their away chance but can never override the baseline. Recommended default: keep it removed initially, add back only if backtest supports it.

### 5. Form as a modifier, not a base
- `get_team_form_score()` returns last-5 PPG minus the team's own long-run PPG → a small `form_delta`. No venue multiplier.

### 6. Rewrite `predict_match()`
- Implement the log-odds combination above; output the same dict keys (so models/views/JS are untouched) plus keep the breakdown fields populated with the new venue-specific values.

---

## Verification: Backtest & Calibration

### New command: supercomputer/management/commands/backtest_predictions.py
```bash
python manage.py backtest_predictions
```
- Runs `predict_match` over every completed historical match.
- Reports: **average predicted** home/draw/away % vs **actual** 71/21/8, plus argmax accuracy and log-loss.
- **Acceptance target**: aggregate predicted away % lands in a realistic **~7–13%** band (not 25%), draw ~18–24%, home ~65–73%; accuracy beats the naive "always home" baseline on log-loss.
- Use its output to hand-tune the `β` coefficients until the aggregate matches reality.

### Unit tests (supercomputer/tests.py)
- **Baseline sanity**: two perfectly average teams → predicted split ≈ league baseline.
- **Away realism**: an average away side at an average home side → away % < 15%.
- **Strong-away case**: elite away record vs weak home side → away % elevated but still below home unless the gap is large.
- **Percentages sum to 100** for every fixture.
- **Venue-specific H2H**: constructed fixtures confirm only same-venue meetings count.

### Manual step
- `python manage.py generate_predictions --season 26/27 --label "Calibrated v2"` → spot-check Match Day 1 cards: away percentages should now sit mostly in single digits / low teens.

---

## Assumptions & Decisions (made as the expert)
- **Baseline is computed live** from the DB so it self-corrects as 26/27 results arrive.
- **Draw probability stays near baseline** and only rises for evenly-matched sides — draws are hard to predict, so we don't over-engineer them.
- **No schema/API/frontend changes** — output contract is identical; this is a `predictor.py` internals rewrite plus one backtest command and tests.
- The existing `generate_predictions` / snapshot flow is reused to publish the recalibrated numbers.

## Out of Scope
- Full Dixon-Coles/Poisson goal model (possible future upgrade; the anchored log-odds model gets us realistic W/D/A without it).
- Player-level or injury data.
