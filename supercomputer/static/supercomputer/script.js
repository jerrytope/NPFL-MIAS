/* ============================================================
   NPFL Super Computer — Interactive Dashboard JS
   ============================================================ */

const API_BASE = '/supercomputer/api';

let allPredictions = [];
let filteredPredictions = [];
let teams = new Set();
let unlockedMatchDays = [];  // published by the admin — see updateLockStatus()
let seasonTotals = null;     // season-wide banner figures, independent of locks

// Scoreline Projections tab — lazy-loaded the first time the tab is opened, since
// its payload carries a full 9x9 grid per fixture and most visits never open it.
let allScorelines = [];
let filteredScorelines = [];
let scorelinesLoaded = false;

// Whether to show the admin "Download PNG" buttons. Handed over by the view
// via {{ is_admin|json_script:"is-admin" }} — the cards are built here in JS,
// not by a template loop, so a {% if %} in the template could never reach one.
const IS_ADMIN = (() => {
    const el = document.getElementById('is-admin');
    try {
        return el ? JSON.parse(el.textContent) === true : false;
    } catch (e) {
        return false;
    }
})();

/* The button markup for a card. Empty for anyone not signed in, so the
   download simply does not exist rather than being hidden with CSS.

   The filename label travels in a data attribute rather than being
   interpolated into an inline onclick="". A club name containing an apostrophe
   would otherwise close the JS string inside that attribute and break the
   button, and hand-escaping it is the kind of thing that looks right and
   silently is not. Delegation removes the problem instead of patching it. */
function escapeAttr(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function downloadButton(kind, id, label) {
    if (!IS_ADMIN) return '';
    return `<button type="button" class="download-btn card-download-btn"
                    title="Download PNG" aria-label="Download this card as an image"
                    data-dl-kind="${kind}" data-dl-id="${id}" data-dl-label="${escapeAttr(label)}">
                <i class="fa-solid fa-download"></i>
            </button>`;
}

/* One listener covers every card, including any rendered later. */
document.addEventListener('click', (event) => {
    const btn = event.target.closest('.card-download-btn');
    if (!btn) return;

    const kind = btn.dataset.dlKind;
    const card = document.getElementById(`${kind}-card-${btn.dataset.dlId}`);
    if (card && typeof window.downloadElementAsPNG === 'function') {
        window.downloadElementAsPNG(card, kind, btn.dataset.dlLabel || '');
    }
});

// ---------- DOM Elements ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
    matchDaySelect: $('#matchDaySelect'),
    teamSelect: $('#teamSelect'),
    clearFilters: $('#clearFilters'),
    activeFilters: $('#activeFilters'),
    revealStatus: $('#revealStatus'),
    statTotal: $('#statTotal'),
    statTotalLabel: $('#statTotalLabel'),
    statHomeWins: $('#statHomeWins'),
    statHomeWinsLabel: $('#statHomeWinsLabel'),
    statDraws: $('#statDraws'),
    statDrawsLabel: $('#statDrawsLabel'),
    statAwayWins: $('#statAwayWins'),
    statAwayWinsLabel: $('#statAwayWinsLabel'),
    grid: $('#predictionsGrid'),
    loading: $('#loadingState'),
    empty: $('#emptyState'),
    scorelinesGrid: $('#scorelinesGrid'),
    scorelinesLoading: $('#scorelinesLoading'),
    scorelinesEmpty: $('#scorelinesEmpty'),
};

// ---------- Initialization ----------
document.addEventListener('DOMContentLoaded', init);

async function init() {
    bindEvents();
    await loadPredictions();
}

function bindEvents() {
    els.matchDaySelect.addEventListener('change', applyFilters);
    els.teamSelect.addEventListener('change', applyFilters);
    els.clearFilters.addEventListener('click', clearFilters);
}

