/// ZEFCP & Quakete Riverpod Providers
///
/// Provides reactive state management for Layer 1 (ZEFCP Physical Transport)
/// and Layer 8 (Quakete Swarm Solidarity) mobile services.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../zefcp/zefcp_service.dart';
import '../zefcp/secure_key_store.dart';
import '../zefcp/battery_manager.dart';
import '../zefcp/fibre_identity.dart';
import '../quakete/quakete_state_manager.dart';
import '../quakete/nevedal_bridge.dart';
import '../quakete/trail_emitter.dart';
import '../quakete/quakete_boost_manager.dart';
import '../quakete/ramp_up_handler.dart';
import '../quakete/constants.dart';

// =============================================================================
// ZEFCP Layer 1 Providers
// =============================================================================

/// Main ZEFCP orchestrator service.
final zefcpServiceProvider = Provider<ZefcpService>((ref) {
  return ZefcpService();
});

/// Secure key store singleton.
final secureKeyStoreProvider = Provider<SecureKeyStore>((ref) {
  return SecureKeyStore();
});

/// Fibre identity for this device.
final fibreIdentityProvider = FutureProvider<FibreIdentity>((ref) async {
  final identity = FibreIdentity();
  await identity.initialize();
  return identity;
});

/// Battery manager for adaptive scanning.
final batteryManagerProvider = Provider<BatteryManager>((ref) {
  return BatteryManager();
});

/// Battery profile stream for reactive UI updates.
final batteryProfileProvider = StreamProvider<BatteryProfile>((ref) {
  final manager = ref.watch(batteryManagerProvider);
  return manager.batteryProfileStream;
});

/// ZEFCP running status.
final zefcpStatusProvider = StreamProvider<ZefcpStatus>((ref) {
  final service = ref.watch(zefcpServiceProvider);
  return service.statusStream;
});

/// Whether the device has been provisioned with swarm keys.
final isProvisionedProvider = FutureProvider<bool>((ref) async {
  final store = ref.watch(secureKeyStoreProvider);
  return store.isProvisioned();
});

// =============================================================================
// Quakete Layer 8 Providers
// =============================================================================

/// Quakete operational mode state machine.
final quaketeStateProvider = Provider<QuaketeStateManager>((ref) {
  return QuaketeStateManager();
});

/// Current Quakete mode stream.
final quaketeModeProvider = StreamProvider<QuaketeMode>((ref) {
  final manager = ref.watch(quaketeStateProvider);
  return manager.modeStream;
});

/// Nevedal-to-Quakete resonance bridge.
final nevedalBridgeProvider = Provider<NevedalQuaketeBridge>((ref) {
  return NevedalQuaketeBridge();
});

/// Trail emitter for periodic heartbeats.
final trailEmitterProvider = Provider<TrailEmitter>((ref) {
  return TrailEmitter(
    stateManager: ref.watch(quaketeStateProvider),
    bridge: ref.watch(nevedalBridgeProvider),
  );
});

/// Quakete boost manager for incoming energy.
final quaketeBoostProvider = Provider<QuaketeBoostManager>((ref) {
  return QuaketeBoostManager();
});

/// Active boost stream for UI animations.
final activeBoostsProvider = StreamProvider<QuaketeBoost>((ref) {
  final manager = ref.watch(quaketeBoostProvider);
  return manager.boostReceivedStream;
});

/// Emergency ramp-up handler.
final rampUpHandlerProvider = Provider<RampUpHandler>((ref) {
  return RampUpHandler(
    stateManager: ref.watch(quaketeStateProvider),
  );
});

/// Whether device is currently in distress.
final isInDistressProvider = Provider<bool>((ref) {
  final handler = ref.watch(rampUpHandlerProvider);
  return handler.isInDistress;
});
