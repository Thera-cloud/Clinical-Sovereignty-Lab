// =============================================================================
// LITTLE NATE — Biometric Collector & Nevedal Integration
// Version: 1.0
// Date: January 21, 2026
//
// Integrates with VagusEngine to extract voice biometrics and send to
// the Nevedal Engine for quantum emotional coherence computation.
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

// =============================================================================
// NEVEDAL STATE MODEL
// =============================================================================

/// Represents the current Nevedal quantum emotional coherence state
class NevedalState {
  final DateTime timestamp;
  final double cEmo;          // Quantum Emotional Coherence (0-1)
  final double pEnt;          // Emotional Entanglement (0-1)
  final double tTunnel;       // Tunneling Transparency (0-1)
  final double dDistance;     // Interpersonal Distance (0-1)
  final double gammaEnv;      // Decoherence Rate (0-1)
  final double eGJoint;       // Joint Emotional Load (0-1)
  final double tauEmo;        // Coherence Lifetime
  final bool ceeWindow;       // Corrective Emotional Experience active
  final int ceeDuration;      // CEE duration in seconds
  final String interpretation;
  final List<String> recommendations;

  NevedalState({
    required this.timestamp,
    required this.cEmo,
    required this.pEnt,
    required this.tTunnel,
    required this.dDistance,
    required this.gammaEnv,
    required this.eGJoint,
    required this.tauEmo,
    required this.ceeWindow,
    required this.ceeDuration,
    required this.interpretation,
    required this.recommendations,
  });

  factory NevedalState.fromJson(Map<String, dynamic> json) {
    return NevedalState(
      timestamp: DateTime.parse(json['timestamp'] ?? DateTime.now().toIso8601String()),
      cEmo: (json['c_emo'] ?? 0.5).toDouble(),
      pEnt: (json['p_ent'] ?? 0.5).toDouble(),
      tTunnel: (json['t_tunnel'] ?? 0.5).toDouble(),
      dDistance: (json['d_distance'] ?? 0.5).toDouble(),
      gammaEnv: (json['gamma_env'] ?? 0.3).toDouble(),
      eGJoint: (json['e_g_joint'] ?? 0.4).toDouble(),
      tauEmo: (json['tau_emo'] ?? 1.0).toDouble(),
      ceeWindow: json['cee_window'] ?? false,
      ceeDuration: json['cee_duration_seconds'] ?? 0,
      interpretation: json['interpretation'] ?? '',
      recommendations: List<String>.from(json['recommendations'] ?? []),
    );
  }

  factory NevedalState.defaultState() {
    return NevedalState(
      timestamp: DateTime.now(),
      cEmo: 0.5,
      pEnt: 0.5,
      tTunnel: 0.5,
      dDistance: 0.5,
      gammaEnv: 0.3,
      eGJoint: 0.4,
      tauEmo: 1.0,
      ceeWindow: false,
      ceeDuration: 0,
      interpretation: 'Initializing...',
      recommendations: [],
    );
  }

  /// Get color based on coherence level
  Color get coherenceColor {
    if (cEmo >= 0.7) return const Color(0xFF00FF88);  // Green
    if (cEmo >= 0.5) return const Color(0xFFFFD700);  // Gold
    if (cEmo >= 0.3) return const Color(0xFFFF9500);  // Orange
    return const Color(0xFFFF3B3B);  // Red
  }

  /// Get status text
  String get statusText {
    if (ceeWindow) return '🌟 CEE WINDOW';
    if (cEmo >= 0.7) return 'HIGH COHERENCE';
    if (cEmo >= 0.5) return 'MODERATE';
    if (cEmo >= 0.3) return 'LOW';
    return 'MINIMAL';
  }
}

// =============================================================================
// VOICE BIOMETRIC EXTRACTOR (Client-side)
// =============================================================================

/// Extracts basic voice features from audio samples
/// Full analysis is done server-side, this provides quick local estimates
class VoiceBiometricExtractor {
  final List<double> _energyHistory = [];
  final List<double> _pitchHistory = [];
  static const int _historySize = 50;

