// Admin Dashboard Business Logic
let token = null;
let currentUser = null;
let allUsersCache = [];

// ============================================================
// INIT
// ============================================================
async function initializeAdmin() {
  token = auth.getToken();
  currentUser = await auth.checkAuthGuard(['admin']);

  if (currentUser) {
    document.getElementById('profile-name').textContent = currentUser.full_name;
    document.getElementById('profile-initials').textContent = 'AD';
    await refreshDashboard();
  }
}

// ============================================================
// TAB SWITCHING
// ============================================================
function switchTab(tabId) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  document.getElementById('tab-btn-' + tabId.replace('tab-', '')).classList.add('active');

  // Lazy-load tab content
  if (tabId === 'tab-wards') loadAdminWards();
  if (tabId === 'tab-departments') loadAdminDepartments();
  if (tabId === 'tab-users') loadAllUsers();
  if (tabId === 'tab-approvals') loadPendingUsers();
  if (tabId === 'tab-blockchain') loadFailedTransactions();
}

// ============================================================
// ALERT BANNER
// ============================================================
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

// ============================================================
// REFRESH ALL
// ============================================================
async function refreshDashboard() {
  await Promise.all([
    loadStats(),
    loadPendingUsers(),
    loadFailedTransactions(),
    loadAdminWards(),
    loadAdminDepartments(),
    loadAllUsers(),
  ]);
}

// ============================================================
// STATS
// ============================================================
async function loadStats() {
  try {
    const res = await fetch('/api/admin/stats', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      const s = data.data;
      document.getElementById('stat-total-users').textContent = s.total_users;
      document.getElementById('stat-total-issues').textContent = s.total_issues;
      document.getElementById('stat-pending-approvals').textContent = s.pending_approvals;
      document.getElementById('stat-resolved-issues').textContent = s.resolved_issues;
      document.getElementById('stat-failed-txns').textContent = s.failed_txns;
    }
  } catch (err) {
    console.error('Failed to load stats:', err);
  }
}

// ============================================================
// ==================== WARDS MANAGEMENT ====================
// ============================================================
async function loadAdminWards() {
  const tbody = document.getElementById('wards-tbody');
  if (!tbody) return;
  try {
    const res = await fetch('/api/admin/wards', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.detail || 'Failed');

    const wards = data.data;
    // Populate dropdown for assignment
    const wardSel = document.getElementById('assign-ward-select');
    if (wardSel) {
      wardSel.innerHTML = '<option value="">— select ward —</option>' +
        wards.map(w => `<option value="${w.id}">${escapeHtml(w.name)}</option>`).join('');
    }

    if (wards.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:32px;">No wards found. Create one above.</td></tr>`;
      return;
    }

    tbody.innerHTML = wards.map(w => `
      <tr>
        <td style="font-family:monospace;font-size:0.85rem;">${w.id}</td>
        <td style="font-weight:600;">${escapeHtml(w.name)}</td>
        <td style="font-family:monospace;font-size:0.8rem;">${Number(w.center_latitude).toFixed(4)}, ${Number(w.center_longitude).toFixed(4)}</td>
        <td>${Number(w.radius_meters).toLocaleString()} m</td>
        <td>
          ${w.member_username
            ? `<span style="font-weight:600;">${escapeHtml(w.member_name || w.member_username)}</span>
               <span style="font-size:0.75rem;color:var(--text-secondary);display:block;">@${escapeHtml(w.member_username)}</span>`
            : `<span style="color:var(--text-secondary);font-size:0.85rem;">— unassigned —</span>`}
        </td>
        <td>
          <button class="btn-icon danger" onclick="deleteWard(${w.id}, '${escapeHtml(w.name)}')">🗑 Delete</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:16px;">Failed to load wards: ${err.message}</td></tr>`;
  }

  // Also populate ward-member users for the assignment dropdown
  populateUserDropdown('assign-ward-user-select', 'ward_member');
}

async function createWard() {
  const name = document.getElementById('ward-name').value.trim();
  const lat  = parseFloat(document.getElementById('ward-lat').value);
  const lng  = parseFloat(document.getElementById('ward-lng').value);
  const rad  = parseFloat(document.getElementById('ward-radius').value);

  if (!name || isNaN(lat) || isNaN(lng)) {
    showAlert('Please fill in Ward Name, Latitude, and Longitude.', true);
    return;
  }

  try {
    const res = await fetch('/api/admin/wards', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, center_latitude: lat, center_longitude: lng, radius_meters: rad || 5000 })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`Ward "${name}" created successfully (ID ${data.ward_id}).`);
      document.getElementById('ward-name').value = '';
      document.getElementById('ward-lat').value = '';
      document.getElementById('ward-lng').value = '';
      document.getElementById('ward-radius').value = '5000';
      await loadAdminWards();
    } else {
      showAlert(data.detail || 'Failed to create ward.', true);
    }
  } catch (err) {
    showAlert('Server connection error while creating ward.', true);
  }
}

