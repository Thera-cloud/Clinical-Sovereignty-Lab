import 'dart:typed_data';

/// Stub implementation for non-web platforms.
/// On mobile, use http.MultipartRequest which works fine with file paths.
Future<Map<String, dynamic>> uploadVideoNative({
  required String url,
  required String token,
  required String coachId,
  required String clientId,
  required Uint8List bytes,
  required String filename,
  void Function(double progress)? onProgress,
}) async {
  throw UnsupportedError('uploadVideoNative is only supported on web. '
      'Use http.MultipartRequest on mobile platforms.');
}