  /// Process audio samples and extract features
  Map<String, double> processAudioSamples(Uint8List audioData) {
    // Convert bytes to samples (assuming 16-bit PCM)
    final samples = _bytesToSamples(audioData);
    if (samples.isEmpty) return _defaultMetrics();

    // Calculate energy (RMS)
    final energy = _calculateEnergy(samples);
    _energyHistory.add(energy);
    if (_energyHistory.length > _historySize) _energyHistory.removeAt(0);

    // Estimate pitch (simplified)
    final pitch = _estimatePitch(samples);
    if (pitch > 0) {
      _pitchHistory.add(pitch);
      if (_pitchHistory.length > _historySize) _pitchHistory.removeAt(0);
    }

    // Calculate pitch variance
    final pitchVariance = _pitchHistory.length > 5 
        ? _standardDeviation(_pitchHistory) 
        : 20.0;

    // Calculate pause ratio
    final pauseRatio = _calculatePauseRatio(samples, energy);

    // Estimate speech rate from energy fluctuations
    final speechRate = _estimateSpeechRate();

    // Calculate stress index
    final stressIndex = _calculateStressIndex(
      pitch: pitch > 0 ? pitch : 150,
      pitchVariance: pitchVariance,
      speechRate: speechRate,
      pauseRatio: pauseRatio,
    );

    // Calculate warmth index
    final warmthIndex = _calculateWarmthIndex(
      energy: energy,
      pitchVariance: pitchVariance,
      pauseRatio: pauseRatio,
    );

    return {
      'voice_energy': energy,
      'voice_pitch_mean': pitch > 0 ? pitch : 150,
      'voice_pitch_variance': pitchVariance,
      'speech_rate': speechRate,
      'pause_ratio': pauseRatio,
      'voice_stress_index': stressIndex,
      'voice_warmth_index': warmthIndex,
    };
  }

  List<double> _bytesToSamples(Uint8List bytes) {
    if (bytes.length < 2) return [];
    
    final samples = <double>[];
    for (int i = 0; i < bytes.length - 1; i += 2) {
      final sample = bytes[i] | (bytes[i + 1] << 8);
      // Convert to signed 16-bit
      final signedSample = sample > 32767 ? sample - 65536 : sample;
      samples.add(signedSample / 32768.0);  // Normalize to [-1, 1]
    }
    return samples;
  }

  double _calculateEnergy(List<double> samples) {
    if (samples.isEmpty) return -60;
    final sumSquared = samples.fold<double>(0, (sum, s) => sum + s * s);
    final rms = sqrt(sumSquared / samples.length);
    // Convert to dB
    return 20 * log(max(rms, 1e-10)) / ln10;
  }

  double _estimatePitch(List<double> samples) {
    // Simplified autocorrelation-based pitch estimation
    if (samples.length < 512) return 0;

    final n = samples.length;
    double maxCorr = 0;
    int bestLag = 0;

    // Search for pitch between 50 Hz and 500 Hz (assuming 16kHz sample rate)
    final minLag = 32;   // 500 Hz at 16kHz
    final maxLag = 320;  // 50 Hz at 16kHz

    for (int lag = minLag; lag < min(maxLag, n ~/ 2); lag++) {
      double corr = 0;
      for (int i = 0; i < n - lag; i++) {
        corr += samples[i] * samples[i + lag];
      }
      if (corr > maxCorr) {
        maxCorr = corr;
        bestLag = lag;
      }
    }

    if (bestLag > 0 && maxCorr > 0.1) {
      return 16000.0 / bestLag;  // Assuming 16kHz sample rate
    }
    return 0;
  }

  double _calculatePauseRatio(List<double> samples, double avgEnergy) {
    if (samples.isEmpty) return 0.3;
    
    final threshold = pow(10, (avgEnergy - 10) / 20);  // 10 dB below average
    int silentSamples = 0;
    
    for (final s in samples) {
      if (s.abs() < threshold) silentSamples++;
    }
    
    return silentSamples / samples.length;
  }

  double _estimateSpeechRate() {
    if (_energyHistory.length < 10) return 120;
    
    // Count energy peaks (syllables)
    int peaks = 0;
    final avgEnergy = _energyHistory.reduce((a, b) => a + b) / _energyHistory.length;
    
    bool aboveThreshold = false;
    for (final e in _energyHistory) {
      if (e > avgEnergy && !aboveThreshold) {
        peaks++;
        aboveThreshold = true;
      } else if (e < avgEnergy) {
        aboveThreshold = false;
      }
    }
    
    // Convert to words per minute (rough estimate)
    // Assuming each entry represents ~100ms
    final durationMinutes = (_energyHistory.length * 0.1) / 60;
    if (durationMinutes > 0) {
      final syllablesPerMin = peaks / durationMinutes;
      return (syllablesPerMin / 2).clamp(60, 250);  // ~2 syllables per word
    }
    
    return 120;
  }

