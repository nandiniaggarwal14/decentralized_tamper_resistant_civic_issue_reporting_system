// Citizen Console Business Logic
let token = null;
let currentUser = null;
const feedContainer = document.getElementById('feed-container');

// Auth Guard Check
async function initializeDashboard() {
  token = auth.getToken();
  currentUser = await auth.checkAuthGuard(['citizen']);
  
  if (currentUser) {
    // Populate profile card
    document.getElementById('profile-name').textContent = currentUser.full_name;
    const initials = currentUser.full_name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase();
    document.getElementById('profile-initials').textContent = initials.substring(0, 2);
    
    // Load Feed
    await loadIssues();
  }
}

// Show Alerts
function showAlert(text, isError = false) {
  const banner = document.getElementById('alert-banner');
  const textEl = document.getElementById('alert-text');
  if (banner && textEl) {
    textEl.textContent = text;
    banner.className = `alert-banner ${isError ? 'alert-error' : 'alert-success'}`;
    banner.style.display = 'flex';
    setTimeout(() => { banner.style.display = 'none'; }, 5000);
  }
}

// Fetch and render issues list
async function loadIssues() {
  try {
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
    const url = '/api/issues';
    const res = await fetch(url, { headers });
    const data = await res.json();
    
    if (res.ok && data.success) {
      renderIssues(data.data);
    } else {
      feedContainer.innerHTML = `<p style="text-align: center; color: var(--text-muted); padding: 40px;">Failed to load complaints feed.</p>`;
    }
  } catch (err) {
    console.error('Error fetching issues:', err);
    feedContainer.innerHTML = `<p style="text-align: center; color: var(--text-muted); padding: 40px;">Connection failure. Is the server running?</p>`;
  }
}

// Render Issues Grid
function renderIssues(issues) {
  if (!issues || issues.length === 0) {
    feedContainer.innerHTML = `
      <div style="text-align: center; color: var(--text-muted); padding: 60px;">
        <span style="font-size: 3rem; display: block; margin-bottom: 16px;">🌱</span>
        <p data-i18n="no_reports">No civic issues reported yet.</p>
      </div>
    `;
    if (window.i18n) window.i18n.translatePage();
    return;
  }

  feedContainer.innerHTML = issues.map(issue => {
    const statusText = window.i18n ? window.i18n.t(`badge-${issue.status}`, issue.status) : issue.status;
    const priorityText = window.i18n ? window.i18n.t(`badge-priority-${issue.priority}`, issue.priority) : issue.priority;
    
    // Parse uploaded media
    const mediaHTML = (issue.media_urls || []).map(media => {
      if (media.type === 'image') {
        return `<img src="${media.url}" class="gallery-image" onclick="window.open('${media.url}')" title="IPFS CID: ${media.cid}">`;
      } else if (media.type === 'audio') {
        return `
          <div class="media-audio-wrapper" style="width: 100%; margin-top: 8px;">
            <audio controls style="width: 100%; height: 36px;"><source src="${media.url}"></audio>
            <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 4px;">IPFS: ${media.cid}</div>
          </div>
        `;
      } else if (media.type === 'video') {
        return `
          <div class="media-video-wrapper" style="margin-top: 8px;">
            <video controls style="max-width: 100%; max-height: 200px; border-radius: 6px;"><source src="${media.url}"></video>
            <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 4px;">IPFS: ${media.cid}</div>
          </div>
        `;
      }
      return '';
    }).join('');

    const formattedDate = new Date(issue.created_at).toLocaleString();

    // Verify translations
    const verifBtnText = window.i18n ? window.i18n.t('verify_integrity', 'Verify Integrity') : 'Verify Integrity';

    return `
      <div class="issue-card ${issue.status}">
        <div class="issue-header">
          <div>
            <span class="badge badge-${issue.status}">${statusText}</span>
            <span class="badge badge-priority-${issue.priority}">${priorityText}</span>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 6px;">
              Category: <strong>${window.i18n ? window.i18n.t(issue.category, issue.category) : issue.category}</strong>
            </div>
          </div>
          <div style="font-size: 0.75rem; color: var(--text-muted);">${formattedDate}</div>
        </div>

        <h3 class="issue-title">${escapeHtml(issue.title)}</h3>
        <p class="issue-body">${escapeHtml(issue.description)}</p>

        <!-- Gallery -->
        <div class="media-gallery">
          ${mediaHTML}
        </div>

        <!-- Meta list -->
        <div class="issue-meta-info">
          <span>Area: <strong>${escapeHtml(issue.area)}</strong></span>
          <span>Reporter: <strong>${escapeHtml(issue.reporter.name)}</strong></span>
          <span>Ward: <strong>${issue.ward_name || 'Unassigned'}</strong></span>
          <span>Upvotes: <strong>${issue.votes.upvotes}</strong></span>
        </div>

        <!-- Actions footer -->
        <div class="issue-footer">
          <button onclick="auditIssueHash('${issue.id}')" class="btn btn-secondary" style="padding: 6px 12px; font-size: 0.8rem;">🔍 ${verifBtnText}</button>
          
          <!-- Upvote Widget -->
          <div class="vote-widget">
            <button onclick="castVote('${issue.id}', 'up')" class="vote-btn up ${issue.votes.user_vote === 'up' ? 'active' : ''}">▲</button>
            <span class="vote-number" style="color: ${issue.votes.score >= 0 ? 'var(--success)' : 'var(--danger)'}">${issue.votes.score}</span>
            <button onclick="castVote('${issue.id}', 'down')" class="vote-btn down ${issue.votes.user_vote === 'down' ? 'active' : ''}">▼</button>
          </div>
        </div>

        <!-- Cryptographic Audit Display -->
        <div id="audit-panel-${issue.id}" class="audit-box" style="display: none;"></div>
      </div>
    `;
  }).join('');

  if (window.i18n) window.i18n.translatePage();
}

