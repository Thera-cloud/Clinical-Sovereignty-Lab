// =============================================================================
// LIMINAL PRESENCE SERVICE — Core service for Liminal Presence feature
//
// Manages enabled platforms, active sessions, conversation memory, and
// WebSocket-backed recall/processing. © 2026 Clinical Sovereignty Lab.
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/app_config.dart';

// =============================================================================
// MODELS
// =============================================================================

class LiminalSession {
  final String id;
  final String platform;
  final String contactAlias;
  final int messageCount;
  final DateTime? startedAt;

  LiminalSession({
    required this.id,
    required this.platform,
    required this.contactAlias,
    this.messageCount = 0,
    this.startedAt,
  });

  factory LiminalSession.fromJson(Map<String, dynamic> json) {
    return LiminalSession(
      id: json['id']?.toString() ?? '',
      platform: json['platform']?.toString() ?? 'sms',
      contactAlias: json['contact_alias']?.toString() ?? json['contactAlias']?.toString() ?? '',
      messageCount: (json['message_count'] as int?) ?? (json['messageCount'] as int?) ?? 0,
      startedAt: json['started_at'] != null
          ? DateTime.tryParse(json['started_at'].toString())
          : json['startedAt'] != null
              ? DateTime.tryParse(json['startedAt'].toString())
              : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'platform': platform,
        'contact_alias': contactAlias,
        'message_count': messageCount,
        'started_at': startedAt?.toIso8601String(),
      };
}

// =============================================================================
// LIMINAL PRESENCE SERVICE
// =============================================================================

/// ChangeNotifier managing Liminal Presence: platforms, sessions, conversation
/// memory, and WebSocket-backed recall/process.
class LiminalPresenceService with ChangeNotifier {
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  String? _token;
  String? _userId;

  final Set<String> _enabledPlatforms = {'sms'};
  final List<LiminalSession> _activeSessions = [];
  final Map<String, List<String>> _conversationMemory = {};
  List<Map<String, dynamic>> _recallCache = [];
  bool _wsConnected = false;
  String? _lastError;

  /// Which messaging platforms are active for coaching.
  Set<String> get enabledPlatforms => Set.unmodifiable(_enabledPlatforms);

  /// Active liminal sessions with contact alias, platform, message count.
  List<LiminalSession> get activeSessions => List.unmodifiable(_activeSessions);

  /// Conversation history keyed by contact alias.
  Map<String, List<String>> get conversationMemory =>
      Map.unmodifiable(_conversationMemory.map((k, v) => MapEntry(k, List.unmodifiable(v))));

  /// Last error message, if any.
  String? get lastError => _lastError;

  /// Whether the WebSocket is connected.
  bool get wsConnected => _wsConnected;

  static const _allowedPlatforms = [
    'sms',
    'facebook_messenger',
    'linkedin',
    'x',
    'instagram',
  ];

  /// Initialize with auth token and user ID. Call before using recall/process.
  void initialize({required String token, required String userId}) {
    _token = token;
    _userId = userId;
    _connect();
  }

  void _connect() {
    if (_token == null || _userId == null) return;

    _channel?.sink.close();
    _channel = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
    _subscription?.cancel();
    _subscription = _channel!.stream.listen(
      _onMessage,
      onError: (e) {
        _wsConnected = false;
        _lastError = 'Connection error: $e';
        notifyListeners();
      },
      onDone: () {
        _wsConnected = false;
        notifyListeners();
      },
    );
    _channel!.sink.add(jsonEncode({
      'type': 'auth',
      'token': _token,
      'hardware_id': _userId,
    }));
  }

