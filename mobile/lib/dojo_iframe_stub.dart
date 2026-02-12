// Stub implementation for non-web platforms
// This file is imported on mobile platforms where dart:html is not available

import 'package:flutter/widgets.dart';

/// Stub - returns empty container on non-web platforms
/// (Mobile uses WebView instead, this is never called)
Widget buildDojoIframe(String dojoUrl) {
  return const SizedBox.shrink();
}

/// Stub - not used on mobile (url_launcher is used instead)
void launchDojoUrl(String url) {
  // No-op on non-web
}

/// Stub - no-op on non-web platforms (no iframes to manage)
void setDojoIframePointerEvents(bool enabled) {
  // No-op on non-web
}
