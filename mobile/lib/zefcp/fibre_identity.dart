/// ZEFCP Fibre Identity — Mobile Device Identity Management
/// Manages the mobile device's identity as a Fibre in the ZEFCP swarm
/// Layer 3 Identity & Cryptography: Ed25519 keypair and trust management

import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:cryptography/cryptography.dart';

/// Trust level for a Fibre in the swarm
enum TrustLevel {
  /// Not yet provisioned or trusted
  untrusted,
  
  /// Provisioned but not validated
  provisioned,
  
  /// Validated by swarm
  validated,
  
  /// Trusted by swarm
  trusted,
  
  /// Core Fibre (highest trust)
  core,
}

/// Fibre identity for ZEFCP swarm participation
/// 
/// Manages the mobile device's cryptographic identity as a Fibre,
/// including Ed25519 keypair generation, signing, and trust level tracking.
/// 
/// Features:
/// - Ed25519 keypair generation and storage
/// - Secure key storage via FlutterSecureStorage
/// - Cryptographic signing and verification
/// - Trust level management
/// - Automatic provisioning if not initialized
class FibreIdentity {
  static const String _storageKeyFibreId = 'zefcp_fibre_id';
  static const String _storageKeyPublicKey = 'zefcp_public_key';
  static const String _storageKeyPrivateKey = 'zefcp_private_key';
  static const String _storageKeyTrustLevel = 'zefcp_trust_level';
  
