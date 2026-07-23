/* global acquireVsCodeApi */

(function () {
  const vscode = acquireVsCodeApi();

  let currentMode = 'ask';
  let isBusy = false;
  let activePlanId = null;

  // Turn card state
  let currentTurnNum = 0;
  let currentCard = null;
  let currentCardBody = null;
  let currentProgressEl = null;
  let turnToolCount = 0;
  let turnStartMs = 0;
  let turnProvider = '';
  let turnToolNames = [];

  // Nate response state
  let activeNateEl = null;

  // Progress timer
  let progressTimer = null;
  let progressStartMs = 0;

  const chatLog = document.getElementById('chatLog');
  const chatInput = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');
  const clearBtn = document.getElementById('clearBtn');
  const hypothesisPanel = document.getElementById('hypothesisPanel');
  const markFixedBar = document.getElementById('markFixedBar');
  const markFixedBtn = document.getElementById('markFixedBtn');
  const cleanLogsBtn = document.getElementById('cleanLogsBtn');
  const sessionCost = document.getElementById('sessionCost');
  const planLoadBtn = document.getElementById('planLoadBtn');
  const planInfo = document.getElementById('planInfo');
  const planName = document.getElementById('planName');
  const planProgress = document.getElementById('planProgress');
  const planClearBtn = document.getElementById('planClearBtn');

  // Safety: bail early if critical elements are missing (prevents silent IIFE crash)
  if (!chatInput || !sendBtn || !chatLog) {
    console.error('[LN] Critical DOM elements missing — chat.js cannot initialize');
    return;
  }

  // Safety timeout: if isBusy stays true for >2min, auto-recover
  let busyTimeoutId = null;

  // ── marked.js / hljs ──
  let markedParse;
  try {
    const { marked } = require('marked');
    const hljs = require('highlight.js');
    marked.setOptions({
      highlight: function (code, lang) {
        if (lang && hljs.getLanguage(lang)) {
          return hljs.highlight(code, { language: lang }).value;
        }
        return hljs.highlightAuto(code).value;
      },
      breaks: true,
      gfm: true,
    });
    markedParse = (text) => marked.parse(text);
  } catch {
    markedParse = (text) => text.replace(/\n/g, '<br>');
  }

  // ════════════════════════
  //  MODE SWITCHING
  // ════════════════════════

  document.querySelectorAll('.mode-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      if (mode === currentMode) return;
      switchMode(mode);
    });
  });

  function switchMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-btn').forEach((b) => b.classList.remove('active'));
    const active = document.querySelector(`.mode-btn[data-mode="${mode}"]`);
    if (active) active.classList.add('active');

    if (hypothesisPanel) hypothesisPanel.classList.toggle('visible', mode === 'debug');
    if (markFixedBar) markFixedBar.classList.toggle('visible', mode === 'debug' && !!activePlanId);

    const placeholders = {
      ask: 'Ask Little Nate...',
      plan: 'Describe what you want to plan...',
      ln_fab: 'Describe what to build or change...',
      debug: 'Describe the bug or unexpected behavior...',
    };
    chatInput.placeholder = placeholders[mode] || 'Ask Little Nate...';
    vscode.postMessage({ cmd: 'switchMode', mode });
  }

  // ════════════════════════
  //  SEND MESSAGE
  // ════════════════════════

  sendBtn.addEventListener('click', sendMessage);

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
  });

  function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isBusy) return;

    appendUserMessage(text);
    chatInput.value = '';
    chatInput.style.height = 'auto';
    setBusy(true);
    resetTurnState();

    vscode.postMessage({ cmd: 'send', mode: currentMode, message: text });
  }

  // ── Clear Chat ──
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      chatLog.innerHTML = '';
      if (hypothesisPanel) { hypothesisPanel.innerHTML = ''; hypothesisPanel.classList.remove('visible'); }
      if (markFixedBar) markFixedBar.classList.remove('visible');
      if (sessionCost) sessionCost.style.display = 'none';
      activePlanId = null;
      resetTurnState();
      setBusy(false);
      vscode.postMessage({ cmd: 'clearChat' });
    });
  }

  // ── Mark Fixed / Clean Logs ──
  if (markFixedBtn) {
    markFixedBtn.addEventListener('click', () => {
      if (!activePlanId) return;
      vscode.postMessage({ cmd: 'markFixed', plan_id: activePlanId, resolution: 'Marked as fixed by user in VS Code' });
      if (markFixedBar) markFixedBar.classList.remove('visible');
      appendStatusMessage('Bug marked as fixed.');
    });
  }

  if (cleanLogsBtn) {
    cleanLogsBtn.addEventListener('click', () => {
      vscode.postMessage({ cmd: 'markFixed', plan_id: activePlanId, resolution: 'clean_logs' });
      appendStatusMessage('Cleaning injected debug logs...');
    });
  }

  // ── Plan Context ──
  if (planLoadBtn) {
    planLoadBtn.addEventListener('click', () => { vscode.postMessage({ cmd: 'loadPlan' }); });
  }

  if (planClearBtn) {
    planClearBtn.addEventListener('click', () => {
      vscode.postMessage({ cmd: 'clearPlan' });
      showPlanBar(false);
    });
  }

  function showPlanBar(loaded, name, todos) {
    if (loaded) {
      if (planLoadBtn) planLoadBtn.style.display = 'none';
      if (planInfo) planInfo.style.display = 'flex';
      if (planName) planName.textContent = name || 'Unnamed Plan';
      if (planProgress) {
        if (todos && todos.length > 0) {
          const done = todos.filter(function(t) { return t.status === 'completed'; }).length;
          planProgress.textContent = done + '/' + todos.length + ' done';
        } else {
          planProgress.textContent = '';
        }
      }
    } else {
      if (planLoadBtn) planLoadBtn.style.display = '';
      if (planInfo) planInfo.style.display = 'none';
    }
  }

  // ════════════════════════════════════════
  //  INCOMING MESSAGES FROM EXTENSION HOST
  // ════════════════════════════════════════

  window.addEventListener('message', (event) => {
    const msg = event.data;
    if (!msg || !msg.cmd) return;

    switch (msg.cmd) {
      case 'chunk':    handleChunk(msg);    break;
      case 'tool':     handleToolCall(msg); break;
      case 'status':   handleStatus(msg);   break;
      case 'output':   handleOutput(msg);   break;
      case 'done':     handleDone(msg);     break;

      case 'error':
        appendStatusMessage('Error: ' + (msg.error || 'Unknown error'));
        stopProgressTimer();
        resetTurnState();
        setBusy(false);
        break;

      case 'connected':
        appendStatusMessage('Connected to bridge' + (msg.bridge_target ? ` (${msg.bridge_target})` : ''));
        setBusy(false);
        break;

      case 'authenticated':
        appendStatusMessage('Authenticated — ready');
        setBusy(false);
        break;

      case 'ask_user_prompt':
        handleAskUserPrompt(msg);
        break;

      case 'disconnected':
        appendStatusMessage('Disconnected from bridge');
        stopProgressTimer();
        resetTurnState();
        setBusy(false);
        break;

      case 'modeChanged':
        if (msg.mode) switchMode(msg.mode);
        break;

      case 'output_applied':
        appendStatusMessage('Changes applied to ' + (msg.content || 'file'));
        break;

      case 'planLoaded':
        showPlanBar(true, msg.plan_name, msg.plan_todos);
        appendStatusMessage('Plan loaded: ' + (msg.plan_name || 'Unnamed'));
        break;

      case 'planCleared':
        showPlanBar(false);
        break;

      case 'restoreHistory':
        restoreFromHistory(msg.history || []);
        break;
    }
  });

  // ════════════════════════════════════
  //  TURN CARD MANAGEMENT
  // ════════════════════════════════════

  function resetTurnState() {
    currentTurnNum = 0;
    currentCard = null;
    currentCardBody = null;
    currentProgressEl = null;
    turnToolCount = 0;
    turnStartMs = 0;
    turnProvider = '';
    turnToolNames = [];
    activeNateEl = null;
    stopProgressTimer();
  }

  function ensureTurnCard(turn) {
    const turnNum = turn || (currentTurnNum || 1);

    if (currentCard && currentTurnNum === turnNum) return;

    // Collapse previous card
    if (currentCard) {
      finalizeCurrentCard();
      currentCard.classList.remove('active', 'expanded');
      currentCard.classList.add('collapsed');
    }

    currentTurnNum = turnNum;
    turnToolCount = 0;
    turnToolNames = [];
    turnStartMs = Date.now();

    // Build card DOM
    const card = document.createElement('div');
    card.className = 'turn-card active expanded';
    card.dataset.turn = turnNum;

    const header = document.createElement('div');
    header.className = 'turn-card-header';
    header.innerHTML =
      '<span class="turn-label">TURN ' + turnNum + '</span>' +
      '<span class="turn-summary">Working...</span>' +
      '<span class="turn-tool-count" style="display:none"></span>' +
      '<span class="turn-duration"></span>' +
      '<span class="provider-badge" style="display:none"></span>' +
      '<span class="turn-chevron">›</span>';

    header.addEventListener('click', () => toggleCard(card));

    const progress = document.createElement('div');
    progress.className = 'turn-card-progress';
    progress.innerHTML =
      '<span class="spinner"></span>' +
      '<span class="progress-text">Working...</span>' +
      '<span class="progress-time"></span>';

    const body = document.createElement('div');
    body.className = 'turn-card-body';

    card.appendChild(header);
    card.appendChild(progress);
    card.appendChild(body);
    chatLog.appendChild(card);

    currentCard = card;
    currentCardBody = body;
    currentProgressEl = progress;
    currentProgressEl.classList.add('visible');

    startProgressTimer();
    scrollToCard(card);
  }

  function toggleCard(card) {
    card.classList.toggle('expanded');
  }

  function updateCardHeader() {
    if (!currentCard) return;
    const header = currentCard.querySelector('.turn-card-header');
    if (!header) return;

    const countEl = header.querySelector('.turn-tool-count');
    if (countEl && turnToolCount > 0) {
      countEl.textContent = turnToolCount + ' tool' + (turnToolCount !== 1 ? 's' : '');
      countEl.style.display = '';
    }

    const durEl = header.querySelector('.turn-duration');
    if (durEl && turnStartMs) {
      durEl.textContent = ((Date.now() - turnStartMs) / 1000).toFixed(1) + 's';
    }

    if (turnProvider) {
      const provEl = header.querySelector('.provider-badge');
      if (provEl) {
        provEl.textContent = turnProvider.toUpperCase();
        provEl.className = 'provider-badge ' + turnProvider.toLowerCase().replace(/[\s-]/g, '_');
        provEl.style.display = '';
      }
    }
  }

  function updateCardSummary(text) {
    if (!currentCard) return;
    const el = currentCard.querySelector('.turn-summary');
    if (el) el.textContent = text;
  }

  function buildAutoSummary() {
    if (turnToolNames.length === 0) return 'Working...';
    const counts = {};
    turnToolNames.forEach(function(n) { counts[n] = (counts[n] || 0) + 1; });
    return Object.entries(counts)
      .map(function(e) { return e[0] + (e[1] > 1 ? ' ×' + e[1] : ''); })
      .join(', ');
  }

  function finalizeCurrentCard() {
    if (!currentCard) return;
    stopProgressTimer();
    if (currentProgressEl) currentProgressEl.classList.remove('visible');

    updateCardHeader();
    updateCardSummary(buildAutoSummary());
  }

  function startProgressTimer() {
    stopProgressTimer();
    progressStartMs = Date.now();
    progressTimer = setInterval(function () {
      if (currentProgressEl) {
        const timeEl = currentProgressEl.querySelector('.progress-time');
        if (timeEl) {
          timeEl.textContent = ((Date.now() - progressStartMs) / 1000).toFixed(1) + 's';
        }
      }
    }, 100);
  }

  function stopProgressTimer() {
    if (progressTimer) {
      clearInterval(progressTimer);
      progressTimer = null;
    }
  }

  // ════════════════════════════════════
  //  MESSAGE HANDLERS
  // ════════════════════════════════════

  function handleToolCall(msg) {
    const turn = msg.turn || currentTurnNum || 1;
    ensureTurnCard(turn);

    turnToolCount++;
    turnToolNames.push(msg.tool_name);
    if (msg.provider) turnProvider = msg.provider;

    // Build tool line
    const line = document.createElement('div');
    line.className = 'tool-line';

    const icon = toolIcon(msg.tool_name);
    const argsSummary = toolArgsSummary(msg.tool_name, msg.tool_input);
    const status = (msg.status || 'ok').toLowerCase();
    const statusLabel = status.toUpperCase();
    const durText = msg.duration_ms != null ? msg.duration_ms + 'ms' : '';

    let argsHtml = escHtml(argsSummary);
    // Make file paths clickable for read_file
    const filePath = msg.tool_input && msg.tool_input.path;
    if (filePath && (msg.tool_name === 'read_file' || msg.tool_name === 'write_file' || msg.tool_name === 'create_file')) {
      const startLine = msg.tool_input.start_line || 1;
      argsHtml = '<span class="file-link" data-path="' + escHtml(String(filePath)) + '" data-line="' + startLine + '">(' + escHtml(argsSummary) + ')</span>';
    } else {
      argsHtml = '(' + argsHtml + ')';
    }

    const hasOutput = msg.tool_output_preview && msg.tool_output_preview.length > 0;

    line.innerHTML =
      '<span class="tool-icon">' + icon + '</span>' +
      '<span class="tool-name">' + escHtml(msg.tool_name) + '</span>' +
      '<span class="tool-args">' + argsHtml + '</span>' +
      '<span class="tool-status ' + escHtml(status) + '">' + statusLabel + '</span>' +
      '<span class="tool-dur">' + escHtml(durText) + '</span>' +
      (hasOutput ? '<button class="tool-show-btn">Show</button>' : '');

    // Wire file link click
    const fileLink = line.querySelector('.file-link');
    if (fileLink) {
      fileLink.addEventListener('click', function (e) {
        e.stopPropagation();
        vscode.postMessage({
          cmd: 'openFile',
          file_path: fileLink.dataset.path,
          start_line: parseInt(fileLink.dataset.line) || 1,
        });
      });
    }

    currentCardBody.appendChild(line);

    // Add expandable output
    if (hasOutput) {
      const outputEl = document.createElement('div');
      outputEl.className = 'tool-output';
      outputEl.textContent = String(msg.tool_output_preview || '').substring(0, 3000);
      currentCardBody.appendChild(outputEl);

      const showBtn = line.querySelector('.tool-show-btn');
      showBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        const visible = outputEl.classList.toggle('visible');
        showBtn.textContent = visible ? 'Hide' : 'Show';
      });
    }

    // Render str_replace / proposed_edit proposals
    if (isProposalTool(msg.tool_name, msg.status)) {
      renderProposalBlock(msg);
    }

    // Update card header
    updateCardHeader();

    // Update progress indicator
    if (currentProgressEl) {
      const progText = currentProgressEl.querySelector('.progress-text');
      if (progText) {
        progText.textContent = msg.tool_name + '(' + toolArgsSummary(msg.tool_name, msg.tool_input, true) + ')';
      }
    }

    scrollToCard(currentCard);
  }

  function handleChunk(msg) {
    // Finalize any open card when text streaming starts
    if (currentCard && currentProgressEl && currentProgressEl.classList.contains('visible')) {
      finalizeCurrentCard();
      currentCard.classList.remove('expanded');
    }

    if (!activeNateEl) {
      activeNateEl = document.createElement('div');
      activeNateEl.className = 'msg-nate';
      activeNateEl._raw = '';
      chatLog.appendChild(activeNateEl);
    }

    if (msg.provider) turnProvider = msg.provider;

    activeNateEl._raw += msg.delta || '';
    try {
      activeNateEl.innerHTML = markedParse(activeNateEl._raw);
    } catch (err) {
      activeNateEl.innerHTML = activeNateEl._raw.replace(/\n/g, '<br>');
    }
    scrollToBottom();
  }

  function handleStatus(msg) {
    const text = msg.status_text || msg.detail || 'Processing...';

    if (text === 'debug_cleanup') {
      appendStatusMessage('Debug injections cleaned up.');
      return;
    }

    const turn = msg.turn || currentTurnNum || 1;

    // 'thinking' signals a new turn
    if (text === 'thinking' || text === 'Thinking...') {
      ensureTurnCard(turn);
      return;
    }

    // Update progress on existing card
    if (currentCard && currentProgressEl) {
      currentProgressEl.classList.add('visible');
      const progText = currentProgressEl.querySelector('.progress-text');
      if (progText) progText.textContent = text;
      startProgressTimer();
    } else {
      ensureTurnCard(turn);
    }
  }

  function handleOutput(msg) {
    appendStatusMessage('Generated code output (' + (msg.language || 'text') + ')');
  }

  function handleDone(msg) {
    stopProgressTimer();
    removeLoadingIndicator();

    // Finalize current card
    if (currentCard) {
      finalizeCurrentCard();
      if (msg.provider) turnProvider = msg.provider;
      updateCardHeader();
      // Collapse card body if response text exists
      if (activeNateEl) {
        currentCard.classList.remove('expanded');
      }
    }

    setBusy(false);

    if (msg.plan_id) activePlanId = msg.plan_id;

    // Add provider badge to nate response if no card was shown
    if (activeNateEl && !currentCard && (msg.provider || turnProvider)) {
      const badge = document.createElement('div');
      badge.style.cssText = 'margin-top:4px;';
      const prov = msg.provider || turnProvider;
      badge.innerHTML = '<span class="provider-badge ' + escHtml(prov) + '">' + escHtml(prov.toUpperCase()) + '</span>';
      activeNateEl.appendChild(badge);
    }

    // Hypotheses (debug mode)
    if (msg.hypotheses && msg.hypotheses.length > 0) {
      renderHypotheses(msg.hypotheses);
    }

    if (msg.mode === 'debug' && activePlanId) {
      markFixedBar.classList.add('visible');
    }

    // Cost badge
    if (msg.cost) {
      sessionCost.textContent = '$' + msg.cost.est_cost_usd.toFixed(4) + ' | ' + msg.cost.est_input_tokens + '→' + msg.cost.est_output_tokens + ' tok';
      sessionCost.style.display = 'inline-flex';
    }

    if (msg.error) {
      appendStatusMessage('Error: ' + msg.error);
    }

    // Reset turn state for next interaction
    currentCard = null;
    currentCardBody = null;
    currentProgressEl = null;
    activeNateEl = null;

    scrollToBottom();
  }

  // ════════════════════════════════════
  //  ASK USER PROMPT (structured UI)
  // ════════════════════════════════════

  function handleAskUserPrompt(msg) {
    var container = document.createElement('div');
    container.className = 'ask-user-prompt';

    var questionEl = document.createElement('div');
    questionEl.className = 'ask-user-question';
    questionEl.textContent = msg.question || 'Please select:';
    container.appendChild(questionEl);

    if (msg.context) {
      var ctxEl = document.createElement('div');
      ctxEl.className = 'ask-user-context';
      ctxEl.textContent = msg.context;
      container.appendChild(ctxEl);
    }

    var optionsEl = document.createElement('div');
    optionsEl.className = 'ask-user-options';
    var isMulti = msg.question_type === 'multi_select';
    var selected = {};
    var options = msg.options || [];

    options.forEach(function (opt) {
      var btn = document.createElement('button');
      btn.className = 'ask-user-option';
      btn.textContent = opt.label || opt.id;
      btn.dataset.optId = opt.id;
      btn.addEventListener('click', function () {
        if (isMulti) {
          selected[opt.id] = !selected[opt.id];
          btn.classList.toggle('selected', !!selected[opt.id]);
        } else {
          vscode.postMessage({
            cmd: 'ask_user_response',
            question_id: msg.question_id,
            selected_values: [opt.id],
          });
          container.remove();
          appendStatusMessage('Selected: ' + (opt.label || opt.id));
        }
      });
      optionsEl.appendChild(btn);
    });
    container.appendChild(optionsEl);

    if (isMulti) {
      var submitBtn = document.createElement('button');
      submitBtn.className = 'ask-user-submit';
      submitBtn.textContent = 'Confirm';
      submitBtn.addEventListener('click', function () {
        var vals = Object.keys(selected).filter(function (k) { return selected[k]; });
        if (vals.length > 0) {
          vscode.postMessage({
            cmd: 'ask_user_response',
            question_id: msg.question_id,
            selected_values: vals,
          });
          container.remove();
          appendStatusMessage('Selected: ' + vals.join(', '));
        }
      });
      container.appendChild(submitBtn);
    }

    if (msg.allow_skip) {
      var skipBtn = document.createElement('button');
      skipBtn.className = 'ask-user-skip';
      skipBtn.textContent = 'Skip';
      skipBtn.addEventListener('click', function () {
        vscode.postMessage({
          cmd: 'ask_user_response',
          question_id: msg.question_id,
          selected_values: [],
          skipped: true,
        });
        container.remove();
        appendStatusMessage('Skipped question');
      });
      container.appendChild(skipBtn);
    }

    chatLog.appendChild(container);
    scrollToBottom();
  }

  // ════════════════════════════════════
  //  PROPOSAL BLOCK (str_replace)
  // ════════════════════════════════════

  function isProposalTool(toolName, status) {
    return (toolName === 'str_replace' || toolName === 'proposed_edit') &&
           (status === 'pending' || status === 'denied');
  }

  function renderProposalBlock(msg) {
    const block = document.createElement('div');
    block.className = 'proposal-block';

    const path = msg.tool_input && msg.tool_input.path ? String(msg.tool_input.path) : 'file';
    const shortPath = path.split('/').pop();
    const oldStr = msg.tool_input && msg.tool_input.old_string ? String(msg.tool_input.old_string) : '';
    const newStr = msg.tool_input && msg.tool_input.new_string ? String(msg.tool_input.new_string) : '';
    const content = msg.tool_input && msg.tool_input.content ? String(msg.tool_input.content) : '';

    const ruleMatch = (msg.tool_output_preview || '').match(/Rule\s+(\d+)/i);
    const ruleLabel = ruleMatch ? ' (Rule ' + ruleMatch[1] + ')' : '';

    let titleText = 'Proposed ' + msg.tool_name + ' for ' + shortPath + ruleLabel + ':';

    let beforeBlock = '';
    let afterBlock = '';

    if (oldStr || newStr) {
      const startLine = msg.tool_input.start_line;
      const endLine = msg.tool_input.end_line;
      const lineRange = startLine && endLine ? ' (lines ' + startLine + '-' + endLine + ')' : '';
      const newLineCount = newStr.split('\n').length;
      const oldLineCount = oldStr.split('\n').length;
      const lineDiff = newLineCount - oldLineCount;
      const afterLabel = lineDiff > 0 ? '(+' + lineDiff + ' lines)' :
                          lineDiff < 0 ? '(' + lineDiff + ' lines)' : '';

      beforeBlock =
        '<div class="proposal-section">' +
          '<div class="proposal-label before">BEFORE' + escHtml(lineRange) + ':</div>' +
          '<pre class="proposal-code">' + escHtml(truncateCode(oldStr, 20)) + '</pre>' +
        '</div>';

      afterBlock =
        '<div class="proposal-section">' +
          '<div class="proposal-label after">AFTER ' + escHtml(afterLabel) + ':</div>' +
          '<pre class="proposal-code">' + escHtml(truncateCode(newStr, 20)) + '</pre>' +
        '</div>';
    } else if (content) {
      afterBlock =
        '<div class="proposal-section">' +
          '<div class="proposal-label after">CONTENT:</div>' +
          '<pre class="proposal-code">' + escHtml(truncateCode(content, 20)) + '</pre>' +
        '</div>';
    }

    block.innerHTML =
      '<div class="proposal-title">' + escHtml(titleText) + '</div>' +
      beforeBlock + afterBlock +
      '<div class="proposal-actions">' +
        'Say <span class="kw-approved">"approved"</span> to execute or <span class="kw-stop">"stop"</span> to abandon.' +
      '</div>';

    chatLog.appendChild(block);

    // Approval waiting indicator
    const waiting = document.createElement('div');
    waiting.className = 'approval-waiting';
    waiting.innerHTML = '<span class="approval-dot"></span> Waiting for approval' + escHtml(ruleLabel) + '...';
    chatLog.appendChild(waiting);
  }

  function truncateCode(code, maxLines) {
    const lines = code.split('\n');
    if (lines.length <= maxLines) return code;
    return lines.slice(0, maxLines).join('\n') + '\n  ... (' + (lines.length - maxLines) + ' more lines)';
  }

  // ════════════════════════════════════
  //  TOOL HELPERS
  // ════════════════════════════════════

  function toolIcon(name) {
    var icons = {
      'read_file': '📄', 'write_file': '✏️', 'create_file': '📝',
      'str_replace': '✏️', 'proposed_edit': '✏️',
      'search_code': '🔍', 'list_directory': '📁',
      'grep': '🔎', 'glob': '📂',
      'shell': '⚡', 'read_lints': '🔬',
      'inject_log': '💉', 'debug_cleanup': '🧹',
      'delete_file': '🗑️', 'rename_file': '📎',
      'run_command': '⚡', 'read_diagnostics': '🔬',
      'read_git_status': '📊', 'git_log': '📜', 'read_open_editors': '📑', 'plan_index': '🗺️',
      'web_fetch': '🌐', 'web_search_local': '🌐',
      'todo_write': '📋', 'switch_mode': '🔄',
      'provider_stats': '📊',
    };
    if (icons[name]) return icons[name];
    if (name && name.startsWith('query_')) return '🗃️';
    return '🔧';
  }

  function toolArgsSummary(toolName, input, short) {
    if (!input) return '';
    var p = input.path ? String(input.path) : '';
    var shortPath = p.split('/').pop() || p;

    switch (toolName) {
      case 'read_file': {
        var range = '';
        if (input.start_line && input.end_line) range = ':' + input.start_line + '-' + input.end_line;
        else if (input.start_line) range = ':' + input.start_line;
        return shortPath + range;
      }
      case 'str_replace':
      case 'proposed_edit': {
        if (short) return shortPath;
        var newStr = input.new_string ? String(input.new_string) : '';
        var lines = newStr.split('\n').length;
        return shortPath + ' +' + lines + ' lines';
      }
      case 'write_file':
      case 'create_file':
      case 'delete_file':
        return shortPath;
      case 'rename_file':
        return (input.old_path ? String(input.old_path).split('/').pop() : '') + ' → ' + shortPath;
      case 'search_code':
        return short ? (input.pattern || '') : '"' + (input.pattern || '') + '"' + (p ? ' in ' + shortPath : '');
      case 'list_directory':
        return shortPath || '.';
      case 'run_command':
        var cmd = input.command ? String(input.command) : '';
        return cmd.length > 40 ? cmd.substring(0, 40) + '…' : cmd;
      default:
        return shortPath || Object.keys(input).filter(function(k) { return k !== 'content'; }).map(function(k) {
          return k + '=' + String(input[k]).substring(0, 30);
        }).join(', ');
    }
  }

  // ════════════════════════════════════
  //  HYPOTHESIS RENDERING (DEBUG)
  // ════════════════════════════════════

  function renderHypotheses(hypotheses) {
    hypothesisPanel.innerHTML = '';
    hypothesisPanel.classList.add('visible');

    hypotheses.forEach(function (h) {
      var card = document.createElement('div');
      card.className = 'hypothesis-card';
      var evidenceHtml = '';
      if (h.evidence && h.evidence.length) {
        evidenceHtml = '<ul class="h-evidence">' + h.evidence.map(function(e) { return '<li>' + escHtml(e) + '</li>'; }).join('') + '</ul>';
      }
      card.innerHTML =
        '<div class="h-title">Hypothesis ' + h.id + ': ' + escHtml(h.title) + '</div>' +
        '<div class="h-confidence">' + escHtml(h.confidence || 'medium') + '</div>' +
        evidenceHtml;
      hypothesisPanel.appendChild(card);
    });
  }

  // ════════════════════════════════════
  //  UI UTILITIES
  // ════════════════════════════════════

  function restoreFromHistory(entries) {
    if (!entries || entries.length === 0) return;
    chatLog.innerHTML = '';
    entries.forEach(function (entry) {
      if (entry.role === 'user') {
        var el = document.createElement('div');
        el.className = 'msg-user';
        el.textContent = entry.content;
        chatLog.appendChild(el);
      } else if (entry.role === 'nate') {
        var el = document.createElement('div');
        el.className = 'msg-nate';
        try {
          el.innerHTML = markedParse(entry.content);
        } catch (err) {
          el.innerHTML = entry.content.replace(/\n/g, '<br>');
        }
        if (entry.provider) {
          var badge = document.createElement('div');
          badge.style.cssText = 'margin-top:4px;';
          badge.innerHTML = '<span class="provider-badge ' + escHtml(entry.provider) + '">' + escHtml(entry.provider.toUpperCase()) + '</span>';
          el.appendChild(badge);
        }
        chatLog.appendChild(el);
      } else if (entry.role === 'status') {
        var el = document.createElement('div');
        el.className = 'msg-status';
        el.textContent = entry.content;
        chatLog.appendChild(el);
      }
    });
    scrollToBottom();
  }

  function appendUserMessage(text) {
    var el = document.createElement('div');
    el.className = 'msg-user';
    el.textContent = text;
    chatLog.appendChild(el);
    scrollToBottom();
  }

  function appendStatusMessage(text) {
    removeLoadingIndicator();
    var el = document.createElement('div');
    el.className = 'msg-status';
    el.textContent = text;
    chatLog.appendChild(el);
    scrollToBottom();
  }

  function removeLoadingIndicator() {
    var existing = document.getElementById('loadingIndicator');
    if (existing) existing.remove();
  }

  function setBusy(busy) {
    isBusy = busy;
    sendBtn.disabled = busy;
    chatInput.disabled = busy;
    if (busyTimeoutId) { clearTimeout(busyTimeoutId); busyTimeoutId = null; }
    if (busy) {
      busyTimeoutId = setTimeout(function () {
        if (isBusy) {
          console.warn('[LN] isBusy stuck for 2 min — auto-recovering');
          setBusy(false);
          appendStatusMessage('Response timed out. You can try again.');
        }
      }, 120000);
    } else {
      chatInput.focus();
    }
  }

  function scrollToCard(card) {
    requestAnimationFrame(function () {
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }

  function scrollToBottom() {
    requestAnimationFrame(function () {
      chatLog.scrollTop = chatLog.scrollHeight;
    });
  }

  function escHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
