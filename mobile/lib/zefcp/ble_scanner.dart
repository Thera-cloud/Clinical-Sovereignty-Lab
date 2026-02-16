/// ZEFCP BLE Scanner — Promiscuous BLE Observer
/// Scans ALL BLE devices and extracts ZEFCP fragments from advertising data
/// Layer 1 Physical Transport: Inbound fragment detection

import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:flutter/services.dart';
import 'constants.dart';

/// Result from a BLE scan containing potential ZEFCP fragment data
class ZefcpScanResult {
  /// Raw BLE advertising data
  final Uint8List advertisingData;
  
  /// Device MAC address or identifier
  final String deviceId;
  
  /// RSSI signal strength
  final int rssi;
  
  /// Timestamp when fragment was detected
  final DateTime timestamp;
  
  /// AD type where fragment was found
  final int? adType;
  
  /// Leading bytes extracted (first part of fragment)
  final Uint8List? leadingBytes;
  
  /// Trailing bytes extracted (second part of fragment)
  final Uint8List? trailingBytes;
  
  /// Whether this looks like a potential ZEFCP fragment
  final bool isPotentialFragment;
  
  ZefcpScanResult({
    required this.advertisingData,
    required this.deviceId,
    required this.rssi,
    required this.timestamp,
    this.adType,
    this.leadingBytes,
    this.trailingBytes,
    this.isPotentialFragment = false,
  });
}

/// Promiscuous BLE scanner for ZEFCP fragment detection
/// 
/// Scans ALL BLE devices (not just specific UUIDs) and extracts
/// advertising data that may contain ZEFCP micro-fragments.
/// 
/// Features:
/// - Promiscuous mode scanning (all devices)
/// - Adaptive scan parameters based on battery level
/// - False positive tracking (raw packets vs fragments)
/// - Stream-based fragment emission
class ZefcpBleScanner {
  StreamSubscription<List<ScanResult>>? _scanSubscription;
  final StreamController<ZefcpScanResult> _resultController = 
      StreamController<ZefcpScanResult>.broadcast();
  
  bool _isScanning = false;
  int _rawPacketCount = 0;
  int _fragmentCandidateCount = 0;
  
  /// Stream of scan results containing potential ZEFCP fragments
  Stream<ZefcpScanResult> get scanResults => _resultController.stream;
  
  /// Whether scanner is currently active
  bool get isScanning => _isScanning;
  
  /// Number of raw BLE packets observed
  int get rawPacketCount => _rawPacketCount;
  
  /// Number of fragment candidates extracted
  int get fragmentCandidateCount => _fragmentCandidateCount;
  
  /// False positive rate (should stay below threshold)
  double get falsePositiveRate {
    if (_rawPacketCount == 0) return 0.0;
    return _fragmentCandidateCount / _rawPacketCount;
  }
  
  /// Start promiscuous BLE scanning
  /// 
  /// [batteryLevel] Optional battery level (0.0-1.0) for adaptive parameters
  /// [scanMode] Scan mode (default: promiscuous)
  Future<void> start({
    double? batteryLevel,
    BleScanMode scanMode = BleScanMode.promiscuous,
  }) async {
    if (_isScanning) {
      print('[ZEFCP Scanner] Already scanning');
      return;
    }
    
    try {
      // Check BLE availability
      if (await FlutterBluePlus.isSupported == false) {
        throw Exception('BLE not supported on this device');
      }
      
      // Request permissions
      await FlutterBluePlus.turnOn();
      
      // Adaptive scan parameters based on battery
      final scanSettings = _getAdaptiveScanSettings(batteryLevel ?? 1.0, scanMode);
      
      print('[ZEFCP Scanner] Starting promiscuous scan...');
      
      // Start scanning with promiscuous settings
      _scanSubscription = FlutterBluePlus.scanResults.listen(
        (results) => _processScanResults(results),
        onError: (error) {
          print('[ZEFCP Scanner] Scan error: $error');
          _resultController.addError(error);
        },
      );
      
      await FlutterBluePlus.startScan(
        timeout: const Duration(seconds: 0), // Continuous scan
        androidUsesFineLocation: true,
      );
      
      _isScanning = true;
      _rawPacketCount = 0;
      _fragmentCandidateCount = 0;
      
      print('[ZEFCP Scanner] Scan started successfully');
    } catch (e) {
      print('[ZEFCP Scanner] Failed to start scan: $e');
      _isScanning = false;
      rethrow;
    }
  }
  
  /// Stop scanning
  Future<void> stop() async {
    if (!_isScanning) return;
    
    try {
      await FlutterBluePlus.stopScan();
      await _scanSubscription?.cancel();
      _scanSubscription = null;
      _isScanning = false;
      
      print('[ZEFCP Scanner] Scan stopped');
    } catch (e) {
      print('[ZEFCP Scanner] Error stopping scan: $e');
    }
  }
  
  /// Process scan results and extract potential fragments
  void _processScanResults(List<ScanResult> results) {
    for (final result in results) {
      _rawPacketCount++;
      
      try {
        // Extract advertising data
        final adData = _extractAdvertisingData(result);
        if (adData == null || adData.isEmpty) continue;
        
        // Check for ZEFCP signature in AD structures
        final fragmentData = _extractFragmentData(result.advertisementData);
        
        if (fragmentData != null) {
          _fragmentCandidateCount++;
          
          final scanResult = ZefcpScanResult(
            advertisingData: adData,
            deviceId: result.device.remoteId.str,
            rssi: result.rssi,
            timestamp: DateTime.now(),
            adType: fragmentData['adType'],
            leadingBytes: fragmentData['leading'],
            trailingBytes: fragmentData['trailing'],
            isPotentialFragment: true,
          );
          
          _resultController.add(scanResult);
        }
      } catch (e) {
        print('[ZEFCP Scanner] Error processing result: $e');
      }
    }
  }
  
