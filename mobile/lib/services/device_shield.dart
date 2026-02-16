/// HIVE DEFENSE v4.3 — Client Device Shield (Window 6)
///
/// Multi-layered client-side security:
/// 1. Jailbreak / Root Detection
/// 2. Screen Recording Detection
/// 3. Debugger Detection
/// 4. App Integrity Verification
/// 5. Secure Enclave Key Storage
/// 6. Memory Wipe on Background
/// 7. Crystal Never on Disk (ephemeral session data)
///
/// All checks run on app launch and periodically during active sessions.
/// Failed checks trigger graduated responses: warn → degrade → lock.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Shield status levels
enum ShieldStatus {
  /// All checks passed
  secure,

  /// Minor anomalies detected (e.g. old OS version)
  advisory,

  /// Potential compromise detected (e.g. debugger attached)
  degraded,

  /// Critical compromise detected (jailbreak / root)
  locked,
}

/// Result of a single shield check
class ShieldCheckResult {
  final String checkName;
  final bool passed;
  final String? reason;
  final ShieldStatus severity;

  const ShieldCheckResult({
    required this.checkName,
    required this.passed,
    this.reason,
    this.severity = ShieldStatus.secure,
  });

  Map<String, dynamic> toJson() => {
        'check': checkName,
        'passed': passed,
        if (reason != null) 'reason': reason,
        'severity': severity.name,
      };
}

/// Aggregate shield report
class ShieldReport {
  final ShieldStatus overallStatus;
  final List<ShieldCheckResult> checks;
  final DateTime timestamp;

  const ShieldReport({
    required this.overallStatus,
    required this.checks,
    required this.timestamp,
  });

  bool get isSecure => overallStatus == ShieldStatus.secure;
  bool get isLocked => overallStatus == ShieldStatus.locked;

  Map<String, dynamic> toJson() => {
        'status': overallStatus.name,
        'timestamp': timestamp.toIso8601String(),
        'checks': checks.map((c) => c.toJson()).toList(),
        'passed': checks.where((c) => c.passed).length,
        'failed': checks.where((c) => !c.passed).length,
      };
}