  double _calculateStressIndex({
    required double pitch,
    required double pitchVariance,
    required double speechRate,
    required double pauseRatio,
  }) {
    double stress = 0;
    
    // Higher pitch = more stress
    stress += ((pitch - 100) / 200).clamp(0, 1) * 0.3;
    
    // Higher pitch variance = more stress
    stress += (pitchVariance / 50).clamp(0, 1) * 0.25;
    
    // Faster speech = more stress
    stress += ((speechRate - 100) / 100).clamp(0, 1) * 0.25;
    
    // Less pauses = more stress
    stress += (1 - pauseRatio).clamp(0, 1) * 0.2;
    
    return stress.clamp(0, 1);
  }

  double _calculateWarmthIndex({
    required double energy,
    required double pitchVariance,
    required double pauseRatio,
  }) {
    double warmth = 0;
    
    // Lower pitch variance = warmer
    warmth += (1 - pitchVariance / 50).clamp(0, 1) * 0.35;
    
    // Moderate energy = warmer (not too loud, not too quiet)
    final energyDiff = (energy + 20).abs();  // Optimal around -20 dB
    warmth += (1 - energyDiff / 30).clamp(0, 1) * 0.3;
    
    // More pauses = warmer (thoughtful)
    warmth += (pauseRatio * 2).clamp(0, 1) * 0.35;
    
    return warmth.clamp(0, 1);
  }

  double _standardDeviation(List<double> values) {
    if (values.isEmpty) return 0;
    final mean = values.reduce((a, b) => a + b) / values.length;
    final sumSquaredDiff = values.fold<double>(0, (sum, v) => sum + pow(v - mean, 2));
    return sqrt(sumSquaredDiff / values.length);
  }

  Map<String, double> _defaultMetrics() {
    return {
      'voice_energy': -30,
      'voice_pitch_mean': 150,
      'voice_pitch_variance': 20,
      'speech_rate': 120,
      'pause_ratio': 0.3,
      'voice_stress_index': 0.3,
      'voice_warmth_index': 0.5,
    };
  }
}

// =============================================================================
// BIOMETRIC COLLECTOR
// =============================================================================

/// Collects and aggregates biometric data from various sources
class BiometricCollector {
  final VoiceBiometricExtractor _voiceExtractor = VoiceBiometricExtractor();
  
  // Current biometric state
  Map<String, double> _subjectA = {};
  Map<String, double> _subjectB = {};
  Map<String, double> _synchrony = {};
  
  // Simulated values (replace with real sensor data when available)
  double _gazeContact = 0.5;
  double _bodyLean = 0;
  double _eda = 2.0;

  /// Process voice audio for subject A (client)
  void processClientAudio(Uint8List audioData) {
    final voiceMetrics = _voiceExtractor.processAudioSamples(audioData);
    _subjectA = {
      ..._subjectA,
      ...voiceMetrics,
      'gaze_contact': _gazeContact,
      'body_lean': _bodyLean,
      'eda': _eda,
    };
  }

  /// Process voice audio for subject B (therapist/Nate)
  void processTherapistAudio(Uint8List audioData) {
    // For AI sessions, we can simulate therapist metrics based on Nate's responses
    _subjectB = {
      'voice_stress_index': 0.15,  // Nate is always calm
      'voice_warmth_index': 0.85,  // Nate is warm
      'gaze_contact': 0.9,         // Nate maintains attention
      'body_lean': 5,              // Slight lean forward
      'eda': 1.5,                  // Low arousal
      'pause_ratio': 0.4,          // Thoughtful pauses
    };
  }

  /// Update gaze contact (from camera/face tracking)
  void updateGazeContact(double value) {
    _gazeContact = value.clamp(0, 1);
    _subjectA['gaze_contact'] = _gazeContact;
    _updateSynchrony();
  }

  /// Update body lean (from pose estimation)
  void updateBodyLean(double degrees) {
    _bodyLean = degrees.clamp(-30, 30);
    _subjectA['body_lean'] = _bodyLean;
    _updateSynchrony();
  }

  /// Update EDA (from wearable sensor)
  void updateEDA(double microSiemens) {
    _eda = microSiemens.clamp(0, 20);
    _subjectA['eda'] = _eda;
  }

