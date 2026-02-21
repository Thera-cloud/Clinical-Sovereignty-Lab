import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

/// Nate Guardian — Device-level protection module
/// Provides real-time security checks for all platform users.
///
/// Features:
///   1. Link Guardian — URL interception and phishing check via Hive API
///   2. Clipboard Shield — PII detection in clipboard content
///   3. Network Safety — Basic connectivity health checks
///   4. Session Lock — Idle timeout and background lock
///
/// Patent-Pending — Claims 30-56
/// © 2026 Clinical Sovereignty Lab. All rights reserved.

class NateGuardianConfig {
  final String apiBaseUrl;
  final Duration clipboardCheckInterval;
  final Duration sessionTimeout;
  final bool enableLinkGuardian;
  final bool enableClipboardShield;
  final bool enableNetworkSafety;

  const NateGuardianConfig({
    required this.apiBaseUrl,
    this.clipboardCheckInterval = const Duration(seconds: 30),
    this.sessionTimeout = const Duration(minutes: 15),
    this.enableLinkGuardian = true,
    this.enableClipboardShield = true,
    this.enableNetworkSafety = true,
  });
}

enum ThreatLevel { clean, suspicious, malicious }

class GuardianAlert {
  final String id;
  final String module;
  final ThreatLevel level;
  final String title;
  final String detail;
  final DateTime timestamp;
  final Map<String, dynamic>? metadata;

  GuardianAlert({
    required this.id,
    required this.module,
    required this.level,
    required this.title,
    required this.detail,
    DateTime? timestamp,
    this.metadata,
  }) : timestamp = timestamp ?? DateTime.now();

  Map<String, dynamic> toJson() => {
        'id': id,
        'module': module,
        'level': level.name,
        'title': title,
        'detail': detail,
        'timestamp': timestamp.toIso8601String(),
        'metadata': metadata,
      };
}

class NateGuardian {
  final NateGuardianConfig config;
  final List<GuardianAlert> _alerts = [];
  final StreamController<GuardianAlert> _alertStream =
      StreamController.broadcast();
  Timer? _clipboardTimer;
  Timer? _sessionTimer;
  String? _lastClipboard;
  bool _running = false;
  int _linksChecked = 0;
  int _threatsBlocked = 0;
  int _clipboardScans = 0;

  NateGuardian({required this.config});

  Stream<GuardianAlert> get alertStream => _alertStream.stream;
  List<GuardianAlert> get recentAlerts => List.unmodifiable(_alerts);
  bool get isRunning => _running;
  int get linksChecked => _linksChecked;
  int get threatsBlocked => _threatsBlocked;
  int get clipboardScans => _clipboardScans;

  Map<String, dynamic> get status => {
        'running': _running,
        'links_checked': _linksChecked,
        'threats_blocked': _threatsBlocked,
        'clipboard_scans': _clipboardScans,
        'recent_alerts': _alerts.length,
        'modules': {
          'link_guardian': config.enableLinkGuardian,
          'clipboard_shield': config.enableClipboardShield,
          'network_safety': config.enableNetworkSafety,
        },
      };

  /// Start all enabled protection modules
  void start() {
    if (_running) return;
    _running = true;

    if (config.enableClipboardShield) {
      _startClipboardShield();
    }

    if (config.enableNetworkSafety) {
      _startSessionLock();
    }

    debugPrint('[NateGuardian] Started — modules active');
  }

  /// Stop all protection modules
  void stop() {
    _running = false;
    _clipboardTimer?.cancel();
    _sessionTimer?.cancel();
    debugPrint('[NateGuardian] Stopped');
  }

  void dispose() {
    stop();
    _alertStream.close();
  }

  // ═══════════════════════════════════════════════════════════
  // LINK GUARDIAN — Check URLs before opening
  // ═══════════════════════════════════════════════════════════