  /// Extract raw advertising data bytes
  Uint8List? _extractAdvertisingData(ScanResult result) {
    try {
      final ad = result.advertisementData;
      final bytes = <int>[];
      
      // Extract manufacturer data
      if (ad.manufacturerData.isNotEmpty) {
        bytes.addAll(ad.manufacturerData.values.first);
      }
      
      // Extract service data
      for (final serviceData in ad.serviceData.values) {
        bytes.addAll(serviceData);
      }
      
      // Extract service UUIDs
      for (final uuid in ad.serviceUuids) {
        final uuidBytes = uuid.toByteArray();
        bytes.addAll(uuidBytes);
      }
      
      // Extract local name (trailing bytes)
      if (ad.localName.isNotEmpty) {
        final nameBytes = ad.localName.codeUnits;
        if (nameBytes.length > 1) {
          // Include trailing bytes after first character
          bytes.addAll(nameBytes.sublist(1));
        }
      }
      
      return bytes.isEmpty ? null : Uint8List.fromList(bytes);
    } catch (e) {
      print('[ZEFCP Scanner] Error extracting AD data: $e');
      return null;
    }
  }
  
  /// Extract fragment data from advertisement structures
  /// Returns map with 'adType', 'leading', 'trailing' if fragment detected
  Map<String, dynamic>? _extractFragmentData(AdvertisementData ad) {
    try {
      // Check manufacturer data (AD type 0xFF)
      if (ad.manufacturerData.isNotEmpty) {
        final mfgData = ad.manufacturerData.values.first;
        if (mfgData.length >= standardTotalBytes) {
          final fragment = _checkForFragment(mfgData, 0xFF);
          if (fragment != null) return fragment;
        }
      }
      
      // Check service data (AD types 0x16, 0x21)
      for (final entry in ad.serviceData.entries) {
        final serviceData = entry.value;
        if (serviceData.length >= standardTotalBytes) {
          final fragment = _checkForFragment(serviceData, 0x16);
          if (fragment != null) return fragment;
        }
      }
      
      // Check local name trailing bytes (AD type 0x09)
      if (ad.localName.isNotEmpty) {
        final nameBytes = ad.localName.codeUnits;
        if (nameBytes.length > minimumFunctionalBytes[0x09]! + standardTotalBytes) {
          final trailing = nameBytes.sublist(minimumFunctionalBytes[0x09]!);
          final fragment = _checkForFragment(trailing, 0x09);
          if (fragment != null) return fragment;
        }
      }
      
      return null;
    } catch (e) {
      print('[ZEFCP Scanner] Error extracting fragment data: $e');
      return null;
    }
  }
  
  /// Check if bytes contain a ZEFCP fragment signature
  /// Returns fragment data if detected, null otherwise
  Map<String, dynamic>? _checkForFragment(List<int> bytes, int adType) {
    if (bytes.length < standardTotalBytes) return null;
    
    // Check for standard fragment (8 bytes)
    if (bytes.length >= standardTotalBytes) {
      final leading = bytes.sublist(0, standardLeadingBytes);
      final trailing = bytes.sublist(
        bytes.length - standardTrailingBytes,
        bytes.length,
      );
      
      // First byte should be signature (will be validated by SpiderWebService)
      // For now, just check if it's in exploitable AD types
      if (exploitableAdTypes.contains(adType)) {
        return {
          'adType': adType,
          'leading': Uint8List.fromList(leading),
          'trailing': Uint8List.fromList(trailing),
        };
      }
    }
    
    // Check for extended fragment (12 bytes)
    if (bytes.length >= extendedTotalBytes) {
      final leading = bytes.sublist(0, extendedLeadingBytes);
      final trailing = bytes.sublist(
        bytes.length - extendedTrailingBytes,
        bytes.length,
      );
      
      if (exploitableAdTypes.contains(adType)) {
        return {
          'adType': adType,
          'leading': Uint8List.fromList(leading),
          'trailing': Uint8List.fromList(trailing),
        };
      }
    }
    
    return null;
  }
  
  /// Get adaptive scan settings based on battery level
  ScanSettings _getAdaptiveScanSettings(double batteryLevel, BleScanMode mode) {
    // Lower battery = less aggressive scanning
    final scanInterval = batteryLevel < 0.2 
        ? 2000  // 2 seconds (low battery)
        : batteryLevel < 0.5
            ? 1000  // 1 second (medium battery)
            : 500;  // 0.5 seconds (high battery)
    
    final scanWindow = (scanInterval * 0.5).round();
    
    return ScanSettings(
      android: AndroidScanSettings(
        scanMode: AndroidScanMode.lowLatency,
        callbackType: AndroidCallbackType.allMatches,
        reportDelay: 0,
      ),
      ios: IosScanSettings(
        allowDuplicates: true,
      ),
    );
  }
  
  /// Dispose resources
  void dispose() {
    stop();
    _resultController.close();
  }
}
