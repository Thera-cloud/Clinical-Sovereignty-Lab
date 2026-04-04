/* ── Intake module — Identity Forge 10-turn conversation ── */

var Intake = (function () {
  var _container = null;
  var _turn = 0;
  var _history = [];
  var _sending = false;

  function render(container) {
    _container = container;
    _turn = 0;
    _history = [];
    _sending = false;

    container.innerHTML =
      '<div class="page active" style="display:flex;flex-direction:column;height:100%">' +
        '<div class="intake-progress">' +
          '<div>Getting to know you — <span id="intake-turn">0</span>/10</div>' +
          '<div class="intake-bar" style="margin-top:6px"><div class="intake-bar-fill" id="intake-bar" style="width:0%"></div></div>' +
        '</div>' +
        '<div class="chat-messages" id="intake-msgs"></div>' +
        '<div class="chat-input-bar">' +
          '<textarea class="chat-input" id="intake-input" rows="1" placeholder="Your response..." maxlength="2000"></textarea>' +
          '<button class="chat-send" id="intake-send" disabled>' +
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>' +
          '</button>' +
        '</div>' +
      '</div>';

    var inputEl = document.getElementById('intake-input');
    var sendBtn = document.getElementById('intake-send');

    inputEl.addEventListener('input', function () {
      sendBtn.disabled = !inputEl.value.trim() || _sending;
    });
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _send(); }
    });
    sendBtn.addEventListener('click', _send);

    _firstTurn();
  }

  function _firstTurn() {
    _showTyping();
    _callApi('', 1);
  }

  function _send() {
    var inputEl = document.getElementById('intake-input');
    var text = (inputEl.value || '').trim();
    if (!text || _sending) return;
    inputEl.value = '';
    _addBubble('user', text);
    _showTyping();
    _turn++;
    _callApi(text, _turn);
  }

  function _callApi(userMsg, turnNum) {
    _sending = true;
    document.getElementById('intake-send').disabled = true;
    var uid = (Auth.profile() || {}).hardware_id || (Auth.profile() || {}).id || '';
    var name = (Auth.profile() || {}).name || (Auth.profile() || {}).username || '';

    if (userMsg) _history.push({ role: 'user', content: userMsg });

    fetch(Auth.apiBase() + '/api/sse-client/intake/turn', {
      method: 'POST',
      headers: Auth.headers('application/json'),
      body: JSON.stringify({
        user_id: uid,
        user_name: name,
        turn: turnNum,
        user_message: userMsg,
        conversation_history: _history
      })
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      _hideTyping();
      _sending = false;
      document.getElementById('intake-send').disabled = false;

      var nateMsg = d.nate_message || d.response || '';
      if (nateMsg) {
        _addBubble('nate', nateMsg);
        _history.push({ role: 'assistant', content: nateMsg });
      }

      _turn = d.turn || _turn;
      _updateProgress(_turn);

      if (d.complete) {
        _showComplete();
      }
    })
    .catch(function (err) {
      _hideTyping();
      _sending = false;
      _addBubble('nate', 'Something went wrong. Let\'s try that again.');
      document.getElementById('intake-send').disabled = false;
    });
  }

  function _updateProgress(t) {
    var el = document.getElementById('intake-turn');
    var bar = document.getElementById('intake-bar');
    if (el) el.textContent = Math.min(t, 10);
    if (bar) bar.style.width = Math.min(t / 10 * 100, 100) + '%';
  }

  function _showComplete() {
    var inputBar = _container.querySelector('.chat-input-bar');
    if (inputBar) inputBar.style.display = 'none';
    var progress = _container.querySelector('.intake-progress');
    if (progress) progress.innerHTML =
      '<div style="color:var(--cyan);font-weight:600">✨ Welcome to your story world</div>';

    setTimeout(function () { App.navigate('storyboard'); }, 3500);
  }

  function _addBubble(role, text) {
    var msgs = document.getElementById('intake-msgs');
    var isNate = role === 'nate';
    var row = document.createElement('div');
    row.className = 'chat-row ' + role;
    row.innerHTML =
      '<div class="chat-avatar">' + (isNate ? 'N' : 'Y') + '</div>' +
      '<div class="chat-bubble ' + role + '">' + _esc(text) + '</div>';
    msgs.appendChild(row);
    requestAnimationFrame(function () { msgs.scrollTop = msgs.scrollHeight; });
  }

  function _showTyping() {
    var msgs = document.getElementById('intake-msgs');
    var el = document.createElement('div');
    el.className = 'chat-row nate';
    el.id = 'intake-typing';
    el.innerHTML =
      '<div class="chat-avatar">N</div>' +
      '<div class="chat-bubble nate"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
    msgs.appendChild(el);
    requestAnimationFrame(function () { msgs.scrollTop = msgs.scrollHeight; });
  }

  function _hideTyping() {
    var el = document.getElementById('intake-typing');
    if (el) el.remove();
  }

  function _esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

  return { render: render };
})();
