/* ── App module — SPA router, page lifecycle ── */

var App = (function () {
  var _currentRoute = null;
  var _routes = {
    login:      { title: 'Sign In',             nav: false,  auth: false },
    chat:       { title: 'Little Nate',          nav: true,   auth: true  },
    storyboard: { title: 'Your Journey',         nav: true,   auth: true  },
    intake:     { title: 'Identity Forge',       nav: false,  auth: true  },
    vault:      { title: 'Vault',                nav: true,   auth: true  },
    profile:    { title: 'Profile',              nav: true,   auth: true  },
    register:   { title: 'Create Account',       nav: false,  auth: false }
  };

  function init() {
    Auth.restore();
    window.addEventListener('hashchange', _onHash);
    _onHash();
    _registerSW();
  }

  function navigate(route) {
    window.location.hash = '#/' + route;
  }

  function _onHash() {
    var hash = (window.location.hash || '#/login').replace('#/', '');
    if (!hash) hash = 'login';
    var cfg = _routes[hash];
    if (!cfg) { hash = 'chat'; cfg = _routes.chat; }

    if (cfg.auth && !Auth.isLoggedIn()) {
      navigate('login');
      return;
    }
    if (hash === 'login' && Auth.isLoggedIn()) {
      navigate('chat');
      return;
    }

    _teardown(_currentRoute);
    _currentRoute = hash;
    _render(hash, cfg);
  }

  function _render(route, cfg) {
    var container = document.getElementById('app');
    var topTitle = document.getElementById('topbar-title');
    var topBack = document.getElementById('topbar-back');
    var bottomNav = document.getElementById('bottomnav');

    topTitle.textContent = cfg.title;
    topBack.style.display = cfg.nav ? 'none' : 'flex';
    bottomNav.style.display = cfg.nav || route === 'intake' ? '' : 'none';

    document.querySelectorAll('.nav-item').forEach(function (el) {
      el.classList.toggle('active', el.dataset.route === route);
    });

    container.innerHTML = '';

    switch (route) {
      case 'login':
        Auth.renderLogin(container);
        break;
      case 'chat':
        Chat.render(container);
        break;
      case 'storyboard':
        Storyboard.render(container);
        break;
      case 'intake':
        Intake.render(container);
        break;
      case 'vault':
        Vault.render(container);
        break;
      case 'profile':
        Auth.renderProfile(container);
        break;
      case 'register':
        _renderRegister(container);
        break;
    }
  }

  function _teardown(prev) {
    if (prev === 'chat') Chat.destroy();
  }

  function _renderRegister(container) {
    container.innerHTML =
      '<div class="auth-page">' +
        '<div class="auth-logo">N</div>' +
        '<div class="auth-title">Join the Sanctuary</div>' +
        '<div class="auth-subtitle">Begin your healing journey with Little Nate</div>' +
        '<div style="display:flex;flex-direction:column;gap:12px;width:100%;max-width:340px">' +
          '<a class="btn btn-gold" href="https://sovereignsanctuary.net/register" target="_blank">Create Account</a>' +
          '<button class="btn btn-outline" onclick="App.navigate(\'login\')">Already have an account? Sign in</button>' +
        '</div>' +
      '</div>';
  }

  function _registerSW() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/service-worker.js').catch(function () { /* optional */ });
    }
  }

  function toast(msg) {
    var el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 2800);
  }

  return { init: init, navigate: navigate, toast: toast };
})();

document.addEventListener('DOMContentLoaded', App.init);