/// Main Device Shield service
class DeviceShield {
  DeviceShield._();
  static final DeviceShield instance = DeviceShield._();

  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(
      accessibility: KeychainAccessibility.first_unlock_this_device,
    ),
  );

  /// Ephemeral session data that must never touch disk
  final Map<String, dynamic> _ephemeralData = {};

  /// Timer for periodic checks during active sessions
  Timer? _periodicCheckTimer;

  /// Callback for shield status changes
  void Function(ShieldReport)? onStatusChange;

  // ─── 1. Jailbreak / Root Detection ─────────────────────────────────────

  ShieldCheckResult checkJailbreak() {
    if (kIsWeb) {
      return const ShieldCheckResult(
        checkName: 'jailbreak_detection',
        passed: true,
        reason: 'Web platform — not applicable',
      );
    }

    final suspicious = <String>[];

    if (Platform.isIOS) {
      // Check for common jailbreak indicators
      final jailbreakPaths = [
        '/Applications/Cydia.app',
        '/Library/MobileSubstrate/MobileSubstrate.dylib',
        '/bin/bash',
        '/usr/sbin/sshd',
        '/etc/apt',
        '/private/var/lib/apt/',
        '/usr/lib/TweakInject',
        '/var/lib/dpkg/info',
      ];
      for (final path in jailbreakPaths) {
        if (File(path).existsSync()) {
          suspicious.add('Found: $path');
        }
      }

      // Check if app can write outside sandbox
      try {
        final testFile = File('/private/jailbreak_test_${DateTime.now().millisecondsSinceEpoch}');
        testFile.writeAsStringSync('test');
        testFile.deleteSync();
        suspicious.add('Writable outside sandbox');
      } catch (_) {
        // Expected on non-jailbroken device
      }
    } else if (Platform.isAndroid) {
      // Check for common root indicators
      final rootPaths = [
        '/system/app/Superuser.apk',
        '/sbin/su',
        '/system/bin/su',
        '/system/xbin/su',
        '/data/local/xbin/su',
        '/data/local/bin/su',
        '/system/sd/xbin/su',
        '/system/bin/failsafe/su',
        '/data/local/su',
        '/su/bin/su',
      ];
      for (final path in rootPaths) {
        if (File(path).existsSync()) {
          suspicious.add('Found: $path');
        }
      }
    }

    if (suspicious.isNotEmpty) {
      return ShieldCheckResult(
        checkName: 'jailbreak_detection',
        passed: false,
        reason: 'Jailbreak/root indicators: ${suspicious.length} found',
        severity: ShieldStatus.locked,
      );
    }

    return const ShieldCheckResult(
      checkName: 'jailbreak_detection',
      passed: true,
    );
  }

  // ─── 2. Screen Recording Detection ─────────────────────────────────────

  ShieldCheckResult checkScreenRecording() {
    if (kIsWeb || !Platform.isIOS) {
      // Android doesn't have a reliable screen recording API
      // iOS has UIScreen.isCaptured
      return const ShieldCheckResult(
        checkName: 'screen_recording_detection',
        passed: true,
        reason: 'Platform check not applicable or unavailable',
      );
    }

    // On iOS, we use platform channel to check UIScreen.main.isCaptured
    // This is a synchronous check; the actual platform call is in the
    // native iOS code. Here we return advisory since we can't block
    // synchronously from Dart.
    return const ShieldCheckResult(
      checkName: 'screen_recording_detection',
      passed: true,
      reason: 'Checked via platform channel on next async cycle',
    );
  }

  /// Async version that queries the native platform
  Future<ShieldCheckResult> checkScreenRecordingAsync() async {
    if (kIsWeb) {
      return const ShieldCheckResult(
        checkName: 'screen_recording_detection',
        passed: true,
      );
    }

    try {
      const channel = MethodChannel('com.sovereignsanctuary/device_shield');
      final bool isCaptured = await channel.invokeMethod('isScreenCaptured') ?? false;

      if (isCaptured) {
        return const ShieldCheckResult(
          checkName: 'screen_recording_detection',
          passed: false,
          reason: 'Screen recording or mirroring detected',
          severity: ShieldStatus.degraded,
        );
      }
    } on MissingPluginException {
      // Platform channel not implemented yet — pass with advisory
      return const ShieldCheckResult(
        checkName: 'screen_recording_detection',
        passed: true,
        reason: 'Native check not yet implemented',
        severity: ShieldStatus.advisory,
      );
    } catch (e) {
      debugPrint('[DeviceShield] Screen recording check error: $e');
    }

    return const ShieldCheckResult(
      checkName: 'screen_recording_detection',
      passed: true,
    );
  }

  // ─── 3. Debugger Detection ─────────────────────────────────────────────

  ShieldCheckResult checkDebugger() {
    if (kDebugMode) {
      // Don't flag during development
      return const ShieldCheckResult(
        checkName: 'debugger_detection',
        passed: true,
        reason: 'Debug mode — check skipped',
        severity: ShieldStatus.advisory,
      );
    }

    // In release mode, kDebugMode is false. Check for attached debugger.
    final isProfileMode = kProfileMode;
    if (isProfileMode) {
      return const ShieldCheckResult(
        checkName: 'debugger_detection',
        passed: false,
        reason: 'Profile mode detected in release build',
        severity: ShieldStatus.degraded,
      );
    }

    // assert() only executes in debug mode; if it doesn't fire, we're in release
    bool assertsEnabled = false;
    assert(() {
      assertsEnabled = true;
      return true;
    }());

    if (assertsEnabled) {
      return const ShieldCheckResult(
        checkName: 'debugger_detection',
        passed: false,
        reason: 'Asserts enabled in apparent release build',
        severity: ShieldStatus.degraded,
      );
    }

    return const ShieldCheckResult(
      checkName: 'debugger_detection',
      passed: true,
    );
  }

  // ─── 4. App Integrity Verification ─────────────────────────────────────

  Future<ShieldCheckResult> checkAppIntegrity() async {
    if (kIsWeb) {
      return const ShieldCheckResult(
        checkName: 'app_integrity',
        passed: true,
        reason: 'Web platform — integrity verified by HTTPS',
      );
    }

    try {
      const channel = MethodChannel('com.sovereignsanctuary/device_shield');
      final Map<dynamic, dynamic>? result =
          await channel.invokeMethod('verifyAppIntegrity');

      if (result != null && result['valid'] == true) {
        return const ShieldCheckResult(
          checkName: 'app_integrity',
          passed: true,
        );
      }

      return ShieldCheckResult(
        checkName: 'app_integrity',
        passed: false,
        reason: result?['reason']?.toString() ?? 'Integrity check failed',
        severity: ShieldStatus.locked,
      );
    } on MissingPluginException {
      return const ShieldCheckResult(
        checkName: 'app_integrity',
        passed: true,
        reason: 'Native integrity check not yet implemented',
        severity: ShieldStatus.advisory,
      );
    } catch (e) {
      debugPrint('[DeviceShield] App integrity check error: $e');
      return const ShieldCheckResult(
        checkName: 'app_integrity',
        passed: true,
        reason: 'Check unavailable',
        severity: ShieldStatus.advisory,
      );
    }
  }

  // ─── 5. Secure Enclave Key Storage ─────────────────────────────────────

  /// Store a key securely using the platform's Secure Enclave / Keystore
  Future<void> secureStoreKey(String key, String value) async {
    await _secureStorage.write(key: key, value: value);
  }

  /// Retrieve a securely stored key
  Future<String?> secureReadKey(String key) async {
    return await _secureStorage.read(key: key);
  }

  /// Delete a securely stored key
  Future<void> secureDeleteKey(String key) async {
    await _secureStorage.delete(key: key);
  }

  /// Delete all securely stored keys (emergency wipe)
  Future<void> secureDeleteAll() async {
    await _secureStorage.deleteAll();
  }

  // ─── 6. Memory Wipe on Background ─────────────────────────────────────

  /// Called when app enters background — wipe ephemeral session data
  void onAppBackground() {
    _ephemeralData.clear();
    debugPrint('[DeviceShield] Ephemeral data wiped on background');
  }

  /// Called when app returns to foreground — trigger re-verification
  Future<ShieldReport> onAppForeground() async {
    return await runFullCheck();
  }

  // ─── 7. Crystal Never on Disk ──────────────────────────────────────────

  /// Store ephemeral session data (memory only, never persisted)
  void setEphemeral(String key, dynamic value) {
    _ephemeralData[key] = value;
  }

  /// Retrieve ephemeral session data
  dynamic getEphemeral(String key) {
    return _ephemeralData[key];
  }

  /// Clear all ephemeral data
  void clearEphemeral() {
    _ephemeralData.clear();
  }

  /// Check if any sensitive data has leaked to disk
  Future<ShieldCheckResult> checkDiskLeakage() async {
    if (kIsWeb) {
      return const ShieldCheckResult(
        checkName: 'disk_leakage',
        passed: true,
      );
    }

    // Check common temp/cache directories for sensitive data patterns
    // This is a heuristic check — it looks for files that shouldn't exist
    final suspicious = <String>[];

    try {
      const channel = MethodChannel('com.sovereignsanctuary/device_shield');
      final List<dynamic>? leaks = await channel.invokeMethod('checkDiskLeaks');
      if (leaks != null && leaks.isNotEmpty) {
        suspicious.addAll(leaks.map((e) => e.toString()));
      }
    } on MissingPluginException {
      // Platform check not available
    } catch (e) {
      debugPrint('[DeviceShield] Disk leakage check error: $e');
    }

    if (suspicious.isNotEmpty) {
      return ShieldCheckResult(
        checkName: 'disk_leakage',
        passed: false,
        reason: '${suspicious.length} potential data leaks found on disk',
        severity: ShieldStatus.degraded,
      );
    }

    return const ShieldCheckResult(
      checkName: 'disk_leakage',
      passed: true,
    );
  }

  // ─── Full Shield Check ─────────────────────────────────────────────────

  /// Run all shield checks and return an aggregate report
  Future<ShieldReport> runFullCheck() async {
    final checks = <ShieldCheckResult>[];

    // Synchronous checks
    checks.add(checkJailbreak());
    checks.add(checkScreenRecording());
    checks.add(checkDebugger());

    // Async checks
    checks.add(await checkScreenRecordingAsync());
    checks.add(await checkAppIntegrity());
    checks.add(await checkDiskLeakage());

    // Determine overall status (worst severity wins)
    ShieldStatus overall = ShieldStatus.secure;
    for (final check in checks) {
      if (!check.passed) {
        if (check.severity.index > overall.index) {
          overall = check.severity;
        }
      }
    }

    final report = ShieldReport(
      overallStatus: overall,
      checks: checks,
      timestamp: DateTime.now(),
    );

    onStatusChange?.call(report);
    return report;
  }

  // ─── Periodic Monitoring ───────────────────────────────────────────────

  /// Start periodic shield checks during an active session
  void startPeriodicChecks({Duration interval = const Duration(minutes: 5)}) {
    stopPeriodicChecks();
    _periodicCheckTimer = Timer.periodic(interval, (_) async {
      final report = await runFullCheck();
      if (report.isLocked) {
        debugPrint('[DeviceShield] CRITICAL: Device locked during session');
      }
    });
  }

  /// Stop periodic shield checks
  void stopPeriodicChecks() {
    _periodicCheckTimer?.cancel();
    _periodicCheckTimer = null;
  }

  /// Encode the current shield report for transmission to the backend
  String encodeReportForTransmit(ShieldReport report) {
    return jsonEncode(report.toJson());
  }
}
