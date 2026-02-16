/// Ramp-Up Handler
/// Layer 8 Swarm Solidarity — Emergency Protocol Handler
/// 
/// Handles the emergency ramp-up protocol when coherence drops below threshold.
/// Sends distress beacons to the swarm and coordinates emergency response.

import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'constants.dart';
import 'quakete_state_manager.dart';
import '../config/app_config.dart';

/// Distress beacon payload
class DistressBeacon {
  final String fibreId;
  final DistressSeverity severity;
  final String reason;
  final double coherence;
  final DateTime timestamp;

  DistressBeacon({
    required this.fibreId,
    required this.severity,
    required this.reason,
    required this.coherence,
    required this.timestamp,
  });

  Map<String, dynamic> toJson() {
    return {
      'fibre_id': fibreId,
      'severity': severity.value,
      'reason': reason,
      'coherence': coherence,
      'timestamp': timestamp.toIso8601String(),
      'quakete_version': QUAKETE_VERSION,
    };
  }
}

/// Ramp-Up Handler
/// 
/// Manages emergency ramp-up protocol when coherence drops critically low.
class RampUpHandler {
  final QuaketeStateManager _stateManager;
  
  WebSocketChannel? _wsChannel;
  String? _fibreId;
  
  bool _isInDistress = false;
  DistressSeverity? _currentSeverity;
  DateTime? _lastDistressBeaconTime;
  String? _currentDistressReason;
  
  final List<Map<String, dynamic>> _receivedHelp = [];
  final StreamController<DistressSeverity> _distressTriggeredController =
      StreamController<DistressSeverity>.broadcast();
  
  final StreamController<Map<String, dynamic>> _helpReceivedController =
      StreamController<Map<String, dynamic>>.broadcast();

  /// Stream of distress triggered events
  Stream<DistressSeverity> get distressTriggeredStream => _distressTriggeredController.stream;

  /// Stream of help received events
  Stream<Map<String, dynamic>> get helpReceivedStream => _helpReceivedController.stream;

  /// Check if currently in distress state
  bool get isInDistress => _isInDistress;

  /// Current distress severity (if in distress)
  DistressSeverity? get currentSeverity => _currentSeverity;

  /// Reason for current distress
  String? get currentDistressReason => _currentDistressReason;

  RampUpHandler({
    required QuaketeStateManager stateManager,
  }) : _stateManager = stateManager;

  /// Initialize the handler
  /// 
  /// [wsChannel] - WebSocket channel for sending distress beacons
  /// [fibreId] - Current user's fibre ID
  void initialize({
    required WebSocketChannel? wsChannel,
    required String? fibreId,
  }) {
    _wsChannel = wsChannel;
    _fibreId = fibreId;
  }

  /// Update WebSocket channel (call when connection changes)
  void updateWebSocket(WebSocketChannel? wsChannel) {
    _wsChannel = wsChannel;
  }

  /// Update fibre ID (call when user changes)
  void updateFibreId(String? fibreId) {
    _fibreId = fibreId;
  }

