// Web-specific iframe implementation for Dojo
// This file is only imported on web platform

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/widgets.dart';

// Track registered view factories by URL
final Map<String, bool> _registeredViewTypes = {};

/// Toggle pointer-events on all iframes to prevent platform view z-index conflicts.
/// When disabled, iframes won't intercept taps meant for Flutter overlay widgets
/// (like popup menus), while keeping the iframe alive and state intact.
void setDojoIframePointerEvents(bool enabled) {
  final iframes = html.document.querySelectorAll('iframe');
  for (final el in iframes) {
    (el as html.IFrameElement).style.pointerEvents = enabled ? 'auto' : 'none';
  }
}

/// Opens the Dojo URL in a new browser tab (web only)
void launchDojoUrl(String url) {
  html.window.open(url, '_blank');
}

/// Creates a widget that displays the Dojo page in an iframe (web only)
Widget buildDojoIframe(String dojoUrl) {
  // Create unique view type per URL to handle URL changes
  final viewType = 'dojo-iframe-${dojoUrl.hashCode}';
  
  // Register the view factory for this URL if not already done
  if (!_registeredViewTypes.containsKey(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int viewId) {
        final iframe = html.IFrameElement()
          ..src = dojoUrl
          ..style.border = 'none'
          ..style.width = '100%'
          ..style.height = '100%'
          ..allow = 'microphone; camera'
          ..setAttribute('allowfullscreen', 'true')
          ..setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads');
        return iframe;
      },
    );
    _registeredViewTypes[viewType] = true;
  }
  
  return HtmlElementView(
    viewType: viewType,
    key: ValueKey(dojoUrl),
  );
}
