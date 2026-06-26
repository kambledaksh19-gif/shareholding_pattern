// App state
let currentStockData = null;
let selectedYear = null;
let selectedTab = "summary"; // summary, promoter, public, non_promoter
let trendChart = null;

// DOM Elements
const searchInput = document.getElementById("search-input");
const searchSpinner = document.getElementById("search-spinner");
const suggestionsList = document.getElementById("suggestions-list");
const landingHero = document.getElementById("landing-hero");
const mainLoader = document.getElementById("main-loader");
const loaderStatus = document.getElementById("loader-status");
const dashboardContent = document.getElementById("dashboard-content");
const themeToggle = document.getElementById("theme-toggle");

// Suggestion delay variables
let searchTimeout = null;

// Initialize theme
if (localStorage.getItem("theme") === "light") {
    document.body.classList.remove("dark-mode");
    document.body.classList.add("light-mode");
    themeToggle.innerHTML = '<i class="fa-solid fa-moon"></i>';
} else {
    document.body.classList.add("dark-mode");
    document.body.classList.remove("light-mode");
    themeToggle.innerHTML = '<i class="fa-solid fa-sun"></i>';
}

// 1. Theme toggle listener
themeToggle.addEventListener("click", () => {
    if (document.body.classList.contains("dark-mode")) {
        document.body.classList.remove("dark-mode");
        document.body.classList.add("light-mode");
        themeToggle.innerHTML = '<i class="fa-solid fa-moon"></i>';
        localStorage.setItem("theme", "light");
    } else {
        document.body.classList.add("dark-mode");
        document.body.classList.remove("light-mode");
        themeToggle.innerHTML = '<i class="fa-solid fa-sun"></i>';
        localStorage.setItem("theme", "dark");
    }
    // Re-render chart if open to match theme
    if (currentStockData) {
        renderTrendChart();
    }
});

// 2. Autocomplete search suggestions
searchInput.addEventListener("input", () => {
    const val = searchInput.value.trim();
    clearTimeout(searchTimeout);
    
    if (!val) {
        suggestionsList.classList.add("hidden");
        searchSpinner.classList.add("hidden");
        return;
    }
    
    searchSpinner.classList.remove("hidden");
    
    searchTimeout = setTimeout(async () => {
        try {
            const r = await fetch(`/api/search?symbol=${encodeURIComponent(val)}`);
            if (r.ok) {
                const data = await r.json();
                renderSuggestions(data);
            }
        } catch (e) {
            console.error("Error fetching suggestions:", e);
        } finally {
            searchSpinner.classList.add("hidden");
        }
    }, 400);
});

// Hide suggestions when clicking outside
document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-box")) {
        suggestionsList.classList.add("hidden");
    }
});

function renderSuggestions(list) {
    suggestionsList.innerHTML = "";
    if (list.length === 0) {
        suggestionsList.classList.add("hidden");
        return;
    }
    
    list.forEach(item => {
        const div = document.createElement("div");
        div.className = "suggestion-item";
        div.innerHTML = `
            <span class="comp-name">${item.company_name}</span>
            <span class="comp-symbol-code">
                <strong>${item.symbol}</strong> ${item.scrip_code}
            </span>
        `;
        div.addEventListener("click", () => {
            searchInput.value = item.symbol || item.scrip_code;
            suggestionsList.classList.add("hidden");
            loadStockData(item.scrip_code);
        });
        suggestionsList.appendChild(div);
    });
    suggestionsList.classList.remove("hidden");
}

// 3. Quick search links
document.querySelectorAll(".quick-search-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const sym = btn.getAttribute("data-symbol");
        searchInput.value = sym;
        loadStockData(sym);
    });
});