  void _onMessage(dynamic raw) {
    try {
      final data = jsonDecode(raw.toString()) as Map<String, dynamic>;
      final type = data['type'] as String? ?? '';

      switch (type) {
        case 'auth_success':
          _wsConnected = true;
          _lastError = null;
          notifyListeners();
          break;
        case 'auth_failed':
          _wsConnected = false;
          _lastError = 'Authentication failed.';
          notifyListeners();
          break;
        case 'liminal_recall_response':
          final sessions = data['sessions'];
          _recallCache = sessions is List
              ? (sessions as List<dynamic>)
                  .map<Map<String, dynamic>>((e) => Map<String, dynamic>.from(e as Map))
                  .toList()
              : <Map<String, dynamic>>[];
          notifyListeners();
          break;
        case 'error':
          _lastError = data['message']?.toString() ?? 'Unknown error';
          notifyListeners();
          break;
      }
    } catch (_) {}
  }

  /// Enable a platform for coaching.
  void enablePlatform(String platform) {
    final p = platform.toLowerCase().replaceAll(' ', '_');
    if (_allowedPlatforms.contains(p)) {
      _enabledPlatforms.add(p);
      notifyListeners();
    }
  }

  /// Disable a platform.
  void disablePlatform(String platform) {
    final p = platform.toLowerCase().replaceAll(' ', '_');
    _enabledPlatforms.remove(p);
    notifyListeners();
  }

  /// Process conversation text and send to backend via WebSocket.
  /// Uses liminal_conversation or similar message type if supported.
  Future<void> processConversation({
    required String platform,
    required String conversationText,
    required String contactAlias,
  }) async {
    if (!_wsConnected || _token == null) {
      _lastError = 'Not connected. Call initialize() first.';
      notifyListeners();
      return;
    }

    final p = platform.toLowerCase().replaceAll(' ', '_');
    if (!_allowedPlatforms.contains(p)) {
      _lastError = 'Unsupported platform: $platform';
      notifyListeners();
      return;
    }

    _conversationMemory.putIfAbsent(contactAlias, () => []);
    _conversationMemory[contactAlias]!.add(conversationText);
    notifyListeners();

    try {
      _channel?.sink.add(jsonEncode({
        'type': 'liminal_conversation',
        'platform': p,
        'contact_alias': contactAlias,
        'conversation_text': conversationText,
      }));
    } catch (e) {
      _lastError = 'Failed to send: $e';
      notifyListeners();
    }
  }

  /// Send liminal_recall_request and return cached sessions.
  Future<List<Map<String, dynamic>>> recallConversation(String contactAlias) async {
    if (!_wsConnected || _token == null) {
      _lastError = 'Not connected. Call initialize() first.';
      notifyListeners();
      return [];
    }

    _recallCache = [];
    _channel?.sink.add(jsonEncode({
      'type': 'liminal_recall_request',
      'contact_alias': contactAlias,
    }));

    await Future.delayed(const Duration(milliseconds: 500));
    for (var i = 0; i < 20; i++) {
      await Future.delayed(const Duration(milliseconds: 200));
      if (_recallCache.isNotEmpty) break;
    }

    return List.from(_recallCache);
  }

  /// Create a new session.
  void startSession(String platform, String contactAlias) {
    final p = platform.toLowerCase().replaceAll(' ', '_');
    if (!_allowedPlatforms.contains(p)) return;

    final id = '${contactAlias}_${DateTime.now().millisecondsSinceEpoch}';
    final session = LiminalSession(
      id: id,
      platform: p,
      contactAlias: contactAlias,
      messageCount: 0,
      startedAt: DateTime.now(),
    );
    _activeSessions.add(session);
    notifyListeners();
  }

  /// End a session by ID.
  void endSession(String sessionId) {
    _activeSessions.removeWhere((s) => s.id == sessionId);
    notifyListeners();
  }

  /// Increment message count for a session.
  void incrementMessageCount(String sessionId) {
    final idx = _activeSessions.indexWhere((s) => s.id == sessionId);
    if (idx < 0) return;
    // LiminalSession is immutable; replace with updated copy
    final s = _activeSessions[idx];
    _activeSessions[idx] = LiminalSession(
      id: s.id,
      platform: s.platform,
      contactAlias: s.contactAlias,
      messageCount: s.messageCount + 1,
      startedAt: s.startedAt,
    );
    notifyListeners();
  }

  /// Disconnect and clean up.
  void dispose() {
    _subscription?.cancel();
    _channel?.sink.close();
  }
}
