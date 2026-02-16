/// ZEFCP Background Service — Persistent BLE scanning in background
/// 
/// Android: Uses foreground service with persistent notification
/// iOS: Uses CBCentralManager background mode (limited scanning)
/// 
/// Manages BleScanner lifecycle and battery-aware scanning

import 'dart:async';
import 'package:flutter/services.dart';
import 'battery_manager.dart';

/// Background service state
enum BackgroundServiceState {
  stopped,
  starting,
  running,
  stopping,
  error,
}

/// ZEFCP Background Service
class ZefcpBackgroundService {
  static final ZefcpBackgroundService _instance = ZefcpBackgroundService._internal();
  factory ZefcpBackgroundService() => _instance;
  ZefcpBackgroundService._internal();

  BackgroundServiceState _state = BackgroundServiceState.stopped;
  final StreamController<BackgroundServiceState> _stateController =
      StreamController<BackgroundServiceState>.broadcast();

  Timer? _scanTimer;
  BatteryManager? _batteryManager;
  StreamSubscription<BatteryProfile>? _batterySubscription;

  // Platform channel for native background service
  static const MethodChannel _channel = MethodChannel('zefcp/background_service');

  /// Current service state
  BackgroundServiceState get state => _state;

  /// Stream of state changes
  Stream<BackgroundServiceState> get stateStream => _stateController.stream;

  /// Check if service is running
  bool get isRunning => _state == BackgroundServiceState.running;

  /// Initialize the background service
  Future<void> initialize() async {
    _batteryManager = BatteryManager();
    await _batteryManager!.initialize();

    // Listen to battery changes for adaptive scanning
    _batterySubscription = _batteryManager!.batteryProfileStream.listen(
      (profile) {
        if (_state == BackgroundServiceState.running) {
          _updateScanParameters(profile);
        }
      },
    );
  }

  /// Start background scanning service
  Future<bool> startBackground() async {
    if (_state == BackgroundServiceState.running ||
        _state == BackgroundServiceState.starting) {
      return _state == BackgroundServiceState.running;
    }

    _updateState(BackgroundServiceState.starting);

    try {
      // Request necessary permissions
      final hasPermissions = await _requestPermissions();
      if (!hasPermissions) {
        _updateState(BackgroundServiceState.error);
        return false;
      }

      // Start native background service
      final result = await _channel.invokeMethod<bool>('startBackgroundService');
      
      if (result == true) {
        _updateState(BackgroundServiceState.running);
        
        // Start adaptive scanning based on battery
        final profile = await _batteryManager!.getCurrentProfile();
        _updateScanParameters(profile);
        
        return true;
      } else {
        _updateState(BackgroundServiceState.error);
        return false;
      }
    } catch (e) {
      print('[ZEFCP Background] Failed to start: $e');
      _updateState(BackgroundServiceState.error);
      return false;
    }
  }

  /// Stop background scanning service
  Future<void> stopBackground() async {
    if (_state == BackgroundServiceState.stopped ||
        _state == BackgroundServiceState.stopping) {
      return;
    }

    _updateState(BackgroundServiceState.stopping);

    try {
      _scanTimer?.cancel();
      _scanTimer = null;

      await _channel.invokeMethod('stopBackgroundService');
      _updateState(BackgroundServiceState.stopped);
    } catch (e) {
      print('[ZEFCP Background] Failed to stop: $e');
      _updateState(BackgroundServiceState.error);
    }
  }

  /// Update scan parameters based on battery profile
  void _updateScanParameters(BatteryProfile profile) {
    _scanTimer?.cancel();

    // Schedule periodic wake-ups based on battery mode
    final interval = profile.scanInterval;
    
    _scanTimer = Timer.periodic(interval, (_) {
      _performBackgroundScan(profile);
    });

    // Update native service with new parameters
    _channel.invokeMethod('updateScanParameters', {
      'scan_interval_ms': profile.scanInterval.inMilliseconds,
      'advertising_interval_ms': profile.advertisingInterval.inMilliseconds,
      'mode': profile.mode.toString(),
    });
  }

  /// Perform a background scan cycle
  void _performBackgroundScan(BatteryProfile profile) {
    // In a real implementation, this would trigger BLE scanning
    // For now, we rely on the native service to handle scanning
    print('[ZEFCP Background] Performing scan (mode: ${profile.mode})');
  }

  /// Request necessary permissions for background scanning
  Future<bool> _requestPermissions() async {
    try {
      // Request location permission (required for BLE scanning on Android)
      // Request Bluetooth permission
      final result = await _channel.invokeMethod<bool>('requestPermissions');
      return result ?? false;
    } catch (e) {
      print('[ZEFCP Background] Permission request failed: $e');
      return false;
    }
  }

  /// Update service state and notify listeners
  void _updateState(BackgroundServiceState newState) {
    if (_state != newState) {
      _state = newState;
      _stateController.add(newState);
    }
  }

  /// Dispose resources
  void dispose() {
    stopBackground();
    _batterySubscription?.cancel();
    _batteryManager?.dispose();
    _stateController.close();
  }
}
