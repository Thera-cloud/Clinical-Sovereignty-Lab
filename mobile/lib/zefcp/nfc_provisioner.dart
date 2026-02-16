/// NFC Provisioner — Handles NFC-based key provisioning for ZEFCP
/// Reads provisioning payload from NFC tags and stores keys securely
/// 
/// Requires nfc_manager package for NFC tag reading

import 'dart:convert';
import 'package:nfc_manager/nfc_manager.dart';
import 'secure_key_store.dart';

/// Result of NFC provisioning operation
class ProvisioningResult {
  final bool success;
  final String? fibreId;
  final String? error;
  final Map<String, dynamic>? metadata;

  ProvisioningResult({
    required this.success,
    this.fibreId,
    this.error,
    this.metadata,
  });
}

/// ZEFCP NFC Provisioner
class NfcProvisioner {
  final SecureKeyStore _keyStore = SecureKeyStore();
  bool _isProvisioning = false;

  /// Check if NFC is available on this platform
  Future<bool> isNfcAvailable() async {
    try {
      return await NfcManager.instance.isAvailable();
    } catch (e) {
      print('[NFC Provisioner] NFC availability check failed: $e');
      return false;
    }
  }

  /// Start NFC provisioning session
  /// Reads NFC tag and extracts provisioning payload
  Future<ProvisioningResult> startProvisioning({
    Duration timeout = const Duration(seconds: 30),
  }) async {
    if (_isProvisioning) {
      return ProvisioningResult(
        success: false,
        error: 'Provisioning already in progress',
      );
    }

    final isAvailable = await isNfcAvailable();
    if (!isAvailable) {
      return ProvisioningResult(
        success: false,
        error: 'NFC is not available on this device',
      );
    }

    _isProvisioning = true;

    try {
      // Start NFC session
      final result = await NfcManager.instance.startSession(
        onDiscovered: (NfcTag tag) async {
          try {
            // Extract NDEF data from tag
            final ndef = Ndef.from(tag);
            if (ndef == null) {
              await NfcManager.instance.stopSession(
                errorMessage: 'Tag does not support NDEF',
              );
              return;
            }

            // Read NDEF message
            final ndefMessage = await ndef.read();
            if (ndefMessage == null || ndefMessage.records.isEmpty) {
              await NfcManager.instance.stopSession(
                errorMessage: 'Tag is empty',
              );
              return;
            }

            // Extract payload from first NDEF record
            final firstRecord = ndefMessage.records.first;
            final payloadData = firstRecord.payload;
            
            // Decode payload (assuming JSON format)
            String payloadString;
            try {
              // NDEF payload may have a language code prefix (skip first byte)
              if (payloadData.isNotEmpty && payloadData[0] < 0x80) {
                // Skip language code (typically 1-3 bytes)
                int skipBytes = 1;
                if (payloadData.length > 1 && payloadData[1] < 0x80) {
                  skipBytes = 2;
                }
                payloadString = utf8.decode(payloadData.sublist(skipBytes));
              } else {
                payloadString = utf8.decode(payloadData);
              }
            } catch (e) {
              // Try decoding entire payload if prefix skip fails
              payloadString = utf8.decode(payloadData);
            }

            // Parse provisioning payload JSON
            final provisioningData = jsonDecode(payloadString) as Map<String, dynamic>;

            // Extract provisioning components
            final swarmSecret = provisioningData['swarm_secret'] as String?;
            final fibreKeypair = provisioningData['fibre_keypair'] as Map<String, dynamic>?;
            final fibreId = provisioningData['fibre_id'] as String?;
            final transportConfig = provisioningData['transport_config'] as Map<String, dynamic>?;
            final meshEndpointConfig = provisioningData['mesh_endpoint_config'] as Map<String, dynamic>?;
            final expiryStr = provisioningData['key_expiry'] as String?;

            if (swarmSecret == null ||
                fibreKeypair == null ||
                fibreId == null ||
                transportConfig == null) {
              await NfcManager.instance.stopSession(
                errorMessage: 'Invalid provisioning payload: missing required fields',
              );
              return;
            }

            // Parse expiry if provided
            DateTime? expiry;
            if (expiryStr != null) {
              try {
                expiry = DateTime.parse(expiryStr);
              } catch (e) {
                print('[NFC Provisioner] Failed to parse expiry: $e');
              }
            }

            // Store provisioning data using individual SecureKeyStore methods
            // swarm_secret and keypair values arrive as base64 strings from the NFC payload;
            // SecureKeyStore expects Uint8List for cryptographic material.
            await _keyStore.storeSwarmSecret(base64Decode(swarmSecret));
            await _keyStore.storeFibreKeypair(
              privateKey: base64Decode(fibreKeypair['private_key'] as String),
              publicKey: base64Decode(fibreKeypair['public_key'] as String),
            );
            await _keyStore.storeFibreId(fibreId);
            await _keyStore.storeTransportConfig(transportConfig);
            await _keyStore.markProvisioned();

            // Stop session with success
            await NfcManager.instance.stopSession();
          } catch (e) {
            print('[NFC Provisioner] Error processing tag: $e');
            await NfcManager.instance.stopSession(
              errorMessage: 'Failed to process provisioning payload: $e',
            );
          }
        },
        timeout: timeout,
      );

      _isProvisioning = false;

      // Check if provisioning was successful
      if (result == true) {
        final fibreId = await _keyStore.getFibreId();
        return ProvisioningResult(
          success: true,
          fibreId: fibreId,
          metadata: {
            'provisioned_at': DateTime.now().toIso8601String(),
          },
        );
      } else {
        return ProvisioningResult(
          success: false,
          error: 'NFC session ended without provisioning',
        );
      }
    } catch (e) {
      _isProvisioning = false;
      return ProvisioningResult(
        success: false,
        error: 'NFC provisioning failed: $e',
      );
    }
  }

  /// Cancel ongoing provisioning session
  Future<void> cancelProvisioning() async {
    if (!_isProvisioning) return;

    try {
      await NfcManager.instance.stopSession();
    } catch (e) {
      print('[NFC Provisioner] Error canceling session: $e');
    } finally {
      _isProvisioning = false;
    }
  }

  /// Check if provisioning is currently in progress
  bool get isProvisioning => _isProvisioning;
}
