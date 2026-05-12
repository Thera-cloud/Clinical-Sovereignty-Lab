/// Conversation Log View
///
/// Shared widget that renders the bridge's `recent_memory` /
/// `recent_conversations` payload as a threaded conversation log.
///
/// Each entry has the shape:
///   {
///     "timestamp": "2026-05-08 15:21:34.123456" | ISO8601 | null,
///     "session_id": "session_xyz" | null,
///     "user": "<client message>",
///     "ai":   "<Little Nate response>",
///     "word_count_user": int,
///     "word_count_ai":   int,
///     ...optional metadata...
///   }
///
/// Used by:
///   - Coach Command Client Briefing modal (`updated_screens.dart`)
///   - (future) Sovereign Command Sensitive Clinical Bridge oversight tab
///
/// Mirrors `dashboard/conversation_log_renderer.js` so clinicians see the
/// same conversation shape across web and mobile.
library;

import 'dart:convert';
import 'package:flutter/material.dart';

class ConversationLogView extends StatefulWidget {
  const ConversationLogView({
    super.key,
    required this.entries,
    this.clientFirstName = 'Client',
    this.aiName = 'Little Nate',
    this.collapseChars = 200,
    this.emptyText = 'No conversation history available.',
    this.headerColor,
  });

  final List<dynamic> entries;
  final String clientFirstName;
  final String aiName;
  final int collapseChars;
  final String emptyText;
  final Color? headerColor;

  /// Accepts the bridge payload in any of three forms:
  ///   - List<dynamic>
  ///   - Map<String, dynamic> (single turn)
  ///   - String (JSONL — one JSON object per line)
  /// Lines that fail to parse are kept as user-only synthetic entries so the
  /// clinician still sees raw content rather than silently losing it.
  static List<Map<String, dynamic>> parseEntries(dynamic input) {
    if (input == null) return const <Map<String, dynamic>>[];
    if (input is List) {
      return input
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    }
    if (input is Map) {
      return <Map<String, dynamic>>[Map<String, dynamic>.from(input)];
    }
    final text = input.toString().trim();
    if (text.isEmpty) return const <Map<String, dynamic>>[];
    final out = <Map<String, dynamic>>[];
    for (final raw in text.split(RegExp(r'\r?\n'))) {
      final line = raw.trim();
      if (line.isEmpty) continue;
      try {
        final parsed = jsonDecode(line);
        if (parsed is Map) {
          out.add(Map<String, dynamic>.from(parsed));
          continue;
        }
      } catch (_) {
        // fall through to synthetic entry
      }
      out.add(<String, dynamic>{
        'user': line,
        'ai': '',
        'timestamp': null,
        'session_id': null,
      });
    }
    return out;
  }

  static DateTime? parseTimestamp(dynamic value) {
    if (value == null) return null;
    final s = value.toString().trim();
    if (s.isEmpty) return null;
    final iso = s.contains('T') ? s : s.replaceFirst(' ', 'T');
    try {
      return DateTime.parse(iso);
    } catch (_) {
      return null;
    }
  }

  static const List<String> _months = <String>[
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];

  /// Returns "May 8, 3:21 PM" or the raw string fallback.
  static String formatTimestamp(dynamic value) {
    final dt = parseTimestamp(value);
    if (dt == null) return value == null ? '—' : value.toString();
    final hour24 = dt.hour;
    final ampm = hour24 >= 12 ? 'PM' : 'AM';
    var hh = hour24 % 12;
    if (hh == 0) hh = 12;
    final mm = dt.minute.toString().padLeft(2, '0');
    final mon = _months[dt.month - 1];
    return '$mon ${dt.day}, $hh:$mm $ampm';
  }

  static int _wordCount(String text) {
    if (text.isEmpty) return 0;
    return text
        .split(RegExp(r'\s+'))
        .where((w) => w.isNotEmpty)
        .length;
  }

  @override
  State<ConversationLogView> createState() => _ConversationLogViewState();
}

class _ConversationLogViewState extends State<ConversationLogView> {
  bool _showMetadata = false;
  // bubbleId -> expanded
  final Map<String, bool> _expanded = <String, bool>{};

  static const Color _userColor = Color(0xFFC9A962);
  static const Color _aiColor = Color(0xFF4ECDC4);
  static const Color _bubbleText = Color(0xFFE8E8E8);
  static const Color _meta = Color(0xFF6B6B6B);
  static const Color _divider = Color(0x14FFFFFF);

  List<Map<String, dynamic>> _sortedEntries() {
    final normalized = widget.entries
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    normalized.sort((a, b) {
      final ta = ConversationLogView.parseTimestamp(a['timestamp']);
      final tb = ConversationLogView.parseTimestamp(b['timestamp']);
      final ma = ta?.millisecondsSinceEpoch ?? 0;
      final mb = tb?.millisecondsSinceEpoch ?? 0;
      return ma.compareTo(mb);
    });
    return normalized;
  }

