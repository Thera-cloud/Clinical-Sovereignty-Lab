// Stub for Community Mesh BLE — no-op on web (BLE not supported)
/// No-op implementation for platforms without BLE (e.g., web).
Future<void> startCommunityMeshSession({
  required String localName,
  required String sessionId,
  required void Function(String id, String name) onPeerFound,
}) async {
  // No-op on web
}

Future<void> stopCommunityMeshSession() async {
  // No-op on web
}
