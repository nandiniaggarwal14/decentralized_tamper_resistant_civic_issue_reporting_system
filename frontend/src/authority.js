// Government Department Official Console Logic
let token = null;
let currentUser = null;
const queueContainer = document.getElementById('authority-issues-container');

// Auth Guard Check
async function initializeAuthority() {
  token = auth.getToken();
  currentUser = await auth.checkAuthGuard(['authority']);
  
  if (currentUser) {
    if (currentUser.is_approved === false) {
      document.getElementById('pending-overlay').style.display = 'flex';
      return;
    }
    // Populate profile card
    document.getElementById('profile-name').textContent = currentUser.full_name;
    const initials = currentUser.full_name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase();
    document.getElementById('profile-initials').textContent = initials.substring(0, 2);

    // Update title/role with department information
    if (currentUser.department_name) {
      document.getElementById('authority-subtitle').textContent = `Review, update status, and publish blockchain resolution proof for assigned ${currentUser.department_name} issues`;
      document.getElementById('profile-role').textContent = `${currentUser.department_name} Official`;
    }
    
    // Load Work Queue
    await loadAuthorityIssues();

    // Load Profile & Stats in background
    await loadProfile();
    await loadStats();
  }
}

// Tab Switching
function switchTab(tab) {
  // Hide all tab contents
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  // Deactivate all nav links
  document.querySelectorAll('.sidebar-nav .nav-link').forEach(el => el.classList.remove('active'));
  
  // Show target tab
  document.getElementById(`tab-${tab}`).style.display = 'block';
  // Activate target link
  document.getElementById(`tab-link-${tab}`).classList.add('active');
  
  // Trigger specific reloads
  if (tab === 'analytics') {
    loadStats();
  } else if (tab === 'profile') {
    loadProfile();
  } else if (tab === 'queue') {
    loadAuthorityIssues();
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
    setTimeout(() => { banner.style.display = 'none'; }, 6000);
  }
}

// Load authority complaints
async function loadAuthorityIssues() {
  try {
    const res = await fetch('/api/authority/issues', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      renderAuthorityIssues(data.data);
    } else {
      queueContainer.innerHTML = `<p style="text-align: center; color: var(--text-muted); padding: 40px;">Failed to load department queue.</p>`;
    }
  } catch (err) {
    console.error('Error loading authority issues:', err);
    queueContainer.innerHTML = `<p style="text-align: center; color: var(--text-muted); padding: 40px;">Connection failure.</p>`;
  }
}

