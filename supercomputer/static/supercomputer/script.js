/* ============================================================
   NPFL Super Computer — Interactive Dashboard JS
   ============================================================ */

const API_BASE = '/supercomputer/api';
const ITEMS_PER_PAGE = 10;

let allPredictions = [];
let filteredPredictions = [];
let currentPage = 1;
let teams = new Set();
let matchDays = new Set();

// ---------- DOM Elements ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const els = {
    matchDaySelect: $('#matchDaySelect'),
    teamSelect: $('#teamSelect'),
    clearFilters: $('#clearFilters'),
    activeFilters: $('#activeFilters'),
    statTotal: $('#statTotal'),
    statHomeWins: $('#statHomeWins'),
    statDraws: $('#statDraws'),
    statAwayWins: $('#statAwayWins'),
    grid: $('#predictionsGrid'),
    pagination: $('#pagination'),
    loading: $('#loadingState'),
    empty: $('#emptyState'),
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
            showLoading(false);
            showEmpty(true);
            return;
        }

        allPredictions = data.results;
        filteredPredictions = allPredictions;

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

function populateFilterOptions() {
    teams = new Set();
    matchDays = new Set();

    allPredictions.forEach(p => {
        teams.add(p.home);
        teams.add(p.away);
        matchDays.add(p.match_day);
    });

    const currentMD = els.matchDaySelect.value;
    if (els.matchDaySelect.options.length <= 1) {
        const sortedMDs = [...matchDays].sort((a, b) => a - b);
        sortedMDs.forEach(md => {
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

    currentPage = 1;
    updateActiveFilters();
    updateStats();
    renderPredictions();
    renderPagination();
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
function updateStats() {
    const data = filteredPredictions;
    const homeWins = data.filter(p => p.predicted_result === 'HOME').length;
    const draws = data.filter(p => p.predicted_result === 'DRAW').length;
    const awayWins = data.filter(p => p.predicted_result === 'AWAY').length;

    animateNumber(els.statTotal, data.length);
    animateNumber(els.statHomeWins, homeWins);
    animateNumber(els.statDraws, draws);
    animateNumber(els.statAwayWins, awayWins);
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

// ---------- Rendering ----------
function renderPredictions() {
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    const end = start + ITEMS_PER_PAGE;
    const pageData = filteredPredictions.slice(start, end);

    els.grid.innerHTML = '';

    let lastMD = null;

    pageData.forEach((p, i) => {
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

function createPredictionCard(p) {
    const card = document.createElement('div');
    card.className = 'prediction-card';
    if (p.confidence >= 60) card.classList.add('high-confidence');

    const confidenceLevel = p.confidence >= 60 ? 'High' : p.confidence >= 40 ? 'Medium' : 'Low';
    const confidenceColor = p.confidence >= 60 ? 'var(--accent-green)' : p.confidence >= 40 ? 'var(--accent-amber)' : 'var(--accent-red)';

    card.innerHTML = `
        <div class="card-match-day">Match Day ${p.match_day}</div>
        <div class="card-teams">
            <div>
                <div class="team-name home">${p.home}</div>
                <div class="venue-tag">Home</div>
            </div>
            <div class="vs-badge">VS</div>
            <div>
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
            <span class="confidence-meter">
                Confidence: <strong style="color:${confidenceColor}">${p.confidence.toFixed(1)}%</strong>
                <small>(${confidenceLevel})</small>
            </span>
        </div>
        <div class="card-breakdown">
            <div class="breakdown-item">
                <div class="breakdown-label">Form</div>
                <div class="breakdown-value">${p.home_form_score.toFixed(2)} / ${p.away_form_score.toFixed(2)}</div>
            </div>
            <div class="breakdown-item">
                <div class="breakdown-label">H2H</div>
                <div class="breakdown-value">${(p.h2h_home_rate * 100).toFixed(0)}-${(p.h2h_draw_rate * 100).toFixed(0)}-${(p.h2h_away_rate * 100).toFixed(0)}</div>
            </div>
            <div class="breakdown-item">
                <div class="breakdown-label">Venue</div>
                <div class="breakdown-value">${(p.home_venue_strength * 100).toFixed(0)}% / ${(p.away_venue_strength * 100).toFixed(0)}%</div>
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

function getResultIcon(result) {
    switch (result) {
        case 'HOME': return '<i class="fas fa-home"></i>';
        case 'DRAW': return '<i class="fas fa-handshake"></i>';
        case 'AWAY': return '<i class="fas fa-plane"></i>';
        default: return '';
    }
}

// ---------- Pagination ----------
function renderPagination() {
    const totalPages = Math.ceil(filteredPredictions.length / ITEMS_PER_PAGE);

    if (totalPages <= 1) {
        els.pagination.style.display = 'none';
        return;
    }

    els.pagination.style.display = 'flex';
    els.pagination.innerHTML = '';

    const prevBtn = createPageBtn('<i class="fas fa-chevron-left"></i>', currentPage > 1, () => {
        currentPage--;
        renderPredictions();
        renderPagination();
        scrollToTop();
    });
    els.pagination.appendChild(prevBtn);

    const range = getPageRange(currentPage, totalPages);
    range.forEach(page => {
        if (page === '...') {
            const ellipsis = document.createElement('span');
            ellipsis.className = 'page-btn disabled';
            ellipsis.textContent = '...';
            els.pagination.appendChild(ellipsis);
        } else {
            const btn = createPageBtn(page, true, () => {
                currentPage = page;
                renderPredictions();
                renderPagination();
                scrollToTop();
            });
            if (page === currentPage) btn.classList.add('active');
            els.pagination.appendChild(btn);
        }
    });

    const nextBtn = createPageBtn('<i class="fas fa-chevron-right"></i>', currentPage < totalPages, () => {
        currentPage++;
        renderPredictions();
        renderPagination();
        scrollToTop();
    });
    els.pagination.appendChild(nextBtn);
}

function createPageBtn(label, enabled, onClick) {
    const btn = document.createElement('button');
    btn.className = `page-btn${enabled ? '' : ' disabled'}`;
    btn.innerHTML = label;
    if (enabled) btn.addEventListener('click', onClick);
    return btn;
}

function getPageRange(current, total) {
    if (total <= 7) return Array.from({length: total}, (_, i) => i + 1);

    const range = [];
    range.push(1);

    if (current > 3) range.push('...');

    const start = Math.max(2, current - 1);
    const end = Math.min(total - 1, current + 1);

    for (let i = start; i <= end; i++) range.push(i);

    if (current < total - 2) range.push('...');

    range.push(total);
    return range;
}

function scrollToTop() {
    window.scrollTo({ top: els.grid.offsetTop - 20, behavior: 'smooth' });
}

// ---------- Helpers ----------
function showLoading(show) {
    els.loading.style.display = show ? 'flex' : 'none';
    els.grid.style.display = show ? 'none' : 'grid';
}

function showEmpty(show) {
    els.empty.style.display = show ? 'block' : 'none';
    els.grid.style.display = show ? 'none' : 'grid';
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}
