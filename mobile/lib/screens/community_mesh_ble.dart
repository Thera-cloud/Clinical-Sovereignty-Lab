// Community Mesh BLE — Native BLE scanning for Nate-to-Nate discovery
// Note: FlutterBluePlus supports Central (scan) only. Peripheral advertising
// requires platform-specific implementation (e.g. FlutterBlePeripheral).
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

/// Start BLE scanning for Community Mesh sessions.
/// Looks for devices advertising with "Nate-" prefix in their name.
Future<void> startCommunityMeshSession({
  required String localName,
  required String sessionId,
  required void Function(String id, String name) onPeerFound,
}) async {
  if (await FlutterBluePlus.isSupported == false) {
    throw Exception('BLE not supported');
  }
  await FlutterBluePlus.turnOn();

  // Scan for all devices; filter by advertised name
  await FlutterBluePlus.startScan(
    androidUsesFineLocation: true,
  );

  FlutterBluePlus.scanResults.listen((results) {
    for (final r in results) {
      final name = (r.device.advName).trim().isNotEmpty
          ? r.device.advName
          : (r.device.platformName).trim().isNotEmpty
              ? r.device.platformName
              : r.device.remoteId.str;
      if (name.startsWith('Nate-') && name != localName) {
        onPeerFound(r.device.remoteId.str, name);
      }
    }
  });
}

/// Stop BLE scanning.
Future<void> stopCommunityMeshSession() async {
  try {
    await FlutterBluePlus.stopScan();
  } catch (_) {}
}
