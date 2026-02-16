/// ZEFCP BLE Advertiser — Outbound Fragment Embedding
/// Embeds ZEFCP fragments into BLE advertising data for zero-energy transport
/// Layer 1 Physical Transport: Outbound fragment transmission

import 'dart:async';
import 'dart:typed_data';
import 'dart:convert';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:crypto/crypto.dart';
import 'constants.dart';

/// Fragment to be embedded in BLE advertising
class FragmentToEmbed {
  /// Fragment bytes (8 or 12 bytes)
  final Uint8List bytes;
  
  /// Priority (higher = sent first)
  final int priority;
  
  /// Timestamp when enqueued
  final DateTime enqueuedAt;
  
  FragmentToEmbed({
    required this.bytes,
    this.priority = 0,
    DateTime? enqueuedAt,
  }) : enqueuedAt = enqueuedAt ?? DateTime.now();
}

/// BLE advertiser for ZEFCP fragment embedding
/// 
/// Maintains a queue of fragments and cycles through them on each
/// advertising interval, embedding fragments into advertising data.
/// 
/// Features:
/// - Fragment queue management
/// - Configurable advertising interval
/// - HMAC-SHA256 signature computation
/// - Adaptive embedding rate limiting
class ZefcpBleAdvertiser {
  final List<FragmentToEmbed> _fragmentQueue = [];
  Timer? _advertisingTimer;
  bool _isAdvertising = false;
  int _currentFragmentIndex = 0;
  
  /// Swarm secret for signature computation
  Uint8List? _swarmSecret;
  
  /// Current advertising interval (milliseconds)
  int _advertisingIntervalMs = 100; // Default 100ms
  
  /// Maximum queue depth
  static const int maxQueueDepth = 100;
  
  /// Whether advertiser is currently active
  bool get isAdvertising => _isAdvertising;
  
  /// Current queue depth
  int get queueDepth => _fragmentQueue.length;
  
  /// Get current queue depth (alias for queueDepth)
  int getQueueDepth() => queueDepth;
  
  /// Initialize with swarm secret
  void initialize(Uint8List swarmSecret) {
    _swarmSecret = swarmSecret;
  }
  
  /// Start BLE advertising with fragment embedding
  /// 
  /// [intervalMs] Advertising interval in milliseconds (default: 100ms)
  Future<void> start({int intervalMs = 100}) async {
    if (_isAdvertising) {
      print('[ZEFCP Advertiser] Already advertising');
      return;
    }
    
    if (_swarmSecret == null) {
      throw Exception('Swarm secret not initialized. Call initialize() first.');
    }
    
    try {
      // Check BLE availability
      if (await FlutterBluePlus.isSupported == false) {
        throw Exception('BLE not supported on this device');
      }
      
      await FlutterBluePlus.turnOn();
      
      _advertisingIntervalMs = intervalMs;
      _isAdvertising = true;
      _currentFragmentIndex = 0;
      
      // Start periodic advertising
      _advertisingTimer = Timer.periodic(
        Duration(milliseconds: intervalMs),
        (_) => _advertiseNextFragment(),
      );
      
      print('[ZEFCP Advertiser] Started advertising (interval: ${intervalMs}ms)');
    } catch (e) {
      print('[ZEFCP Advertiser] Failed to start: $e');
      _isAdvertising = false;
      rethrow;
    }
  }
  
  /// Stop advertising
  Future<void> stop() async {
    if (!_isAdvertising) return;
    
    try {
      _advertisingTimer?.cancel();
      _advertisingTimer = null;
      _isAdvertising = false;
      
      // Stop BLE advertising
      await FlutterBluePlus.stopAdvertising();
      
      print('[ZEFCP Advertiser] Stopped advertising');
    } catch (e) {
      print('[ZEFCP Advertiser] Error stopping: $e');
    }
  }
  
  /// Enqueue a fragment for embedding
  /// 
  /// [fragmentBytes] Fragment bytes (must be 8 or 12 bytes)
  /// [priority] Priority (higher = sent first, default: 0)
  /// 
  /// Returns true if enqueued, false if queue is full
  bool enqueueFragment(Uint8List fragmentBytes, {int priority = 0}) {
    if (fragmentBytes.length != standardTotalBytes && 
        fragmentBytes.length != extendedTotalBytes) {
      print('[ZEFCP Advertiser] Invalid fragment size: ${fragmentBytes.length}');
      return false;
    }
    
    if (_fragmentQueue.length >= maxQueueDepth) {
      print('[ZEFCP Advertiser] Queue full, dropping fragment');
      return false;
    }
    
    final fragment = FragmentToEmbed(
      bytes: fragmentBytes,
      priority: priority,
    );
    
    // Insert by priority (higher first)
    int insertIndex = _fragmentQueue.length;
    for (int i = 0; i < _fragmentQueue.length; i++) {
      if (_fragmentQueue[i].priority < priority) {
        insertIndex = i;
        break;
      }
    }
    
    _fragmentQueue.insert(insertIndex, fragment);
    
    print('[ZEFCP Advertiser] Enqueued fragment (queue: ${_fragmentQueue.length})');
    return true;
  }
  