// Render issues
function renderAuthorityIssues(issues) {
  if (!issues || issues.length === 0) {
    queueContainer.innerHTML = `
      <div style="text-align: center; color: var(--text-muted); padding: 60px;">
        <span style="font-size: 3rem; display: block; margin-bottom: 16px;"></span>
        <p data-i18n="no_auth_issues">No issues assigned to your department queue.</p>
      </div>
    `;
    if (window.i18n) window.i18n.translatePage();
    return;
  }

  queueContainer.innerHTML = issues.map(issue => {
    const statusText = window.i18n ? window.i18n.t(`badge-${issue.status}`, issue.status) : issue.status;
    const priorityText = window.i18n ? window.i18n.t(`badge-priority-${issue.priority}`, issue.priority) : issue.priority;
    const formattedDate = new Date(issue.created_at).toLocaleString();

    // Parse uploaded media
    const mediaHTML = (issue.media_urls || []).map(media => {
      if (media.type === 'image') {
        return `<img src="${media.url}" class="gallery-image" onclick="window.open('${media.url}')">`;
      } else if (media.type === 'audio') {
        return `<audio controls style="max-width: 100%; height: 32px; margin-top: 6px;"><source src="${media.url}"></audio>`;
      } else if (media.type === 'video') {
        return `<video controls style="max-width: 100%; max-height: 140px; border-radius: 6px; margin-top: 6px;"><source src="${media.url}"></video>`;
      }
      return '';
    }).join('');

    // Active action options
    let actionButtons = '';
    if (issue.status === 'pending') {
      actionButtons = `
        <button onclick="updateStatus('${issue.id}', 'in_progress')" class="btn btn-secondary" style="padding: 8px 16px;" data-i18n="mark_inprogress">Mark In Progress</button>
      `;
    } else if (issue.status === 'in_progress') {
      actionButtons = `
        <button onclick="openResolveDialog('${issue.id}')" class="btn btn-success" style="padding: 8px 16px;" data-i18n="resolve_issue">Resolve Issue</button>
      `;
    } else {
      actionButtons = `<span style="font-size:0.85rem; color: var(--text-muted);">Issue finalized. Integrity locked.</span>`;
    }

    return `
      <div class="issue-card ${issue.status}">
        <div class="issue-header">
          <div>
            <span class="badge badge-${issue.status}">${statusText}</span>
            <span class="badge badge-priority-${issue.priority}">${priorityText}</span>
          </div>
          <span style="font-size: 0.8rem; color: var(--text-muted);">${formattedDate}</span>
        </div>
        
        <h3 class="issue-title">${escapeHtml(issue.title)}</h3>
        <p class="issue-desc">${escapeHtml(issue.description)}</p>
        
        <div style="font-size: 0.85rem; margin: 12px 0; color: var(--text-secondary); display: flex; flex-direction: column; gap: 4px;">
          <div><strong>Location:</strong> ${escapeHtml(issue.address || 'GPS Coordinates Only')}</div>
          <div><strong>Ward:</strong> ${escapeHtml(issue.ward_name || 'Unassigned')}</div>
          <div><strong>Reporter:</strong> ${escapeHtml(issue.reporter_name)} (${escapeHtml(issue.contact || 'N/A')})</div>
          <div><strong>Upvotes:</strong> ${issue.votes ? issue.votes.upvotes : 0}</div>
        </div>

        <!-- Render captured files -->
        ${mediaHTML ? `<div class="media-gallery" style="margin-top: 12px; gap: 8px;">${mediaHTML}</div>` : ''}

        <div class="issue-footer" style="border-top: 1px solid var(--border); padding-top: 12px; margin-top: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap;">
          <div style="display: flex; gap: 8px;">
            ${actionButtons}
          </div>
        </div>
      </div>
    `;
  }).join('');

  if (window.i18n) window.i18n.translatePage();
}

// Update Status (for in_progress / rejected)
async function updateStatus(issueId, status) {
  try {
    const res = await fetch(`/api/authority/issues/${issueId}/status`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ status })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`Issue status updated to ${status.replace('_', ' ')}!`, false);
      await loadAuthorityIssues();
    } else {
      showAlert(data.detail || 'Failed to update status.', true);
    }
  } catch (err) {
    showAlert('Server connection error during status update.', true);
  }
}

// Open Resolution Dialog
function openResolveDialog(issueId) {
  document.getElementById('resolve-issue-id').value = issueId;
  document.getElementById('resolve-comments').value = '';
  document.getElementById('resolve-file').value = '';
  document.getElementById('resolve-dialog').showModal();
}

// Submit Resolution with Proof File
async function submitIssueResolution(event) {
  event.preventDefault();
  const dialog = document.getElementById('resolve-dialog');
  const issueId = document.getElementById('resolve-issue-id').value;
  const comments = document.getElementById('resolve-comments').value.trim();
  const fileInput = document.getElementById('resolve-file').files[0];

  if (!fileInput) {
    showAlert('Resolution proof file is required.', true);
    return;
  }

  const formData = new FormData();
  formData.append('comments', comments);
  formData.append('proof_file', fileInput);

  dialog.close();
  showAlert('Publishing proof of work to IPFS and anchoring on Ethereum Sepolia...');

  try {
    const res = await fetch(`/api/authority/issues/${issueId}/resolve`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert('Issue resolved successfully! Hash locked on-chain.', false);
      await loadAuthorityIssues();
    } else {
      showAlert(data.detail || 'Failed to publish resolution proof.', true);
    }
  } catch (err) {
    showAlert('Server connection failure during resolution.', true);
  }
}

