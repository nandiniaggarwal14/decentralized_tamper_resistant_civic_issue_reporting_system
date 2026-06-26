// Ward Representative Console Logic
let token = null;
let currentUser = null;
let departments = [];
const issuesContainer = document.getElementById('ward-issues-container');

// Auth Guard Check
async function initializeWard() {
  token = auth.getToken();
  currentUser = await auth.checkAuthGuard(['ward_member']);
  
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

    // Update subtitle if ward info is available
    if (currentUser.ward_name) {
      document.getElementById('ward-subtitle').textContent = `Review complaints routed to ${currentUser.ward_name}`;
    }
    
    // Load Departments and Ward Queue
    await loadDepartments();
    await loadWardIssues();
    
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
    loadWardIssues();
  }
}

// Fetch departments list
async function loadDepartments() {
  try {
    const res = await fetch('/api/departments');
    const data = await res.json();
    if (res.ok && data.success) {
      departments = data.data;
    }
  } catch (err) {
    console.error('Failed to load departments list:', err);
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

// Load ward-assigned complaints
async function loadWardIssues() {
  try {
    const res = await fetch('/api/ward/issues', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      renderWardIssues(data.data);
    } else {
      issuesContainer.innerHTML = `<p style="text-align: center; color: var(--text-muted); padding: 40px;">Failed to load ward queue.</p>`;
    }
  } catch (err) {
    console.error('Error loading ward issues:', err);
    issuesContainer.innerHTML = `<p style="text-align: center; color: var(--text-muted); padding: 40px;">Connection failure.</p>`;
  }
}

// Render Ward Issues
function renderWardIssues(issues) {
  if (!issues || issues.length === 0) {
    issuesContainer.innerHTML = `
      <div style="text-align: center; color: var(--text-muted); padding: 60px;">
        <span style="font-size: 3rem; display: block; margin-bottom: 16px;"></span>
        <p data-i18n="no_ward_issues">No issues routed to your ward.</p>
      </div>
    `;
    if (window.i18n) window.i18n.translatePage();
    return;
  }

  issuesContainer.innerHTML = issues.map(issue => {
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

    // Generate redirect options
    const redirectOptions = departments.map(d => 
      `<option value="${d.id}" ${issue.department_id === d.id ? 'selected' : ''}>${d.name}</option>`
    ).join('');

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
          <div><strong>Address:</strong> ${escapeHtml(issue.address || 'GPS Coordinates Only')}</div>
          <div><strong>Category:</strong> ${escapeHtml(issue.category)}</div>
          <div><strong>Upvotes:</strong> ${issue.votes ? issue.votes.upvotes : 0}</div>
        </div>

        <!-- Render captured files -->
        ${mediaHTML ? `<div class="media-gallery" style="margin-top: 12px; gap: 8px;">${mediaHTML}</div>` : ''}

        <div class="issue-footer" style="border-top: 1px solid var(--border); padding-top: 12px; margin-top: 12px; display: flex; flex-direction: column; gap: 12px;">
          <!-- Actions panel -->
          <div style="display: flex; gap: 16px; align-items: center; justify-content: space-between; flex-wrap: wrap;">
            
            <div style="display: flex; align-items: center; gap: 8px;">
              <span data-i18n="redirect_dept">Redirect Department:</span>
              <select id="redirect-dept-${issue.id}" style="padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg-secondary); color: #fff;">
                ${redirectOptions}
              </select>
              <button onclick="redirectDept('${issue.id}')" class="btn" style="padding: 6px 12px; font-size: 0.8rem;" data-i18n="redirect">Redirect</button>
            </div>
            
          </div>
        </div>
      </div>
    `;
  }).join('');

  if (window.i18n) window.i18n.translatePage();
}

// Set Priority Level
async function setPriority(issueId, level) {
  try {
    const res = await fetch(`/api/ward/issues/${issueId}/priority`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ priority: level })
    });
    if (res.ok) {
      showAlert(`Priority updated to ${level}!`, false);
      await loadWardIssues();
    } else {
      showAlert('Failed to update priority level.', true);
    }
  } catch (err) {
    showAlert('Connection error during priority change.', true);
  }
}

// Redirect Department
async function redirectDept(issueId) {
  const select = document.getElementById(`redirect-dept-${issueId}`);
  const deptId = parseInt(select.value);

  try {
    const res = await fetch(`/api/ward/issues/${issueId}/redirect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ department_id: deptId })
    });
    if (res.ok) {
      showAlert('Issue redirected successfully!', false);
      await loadWardIssues();
    } else {
      showAlert('Failed to redirect issue.', true);
    }
  } catch (err) {
    showAlert('Connection error during department redirection.', true);
  }
}