  @override
  Widget build(BuildContext context) {
    final sorted = _sortedEntries();

    if (sorted.isEmpty) {
      return Container(
        padding: const EdgeInsets.all(12),
        alignment: Alignment.center,
        child: Text(
          widget.emptyText,
          style: const TextStyle(color: Color(0xFF666666), fontSize: 12),
        ),
      );
    }

    final children = <Widget>[];
    String? lastSession;
    var initialized = false;
    for (var i = 0; i < sorted.length; i++) {
      final e = sorted[i];
      final sid = e['session_id']?.toString();
      if (initialized && sid != lastSession) {
        children.add(_sessionDivider());
      }
      lastSession = sid;
      initialized = true;

      final tsLabel = ConversationLogView.formatTimestamp(e['timestamp']);
      final userText = (e['user'] ?? '').toString();
      final aiText = (e['ai'] ?? '').toString();

      if (userText.replaceAll(RegExp(r'\s'), '').isNotEmpty) {
        children.add(_bubble(
          bubbleId: 'u_$i',
          isAi: false,
          speaker: widget.clientFirstName,
          timestampLabel: tsLabel,
          text: userText,
          metaWordCount: e['word_count_user'],
          sessionId: sid,
          rawTimestamp: e['timestamp'],
        ));
      }
      if (aiText.replaceAll(RegExp(r'\s'), '').isNotEmpty) {
        children.add(_bubble(
          bubbleId: 'a_$i',
          isAi: true,
          speaker: widget.aiName,
          timestampLabel: tsLabel,
          text: aiText,
          metaWordCount: e['word_count_ai'],
          sessionId: sid,
          rawTimestamp: e['timestamp'],
        ));
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  '${sorted.length} turn${sorted.length == 1 ? '' : 's'}',
                  style: const TextStyle(
                    color: Color(0xFF888888),
                    fontSize: 11,
                    letterSpacing: 1,
                  ),
                ),
              ),
              GestureDetector(
                onTap: () => setState(() => _showMetadata = !_showMetadata),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.transparent,
                    border: Border.all(color: const Color(0x26FFFFFF)),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _showMetadata ? 'Hide metadata' : 'Show metadata',
                    style: const TextStyle(
                      color: _userColor,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
        ...children,
      ],
    );
  }

  Widget _sessionDivider() {
    return const Padding(
      padding: EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: <Widget>[
          Expanded(child: Divider(color: _divider, height: 1)),
          Padding(
            padding: EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              'SESSION BOUNDARY',
              style: TextStyle(
                color: Color(0xFF555555),
                fontSize: 10,
                letterSpacing: 1.5,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(child: Divider(color: _divider, height: 1)),
        ],
      ),
    );
  }

  Widget _bubble({
    required String bubbleId,
    required bool isAi,
    required String speaker,
    required String timestampLabel,
    required String text,
    required dynamic metaWordCount,
    required String? sessionId,
    required dynamic rawTimestamp,
  }) {
    final accent = isAi ? _aiColor : _userColor;
    final bg = isAi
        ? const Color(0x0F4ECDC4)
        : const Color(0x0FC9A962);
    final border = isAi
        ? const Color(0x404ECDC4)
        : const Color(0x40C9A962);

    final isLong = text.length > widget.collapseChars;
    final expanded = _expanded[bubbleId] ?? false;
    final shownText = (isLong && !expanded)
        ? '${text.substring(0, widget.collapseChars).trimRight()}…'
        : text;

    final wordCount = metaWordCount is int
        ? metaWordCount
        : ConversationLogView._wordCount(text);

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: bg,
        border: Border.all(color: border),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: <Widget>[
              Text(
                speaker.toUpperCase(),
                style: TextStyle(
                  color: accent,
                  fontSize: 11,
                  letterSpacing: 0.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(width: 10),
              Text(
                timestampLabel,
                style: const TextStyle(
                  color: Color(0xFF888888),
                  fontSize: 11,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            shownText,
            style: const TextStyle(
              color: _bubbleText,
              fontSize: 13,
              height: 1.45,
            ),
          ),
          if (isLong)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: GestureDetector(
                onTap: () => setState(() {
                  _expanded[bubbleId] = !expanded;
                }),
                child: Text(
                  expanded ? 'show less' : 'show more',
                  style: TextStyle(
                    color: accent,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
          if (_showMetadata)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                _metaLine(wordCount, sessionId, rawTimestamp),
                style: const TextStyle(
                  color: _meta,
                  fontSize: 10,
                  fontFamily: 'monospace',
                ),
              ),
            ),
        ],
      ),
    );
  }

  String _metaLine(int wordCount, String? sessionId, dynamic rawTimestamp) {
    final parts = <String>['words: $wordCount'];
    if (sessionId != null && sessionId.isNotEmpty) {
      parts.add('session: $sessionId');
    }
    if (rawTimestamp != null && rawTimestamp.toString().isNotEmpty) {
      parts.add('raw_ts: ${rawTimestamp.toString()}');
    }
    return parts.join(' • ');
  }
}