async function deleteWard(wardId, wardName) {
  if (!confirm(`Delete ward "${wardName}"? This will also remove any ward-member assignment.`)) return;
  try {
    const res = await fetch(`/api/admin/wards/${wardId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`Ward "${wardName}" deleted.`);
      await loadAdminWards();
    } else {
      showAlert(data.detail || 'Failed to delete ward.', true);
    }
  } catch (err) {
    showAlert('Server error while deleting ward.', true);
  }
}

async function assignWardMember() {
  const wardId  = document.getElementById('assign-ward-select').value;
  const userId  = document.getElementById('assign-ward-user-select').value;
  if (!wardId || !userId) {
    showAlert('Please select both a ward and a ward-member user.', true);
    return;
  }
  try {
    const res = await fetch(`/api/admin/wards/${wardId}/assign-member`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert('Ward member assigned successfully!');
      await loadAdminWards();
    } else {
      showAlert(data.detail || 'Failed to assign ward member.', true);
    }
  } catch (err) {
    showAlert('Server error during ward member assignment.', true);
  }
}

async function unassignWardMember() {
  const wardId = document.getElementById('assign-ward-select').value;
  if (!wardId) { showAlert('Please select a ward first.', true); return; }
  if (!confirm('Remove the current ward member assignment from this ward?')) return;
  try {
    const res = await fetch(`/api/admin/wards/${wardId}/unassign-member`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert('Ward member unassigned.');
      await loadAdminWards();
    } else {
      showAlert(data.detail || 'Failed to unassign ward member.', true);
    }
  } catch (err) {
    showAlert('Server error during unassignment.', true);
  }
}

// ============================================================
// ============= DEPARTMENTS MANAGEMENT ====================
// ============================================================
async function loadAdminDepartments() {
  const tbody = document.getElementById('departments-tbody');
  if (!tbody) return;
  try {
    const res = await fetch('/api/admin/departments', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.detail || 'Failed');

    const depts = data.data;
    // Populate dropdown
    const deptSel = document.getElementById('assign-dept-select');
    if (deptSel) {
      deptSel.innerHTML = '<option value="">— select department —</option>' +
        depts.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('');
    }

    if (depts.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);padding:32px;">No departments found. Create one above.</td></tr>`;
      return;
    }

    tbody.innerHTML = depts.map(d => `
      <tr>
        <td style="font-family:monospace;font-size:0.85rem;">${d.id}</td>
        <td style="font-weight:600;">${escapeHtml(d.name)}</td>
        <td style="font-size:0.85rem;color:var(--text-secondary);">${escapeHtml(d.description || '—')}</td>
        <td>
          ${d.authorities.length === 0
            ? `<span style="color:var(--text-secondary);font-size:0.85rem;">— unassigned —</span>`
            : d.authorities.map(a => `
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                  <span style="font-weight:600;">${escapeHtml(a.full_name || a.username)}</span>
                  <span style="font-size:0.75rem;color:var(--text-secondary);">(${escapeHtml(a.designation)})</span>
                  <button class="btn-icon danger" style="font-size:0.7rem;padding:2px 6px;"
                    onclick="removeAuthority(${d.id}, '${a.user_id}', '${escapeHtml(a.username)}')">✕</button>
                </div>
              `).join('')}
        </td>
        <td>
          <button class="btn-icon danger" onclick="deleteDepartment(${d.id}, '${escapeHtml(d.name)}')">🗑 Delete</button>
        </td>
      </tr>
    `).join('');
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--danger);padding:16px;">Failed to load departments: ${err.message}</td></tr>`;
  }

  // Populate authority users for the assignment dropdown
  populateUserDropdown('assign-dept-user-select', 'authority');
}

async function createDepartment() {
  const name = document.getElementById('dept-name').value.trim();
  const desc = document.getElementById('dept-desc').value.trim();
  if (!name) { showAlert('Department name is required.', true); return; }
  try {
    const res = await fetch('/api/admin/departments', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: desc || null })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`Department "${name}" created (ID ${data.department_id}).`);
      document.getElementById('dept-name').value = '';
      document.getElementById('dept-desc').value = '';
      await loadAdminDepartments();
    } else {
      showAlert(data.detail || 'Failed to create department.', true);
    }
  } catch (err) {
    showAlert('Server error while creating department.', true);
  }
}