// Load Ward Statistics
async function loadStats() {
  try {
    const res = await fetch('/api/ward/stats', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const stats = data.data;
      document.getElementById('stats-total').textContent = stats.total_issues;
      document.getElementById('stats-speed').textContent = stats.avg_res_time_hours > 0 ? stats.avg_res_time_hours : '0.0';

      // Status breakdown render
      const statusList = document.getElementById('stats-status-list');
      const statuses = ['pending', 'in_progress', 'resolved', 'rejected'];
      statusList.innerHTML = statuses.map(s => {
        const count = stats.status_breakdown[s] || 0;
        const pct = stats.total_issues > 0 ? Math.round((count / stats.total_issues) * 100) : 0;
        return `
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
              <span style="text-transform: capitalize;">${s.replace('_', ' ')}</span>
              <span>${count} (${pct}%)</span>
            </div>
            <div style="background: rgba(255,255,255,0.05); height: 8px; border-radius: 99px; overflow: hidden;">
              <div style="background: var(--primary); width: ${pct}%; height: 100%; border-radius: 99px;"></div>
            </div>
          </div>
        `;
      }).join('');

      // Priority distribution render
      const priorityList = document.getElementById('stats-priority-list');
      const priorities = ['low', 'medium', 'high', 'critical'];
      priorityList.innerHTML = priorities.map(p => {
        const count = stats.priority_breakdown[p] || 0;
        const pct = stats.total_issues > 0 ? Math.round((count / stats.total_issues) * 100) : 0;
        let color = 'var(--text-secondary)';
        if (p === 'high') color = 'var(--warning)';
        else if (p === 'critical') color = 'var(--danger)';
        else if (p === 'low') color = 'var(--success)';
        
        return `
          <div>
            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px;">
              <span style="text-transform: capitalize;">${p}</span>
              <span>${count} (${pct}%)</span>
            </div>
            <div style="background: rgba(255,255,255,0.05); height: 8px; border-radius: 99px; overflow: hidden;">
              <div style="background: ${color}; width: ${pct}%; height: 100%; border-radius: 99px;"></div>
            </div>
          </div>
        `;
      }).join('');

      // Categories distribution render
      const categoriesList = document.getElementById('stats-categories-list');
      const cats = Object.entries(stats.top_categories);
      if (cats.length === 0) {
        categoriesList.innerHTML = `<p style="font-size: 0.85rem; color: var(--text-secondary); text-align: center; padding: 16px;">No category statistics available.</p>`;
      } else {
        categoriesList.innerHTML = cats.map(([cat, count]) => {
          return `
            <div style="display: flex; justify-content: space-between; font-size: 0.85rem; padding: 8px 12px; background: rgba(255,255,255,0.02); border-radius: 6px; border: 1px solid var(--border);">
              <span style="font-weight: 500;">${escapeHtml(cat)}</span>
              <span style="color: var(--primary); font-weight: 700;">${count}</span>
            </div>
          `;
        }).join('');
      }
    }
  } catch (err) {
    console.error('Error fetching ward stats:', err);
  }
}

// Load Ward Profile
async function loadProfile() {
  try {
    const res = await fetch('/api/ward/profile', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const p = data.data;
      document.getElementById('profile-username').value = p.username;
      document.getElementById('profile-fullname').value = p.full_name;
      document.getElementById('profile-contact').value = p.contact || '';
      
      // Update Audit Cards
      document.getElementById('audit-jurisdiction').textContent = p.ward_name;
      
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
    console.error('Error fetching ward profile:', err);
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
    contact: document.getElementById('profile-contact').value.trim()
  };

  try {
    const res = await fetch('/api/ward/profile', {
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
window.addEventListener('load', initializeWard);
window.addEventListener('languageChanged', loadWardIssues);
window.auth_tabs = { switchTab }; // export tab switching globally
window.switchTab = switchTab;
