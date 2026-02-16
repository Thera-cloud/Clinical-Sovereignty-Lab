/// ZEFCP Spider Web Service — Per-PDU Threat Assessment
/// Mobile-side Spider Web detector for validating BLE scan results
/// Validates HMAC-SHA256 signatures and CRC-8 integrity

import 'dart:typed_data';
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'constants.dart';
import 'ble_scanner.dart';

/// Threat level assessment for a BLE PDU
enum SpiderThreatLevel {
  /// Clean fragment (valid signature and CRC)
  clean,
  
  /// Suspicious (signature mismatch or structural anomaly)
  suspicious,
  
  /// Hostile (malicious or attack pattern detected)
  hostile,
}

/// Assessment result from Spider Web validation
class SpiderWebAssessment {
  /// Whether this appears to be a ZEFCP fragment
  final bool isFragment;
  
  /// Whether fragment is valid (signature + CRC pass)
  final bool isValid;
  
  /// Threat level assessment
  final SpiderThreatLevel threatLevel;
  
  /// Decoded fragment bytes (if valid)
  final Uint8List? fragmentBytes;
  
  /// Reason for assessment
  final String? reason;
  
  SpiderWebAssessment({
    required this.isFragment,
    required this.isValid,
    required this.threatLevel,
    this.fragmentBytes,
    this.reason,
  });
}

/// Spider Web Service — Per-PDU threat assessment
/// 
/// Validates each BLE scan result for ZEFCP fragment presence,
/// checks HMAC-SHA256 signature validity, and computes CRC-8
/// for data integrity.
/// 
/// Features:
/// - Signature validation with rotation window
/// - CRC-8 integrity checking
/// - False positive rate tracking
/// - Secure key storage integration
class SpiderWebService {
  final FlutterSecureStorage _secureStorage = const FlutterSecureStorage();
  
  Uint8List? _swarmSecret;
  int _totalPdusProcessed = 0;
  int _fragmentsDetected = 0;
  int _validFragments = 0;
  int _falsePositives = 0;
  
  /// Key name for swarm secret in secure storage
  static const String swarmSecretKey = 'zefcp_swarm_secret';
  
  /// Total PDUs processed
  int get totalPdusProcessed => _totalPdusProcessed;
  
  /// Fragments detected
  int get fragmentsDetected => _fragmentsDetected;
  
  /// Valid fragments (passed all checks)
  int get validFragments => _validFragments;
  
  /// False positive rate
  double get falsePositiveRate {
    if (_totalPdusProcessed == 0) return 0.0;
    return _falsePositives / _totalPdusProcessed;
  }
  
  /// Initialize service and load swarm secret
  Future<void> initialize() async {
    try {
      final secretString = await _secureStorage.read(key: swarmSecretKey);
      if (secretString != null) {
        _swarmSecret = base64Decode(secretString);
        print('[Spider Web] Swarm secret loaded');
      } else {
        print('[Spider Web] Warning: No swarm secret found');
      }
    } catch (e) {
      print('[Spider Web] Error loading swarm secret: $e');
    }
  }
  
  /// Set swarm secret (typically from NFC provisioning)
  Future<void> setSwarmSecret(Uint8List secret) async {
    _swarmSecret = secret;
    try {
      await _secureStorage.write(
        key: swarmSecretKey,
        value: base64Encode(secret),
      );
      print('[Spider Web] Swarm secret stored');
    } catch (e) {
      print('[Spider Web] Error storing swarm secret: $e');
    }
  }
  
  /// Assess a BLE scan result for ZEFCP fragment presence
  /// 
  /// [scanResult] BLE scan result to assess
  /// 
  /// Returns assessment with validation results
  Future<SpiderWebAssessment> assessScanResult(ZefcpScanResult scanResult) async {
    _totalPdusProcessed++;
    
    // Check if this looks like a fragment
    if (!scanResult.isPotentialFragment || 
        scanResult.leadingBytes == null || 
        scanResult.trailingBytes == null) {
      return SpiderWebAssessment(
        isFragment: false,
        isValid: false,
        threatLevel: SpiderThreatLevel.clean,
        reason: 'Not a fragment candidate',
      );
    }
    
    _fragmentsDetected++;
    
    // Combine leading and trailing bytes
    final combined = Uint8List(
      scanResult.leadingBytes!.length + scanResult.trailingBytes!.length,
    );
    combined.setRange(0, scanResult.leadingBytes!.length, scanResult.leadingBytes!);
    combined.setRange(
      scanResult.leadingBytes!.length,
      combined.length,
      scanResult.trailingBytes!,
    );
    
    // Validate fragment structure
    final assessment = await _validateFragment(combined);
    
    if (assessment.isValid) {
      _validFragments++;
    } else {
      _falsePositives++;
      
      // Check false positive rate threshold
      if (falsePositiveRate > spiderWebFalsePositiveThreshold) {
        print('[Spider Web] Warning: False positive rate exceeded threshold: $falsePositiveRate');
      }
    }
    
    return assessment;
  }
  