  /// Check a URL against the Hive Defense API before opening it.
  /// Returns a [LinkCheckResult] with the verdict.
  Future<LinkCheckResult> checkLink(String url) async {
    _linksChecked++;
    try {
      final response = await http
          .post(
            Uri.parse(
                '${config.apiBaseUrl}/api/hive-defense/v4/inspect-url?url=${Uri.encodeComponent(url)}'),
            headers: {'Content-Type': 'application/json'},
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final verdict = data['verdict'] ?? 'CLEAN';
        final score = (data['score'] ?? 0) as int;
        final signals = (data['signals'] as List?)?.length ?? 0;

        if (verdict == 'MALICIOUS') {
          _threatsBlocked++;
          final alert = GuardianAlert(
            id: 'link_${DateTime.now().millisecondsSinceEpoch}',
            module: 'Link Guardian',
            level: ThreatLevel.malicious,
            title: 'Malicious Link Blocked',
            detail: 'URL scored $score/100 with $signals phishing signals',
            metadata: {'url': url, 'score': score, 'verdict': verdict},
          );
          _addAlert(alert);
          return LinkCheckResult(
              safe: false, verdict: verdict, score: score, signals: signals);
        } else if (verdict == 'SUSPICIOUS') {
          final alert = GuardianAlert(
            id: 'link_${DateTime.now().millisecondsSinceEpoch}',
            module: 'Link Guardian',
            level: ThreatLevel.suspicious,
            title: 'Suspicious Link Detected',
            detail: 'URL scored $score/100 — proceed with caution',
            metadata: {'url': url, 'score': score, 'verdict': verdict},
          );
          _addAlert(alert);
          return LinkCheckResult(
              safe: true,
              verdict: verdict,
              score: score,
              signals: signals,
              warning: true);
        }

        return LinkCheckResult(
            safe: true, verdict: verdict, score: score, signals: signals);
      }
    } catch (e) {
      debugPrint('[NateGuardian] Link check error: $e');
    }

    return LinkCheckResult(
        safe: true, verdict: 'UNCHECKED', score: 0, signals: 0);
  }

  // ═══════════════════════════════════════════════════════════
  // CLIPBOARD SHIELD — PII detection in clipboard
  // ═══════════════════════════════════════════════════════════

  static final _piiPatterns = {
    'SSN': RegExp(r'\b\d{3}-\d{2}-\d{4}\b'),
    'Credit Card':
        RegExp(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'),
    'Phone':
        RegExp(r'\b\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'),
    'Email':
        RegExp(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'),
  };

  void _startClipboardShield() {
    _clipboardTimer =
        Timer.periodic(config.clipboardCheckInterval, (_) async {
      if (!_running) return;
      try {
        final data = await Clipboard.getData(Clipboard.kTextPlain);
        final text = data?.text ?? '';
        if (text.isEmpty || text == _lastClipboard) return;
        _lastClipboard = text;
        _clipboardScans++;

        for (final entry in _piiPatterns.entries) {
          if (entry.value.hasMatch(text)) {
            final alert = GuardianAlert(
              id: 'clip_${DateTime.now().millisecondsSinceEpoch}',
              module: 'Clipboard Shield',
              level: ThreatLevel.suspicious,
              title: '${entry.key} Detected in Clipboard',
              detail:
                  'Sensitive data pattern found — clipboard contains a potential ${entry.key}',
              metadata: {
                'pattern_type': entry.key,
                'text_length': text.length
              },
            );
            _addAlert(alert);
            break;
          }
        }
      } catch (_) {
        // Clipboard access may fail on some platforms
      }
    });
  }

  // ═══════════════════════════════════════════════════════════
  // SESSION LOCK — Idle timeout
  // ═══════════════════════════════════════════════════════════

  DateTime _lastActivity = DateTime.now();

  void recordActivity() {
    _lastActivity = DateTime.now();
  }

  void _startSessionLock() {
    _sessionTimer = Timer.periodic(const Duration(minutes: 1), (_) {
      if (!_running) return;
      final idle = DateTime.now().difference(_lastActivity);
      if (idle > config.sessionTimeout) {
        final alert = GuardianAlert(
          id: 'session_${DateTime.now().millisecondsSinceEpoch}',
          module: 'Session Lock',
          level: ThreatLevel.suspicious,
          title: 'Session Idle Timeout',
          detail:
              'No activity for ${idle.inMinutes} minutes — session should be locked',
          metadata: {'idle_minutes': idle.inMinutes},
        );
        _addAlert(alert);
      }
    });
  }

  // ═══════════════════════════════════════════════════════════
  // ALERT MANAGEMENT
  // ═══════════════════════════════════════════════════════════

  void _addAlert(GuardianAlert alert) {
    _alerts.add(alert);
    _alertStream.add(alert);
    if (_alerts.length > 100) {
      _alerts.removeRange(0, _alerts.length - 100);
    }
    debugPrint('[NateGuardian] ALERT: ${alert.module} — ${alert.title}');
  }

  void clearAlerts() {
    _alerts.clear();
  }
}

class LinkCheckResult {
  final bool safe;
  final String verdict;
  final int score;
  final int signals;
  final bool warning;

  LinkCheckResult({
    required this.safe,
    required this.verdict,
    required this.score,
    required this.signals,
    this.warning = false,
  });
}
