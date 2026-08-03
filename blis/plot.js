let db = null;
let chartInstance = null;
let SQL = null;
let currentView = 'overview'; // 'overview' or 'detail'
let currentMachine = null;

// Progress tracking
let progressInterval = null;

// Card chart instances
let cardChartInstances = {};

// Historical chart instances (organized by operation and thread count)
let operationChartInstances = {};

// Branch/Tag selection
let selectedTestBranch = 'master';
let selectedReferenceBranch = 'v2.1';

// Database Initialization
async function initializeDatabase() {
    if (SQL) return;

    // Properly initialize SQL.js
    SQL = await window.initSqlJs({
        locateFile: file => `https://sql.js.org/dist/${file}`
    });
}

// Auto-load database with progress tracking
async function autoLoadDatabase() {
    showLoading();
    updateProgress(10);

    try {
        // Initialize SQL.js if needed
        await initializeDatabase();
        updateProgress(30);

        // Fetch perf.sqlite from the server
        const response = await fetch('perf.sqlite');

        if (!response.ok) {
            throw new Error(`Failed to fetch database: ${response.statusText}`);
        }

        // Track download progress
        const contentLength = response.headers.get('content-length');
        let loadedLength = 0;

        const reader = response.body.getReader();
        const chunks = [];

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            chunks.push(value);
            loadedLength += value.length;

            if (contentLength) {
                const percentComplete = Math.round((loadedLength / contentLength) * 100);
                updateProgress(30 + (percentComplete * 0.6) / 100); // 30-60% for download
            }
        }

        const arrayBuffer = new Uint8Array(loadedLength);
        let position = 0;
        for (const chunk of chunks) {
            arrayBuffer.set(chunk, position);
            position += chunk.length;
        }

        updateProgress(70);

        // Load database
        db = new SQL.Database(arrayBuffer);
        updateProgress(90);

        const dbStatus = document.getElementById('db-status');
        dbStatus.textContent = '✓ Database loaded: perf.sqlite';
        dbStatus.classList.add('loaded');

        updateProgress(100);

        // Slight delay for visual feedback
        setTimeout(() => {
            clearLoading();
            document.getElementById('db-loader').style.display = 'none';
            populateBranchSelectors();
            loadMachineOverview();
        }, 300);
    } catch (error) {
        showError(`Failed to load database: ${error.message}`);
        clearLoading();
    }
}

// Progress update function
function updateProgress(percentage) {
    const progressFill = document.getElementById('progress-fill');
    const progressText = document.getElementById('progress-text');

    if (progressFill && progressText) {
        progressFill.style.width = percentage + '%';
        progressText.textContent = Math.round(percentage) + '%';
    }
}

async function loadDatabase(event) {
    const file = event.target.files[0];
    if (!file) return;

    showLoading();

    try {
        // Initialize SQL.js if needed
        await initializeDatabase();

        const arrayBuffer = await file.arrayBuffer();
        const data = new Uint8Array(arrayBuffer);

        db = new SQL.Database(data);

        document.getElementById('db-status').textContent = `✓ Database loaded: ${file.name}`;
        document.getElementById('db-status').classList.add('loaded');

        showSuccess(`Database loaded successfully: ${file.name}`);
        clearLoading();

        // Populate branch selectors and load machine overview
        populateBranchSelectors();
        loadMachineOverview();
    } catch (error) {
        showError(`Failed to load database: ${error.message}`);
        clearLoading();
    }
}

// UI Control Functions

function clearMessages() {
    document.getElementById('error-message').classList.remove('active');
    document.getElementById('success-message').classList.remove('active');
}

// View Management Functions
function switchView(toView) {
    const fromView = currentView === 'overview' ? 'overview-view' : 'detail-view';
    const toViewElement = toView === 'overview' ? 'overview-view' : 'detail-view';

    const fromElement = document.getElementById(fromView);
    const toElement = document.getElementById(toViewElement);

    if (currentView === toView) return;

    // Animate out current view
    fromElement.classList.add('exiting');

    // After animation, switch views
    setTimeout(() => {
        fromElement.classList.remove('active', 'exiting');
        toElement.classList.add('active');
        currentView = toView;
    }, 500);
}

function backToOverview() {
    switchView('overview');
}

function showError(message) {
    clearMessages();
    const errorDiv = document.getElementById('error-message');
    errorDiv.textContent = message;
    errorDiv.classList.add('active');
}

function showSuccess(message) {
    clearMessages();
    const successDiv = document.getElementById('success-message');
    successDiv.textContent = message;
    successDiv.classList.add('active');
}