// 4. API Fetching Shareholding Database
async function loadStockData(scripcode) {
    if (typeof batchPanel !== 'undefined' && batchPanel) {
        batchPanel.classList.add("hidden");
    }
    landingHero.classList.add("hidden");
    dashboardContent.classList.add("hidden");
    mainLoader.classList.remove("hidden");
    loaderStatus.innerText = "Connecting to BSE India...";
    
    try {
        loaderStatus.innerText = "Retrieving corporate filing histories...";
        const r = await fetch(`/api/shareholding?scripcode=${encodeURIComponent(scripcode)}`);
        if (!r.ok) {
            const err = await r.json();
            alert(err.detail || "Failed to fetch data.");
            mainLoader.classList.add("hidden");
            landingHero.classList.remove("hidden");
            return;
        }
        
        currentStockData = await r.json();
        renderDashboard();
    } catch (e) {
        console.error("Error loading stock:", e);
        alert("An error occurred while communicating with the server.");
        mainLoader.classList.add("hidden");
        landingHero.classList.remove("hidden");
    }
}

// 5. Render Dashboard
function renderDashboard() {
    mainLoader.classList.add("hidden");
    
    // Fill company information
    document.getElementById("company-name").innerText = currentStockData.company_name;
    document.getElementById("company-meta").innerText = `Scrip Code: ${currentStockData.scrip_code} | Symbol: ${currentStockData.symbol}`;
    document.getElementById("excel-download-link").href = `/api/download?scripcode=${currentStockData.scrip_code}`;
    
    const years = Object.keys(currentStockData.years).sort((a,b) => parseInt(b) - parseInt(a)); // Sort descending
    document.getElementById("stat-years").innerText = years.length;
    
    // Extract latest promoters / public shares %
    if (years.length > 0) {
        const latestYearData = currentStockData.years[years[0]];
        const summary = latestYearData.summary || [];
        const prom = summary.find(x => x.category.includes("(A)"));
        const pub = summary.find(x => x.category.includes("(B)"));
        document.getElementById("stat-promoters").innerText = prom ? `${prom.percentage.toFixed(2)}%` : "N/A";
        document.getElementById("stat-public").innerText = pub ? `${pub.percentage.toFixed(2)}%` : "N/A";
        
        // Select latest year tab by default
        selectedYear = years[0];
    } else {
        document.getElementById("stat-promoters").innerText = "N/A";
        document.getElementById("stat-public").innerText = "N/A";
        selectedYear = null;
    }
    
    // Generate Year Selection Tabs
    renderYearTabs(years);
    
    // Draw Trend Chart
    renderTrendChart();
    
    // Render current active table
    renderTable();
    
    dashboardContent.classList.remove("hidden");
}

// Year Tabs
function renderYearTabs(years) {
    const container = document.getElementById("year-tabs-container");
    container.innerHTML = "";
    
    years.forEach(yr => {
        const btn = document.createElement("button");
        btn.className = `year-tab-btn ${yr === selectedYear ? 'active' : ''}`;
        btn.innerText = `Mar ${yr}`;
        btn.addEventListener("click", () => {
            document.querySelectorAll(".year-tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            selectedYear = yr;
            renderTable();
        });
        container.appendChild(btn);
    });
    
    // Scroll arrow support
    const tabs = document.getElementById("year-tabs-container");
    document.getElementById("tabs-scroll-left").onclick = () => tabs.scrollLeft -= 120;
    document.getElementById("tabs-scroll-right").onclick = () => tabs.scrollLeft += 120;
}

// Category Tabs
document.querySelectorAll(".table-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".table-tab-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        selectedTab = btn.getAttribute("data-tab");
        renderTable();
    });
});

