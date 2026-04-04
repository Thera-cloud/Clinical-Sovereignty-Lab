/* ── Storyboard module — daily panel viewer ── */

var Storyboard = (function () {
  var _container = null;

  function render(container) {
    _container = container;
    container.innerHTML = '<div class="centered"><div class="spinner"></div></div>';
    _load();
  }

  function _load() {
    var uid = (Auth.profile() || {}).hardware_id || (Auth.profile() || {}).id || '';
    fetch(Auth.apiBase() + '/api/sse-client/intake/status/' + encodeURIComponent(uid), {
      headers: Auth.headers()
    })
    .then(function (r) { return r.json(); })
    .then(function (status) {
      if (!status.completed) {
        _renderNotEnrolled();
        return;
      }
      return _fetchPanels();
    })
    .catch(function () { _renderError(); });
  }

  function _fetchPanels() {
    var uid = (Auth.profile() || {}).hardware_id || (Auth.profile() || {}).id || '';
    fetch(Auth.apiBase() + '/api/sse-client/storyboard/' + encodeURIComponent(uid), {
      headers: Auth.headers()
    })
    .then(function (r) {
      if (r.status === 404) { _renderComingSoon(); return; }
      return r.json().then(_renderPanels);
    })
    .catch(function () { _renderComingSoon(); });
  }

  function _renderPanels(data) {
    var panels = data.panels || [data];
    if (!panels.length) { _renderComingSoon(); return; }
    var html = '';
    panels.forEach(function (p) {
      html +=
        '<div class="panel-card">' +
          (p.r2_url ? '<img class="panel-image" src="' + _esc(p.r2_url) + '" alt="Panel" loading="lazy">' : '') +
          '<div class="panel-body">' +
            '<div class="panel-phase">' + _esc(p.phase_id || p.phase || 'Chapter') + '</div>' +
            '<div class="panel-title">' + _esc(p.title || p.scene_title || '') + '</div>' +
            '<div class="panel-text">' + _esc(p.narrative_text || p.scene_description || '') + '</div>' +
            (p.mission_prompt ? '<div class="panel-mission">' + _esc(p.mission_prompt) + '</div>' : '') +
            (p.mission_prompt ? '<button class="btn btn-cyan" onclick="Storyboard.completeMission(\'' + _esc(p.phase_id || '') + '\')">Complete Mission</button>' : '') +
          '</div>' +
        '</div>';
    });
    _container.innerHTML = '<div style="overflow-y:auto;height:100%">' + html + '</div>';
  }

  function _renderNotEnrolled() {
    _container.innerHTML =
      '<div class="vault-empty">' +
        '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>' +
        '<div style="font-family:var(--font-display);font-size:20px;color:var(--gold);margin-bottom:8px">Your Story Awaits</div>' +
        '<div style="color:var(--text-secondary);font-size:14px;margin-bottom:24px">Complete your intake with Little Nate to unlock your personalized journey.</div>' +
        '<button class="btn btn-cyan" style="width:auto" onclick="App.navigate(\'intake\')">Begin Intake</button>' +
      '</div>';
  }

  function _renderComingSoon() {
    _container.innerHTML =
      '<div class="vault-empty">' +
        '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>' +
        '<div style="font-family:var(--font-display);font-size:20px;color:var(--gold);margin-bottom:8px">Your first panel is coming</div>' +
        '<div style="color:var(--text-secondary);font-size:14px">Panels are delivered daily at sunrise. Check back tomorrow.</div>' +
      '</div>';
  }

  function _renderError() {
    _container.innerHTML =
      '<div class="vault-empty">' +
        '<div style="color:var(--text-secondary)">Unable to load your journey. Pull down to retry.</div>' +
        '<button class="btn btn-outline" style="width:auto;margin-top:16px" onclick="Storyboard.render(Storyboard._container)">Retry</button>' +
      '</div>';
  }

  function completeMission(phaseId) {
    App.toast('Mission logged — ' + phaseId);
  }

  function _esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  return { render: render, completeMission: completeMission, _container: null };
})();
