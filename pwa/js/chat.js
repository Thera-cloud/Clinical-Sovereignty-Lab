/* ── Chat module — Little Nate companion via WebSocket ── */

var Chat = (function () {
  var _ws = null;
  var _container = null;
  var _messagesEl = null;
  var _inputEl = null;
  var _sendBtn = null;
  var _reconnectAttempts = 0;
  var _reconnectTimer = null;
  var _typingEl = null;

  function render(container) {
    _container = container;
    container.innerHTML =
      '<div class="page active" style="display:flex;flex-direction:column;height:100%">' +
        '<div class="chat-messages" id="chat-msgs"></div>' +
        '<div id="chat-typing" class="hidden" style="padding:0 16px 4px">' +
          '<div class="chat-row"><div class="chat-avatar">N</div>' +
          '<div class="chat-bubble nate"><div class="typing-dots"><span></span><span></span><span></span></div></div></div></div>' +
        '<div class="chat-input-bar">' +
          '<textarea class="chat-input" id="chat-input" rows="1" placeholder="Talk to Nate..." maxlength="4000"></textarea>' +
          '<button class="chat-send" id="chat-send" disabled>' +
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>' +
          '</button>' +
        '</div>' +
      '</div>';

    _messagesEl = document.getElementById('chat-msgs');
    _inputEl = document.getElementById('chat-input');
    _sendBtn = document.getElementById('chat-send');
    _typingEl = document.getElementById('chat-typing');

    _inputEl.addEventListener('input', _autoGrow);
    _inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _send(); }
    });
    _sendBtn.addEventListener('click', _send);

    _connect();
  }

  function destroy() {
    clearTimeout(_reconnectTimer);
    if (_ws) { try { _ws.close(); } catch (e) { /* */ } }
    _ws = null;
    _reconnectAttempts = 0;
  }

  function _connect() {
    if (!Auth.isLoggedIn()) return;
    try {
      _ws = new WebSocket(Auth.wsUrl());
    } catch (e) { _scheduleReconnect(); return; }

    _ws.onopen = function () {
      _reconnectAttempts = 0;
      _ws.send(JSON.stringify({
        type: 'login_request',
        username: Auth.profile().username,
        password: Auth.profile().password || '',
        expected_role: 'CLIENT'
      }));
      _enableInput(true);
    };

    _ws.onmessage = function (ev) {
      try {
        var d = JSON.parse(ev.data);
        if (d.type === 'nate_response' || d.type === 'ai_response') {
          _hideTyping();
          _addMessage('nate', d.message || d.response || d.text || '');
        } else if (d.type === 'login_success') {
          _addMessage('nate', 'Welcome back. I\'m here whenever you\'re ready.');
        }
      } catch (e) { /* non-JSON frame */ }
    };

    _ws.onclose = function () {
      _enableInput(false);
      _scheduleReconnect();
    };

    _ws.onerror = function () { /* onclose fires after */ };
  }

  function _scheduleReconnect() {
    var attempt = Math.min(_reconnectAttempts, 10);
    var baseMs = Math.min(1000 * Math.pow(2, attempt), 30000);
    var jitter = Math.floor(baseMs * 0.2 * Math.random());
    _reconnectAttempts++;
    _reconnectTimer = setTimeout(_connect, baseMs + jitter);
  }

  function _send() {
    var text = (_inputEl.value || '').trim();
    if (!text || !_ws || _ws.readyState !== 1) return;
    _addMessage('user', text);
    _ws.send(JSON.stringify({
      type: 'chat_message',
      message: text,
      user_id: Auth.profile().hardware_id || Auth.profile().id || ''
    }));
    _inputEl.value = '';
    _autoGrow();
    _showTyping();
  }

  function _addMessage(role, text) {
    var isNate = role === 'nate';
    var row = document.createElement('div');
    row.className = 'chat-row ' + role;
    row.innerHTML =
      '<div class="chat-avatar">' + (isNate ? 'N' : 'Y') + '</div>' +
      '<div class="chat-bubble ' + role + '">' + _esc(text) + '</div>';
    _messagesEl.appendChild(row);
    _scrollDown();
  }

  function _showTyping() { _typingEl.classList.remove('hidden'); _scrollDown(); }
  function _hideTyping() { _typingEl.classList.add('hidden'); }

  function _enableInput(on) {
    _sendBtn.disabled = !on;
    _inputEl.disabled = !on;
    _inputEl.placeholder = on ? 'Talk to Nate...' : 'Connecting...';
  }

  function _scrollDown() {
    requestAnimationFrame(function () { _messagesEl.scrollTop = _messagesEl.scrollHeight; });
  }

  function _autoGrow() {
    _inputEl.style.height = 'auto';
    _inputEl.style.height = Math.min(_inputEl.scrollHeight, 100) + 'px';
    _sendBtn.disabled = !(_inputEl.value.trim()) || !_ws || _ws.readyState !== 1;
  }

  function _esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  return { render: render, destroy: destroy };
})();
