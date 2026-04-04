/* ── Auth module — login, token, session ── */
/* global App */

var Auth = (function () {
  var _token = null;
  var _profile = null;
  var _wsUrl = 'wss://api.sovereignsanctuary.net/ws';
  var _apiBase = 'https://api.sovereignsanctuary.net';

  function token() { return _token; }
  function profile() { return _profile; }
  function isLoggedIn() { return !!_token && !!_profile; }
  function headers(contentType) {
    var h = {};
    if (_token) h['Authorization'] = 'Bearer ' + _token;
    if (contentType) h['Content-Type'] = contentType;
    return h;
  }
  function apiBase() { return _apiBase; }
  function wsUrl() { return _wsUrl; }

  function login(username, password, expectedRole) {
    return new Promise(function (resolve, reject) {
      try {
        var ws = new WebSocket(_wsUrl);
        var timer = setTimeout(function () { ws.close(); reject(new Error('Timeout')); }, 15000);
        ws.onopen = function () {
          ws.send(JSON.stringify({
            type: 'login_request',
            username: username,
            password: password,
            expected_role: expectedRole || 'CLIENT'
          }));
        };
        ws.onmessage = function (ev) {
          try {
            var d = JSON.parse(ev.data);
            if (d.type === 'login_success') {
              clearTimeout(timer);
              _token = d.token || '';
              _profile = d.profile || d;
              _profile.token = _token;
              _profile.username = username;
              ws.close();
              resolve(_profile);
            } else if (d.type === 'error' || d.type === 'login_failed') {
              clearTimeout(timer);
              ws.close();
              reject(new Error(d.message || 'Login failed'));
            }
          } catch (e) { /* ignore non-JSON frames */ }
        };
        ws.onerror = function () { clearTimeout(timer); reject(new Error('Connection error')); };
      } catch (e) { reject(e); }
    });
  }

  function logout() {
    _token = null;
    _profile = null;
    if (typeof App !== 'undefined') App.navigate('login');
  }

  function restore() {
    try {
      var s = sessionStorage.getItem('ss_session');
      if (s) {
        var d = JSON.parse(s);
        _token = d.token;
        _profile = d.profile;
        return true;
      }
    } catch (e) { /* ignore */ }
    return false;
  }

  function persist() {
    try {
      sessionStorage.setItem('ss_session', JSON.stringify({ token: _token, profile: _profile }));
    } catch (e) { /* ignore — Safari private mode */ }
  }

  function renderLogin(container) {
    container.innerHTML =
      '<div class="auth-page">' +
        '<div class="auth-logo">N</div>' +
        '<div class="auth-title">Sovereign Sanctuary</div>' +
        '<div class="auth-subtitle">Sign in to continue</div>' +
        '<form class="auth-form" id="login-form">' +
          '<div class="form-group">' +
            '<label class="form-label">Username</label>' +
            '<input class="form-input" id="login-user" type="text" autocomplete="username" autocapitalize="none" required>' +
          '</div>' +
          '<div class="form-group">' +
            '<label class="form-label">Password</label>' +
            '<input class="form-input" id="login-pass" type="password" autocomplete="current-password" required>' +
          '</div>' +
          '<div id="login-error" style="color:var(--red);font-size:13px;margin-bottom:12px;display:none"></div>' +
          '<button class="btn btn-cyan" type="submit" id="login-btn">Enter the Sanctuary</button>' +
        '</form>' +
        '<div class="auth-footer">New here? <a href="#/register">Create an account</a></div>' +
      '</div>';

    document.getElementById('login-form').onsubmit = function (e) {
      e.preventDefault();
      var btn = document.getElementById('login-btn');
      var errEl = document.getElementById('login-error');
      var user = document.getElementById('login-user').value.trim();
      var pass = document.getElementById('login-pass').value;
      if (!user || !pass) return;
      btn.disabled = true; btn.textContent = 'Connecting...';
      errEl.style.display = 'none';
      login(user, pass).then(function () {
        persist();
        App.navigate('chat');
      }).catch(function (err) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Enter the Sanctuary';
      });
    };
  }

  function renderProfile(container) {
    var p = _profile || {};
    var name = p.name || p.username || 'User';
    var tier = p.subscription_plan || p.tier || 'TRIAL';
    container.innerHTML =
      '<div class="profile-section">' +
        '<div class="profile-card">' +
          '<div class="profile-name">' + _esc(name) + '</div>' +
          '<div class="profile-tier">' + _esc(tier) + '</div>' +
        '</div>' +
        '<div class="profile-card">' +
          '<div class="profile-row"><span>Account</span><span>' + _esc(p.username || '') + '</span></div>' +
          '<div class="profile-row"><span>Email</span><span>' + _esc(p.email || '—') + '</span></div>' +
          '<div class="profile-row"><span>Coach</span><span>' + _esc(p.assigned_coach || '—') + '</span></div>' +
        '</div>' +
        '<button class="btn btn-outline" onclick="Auth.logout()" style="margin-top:12px">Sign Out</button>' +
      '</div>';
  }

  function _esc(s) {
    var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML;
  }

  return {
    token: token, profile: profile, isLoggedIn: isLoggedIn, headers: headers,
    apiBase: apiBase, wsUrl: wsUrl, login: login, logout: logout,
    restore: restore, persist: persist,
    renderLogin: renderLogin, renderProfile: renderProfile
  };
})();
