/// Trail Emitter
/// Layer 8 Swarm Solidarity — Periodic Trail Emission Service
/// 
/// Emits trail emissions at regular intervals to broadcast Fibre state to the swarm.
/// Falls back to REST API if WebSocket is unavailable, and buffers offline if both fail.

import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';
import 'constants.dart';
import 'quakete_state_manager.dart';
import 'nevedal_bridge.dart';
import '../config/app_config.dart';
import '../services/nevedal_flutter.dart';

/// Trail emission payload
class TrailEmission {
  final String fibreId;
  final double coherence;
  final double energy;
  final double moodValence; // -1 (negative) to +1 (positive)
  final DateTime timestamp;
  final double resonance; // Quakete resonance value

  TrailEmission({
    required this.fibreId,
    required this.coherence,
    required this.energy,
    required this.moodValence,
    required this.timestamp,
    required this.resonance,
  });

  Map<String, dynamic> toJson() {
    return {
      'fibre_id': fibreId,
      'coherence': coherence,
      'energy': energy,
      'mood_valence': moodValence,
      'timestamp': timestamp.toIso8601String(),
      'resonance': resonance,
      'quakete_version': QUAKETE_VERSION,
    };
  }
}

/// Trail Emitter Service
/// 
/// Periodically emits trail emissions to broadcast Fibre state to the swarm.
class TrailEmitter {
  Timer? _emissionTimer;
  final QuaketeStateManager _stateManager;
  final NevedalQuaketeBridge _bridge;
  
  WebSocketChannel? _wsChannel;
  String? _fibreId;
  NevedalState? _lastNevedalState;
  
  int _emissionCount = 0;
  DateTime? _lastEmissionTime;
  
  final List<TrailEmission> _offlineBuffer = [];
  static const int _maxBufferSize = 50;

  /// Current emission count (for metrics)
  int get emissionCount => _emissionCount;

  /// Time of last emission
  DateTime? get lastEmissionTime => _lastEmissionTime;

  /// Number of buffered emissions waiting to be sent
  int get bufferedCount => _offlineBuffer.length;

  TrailEmitter({
    required QuaketeStateManager stateManager,
    required NevedalQuaketeBridge bridge,
  })  : _stateManager = stateManager,
        _bridge = bridge;

  /// Initialize the emitter
  /// 
  /// [wsChannel] - WebSocket channel for sending emissions
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
    