async function deleteDepartment(deptId, deptName) {
  if (!confirm(`Delete department "${deptName}"? All authority assignments in this department will also be removed.`)) return;
  try {
    const res = await fetch(`/api/admin/departments/${deptId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`Department "${deptName}" deleted.`);
      await loadAdminDepartments();
    } else {
      showAlert(data.detail || 'Failed to delete department.', true);
    }
  } catch (err) {
    showAlert('Server error while deleting department.', true);
  }
}

async function assignAuthorityToDept() {
  const deptId      = document.getElementById('assign-dept-select').value;
  const userId      = document.getElementById('assign-dept-user-select').value;
  const designation = document.getElementById('assign-designation').value.trim() || 'Department Official';
  if (!deptId || !userId) {
    showAlert('Please select both a department and an authority user.', true);
    return;
  }
  try {
    const res = await fetch(`/api/admin/departments/${deptId}/assign-authority`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, designation })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert('Authority assigned to department successfully!');
      await loadAdminDepartments();
    } else {
      showAlert(data.detail || 'Failed to assign authority.', true);
    }
  } catch (err) {
    showAlert('Server error during authority assignment.', true);
  }
}

async function removeAuthority(deptId, userId, username) {
  if (!confirm(`Remove authority "@${username}" from this department?`)) return;
  try {
    const res = await fetch(`/api/admin/departments/${deptId}/remove-authority/${userId}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`Authority @${username} removed from department.`);
      await loadAdminDepartments();
    } else {
      showAlert(data.detail || 'Failed to remove authority.', true);
    }
  } catch (err) {
    showAlert('Server error while removing authority.', true);
  }
}

// ============================================================
// ==================== ALL USERS VIEW ====================
// ============================================================
async function loadAllUsers() {
  const tbody = document.getElementById('users-tbody');
  if (!tbody) return;
  try {
    const res = await fetch('/api/admin/users', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.detail || 'Failed');
    allUsersCache = data.data;
    renderUsersTable(allUsersCache);
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:16px;">Failed to load users: ${err.message}</td></tr>`;
  }
}

function renderUsersTable(users) {
  const tbody = document.getElementById('users-tbody');
  if (!tbody) return;
  if (users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:32px;">No users match the filter.</td></tr>`;
    return;
  }
  tbody.innerHTML = users.map(u => {
    let assignedTo = '—';
    if (u.ward_name) assignedTo = `🗺 ${escapeHtml(u.ward_name)}`;
    else if (u.department_name) assignedTo = `🏢 ${escapeHtml(u.department_name)}`;
    const roleClass = u.role.replace(' ', '_');
    const joinDate = u.created_at ? new Date(u.created_at).toLocaleDateString() : '—';
    return `
      <tr>
        <td style="font-family:monospace;font-weight:600;">@${escapeHtml(u.username)}</td>
        <td>${escapeHtml(u.full_name || '—')}</td>
        <td><span class="role-badge ${roleClass}">${u.role.replace('_', ' ')}</span></td>
        <td style="font-size:0.85rem;">${assignedTo}</td>
        <td>
          ${u.is_approved
            ? `<span class="status-badge approved" style="font-size:0.75rem;">✓ Yes</span>`
            : `<span class="status-badge pending" style="font-size:0.75rem;">⏳ No</span>`}
        </td>
        <td style="font-size:0.8rem;color:var(--text-secondary);">${joinDate}</td>
      </tr>
    `;
  }).join('');
}

function filterUsers() {
  const search = document.getElementById('user-search').value.toLowerCase();
  const role   = document.getElementById('user-role-filter').value;
  const filtered = allUsersCache.filter(u => {
    const matchRole   = !role || u.role === role;
    const matchSearch = !search ||
      (u.username || '').toLowerCase().includes(search) ||
      (u.full_name || '').toLowerCase().includes(search);
    return matchRole && matchSearch;
  });
  renderUsersTable(filtered);
}

// ============================================================
// HELPER: populate a <select> with users of a specific role
// ============================================================
async function populateUserDropdown(selectId, role) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  try {
    // Use cached users if available, otherwise fetch
    let users = allUsersCache.length ? allUsersCache : [];
    if (!users.length) {
      const res = await fetch('/api/admin/users', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.success) { users = data.data; allUsersCache = users; }
    }
    const filtered = users.filter(u => u.role === role);
    sel.innerHTML = `<option value="">— select user —</option>` +
      filtered.map(u => `<option value="${u.id}">@${escapeHtml(u.username)}${u.full_name ? ' – ' + escapeHtml(u.full_name) : ''}</option>`).join('');
  } catch (err) {
    sel.innerHTML = `<option value="">Error loading users</option>`;
  }
}