  /// Calculate synchrony between subjects
  void _updateSynchrony() {
    if (_subjectA.isEmpty || _subjectB.isEmpty) return;

    // Calculate HRV synchrony (simulated for now)
    _synchrony['hrv'] = 0.5 + Random().nextDouble() * 0.3;

    // Calculate breath synchrony (simulated)
    _synchrony['breath'] = 0.5 + Random().nextDouble() * 0.3;

    // Calculate voice synchrony based on warmth correlation
    final warmthA = _subjectA['voice_warmth_index'] ?? 0.5;
    final warmthB = _subjectB['voice_warmth_index'] ?? 0.5;
    _synchrony['voice'] = 1 - (warmthA - warmthB).abs();

    // Calculate posture synchrony
    final leanA = _subjectA['body_lean'] ?? 0;
    final leanB = _subjectB['body_lean'] ?? 0;
    _synchrony['posture'] = 1 - ((leanA - leanB).abs() / 60).clamp(0, 1);

    // Calculate gaze synchrony
    final gazeA = _subjectA['gaze_contact'] ?? 0.5;
    final gazeB = _subjectB['gaze_contact'] ?? 0.5;
    _synchrony['gaze'] = (gazeA + gazeB) / 2;
  }

  /// Get complete biometric payload for server
  Map<String, dynamic> getBiometricPayload() {
    _updateSynchrony();
    
    return {
      'subject_a': Map<String, dynamic>.from(_subjectA),
      'subject_b': Map<String, dynamic>.from(_subjectB),
      'synchrony': Map<String, dynamic>.from(_synchrony),
    };
  }

  /// Reset collector state
  void reset() {
    _subjectA = {};
    _subjectB = {};
    _synchrony = {};
    _gazeContact = 0.5;
    _bodyLean = 0;
    _eda = 2.0;
  }
}

// =============================================================================
// NEVEDAL SERVICE
// =============================================================================

/// Service for communicating with the Nevedal Engine on the server
class NevedalService {
  final BiometricCollector _collector = BiometricCollector();
  final StreamController<NevedalState> _stateController = StreamController.broadcast();
  
  WebSocketChannel? _socket;
  Timer? _updateTimer;
  NevedalState _currentState = NevedalState.defaultState();
  
  String? _sessionId;
  String? _userId;
  
  /// Stream of Nevedal state updates
  Stream<NevedalState> get stateStream => _stateController.stream;
  
  /// Current Nevedal state
  NevedalState get currentState => _currentState;
  
  /// Biometric collector for external access
  BiometricCollector get collector => _collector;

  /// Initialize the service
  void initialize({
    required WebSocketChannel socket,
    required String sessionId,
    required String userId,
  }) {
    _socket = socket;
    _sessionId = sessionId;
    _userId = userId;
    
    // Start periodic biometric updates (every 2 seconds)
    _updateTimer?.cancel();
    _updateTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      _sendBiometricUpdate();
    });
    
    print(">>> [NEVEDAL] Service initialized for session: $sessionId");
  }

  /// Process incoming audio from VagusEngine
  void processClientAudio(Uint8List audioData) {
    _collector.processClientAudio(audioData);
  }

  /// Process Nate's audio response
  void processNateAudio(Uint8List audioData) {
    _collector.processTherapistAudio(audioData);
  }

  /// Handle state update from server
  void handleServerUpdate(Map<String, dynamic> data) {
    try {
      _currentState = NevedalState.fromJson(data);
      _stateController.add(_currentState);
      
      // Log CEE windows
      if (_currentState.ceeWindow) {
        print(">>> [NEVEDAL] 🌟 CEE WINDOW ACTIVE - Duration: ${_currentState.ceeDuration}s");
      }
    } catch (e) {
      print(">>> [NEVEDAL] Error parsing state: $e");
    }
  }

  /// Send biometric update to server
  void _sendBiometricUpdate() {
    if (_socket == null || _sessionId == null) return;
    
    final payload = {
      'type': 'biometric_update',
      'session_id': _sessionId,
      'user_id': _userId,
      'biometrics': _collector.getBiometricPayload(),
      'timestamp': DateTime.now().toIso8601String(),
    };
    
    try {
      _socket!.sink.add(jsonEncode(payload));
    } catch (e) {
      print(">>> [NEVEDAL] Error sending biometrics: $e");
    }
  }

  /// Dispose of resources
  void dispose() {
    _updateTimer?.cancel();
    _stateController.close();
    _collector.reset();
  }
}

// =============================================================================
// NEVEDAL STATE WIDGET
// =============================================================================

/// Widget displaying the current Nevedal state
class NevedalStateWidget extends StatelessWidget {
  final NevedalState state;
  final bool compact;

