/// Secure Key Store
///
/// Encrypted-at-rest storage for ZEFCP cryptographic material.
/// Uses flutter_secure_storage for platform-native encryption
/// (iOS Keychain, Android EncryptedSharedPreferences).
library;

import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Secure storage for swarm cryptographic material (singleton).
class SecureKeyStore {
  // Singleton
  static final SecureKeyStore _instance = SecureKeyStore._internal();
  factory SecureKeyStore() => _instance;
  SecureKeyStore._internal();

  final FlutterSecureStorage _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  // Storage keys
  static const _keySwarmSecret = 'zefcp_swarm_secret';
  static const _keyFibreId = 'zefcp_fibre_id';
  static const _keyFibrePrivateKey = 'zefcp_fibre_private_key';
  static const _keyFibrePublicKey = 'zefcp_fibre_public_key';
  static const _keyTransportConfig = 'zefcp_transport_config';
  static const _keyProvisionedAt = 'zefcp_provisioned_at';
  static const _keyKeyExpiresAt = 'zefcp_key_expires_at';

  // ─── Swarm Secret ─────────────────────────────────────────────────────

  /// Store the swarm secret (32-byte HMAC key).
  Future<void> storeSwarmSecret(Uint8List secret) async {
    await _storage.write(
      key: _keySwarmSecret,
      value: base64Encode(secret),
    );
  }

  /// Retrieve the swarm secret.
  Future<Uint8List?> getSwarmSecret() async {
    final encoded = await _storage.read(key: _keySwarmSecret);
    if (encoded == null) return null;
    return base64Decode(encoded);
  }

  // ─── Fibre Identity ───────────────────────────────────────────────────

  /// Store the Fibre ID assigned during provisioning.
  Future<void> storeFibreId(String fibreId) async {
    await _storage.write(key: _keyFibreId, value: fibreId);
  }

  /// Retrieve the Fibre ID.
  Future<String?> getFibreId() async {
    return _storage.read(key: _keyFibreId);
  }

  /// Store an Ed25519 keypair for Fibre identity.
  Future<void> storeFibreKeypair({
    required Uint8List privateKey,
    required Uint8List publicKey,
  }) async {
    await _storage.write(
      key: _keyFibrePrivateKey,
      value: base64Encode(privateKey),
    );
    await _storage.write(
      key: _keyFibrePublicKey,
      value: base64Encode(publicKey),
    );
  }

  /// Retrieve the Fibre keypair.
  Future<({Uint8List privateKey, Uint8List publicKey})?> getFibreKeypair() async {
    final privEncoded = await _storage.read(key: _keyFibrePrivateKey);
    final pubEncoded = await _storage.read(key: _keyFibrePublicKey);
    if (privEncoded == null || pubEncoded == null) return null;
    return (
      privateKey: base64Decode(privEncoded),
      publicKey: base64Decode(pubEncoded),
    );
  }

  // ─── Transport Config ─────────────────────────────────────────────────

  /// Store transport configuration (JSON-serializable map).
  Future<void> storeTransportConfig(Map<String, dynamic> config) async {
    await _storage.write(
      key: _keyTransportConfig,
      value: jsonEncode(config),
    );
  }

  /// Retrieve transport configuration.
  Future<Map<String, dynamic>?> getTransportConfig() async {
    final encoded = await _storage.read(key: _keyTransportConfig);
    if (encoded == null) return null;
    return jsonDecode(encoded) as Map<String, dynamic>;
  }

  // ─── Provisioning State ───────────────────────────────────────────────

  /// Check if the device has been provisioned with swarm keys.
  Future<bool> isProvisioned() async {
    final secret = await _storage.read(key: _keySwarmSecret);
    final fibreId = await _storage.read(key: _keyFibreId);
    return secret != null && fibreId != null;
  }

  /// Record the provisioning timestamp.
  Future<void> markProvisioned() async {
    await _storage.write(
      key: _keyProvisionedAt,
      value: DateTime.now().toUtc().toIso8601String(),
    );
  }

  /// Get the provisioning timestamp.
  Future<DateTime?> getProvisionedAt() async {
    final ts = await _storage.read(key: _keyProvisionedAt);
    if (ts == null) return null;
    return DateTime.parse(ts);
  }

  // ─── Key Expiry ───────────────────────────────────────────────────────

  /// Set key expiration time.
  Future<void> setKeyExpiry(DateTime expiresAt) async {
    await _storage.write(
      key: _keyKeyExpiresAt,
      value: expiresAt.toUtc().toIso8601String(),
    );
  }

  /// Check if keys have expired.
  Future<bool> areKeysExpired() async {
    final expiry = await _storage.read(key: _keyKeyExpiresAt);
    if (expiry == null) return false; // No expiry set = never expires
    return DateTime.now().toUtc().isAfter(DateTime.parse(expiry));
  }

  // ─── Clear ────────────────────────────────────────────────────────────

  /// Clear all stored cryptographic material.
  /// Use with caution — requires re-provisioning.
  Future<void> clearAll() async {
    await _storage.delete(key: _keySwarmSecret);
    await _storage.delete(key: _keyFibreId);
    await _storage.delete(key: _keyFibrePrivateKey);
    await _storage.delete(key: _keyFibrePublicKey);
    await _storage.delete(key: _keyTransportConfig);
    await _storage.delete(key: _keyProvisionedAt);
    await _storage.delete(key: _keyKeyExpiresAt);
  }
}