// ============================================================
// PENDING APPROVALS
// ============================================================
async function loadPendingUsers() {
  const tbody = document.getElementById('approvals-tbody');
  if (!tbody) return;
  try {
    const res = await fetch('/api/admin/pending-users', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();

    if (res.ok && data.success) {
      const users = data.data;
      if (users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:32px;">No users pending administrator approval.</td></tr>`;
        return;
      }
      tbody.innerHTML = users.map(user => {
        let details = '—';
        if (user.role === 'ward_member') details = `Ward ID: ${user.ward_id || 'N/A'}`;
        else if (user.role === 'authority') details = `Dept ID: ${user.department_id || 'N/A'}`;
        return `
          <tr>
            <td style="font-weight:600;">${escapeHtml(user.full_name)}</td>
            <td>@${escapeHtml(user.username)}</td>
            <td style="text-transform:capitalize;">${escapeHtml(user.role.replace('_', ' '))}</td>
            <td>${escapeHtml(details)}</td>
            <td><span class="status-badge pending">Pending</span></td>
            <td>
              <div style="display:flex;gap:8px;">
                <button onclick="approveUser('${user.id}','${escapeHtml(user.full_name)}')" class="btn btn-success" style="padding:5px 10px;font-size:0.8rem;">Approve</button>
                <button onclick="rejectUser('${user.id}','${escapeHtml(user.full_name)}')"  class="btn btn-danger"  style="padding:5px 10px;font-size:0.8rem;">Reject</button>
              </div>
            </td>
          </tr>
        `;
      }).join('');
    } else {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:16px;">Failed: ${data.detail || 'Access denied'}</td></tr>`;
    }
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:16px;">Server connection failure.</td></tr>`;
  }
}

async function approveUser(userId, name) {
  try {
    const res = await fetch(`/api/admin/approve-user/${userId}`, {
      method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`User "${name}" approved!`);
      await Promise.all([loadPendingUsers(), loadStats()]);
    } else {
      showAlert(data.detail || 'Failed to approve user.', true);
    }
  } catch (err) {
    showAlert('Server connection error during user approval.', true);
  }
}

async function rejectUser(userId, name) {
  if (!confirm(`Reject and remove "${name}" from the system?`)) return;
  try {
    const res = await fetch(`/api/admin/reject-user/${userId}`, {
      method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(`Registration for "${name}" has been rejected.`);
      await Promise.all([loadPendingUsers(), loadStats()]);
    } else {
      showAlert(data.detail || 'Failed to reject user.', true);
    }
  } catch (err) {
    showAlert('Server connection error during user rejection.', true);
  }
}

// ============================================================
// FAILED BLOCKCHAIN TRANSACTIONS
// ============================================================
async function loadFailedTransactions() {
  const tbody = document.getElementById('transactions-tbody');
  if (!tbody) return;
  try {
    const res = await fetch('/api/admin/failed-transactions', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();

    if (res.ok && data.success) {
      const txns = data.data;
      if (txns.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:32px;">No failed blockchain transactions. All entries synced!</td></tr>`;
        return;
      }
      tbody.innerHTML = txns.map(tx => {
        const dateStr = tx.created_at ? new Date(tx.created_at).toLocaleString() : 'N/A';
        return `
          <tr style="${tx.resolved_at ? 'opacity:0.5;' : ''}">
            <td style="font-family:monospace;font-size:0.8rem;">TX-${tx.id}</td>
            <td style="font-weight:600;color:var(--primary);font-family:monospace;">${escapeHtml(tx.function_name)}</td>
            <td style="max-width:250px;font-family:monospace;font-size:0.75rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(tx.args_json)}">${escapeHtml(tx.args_json)}</td>
            <td style="text-align:center;">${tx.retry_count}</td>
            <td style="max-width:200px;color:var(--danger);font-size:0.8rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(tx.error_message)}">${escapeHtml(tx.error_message || 'Unknown error')}</td>
            <td style="font-size:0.8rem;color:var(--text-muted);">${dateStr}</td>
          </tr>
        `;
      }).join('');
    } else {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:16px;">Failed: ${data.detail || 'Access denied'}</td></tr>`;
    }
  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--danger);padding:16px;">Server connection failure.</td></tr>`;
  }
}

async function retryFailedTransactions() {
  const btn = document.getElementById('btn-retry-all');
  btn.disabled = true;
  btn.textContent = 'Processing retries...';
  try {
    const res = await fetch('/api/admin/retry-blockchain', {
      method: 'POST', headers: { 'Authorization': `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok && data.success) {
      showAlert(data.message || 'Blockchain ledger sync retries completed.');
      await loadFailedTransactions();
    } else {
      showAlert(data.detail || 'Failed to trigger blockchain retries.', true);
    }
  } catch (err) {
    showAlert('Connection error while retrying failed transactions.', true);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Retry All Transactions';
  }
}

// ============================================================
// UTILITIES
// ============================================================
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
window.addEventListener('load', initializeAdmin);
window.addEventListener('languageChanged', refreshDashboard);