// ---------- Data Loading ----------
async function loadPredictions() {
    showLoading(true);

    const matchDay = els.matchDaySelect.value;
    const team = els.teamSelect.value;

    let url = `${API_BASE}/predictions/?`;
    if (matchDay) url += `&match_day=${matchDay}`;
    if (team) url += `&team=${encodeURIComponent(team)}`;

    try {
        const res = await fetch(url);
        const data = await res.json();

        if (!data.results || data.results.length === 0) {
            seasonTotals = data.season_totals || null;
            // Nothing to show for two very different reasons: predictions were
            // never generated, or they exist but no match day is published yet.
            // Saying "run generate_predictions" in the second case would send
            // the admin chasing the wrong problem.
            const nothingPublished = seasonTotals && seasonTotals.games > 0;
            showLoading(false);
            showEmpty(true, nothingPublished);
            return;
        }

        allPredictions = data.results;
        filteredPredictions = allPredictions;
        seasonTotals = data.season_totals || null;

        updateLockStatus(data.unlocked_match_days || [], data.total_match_days);
        populateFilterOptions();
        applyFilters();

        showLoading(false);
        showEmpty(false);
    } catch (err) {
        console.error('Failed to load predictions:', err);
        showLoading(false);
        showEmpty(true);
    }
}

// ---------- Match day locks ----------
// The admin publishes each match day explicitly from the admin panel's
// Access Control page. A locked match day is absent from the API entirely —
// not just from the dropdown — so there is no route to it from this page.
// This banner explains why the rest of the season isn't here, so it doesn't
// read as missing data.
function updateLockStatus(apiUnlockedMatchDays, totalMatchDays) {
    unlockedMatchDays = apiUnlockedMatchDays;

    if (!els.revealStatus) return;

    const shown = unlockedMatchDays.length;
    if (!totalMatchDays || shown >= totalMatchDays) {
        els.revealStatus.style.display = 'none';
        return;
    }

    const label = shown === 1
        ? `Match Day ${unlockedMatchDays[0]} is`
        : `${shown} of ${totalMatchDays} match days are`;

    els.revealStatus.innerHTML = `
        <i class="fas fa-lock"></i>
        ${label} published so far. The remaining match days are released by the
        NPFL Super Computer team once their predictions are final.
    `;
    els.revealStatus.style.display = 'block';
}

function populateFilterOptions() {
    teams = new Set();

    allPredictions.forEach(p => {
        teams.add(p.home);
        teams.add(p.away);
    });

    const currentMD = els.matchDaySelect.value;
    if (els.matchDaySelect.options.length <= 1) {
        // Iterate the published list rather than counting 1..N: the admin can
        // unlock match days in any order, so the unlocked set may have gaps.
        unlockedMatchDays.forEach(md => {
            const opt = document.createElement('option');
            opt.value = md;
            opt.textContent = `Match Day ${md}`;
            els.matchDaySelect.appendChild(opt);
        });
    }

    if (els.teamSelect.options.length <= 1) {
        const sortedTeams = [...teams].sort();
        sortedTeams.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            els.teamSelect.appendChild(opt);
        });
    }

    if (currentMD) els.matchDaySelect.value = currentMD;
}

// ---------- Filtering ----------
function applyFilters() {
    const matchDay = els.matchDaySelect.value;
    const team = els.teamSelect.value;

    filteredPredictions = allPredictions;

    if (matchDay) {
        filteredPredictions = filteredPredictions.filter(p => p.match_day === parseInt(matchDay));
    }

    if (team) {
        filteredPredictions = filteredPredictions.filter(p => p.home === team || p.away === team);
    }

    // Same match day / team filter drives the Scoreline Projections tab, so
    // switching tabs never changes which fixtures you're looking at.
    filteredScorelines = allScorelines;
    if (matchDay) {
        filteredScorelines = filteredScorelines.filter(s => s.match_day === parseInt(matchDay));
    }
    if (team) {
        filteredScorelines = filteredScorelines.filter(s => s.home === team || s.away === team);
    }

    updateActiveFilters();
    updateStats();
    renderPredictions();
    renderScorelines();
}

function clearFilters() {
    els.matchDaySelect.value = '';
    els.teamSelect.value = '';
    applyFilters();
}