// 6. Draw Chart.js Line Chart
function renderTrendChart() {
    const years = Object.keys(currentStockData.years).sort((a,b) => parseInt(a) - parseInt(b)); // Sort chronological ascending
    
    const labels = [];
    const promoterData = [];
    const publicData = [];
    const custodianData = [];
    
    years.forEach(yr => {
        labels.push(`Mar ${yr}`);
        const summary = currentStockData.years[yr].summary || [];
        const prom = summary.find(x => x.category.includes("(A)"));
        const pub = summary.find(x => x.category.includes("(B)"));
        const cust = summary.find(x => x.category.includes("(C)"));
        
        promoterData.push(prom ? prom.percentage : 0.0);
        publicData.push(pub ? pub.percentage : 0.0);
        custodianData.push(cust ? cust.percentage : 0.0);
    });
    
    const ctx = document.getElementById("trend-chart").getContext("2d");
    if (trendChart) {
        trendChart.destroy();
    }
    
    const isDark = document.body.classList.contains("dark-mode");
    const gridColor = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
    const textColor = isDark ? "#9ca3af" : "#4b5563";
    
    trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Promoters & Group (%)',
                    data: promoterData,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.05)',
                    borderWidth: 3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    tension: 0.15,
                    fill: true
                },
                {
                    label: 'Public Shareholders (%)',
                    data: publicData,
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.05)',
                    borderWidth: 3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    tension: 0.15,
                    fill: true
                },
                {
                    label: 'Non-Promoter Non-Public (%)',
                    data: custodianData,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    borderWidth: 2,
                    pointRadius: 2,
                    tension: 0.15,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: textColor,
                        font: { family: 'Outfit', size: 11, weight: '500' },
                        boxWidth: 12,
                        padding: 10
                    }
                },
                tooltip: {
                    padding: 10,
                    bodyFont: { family: 'Inter' },
                    titleFont: { family: 'Outfit', weight: 'bold' }
                }
            },
            scales: {
                x: {
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'Inter', size: 10 } }
                },
                y: {
                    min: 0,
                    max: 100,
                    grid: { color: gridColor },
                    ticks: {
                        color: textColor,
                        font: { family: 'Inter', size: 10 },
                        callback: function(value) { return value + "%"; }
                    }
                }
            }
        }
    });
}

