// Unified Auth Management for Civic System
(function () {
  let token = localStorage.getItem('token') || null;
  let currentUser = null;

  function getToken() {
    return token;
  }

  function getCurrentUser() {
    return currentUser;
  }

  // Check backend server health status and update UI
  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      const data = await res.json();
      
      const dbEl = document.getElementById('status-db');
      const chainEl = document.getElementById('status-blockchain');
      
      if (data.success) {
        if (dbEl) {
          dbEl.textContent = window.i18n ? window.i18n.t('active', 'Active') : 'Active';
          dbEl.style.color = 'var(--success)';
        }
        if (chainEl) {
          chainEl.textContent = data.blockchain === 'active' 
            ? (window.i18n ? window.i18n.t('active', 'Active') : 'Active') 
            : 'Mock Mode';
          chainEl.style.color = data.blockchain === 'active' ? 'var(--success)' : 'var(--warning)';
        }
      } else {
        if (dbEl) {
          dbEl.textContent = window.i18n ? window.i18n.t('inactive', 'Inactive') : 'Inactive';
          dbEl.style.color = 'var(--danger)';
        }
      }
    } catch (err) {
      console.error('Health check failed:', err);
    }
  }

  // Register account
  async function handleRegister(payload) {
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok && data.success) {
        return { success: true, message: data.message };
      }
      return { success: false, error: data.detail || 'Registration failed' };
    } catch (err) {
      return { success: false, error: 'Connection error during registration' };
    }
  }

  // Login
  async function handleLogin(username, password) {
    try {
      const res = await fetch('/api/auth/json-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (res.ok && data.access_token) {
        token = data.access_token;
        localStorage.setItem('token', token);
        return { success: true, role: data.role };
      }
      return { success: false, error: data.detail || 'Invalid username or password' };
    } catch (err) {
      return { success: false, error: 'Login server connection failed' };
    }
  }

  // Fetch logged in profile
  async function getProfile() {
    if (!token) return null;
    try {
      const res = await fetch('/api/auth/me', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        currentUser = await res.json();
        return currentUser;
      }
      logout();
      return null;
    } catch (err) {
      console.error('Failed to retrieve profile:', err);
      return null;
    }
  }

  // Logout
  function logout() {
    token = null;
    currentUser = null;
    localStorage.removeItem('token');
    window.location.href = '/';
  }

  // Route guarding mechanism
  async function checkAuthGuard(allowedRoles = []) {
    // Run health check in background
    checkHealth();

    if (!token) {
      // Not logged in: go to landing/auth page
      if (window.location.pathname !== '/' && !window.location.pathname.endsWith('index.html')) {
        window.location.href = '/';
      }
      return null;
    }

    const user = await getProfile();
    if (!user) {
      if (window.location.pathname !== '/' && !window.location.pathname.endsWith('index.html')) {
        window.location.href = '/';
      }
      return null;
    }

    // Role verification
    const currentPath = window.location.pathname;
    
    if (allowedRoles.length > 0 && !allowedRoles.includes(user.role)) {
      // User is logged in but doesn't belong on this dashboard page. Redirect.
      redirectByRole(user.role);
      return user;
    }

    // If we are on index.html and logged in, auto-redirect to correct dashboard
    if (currentPath === '/' || currentPath.endsWith('index.html')) {
      redirectByRole(user.role);
    }

    return user;
  }

  // Dynamic dashboard redirects
  function redirectByRole(role) {
    if (role === 'citizen') {
      window.location.href = '/citizen.html';
    } else if (role === 'ward_member') {
      window.location.href = '/ward.html';
    } else if (role === 'authority') {
      window.location.href = '/authority.html';
    } else if (role === 'admin') {
      window.location.href = '/admin.html';
    } else {
      window.location.href = '/';
    }
  }

  function isApproved() {
    return currentUser ? currentUser.is_approved !== false : false;
  }

  // Global exports
  window.auth = {
    getToken,
    getCurrentUser,
    handleRegister,
    handleLogin,
    logout,
    checkAuthGuard,
    redirectByRole,
    checkHealth,
    isApproved
  };
})();