function updateActiveFilters() {
    const matchDay = els.matchDaySelect.value;
    const team = els.teamSelect.value;
    const chips = [];

    if (matchDay) chips.push(`<span class="filter-chip"><i class="fas fa-calendar-alt"></i> Match Day ${matchDay}</span>`);
    if (team) chips.push(`<span class="filter-chip"><i class="fas fa-futbol"></i> ${team}</span>`);

    if (chips.length > 0) {
        els.activeFilters.innerHTML = chips.join('');
        els.activeFilters.style.display = 'flex';
    } else {
        els.activeFilters.style.display = 'none';
    }
}

// ---------- Stats ----------
// Two different, deliberate methods depending on whether a filter is active:
//
// - No filter at all ("All Match Days" / "All Teams"): the season_totals block
//   from the API — expected value, i.e. the sum of each match's real
//   win/draw/loss probability. This is the SAME method the Standings page's
//   Tab 1 is built from, so the season-wide numbers shown here match what's
//   actually driving the predicted table (e.g. ~47 total expected away wins
//   across the season, not a raw badge count).
//
//   It deliberately spans ALL 380 fixtures, including match days the admin
//   hasn't published yet — it must NOT be recomputed from the cards on screen.
//   An aggregate over the whole season reveals no individual matchup, so it
//   leaks nothing, and it's the headline figure the page exists to show. The
//   locks restrict the cards, not this.
//
// - Any filter active (team and/or match day): count each card's actual
//   predicted_result pick instead, so the banner always matches the visible
//   badges in the (now much shorter) filtered list below it — expected
//   value structurally can't match a short, specific list of cards, which
//   was a recurring source of confusion when filtered down to one team or
//   match day.
//
// When a team filter is active, "home"/"draw"/"away" no longer means
// anything useful (half the filtered team's own fixtures are ones where
// THEY are the away side) — so the three numbers are reoriented to the
// selected team's own win/draw/loss instead, and relabeled accordingly.
function updateStats() {
    if (!els.statTotal) return; // banner not present on the page

    const data = filteredPredictions;
    const team = els.teamSelect.value;
    const matchDay = els.matchDaySelect.value;
    const filtered = Boolean(team || matchDay);

    let winCount = 0;
    let drawCount = 0;
    let lossCount = 0;

    if (filtered) {
        data.forEach(p => {
            if (p.predicted_result === 'DRAW') {
                drawCount++;
                return;
            }
            const teamIsAway = team && p.away === team;
            const homeWins = p.predicted_result === 'HOME';
            if (team ? (homeWins === teamIsAway) : !homeWins) {
                lossCount++; // team lost (or, unfiltered, this is the "AWAY" bucket)
            } else {
                winCount++;
            }
        });
    } else if (seasonTotals) {
        winCount = seasonTotals.home;
        drawCount = seasonTotals.draw;
        lossCount = seasonTotals.away;
    }

    animateNumber(els.statTotal, filtered ? data.length : (seasonTotals ? seasonTotals.games : data.length));
    animateNumber(els.statHomeWins, winCount);
    animateNumber(els.statDraws, drawCount);
    animateNumber(els.statAwayWins, lossCount);

    els.statHomeWinsLabel.textContent = team ? 'Wins' : 'Home Wins';
    els.statDrawsLabel.textContent = 'Draws';
    els.statAwayWinsLabel.textContent = team ? 'Losses' : 'Away Wins';
    // Unfiltered, these are whole-season projections, not a count of the cards
    // below — which are limited to the published match days. Label them so the
    // two numbers aren't read as contradicting each other.
    if (els.statTotalLabel) els.statTotalLabel.textContent = filtered ? 'Games Shown' : 'Season Games';
}

function animateNumber(el, target) {
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;
    const step = Math.max(1, Math.ceil(Math.abs(target - current) / 20));
    const dir = target > current ? 1 : -1;

    let val = current;
    const interval = setInterval(() => {
        val += step * dir;
        if ((dir === 1 && val >= target) || (dir === -1 && val <= target)) {
            val = target;
            clearInterval(interval);
        }
        el.textContent = val;
    }, 30);
}