// 7. Render Tables Dynamically
function renderTable() {
    const head = document.getElementById("table-head");
    const body = document.getElementById("table-body");
    const emptyMsg = document.getElementById("table-empty-message");
    const stdNote = document.getElementById("reporting-standard");
    
    head.innerHTML = "";
    body.innerHTML = "";
    emptyMsg.classList.add("hidden");
    
    if (!currentStockData || !selectedYear) return;
    
    const year_data = currentStockData.years[selectedYear];
    const qtr_id = year_data.qtr_id;
    
    // Standard note updates based on year (Clause 35 vs Regulation 31)
    if (qtr_id >= 88.0) {
        stdNote.innerText = "SEBI Regulation 31 Format (JSON API)";
    } else {
        stdNote.innerText = "Clause 35 Listing Agreement (ASPX Scrape)";
    }
    
    const rows = year_data[selectedTab] || [];
    
    if (rows.length === 0) {
        emptyMsg.classList.remove("hidden");
        return;
    }
    
    // Render specific category table
    if (selectedTab === "summary") {
        head.innerHTML = `
            <tr>
                <th class="text-left">Category of Shareholder</th>
                <th class="text-right">No. of Shareholders</th>
                <th class="text-right">Total Shares Held</th>
                <th class="text-right">As a % of (A+B+C)</th>
                <th class="text-right">Total Demat Shares</th>
                <th class="text-right">Pledged Shares</th>
                <th class="text-right">Pledged %</th>
            </tr>
        `;
        
        rows.forEach(r => {
            const tr = document.createElement("tr");
            const isGrandTotal = r.category === "Grand Total";
            if (isGrandTotal) {
                tr.className = "total-row";
            }
            
            let colorClass = "";
            if (r.category.includes("(A)")) colorClass = "color-promoter";
            if (r.category.includes("(B)")) colorClass = "color-public";
            if (r.category.includes("(C)")) colorClass = "color-custodian";
            
            tr.innerHTML = `
                <td class="text-left ${colorClass}">${r.category}</td>
                <td class="text-right">${r.no_shareholders.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.shares.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.percentage.toFixed(2)}%</td>
                <td class="text-right">${r.demat_shares.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.pledged_shares > 0 ? r.pledged_shares.toLocaleString('en-IN') : '--'}</td>
                <td class="text-right">${r.pledged_shares > 0 ? r.pledged_percentage.toFixed(2) + '%' : '--'}</td>
            `;
            body.appendChild(tr);
        });
        
    } else if (selectedTab === "promoter") {
        head.innerHTML = `
            <tr>
                <th class="text-left">Shareholder Name</th>
                <th class="text-left">Sub-category</th>
                <th class="text-right">No. of Shareholders</th>
                <th class="text-right">Total Shares Held</th>
                <th class="text-right">Shareholding %</th>
                <th class="text-right">Total Demat Shares</th>
                <th class="text-right">Pledged Shares</th>
                <th class="text-right">Pledged %</th>
            </tr>
        `;
        
        rows.forEach(r => {
            const tr = document.createElement("tr");
            const isTotalRow = r.shareholder_name === "Total";
            const isSubCat = r.shareholder_name === null;
            
            if (isTotalRow) {
                tr.className = "total-row";
            } else if (isSubCat) {
                tr.className = "subtotal-row";
            }
            
            const name = r.shareholder_name || r.category || r.sub_category || "";
            
            tr.innerHTML = `
                <td class="text-left">${name}</td>
                <td class="text-left">${isSubCat ? "" : (r.sub_category || "")}</td>
                <td class="text-right">${r.no_shareholders.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.shares.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.percentage.toFixed(2)}%</td>
                <td class="text-right">${r.demat_shares.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.pledged_shares > 0 ? r.pledged_shares.toLocaleString('en-IN') : '--'}</td>
                <td class="text-right">${r.pledged_shares > 0 ? r.pledged_percentage.toFixed(2) + '%' : '--'}</td>
            `;
            body.appendChild(tr);
        });
        
    } else { // public or non_promoter
        head.innerHTML = `
            <tr>
                <th class="text-left">Shareholder Name</th>
                <th class="text-left">Sub-category</th>
                <th class="text-right">No. of Shareholders</th>
                <th class="text-right">Total Shares Held</th>
                <th class="text-right">Shareholding %</th>
                <th class="text-right">Total Demat Shares</th>
            </tr>
        `;
        
        rows.forEach(r => {
            const tr = document.createElement("tr");
            const isTotalRow = r.shareholder_name === "Total";
            const isSubCat = r.shareholder_name === null;
            
            if (isTotalRow) {
                tr.className = "total-row";
            } else if (isSubCat) {
                tr.className = "subtotal-row";
            }
            
            const name = r.shareholder_name || r.category || r.sub_category || "";
            
            tr.innerHTML = `
                <td class="text-left">${name}</td>
                <td class="text-left">${isSubCat ? "" : (r.sub_category || "")}</td>
                <td class="text-right">${r.no_shareholders.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.shares.toLocaleString('en-IN')}</td>
                <td class="text-right">${r.percentage.toFixed(2)}%</td>
                <td class="text-right">${r.demat_shares.toLocaleString('en-IN')}</td>
            `;
            body.appendChild(tr);
        });
    }
}

// ==========================================
// BATCH COMPILER FRONTEND MODULE
// ==========================================

// DOM Elements
const batchModeBtn = document.getElementById("batch-mode-btn");
const heroBatchBtn = document.getElementById("hero-batch-btn");
const closeBatchBtn = document.getElementById("close-batch-btn");
const batchPanel = document.getElementById("batch-panel");
const dropZone = document.getElementById("drop-zone");
const csvFileInput = document.getElementById("csv-file-input");
const batchProgressContainer = document.getElementById("batch-progress-container");
const batchCurrentSymbol = document.getElementById("batch-current-symbol");
const batchProgressBar = document.getElementById("batch-progress-bar");
const batchProgressText = document.getElementById("batch-progress-text");
const batchStatTotal = document.getElementById("batch-stat-total");
const batchStatCompiled = document.getElementById("batch-stat-compiled");
const batchStatFailed = document.getElementById("batch-stat-failed");
const batchLoader = document.getElementById("batch-loader");
const batchStatusMessage = document.getElementById("batch-status-message");
const batchDownloadBtn = document.getElementById("batch-download-btn");
const batchResetBtn = document.getElementById("batch-reset-btn");
const savePathInput = document.getElementById("save-path-input");
if (savePathInput) {
    // Clean up any legacy cached paths containing "kambl"
    const cachedSavePath = localStorage.getItem("shp_excel_save_path");
    if (cachedSavePath && cachedSavePath.toLowerCase().includes("kambl")) {
        localStorage.removeItem("shp_excel_save_path");
    }
    
    // Clear the input value if the browser auto-filled it from history/cache
    if (savePathInput.value && savePathInput.value.toLowerCase().includes("kambl")) {
        savePathInput.value = "";
    }

    const currentCached = localStorage.getItem("shp_excel_save_path");
    if (currentCached) {
        savePathInput.value = currentCached;
    }
    
    savePathInput.addEventListener("input", () => {
        localStorage.setItem("shp_excel_save_path", savePathInput.value.trim());
    });
}
const batchErrorsContainer = document.getElementById("batch-errors-container");
const batchErrorsList = document.getElementById("batch-errors-list");