function showLoading() {
    // Loading indicator no longer needed
}

function clearLoading() {
    // Loading indicator no longer needed
}

function showParams(params, plotType) {
    // Parameters display no longer needed
}

// Database Query Functions
function queryDatabase(query, params = []) {
    if (!db) {
        throw new Error('Database not loaded');
    }

    const stmt = db.prepare(query);
    stmt.bind(params);

    const result = [];
    while (stmt.step()) {
        const row = stmt.getAsObject();
        result.push(row);
    }
    stmt.free();

    return result;
}

function getParam(id) {
    const value = document.getElementById(id).value;
    if (value === '' || value === '-1') return -1;
    return isNaN(value) ? value : parseInt(value);
}

function queryHistoricalPlot(machine, op, dt, threads, tag, m, n, k) {
    let query = 'SELECT timestamp, gflops FROM run WHERE 1=1';
    const params = [];

    if (machine !== -1) {
        query += ' AND machine = ?';
        params.push(machine);
    }
    if (op !== -1) {
        query += ' AND op = ?';
        params.push(op);
    }
    if (dt !== -1) {
        query += ' AND dt = ?';
        params.push(dt);
    }
    if (threads !== -1) {
        query += ' AND threads = ?';
        params.push(threads);
    }
    if (tag !== -1) {
        query += ' AND tag = ?';
        params.push(tag);
    }
    if (m !== -1) {
        query += ' AND m = ?';
        params.push(m);
    }
    if (n !== -1) {
        query += ' AND n = ?';
        params.push(n);
    }
    if (k !== -1) {
        query += ' AND k = ?';
        params.push(k);
    }

    query += ' ORDER BY timestamp ASC';

    return queryDatabase(query, params);
}

function queryScalingPlot(git, machine, op, dt, threads, m, n, k) {
    let query = 'SELECT m, n, k, gflops FROM run WHERE git = ?';
    const params = [git];

    // Determine varying dimension
    let varyingDim;
    if (m === -1) varyingDim = 'm';
    else if (n === -1) varyingDim = 'n';
    else if (k === -1) varyingDim = 'k';
    else varyingDim = 'm'; // Default if all specified

    if (machine !== -1) {
        query += ' AND machine = ?';
        params.push(machine);
    }
    if (op !== -1) {
        query += ' AND op = ?';
        params.push(op);
    }
    if (dt !== -1) {
        query += ' AND dt = ?';
        params.push(dt);
    }
    if (threads !== -1) {
        query += ' AND threads = ?';
        params.push(threads);
    }
    if (m !== -1) {
        query += ' AND m = ?';
        params.push(m);
    }
    if (n !== -1) {
        query += ' AND n = ?';
        params.push(n);
    }
    if (k !== -1) {
        query += ' AND k = ?';
        params.push(k);
    }

    query += ` ORDER BY ${varyingDim} ASC`;

    const rows = queryDatabase(query, params);
    return { rows, varyingDim };
}

function queryOverviewPlot(git, machine, threads, dt, m, n, k) {
    let query = 'SELECT op, gflops FROM run WHERE git = ?';
    const params = [git];

    if (machine !== -1) {
        query += ' AND machine = ?';
        params.push(machine);
    }
    if (dt !== -1) {
        query += ' AND dt = ?';
        params.push(dt);
    }
    if (threads !== -1) {
        query += ' AND threads = ?';
        params.push(threads);
    }
    if (m !== -1) {
        query += ' AND (m = ? OR m = -1)';
        params.push(m);
    }
    if (n !== -1) {
        query += ' AND (n = ? OR n = -1)';
        params.push(n);
    }
    if (k !== -1) {
        query += ' AND (k = ? OR k = -1)';
        params.push(k);
    }

    query += ' ORDER BY op ASC';

    return queryDatabase(query, params);
}

function queryComparisonPlot(testGit, refGit, machine, threads, dt, m, n, k) {
    // Query data for test branch
    const testData = queryOverviewPlot(testGit, machine, threads, dt, m, n, k);

    // Query data for reference branch
    const refData = queryOverviewPlot(refGit, machine, threads, dt, m, n, k);

    // Create maps for easy lookup
    const testByOp = {};
    const refByOp = {};

    testData.forEach(row => {
        if (!testByOp[row.op]) testByOp[row.op] = [];
        testByOp[row.op].push(row.gflops);
    });

    refData.forEach(row => {
        if (!refByOp[row.op]) refByOp[row.op] = [];
        refByOp[row.op].push(row.gflops);
    });

    // Calculate percentage change for each operation
    const comparisonData = [];
    Object.keys(testByOp).forEach(op => {
        if (refByOp[op]) {
            const testMax = Math.max(...testByOp[op]);
            const refMax = Math.max(...refByOp[op]);

            if (refMax > 0) {
                const percentChange = ((testMax / refMax) - 1) * 100;
                comparisonData.push({
                    op,
                    percentChange,
                    testGflops: testMax,
                    refGflops: refMax
                });
            }
        }
    });

    return comparisonData.sort((a, b) => a.op.localeCompare(b.op));
}

