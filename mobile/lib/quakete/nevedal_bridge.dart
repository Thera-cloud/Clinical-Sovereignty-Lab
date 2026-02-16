/// Nevedal-Quakete Bridge
/// Layer 8 Swarm Solidarity — Coherence Integration
/// 
/// Bridges the Nevedal quantum emotional coherence engine with Quakete solidarity.
/// Converts coherence metrics to Quakete resonance values and triggers mode transitions.

import 'dart:math';
import 'constants.dart';
import '../services/nevedal_flutter.dart';

/// Coherence trend analysis
enum CoherenceTrend {
  /// Coherence improving over time
  improving,
  
  /// Coherence stable
  stable,
  
  /// Coherence declining
  declining,
  
  /// Coherence at crisis level
  crisis,
}

/// Nevedal-Quakete Bridge
/// 
/// Converts Nevedal coherence (C_emo) to Quakete resonance (C_q) and monitors trends.
class NevedalQuaketeBridge {
  final List<double> _coherenceHistory = [];
  final List<double> _resonanceHistory = [];
  static const int _historySize = 10; // Keep last 10 readings
  
  double _lastResonance = 0.0;
  CoherenceTrend _currentTrend = CoherenceTrend.stable;

  /// Current Quakete resonance value (0-1)
  double get resonance => _lastResonance;

  /// Current coherence trend
  CoherenceTrend get trend => _currentTrend;

  /// Process Nevedal coherence state and convert to Quakete resonance
  /// 
  /// Formula: C_q = C_emo * p_ent * T_tunnel / max(gamma_env, 0.001)
  /// Clamped to [0, 1]
  /// 
  /// [cEmo] - Quantum Emotional Coherence (0-1)
  /// [pEnt] - Emotional Entanglement (0-1)
  /// [tTunnel] - Tunneling Transparency (0-1)
  /// [gammaEnv] - Decoherence Rate (0-1)
  /// 
  /// Returns the computed Quakete resonance value.
  double processCoherence({
    required double cEmo,
    required double pEnt,
    required double tTunnel,
    required double gammaEnv,
  }) {
    // Prevent division by zero
    final safeGamma = max(gammaEnv, 0.001);
    
    // Compute Quakete resonance: C_q = C_emo * p_ent * T_tunnel / gamma_env
    final resonance = (cEmo * pEnt * tTunnel / safeGamma).clamp(0.0, 1.0);
    
    // Update history
    _coherenceHistory.add(cEmo);
    _resonanceHistory.add(resonance);
    
    if (_coherenceHistory.length > _historySize) {
      _coherenceHistory.removeAt(0);
      _resonanceHistory.removeAt(0);
    }
    
    _lastResonance = resonance;
    
    // Analyze trend
    _updateTrend();
    
    return resonance;
  }

  /// Process NevedalState directly
  double processNevedalState(NevedalState state) {
    return processCoherence(
      cEmo: state.cEmo,
      pEnt: state.pEnt,
      tTunnel: state.tTunnel,
      gammaEnv: state.gammaEnv,
    );
  }

  /// Get current resonance value
  double getResonance() {
    return _lastResonance;
  }

  /// Get current coherence trend
  CoherenceTrend getTrend() {
    return _currentTrend;
  }

  /// Analyze coherence trend from history
  void _updateTrend() {
    if (_coherenceHistory.length < 3) {
      _currentTrend = CoherenceTrend.stable;
      return;
    }

    // Check for crisis (any recent reading below threshold)
    final recentLow = _coherenceHistory.any((c) => c < RAMP_UP_THRESHOLD);
    if (recentLow) {
      _currentTrend = CoherenceTrend.crisis;
      return;
    }

    // Calculate trend from last 5 readings
    final recent = _coherenceHistory.length >= 5
        ? _coherenceHistory.sublist(_coherenceHistory.length - 5)
        : _coherenceHistory;
    
    final first = recent.first;
    final last = recent.last;
    final diff = last - first;
    
    // Threshold for trend detection
    const trendThreshold = 0.05;
    
    if (diff > trendThreshold) {
      _currentTrend = CoherenceTrend.improving;
    } else if (diff < -trendThreshold) {
      _currentTrend = CoherenceTrend.declining;
    } else {
      _currentTrend = CoherenceTrend.stable;
    }
  }

  /// Check if coherence is low enough to trigger emergency
  bool shouldTriggerEmergency() {
    if (_coherenceHistory.isEmpty) return false;
    final latest = _coherenceHistory.last;
    return latest < RAMP_UP_THRESHOLD;
  }

  /// Check if coherence is low enough to request transfer
  bool shouldRequestTransfer() {
    if (_coherenceHistory.isEmpty) return false;
    final latest = _coherenceHistory.last;
    return latest < 0.3;
  }

  /// Check if coherence is high enough to donate energy
  bool canDonateEnergy() {
    if (_coherenceHistory.isEmpty) return false;
    final latest = _coherenceHistory.last;
    return latest > 0.6;
  }

  /// Check if coherence is high enough for ring formation
  bool isRingFormationCandidate() {
    if (_coherenceHistory.isEmpty) return false;
    final latest = _coherenceHistory.last;
    return latest > 0.8;
  }

  /// Get recommended Quakete mode based on current coherence
  QuaketeMode getRecommendedMode() {
    if (_coherenceHistory.isEmpty) {
      return QuaketeMode.DORMANT;
    }

    final latest = _coherenceHistory.last;
    
    if (latest < RAMP_UP_THRESHOLD) {
      return QuaketeMode.EMERGENCY;
    } else if (latest < 0.3) {
      // Low coherence but not emergency - stay in current mode or LISTENING
      return QuaketeMode.LISTENING;
    } else if (latest > 0.6) {
      return QuaketeMode.RESONATING;
    } else {
      return QuaketeMode.LISTENING;
    }
  }

  /// Get coherence history (for visualization/debugging)
  List<double> getCoherenceHistory() {
    return List.unmodifiable(_coherenceHistory);
  }

  /// Get resonance history (for visualization/debugging)
  List<double> getResonanceHistory() {
    return List.unmodifiable(_resonanceHistory);
  }

  /// Reset history (for new session)
  void reset() {
    _coherenceHistory.clear();
    _resonanceHistory.clear();
    _lastResonance = 0.0;
    _currentTrend = CoherenceTrend.stable;
  }
}
