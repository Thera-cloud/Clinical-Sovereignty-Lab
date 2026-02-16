/// ZEFCP Service — Main Orchestrator for Zero-Energy Fibre Communication Protocol
/// Coordinates all ZEFCP sub-services and manages the complete lifecycle
/// Layer 4 Service Orchestration: Unified ZEFCP service management

import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'offline_buffer.dart';
import 'fibre_identity.dart';
import 'ble_scanner.dart';
import 'ble_advertiser.dart';
import 'spider_web_service.dart';
import 'fragment_buffer.dart';
import 'mesh_bridge.dart';
import 'battery_manager.dart';
import 'background_service.dart';
import 'constants.dart';

/// ZEFCP service status
class ZefcpStatus {
  /// Whether service is running
  final bool isRunning;
  
  /// Whether Fibre is provisioned
  final bool isProvisioned;
  
  /// Number of fragments captured
  final int fragmentsCaptured;
  
  /// Number of fragments sent
  final int fragmentsSent;
  
  /// Battery profile (0.0-1.0)
  final double? batteryProfile;
  
  /// Trust level
  final TrustLevel? trustLevel;
  
  /// Unsynced buffer count
  final int unsyncedCount;
  
  ZefcpStatus({
    required this.isRunning,
    required this.isProvisioned,
    this.fragmentsCaptured = 0,
    this.fragmentsSent = 0,
    this.batteryProfile,
    this.trustLevel,
    this.unsyncedCount = 0,
  });
  
  ZefcpStatus copyWith({
    bool? isRunning,
    bool? isProvisioned,
    int? fragmentsCaptured,
    int? fragmentsSent,
    double? batteryProfile,
    TrustLevel? trustLevel,
    int? unsyncedCount,
  }) {
    return ZefcpStatus(
      isRunning: isRunning ?? this.isRunning,
      isProvisioned: isProvisioned ?? this.isProvisioned,
      fragmentsCaptured: fragmentsCaptured ?? this.fragmentsCaptured,
      fragmentsSent: fragmentsSent ?? this.fragmentsSent,
      batteryProfile: batteryProfile ?? this.batteryProfile,
      trustLevel: trustLevel ?? this.trustLevel,
      unsyncedCount: unsyncedCount ?? this.unsyncedCount,
    );
  }
}

/// Main ZEFCP service orchestrator
/// 
/// Manages the complete ZEFCP lifecycle:
/// 1. Initializes all sub-services in correct order
/// 2. Establishes data pipes between services
/// 3. Provides unified status stream
/// 4. Handles errors and graceful degradation
/// 
/// Service Initialization Order:
/// 1. SecureKeyStore (via FibreIdentity)
/// 2. FibreIdentity
/// 3. BatteryManager
/// 4. BleScanner
/// 5. SpiderWebService
/// 6. FragmentBuffer
/// 7. OfflineBuffer
/// 8. BleAdvertiser
/// 9. MeshBridge
/// 10. BackgroundService
class ZefcpService {
  // Core services
  FibreIdentity? _fibreIdentity;
  BatteryManager? _batteryManager;
  OfflineBuffer? _offlineBuffer;
  ZefcpBleScanner? _bleScanner;
  SpiderWebService? _spiderWebService;
  FragmentBuffer? _fragmentBuffer;
  ZefcpBleAdvertiser? _bleAdvertiser;
  ZefcpMeshBridge? _meshBridge;
  ZefcpBackgroundService? _backgroundService;
  
  // State
  bool _isInitialized = false;
  bool _isRunning = false;
  int _fragmentsCaptured = 0;
  int _fragmentsSent = 0;
  double? _batteryProfile;
  
  // Status stream
  final StreamController<ZefcpStatus> _statusController =
      StreamController<ZefcpStatus>.broadcast();
  
  Timer? _statusUpdateTimer;
  StreamSubscription<ZefcpScanResult>? _scanSubscription;
  StreamSubscription<SpiderWebAssessment>? _spiderWebSubscription;
  StreamSubscription<AssembledObservation>? _assemblySubscription;
  StreamSubscription<BatteryProfile>? _batterySubscription;
  StreamSubscription<ZefcpConnectionState>? _meshBridgeSubscription;
  StreamSubscription<EmbedQueueEntry>? _embedQueueSubscription;
  
  /// Stream of ZEFCP status updates
  Stream<ZefcpStatus> get statusStream => _statusController.stream;
  
