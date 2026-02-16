/// Quakete State Manager
/// Layer 8 Swarm Solidarity — State Machine
/// 
/// Manages the 6-state operational mode machine for Quakete solidarity protocol.
/// Enforces valid state transitions and broadcasts state changes to listeners.

import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'constants.dart';
import '../config/app_config.dart';

/// Quakete state transition rules
/// 
/// Valid transitions:
/// - DORMANT → LISTENING (activation)
/// - LISTENING → RESONATING (normal operation)
/// - LISTENING → EMERGENCY (crisis detected)
/// - RESONATING → TRANSFERRING (energy transfer initiated)
/// - RESONATING → EMERGENCY (crisis detected)
/// - TRANSFERRING → RESONATING (transfer complete)
/// - EMERGENCY → RESONATING (crisis resolved)
/// - EMERGENCY → MEMORIAL (member lost)
/// - MEMORIAL → DORMANT (memorial complete)
class QuaketeStateManager {
  QuaketeMode _currentMode = QuaketeMode.DORMANT;
  final StreamController<QuaketeMode> _modeController =
      StreamController<QuaketeMode>.broadcast();
  
  WebSocketChannel? _wsChannel;
  String? _fibreId;

  /// Current operational mode
  QuaketeMode get currentMode => _currentMode;

  /// Stream of mode changes for reactive updates
  Stream<QuaketeMode> get modeStream => _modeController.stream;

  /// Initialize the state manager
  /// 
  /// [wsChannel] - WebSocket channel for sending mode updates to backend
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

  /// Check if a transition to [newMode] is valid from current state
  bool canTransition(QuaketeMode newMode) {
    if (_currentMode == newMode) {
      return true; // Already in this state
    }

    switch (_currentMode) {
      case QuaketeMode.DORMANT:
        // Can only activate to LISTENING
        return newMode == QuaketeMode.LISTENING;

      case QuaketeMode.LISTENING:
        // Can go to RESONATING (normal) or EMERGENCY (crisis)
        return newMode == QuaketeMode.RESONATING ||
               newMode == QuaketeMode.EMERGENCY;

      case QuaketeMode.RESONATING:
        // Can go to TRANSFERRING (donating energy) or EMERGENCY (crisis)
        return newMode == QuaketeMode.TRANSFERRING ||
               newMode == QuaketeMode.EMERGENCY;

      case QuaketeMode.TRANSFERRING:
        // Can only return to RESONATING after transfer
        return newMode == QuaketeMode.RESONATING;

      case QuaketeMode.EMERGENCY:
        // Can resolve to RESONATING or enter MEMORIAL if member lost
        return newMode == QuaketeMode.RESONATING ||
               newMode == QuaketeMode.MEMORIAL;

      case QuaketeMode.MEMORIAL:
        // Can only return to DORMANT after memorial
        return newMode == QuaketeMode.DORMANT;
    }
  }

  /// Transition to a new mode
  /// 
  /// Returns true if transition was successful, false if invalid.
  /// Automatically sends mode update to backend via WebSocket.
  bool transition(QuaketeMode newMode) {
    if (!canTransition(newMode)) {
      print('[QuaketeStateManager] Invalid transition: ${_currentMode.value} → ${newMode.value}');
      return false;
    }

    final previousMode = _currentMode;
    _currentMode = newMode;
    
    print('[QuaketeStateManager] Mode transition: ${previousMode.value} → ${newMode.value}');
    
    // Broadcast state change
    _modeController.add(_currentMode);
    
    // Send update to backend
    _sendModeUpdateToBackend();
    
    return true;
  }

  /// Get behavior description for current mode
  String getCurrentBehavior() {
    switch (_currentMode) {
      case QuaketeMode.DORMANT:
        return 'No emissions, no scanning, inactive state';
      case QuaketeMode.LISTENING:
        return 'Passive trail reception, monitoring swarm';
      case QuaketeMode.RESONATING:
        return 'Active trail emission + reception, normal operation';
      case QuaketeMode.TRANSFERRING:
        return 'Energy transfer in progress';
      case QuaketeMode.EMERGENCY:
        return 'Ramp-up protocol active, requesting swarm assistance';
      case QuaketeMode.MEMORIAL:
        return 'Encoding lost Fibre wisdom, honoring departed members';
    }
  }

  /// Check if current mode allows trail emission
  bool canEmitTrails() {
    return _currentMode == QuaketeMode.LISTENING ||
           _currentMode == QuaketeMode.RESONATING ||
           _currentMode == QuaketeMode.TRANSFERRING ||
           _currentMode == QuaketeMode.EMERGENCY;
  }

  /// Check if current mode allows trail reception
  bool canReceiveTrails() {
    return _currentMode == QuaketeMode.LISTENING ||
           _currentMode == QuaketeMode.RESONATING ||
           _currentMode == QuaketeMode.TRANSFERRING ||
           _currentMode == QuaketeMode.EMERGENCY;
  }

  /// Check if current mode allows energy transfer
  bool canTransferEnergy() {
    return _currentMode == QuaketeMode.RESONATING ||
           _currentMode == QuaketeMode.TRANSFERRING;
  }

  /// Send mode update to backend via WebSocket
  void _sendModeUpdateToBackend() {
    if (_wsChannel == null || _fibreId == null) {
      print('[QuaketeStateManager] Cannot send mode update: missing WebSocket or fibreId');
      return;
    }

    try {
      _wsChannel!.sink.add(jsonEncode({
        'type': 'quakete_mode_update',
        'fibre_id': _fibreId,
        'mode': _currentMode.value,
        'timestamp': DateTime.now().toIso8601String(),
      }));
    } catch (e) {
      print('[QuaketeStateManager] Error sending mode update: $e');
    }
  }

  /// Reset to DORMANT state (for logout or deactivation)
  void reset() {
    _currentMode = QuaketeMode.DORMANT;
    _modeController.add(_currentMode);
    _sendModeUpdateToBackend();
  }

  /// Dispose resources
  void dispose() {
    _modeController.close();
  }
}