  /// Validate fragment bytes (signature + CRC)
  Future<SpiderWebAssessment> _validateFragment(Uint8List fragmentBytes) async {
    if (_swarmSecret == null) {
      return SpiderWebAssessment(
        isFragment: true,
        isValid: false,
        threatLevel: SpiderThreatLevel.suspicious,
        reason: 'Swarm secret not available',
      );
    }
    
    // Check fragment length
    if (fragmentBytes.length != standardTotalBytes && 
        fragmentBytes.length != extendedTotalBytes) {
      return SpiderWebAssessment(
        isFragment: false,
        isValid: false,
        threatLevel: SpiderThreatLevel.clean,
        reason: 'Invalid fragment length: ${fragmentBytes.length}',
      );
    }
    
    // Extract signature byte (first byte)
    final signatureByte = fragmentBytes[0];
    
    // Validate signature
    final validSignatures = _getValidSignatures();
    if (!validSignatures.contains(signatureByte)) {
      return SpiderWebAssessment(
        isFragment: true,
        isValid: false,
        threatLevel: SpiderThreatLevel.suspicious,
        reason: 'Signature mismatch (got: 0x${signatureByte.toRadixString(16)}, valid: ${validSignatures.map((s) => '0x${s.toRadixString(16)}').join(', ')})',
      );
    }
    
    // Validate CRC-8
    final dataPart = fragmentBytes.sublist(0, fragmentBytes.length - 1);
    final storedChecksum = fragmentBytes[fragmentBytes.length - 1];
    final computedChecksum = _computeCrc8(dataPart);
    
    if (computedChecksum != storedChecksum) {
      return SpiderWebAssessment(
        isFragment: true,
        isValid: false,
        threatLevel: SpiderThreatLevel.suspicious,
        reason: 'CRC-8 mismatch (stored: 0x${storedChecksum.toRadixString(16)}, computed: 0x${computedChecksum.toRadixString(16)})',
      );
    }
    
    // Fragment is valid
    return SpiderWebAssessment(
      isFragment: true,
      isValid: true,
      threatLevel: SpiderThreatLevel.clean,
      fragmentBytes: fragmentBytes,
      reason: 'Valid fragment',
    );
  }
  
  /// Compute CRC-8 checksum
  /// 
  /// [data] Data bytes to checksum
  /// 
  /// Returns CRC-8 value
  int _computeCrc8(Uint8List data) {
    int crc = crc8Init;
    final poly = crc8Polynomial;
    
    for (final byte in data) {
      crc ^= byte;
      for (int i = 0; i < 8; i++) {
        if (crc & 0x80 != 0) {
          crc = (crc << 1) ^ poly;
        } else {
          crc <<= 1;
        }
        crc &= 0xFF;
      }
    }
    
    return crc;
  }
  
  /// Get valid signatures for current time window (±1 period)
  Set<int> _getValidSignatures() {
    if (_swarmSecret == null) return {};
    
    final now = DateTime.now();
    final epochMinute = now.millisecondsSinceEpoch ~/ (60 * 1000);
    
    final signatures = <int>{};
    for (final offset in [-signatureRotationMinutes, 0, signatureRotationMinutes]) {
      final em = epochMinute + offset;
      signatures.add(_computeSignature(em));
    }
    
    return signatures;
  }
  
  /// Compute signature for an epoch minute
  int _computeSignature(int epochMinute) {
    if (_swarmSecret == null) return 0;
    
    final rotationPeriod = epochMinute ~/ signatureRotationMinutes;
    final rotationBytes = Uint8List(8);
    for (int i = 0; i < 8; i++) {
      rotationBytes[7 - i] = (rotationPeriod >> (i * 8)) & 0xFF;
    }
    
    final hmac = Hmac(sha256, _swarmSecret!);
    final digest = hmac.convert(rotationBytes);
    
    return digest.bytes[0];
  }
  
  /// Reset statistics
  void resetStats() {
    _totalPdusProcessed = 0;
    _fragmentsDetected = 0;
    _validFragments = 0;
    _falsePositives = 0;
  }
}
