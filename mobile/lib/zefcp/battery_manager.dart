/// Battery Manager — Adaptive battery management for ZEFCP BLE scanning
/// 
/// Monitors battery level and charging state to adjust:
/// - BLE scan intervals
/// - Advertising intervals
/// - Scanning mode (aggressive vs minimal)
/// 
/// Battery profiles:
/// - FULL (>80%): Aggressive scanning, 1s intervals
/// - NORMAL (30-80%): Standard scanning, 5s intervals
/// - LOW (15-30%): Reduced scanning, 15s intervals
/// - CRITICAL (<15%): Minimal scanning, 60s intervals, no advertising
/// - CHARGING: Aggressive regardless of level

import 'dart:async';
import 'package:battery_plus/battery_plus.dart';

/// Battery profile with adaptive parameters
class BatteryProfile {
  final int level; // 0-100
  final bool isCharging;
  final Duration scanInterval;
  final Duration advertisingInterval;
  final BatteryMode mode;

  BatteryProfile({
    required this.level,
    required this.isCharging,
    required this.scanInterval,
    required this.advertisingInterval,
    required this.mode,
  });

  @override
  String toString() => 'BatteryProfile(level: $level%, charging: $isCharging, mode: $mode)';
}

/// Battery mode for adaptive behavior
enum BatteryMode {
  aggressive,  // Full power scanning
  standard,    // Normal operation
  reduced,     // Power-saving mode
  minimal,     // Critical power mode
}

/// Battery Manager — monitors battery and provides adaptive profiles
class BatteryManager {
  final Battery _battery = Battery();
  final StreamController<BatteryProfile> _profileController =
      StreamController<BatteryProfile>.broadcast();

  StreamSubscription<BatteryState>? _stateSubscription;
  Timer? _levelCheckTimer;
  BatteryProfile? _currentProfile;

  /// Stream of battery profile updates
  Stream<BatteryProfile> get batteryProfileStream => _profileController.stream;

  /// Current battery profile
  BatteryProfile? get currentProfile => _currentProfile;

  /// Initialize battery monitoring
  Future<void> initialize() async {
    // Get initial state
    final level = await _battery.batteryLevel;
    final state = await _battery.batteryState;
    final isCharging = state == BatteryState.charging ||
                       state == BatteryState.full;

    _currentProfile = _calculateProfile(level, isCharging);
    _profileController.add(_currentProfile!);

    // Listen to battery state changes (charging/discharging)
    _stateSubscription = _battery.onBatteryStateChanged.listen(
      (state) async {
        final level = await _battery.batteryLevel;
        final isCharging = state == BatteryState.charging ||
                          state == BatteryState.full;
        _updateProfile(level, isCharging);
      },
    );

    // Periodically check battery level (every 30 seconds)
    _levelCheckTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) async {
        final level = await _battery.batteryLevel;
        final state = await _battery.batteryState;
        final isCharging = state == BatteryState.charging ||
                          state == BatteryState.full;
        _updateProfile(level, isCharging);
      },
    );
  }

  /// Get current battery profile (synchronous)
  Future<BatteryProfile> getCurrentProfile() async {
    if (_currentProfile != null) {
      return _currentProfile!;
    }

    final level = await _battery.batteryLevel;
    final state = await _battery.batteryState;
    final isCharging = state == BatteryState.charging ||
                       state == BatteryState.full;

    return _calculateProfile(level, isCharging);
  }

  /// Update battery profile and notify listeners
  void _updateProfile(int level, bool isCharging) {
    final newProfile = _calculateProfile(level, isCharging);
    
    // Only emit if profile changed
    if (_currentProfile == null ||
        _currentProfile!.level != newProfile.level ||
        _currentProfile!.isCharging != newProfile.isCharging ||
        _currentProfile!.mode != newProfile.mode) {
      _currentProfile = newProfile;
      _profileController.add(newProfile);
    }
  }

  /// Calculate battery profile based on level and charging state
  BatteryProfile _calculateProfile(int level, bool isCharging) {
    // If charging, use aggressive mode regardless of level
    if (isCharging) {
      return BatteryProfile(
        level: level,
        isCharging: true,
        scanInterval: const Duration(seconds: 1),
        advertisingInterval: const Duration(milliseconds: 100),
        mode: BatteryMode.aggressive,
      );
    }

    // Determine mode based on battery level
    BatteryMode mode;
    Duration scanInterval;
    Duration advertisingInterval;

    if (level > 80) {
      // FULL: Aggressive scanning
      mode = BatteryMode.aggressive;
      scanInterval = const Duration(seconds: 1);
      advertisingInterval = const Duration(milliseconds: 100);
    } else if (level >= 30) {
      // NORMAL: Standard scanning
      mode = BatteryMode.standard;
      scanInterval = const Duration(seconds: 5);
      advertisingInterval = const Duration(milliseconds: 200);
    } else if (level >= 15) {
      // LOW: Reduced scanning
      mode = BatteryMode.reduced;
      scanInterval = const Duration(seconds: 15);
      advertisingInterval = const Duration(milliseconds: 500);
    } else {
      // CRITICAL: Minimal scanning, no advertising
      mode = BatteryMode.minimal;
      scanInterval = const Duration(seconds: 60);
      advertisingInterval = const Duration(seconds: 0); // Disabled
    }

    return BatteryProfile(
      level: level,
      isCharging: false,
      scanInterval: scanInterval,
      advertisingInterval: advertisingInterval,
      mode: mode,
    );
  }

  /// Dispose resources
  void dispose() {
    _stateSubscription?.cancel();
    _levelCheckTimer?.cancel();
    _profileController.close();
  }
}