// Machine Overview Query Functions
function getLatestGitCommit() {
    const query = 'SELECT DISTINCT git FROM run ORDER BY timestamp DESC LIMIT 1';
    const result = queryDatabase(query);
    return result.length > 0 ? result[0].git : null;
}

function getAllTags() {
    const query = 'SELECT DISTINCT tag FROM run ORDER BY tag ASC';
    return queryDatabase(query);
}

function getLatestGitCommitForTag(tag) {
    const query = 'SELECT DISTINCT git FROM run WHERE tag = ? ORDER BY timestamp DESC LIMIT 1';
    const result = queryDatabase(query, [tag]);
    return result.length > 0 ? result[0].git : null;
}

function populateBranchSelectors() {
    try {
        const allTags = getAllTags();
        const tags = allTags.map(t => t.tag).filter(t => t && t.trim() !== '');

        const testSelect = document.getElementById('test-branch-select');
        const refSelect = document.getElementById('reference-branch-select');

        // Clear existing options
        testSelect.innerHTML = '';
        refSelect.innerHTML = '';

        // Populate both selects with the same tags
        tags.forEach(tag => {
            const option1 = document.createElement('option');
            option1.value = tag;
            option1.textContent = tag;
            testSelect.appendChild(option1);

            const option2 = document.createElement('option');
            option2.value = tag;
            option2.textContent = tag;
            refSelect.appendChild(option2);
        });

        // Set default values
        if (tags.includes('master')) {
            testSelect.value = 'master';
            selectedTestBranch = 'master';
        } else if (tags.length > 0) {
            testSelect.value = tags[0];
            selectedTestBranch = tags[0];
        }

        if (tags.includes('v2.1')) {
            refSelect.value = 'v2.1';
            selectedReferenceBranch = 'v2.1';
        } else if (tags.length > 0) {
            refSelect.value = tags[tags.length - 1];
            selectedReferenceBranch = tags[tags.length - 1];
        }

        // Add event listeners for changes
        testSelect.addEventListener('change', function() {
            selectedTestBranch = this.value;
            loadMachineOverview(); // Reload the overview with the new selection
        });

        refSelect.addEventListener('change', function() {
            selectedReferenceBranch = this.value;
            loadMachineOverview(); // Reload the overview to update reference branch display
        });

    } catch (error) {
        console.error('Error populating branch selectors:', error);
    }
}

function getMaxThreadsForMachine(machine) {
    const query = 'SELECT MAX(threads) as max_threads FROM run WHERE machine = ?';
    const result = queryDatabase(query, [machine]);
    return result.length > 0 ? result[0].max_threads : -1;
}

function getAllMachines() {
    const query = 'SELECT DISTINCT machine FROM run ORDER BY machine ASC';
    return queryDatabase(query);
}

function getMachineHistoricalData(machine, tag = null) {
    let query = `
        SELECT DISTINCT op, threads, dt, git, timestamp, gflops
        FROM run
        WHERE machine = ?`;
    const params = [machine];

    if (tag !== null && tag !== '') {
        query += ` AND tag = ?`;
        params.push(tag);
    }

    query += ` ORDER BY op ASC, threads DESC, dt ASC, timestamp DESC`;
    return queryDatabase(query, params);
}

// Machine Overview Rendering
function loadMachineOverview() {
    try {
        if (!db) {
            showError('Database not loaded');
            return;
        }

        showLoading();

        // Get the git commit for the selected test branch
        const testGit = getLatestGitCommitForTag(selectedTestBranch);
        const refGit = getLatestGitCommitForTag(selectedReferenceBranch);
        const machines = getAllMachines();

        if (!testGit) {
            showError('No data available for the selected branch');
            clearLoading();
            return;
        }

        const machineCards = machines.map(m => {
            const machine = m.machine;
            const maxThreads = getMaxThreadsForMachine(machine);
            return {
                machine,
                maxThreads,
                testGitFull: testGit,
                testGit: testGit.substring(0, 7),
                refGitFull: refGit,
                refGit: refGit.substring(0, 7)
            };
        });

        renderMachineOverview(machineCards);
        clearLoading();

        // Show overview view
        switchViewToOverview();
    } catch (error) {
        showError(`Error loading overview: ${error.message}`);
        clearLoading();
    }
}