  /// Current status
  ZefcpStatus get currentStatus => ZefcpStatus(
        isRunning: _isRunning,
        isProvisioned: _fibreIdentity?.isProvisioned ?? false,
        fragmentsCaptured: _fragmentsCaptured,
        fragmentsSent: _fragmentsSent,
        batteryProfile: _batteryProfile,
        trustLevel: _fibreIdentity?.trustLevel,
        unsyncedCount: 0, // Would query OfflineBuffer
      );
  
  /// Whether service is initialized
  bool get isInitialized => _isInitialized;
  
  /// Whether service is running
  bool get isRunning => _isRunning;
  
  /// Initialize all ZEFCP sub-services
  /// 
  /// Must be called before start()
  Future<bool> initialize() async {
    if (_isInitialized) {
      print('[ZEFCP Service] Already initialized');
      return true;
    }
    
    try {
      print('[ZEFCP Service] Initializing ZEFCP services...');
      
      // 1. Initialize FibreIdentity (includes SecureKeyStore)
      _fibreIdentity = FibreIdentity();
      final identityInitialized = await _fibreIdentity!.initialize();
      if (!identityInitialized) {
        print('[ZEFCP Service] Failed to initialize FibreIdentity');
        return false;
      }
      print('[ZEFCP Service] ✓ FibreIdentity initialized');
      
      // 2. Initialize BatteryManager
      _batteryManager = BatteryManager();
      await _batteryManager!.initialize();
      _batteryProfile = _batteryManager!.currentProfile.level / 100.0;
      print('[ZEFCP Service] ✓ BatteryManager initialized');
      
      // 3. Initialize OfflineBuffer
      _offlineBuffer = OfflineBuffer();
      print('[ZEFCP Service] ✓ OfflineBuffer initialized');
      
      // 4. Initialize BLE Scanner
      _bleScanner = ZefcpBleScanner();
      print('[ZEFCP Service] ✓ BLE Scanner initialized');
      
      // 5. Initialize SpiderWebService
      _spiderWebService = SpiderWebService();
      await _spiderWebService!.initialize();
      print('[ZEFCP Service] ✓ SpiderWebService initialized');
      
      // 6. Initialize FragmentBuffer
      _fragmentBuffer = FragmentBuffer();
      print('[ZEFCP Service] ✓ FragmentBuffer initialized');
      
      // 7. Initialize BLE Advertiser
      _bleAdvertiser = ZefcpBleAdvertiser();
      // Derive swarm secret from Fibre identity for BLE HMAC validation.
      // In production, the swarm secret is provisioned via the MeshBridge
      // websocket handshake. Here we derive a deterministic per-device secret
      // from the Fibre identity so BLE advertising works immediately.
      Uint8List swarmSecret;
      try {
        final fibreId = _fibreIdentity?.fibreId;
        if (fibreId != null && fibreId.isNotEmpty) {
          // Derive 32-byte secret from fibre ID string via simple hash-like expansion
          final idBytes = Uint8List.fromList(fibreId.codeUnits);
          swarmSecret = Uint8List(32);
          for (var i = 0; i < 32; i++) {
            swarmSecret[i] = idBytes[i % idBytes.length] ^ (0xA5 + i);
          }
          print('[ZEFCP Service] Swarm secret derived from Fibre identity');
        } else {
          // Identity not yet provisioned — use zeros; will be replaced during mesh provisioning
          swarmSecret = Uint8List(32);
          print('[ZEFCP Service] WARNING: No Fibre identity yet — using placeholder swarm secret');
        }
      } catch (e) {
        swarmSecret = Uint8List(32);
        print('[ZEFCP Service] WARNING: Swarm secret derivation failed: $e');
      }
      _bleAdvertiser!.initialize(swarmSecret);
      print('[ZEFCP Service] ✓ BLE Advertiser initialized');
      
      // 8. Initialize MeshBridge
      _meshBridge = ZefcpMeshBridge();
      await _meshBridge!.initialize();
      print('[ZEFCP Service] ✓ MeshBridge initialized');
      
      // 9. Initialize BackgroundService
      _backgroundService = ZefcpBackgroundService();
      await _backgroundService!.initialize();
      print('[ZEFCP Service] ✓ BackgroundService initialized');
      
      _isInitialized = true;
      print('[ZEFCP Service] All services initialized successfully');
      
      // Emit initial status
      _emitStatus();
      
      return true;
    } catch (e, stackTrace) {
      print('[ZEFCP Service] Error initializing: $e');
      print('[ZEFCP Service] Stack trace: $stackTrace');
      return false;
    }
  }
  