// Load stats
async function loadStats() {
  try {
    const res = await fetch('/api/authority/stats', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const stats = data.data;
      document.getElementById('stats-total').textContent = stats.total_issues;
      document.getElementById('stats-rate').textContent = `${stats.resolution_rate}%`;
      document.getElementById('stats-speed').textContent = stats.avg_res_time_hours > 0 ? stats.avg_res_time_hours : '0.0';

      // Comparative: Ward distribution
      const distList = document.getElementById('stats-wards-distribution');
      const entries = Object.entries(stats.ward_distribution);
      if (entries.length === 0) {
        distList.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-secondary); text-align: center; padding: 16px;">No ward distribution statistics available.</p>`;
      } else {
        distList.innerHTML = entries.map(([ward, count]) => {
          const pct = stats.total_issues > 0 ? Math.round((count / stats.total_issues) * 100) : 0;
          return `
            <div>
              <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
                <span style="font-weight: 500;">${escapeHtml(ward)}</span>
                <span>${count} (${pct}%)</span>
              </div>
              <div style="background: rgba(255,255,255,0.05); height: 8px; border-radius: 99px; overflow: hidden;">
                <div style="background: var(--primary); width: ${pct}%; height: 100%; border-radius: 99px;"></div>
              </div>
            </div>
          `;
        }).join('');
      }
    }
  } catch (err) {
    console.error('Error fetching authority stats:', err);
  }
}

// Load Profile
async function loadProfile() {
  try {
    const res = await fetch('/api/authority/profile', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const p = data.data;
      document.getElementById('profile-username').value = p.username;
      document.getElementById('profile-fullname').value = p.full_name;
      document.getElementById('profile-contact').value = p.contact || '';
      document.getElementById('profile-designation').value = p.designation || 'Department Official';
      
      // Update Audit Cards
      document.getElementById('audit-jurisdiction').textContent = p.department_name;
      
      const ipfsLink = document.getElementById('audit-ipfs-link');
      if (p.ipfs_cid) {
        ipfsLink.textContent = p.ipfs_cid;
        ipfsLink.href = `https://gateway.pinata.cloud/ipfs/${p.ipfs_cid}`;
      } else {
        ipfsLink.textContent = 'None';
        ipfsLink.removeAttribute('href');
      }

      document.getElementById('audit-db-hash').textContent = p.blockchain_hash || 'None';
      document.getElementById('audit-chain-hash').textContent = p.onchain_hash || 'None';

      const badge = document.getElementById('audit-status-badge');
      if (p.is_verified) {
        badge.className = 'status-badge approved';
        badge.textContent = 'Verified (On-Chain)';
      } else if (p.blockchain_hash) {
        badge.className = 'status-badge rejected';
        badge.textContent = 'Verification Failed';
      } else {
        badge.className = 'status-badge pending';
        badge.textContent = 'Unanchored';
      }
    }
  } catch (err) {
    console.error('Error fetching authority profile:', err);
  }
}

// Update Profile Form action
async function updateProfile(event) {
  event.preventDefault();
  const saveBtn = document.getElementById('btn-save-profile');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Updating...';

  const payload = {
    full_name: document.getElementById('profile-fullname').value.trim(),
    contact: document.getElementById('profile-contact').value.trim(),
    designation: document.getElementById('profile-designation').value.trim()
  };

  try {
    const res = await fetch('/api/authority/profile', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    
    if (res.ok && data.success) {
      showAlert('Profile details successfully re-anchored on blockchain!', false);
      // Update UI elements
      document.getElementById('profile-name').textContent = payload.full_name;
      currentUser.full_name = payload.full_name;
      
      await loadProfile();
    } else {
      showAlert(data.detail || 'Failed to update profile.', true);
    }
  } catch (err) {
    showAlert('Server connection error during profile update.', true);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save Changes & Update IPFS';
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

// Startup
window.addEventListener('load', initializeAuthority);
window.addEventListener('languageChanged', loadAuthorityIssues);
window.switchTab = switchTab;