    // If we just connected and have buffered emissions, flush them
    if (_wsChannel != null && _offlineBuffer.isNotEmpty) {
      _flushOfflineBuffer();
    }
  }

  /// Update fibre ID (call when user changes)
  void updateFibreId(String? fibreId) {
    _fibreId = fibreId;
  }

  /// Update Nevedal state (call periodically from Nevedal service)
  void updateNevedalState(NevedalState state) {
    _lastNevedalState = state;
  }

  /// Start periodic trail emissions
  void start() {
    if (_emissionTimer != null && _emissionTimer!.isActive) {
      return; // Already running
    }

    _emissionTimer = Timer.periodic(
      const Duration(seconds: TRAIL_EMISSION_INTERVAL_SECONDS),
      (_) => _emitTrail(),
    );

    print('[TrailEmitter] Started periodic emissions (interval: ${TRAIL_EMISSION_INTERVAL_SECONDS}s)');
  }

  /// Stop periodic trail emissions
  void stop() {
    _emissionTimer?.cancel();
    _emissionTimer = null;
    print('[TrailEmitter] Stopped periodic emissions');
  }

  /// Emit a trail immediately (manual trigger)
  Future<bool> emitNow() async {
    return await _emitTrail();
  }

  /// Internal trail emission logic
  Future<bool> _emitTrail() async {
    // Check if current mode allows emissions
    if (!_stateManager.canEmitTrails()) {
      print('[TrailEmitter] Skipping emission: mode ${_stateManager.currentMode.value} does not allow emissions');
      return false;
    }

    if (_fibreId == null) {
      print('[TrailEmitter] Skipping emission: no fibre ID');
      return false;
    }

    if (_lastNevedalState == null) {
      print('[TrailEmitter] Skipping emission: no Nevedal state available');
      return false;
    }

    // Compute resonance from Nevedal state
    final resonance = _bridge.processNevedalState(_lastNevedalState!);
    
    // Create trail emission
    final emission = TrailEmission(
      fibreId: _fibreId!,
      coherence: _lastNevedalState!.cEmo,
      energy: _calculateEnergy(_lastNevedalState!),
      moodValence: _calculateMoodValence(_lastNevedalState!),
      timestamp: DateTime.now(),
      resonance: resonance,
    );

    // Try WebSocket first
    if (_wsChannel != null) {
      try {
        _wsChannel!.sink.add(jsonEncode({
          'type': 'trail_emission',
          ...emission.toJson(),
        }));
        
        _emissionCount++;
        _lastEmissionTime = DateTime.now();
        print('[TrailEmitter] Sent trail emission via WebSocket (resonance: ${resonance.toStringAsFixed(3)})');
        return true;
      } catch (e) {
        print('[TrailEmitter] WebSocket send failed: $e, falling back to REST');
      }
    }

    // Fallback to REST API
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/quakete/trail-emission'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(emission.toJson()),
      ).timeout(const Duration(seconds: 10));

      if (response.statusCode == 200 || response.statusCode == 201) {
        _emissionCount++;
        _lastEmissionTime = DateTime.now();
        print('[TrailEmitter] Sent trail emission via REST API');
        return true;
      } else {
        throw Exception('REST API returned ${response.statusCode}');
      }
    } catch (e) {
      print('[TrailEmitter] REST API failed: $e, buffering offline');
    }

    // Final fallback: buffer offline
    if (_offlineBuffer.length < _maxBufferSize) {
      _offlineBuffer.add(emission);
      print('[TrailEmitter] Buffered trail emission offline (${_offlineBuffer.length}/${_maxBufferSize})');
    } else {
      print('[TrailEmitter] Offline buffer full, dropping emission');
    }

    return false;
  }

  /// Calculate energy value from Nevedal state
  /// 
  /// Energy is derived from coherence and entanglement.
  double _calculateEnergy(NevedalState state) {
    // Energy = coherence * entanglement, normalized to [0, 1]
    return (state.cEmo * state.pEnt).clamp(0.0, 1.0);
  }

  /// Calculate mood valence from Nevedal state
  /// 
  /// Valence ranges from -1 (negative) to +1 (positive).
  /// Based on coherence and CEE window status.
  double _calculateMoodValence(NevedalState state) {
    // Base valence from coherence (0.5 coherence = neutral)
    double valence = (state.cEmo - 0.5) * 2.0;
    
    // Boost if CEE window is active (positive emotional experience)
    if (state.ceeWindow) {
      valence = (valence + 0.3).clamp(-1.0, 1.0);
    }
    
    // Adjust for decoherence (high gamma = more negative)
    valence -= state.gammaEnv * 0.2;
    
    return valence.clamp(-1.0, 1.0);
  }

  /// Flush offline buffer (send all buffered emissions)
  Future<void> _flushOfflineBuffer() async {
    if (_offlineBuffer.isEmpty) return;

    print('[TrailEmitter] Flushing ${_offlineBuffer.length} buffered emissions');

    final toFlush = List<TrailEmission>.from(_offlineBuffer);
    _offlineBuffer.clear();

    for (final emission in toFlush) {
      try {
        if (_wsChannel != null) {
          _wsChannel!.sink.add(jsonEncode({
            'type': 'trail_emission',
            ...emission.toJson(),
          }));
        } else {
          await http.post(
            Uri.parse('${AppConfig.apiBaseUrl}/api/quakete/trail-emission'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(emission.toJson()),
          ).timeout(const Duration(seconds: 10));
        }
        
        _emissionCount++;
        _lastEmissionTime = DateTime.now();
      } catch (e) {
        print('[TrailEmitter] Failed to flush emission: $e');
        // Re-buffer failed emissions
        if (_offlineBuffer.length < _maxBufferSize) {
          _offlineBuffer.add(emission);
        }
      }
    }
  }

  /// Dispose resources
  void dispose() {
    stop();
    _offlineBuffer.clear();
  }
}