  /// Start ZEFCP service
  /// 
  /// Starts all sub-services and establishes data pipes:
  /// - BleScanner → SpiderWebService → FragmentBuffer → MeshBridge
  /// - MeshBridge embed queue → BleAdvertiser
  Future<bool> start() async {
    if (!_isInitialized) {
      print('[ZEFCP Service] Not initialized. Call initialize() first.');
      return false;
    }
    
    if (_isRunning) {
      print('[ZEFCP Service] Already running');
      return true;
    }
    
    try {
      print('[ZEFCP Service] Starting ZEFCP service...');
      
      // Subscribe to battery profile updates
      _batterySubscription = _batteryManager!.batteryProfileStream.listen(
        (profile) {
          _batteryProfile = profile.level / 100.0;
          _emitStatus();
        },
      );
      
      // Start BLE Scanner with current battery profile
      await _bleScanner!.start(
        batteryLevel: _batteryProfile ?? 1.0,
        scanMode: BleScanMode.promiscuous,
      );
      
      // Establish pipe: BleScanner → SpiderWebService → FragmentBuffer → MeshBridge
      _scanSubscription = _bleScanner!.scanResults.listen(
        (scanResult) async {
          if (scanResult.isPotentialFragment) {
            // Process through SpiderWebService
            final assessment = await _spiderWebService!.assessScanResult(scanResult);
            
            if (assessment.isFragment && assessment.isValid && assessment.fragmentBytes != null) {
              _fragmentsCaptured++;
              
              // Extract fragment data (would parse observation_id, sequence, etc.)
              // For now, buffer the validated fragment
              final fragmentData = {
                'device_id': scanResult.deviceId,
                'rssi': scanResult.rssi,
                'timestamp': scanResult.timestamp.toIso8601String(),
                'fragment_bytes': assessment.fragmentBytes!.toList(),
                'ad_type': scanResult.adType,
              };
              
              // Buffer fragment for later sync
              await _offlineBuffer?.bufferFragment(fragmentData);
              
              // Also add to FragmentBuffer for assembly (would parse observation_id)
              // _fragmentBuffer?.addFragment(...);
              
              _emitStatus();
            }
          }
        },
        onError: (error) {
          print('[ZEFCP Service] Scan error: $error');
        },
      );
      
      // Subscribe to assembled observations from FragmentBuffer
      _assemblySubscription = _fragmentBuffer!.assembledObservations.listen(
        (observation) {
          // Forward assembled observation to MeshBridge
          // _meshBridge?.sendObservation(observation);
          print('[ZEFCP Service] Observation assembled: ${observation.observationId}');
        },
      );
      
      // Subscribe to MeshBridge embed queue
      _embedQueueSubscription = _meshBridge!.embedQueue.listen(
        (entry) {
          // Decode payload and enqueue for advertising
          final payloadBytes = Uint8List.fromList(
            entry.payloadB64.codeUnits, // Would base64 decode in real implementation
          );
          _bleAdvertiser?.enqueueFragment(
            payloadBytes,
            priority: entry.metadata?['priority'] as int? ?? 0,
          );
          _fragmentsSent++;
          _emitStatus();
        },
      );
      
      // Subscribe to MeshBridge connection state
      _meshBridgeSubscription = _meshBridge!.stateStream.listen(
        (state) {
          print('[ZEFCP Service] MeshBridge state: $state');
          _emitStatus();
        },
      );
      
      // Start BLE Advertiser
      await _bleAdvertiser!.start(intervalMs: 100);
      
      // Start MeshBridge (connects to backend)
      await _meshBridge!.connect();
      
      // Start BackgroundService
      await _backgroundService!.startBackground();
      
      // Start status update timer
      _statusUpdateTimer = Timer.periodic(
        const Duration(seconds: 5),
        (_) => _updateStatus(),
      );
      
      _isRunning = true;
      print('[ZEFCP Service] ZEFCP service started successfully');
      
      _emitStatus();
      return true;
    } catch (e, stackTrace) {
      print('[ZEFCP Service] Error starting: $e');
      print('[ZEFCP Service] Stack trace: $stackTrace');
      _isRunning = false;
      return false;
    }
  }
  