function getColor(machine, operation, dt, threads, testGit, refGit) {
    let whereClause = `WHERE machine = ? AND git = ?`;
    let testParams = [machine, testGit];
    if (operation) {
        whereClause += ` AND op = ?`;
        testParams.push(operation);
    }
    if (dt) {
        whereClause += ` AND dt = ?`;
        testParams.push(dt);
    }
    if (threads) {
        whereClause += ` AND threads = ?`;
        testParams.push(threads);
    }
    const query = `
        SELECT threads, dt, MAX(gflops) as max_gflops
        FROM run
        ${whereClause}
        GROUP BY threads, dt`;

    const testResult = queryDatabase(query, testParams);
    const refResult = queryDatabase(query, testParams.map((param, index) => index === 1 ? refGit : param));

    // If either is missing, return gray
    if (testResult === null ||
        refResult === null ||
        testResult.length == 0 ||
        refResult.length == 0) {
        return '#f0f0f0'; // Light gray if no data
    }

    const okay = testResult.reduce((acc, row) => {
            return acc && refResult.find(r => r.threads === row.threads && r.dt === row.dt);
        }, Infinity);
    if (!okay) {
        return '#f0f0f0'; // Light gray if no data
    }

    const minPercentChange = testResult.reduce((acc, row) => {
            const testMaxGflops = row.max_gflops;
            const refMaxGflops = refResult.find(r => r.threads === row.threads && r.dt === row.dt).max_gflops;
            return Math.min(acc, ((testMaxGflops / refMaxGflops) - 1) * 100);
        }, Infinity);
    const maxPercentChange = testResult.reduce((acc, row) => {
            const testMaxGflops = row.max_gflops;
            const refMaxGflops = refResult.find(r => r.threads === row.threads && r.dt === row.dt).max_gflops;
            return Math.max(acc, ((testMaxGflops / refMaxGflops) - 1) * 100);
        }, -Infinity);

    // Apply color rules from machine cards
    if (minPercentChange < -15) return '#ffe6e6'; // Very light red
    if (minPercentChange < -5) return '#fff5e6'; // Very light yellow-orange
    if (maxPercentChange > 5) return '#e6ffe6'; // Very light green
    return '#e6f2ff'; // Very light blue
}

function getCardBackgroundColor(card) {
    return getColor(card.machine, null, null, null, card.testGitFull, card.refGitFull) || '#f0f0f0';
}

function renderMachineOverview(machineCards) {
    const grid = document.getElementById('machines-grid');
    grid.innerHTML = '';

    machineCards.forEach((card, index) => {
        const cardEl = document.createElement('div');
        cardEl.className = 'machine-card';
        cardEl.id = `machine-card-${card.machine}`;

        // Get background color based on performance changes
        const bgColor = getCardBackgroundColor(card);
        cardEl.style.backgroundColor = bgColor;

        // Create card content with chart placeholder
        cardEl.innerHTML = `
            <div class="machine-info">
                <div class="machine-name">${card.machine}</div>
                <div class="machine-stats">
                    <div class="stat-row">
                        <span class="stat-label">Threads:</span>
                        <span class="stat-value">${card.maxThreads}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-label">Latest commit:</span>
                        <span class="stat-value">${card.testGit} (${selectedTestBranch})</span>
                        <span class="stat-value">${card.refGit} (${selectedReferenceBranch})</span>
                    </div>
                </div>
            </div>
            <div class="machine-card-chart-grid">
                <div class="machine-card-chart">
                    <div class="chart-card-title">float32 (s)</div>
                    <canvas id="card-chart-${card.machine}-s"></canvas>
                </div>
                <div class="machine-card-chart">
                    <div class="chart-card-title">float64 (d)</div>
                    <canvas id="card-chart-${card.machine}-d"></canvas>
                </div>
                <div class="machine-card-chart">
                    <div class="chart-card-title">complex64 (c)</div>
                    <canvas id="card-chart-${card.machine}-c"></canvas>
                </div>
                <div class="machine-card-chart">
                    <div class="chart-card-title">complex128 (z)</div>
                    <canvas id="card-chart-${card.machine}-z"></canvas>
                </div>
            </div>
        `;

        cardEl.onclick = () => loadMachineDetail(card.machine, selectedTestBranch);
        grid.appendChild(cardEl);

        // Render chart for this card
        renderCardChart(card);
    });
}

