// ─── State ───────────────────────────────────────────────────────────────────
// Holds the API base URL. Empty string = use Vite proxy (local dev).
// Set via the Settings panel to point at the live AWS deployment.
let apiBase = localStorage.getItem('apiBase') || '';

// ─── DOM references ───────────────────────────────────────────────────────────
const urlInput      = document.getElementById('urlInput');
const checkBtn      = document.getElementById('checkBtn');
const loading       = document.getElementById('loading');
const results       = document.getElementById('results');
const errorBanner   = document.getElementById('errorBanner');
const errorMessage  = document.getElementById('errorMessage');
const errorClose    = document.getElementById('errorClose');
const settingsToggle = document.getElementById('settingsToggle');
const settingsPanel  = document.getElementById('settingsPanel');
const apiUrlInput    = document.getElementById('apiUrl');
const saveSettings   = document.getElementById('saveSettings');

// Pre-fill the settings input with whatever was saved previously
apiUrlInput.value = apiBase;

// ─── Settings panel toggle ────────────────────────────────────────────────────
// Shows/hides the API configuration section when the user clicks Settings
settingsToggle.addEventListener('click', () => {
  settingsPanel.classList.toggle('open');
});

// Saves the API base URL to localStorage so it persists across page refreshes
saveSettings.addEventListener('click', () => {
  apiBase = apiUrlInput.value.trim().replace(/\/$/, ''); // strip trailing slash
  localStorage.setItem('apiBase', apiBase);
  settingsPanel.classList.remove('open');
});

// ─── Keyboard shortcut ────────────────────────────────────────────────────────
// Pressing Enter in the URL field triggers a check — same as clicking the button
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') checkWebsite();
});

// Wire up the Check button
checkBtn.addEventListener('click', checkWebsite);

// Wire up the error dismiss button
errorClose.addEventListener('click', hideError);

// Auto-focus the URL input when the page loads
urlInput.focus();

// ─── Main check function ──────────────────────────────────────────────────────
// Called when the user clicks Check or presses Enter.
// Reads the URL and check type, calls the backend API, then renders results.
async function checkWebsite() {
  const url       = urlInput.value.trim();
  const checkType = document.querySelector('input[name="checkType"]:checked').value;

  // Validate: don't allow empty input
  if (!url) {
    showError('Please enter a website URL.');
    return;
  }

  // Switch UI into loading state
  hideError();
  setLoading(true);
  results.innerHTML = '';

  try {
    // Choose the correct endpoint based on single vs multi-region mode
    const endpoint = checkType === 'multi' ? '/check-multi' : '/check';
    const fullUrl  = apiBase + endpoint;

    const response = await fetch(fullUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });

    const data = await response.json();

    if (!response.ok) {
      // Backend returned an error (e.g. 400 bad URL, 500 server error)
      showError(data.error || 'Something went wrong. Please try again.');
      return;
    }

    // Render the results into the page
    renderResults(data, checkType);

  } catch (err) {
    // Network-level error — backend is unreachable or CORS issue
    showError('Could not reach the backend. Make sure the API server is running.');
  } finally {
    // Always turn off loading state when done
    setLoading(false);
  }
}

// ─── Render results ───────────────────────────────────────────────────────────
// Decides whether to render a single-region or multi-region result layout
function renderResults(data, checkType) {
  if (checkType === 'multi') {
    results.innerHTML = buildMultiRegionHTML(data);
  } else {
    results.innerHTML = buildSingleRegionHTML(data);
  }

  // Add a clear button below the results
  const clearBtn = document.createElement('button');
  clearBtn.className = 'btn-clear';
  clearBtn.textContent = 'Clear results';
  clearBtn.addEventListener('click', () => { results.innerHTML = ''; });
  results.appendChild(clearBtn);
}

// ─── Single-region result layout ──────────────────────────────────────────────
// Builds the HTML for a single-region check: summary card + three detail cards
function buildSingleRegionHTML(data) {
  return `
    ${buildSummaryCard(data)}
    <div class="detail-grid">
      ${buildDNSCard(data.detailed_checks.dns)}
      ${buildHTTPCard(data.detailed_checks.http)}
      ${buildPortCard(data.detailed_checks.port)}
    </div>
    ${data.external_checks ? buildExternalChecks(data.external_checks) : ''}
  `;
}