// Vote handling
async function castVote(issueId, voteType) {
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(`/api/issues/${issueId}/vote`, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ vote_type: voteType })
    });
    if (res.ok) {
      await loadIssues();
    } else {
      const errData = await res.json();
      showAlert(errData.detail || 'Failed to submit vote response.', true);
    }
  } catch (err) {
    showAlert('Error connecting to voting service.', true);
  }
}

// Verify Cryptographic Hash on Sepolia Testnet
async function auditIssueHash(issueId) {
  const panel = document.getElementById(`audit-panel-${issueId}`);
  panel.style.display = 'block';
  panel.innerHTML = `<span style="animation: pulse-text 1s infinite;">Reading Ethereum contract nodes...</span>`;

  try {
    const res = await fetch(`/api/verify/${issueId}`);
    const data = await res.json();
    
    if (res.ok && data.success) {
      // Localized labels
      const matchingLabel = window.i18n ? window.i18n.t('matching', 'Matching') : '✓ Matching';
      const mismatchLabel = window.i18n ? window.i18n.t('discrepancy', 'Discrepancy!') : '✗ Discrepancy!';
      const securedLabel = window.i18n ? window.i18n.t('verified_secured', 'Verified (Secured)') : '✓ Verified (Secured)';
      const invalidLabel = window.i18n ? window.i18n.t('invalid_hash', 'Invalid Hash!') : '✗ Invalid Hash!';
      const provenLabel = window.i18n ? window.i18n.t('resolution_proven', 'Resolution Proven') : '✓ Resolution Proven';
      const badResolutionLabel = window.i18n ? window.i18n.t('hash_mismatch', 'Hash Mismatch!') : '✗ Hash Mismatch!';

      const dbStatus = data.database_consistent 
        ? `<span style="color: var(--success); font-weight:bold;">${matchingLabel}</span>` 
        : `<span style="color: var(--danger); font-weight:bold;">${mismatchLabel}</span>`;
      
      const chainStatus = data.verified 
        ? `<span style="color: var(--success); font-weight:bold;">${securedLabel}</span>` 
        : `<span style="color: var(--danger); font-weight:bold;">${invalidLabel}</span>`;

      let resolutionHTML = '';
      if (data.database_completion_hash) {
        const resolutionStatus = data.completion_verified 
          ? `<span style="color: var(--success); font-weight:bold;">${provenLabel}</span>` 
          : `<span style="color: var(--danger); font-weight:bold;">${badResolutionLabel}</span>`;
          
        resolutionHTML = `
          <div class="audit-row" style="margin-top: 10px; border-top: 1px dashed rgba(255, 255, 255, 0.1); padding-top: 10px;">
            <span data-i18n="onchain_resolution">On-Chain Resolution:</span>
            <span>${resolutionStatus}</span>
          </div>
          <div class="audit-row">
            <span data-i18n="resolution_hash">Resolution Proof Hash:</span>
            <span style="font-size:0.7rem;">${data.onchain_completion_hash || 'None'}</span>
          </div>
        `;
      }

      panel.innerHTML = `
        <div class="audit-row">
          <span data-i18n="db_integrity">Database Integrity:</span>
          <span>${dbStatus}</span>
        </div>
        <div class="audit-row">
          <span data-i18n="onchain_registry">On-Chain Registry:</span>
          <span>${chainStatus}</span>
        </div>
        <div class="audit-row">
          <span data-i18n="recomputed_hash">Recomputed Hash:</span>
          <span style="font-size:0.7rem;">${data.recomputed_hash}</span>
        </div>
        <div class="audit-row">
          <span data-i18n="onchain_hash">On-Chain Registered Hash:</span>
          <span style="font-size:0.7rem;">${data.onchain_hash || 'None'}</span>
        </div>
        ${resolutionHTML}
      `;
      
      if (window.i18n) window.i18n.translatePage();
    } else {
      panel.innerHTML = `<span style="color: var(--danger);">Failed to query verification nodes.</span>`;
    }
  } catch (err) {
    panel.innerHTML = `<span style="color: var(--danger);">Connection lost to local Ethereum nodes.</span>`;
  }
}

// Escape utilities
function escapeHtml(value) {
  if (!value) return '';
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

// Run Startup
window.addEventListener('load', initializeDashboard);
// Redraw translations on lang change
window.addEventListener('languageChanged', loadIssues);