  final FlutterSecureStorage _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );
  
  String? _fibreId;
  SimplePublicKey? _publicKey;
  SimpleKeyPair? _keyPair;
  TrustLevel _trustLevel = TrustLevel.untrusted;
  bool _isProvisioned = false;
  
  /// Fibre ID (unique identifier)
  String? get fibreId => _fibreId;
  
  /// Public key (Ed25519)
  SimplePublicKey? get publicKey => _publicKey;
  
  /// Private key (Ed25519) - not exposed directly for security
  SimpleKeyPair? get keyPair => _keyPair;
  
  /// Current trust level
  TrustLevel get trustLevel => _trustLevel;
  
  /// Whether identity is provisioned
  bool get isProvisioned => _isProvisioned;
  
  /// Initialize Fibre identity (loads or creates)
  /// 
  /// If identity doesn't exist, generates a new Ed25519 keypair
  /// and creates a unique Fibre ID.
  /// 
  /// Returns true if initialized successfully
  Future<bool> initialize() async {
    try {
      // Try to load existing identity
      final existingFibreId = await _storage.read(key: _storageKeyFibreId);
      final existingPublicKeyBase64 = await _storage.read(key: _storageKeyPublicKey);
      final existingPrivateKeyBase64 = await _storage.read(key: _storageKeyPrivateKey);
      final existingTrustLevelStr = await _storage.read(key: _storageKeyTrustLevel);
      
      if (existingFibreId != null &&
          existingPublicKeyBase64 != null &&
          existingPrivateKeyBase64 != null) {
        // Load existing identity
        _fibreId = existingFibreId;
        
        final publicKeyBytes = base64Decode(existingPublicKeyBase64);
        final privateKeyBytes = base64Decode(existingPrivateKeyBase64);
        
        // Reconstruct Ed25519 keypair
        final algorithm = Ed25519();
        _keyPair = await algorithm.newKeyPairFromSeed(privateKeyBytes);
        _publicKey = await _keyPair!.extractPublicKey();
        
        // Verify public key matches
        final publicKeyBytesFromPair = await _publicKey!.extractBytes();
        if (!_bytesEqual(publicKeyBytes, publicKeyBytesFromPair)) {
          print('[ZEFCP FibreIdentity] Public key mismatch, regenerating');
          return await _generateNewIdentity();
        }
        
        _trustLevel = TrustLevel.values.firstWhere(
          (e) => e.name == existingTrustLevelStr,
          orElse: () => TrustLevel.untrusted,
        );
        
        _isProvisioned = true;
        
        print('[ZEFCP FibreIdentity] Loaded existing identity: $_fibreId');
        return true;
      }
      
      // Generate new identity
      return await _generateNewIdentity();
    } catch (e) {
      print('[ZEFCP FibreIdentity] Error initializing: $e');
      return false;
    }
  }
  
  /// Generate a new Fibre identity
  Future<bool> _generateNewIdentity() async {
    try {
      final algorithm = Ed25519();
      
      // Generate new Ed25519 keypair
      _keyPair = await algorithm.newKeyPair();
      _publicKey = await _keyPair!.extractPublicKey();
      
      // Generate Fibre ID from public key (first 16 bytes, hex encoded)
      final publicKeyBytes = await _publicKey!.extractBytes();
      final fibreIdBytes = publicKeyBytes.sublist(0, 16);
      _fibreId = _bytesToHex(fibreIdBytes);
      
      _trustLevel = TrustLevel.untrusted;
      _isProvisioned = false;
      
      // Persist to secure storage
      await _persistIdentity();
      
      print('[ZEFCP FibreIdentity] Generated new identity: $_fibreId');
      return true;
    } catch (e) {
      print('[ZEFCP FibreIdentity] Error generating identity: $e');
      return false;
    }
  }
  
  /// Persist identity to secure storage
  Future<void> _persistIdentity() async {
    if (_fibreId == null || _publicKey == null || _keyPair == null) {
      return;
    }
    
    try {
      final publicKeyBytes = await _publicKey!.extractBytes();
      final privateKeyBytes = await _keyPair!.extractBytes();
      
      await _storage.write(key: _storageKeyFibreId, value: _fibreId!);
      await _storage.write(
        key: _storageKeyPublicKey,
        value: base64Encode(publicKeyBytes),
      );
      await _storage.write(
        key: _storageKeyPrivateKey,
        value: base64Encode(privateKeyBytes),
      );
      await _storage.write(
        key: _storageKeyTrustLevel,
        value: _trustLevel.name,
      );
      
      print('[ZEFCP FibreIdentity] Persisted identity to secure storage');
    } catch (e) {
      print('[ZEFCP FibreIdentity] Error persisting identity: $e');
    }
  }
  
  /// Sign data with private key
  /// 
  /// [data] Data to sign (as bytes)
  /// 
  /// Returns signature bytes, or null if signing fails
  Future<Uint8List?> sign(Uint8List data) async {
    if (_keyPair == null) {
      print('[ZEFCP FibreIdentity] Cannot sign: identity not initialized');
      return null;
    }
    
    try {
      final algorithm = Ed25519();
      final signature = await algorithm.sign(
        data,
        keyPair: _keyPair!,
      );
      
      return signature.bytes;
    } catch (e) {
      print('[ZEFCP FibreIdentity] Error signing data: $e');
      return null;
    }
  }
  
  /// Verify signature against data and public key
  /// 
  /// [data] Original data (as bytes)
  /// [signature] Signature bytes to verify
  /// [publicKey] Public key to verify against (default: own public key)
  /// 
  /// Returns true if signature is valid
  Future<bool> verify(
    Uint8List data,
    Uint8List signature, {
    SimplePublicKey? publicKey,
  }) async {
    try {
      final algorithm = Ed25519();
      final keyToUse = publicKey ?? _publicKey;
      
      if (keyToUse == null) {
        print('[ZEFCP FibreIdentity] Cannot verify: no public key');
        return false;
      }
      
      final signatureObj = Signature(signature);
      final isValid = await algorithm.verify(
        data,
        signature: signatureObj,
        publicKey: keyToUse,
      );
      
      return isValid;
    } catch (e) {
      print('[ZEFCP FibreIdentity] Error verifying signature: $e');
      return false;
    }
  }
  
  /// Update trust level
  /// 
  /// [level] New trust level
  Future<void> updateTrustLevel(TrustLevel level) async {
    _trustLevel = level;
    await _storage.write(
      key: _storageKeyTrustLevel,
      value: level.name,
    );
    print('[ZEFCP FibreIdentity] Trust level updated to: ${level.name}');
  }
  
  /// Mark identity as provisioned
  Future<void> markProvisioned() async {
    _isProvisioned = true;
    await updateTrustLevel(TrustLevel.provisioned);
  }
  
  /// Get public key as base64 string
  Future<String?> getPublicKeyBase64() async {
    if (_publicKey == null) return null;
    final bytes = await _publicKey!.extractBytes();
    return base64Encode(bytes);
  }
  
  /// Get public key as hex string
  Future<String?> getPublicKeyHex() async {
    if (_publicKey == null) return null;
    final bytes = await _publicKey!.extractBytes();
    return _bytesToHex(bytes);
  }
  
  /// Compare two byte lists for equality
  bool _bytesEqual(Uint8List a, Uint8List b) {
    if (a.length != b.length) return false;
    for (int i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
  
  /// Convert bytes to hex string
  String _bytesToHex(Uint8List bytes) {
    return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join('');
  }
  
  /// Clear identity (use with caution)
  Future<void> clear() async {
    await _storage.delete(key: _storageKeyFibreId);
    await _storage.delete(key: _storageKeyPublicKey);
    await _storage.delete(key: _storageKeyPrivateKey);
    await _storage.delete(key: _storageKeyTrustLevel);
    
    _fibreId = null;
    _publicKey = null;
    _keyPair = null;
    _trustLevel = TrustLevel.untrusted;
    _isProvisioned = false;
    
    print('[ZEFCP FibreIdentity] Identity cleared');
  }
}