let batchPollingInterval = null;
let activeBatchJobId = null;

function showBatchMode() {
    landingHero.classList.add("hidden");
    dashboardContent.classList.add("hidden");
    mainLoader.classList.add("hidden");
    batchPanel.classList.remove("hidden");
}

function hideBatchMode() {
    batchPanel.classList.add("hidden");
    if (currentStockData) {
        dashboardContent.classList.remove("hidden");
    } else {
        landingHero.classList.remove("hidden");
    }
}

// Click on dropzone triggers file dialog
dropZone.addEventListener("click", () => {
    csvFileInput.click();
});

// File input change handler
csvFileInput.addEventListener("change", (e) => {
    if (csvFileInput.files.length > 0) {
        uploadCSV(csvFileInput.files[0]);
    }
});

// Drag and drop handlers
['dragenter', 'dragover'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    }, false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
    }, false);
});

dropZone.addEventListener('drop', (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
        uploadCSV(files[0]);
    }
}, false);

// Upload CSV to API
async function uploadCSV(file) {
    if (!file.name.endsWith('.csv')) {
        alert("Please select a valid CSV file.");
        return;
    }
    
    const savePath = savePathInput.value.trim();
    if (!savePath) {
        alert("Please enter a valid absolute path to save the Excel file.");
        return;
    }
    if (!savePath.toLowerCase().endsWith(".xlsx")) {
        alert("The save path must end with '.xlsx'.");
        return;
    }
    
    const formData = new FormData();
    formData.append("file", file);
    formData.append("save_path", savePath);
    
    dropZone.classList.add("hidden");
    batchProgressContainer.classList.remove("hidden");
    batchCurrentSymbol.innerText = "Reading CSV file...";
    batchProgressBar.style.width = "0%";
    batchProgressText.innerText = "0%";
    batchStatTotal.innerText = "0";
    batchStatCompiled.innerText = "0";
    batchStatFailed.innerText = "0";
    batchLoader.classList.remove("hidden");
    batchStatusMessage.innerText = "Initializing batch job...";
    batchDownloadBtn.classList.add("hidden");
    batchDownloadBtn.innerHTML = '<i class="fa-solid fa-file-excel"></i> Download Excel Report';
    batchResetBtn.classList.add("hidden");
    batchErrorsContainer.classList.add("hidden");
    batchErrorsList.innerHTML = "";
    
    try {
        const response = await fetch("/api/batch", {
            method: "POST",
            body: formData
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Failed to initialize batch job.");
        }
        
        const data = await response.json();
        activeBatchJobId = data.job_id;
        batchStatTotal.innerText = data.total;
        
        // Start polling status
        startBatchPolling(data.job_id);
    } catch (err) {
        console.error("Error uploading CSV:", err);
        alert(err.message || "An error occurred during file upload.");
        resetBatchView();
    }
}

// Poll batch job status
function startBatchPolling(jobId) {
    if (batchPollingInterval) {
        clearInterval(batchPollingInterval);
    }
    
    batchPollingInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/batch/status?job_id=${encodeURIComponent(jobId)}`);
            if (!res.ok) {
                clearInterval(batchPollingInterval);
                throw new Error("Failed to get job status.");
            }
            
            const data = await res.json();
            
            // Update stats
            batchStatTotal.innerText = data.total;
            batchStatCompiled.innerText = data.completed;
            batchStatFailed.innerText = data.failed;
            
            const processed = data.completed + data.failed;
            const pct = data.total > 0 ? Math.round((processed / data.total) * 100) : 0;
            batchProgressBar.style.width = `${pct}%`;
            batchProgressText.innerText = `${pct}%`;
            
            // Render company errors in real-time
            if (data.errors && data.errors.length > 0) {
                batchErrorsContainer.classList.remove("hidden");
                batchErrorsList.innerHTML = "";
                data.errors.forEach(item => {
                    const div = document.createElement("div");
                    div.style.background = "rgba(239, 68, 68, 0.08)";
                    div.style.border = "1px solid rgba(239, 68, 68, 0.2)";
                    div.style.borderRadius = "6px";
                    div.style.padding = "10px 12px";
                    div.style.marginBottom = "8px";
                    div.style.display = "flex";
                    div.style.flexDirection = "column";
                    div.style.gap = "4px";

                    div.innerHTML = `
                        <div style="font-weight: 600; color: #f87171; display: flex; justify-content: space-between;">
                            <span><i class="fa-solid fa-circle-xmark"></i> ${item.symbol}</span>
                        </div>
                        <div style="color: var(--text-secondary); font-family: monospace; font-size: 12px; white-space: pre-wrap;">${item.error}</div>
                    `;
                    batchErrorsList.appendChild(div);
                });
            } else {
                batchErrorsContainer.classList.add("hidden");
                batchErrorsList.innerHTML = "";
            }
            
            if (data.status === "processing") {
                batchCurrentSymbol.innerText = `Currently processing: ${data.current_symbol || 'Please wait...'}`;
                batchStatusMessage.innerText = `Scraping and compiling ${processed} of ${data.total} companies...`;
                if (data.completed > 0) {
                    batchDownloadBtn.href = `/api/batch/download?job_id=${encodeURIComponent(jobId)}`;
                    batchDownloadBtn.innerHTML = '<i class="fa-solid fa-file-excel"></i> Download Partial Excel Report';
                    batchDownloadBtn.classList.remove("hidden");
                }
            } else if (data.status === "completed") {
                clearInterval(batchPollingInterval);
                batchCurrentSymbol.innerText = "Compilation complete!";
                batchProgressBar.style.width = "100%";
                batchProgressText.innerText = "100%";
                batchStatusMessage.innerText = `Successfully compiled ${data.completed} companies!`;
                batchLoader.classList.add("hidden");
                batchDownloadBtn.href = `/api/batch/download?job_id=${encodeURIComponent(jobId)}`;
                batchDownloadBtn.innerHTML = '<i class="fa-solid fa-file-excel"></i> Download Excel Report';
                batchDownloadBtn.classList.remove("hidden");
                batchResetBtn.classList.remove("hidden");
            } else if (data.status === "failed") {
                clearInterval(batchPollingInterval);
                batchCurrentSymbol.innerText = "Compilation failed.";
                batchStatusMessage.innerText = `Error: ${data.error || 'Job execution failed.'}`;
                batchLoader.classList.add("hidden");
                batchResetBtn.classList.remove("hidden");
            }
        } catch (e) {
            console.error("Error polling batch status:", e);
            clearInterval(batchPollingInterval);
            batchStatusMessage.innerText = "Lost connection to server polling.";
            batchLoader.classList.add("hidden");
            batchResetBtn.classList.remove("hidden");
        }
    }, 1500);
}

function resetBatchView() {
    if (batchPollingInterval) {
        clearInterval(batchPollingInterval);
        batchPollingInterval = null;
    }
    activeBatchJobId = null;
    csvFileInput.value = "";
    dropZone.classList.remove("hidden");
    batchProgressContainer.classList.add("hidden");
    batchErrorsContainer.classList.add("hidden");
    batchErrorsList.innerHTML = "";
}

// Switch button listeners
batchModeBtn.addEventListener("click", showBatchMode);
heroBatchBtn.addEventListener("click", showBatchMode);
closeBatchBtn.addEventListener("click", hideBatchMode);
batchResetBtn.addEventListener("click", resetBatchView);
