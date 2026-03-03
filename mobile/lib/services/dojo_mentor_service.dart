/// LITTLE NATE — DOJO Mentor Service
/// Orchestrates the DOJO Mentor during live Zoom coaching sessions.
/// Manages session state, WebSocket messaging, and coaching card feed.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

// =============================================================================
// DATA MODELS
// =============================================================================

/// A single coaching card from Nate in response to transcript or coach question.
class CoachingCard {
  final String content;
  final String type; // 'observation' | 'suggestion' | 'answer' | 'alert'
  final String? dojoLens;
  final DateTime timestamp;

  CoachingCard({
    required this.content,
    required this.type,
    this.dojoLens,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();

  factory CoachingCard.fromMap(Map<String, dynamic> map) {
    return CoachingCard(
      content: (map['content'] ?? '').toString(),
      type: (map['interaction_type'] ?? map['type'] ?? 'observation').toString(),
      dojoLens: map['dojo_lens']?.toString(),
      timestamp: map['timestamp'] != null
          ? DateTime.tryParse(map['timestamp'].toString()) ?? DateTime.now()
          : DateTime.now(),
    );
  }
}

/// Canonical DOJO keys supported by the mentor engine.
const kValidDojos = [
  'therapist',
  'judge',
  'business',
  'mcat',
  'cnc',
  'teacher',
  'project_pm',
];

/// Human-readable labels for DOJO chips.
const kDojoLabels = {
  'therapist': 'Therapist',
  'judge': 'Judge',
  'business': 'Business',
  'mcat': 'MCAT',
  'cnc': 'CNC',
  'teacher': 'Teacher',
  'project_pm': 'Project PM',
};

// =============================================================================
// SERVICE
// =============================================================================

/// Service that orchestrates the DOJO Mentor during live Zoom sessions.
/// Sends and receives WebSocket messages; maintains coaching card feed and state.
class DojoMentorService extends ChangeNotifier {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;

  /// Session identifier for the current mentored session.
  String _sessionId = '';
  String get sessionId => _sessionId;

  /// Active DOJO lenses (therapist, judge, business, etc.).
  List<String> _activeDojos = [];
  List<String> get activeDojos => List.unmodifiable(_activeDojos);

  /// Coaching cards from Nate (observations, suggestions, answers, alerts).
  final List<CoachingCard> _coachingCards = [];
  List<CoachingCard> get coachingCards => List.unmodifiable(_coachingCards);

  /// Whether the overlay is minimized (48x48 avatar).
  bool _isMinimized = false;
  bool get isMinimized => _isMinimized;
  set isMinimized(bool value) {
    if (_isMinimized != value) {
      _isMinimized = value;
      notifyListeners();
    }
  }

  /// Session mode: coach_client, coach_students, judge_debate, lawyer_client.
  String _sessionMode = 'coach_client';
  String get sessionMode => _sessionMode;

  /// Whether a mentor session is active.
  bool get isSessionActive => _sessionId.isNotEmpty && _channel != null;

  // ---------------------------------------------------------------------------
  // DOJO SUBSCRIPTIONS FROM PROFILE
  // ---------------------------------------------------------------------------

  /// Compute which DOJOs are available for this coach from profile_data['dojo_subscriptions'].
  /// Returns list of DOJO keys that have status == 'active'.
  static List<String> availableDojosFromProfile(Map<String, dynamic> profile) {
    final subs = profile['dojo_subscriptions'];
    if (subs == null || subs is! Map) return List.from(kValidDojos);

    final available = <String>[];
    for (final key in kValidDojos) {
      final val = subs[key];
      if (val is Map && (val['status'] ?? '') == 'active') {
        available.add(key);
      } else if (val == true) {
        available.add(key);
      }
    }
    return available.isEmpty ? ['therapist'] : available;
  }

  /// Set the WebSocket channel. Call when overlay mounts with the coach's socket.
  void setChannel(WebSocketChannel? channel) {
    _subscription?.cancel();
    _subscription = null;
    _channel = channel;

    if (channel != null) {
      _subscription = channel.stream.listen(
        _onMessage,
        onError: (e) => debugPrint('[DojoMentorService] WS error: $e'),
        onDone: () {
          _channel = null;
          notifyListeners();
        },
      );
    }
    notifyListeners();
  }

  void _onMessage(dynamic raw) {
    try {
      final data = jsonDecode(raw) as Map<String, dynamic>;
      final type = (data['type'] ?? '').toString();

      if (type == 'dojo_mentor_response') {
        handleMentorResponse(data);
      } else if (type == 'dojo_mentor_started') {
        _sessionId = (data['session_id'] ?? _sessionId).toString();
        final dojos = data['active_dojos'];
        if (dojos is List) {
          _activeDojos = dojos.map((e) => e.toString()).toList();
        }
        notifyListeners();
      } else if (type == 'dojo_mentor_dojo_toggled') {
        final dojo = (data['dojo'] ?? '').toString();
        final active = data['active'] == true;
        if (active && !_activeDojos.contains(dojo)) {
          _activeDojos = [..._activeDojos, dojo];
        } else if (!active && _activeDojos.contains(dojo)) {
          _activeDojos = _activeDojos.where((d) => d != dojo).toList();
        }
        notifyListeners();
      } else if (type == 'dojo_mentor_ended') {
        _sessionId = '';
        notifyListeners();
      }
    } catch (e) {
      debugPrint('[DojoMentorService] Parse error: $e');
    }
  }

  /// Send a message over the WebSocket.
  void _send(Map<String, dynamic> msg) {
    if (_channel == null) return;
    try {
      _channel!.sink.add(jsonEncode(msg));
    } catch (e) {
      debugPrint('[DojoMentorService] Send error: $e');
    }
  }

  // ---------------------------------------------------------------------------
  // PUBLIC API
  // ---------------------------------------------------------------------------

  /// Start a DOJO Mentor session.
  /// [coachUserId] should come from profile['hardware_id'].
  void startSession({
    required String sessionId,
    required List<String> activeDojos,
    String? clientId,
    required String sessionMode,
    String? coachUserId,
  }) {
    if (_channel == null) return;

    _sessionId = sessionId;
    _sessionMode = sessionMode;
    _activeDojos = [
      ...activeDojos.where((d) => kValidDojos.contains(d)),
    ];
    if (_activeDojos.isEmpty) _activeDojos = ['therapist'];

    _send({
      'type': 'dojo_mentor_start',
      'session_id': sessionId,
      'active_dojos': _activeDojos,
      'client_id': clientId,
      'session_mode': sessionMode,
      'coach_user_id': coachUserId,
    });
    notifyListeners();
  }

  /// End the current mentor session.
  void endSession() {
    if (_sessionId.isEmpty || _channel == null) return;
    _send({
      'type': 'dojo_mentor_end',
      'session_id': _sessionId,
    });
    _sessionId = '';
    _coachingCards.clear();
    notifyListeners();
  }

  /// Send a transcript chunk for mentor analysis.
  void sendTranscript(String text) {
    if (_sessionId.isEmpty || text.trim().isEmpty || _channel == null) return;
    _send({
      'type': 'dojo_mentor_transcript',
      'session_id': _sessionId,
      'transcript': text.trim(),
    });
  }

  /// Ask Nate a direct question during the session.
  void askQuestion(String question) {
    if (_sessionId.isEmpty || question.trim().isEmpty || _channel == null) return;
    _send({
      'type': 'dojo_mentor_ask',
      'session_id': _sessionId,
      'question': question.trim(),
    });
  }

  /// Toggle a DOJO lens on/off mid-session.
  void toggleDojo(String dojo, bool active) {
    if (_sessionId.isEmpty || _channel == null) return;
    if (!kValidDojos.contains(dojo)) return;

    _send({
      'type': 'dojo_mentor_toggle_dojo',
      'session_id': _sessionId,
      'dojo': dojo,
      'active': active,
    });

    if (active && !_activeDojos.contains(dojo)) {
      _activeDojos = [..._activeDojos, dojo];
    } else if (!active && _activeDojos.contains(dojo)) {
      _activeDojos = _activeDojos.where((d) => d != dojo).toList();
    }
    notifyListeners();
  }

  /// Handle incoming mentor response; adds a coaching card and notifies listeners.
  void handleMentorResponse(Map<String, dynamic> data) {
    final card = CoachingCard.fromMap({
      'content': data['content'] ?? '',
      'interaction_type': data['interaction_type'] ?? data['type'] ?? 'observation',
      'dojo_lens': data['dojo_lens'],
    });
    _coachingCards.add(card);
    notifyListeners();
  }

  /// Clear coaching cards (e.g. when starting a new segment).
  void clearCards() {
    _coachingCards.clear();
    notifyListeners();
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _subscription = null;
    _channel = null;
    super.dispose();
  }
}
