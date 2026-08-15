/* ==========================================================================
   NPFL Analytics Interactive Client Logic
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Element Queries
    const selectTeam1 = document.getElementById('selectTeam1');
    const selectTeam2 = document.getElementById('selectTeam2');
    const errorAlert = document.getElementById('errorAlert');
    const errorMessage = document.getElementById('errorMessage');
    const placeholderCard = document.getElementById('comparisonPlaceholder');
    const resultsWrapper = document.getElementById('comparisonResults');
    const btnGenerateReport = document.getElementById('btnGenerateReport');
    const reportCard = document.getElementById('reportCard');
    const reportSource = document.getElementById('reportSource');
    const reportSourceLabel = document.getElementById('reportSourceLabel');
    const reportStatus = document.getElementById('reportStatus');
    const reportContent = document.getElementById('reportContent');
    const syncStatus = document.getElementById('syncStatus');
    const rawMatchSearch = document.getElementById('rawMatchSearch');
    
    // Tab Elements
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    // Chart instances (stored globally to allow destroying before redrawing)
    let h2hChartInstance = null;
    let goalsChartInstance = null;
    let seasonsChartInstance = null;

    // Mapping team names to existing image files in the logos folder
    // Note: We use lowercase keys for easy matching
    const teamLogoMapping = {
        'enyimba': '1.png',
        'kano pillars': '2.png',
        'bendel insurance': '3.png',
        'sunshine stars': '4.png',
        'jigawa golden stars': '3.png',
        'wikki tourists': '4.png',
        'kwara united': '2.png',
        'julius berger': '1.png',
        'plateau united': '2.png'
    };

    // Helper to get team initials for placeholder avatar
    function getTeamInitials(teamName) {
        if (!teamName) return "??";
        const parts = teamName.split(/\s+/);
        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }
        return teamName.substring(0, 2).toUpperCase();
    }

    // Helper to get unique color gradient for placeholder avatar based on team name
    function getTeamGradient(teamName) {
        let hash = 0;
        for (let i = 0; i < teamName.length; i++) {
            hash = teamName.charCodeAt(i) + ((hash << 5) - hash);
        }
        const h1 = Math.abs(hash % 360);
        const h2 = (h1 + 40) % 360;
        return `linear-gradient(135deg, hsl(${h1}, 70%, 45%), hsl(${h2}, 70%, 25%))`;
    }

    // Helper to render team avatar (logo or custom initials placeholder)
    function renderTeamAvatar(container, teamName) {
        container.innerHTML = '';
        const nameLower = teamName.trim().toLowerCase();
        
        if (teamLogoMapping[nameLower]) {
            // Logo exists in directory
            const img = document.createElement('img');
            img.src = `${logoBaseUrl}${teamLogoMapping[nameLower]}`;
            img.alt = `${teamName} Logo`;
            img.className = 'team-logo-img';
            container.appendChild(img);
        } else {
            // Render beautiful initials placeholder with name-derived gradient
            const badge = document.createElement('div');
            badge.className = 'team-initials-badge';
            badge.style.background = getTeamGradient(teamName);
            badge.innerText = getTeamInitials(teamName);
            container.appendChild(badge);
        }
    }

    // Tab switcher logic
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));
            
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-tab');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // Handle selection changes
    function onSelectionChange() {
        const team1 = selectTeam1.value;
        const team2 = selectTeam2.value;

        // Hide old errors
        errorAlert.style.display = 'none';

        if (!team1 || !team2) {
            return; // Not fully selected yet
        }

        if (team1 === team2) {
            showError("Please select two different teams for comparison.");
            placeholderCard.style.display = 'block';
            resultsWrapper.style.display = 'none';
            updateReportButtonState();
            return;
        }

        updateReportButtonState();
        // Trigger the AJAX fetch to Django view
        fetchComparison(team1, team2);
    }

    selectTeam1.addEventListener('change', onSelectionChange);
    selectTeam2.addEventListener('change', onSelectionChange);
    btnGenerateReport.addEventListener('click', onGenerateReportClick);
    updateReportButtonState();

    function showError(msg) {
        errorMessage.innerText = msg;
        errorAlert.style.display = 'flex';
    }

    // The report is generated as Markdown. Escape it first, then render the
    // small, predictable Markdown subset used by the report prompt.
    function formatReportMarkdown(markdown) {
        const escapeHtml = (value) => value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');

        const formatInline = (value) => escapeHtml(value)
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/__(.+?)__/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/_(.+?)_/g, '<em>$1</em>');

        return markdown.trim().split(/\n\s*\n/).map(block => {
            const lines = block.trim().split('\n').map(line => line.trim()).filter(Boolean);
            if (!lines.length) return '';

            const heading = lines.length === 1 && lines[0].match(/^(#{1,3})\s+(.+)$/);
            if (heading) {
                const level = heading[1].length + 2;
                return `<h${level}>${formatInline(heading[2])}</h${level}>`;
            }

            if (lines.every(line => /^[-*]\s+/.test(line))) {
                return `<ul>${lines.map(line => `<li>${formatInline(line.replace(/^[-*]\s+/, ''))}</li>`).join('')}</ul>`;
            }

            if (lines.every(line => /^\d+[.)]\s+/.test(line))) {
                return `<ol>${lines.map(line => `<li>${formatInline(line.replace(/^\d+[.)]\s+/, ''))}</li>`).join('')}</ol>`;
            }

            return `<p>${lines.map(formatInline).join('<br>')}</p>`;
        }).join('');
    }

    function updateReportButtonState() {
        if (!btnGenerateReport) return;
        const team1 = selectTeam1.value;
        const team2 = selectTeam2.value;
        const valid = team1 && team2 && team1 !== team2;
        btnGenerateReport.disabled = !valid;
        if (!valid) {
            reportCard.style.display = 'none';
            reportStatus.innerText = 'Select two different teams to enable report generation.';
        }
    }

    function displaySavedReport(report, team1, team2, aiGenerated) {
        if (!report) {
            reportCard.style.display = 'none';
            reportSource.style.display = 'none';
            reportStatus.innerText = 'No saved report yet. Click Generate BBC Report to create one.';
            return;
        }

        reportCard.style.display = 'block';
        reportStatus.innerText = `Saved report for ${team1} vs ${team2}`;
        reportContent.innerHTML = `<div class="report-text">${formatReportMarkdown(report)}</div>`;

        // Show source label
        reportSource.style.display = 'block';
        reportSourceLabel.innerHTML = aiGenerated
            ? '<i class="fas fa-robot"></i> AI Generated'
            : '<i class="fas fa-pen"></i> Human Written';
    }

    function onGenerateReportClick() {
        const team1 = selectTeam1.value;
        const team2 = selectTeam2.value;

        if (!team1 || !team2 || team1 === team2) {
            showError('Please select two different teams to generate a report.');
            return;
        }

        reportCard.style.display = 'block';
        reportStatus.innerText = 'Generating BBC expert report...';
        reportContent.innerHTML = '<p class="report-placeholder">Working on your analysis. This may take a few seconds.</p>';
        btnGenerateReport.disabled = true;

        fetch(`/generate-report/?team1=${encodeURIComponent(team1)}&team2=${encodeURIComponent(team2)}`)
            .then(res => {
                if (!res.ok) {
                    return res.text().then(text => {
                        try {
                            const err = JSON.parse(text);
                            throw new Error(err.error || err.debug || 'Server error generating report');
                        } catch (parseErr) {
                            throw new Error(text || 'Server error generating report');
                        }
                    });
                }
                return res.json();
            })
            .then(data => {
                reportStatus.innerText = data.cached
                    ? `Saved report for ${team1} vs ${team2}`
                    : `New report saved for ${team1} vs ${team2}`;
                reportContent.innerHTML = `<div class="report-text">${formatReportMarkdown(data.report)}</div>`;
                // Show source label (newly generated is always AI)
                reportSource.style.display = 'block';
                reportSourceLabel.innerHTML = '<i class="fas fa-robot"></i> AI Generated';
            })
            .catch(err => {
                reportStatus.innerText = 'Report generation failed.';
                reportContent.innerHTML = `<p class="report-placeholder">${err.message}</p>`;
            })
            .finally(() => {
                updateReportButtonState();
            });
    }

    // Fetch comparison stats from server
    function fetchComparison(team1, team2) {
        // Change sync status temporarily to fetching
        const dot = syncStatus.querySelector('.status-dot');
        const txt = syncStatus.querySelector('.status-text');
        dot.className = 'status-dot loading';
        txt.innerText = 'Calculating...';

        fetch(`/compare/?team1=${encodeURIComponent(team1)}&team2=${encodeURIComponent(team2)}`)
            .then(res => {
                if (!res.ok) {
                    return res.json().then(err => { throw new Error(err.error || 'Server error') });
                }
                return res.json();
            })
            .then(data => {
                // Restore status indicator
                dot.className = 'status-dot green';
                txt.innerText = 'Cache Synced';

                // Display results view, hide placeholder
                placeholderCard.style.display = 'none';
                resultsWrapper.style.display = 'block';

                // Populate stats
                updateStatsView(data);
                displaySavedReport(data.saved_report, team1, team2, data.report_ai_generated);
            })
            .catch(err => {
                dot.className = 'status-dot green';
                txt.innerText = 'Cache Synced';
                showError(err.message);
                placeholderCard.style.display = 'block';
                resultsWrapper.style.display = 'none';
            });
    }

    // Update frontend widgets and values
    function updateStatsView(data) {
        const t1 = data.team1;
        const t2 = data.team2;

        // Update KPI values
        document.getElementById('kpiTotalMatches').innerText = data.total_matches;
        document.getElementById('kpiTeam1Wins').innerText = data.team1_wins;
        document.getElementById('kpiTeam1WinsLabel').innerText = `${t1} Wins`;
        document.getElementById('kpiTeam2Wins').innerText = data.team2_wins;
        document.getElementById('kpiTeam2WinsLabel').innerText = `${t2} Wins`;
        document.getElementById('kpiDraws').innerText = data.draws;

        // Profiles Headers
        document.getElementById('t1Name').innerText = t1;
        document.getElementById('t2Name').innerText = t2;
        
        // Profiles Avatars
        renderTeamAvatar(document.getElementById('t1Avatar'), t1);
        renderTeamAvatar(document.getElementById('t2Avatar'), t2);

        // Render Recent Form Badges
        renderFormBadges(document.getElementById('t1FormBadges'), data.team1_form);
        renderFormBadges(document.getElementById('t2FormBadges'), data.team2_form);

        // Populate Recent Games Tables
        populateRecentGamesTable(document.getElementById('t1RecentMatchesBody'), data.team1_recent_games, t1);
        populateRecentGamesTable(document.getElementById('t2RecentMatchesBody'), data.team2_recent_games, t2);

        // Average Goals Progress bars
        updateAverageGoalsBar('avgScoredLabel1', 'avgScoredVal1', 'avgScoredFill1', t1, data.avg_scored_t1);
        updateAverageGoalsBar('avgScoredLabel2', 'avgScoredVal2', 'avgScoredFill2', t2, data.avg_scored_t2);
        updateAverageGoalsBar('avgConcededLabel1', 'avgConcededVal1', 'avgConcededFill1', t1, data.avg_conceded_t1);
        updateAverageGoalsBar('avgConcededLabel2', 'avgConcededVal2', 'avgConcededFill2', t2, data.avg_conceded_t2);

        // Draw interactive charts only when the external Chart.js library loaded.
        // A temporary CDN failure should never stop the rest of the comparison.
        if (typeof window.Chart !== 'undefined') {
            drawH2HPieChart(data);
            drawGoalsBarChart(data);
            drawSeasonsChart(data);
        } else {
            console.warn('Chart.js did not load; comparison charts were skipped.');
        }

        // Fill tables
        populateSeasonGoalsTable(data.season_goals);
        populateSeasonPerTeamTable(data.goals_per_team_season, t1, t2);
        populateRawMatchesTable(data.raw_matches);
    }

    // Render form guide circles
    function renderFormBadges(container, formStr) {
        container.innerHTML = '';
        if (!formStr) {
            container.innerHTML = '<span style="color: var(--text-muted); font-size: 0.8125rem;">N/A</span>';
            return;
        }
        for (let i = 0; i < formStr.length; i++) {
            const letter = formStr[i];
            const badge = document.createElement('span');
            badge.className = `form-badge ${letter}`;
            badge.innerText = letter;
            container.appendChild(badge);
        }
    }

    // Populate profile compact tables
    function populateRecentGamesTable(tbody, gamesList, teamName) {
        tbody.innerHTML = '';
        if (!gamesList || gamesList.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No recent matches found.</td></tr>`;
            return;
        }
        
        gamesList.forEach(game => {
            const tr = document.createElement('tr');
            const isHome = game.home === teamName;
            const opponent = isHome ? game.away : game.home;
            const venue = isHome ? 'Home' : 'Away';
            const scoreStr = `${game.home_goal} - ${game.away_goal}`;
            
            tr.innerHTML = `
                <td title="${opponent}">${opponent}</td>
                <td>${venue}</td>
                <td>${scoreStr}</td>
                <td><span class="result-marker ${game.result}">${game.result}</span></td>
            `;
            tbody.appendChild(tr);
        });
    }

    // Scale and update the progress bar animation
    function updateAverageGoalsBar(labelId, valId, fillId, teamName, val) {
        document.getElementById(labelId).innerText = `${teamName} Goals`;
        document.getElementById(valId).innerText = val.toFixed(2);
        
        // Assuming max average is 3.5 goals for scaling
        let percentage = (val / 3.5) * 100;
        if (percentage > 100) percentage = 100;
        
        // Trigger smooth transition
        setTimeout(() => {
            document.getElementById(fillId).style.width = `${percentage}%`;
        }, 100);
    }

    /* ==========================================================================
       Chart.js Visualizations
       ========================================================================== */

    function drawH2HPieChart(data) {
        if (h2hChartInstance) h2hChartInstance.destroy();
        
        const ctx = document.getElementById('h2hPieChart').getContext('2d');
        h2hChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: [`${data.team1} Wins`, 'Draws', `${data.team2} Wins`],
                datasets: [{
                    data: [data.team1_wins, data.draws, data.team2_wins],
                    backgroundColor: ['#f43f5e', '#fbbf24', '#0078d4'],
                    borderColor: 'rgba(10, 14, 26, 0.8)',
                    borderWidth: 2,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#f3f4f6',
                            font: { family: 'Inter', size: 11 }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const val = context.raw;
                                const pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
                                return ` ${context.label}: ${val} (${pct}%)`;
                            }
                        }
                    }
                },
                cutout: '65%'
            }
        });
    }

    function drawGoalsBarChart(data) {
        if (goalsChartInstance) goalsChartInstance.destroy();
        
        const ctx = document.getElementById('goalsBarChart').getContext('2d');
        goalsChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [data.team1, data.team2],
                datasets: [{
                    label: 'Total Goals',
                    data: [data.team1_goals, data.team2_goals],
                    backgroundColor: ['#f43f5e', '#0078d4'],
                    borderWidth: 0,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#9ca3af', font: { family: 'Inter' } }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#9ca3af', font: { family: 'Inter' } }
                    }
                }
            }
        });
    }

    function drawSeasonsChart(data) {
        if (seasonsChartInstance) seasonsChartInstance.destroy();
        
        const seasonsData = data.goals_per_team_season;
        const labels = seasonsData.map(d => d.season);
        const t1Goals = seasonsData.map(d => d[`${data.team1}_goals`]);
        const t2Goals = seasonsData.map(d => d[`${data.team2}_goals`]);
        
        const ctx = document.getElementById('seasonsGroupedBarChart').getContext('2d');
        seasonsChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: data.team1,
                        data: t1Goals,
                        backgroundColor: '#f43f5e',
                        borderRadius: 4
                    },
                    {
                        label: data.team2,
                        data: t2Goals,
                        backgroundColor: '#0078d4',
                        borderRadius: 4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { color: '#f3f4f6', font: { family: 'Inter' } }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#9ca3af', font: { family: 'Inter' } }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#9ca3af', stepSize: 1, font: { family: 'Inter' } }
                    }
                }
            }
        });
    }

    /* ==========================================================================
       Table Population Helpers
       ========================================================================== */

    function populateSeasonGoalsTable(seasonGoals) {
        const tbody = document.getElementById('seasonGoalsTableBody');
        tbody.innerHTML = '';
        if (!seasonGoals || seasonGoals.length === 0) {
            tbody.innerHTML = `<tr><td colspan="2" style="text-align: center; color: var(--text-muted);">No goals record.</td></tr>`;
            return;
        }
        seasonGoals.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${item.season}</strong></td>
                <td>${item.total_goals} goals</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function populateSeasonPerTeamTable(goalsPerTeamSeason, t1, t2) {
        const tbody = document.getElementById('seasonPerTeamTableBody');
        document.getElementById('thTeam1Goals').innerText = `${t1} Goals`;
        document.getElementById('thTeam2Goals').innerText = `${t2} Goals`;
        tbody.innerHTML = '';
        
        if (!goalsPerTeamSeason || goalsPerTeamSeason.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No records found.</td></tr>`;
            return;
        }
        
        // Reverse array to show latest seasons first
        const displayData = [...goalsPerTeamSeason].reverse();
        displayData.forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${item.season}</strong></td>
                <td>${item[`${t1}_goals`]} goals</td>
                <td>${item[`${t2}_goals`]} goals</td>
            `;
            tbody.appendChild(tr);
        });
    }

    function populateRawMatchesTable(matches) {
        const tbody = document.getElementById('rawMatchesTableBody');
        tbody.innerHTML = '';
        if (!matches || matches.length === 0) {
            tbody.innerHTML = `<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">No match history found.</td></tr>`;
            return;
        }
        matches.forEach(m => {
            const tr = document.createElement('tr');
            tr.setAttribute('data-season', m.season.toLowerCase());
            tr.setAttribute('data-home', m.home.toLowerCase());
            tr.setAttribute('data-away', m.away.toLowerCase());
            
            const scoreStr = `${m.home_goal} - ${m.away_goal}`;
            const detailsStr = `<span class="team-1-color font-semibold">${m.home}</span> vs <span class="team-2-color font-semibold">${m.away}</span>`;
            
            tr.innerHTML = `
                <td><strong>${m.season}</strong></td>
                <td>${detailsStr}</td>
                <td>${scoreStr}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    // Filter Raw matches by typing query
    rawMatchSearch.addEventListener('input', () => {
        const q = rawMatchSearch.value.trim().toLowerCase();
        const rows = document.querySelectorAll('#rawMatchesTableBody tr');
        
        rows.forEach(row => {
            if (row.cells.length <= 1 && row.cells[0].innerText.includes("No match")) return;
            
            const season = row.getAttribute('data-season') || "";
            const home = row.getAttribute('data-home') || "";
            const away = row.getAttribute('data-away') || "";
            
            if (season.includes(q) || home.includes(q) || away.includes(q)) {
                row.style.display = '';
            } else {
                row.style.display = 'none';
            }
        });
    });

});