function renderCardChart(card) {
    // Query comparison data: percentage change from reference to test branch
    for (const dt of ['s', 'd', 'c', 'z']) {
        try {
            const comparisonData = queryComparisonPlot(
                card.testGitFull,
                card.refGitFull,
                card.machine,
                card.maxThreads,
                dt, -1, -1, -1
            );

            if (!comparisonData || comparisonData.length === 0) {
                return; // No data for this machine
            }

            // Extract labels and data
            const labels = comparisonData.map(item => item.op);
            const data = comparisonData.map(item => item.percentChange);

            const colors = [
                'rgb(255, 99, 132)',
                'rgb(54, 162, 235)',
                'rgb(255, 206, 86)',
                'rgb(75, 192, 192)',
                'rgb(153, 102, 255)',
                'rgb(255, 159, 64)',
                'rgb(201, 203, 207)',
                'rgb(255, 193, 7)'
            ];

            const canvasId = `card-chart-${card.machine}-${dt}`;
            const canvasEl = document.getElementById(canvasId);

            if (!canvasEl) return;

            const ctx = canvasEl.getContext('2d');

            // Destroy existing chart instance if it exists
            if (cardChartInstances[canvasId]) {
                cardChartInstances[canvasId].destroy();
            }

            const chartConfig = {
                type: 'bar',
                data: {
                    labels,
                    datasets: [{
                        label: '% Change',
                        data,
                        backgroundColor: colors.slice(0, labels.length),
                        borderWidth: 1,
                        borderColor: 'rgba(0, 0, 0, 0.1)'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    aspectRatio: 1.8,
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            enabled: true,
                            callbacks: {
                                label: function(context) {
                                    return context.parsed.y.toFixed(1) + '%';
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            min: -25,
                            max: 25,
                            beginAtZero: true,
                            ticks: {
                                font: {
                                    size: 10
                                },
                                callback: function(value) {
                                    return value.toFixed(0) + '%';
                                }
                            },
                            title: {
                                display: true,
                                text: '% Change',
                                font: {
                                    size: 10
                                }
                            }
                        },
                        x: {
                            ticks: {
                                font: {
                                    size: 8
                                },
                                maxRotation: 90,
                                minRotation: 90,
                                padding: -100,
                                z: 1
                            }
                        }
                    }
                }
            };

            cardChartInstances[canvasId] = new Chart(ctx, chartConfig);
        } catch (error) {
            console.warn(`Error rendering card chart for ${card.machine} datatype ${dt}:`, error);
        }
    }
}

function switchViewToOverview() {
    const overviewView = document.getElementById('overview-view');
    const detailView = document.getElementById('detail-view');

    overviewView.classList.add('active');
    detailView.classList.remove('active');
    currentView = 'overview';
}

// Machine Detail View
function loadMachineDetail(machine, tag = null) {
    try {
        currentMachine = machine;
        showLoading();

        const historicalData = getMachineHistoricalData(machine, tag || selectedTestBranch);

        if (historicalData.length === 0) {
            showError('No historical data available for this machine');
            clearLoading();
            return;
        }

        // Get git commits and max threads for color calculation
        const testGit = getLatestGitCommitForTag(selectedTestBranch);
        const refGit = getLatestGitCommitForTag(selectedReferenceBranch);
        const maxThreads = getMaxThreadsForMachine(machine);

        renderMachineDetail(machine, historicalData, testGit, refGit, maxThreads);
        clearLoading();

        // Switch to detail view
        switchViewToDetail();
    } catch (error) {
        showError(`Error loading machine detail: ${error.message}`);
        clearLoading();
    }
}

// Plugin to draw reference line on chart
const referenceLinePlugin = {
    id: 'referenceLine',
    afterDatasetsDraw(chart) {
        if (!chart.customRefMaxGflops) return;

        const ctx = chart.ctx;
        const yScale = chart.scales.y;
        const xScale = chart.scales.x;

        const yPixel = yScale.getPixelForValue(chart.customRefMaxGflops);

        ctx.save();
        ctx.strokeStyle = 'rgba(255, 0, 0, 0.6)';
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(xScale.left, yPixel);
        ctx.lineTo(xScale.right, yPixel);
        ctx.stroke();
        ctx.restore();
    }
};

// Render all historical charts for a specific operation and thread count
function renderChartsForThreadGroup(machine, operation, threads, container, tag = null) {
    try {
        // Query to get all data types for this operation and thread count
        // Group by timestamp to get one data point per commit
        let query = `
            SELECT dt, timestamp, MAX(gflops) as gflops
            FROM run
            WHERE machine = ? AND op = ? AND threads = ?`;
        const params = [machine, operation, threads];

        if (tag !== null && tag !== '') {
            query += ` AND tag = ?`;
            params.push(tag);
        }

        query += ` GROUP BY dt, timestamp
                  ORDER BY dt ASC, timestamp ASC`;
        const rows = queryDatabase(query, params);

        if (!rows || rows.length === 0) {
            return;
        }

        // Group data by data type
        const groupedByDT = {};
        rows.forEach(row => {
            if (!groupedByDT[row.dt]) {
                groupedByDT[row.dt] = [];
            }
            groupedByDT[row.dt].push(row);
        });

        // Create grid container
        const gridContainer = document.createElement('div');
        gridContainer.className = 'charts-grid';

        // Get unique colors for data types
        const colors = {
            's': '#667eea',
            'd': '#f093fb',
            'c': '#4facfe',
            'z': '#fa709a'
        };

        const dt_names = {
            's': 'float32 (s)',
            'd': 'float64 (d)',
            'c': 'complex64 (c)',
            'z': 'complex128 (z)'
        };

        const testGit = getLatestGitCommitForTag(selectedTestBranch);
        const refGit = getLatestGitCommitForTag(selectedReferenceBranch);

        // Create a chart for each data type
        Object.keys(groupedByDT).sort((a, b) => 'sdcz'.indexOf(a) - 'sdcz'.indexOf(b)).forEach(dt => {
            const dtRows = groupedByDT[dt];

            // Create chart card
            const card = document.createElement('div');
            card.className = 'chart-card';
            card.style.backgroundColor = getColor(machine, operation, dt, threads, testGit, refGit) || '#f0f0f0';

            // Create title
            const title = document.createElement('div');
            title.className = 'chart-card-title';
            title.textContent = `${dt_names[dt]}`;
            card.appendChild(title);

            // Create canvas
            const canvas = document.createElement('canvas');
            const chartId = `chart-${operation}-${threads}-${dt}`.replace(/\s+/g, '-');
            canvas.id = chartId;
            card.appendChild(canvas);

            gridContainer.appendChild(card);

            // Query for reference branch max gflops for this operation/dt/threads combo
            const refQuery = `
                SELECT MAX(gflops) as max_gflops
                FROM run
                WHERE machine = ? AND op = ? AND dt = ? AND threads = ? AND tag = ?`;
            const refParams = [machine, operation, dt, threads, selectedReferenceBranch];
            const refResult = queryDatabase(refQuery, refParams);
            const refMaxGflops = refResult && refResult.length > 0 ? refResult[0].max_gflops : null;

            // Prepare data for chart
            const labels = dtRows.map(r => {
                // Handle both Unix timestamps (numbers) and ISO date strings
                let date;
                if (typeof r.timestamp === 'number') {
                    date = new Date(r.timestamp * 1000);
                } else {
                    date = new Date(r.timestamp);
                }
                return date.toLocaleDateString();
            });
            const data = dtRows.map(r => r.gflops);

            // Create chart instance
            const ctx = canvas.getContext('2d');
            const color = colors[dt] || '#667eea';

            const chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: dt.toUpperCase(),
                        data: data,
                        borderColor: color,
                        backgroundColor: color + '20',
                        borderWidth: 2,
                        fill: true,
                        pointRadius: 3,
                        pointBackgroundColor: color,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 1,
                        tension: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: false
                        },
                        title: {
                            display: false
                        },
                        referenceLine: {
                            enabled: refMaxGflops !== null
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: refMaxGflops !== null ? Math.max(...data, refMaxGflops) * 1.05 : undefined,
                            ticks: {
                                callback: function(value) {
                                    return value.toFixed(1);
                                }
                            },
                            title: {
                                display: true,
                                text: 'GFLOP/s per core'
                            }
                        },
                        x: {
                            title: {
                                display: false
                            }
                        }
                    }
                },
                plugins: [referenceLinePlugin]
            });

            // Set the reference max gflops on the chart instance
            if (refMaxGflops !== null) {
                chartInstance.customRefMaxGflops = refMaxGflops;
            }

            // Store chart instance
            const key = `${operation}-${threads}-${dt}`;
            if (!operationChartInstances[operation]) {
                operationChartInstances[operation] = {};
            }
            operationChartInstances[operation][key] = chartInstance;
        });

        container.appendChild(gridContainer);
    } catch (error) {
        console.error('Error rendering charts for thread group:', error);
    }
}

