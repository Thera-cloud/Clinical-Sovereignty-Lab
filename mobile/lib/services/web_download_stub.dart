/// Stub implementation for non-web platforms.
/// This file is never imported when running on the web.
void downloadFileToDevice(String content, String filename) {
  throw UnsupportedError('downloadFileToDevice is only supported on web');
}