// ─── Multi-region result layout ───────────────────────────────────────────────
// Builds the HTML for a multi-region check: overview card + one card per region
function buildMultiRegionHTML(data) {
  const statusClass = getBadgeClass(data.overall_status);
  const statusIcon  = getStatusIcon(data.overall_status);

  let html = `
    <div class="summary-card">
      <div class="summary-top">
        <div class="summary-domain">${escapeHTML(data.url)}</div>
        <div class="summary-meta">
          <span class="badge ${statusClass}">${statusIcon} ${data.overall_status}</span>
        </div>
      </div>
      <div class="region-overview">
        <span class="region-count">${data.regions_up} / ${data.total_regions}</span> regions reachable
        &nbsp;·&nbsp; ${escapeHTML(data.analysis)}
      </div>
      <div class="summary-info" style="margin-top:14px">
        <span><strong>Checked at</strong> ${formatTimestamp(data.timestamp)}</span>
      </div>
    </div>
  `;

  // One card per region result
  data.results.forEach((result, i) => {
    html += `
      <div class="summary-card">
        <div class="summary-top">
          <div class="summary-domain" style="font-size:1.1rem">Region ${i + 1}: ${escapeHTML(result.region)}</div>
          <div class="summary-meta">
            <span class="badge ${getBadgeClass(result.status)}">${getStatusIcon(result.status)} ${result.status}</span>
            <span class="rt-pill ${getRTPillClass(result.response_time_ms)}">${result.response_time_ms} ms</span>
          </div>
        </div>
        <div class="detail-grid" style="margin-top:16px">
          ${buildDNSCard(result.detailed_checks.dns)}
          ${buildHTTPCard(result.detailed_checks.http)}
          ${buildPortCard(result.detailed_checks.port)}
        </div>
      </div>
    `;
  });

  return html;
}

// ─── Summary card ─────────────────────────────────────────────────────────────
// The big top card showing domain name, overall status badge, and response time
function buildSummaryCard(data) {
  return `
    <div class="summary-card">
      <div class="summary-top">
        <div class="summary-domain">${escapeHTML(data.domain)}</div>
        <div class="summary-meta">
          <span class="badge ${getBadgeClass(data.status)}">${getStatusIcon(data.status)} ${data.status}</span>
          <span class="rt-pill ${getRTPillClass(data.response_time_ms)}">${data.response_time_ms} ms</span>
        </div>
      </div>
      <div class="summary-info">
        <span><strong>Region</strong> ${escapeHTML(data.region)}</span>
        <span><strong>Checked at</strong> ${formatTimestamp(data.timestamp)}</span>
        <span><strong>Summary</strong> ${escapeHTML(data.summary)}</span>
      </div>
    </div>
  `;
}

// ─── DNS detail card ──────────────────────────────────────────────────────────
// Shows how many DNS servers resolved the domain and their individual results
function buildDNSCard(dns) {
  const servers = dns.results.map(r => `
    <div class="dns-server-row">
      <span>${r.dns_server}</span>
      <span class="${r.status === 'success' ? 'dns-ok' : 'dns-fail'}">
        ${r.status === 'success' ? `✓ ${r.ip_address}` : '✗ failed'}
      </span>
    </div>
  `).join('');

  return `
    <div class="detail-card">
      <div class="detail-card-header"><span class="card-icon">🔎</span> DNS Resolution</div>
      <div class="detail-row">
        <span class="detail-key">Status</span>
        <span class="detail-val">${dns.overall_status}</span>
      </div>
      <div class="detail-row">
        <span class="detail-key">Servers resolved</span>
        <span class="detail-val">${dns.success_count} / ${dns.total_servers}</span>
      </div>
      <div class="dns-server-list">${servers}</div>
    </div>
  `;
}