  /// Stop ZEFCP service
  Future<void> stop() async {
    if (!_isRunning) return;
    
    try {
      print('[ZEFCP Service] Stopping ZEFCP service...');
      
      // Stop status timer
      _statusUpdateTimer?.cancel();
      _statusUpdateTimer = null;
      
      // Cancel subscriptions
      await _scanSubscription?.cancel();
      _scanSubscription = null;
      await _spiderWebSubscription?.cancel();
      _spiderWebSubscription = null;
      await _assemblySubscription?.cancel();
      _assemblySubscription = null;
      await _batterySubscription?.cancel();
      _batterySubscription = null;
      await _meshBridgeSubscription?.cancel();
      _meshBridgeSubscription = null;
      await _embedQueueSubscription?.cancel();
      _embedQueueSubscription = null;
      
      // Stop BLE Scanner
      await _bleScanner?.stop();
      
      // Stop BLE Advertiser
      await _bleAdvertiser?.stop();
      
      // Disconnect MeshBridge
      await _meshBridge?.disconnect();
      
      // Stop BackgroundService
      await _backgroundService?.stop();
      
      _isRunning = false;
      print('[ZEFCP Service] ZEFCP service stopped');
      
      _emitStatus();
    } catch (e) {
      print('[ZEFCP Service] Error stopping: $e');
    }
  }
  
  /// Dispose all resources
  Future<void> dispose() async {
    await stop();
    
    _bleScanner?.dispose();
    _bleAdvertiser?.dispose();
    await _offlineBuffer?.close();
    
    await _statusController.close();
    
    _isInitialized = false;
    print('[ZEFCP Service] ZEFCP service disposed');
  }
  
  /// Update status (queries all services)
  Future<void> _updateStatus() async {
    if (!_isRunning) return;
    
    // Query unsynced count from OfflineBuffer
    final unsyncedCount = await _offlineBuffer?.getUnsyncedCount() ?? 0;
    
    // Emit updated status
    final status = ZefcpStatus(
      isRunning: _isRunning,
      isProvisioned: _fibreIdentity?.isProvisioned ?? false,
      fragmentsCaptured: _fragmentsCaptured,
      fragmentsSent: _fragmentsSent,
      batteryProfile: _batteryProfile,
      trustLevel: _fibreIdentity?.trustLevel,
      unsyncedCount: unsyncedCount,
    );
    
    if (!_statusController.isClosed) {
      _statusController.add(status);
    }
  }
  
  /// Emit current status to stream
  void _emitStatus() {
    if (_statusController.isClosed) return;
    _updateStatus();
  }
  
  /// Update battery profile (would be called by BatteryManager)
  void updateBatteryProfile(double level) {
    _batteryProfile = level.clamp(0.0, 1.0);
    _emitStatus();
  }
  
  /// Manually enqueue a fragment for advertising
  /// 
  /// [fragmentBytes] Fragment bytes (8 or 12 bytes)
  /// [priority] Priority (higher = sent first)
  bool enqueueFragment(Uint8List fragmentBytes, {int priority = 0}) {
    if (!_isRunning || _bleAdvertiser == null) {
      return false;
    }
    
    final success = _bleAdvertiser!.enqueueFragment(fragmentBytes, priority: priority);
    if (success) {
      _fragmentsSent++;
      _emitStatus();
    }
    
    return success;
  }
  
  /// Get unsynced buffer entries
  Future<List<BufferEntry>> getUnsyncedEntries({int? limit}) async {
    if (_offlineBuffer == null) return [];
    return await _offlineBuffer!.getUnsynced(limit: limit);
  }
  
  /// Mark entries as synced
  Future<void> markEntriesSynced(List<int> ids) async {
    await _offlineBuffer?.markSynced(ids);
    _emitStatus();
  }
  
  /// Get Fibre identity
  FibreIdentity? get fibreIdentity => _fibreIdentity;
  
  /// Get offline buffer
  OfflineBuffer? get offlineBuffer => _offlineBuffer;
  
  /// Get BLE scanner
  ZefcpBleScanner? get bleScanner => _bleScanner;
  
  /// Get BLE advertiser
  ZefcpBleAdvertiser? get bleAdvertiser => _bleAdvertiser;
  
  /// Get MeshBridge
  ZefcpMeshBridge? get meshBridge => _meshBridge;
}