function renderMachineDetail(machine, historicalData, testGit, refGit, maxThreads) {
    // Set header info
    document.getElementById('detail-machine-name').textContent = `${machine}`;
    document.getElementById('detail-machine-info').textContent =
        `Click on any operation to view performance history`;

    // Group data by operation
    const groupedByOp = {};
    historicalData.forEach(row => {
        if (!groupedByOp[row.op]) {
            groupedByOp[row.op] = [];
        }
        groupedByOp[row.op].push(row);
    });

    const container = document.getElementById('historical-data-container');
    container.innerHTML = '';

    Object.keys(groupedByOp).sort().forEach(op => {
        const opData = groupedByOp[op];

        // Group by threads
        const groupedByThreads = {};
        opData.forEach(row => {
            const key = `${row.threads} threads`;
            if (!groupedByThreads[key]) {
                groupedByThreads[key] = [];
            }
            groupedByThreads[key].push(row);
        });

        const opElement = document.createElement('div');
        opElement.className = 'historical-operation-group';

        const headerEl = document.createElement('div');
        headerEl.className = 'operation-header';

        // Calculate background color for this operation
        const bgColor = getColor(machine, op, null, null, testGit, refGit);
        headerEl.style.backgroundColor = bgColor;

        headerEl.innerHTML = `
            <span>${op}</span>
            <span class="expand-icon">▼</span>
        `;

        const contentEl = document.createElement('div');
        contentEl.className = 'operation-content';

        // Create content with charts for each thread level
        const threadKeys = Object.keys(groupedByThreads).sort((a, b) => {
            const aThreads = parseInt(a.split(' ')[0]);
            const bThreads = parseInt(b.split(' ')[0]);
            return bThreads - aThreads; // Descending
        });

        // Store thread info for lazy rendering
        const threadGroupElements = {};

        threadKeys.forEach(threadKey => {
            const threads = parseInt(threadKey.split(' ')[0]);

            // Create thread group container
            const threadGroupEl = document.createElement('div');
            threadGroupEl.className = 'thread-chart-group';
            threadGroupEl.setAttribute('data-threads', threads);

            const threadLabelEl = document.createElement('div');
            threadLabelEl.className = 'thread-charts-label';
            threadLabelEl.textContent = threadKey;
            threadGroupEl.appendChild(threadLabelEl);

            // Don't render charts yet - will be done on first expand
            threadGroupElements[threads] = threadGroupEl;
            contentEl.appendChild(threadGroupEl);
        });

        // Track expansion state and rendering
        let isExpanded = false;
        let chartsRendered = false;

        // Toggle expand/collapse
        headerEl.onclick = () => {
            if (!isExpanded) {
                // Expanding
                if (!chartsRendered) {
                    // First time expanding - render charts
                    threadKeys.forEach(threadKey => {
                        const threads = parseInt(threadKey.split(' ')[0]);
                        const threadGroupEl = threadGroupElements[threads];

                        // Render charts for this thread group
                        renderChartsForThreadGroup(machine, op, threads, threadGroupEl, selectedTestBranch);
                    });
                    chartsRendered = true;
                }

                contentEl.classList.add('expanded');
                headerEl.querySelector('.expand-icon').classList.add('expanded');
                isExpanded = true;
            } else {
                // Collapsing - just hide, don't destroy charts
                contentEl.classList.remove('expanded');
                headerEl.querySelector('.expand-icon').classList.remove('expanded');
                isExpanded = false;
            }
        };

        opElement.appendChild(headerEl);
        opElement.appendChild(contentEl);
        container.appendChild(opElement);
    });
}

