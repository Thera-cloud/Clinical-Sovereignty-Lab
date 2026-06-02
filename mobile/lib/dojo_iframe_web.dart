// Web-specific iframe implementation for Dojo
// This file is only imported on web platform

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/widgets.dart';

const _dojoViewType = 'dojo-iframe-coach-command';

html.IFrameElement? _dojoIframe;
bool _dojoFactoryRegistered = false;

String? _pendingAuthToken;
String? _pendingAuthHw;
String? _pendingAuthWs;

/// Toggle pointer-events on all iframes to prevent platform view z-index conflicts.
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

void _postAuthToDojoIframe() {
  final iframe = _dojoIframe;
  final token = (_pendingAuthToken ?? '').trim();
  if (iframe == null || token.isEmpty) return;
  final target = iframe.contentWindow;
  if (target == null) return;
  target.postMessage({
    'type': 'ln_dojo_auth',
    'token': token,
    'hw': (_pendingAuthHw ?? '').trim(),
    'ws': (_pendingAuthWs ?? '').trim(),
  }, html.window.location.origin);
}

/// Push bridge auth to the embedded DOJO without reloading the iframe document.
void notifyDojoIframeAuth({
  required String token,
  required String hw,
  required String ws,
}) {
  _pendingAuthToken = token.trim();
  _pendingAuthHw = hw.trim();
  _pendingAuthWs = ws.trim();
  _postAuthToDojoIframe();
}

/// Clear pending auth when coach dashboard disposes (platform view teardown is handled by Flutter).
void disposeDojoIframe() {
  _dojoIframe = null;
  _pendingAuthToken = null;
  _pendingAuthHw = null;
  _pendingAuthWs = null;
}

/// Single stable iframe for Coach Command DOJO (token via postMessage, not URL).
Widget buildDojoIframe(String dojoUrl) {
  if (!_dojoFactoryRegistered) {
    ui_web.platformViewRegistry.registerViewFactory(
      _dojoViewType,
      (int viewId) {
        final iframe = html.IFrameElement()
          ..src = dojoUrl
          ..style.border = 'none'
          ..style.width = '100%'
          ..style.height = '100%'
          ..allow = 'microphone; camera'
          ..setAttribute('allowfullscreen', 'true')
          // sandbox: allow-scripts + allow-same-origin is intentional for same-origin DOJO
          // (WebSocket to bridge, form posts, normal DOM). Chrome warns this combo can
          // escape sandboxing — expected for embedded coach portal on the same origin.
          ..setAttribute(
            'sandbox',
            'allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads',
          );
        iframe.onLoad.listen((_) => _postAuthToDojoIframe());
        _dojoIframe = iframe;
        return iframe;
      },
    );
    _dojoFactoryRegistered = true;
  }

  return const HtmlElementView(
    viewType: _dojoViewType,
    key: ValueKey(_dojoViewType),
  );
}
