/* ── Vault module — Sovereign Journey vault browser ── */

var Vault = (function () {
  var _container = null;

  function render(container) {
    _container = container;
    container.innerHTML = '<div class="centered"><div class="spinner"></div></div>';
    _load();
  }

  function _load() {
    var uid = (Auth.profile() || {}).hardware_id || (Auth.profile() || {}).id || '';
    fetch(Auth.apiBase() + '/api/sse-client/vault/' + encodeURIComponent(uid), {
      headers: Auth.headers()
    })
    .then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    })
    .then(function (data) {
      var items = data.items || data || [];
      if (!items.length) { _renderEmpty(); return; }
      _renderGrid(items);
    })
    .catch(function () { _renderEmpty(); });
  }

  function _renderGrid(items) {
    var html = '<div class="vault-grid">';
    items.forEach(function (item) {
      var thumb = item.r2_url || item.thumbnail_url || item.url || '';
      var label = item.title || item.phase_id || item.type || 'Panel';
      var date = item.delivered_at || item.created_at || '';
      if (date) {
        try { label += ' · ' + new Date(date).toLocaleDateString(); } catch (e) { /* */ }
      }
      html +=
        '<div class="vault-item" onclick="Vault.open(\'' + _esc(thumb) + '\')">' +
          (thumb
            ? '<img class="vault-thumb" src="' + _esc(thumb) + '" alt="" loading="lazy">'
            : '<div class="vault-thumb" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted)">📄</div>') +
          '<div class="vault-label">' + _esc(label) + '</div>' +
        '</div>';
    });
    html += '</div>';
    _container.innerHTML = '<div style="overflow-y:auto;height:100%">' + html + '</div>';
  }

  function _renderEmpty() {
    _container.innerHTML =
      '<div class="vault-empty">' +
        '<svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>' +
        '<div style="font-family:var(--font-display);font-size:20px;color:var(--gold);margin-bottom:8px">Your Vault is Empty</div>' +
        '<div style="color:var(--text-secondary);font-size:14px">Completed story panels and artifacts will appear here as your journey unfolds.</div>' +
      '</div>';
  }

  function open(url) {
    if (!url) return;
    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:200;display:flex;align-items:center;justify-content:center;padding:16px;cursor:pointer';
    overlay.innerHTML = '<img src="' + _esc(url) + '" style="max-width:100%;max-height:100%;border-radius:8px;object-fit:contain">';
    overlay.addEventListener('click', function () { overlay.remove(); });
    document.body.appendChild(overlay);
  }

  function _esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  return { render: render, open: open };
})();