  const NevedalStateWidget({
    super.key,
    required this.state,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    if (compact) {
      return _buildCompact();
    }
    return _buildFull();
  }

  Widget _buildCompact() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: state.coherenceColor.withOpacity(0.2),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: state.coherenceColor),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          // CEE indicator
          if (state.ceeWindow) ...[
            const Text('🌟', style: TextStyle(fontSize: 14)),
            const SizedBox(width: 4),
          ],
          // Coherence value
          Text(
            'C: ${(state.cEmo * 100).toStringAsFixed(0)}%',
            style: TextStyle(
              color: state.coherenceColor,
              fontWeight: FontWeight.bold,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFull() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF252525)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header with CEE indicator
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'NEVEDAL STATE',
                style: TextStyle(
                  color: Color(0xFF9D4EDD),
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1,
                ),
              ),
              if (state.ceeWindow)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: const Color(0xFF00FF88).withOpacity(0.2),
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(color: const Color(0xFF00FF88)),
                  ),
                  child: Row(
                    children: [
                      const Text('🌟', style: TextStyle(fontSize: 10)),
                      const SizedBox(width: 4),
                      Text(
                        'CEE ${state.ceeDuration}s',
                        style: const TextStyle(
                          color: Color(0xFF00FF88),
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          
          // Main coherence gauge
          _buildGauge('Coherence', state.cEmo, state.coherenceColor),
          const SizedBox(height: 8),
          
          // Component metrics
          Row(
            children: [
              Expanded(child: _buildMiniMetric('p_ent', state.pEnt, const Color(0xFF9D4EDD))),
              const SizedBox(width: 8),
              Expanded(child: _buildMiniMetric('T_tunnel', state.tTunnel, const Color(0xFF00D4FF))),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: _buildMiniMetric('γ_env', state.gammaEnv, const Color(0xFFFF9500))),
              const SizedBox(width: 8),
              Expanded(child: _buildMiniMetric('E_G', state.eGJoint, const Color(0xFFFFD700))),
            ],
          ),
          
          // Interpretation
          if (state.interpretation.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text(
              state.interpretation,
              style: const TextStyle(
                color: Color(0xFF888888),
                fontSize: 11,
                fontStyle: FontStyle.italic,
              ),
            ),
          ],
          
          // Recommendations
          if (state.recommendations.isNotEmpty) ...[
            const SizedBox(height: 8),
            ...state.recommendations.take(2).map((rec) => Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('• ', style: TextStyle(color: Color(0xFF00D4FF), fontSize: 11)),
                  Expanded(
                    child: Text(
                      rec,
                      style: const TextStyle(color: Color(0xFFCCCCCC), fontSize: 11),
                    ),
                  ),
                ],
              ),
            )),
          ],
        ],
      ),
    );
  }

  Widget _buildGauge(String label, double value, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              label,
              style: const TextStyle(color: Color(0xFF888888), fontSize: 11),
            ),
            Text(
              '${(value * 100).toStringAsFixed(0)}%',
              style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 14),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Container(
          height: 8,
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A1A),
            borderRadius: BorderRadius.circular(4),
          ),
          child: FractionallySizedBox(
            alignment: Alignment.centerLeft,
            widthFactor: value.clamp(0, 1),
            child: Container(
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(4),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildMiniMetric(String label, double value, Color color) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        children: [
          Text(
            label,
            style: TextStyle(color: color, fontSize: 10, fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: 4),
          Text(
            value.toStringAsFixed(2),
            style: TextStyle(color: color, fontSize: 16, fontWeight: FontWeight.bold),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// CEE NOTIFICATION WIDGET
// =============================================================================

/// Shows a notification when a CEE window is detected
class CEENotificationWidget extends StatefulWidget {
  final NevedalState state;

  const CEENotificationWidget({super.key, required this.state});

  @override
  State<CEENotificationWidget> createState() => _CEENotificationWidgetState();
}

class _CEENotificationWidgetState extends State<CEENotificationWidget>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _pulse;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      duration: const Duration(milliseconds: 1500),
      vsync: this,
    )..repeat(reverse: true);
    _pulse = Tween<double>(begin: 0.8, end: 1.0).animate(_controller);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.state.ceeWindow) return const SizedBox.shrink();

    return AnimatedBuilder(
      animation: _pulse,
      builder: (context, child) {
        return Transform.scale(
          scale: _pulse.value,
          child: Container(
            margin: const EdgeInsets.all(16),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  const Color(0xFF00FF88).withOpacity(0.3),
                  const Color(0xFF00D4FF).withOpacity(0.3),
                ],
              ),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFF00FF88)),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF00FF88).withOpacity(0.3),
                  blurRadius: 20,
                  spreadRadius: 2,
                ),
              ],
            ),
            child: Row(
              children: [
                const Text('🌟', style: TextStyle(fontSize: 32)),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text(
                        'CORRECTIVE EMOTIONAL EXPERIENCE',
                        style: TextStyle(
                          color: Color(0xFF00FF88),
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        'Optimal therapeutic moment • ${widget.state.ceeDuration}s',
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