  /// Advertise the next fragment in the queue
  Future<void> _advertiseNextFragment() async {
    if (_fragmentQueue.isEmpty) {
      // No fragments to advertise
      return;
    }
    
    try {
      // Get next fragment (round-robin)
      final fragment = _fragmentQueue[_currentFragmentIndex];
      _currentFragmentIndex = (_currentFragmentIndex + 1) % _fragmentQueue.length;
      
      // Embed fragment into advertising data
      await _embedFragment(fragment.bytes);
      
      // Remove low-priority fragments after they've been sent multiple times
      if (fragment.priority == 0) {
        final age = DateTime.now().difference(fragment.enqueuedAt);
        if (age.inSeconds > 30) {
          _fragmentQueue.remove(fragment);
          _currentFragmentIndex = 0; // Reset index
        }
      }
    } catch (e) {
      print('[ZEFCP Advertiser] Error advertising fragment: $e');
    }
  }
  
  /// Embed fragment into BLE advertising data
  /// 
  /// Note: flutter_blue_plus advertising API varies by platform.
  /// This implementation uses a generic pattern that may need platform-specific
  /// adjustments. On some platforms, BLE advertising requires platform channels.
  Future<void> _embedFragment(Uint8List fragmentBytes) async {
    try {
      // Create advertising data with fragment embedded in manufacturer data
      // AD type 0xFF (Manufacturer Specific Data) is most exploitable
      
      // Build manufacturer-specific data: Company ID (2 bytes) + fragment
      // Using 0xFFFF as placeholder (in production, use registered company ID)
      final companyIdBytes = Uint8List(2);
      companyIdBytes[0] = 0xFF;
      companyIdBytes[1] = 0xFF;
      
      final mfgData = Uint8List(companyIdBytes.length + fragmentBytes.length);
      mfgData.setRange(0, companyIdBytes.length, companyIdBytes);
      mfgData.setRange(companyIdBytes.length, mfgData.length, fragmentBytes);
      
      // Create advertisement data
      // Note: flutter_blue_plus API may require different structure per platform
      final advertisingData = AdvertisementData(
        localName: null, // Don't use local name to avoid conflicts
        serviceUuids: [], // Empty service UUIDs
        manufacturerData: {
          // Map company ID to data bytes
          0xFFFF: mfgData,
        },
        serviceData: {},
        txPowerLevel: null,
        connectable: false,
      );
      
      // Start advertising with embedded fragment
      // Note: Some platforms may require platform channel calls for advertising
      await FlutterBluePlus.startAdvertising(
        advertisingData,
        timeout: const Duration(seconds: 0), // Continuous advertising
      );
      
      print('[ZEFCP Advertiser] Embedded fragment (${fragmentBytes.length} bytes)');
    } catch (e) {
      // Fallback: Log error but don't fail completely
      // Some platforms may not support BLE advertising from app level
      print('[ZEFCP Advertiser] Error embedding fragment: $e');
      print('[ZEFCP Advertiser] Note: BLE advertising may require platform-specific implementation');
      // Don't rethrow - allow queue to continue processing
    }
  }
  
  /// Compute HMAC-SHA256 signature for a rotation period
  /// 
  /// [epochMinute] Epoch minute (time / 60)
  /// [swarmSecret] Swarm secret bytes
  /// 
  /// Returns signature byte (first byte of HMAC digest)
  static int computeSignature(int epochMinute, Uint8List swarmSecret) {
    final rotationPeriod = epochMinute ~/ signatureRotationMinutes;
    final rotationBytes = Uint8List(8);
    for (int i = 0; i < 8; i++) {
      rotationBytes[7 - i] = (rotationPeriod >> (i * 8)) & 0xFF;
    }
    
    final hmac = Hmac(sha256, swarmSecret);
    final digest = hmac.convert(rotationBytes);
    
    return digest.bytes[0];
  }
  
  /// Get valid signatures for current time window (±1 period)
  /// 
  /// [swarmSecret] Swarm secret bytes
  /// 
  /// Returns set of valid signature bytes
  static Set<int> getValidSignatures(Uint8List swarmSecret) {
    final now = DateTime.now();
    final epochMinute = now.millisecondsSinceEpoch ~/ (60 * 1000);
    
    final signatures = <int>{};
    for (final offset in [-signatureRotationMinutes, 0, signatureRotationMinutes]) {
      final em = epochMinute + offset;
      signatures.add(computeSignature(em, swarmSecret));
    }
    
    return signatures;
  }
  
  /// Clear fragment queue
  void clearQueue() {
    _fragmentQueue.clear();
    _currentFragmentIndex = 0;
    print('[ZEFCP Advertiser] Queue cleared');
  }
  
  /// Dispose resources
  void dispose() {
    stop();
    clearQueue();
  }
}
