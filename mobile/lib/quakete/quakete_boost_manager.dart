/// Quakete Boost Manager
/// Layer 8 Swarm Solidarity — Energy Boost Management
/// 
/// Manages incoming Quakete energy boosts from the swarm.
/// Applies boosts to local emotional state and tracks boost history.

import 'dart:async';
import 'dart:math';

/// Boost entry
class QuaketeBoost {
  final String boostId;
  final String fromFibreId;
  final double amount;
  final DateTime receivedAt;
  final DateTime expiresAt;
  final String? message; // Optional message from donating Fibre

  QuaketeBoost({
    required this.boostId,
    required this.fromFibreId,
    required this.amount,
    required this.receivedAt,
    required this.expiresAt,
    this.message,
  });

  /// Check if boost is still active (not expired)
  bool get isActive => DateTime.now().isBefore(expiresAt);

  /// Get remaining duration until expiration
  Duration get remainingDuration {
    final now = DateTime.now();
    if (now.isAfter(expiresAt)) {
      return Duration.zero;
    }
    return expiresAt.difference(now);
  }

  /// Get decay factor (1.0 = full strength, 0.0 = expired)
  double getDecayFactor() {
    if (!isActive) return 0.0;
    
    final totalDuration = expiresAt.difference(receivedAt);
    final remaining = remainingDuration;
    
    if (totalDuration.inSeconds == 0) return 1.0;
    
    // Exponential decay: e^(-t/tau), where tau = totalDuration / 2
    final tau = totalDuration.inSeconds / 2.0;
    final t = (totalDuration.inSeconds - remaining.inSeconds).toDouble();
    return exp(-t / tau);
  }
}

/// Quakete Boost Manager
/// 
/// Receives and manages incoming energy boosts from the swarm.
class QuaketeBoostManager {
  final Map<String, QuaketeBoost> _activeBoosts = {};
  final List<QuaketeBoost> _boostHistory = [];
  
  double _totalEnergyReceived = 0.0;
  
  Timer? _decayTimer;
  final StreamController<QuaketeBoost> _boostReceivedController =
      StreamController<QuaketeBoost>.broadcast();
  
  final StreamController<double> _boostAppliedController =
      StreamController<double>.broadcast();

  /// Stream of boost received events (for UI notifications)
  Stream<QuaketeBoost> get boostReceivedStream => _boostReceivedController.stream;

  /// Stream of boost applied events (for visual feedback)
  Stream<double> get boostAppliedStream => _boostAppliedController.stream;

  /// Total energy received from all boosts (cumulative)
  double get totalEnergyReceived => _totalEnergyReceived;

  /// Current active boost amount (sum of all active boosts with decay)
  double get currentBoost {
    double total = 0.0;
    for (final boost in _activeBoosts.values) {
      if (boost.isActive) {
        total += boost.amount * boost.getDecayFactor();
      }
    }
    return total;
  }

  /// Number of active boosts
  int get activeBoostCount => _activeBoosts.values.where((b) => b.isActive).length;

  /// Initialize the boost manager
  void initialize() {
    // Start periodic decay check
    _decayTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      _updateDecay();
    });
  }

  /// Apply an incoming boost
  /// 
  /// [boostId] - Unique identifier for this boost
  /// [fromFibreId] - ID of the Fibre that sent the boost
  /// [amount] - Energy amount (0-1)
  /// [durationSeconds] - How long the boost lasts (default: 60 seconds)
  /// [message] - Optional message from donating Fibre
  void applyBoost({
    required String boostId,
    required String fromFibreId,
    required double amount,
    int durationSeconds = 60,
    String? message,
  }) {
    // Clamp amount to valid range
    final clampedAmount = amount.clamp(0.0, 1.0);
    
    final now = DateTime.now();
    final boost = QuaketeBoost(
      boostId: boostId,
      fromFibreId: fromFibreId,
      amount: clampedAmount,
      receivedAt: now,
      expiresAt: now.add(Duration(seconds: durationSeconds)),
      message: message,
    );

    _activeBoosts[boostId] = boost;
    _boostHistory.add(boost);
    
    // Keep history size manageable
    if (_boostHistory.length > 100) {
      _boostHistory.removeAt(0);
    }

    _totalEnergyReceived += clampedAmount;

    print('[QuaketeBoostManager] Applied boost: $boostId from $fromFibreId (amount: ${clampedAmount.toStringAsFixed(3)})');

    // Notify listeners
    _boostReceivedController.add(boost);
    _boostAppliedController.add(clampedAmount);
  }

  /// Handle boost notification from backend (via WebSocket)
  /// 
  /// Expected format:
  /// {
  ///   'type': 'quakete_boost',
  ///   'boost_id': '...',
  ///   'from_fibre_id': '...',
  ///   'amount': 0.5,
  ///   'duration_seconds': 60,
  ///   'message': '...' (optional)
  /// }
  void handleBoostNotification(Map<String, dynamic> data) {
    try {
      applyBoost(
        boostId: data['boost_id'] as String,
        fromFibreId: data['from_fibre_id'] as String,
        amount: (data['amount'] as num).toDouble(),
        durationSeconds: data['duration_seconds'] as int? ?? 60,
        message: data['message'] as String?,
      );
    } catch (e) {
      print('[QuaketeBoostManager] Error handling boost notification: $e');
    }
  }

  /// Get all active boosts
  List<QuaketeBoost> getActiveBoosts() {
    return _activeBoosts.values.where((b) => b.isActive).toList();
  }

  /// Get boost history (all boosts, including expired)
  List<QuaketeBoost> getBoostHistory({int? limit}) {
    final history = List<QuaketeBoost>.from(_boostHistory);
    if (limit != null && limit > 0) {
      return history.sublist(0, history.length.clamp(0, limit));
    }
    return history;
  }

  /// Acknowledge a boost (mark as processed, optional)
  void acknowledgeBoost(String boostId) {
    // For now, just log acknowledgment
    // In future, could send acknowledgment back to backend
    print('[QuaketeBoostManager] Acknowledged boost: $boostId');
  }

  /// Remove expired boosts and update decay
  void _updateDecay() {
    final now = DateTime.now();
    final expiredIds = <String>[];

    for (final entry in _activeBoosts.entries) {
      if (!entry.value.isActive) {
        expiredIds.add(entry.key);
      }
    }

    for (final id in expiredIds) {
      _activeBoosts.remove(id);
    }

    // Notify if boost amount changed significantly
    if (expiredIds.isNotEmpty) {
      _boostAppliedController.add(currentBoost);
    }
  }

  /// Get boost statistics
  Map<String, dynamic> getStatistics() {
    final active = getActiveBoosts();
    final recent = _boostHistory.length > 10
        ? _boostHistory.sublist(_boostHistory.length - 10)
        : _boostHistory;

    return {
      'total_energy_received': _totalEnergyReceived,
      'current_boost': currentBoost,
      'active_boost_count': active.length,
      'total_boosts_received': _boostHistory.length,
      'recent_boosts': recent.length,
      'average_boost_amount': recent.isNotEmpty
          ? recent.map((b) => b.amount).reduce((a, b) => a + b) / recent.length
          : 0.0,
    };
  }

  /// Reset boost manager (for new session)
  void reset() {
    _activeBoosts.clear();
    _boostHistory.clear();
    _totalEnergyReceived = 0.0;
  }

  /// Dispose resources
  void dispose() {
    _decayTimer?.cancel();
    _decayTimer = null;
    _boostReceivedController.close();
    _boostAppliedController.close();
  }
}
