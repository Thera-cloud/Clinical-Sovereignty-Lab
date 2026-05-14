// =============================================================================
// Nate Conversation Log Renderer
//
// Shared, dependency-free JS that turns the bridge's `recent_memory` /
// `recent_conversations` JSONL array into a threaded conversation view.
//
// Each entry in the array has the shape:
//   {
//     "timestamp": "2026-05-08 15:21:34.123456" | ISO8601,
//     "session_id": "session_xyz" | null,
//     "user": "<client message>",
//     "ai":   "<Little Nate response>",
//     "word_count_user": int,
//     "word_count_ai":   int,
//     ...optional metadata...
//   }
//
// Public API:
//   NateConversationLog.render(container, entries, opts)
//     opts.clientFirstName  -- defaults to "Client"
//     opts.aiName           -- defaults to "Little Nate"
//     opts.collapseChars    -- chars before "show more" (default 200)
//     opts.emptyText        -- shown when entries is empty
//
//   NateConversationLog.formatTimestamp(value)  -- "May 8, 3:21 PM"
//   NateConversationLog.parseTimestamp(value)   -- Date | null
//
// Used by:
//   - dashboard/command.html  Crisis Watchlist review modal & Coach Briefing
//   - (future) Sovereign Command Sensitive Clinical Bridge oversight tab
// =============================================================================
(function (global) {
    'use strict';

    var MONTH_NAMES = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
    ];

    function escapeHtml(s) {
        return (s == null ? '' : String(s))
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function parseTimestamp(value) {
        if (value == null) return null;
        var s = String(value).trim();
        if (!s) return null;
        // Bridge stores `str(datetime.datetime.now())` -> "YYYY-MM-DD HH:MM:SS[.ffffff]"
        // Date constructor handles ISO 8601 reliably; substitute the first space with T.
        var iso = s.indexOf('T') === -1 ? s.replace(' ', 'T') : s;
        var d = new Date(iso);
        if (isNaN(d.getTime())) return null;
        return d;
    }

    function formatTimestamp(value) {
        var d = parseTimestamp(value);
        if (!d) return value == null ? '—' : String(value);
        var hours = d.getHours();
        var minutes = d.getMinutes();
        var ampm = hours >= 12 ? 'PM' : 'AM';
        var hh = hours % 12;
        if (hh === 0) hh = 12;
        var mm = (minutes < 10 ? '0' : '') + minutes;
        return MONTH_NAMES[d.getMonth()] + ' ' + d.getDate() + ', ' + hh + ':' + mm + ' ' + ampm;
    }

    function wordCount(text) {
        if (!text) return 0;
        return String(text).split(/\s+/).filter(Boolean).length;
    }

    function bubbleHtml(opts) {
        var role = opts.role; // 'user' | 'ai'
        var color = role === 'ai' ? '#4ECDC4' : '#C9A962';
        var bg = role === 'ai' ? 'rgba(78,205,196,0.06)' : 'rgba(201,169,98,0.06)';
        var border = role === 'ai' ? 'rgba(78,205,196,0.25)' : 'rgba(201,169,98,0.25)';

        var text = opts.text || '';
        var collapseChars = opts.collapseChars;
        var bubbleId = 'ncl_' + Math.random().toString(36).slice(2, 10);
        var bodyHtml;
        if (collapseChars > 0 && text.length > collapseChars) {
            var preview = escapeHtml(text.slice(0, collapseChars).replace(/\s+$/, ''));
            var rest = escapeHtml(text.slice(collapseChars));
            bodyHtml =
                '<span data-ncl-preview>' + preview + '<span data-ncl-ellipsis>…</span></span>' +
                '<span data-ncl-rest style="display:none;">' + rest + '</span> ' +
                '<a href="#" data-ncl-toggle ' +
                'style="color:' + color + ';font-size:11px;text-decoration:none;font-weight:600;margin-left:4px;">' +
                'show more</a>';
        } else {
            bodyHtml = escapeHtml(text);
        }

        var metaHtml = '';
        if (opts.showMetadata) {
            var meta = opts.meta || {};
            var pieces = [];
            var wc = (meta.wordCount != null) ? meta.wordCount : wordCount(text);
            pieces.push('words: ' + wc);
            if (meta.sessionId) pieces.push('session: ' + escapeHtml(String(meta.sessionId)));
            if (meta.rawTimestamp) pieces.push('raw_ts: ' + escapeHtml(String(meta.rawTimestamp)));
            metaHtml =
                '<div style="margin-top:6px;color:#6B6B6B;font-size:10px;font-family:monospace;">' +
                pieces.join(' • ') +
                '</div>';
        }

        return '' +
            '<div data-ncl-bubble="' + bubbleId + '" ' +
                'style="margin:6px 0;padding:10px 12px;border-radius:10px;' +
                       'background:' + bg + ';border:1px solid ' + border + ';">' +
                '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:4px;">' +
                    '<span style="color:' + color + ';font-weight:600;font-size:11px;' +
                                 'letter-spacing:0.5px;text-transform:uppercase;">' +
                        escapeHtml(opts.speaker || '—') +
                    '</span>' +
                    '<span style="color:#888;font-size:11px;">' +
                        escapeHtml(opts.timestampLabel || '') +
                    '</span>' +
                '</div>' +
                '<div style="color:#E8E8E8;font-size:13px;line-height:1.45;' +
                             'white-space:pre-wrap;word-wrap:break-word;">' +
                    bodyHtml +
                '</div>' +
                metaHtml +
            '</div>';
    }

    function wireToggles(scope) {
        var links = scope.querySelectorAll('[data-ncl-toggle]');
        for (var i = 0; i < links.length; i++) {
            (function (a) {
                a.addEventListener('click', function (ev) {
                    ev.preventDefault();
                    var bubble = a.parentNode;
                    while (bubble && !bubble.hasAttribute('data-ncl-bubble')) {
                        bubble = bubble.parentNode;
                    }
                    if (!bubble) return;
                    var rest = bubble.querySelector('[data-ncl-rest]');
                    var ellipsis = bubble.querySelector('[data-ncl-ellipsis]');
                    if (!rest) return;
                    var hidden = rest.style.display === 'none';
                    if (hidden) {
                        rest.style.display = 'inline';
                        if (ellipsis) ellipsis.style.display = 'none';
                        a.textContent = 'show less';
                    } else {
                        rest.style.display = 'none';
                        if (ellipsis) ellipsis.style.display = 'inline';
                        a.textContent = 'show more';
                    }
                });
            })(links[i]);
        }
    }

    function render(container, entries, opts) {
        if (!container) return;
        opts = opts || {};
        var clientName = opts.clientFirstName || opts.clientName || 'Client';
        var aiName = opts.aiName || 'Little Nate';
        var collapseChars = (opts.collapseChars == null) ? 200 : opts.collapseChars;
        var emptyText = opts.emptyText || 'No conversation history available.';

        if (!Array.isArray(entries) || entries.length === 0) {
            container.innerHTML =
                '<div style="color:#666;font-size:12px;padding:12px;text-align:center;">' +
                    escapeHtml(emptyText) +
                '</div>';
            return;
        }

        // Chronological so a clinician reads top-to-bottom like a transcript.
        var sorted = entries.slice().sort(function (a, b) {
            var da = parseTimestamp(a && a.timestamp);
            var db = parseTimestamp(b && b.timestamp);
            var ta = da ? da.getTime() : 0;
            var tb = db ? db.getTime() : 0;
            return ta - tb;
        });

        var showMetadata = false;
        var bodyId = 'nclBody_' + Math.random().toString(36).slice(2, 8);
        var btnId = 'nclMetaBtn_' + Math.random().toString(36).slice(2, 8);

        function buildBody() {
            var parts = [];
            var lastSession;
            var initialized = false;
            for (var i = 0; i < sorted.length; i++) {
                var e = sorted[i] || {};
                var sid = (e.session_id == null) ? null : String(e.session_id);
                if (initialized && sid !== lastSession) {
                    parts.push(
                        '<div style="display:flex;align-items:center;gap:8px;margin:14px 0 6px 0;' +
                                     'color:#555;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;">' +
                            '<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div>' +
                            '<span>Session boundary</span>' +
                            '<div style="flex:1;height:1px;background:rgba(255,255,255,0.08);"></div>' +
                        '</div>'
                    );
                }
                lastSession = sid;
                initialized = true;

                var tsLabel = formatTimestamp(e.timestamp);
                var rawTs = e.timestamp;

                var userText = (e.user == null) ? '' : String(e.user);
                var aiText = (e.ai == null) ? '' : String(e.ai);

                if (userText.replace(/\s/g, '').length) {
                    parts.push(bubbleHtml({
                        role: 'user',
                        speaker: clientName,
                        text: userText,
                        timestampLabel: tsLabel,
                        collapseChars: collapseChars,
                        showMetadata: showMetadata,
                        meta: {
                            wordCount: e.word_count_user,
                            sessionId: sid,
                            rawTimestamp: rawTs
                        }
                    }));
                }
                if (aiText.replace(/\s/g, '').length) {
                    parts.push(bubbleHtml({
                        role: 'ai',
                        speaker: aiName,
                        text: aiText,
                        timestampLabel: tsLabel,
                        collapseChars: collapseChars,
                        showMetadata: showMetadata,
                        meta: {
                            wordCount: e.word_count_ai,
                            sessionId: sid,
                            rawTimestamp: rawTs
                        }
                    }));
                }
            }
            return parts.join('');
        }

        function repaint() {
            var body = container.querySelector('#' + bodyId);
            if (body) {
                body.innerHTML = buildBody();
                wireToggles(body);
            }
            var btn = container.querySelector('#' + btnId);
            if (btn) btn.textContent = showMetadata ? 'Hide metadata' : 'Show metadata';
        }

        container.innerHTML =
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">' +
                '<div style="flex:1;color:#888;font-size:11px;letter-spacing:1px;text-transform:uppercase;">' +
                    escapeHtml(sorted.length + ' turn' + (sorted.length === 1 ? '' : 's')) +
                '</div>' +
                '<button type="button" id="' + btnId + '" ' +
                    'style="background:transparent;border:1px solid rgba(255,255,255,0.15);' +
                           'color:#C9A962;font-size:11px;padding:4px 10px;border-radius:6px;' +
                           'cursor:pointer;">' +
                    'Show metadata' +
                '</button>' +
            '</div>' +
            '<div id="' + bodyId + '"></div>';

        var metaBtn = container.querySelector('#' + btnId);
        if (metaBtn) {
            metaBtn.addEventListener('click', function () {
                showMetadata = !showMetadata;
                repaint();
            });
        }
        repaint();
    }

    function parseEntries(input) {
        if (input == null) return [];
        if (Array.isArray(input)) return input;
        if (typeof input === 'object') return [input];
        var s = String(input).trim();
        if (!s) return [];
        // JSONL: one JSON object per line.
        var lines = s.split(/\r?\n/);
        var out = [];
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (!line) continue;
            try {
                var parsed = JSON.parse(line);
                if (parsed && typeof parsed === 'object') {
                    out.push(parsed);
                    continue;
                }
            } catch (_) {}
            // Treat unparseable lines as a synthetic user-only entry so the
            // clinician still sees them rather than dropping content silently.
            out.push({ user: line, ai: '', timestamp: null, session_id: null });
        }
        return out;
    }

    global.NateConversationLog = {
        render: render,
        formatTimestamp: formatTimestamp,
        parseTimestamp: parseTimestamp,
        parseEntries: parseEntries
    };
})(typeof window !== 'undefined' ? window : this);