function switchViewToDetail() {
    const overviewView = document.getElementById('overview-view');
    const detailView = document.getElementById('detail-view');

    overviewView.classList.remove('active');
    detailView.classList.add('active');
    currentView = 'detail';
}

// Charting Functions
function renderChart(data) {
    const ctx = document.getElementById('chart').getContext('2d');

    if (chartInstance) {
        chartInstance.destroy();
    }

    const chartConfig = {
        type: data.chart.type,
        data: {
            labels: data.chart.labels,
            datasets: data.chart.datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 10
                    },
                    title: {
                        display: true,
                        text: 'Performance (GFLOP/s per core)'
                    }
                }
            }
        }
    };

    if (data.chart.type === 'line') {
        chartConfig.options.scales.y.grid = {
            drawBorder: true,
            color: 'rgba(0, 0, 0, 0.1)',
            lineWidth: 1
        };
    }

    chartInstance = new Chart(ctx, chartConfig);
}

// Main Plot Generation Function
function generatePlot() {
    try {
        clearMessages();

        if (!db) {
            showError('Please load a database first');
            return;
        }

        showLoading();

        const plotType = document.getElementById('plot-type').value;
        const machine = getParam('machine');
        const dt = getParam('dt');
        const threads = getParam('threads');
        const m = getParam('m');
        const n = getParam('n');
        const k = getParam('k');

        const result = {
            type: plotType,
            params: { machine, dt, threads, m, n, k }
        };

        let rows;

        if (plotType === 'historical') {
            const tag = getParam('tag');
            const op = getParam('op');

            if (!tag || tag === -1) {
                throw new Error('Tag is required for Historical plots');
            }
            if (!op || op === -1) {
                throw new Error('Operation is required for Historical plots');
            }

            result.params.tag = tag;
            result.params.op = op;

            rows = queryHistoricalPlot(machine, op, dt, threads, tag, m, n, k);

            // Group by date and keep max gflops for each date
            const dataByDate = {};
            rows.forEach(row => {
                const date = new Date(row.timestamp).toISOString().split('T')[0];
                if (!dataByDate[date]) {
                    dataByDate[date] = row.gflops;
                } else {
                    dataByDate[date] = Math.max(dataByDate[date], row.gflops);
                }
            });

            const labels = Object.keys(dataByDate);
            const data = labels.map(date => dataByDate[date]);

            result.chart = {
                type: 'line',
                labels,
                datasets: [{
                    label: 'Performance (GFLOP/s per core)',
                    data,
                    borderColor: 'rgb(75, 192, 192)',
                    backgroundColor: 'rgba(75, 192, 192, 0.1)',
                    tension: 0.1
                }]
            };

        } else if (plotType === 'scaling') {
            const git = getParam('git-scaling');
            const op = getParam('op-scaling');

            if (!git || git === -1) {
                throw new Error('Git commit is required for Scaling plots');
            }
            if (!op || op === -1) {
                throw new Error('Operation is required for Scaling plots');
            }

            result.params.git = git;
            result.params.op = op;

            const { rows: scalingRows, varyingDim } = queryScalingPlot(git, machine, op, dt, threads, m, n, k);

            const dataByDim = {};
            scalingRows.forEach(row => {
                const dimValue = row[varyingDim];
                if (!dataByDim[dimValue]) dataByDim[dimValue] = [];
                dataByDim[dimValue].push(row.gflops);
            });

            const labels = Object.keys(dataByDim).map(Number).sort((a, b) => a - b);
            const data = labels.map(label => {
                const values = dataByDim[label];
                return Math.max(...values);
            });

            result.chart = {
                type: 'line',
                labels: labels.map(String),
                datasets: [{
                    label: `Performance vs ${varyingDim.toUpperCase()} (GFLOP/s per core)`,
                    data,
                    borderColor: 'rgb(153, 102, 255)',
                    backgroundColor: 'rgba(153, 102, 255, 0.1)',
                    tension: 0.1
                }]
            };

        } else if (plotType === 'overview') {
            const git = getParam('git-overview');

            if (!git || git === -1) {
                throw new Error('Git commit is required for Overview plots');
            }
            if (m === -1 || n === -1 || k === -1) {
                throw new Error('M, N, and K must all be specified for Overview plots');
            }

            result.params.git = git;

            rows = queryOverviewPlot(git, machine, threads, dt, m, n, k);

            const dataByOp = {};
            rows.forEach(row => {
                if (!dataByOp[row.op]) dataByOp[row.op] = [];
                dataByOp[row.op].push(row.gflops);
            });

            const labels = Object.keys(dataByOp).sort();
            const data = labels.map(label => {
                const values = dataByOp[label];
                return Math.max(...values);
            });

            const colors = [
                'rgb(255, 99, 132)',
                'rgb(54, 162, 235)',
                'rgb(255, 206, 86)',
                'rgb(75, 192, 192)',
                'rgb(153, 102, 255)',
                'rgb(255, 159, 64)'
            ];

            result.chart = {
                type: 'bar',
                labels,
                datasets: [{
                    label: 'Performance (GFLOP/s per core)',
                    data,
                    backgroundColor: colors.slice(0, labels.length)
                }]
            };
        }

        if (!result.chart.labels || result.chart.labels.length === 0) {
            throw new Error('No data found matching the specified criteria');
        }

        showParams(result.params, result.type);
        clearLoading();
        renderChart(result);

    } catch (error) {
        showError(`Error: ${error.message}`);
        clearLoading();
    }
}

// Event Listeners
document.addEventListener('DOMContentLoaded', function() {
    // Auto-load the perf.sqlite database on page load
    autoLoadDatabase();

    // Allow Enter to generate plot
    document.addEventListener('keypress', (event) => {
        if (event.key === 'Enter' && event.target.closest('.control-panel')) {
            generatePlot();
        }
    });
});