// ---------- Team crests ----------
// Logo URLs are resolved server-side (dashboard/team_logos.py) from the actual
// files on disk, so there is no filename mapping to maintain here. A club with
// no crest gets a null url and falls back to an initials badge, matching how
// the public dashboard renders unknown clubs.

function getTeamInitials(teamName) {
    if (!teamName) return '??';
    const parts = teamName.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return teamName.substring(0, 2).toUpperCase();
}

function getTeamGradient(teamName) {
    let hash = 0;
    for (let i = 0; i < teamName.length; i++) {
        hash = teamName.charCodeAt(i) + ((hash << 5) - hash);
    }
    const h1 = Math.abs(hash % 360);
    const h2 = (h1 + 40) % 360;
    return `linear-gradient(135deg, hsl(${h1}, 70%, 45%), hsl(${h2}, 70%, 25%))`;
}

function initialsBadgeHtml(teamName) {
    return `<span class="team-initials-badge" style="background:${getTeamGradient(teamName)}">${getTeamInitials(teamName)}</span>`;
}

// `onerror` swaps in the initials badge so a missing or corrupt file degrades
// to the placeholder instead of a broken-image icon.
function teamBadge(teamName, logoUrl) {
    if (!logoUrl) return initialsBadgeHtml(teamName);
    const fallback = initialsBadgeHtml(teamName).replace(/"/g, '&quot;');
    return `<img class="team-logo" src="${logoUrl}" alt="${teamName} crest" loading="lazy"
                 onerror="this.outerHTML='${fallback}'">`;
}

// ---------- Rendering ----------
function renderPredictions() {
    els.grid.innerHTML = '';

    let lastMD = null;

    filteredPredictions.forEach((p, i) => {
        if (p.match_day !== lastMD) {
            lastMD = p.match_day;
            const header = document.createElement('div');
            header.className = 'match-day-header';
            header.textContent = `Match Day ${p.match_day}`;
            els.grid.appendChild(header);
        }

        const card = createPredictionCard(p);
        els.grid.appendChild(card);
    });
}

// Which result the selected team gets out of this fixture (independent of
// which side of the fixture they're on), or null if no team filter is active.
function getTeamRelativeResult(p, team) {
    if (!team || (p.home !== team && p.away !== team)) return null;
    const teamIsAway = p.away === team;
    if (p.predicted_result === 'DRAW') return 'DRAW';
    const homeWins = p.predicted_result === 'HOME';
    return (homeWins !== teamIsAway) ? 'WIN' : 'LOSS';
}

function createPredictionCard(p) {
    const card = document.createElement('div');
    card.className = 'prediction-card';
    // A stable id so the PNG exporter can find this exact card.
    card.id = `prediction-card-${p.id}`;
    if (p.confidence >= 60) card.classList.add('high-confidence');

    const confidenceLevel = p.confidence >= 60 ? 'High' : p.confidence >= 40 ? 'Medium' : 'Low';
    const confidenceColor = p.confidence >= 60 ? 'var(--accent-green)' : p.confidence >= 40 ? 'var(--accent-amber)' : 'var(--accent-red)';

    const selectedTeam = els.teamSelect.value;
    const teamResult = getTeamRelativeResult(p, selectedTeam);
    const teamResultClass = teamResult === 'WIN' ? 'team-win' : teamResult === 'LOSS' ? 'team-loss' : 'team-draw';

    const dlLabel = `${p.home}-vs-${p.away}-md${p.match_day}`;

    card.innerHTML = `
        ${downloadButton('prediction', p.id, dlLabel)}
        <div class="card-match-day">Match Day ${p.match_day}</div>
        <div class="card-teams">
            <div class="card-team-side home">
                ${teamBadge(p.home, p.home_logo)}
                <div class="team-name home">${p.home}</div>
                <div class="venue-tag">Home</div>
            </div>
            <div class="vs-badge">VS</div>
            <div class="card-team-side away">
                ${teamBadge(p.away, p.away_logo)}
                <div class="team-name away">${p.away}</div>
                <div class="venue-tag">Away</div>
            </div>
        </div>
        <div class="prob-bars">
            <div class="prob-row">
                <span class="prob-label">Home Win</span>
                <div class="prob-bar-track">
                    <div class="prob-bar-fill home" style="width: 0%"></div>
                </div>
                <span class="prob-value">${p.home_win_pct.toFixed(1)}%</span>
            </div>
            <div class="prob-row">
                <span class="prob-label">Draw</span>
                <div class="prob-bar-track">
                    <div class="prob-bar-fill draw" style="width: 0%"></div>
                </div>
                <span class="prob-value">${p.draw_pct.toFixed(1)}%</span>
            </div>
            <div class="prob-row">
                <span class="prob-label">Away Win</span>
                <div class="prob-bar-track">
                    <div class="prob-bar-fill away" style="width: 0%"></div>
                </div>
                <span class="prob-value">${p.away_win_pct.toFixed(1)}%</span>
            </div>
        </div>
        <div class="card-result">
            <span class="result-badge ${p.predicted_result}">
                ${getResultIcon(p.predicted_result)} ${p.predicted_result} Win
            </span>
            ${teamResult ? `<span class="result-badge ${teamResultClass}">${selectedTeam}: ${teamResult}</span>` : ''}
            <span class="confidence-meter">
                Confidence: <strong style="color:${confidenceColor}">${p.confidence.toFixed(1)}%</strong>
                <small>(${confidenceLevel})</small>
            </span>
        </div>
        <div class="card-breakdown">
            <div class="breakdown-item">
                <div class="breakdown-label">Expected Goals</div>
                <div class="breakdown-value">${p.home_lambda.toFixed(2)} / ${p.away_lambda.toFixed(2)}</div>
            </div>
            <div class="breakdown-item">
                <div class="breakdown-label">Attack</div>
                <div class="breakdown-value">${p.home_attack.toFixed(2)} / ${p.away_attack.toFixed(2)}</div>
            </div>
            <div class="breakdown-item">
                <div class="breakdown-label">Defense</div>
                <div class="breakdown-value">${p.home_defense.toFixed(2)} / ${p.away_defense.toFixed(2)}</div>
            </div>
            <div class="breakdown-item">
                <div class="breakdown-label">Transfer</div>
                <div class="breakdown-value">${(p.home_transfer_score || 0).toFixed(1)} / ${(p.away_transfer_score || 0).toFixed(1)}</div>
            </div>
        </div>
    `;

    requestAnimationFrame(() => {
        setTimeout(() => {
            const bars = card.querySelectorAll('.prob-bar-fill');
            bars[0].style.width = `${p.home_win_pct}%`;
            bars[1].style.width = `${p.draw_pct}%`;
            bars[2].style.width = `${p.away_win_pct}%`;
        }, 50);
    });

    return card;
}

// ---------- Scoreline Projections tab ----------
function switchTab(tabId, btn) {
    $$('.tab-pane').forEach(p => p.classList.remove('active'));
    $$('.tab-btn').forEach(b => b.classList.remove('active'));

    const targetPane = document.getElementById(tabId);
    if (targetPane) targetPane.classList.add('active');
    if (btn) btn.classList.add('active');

    if (tabId === 'tabScorelines' && !scorelinesLoaded) loadScorelines();
}

async function loadScorelines() {
    scorelinesLoaded = true; // set up front so a fast double-click can't fire two fetches
    showScorelinesLoading(true);

    try {
        const res = await fetch(`${API_BASE}/scorelines/`);
        const data = await res.json();

        allScorelines = data.results || [];
        showScorelinesLoading(false);

        if (allScorelines.length === 0) {
            showScorelinesEmpty(true);
            return;
        }

        showScorelinesEmpty(false);
        applyFilters(); // re-applies the current match day / team filter to the new data
    } catch (err) {
        console.error('Failed to load scorelines:', err);
        scorelinesLoaded = false; // let the user retry by switching tabs again
        showScorelinesLoading(false);
        showScorelinesEmpty(true);
    }
}

// Renders every filtered fixture in one list. Pagination is deliberately
// absent from both tabs: paging forward through the unfiltered list used to
// walk straight into match days the admin hadn't published, which is exactly
// what the locks exist to prevent. Do not reintroduce it.
function renderScorelines() {
    if (!els.scorelinesGrid) return;

    els.scorelinesGrid.innerHTML = '';

    let lastMD = null;
    filteredScorelines.forEach(s => {
        if (s.match_day !== lastMD) {
            lastMD = s.match_day;
            const header = document.createElement('div');
            header.className = 'match-day-header';
            header.textContent = `Match Day ${s.match_day}`;
            els.scorelinesGrid.appendChild(header);
        }
        els.scorelinesGrid.appendChild(createScorelineCard(s));
    });
}

function createScorelineCard(s) {
    const card = document.createElement('div');
    card.className = 'scoreline-card';
    // A stable id so the PNG exporter can find this exact card.
    card.id = `scoreline-card-${s.id}`;

    const top = s.top_scorelines || [];
    const peak = top[0];
    // Bars are scaled against the top scoreline, not against 100% — absolute
    // probabilities here are all small (~20% at best), so scaling to 100 would
    // render every bar as a barely-visible sliver.
    const peakProb = peak ? peak.prob : 1;

    const rows = top.map((sc, i) => {
        const pct = sc.prob * 100;
        const width = peakProb > 0 ? (sc.prob / peakProb) * 100 : 0;
        return `
            <div class="sl-row${i === 0 ? ' top' : ''}">
                <span class="sl-score">${sc.home}&ndash;${sc.away}</span>
                <div class="sl-bar-track">
                    <div class="sl-bar-fill" style="width:0%" data-width="${width.toFixed(1)}"></div>
                </div>
                <span class="sl-pct">${pct.toFixed(1)}%</span>
            </div>
        `;
    }).join('');

    const m = s.markets || {};
    const market = (label, value, strong) => `
        <div class="market-item${strong ? ' strong' : ''}">
            <span class="market-label">${label}</span>
            <span class="market-value">${(value * 100).toFixed(0)}%</span>
        </div>
    `;

    card.innerHTML = `
        ${downloadButton('scoreline', s.id, `${s.home}-vs-${s.away}-md${s.match_day}-scoreline`)}
        <div class="sl-header">
            <div class="sl-teams">
                ${teamBadge(s.home, s.home_logo)}
                <span class="sl-team home">${s.home}</span>
                <span class="sl-vs">vs</span>
                ${teamBadge(s.away, s.away_logo)}
                <span class="sl-team away">${s.away}</span>
            </div>
            <div class="sl-xg">
                <i class="fas fa-bullseye"></i>
                Expected Goals <strong>${s.home_lambda.toFixed(2)}</strong> &ndash; <strong>${s.away_lambda.toFixed(2)}</strong>
            </div>
        </div>

        <div class="sl-section-label">Most Likely Scorelines</div>
        <div class="sl-rows">${rows}</div>

        <div class="sl-section-label">Goal Markets</div>
        <div class="markets-row">
            ${market('Over 2.5', m.over_2_5 || 0, (m.over_2_5 || 0) >= 0.5)}
            ${market('Under 2.5', m.under_2_5 || 0, (m.under_2_5 || 0) >= 0.5)}
            ${market('BTTS Yes', m.btts_yes || 0, (m.btts_yes || 0) >= 0.5)}
            ${market('BTTS No', m.btts_no || 0, (m.btts_no || 0) >= 0.5)}
            ${market('Home Clean Sheet', m.home_clean_sheet || 0, false)}
            ${market('Away Clean Sheet', m.away_clean_sheet || 0, false)}
        </div>

        <details class="sl-heatmap-wrap">
            <summary><i class="fas fa-th"></i> Full scoreline probability grid</summary>
            <div class="sl-heatmap-slot"></div>
        </details>
    `;

    // The grid is built on first expand, not up front: with no pagination the
    // tab renders all 380 fixtures at once, and eagerly building every 9x9
    // table would put ~31,000 extra cells in the DOM that almost nobody opens.
    const details = card.querySelector('details');
    details.addEventListener('toggle', () => {
        const slot = details.querySelector('.sl-heatmap-slot');
        if (details.open && slot && !slot.innerHTML) slot.innerHTML = buildHeatmap(s);
    });

    // Animate the bars in, matching how the prediction cards' probability bars behave.
    requestAnimationFrame(() => {
        setTimeout(() => {
            card.querySelectorAll('.sl-bar-fill').forEach(bar => {
                bar.style.width = `${bar.dataset.width}%`;
            });
        }, 50);
    });

    return card;
}

// 9x9 grid of every scoreline 0-0 .. 8-8. Cell shading is scaled to the grid's
// own peak so the structure stays visible — absolute probabilities are tiny once
// you leave the top-left corner.
function buildHeatmap(s) {
    const grid = s.grid || [];
    if (!grid.length) return '';

    const peak = Math.max(...grid.flat());
    const peakCell = s.top_scorelines && s.top_scorelines[0];

    let head = '<tr><th class="corner"><span>H</span>&nbsp;\\&nbsp;<span>A</span></th>';
    for (let a = 0; a < grid[0].length; a++) head += `<th>${a}</th>`;
    head += '</tr>';

    let body = '';
    grid.forEach((row, h) => {
        body += `<tr><th>${h}</th>`;
        row.forEach((p, a) => {
            const intensity = peak > 0 ? p / peak : 0;
            const isPeak = peakCell && peakCell.home === h && peakCell.away === a;
            const pct = p * 100;
            // Below 0.05% renders as "·" — printing 0.0% in 50-odd cells is noise.
            const label = pct >= 0.05 ? pct.toFixed(1) : '·';
            body += `<td class="${isPeak ? 'peak' : ''}" style="--cell:${intensity.toFixed(3)}"
                         title="${h}–${a}: ${pct.toFixed(2)}%">${label}</td>`;
        });
        body += '</tr>';
    });

    return `
        <div class="sl-heatmap-scroll">
            <table class="sl-heatmap">
                <thead>${head}</thead>
                <tbody>${body}</tbody>
            </table>
            <p class="sl-heatmap-note">
                Home goals down the side, away goals across the top. Values are the exact
                probability of that scoreline, in percent.
            </p>
        </div>
    `;
}

function showScorelinesLoading(show) {
    if (els.scorelinesLoading) els.scorelinesLoading.style.display = show ? 'flex' : 'none';
    if (els.scorelinesGrid) els.scorelinesGrid.style.display = show ? 'none' : 'grid';
}

function showScorelinesEmpty(show) {
    if (els.scorelinesEmpty) els.scorelinesEmpty.style.display = show ? 'block' : 'none';
    if (els.scorelinesGrid) els.scorelinesGrid.style.display = show ? 'none' : 'grid';
}

function getResultIcon(result) {
    switch (result) {
        case 'HOME': return '<i class="fas fa-home"></i>';
        case 'DRAW': return '<i class="fas fa-handshake"></i>';
        case 'AWAY': return '<i class="fas fa-plane"></i>';
        default: return '';
    }
}

// ---------- Helpers ----------
function showLoading(show) {
    els.loading.style.display = show ? 'flex' : 'none';
    els.grid.style.display = show ? 'none' : 'grid';
}

function showEmpty(show, nothingPublished) {
    els.empty.style.display = show ? 'block' : 'none';
    els.grid.style.display = show ? 'none' : 'grid';

    if (show && nothingPublished) {
        els.empty.innerHTML = `
            <i class="fas fa-lock"></i>
            <h3>No match days published yet</h3>
            <p>Predictions are ready but none have been released. An admin can publish them
               from the Access Control page in the admin panel.</p>
        `;
    }
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}