// ─── HTTP detail card ─────────────────────────────────────────────────────────
// Shows the HTTP response: status code, response time, content size, redirect info
function buildHTTPCard(http) {
  const rows = [];

  rows.push({ key: 'Status',        val: http.status });
  if (http.status_code)     rows.push({ key: 'Status code',    val: http.status_code });
  if (http.response_time_ms) rows.push({ key: 'Response time', val: `${http.response_time_ms} ms` });
  if (http.content_length)  rows.push({ key: 'Content size',   val: formatBytes(http.content_length) });
  if (http.redirected)      rows.push({ key: 'Redirected to',  val: http.final_url });
  if (http.error)           rows.push({ key: 'Error',          val: http.error });

  return `
    <div class="detail-card">
      <div class="detail-card-header"><span class="card-icon">🌐</span> HTTP Response</div>
      ${rows.map(r => `
        <div class="detail-row">
          <span class="detail-key">${r.key}</span>
          <span class="detail-val">${escapeHTML(String(r.val))}</span>
        </div>
      `).join('')}
    </div>
  `;
}

// ─── Port connectivity card ───────────────────────────────────────────────────
// Shows whether the server's port (80 or 443) is open and accepting connections
function buildPortCard(port) {
  const rows = [
    { key: 'Port',   val: port.port },
    { key: 'Status', val: port.status }
  ];
  if (port.response_time_ms) rows.push({ key: 'Response time', val: `${port.response_time_ms} ms` });
  if (port.error)            rows.push({ key: 'Error',         val: port.error });

  return `
    <div class="detail-card">
      <div class="detail-card-header"><span class="card-icon">🔌</span> Port Connectivity</div>
      ${rows.map(r => `
        <div class="detail-row">
          <span class="detail-key">${r.key}</span>
          <span class="detail-val">${escapeHTML(String(r.val))}</span>
        </div>
      `).join('')}
    </div>
  `;
}

// ─── External checks section ──────────────────────────────────────────────────
// Shows what third-party monitoring services think about the site's status
function buildExternalChecks(external) {
  const chips = Object.entries(external).map(([service, result]) => {
    const cls = result.status === 'up' ? 'ext-up' : result.status === 'down' ? 'ext-down' : 'ext-unknown';
    const icon = result.status === 'up' ? '✓' : result.status === 'down' ? '✗' : '?';
    return `
      <div class="external-chip">
        <span class="ext-name">${escapeHTML(service)}</span>
        <span class="ext-status ${cls}">${icon} ${result.status}</span>
      </div>
    `;
  }).join('');

  return `
    <div class="summary-card external-section">
      <div class="external-title">External Validators</div>
      <div class="external-grid">${chips}</div>
    </div>
  `;
}

// ─── Helper: status badge CSS class ──────────────────────────────────────────
// Maps a status string (up/down/partial/etc.) to the right CSS class
function getBadgeClass(status) {
  const map = { up: 'badge-up', down: 'badge-down', partial: 'badge-partial', dns_only: 'badge-dns_only', mixed: 'badge-mixed' };
  return map[status] || 'badge-unknown';
}

// ─── Helper: status icon ──────────────────────────────────────────────────────
// Returns a small icon for each possible status value
function getStatusIcon(status) {
  const map = { up: '●', down: '●', partial: '◐', dns_only: '◑', mixed: '◑' };
  return map[status] || '○';
}

// ─── Helper: response time CSS class ─────────────────────────────────────────
// Colors the response time green (fast), yellow (medium), or red (slow)
function getRTPillClass(ms) {
  if (ms < 200)  return 'rt-fast';
  if (ms < 600)  return 'rt-medium';
  return 'rt-slow';
}

// ─── Helper: format bytes into human-readable size ────────────────────────────
// Turns raw byte counts like 80098 into "78.2 KB" — readable for anyone
function formatBytes(bytes) {
  if (bytes < 1024)        return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── Helper: format UTC timestamp into local readable time ────────────────────
function formatTimestamp(ts) {
  return new Date(ts + 'Z').toLocaleString();
}

// ─── Helper: escape HTML to prevent XSS ──────────────────────────────────────
// Never inject raw user input or API strings directly into innerHTML without this
function escapeHTML(str) {
  return String(str).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

// ─── UI state helpers ─────────────────────────────────────────────────────────
function setLoading(on) {
  loading.classList.toggle('visible', on);
  checkBtn.disabled = on;
}

function showError(msg) {
  errorMessage.textContent = msg;
  errorBanner.classList.add('visible');
}

function hideError() {
  errorBanner.classList.remove('visible');
}