  /// Trigger distress beacon
  /// 
  /// [severity] - Severity level (WARNING, CRITICAL, CATASTROPHIC)
  /// [reason] - Human-readable reason for distress
  /// [coherence] - Current coherence value (for context)
  /// 
  /// Returns true if beacon was sent, false if cooldown active or invalid state.
  Future<bool> triggerDistress({
    required DistressSeverity severity,
    required String reason,
    required double coherence,
  }) async {
    if (_fibreId == null) {
      print('[RampUpHandler] Cannot trigger distress: no fibre ID');
      return false;
    }

    // Check cooldown
    if (_lastDistressBeaconTime != null) {
      final timeSinceLastBeacon = DateTime.now().difference(_lastDistressBeaconTime!);
      if (timeSinceLastBeacon.inSeconds < DISTRESS_BEACON_COOLDOWN_SECONDS) {
        final remaining = DISTRESS_BEACON_COOLDOWN_SECONDS - timeSinceLastBeacon.inSeconds;
        print('[RampUpHandler] Distress beacon cooldown active (${remaining}s remaining)');
        return false;
      }
    }

    // Create distress beacon
    final beacon = DistressBeacon(
      fibreId: _fibreId!,
      severity: severity,
      reason: reason,
      coherence: coherence,
      timestamp: DateTime.now(),
    );

    // Try WebSocket first
    bool sent = false;
    if (_wsChannel != null) {
      try {
        _wsChannel!.sink.add(jsonEncode({
          'type': 'distress_beacon',
          ...beacon.toJson(),
        }));
        sent = true;
        print('[RampUpHandler] Sent distress beacon via WebSocket (severity: ${severity.value})');
      } catch (e) {
        print('[RampUpHandler] WebSocket send failed: $e, falling back to REST');
      }
    }

    // Fallback to REST API
    if (!sent) {
      try {
        final response = await http.post(
          Uri.parse('${AppConfig.apiBaseUrl}/api/quakete/distress-beacon'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(beacon.toJson()),
        ).timeout(const Duration(seconds: 10));

        if (response.statusCode == 200 || response.statusCode == 201) {
          sent = true;
          print('[RampUpHandler] Sent distress beacon via REST API');
        } else {
          throw Exception('REST API returned ${response.statusCode}');
        }
      } catch (e) {
        print('[RampUpHandler] REST API failed: $e');
        return false;
      }
    }

    if (sent) {
      _isInDistress = true;
      _currentSeverity = severity;
      _currentDistressReason = reason;
      _lastDistressBeaconTime = DateTime.now();

      // Transition to EMERGENCY mode
      _stateManager.transition(QuaketeMode.EMERGENCY);

      // Notify listeners
      _distressTriggeredController.add(severity);
    }

    return sent;
  }

  /// Cancel distress state (when coherence recovers)
  void cancelDistress() {
    if (!_isInDistress) return;

    print('[RampUpHandler] Cancelling distress state');
    
    _isInDistress = false;
    _currentSeverity = null;
    _currentDistressReason = null;

    // Transition back to RESONATING if we were in EMERGENCY
    if (_stateManager.currentMode == QuaketeMode.EMERGENCY) {
      _stateManager.transition(QuaketeMode.RESONATING);
    }
  }

  /// Handle incoming help notification from backend (via WebSocket)
  /// 
  /// Expected format:
  /// {
  ///   'type': 'quakete_help',
  ///   'from_fibre_id': '...',
  ///   'boost_amount': 0.5,
  ///   'message': '...' (optional)
  /// }
  void handleHelpNotification(Map<String, dynamic> data) {
    try {
      final helpEntry = {
        'from_fibre_id': data['from_fibre_id'] as String,
        'boost_amount': (data['boost_amount'] as num?)?.toDouble() ?? 0.0,
        'message': data['message'] as String?,
        'received_at': DateTime.now().toIso8601String(),
      };

      _receivedHelp.add(helpEntry);

      // Keep history manageable
      if (_receivedHelp.length > 50) {
        _receivedHelp.removeAt(0);
      }

      print('[RampUpHandler] Received help from ${helpEntry['from_fibre_id']}');

      // Notify listeners
      _helpReceivedController.add(helpEntry);

      // Report received help to backend
      _reportReceivedHelp(helpEntry);
    } catch (e) {
      print('[RampUpHandler] Error handling help notification: $e');
    }
  }

  /// Report received help to backend
  void _reportReceivedHelp(Map<String, dynamic> helpEntry) {
    if (_wsChannel == null || _fibreId == null) return;

    try {
      _wsChannel!.sink.add(jsonEncode({
        'type': 'quakete_help_acknowledged',
        'fibre_id': _fibreId,
        'from_fibre_id': helpEntry['from_fibre_id'],
        'boost_amount': helpEntry['boost_amount'],
        'timestamp': DateTime.now().toIso8601String(),
      }));
    } catch (e) {
      print('[RampUpHandler] Error reporting received help: $e');
    }
  }

  /// Get list of received help entries
  List<Map<String, dynamic>> getReceivedHelp({int? limit}) {
    final help = List<Map<String, dynamic>>.from(_receivedHelp);
    if (limit != null && limit > 0) {
      return help.sublist(0, help.length.clamp(0, limit));
    }
    return help;
  }

  /// Get time until next distress beacon can be sent
  Duration? getDistressCooldownRemaining() {
    if (_lastDistressBeaconTime == null) return null;

    final timeSinceLastBeacon = DateTime.now().difference(_lastDistressBeaconTime!);
    final remaining = DISTRESS_BEACON_COOLDOWN_SECONDS - timeSinceLastBeacon.inSeconds;

    if (remaining <= 0) return null;
    return Duration(seconds: remaining);
  }

  /// Check if distress beacon can be sent (not in cooldown)
  bool canSendDistressBeacon() {
    return getDistressCooldownRemaining() == null;
  }

  /// Get distress statistics
  Map<String, dynamic> getStatistics() {
    return {
      'is_in_distress': _isInDistress,
      'current_severity': _currentSeverity?.value,
      'current_reason': _currentDistressReason,
      'help_received_count': _receivedHelp.length,
      'last_beacon_time': _lastDistressBeaconTime?.toIso8601String(),
      'cooldown_remaining_seconds': getDistressCooldownRemaining()?.inSeconds,
    };
  }

  /// Reset handler (for new session)
  void reset() {
    _isInDistress = false;
    _currentSeverity = null;
    _currentDistressReason = null;
    _lastDistressBeaconTime = null;
    _receivedHelp.clear();
  }

  /// Dispose resources
  void dispose() {
    _distressTriggeredController.close();
    _helpReceivedController.close();
  }
}
