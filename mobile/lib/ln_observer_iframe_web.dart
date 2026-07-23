// Web-specific iframe for LN-Observer (Coach Command)
// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/widgets.dart';

const _observerViewType = 'ln-observer-iframe-coach-command';

html.IFrameElement? _observerIframe;
bool _observerFactoryRegistered = false;

String? _pendingAuthToken;
String? _pendingAuthHw;
String? _pendingAuthName;
String? _pendingAuthApi;
String? _pendingAuthWs;

void setLnObserverIframePointerEvents(bool enabled) {
  final iframes = html.document.querySelectorAll('iframe');
  for (final el in iframes) {
    (el as html.IFrameElement).style.pointerEvents = enabled ? 'auto' : 'none';
  }
}

void _postAuthToObserverIframe() {
  final iframe = _observerIframe;
  final token = (_pendingAuthToken ?? '').trim();
  if (iframe == null || token.isEmpty) return;
  final target = iframe.contentWindow;
  if (target == null) return;
  target.postMessage({
    'type': 'ln_observer_auth',
    'token': token,
    'hw': (_pendingAuthHw ?? '').trim(),
    'username': (_pendingAuthHw ?? '').trim(),
    'name': (_pendingAuthName ?? '').trim(),
    'api': (_pendingAuthApi ?? '').trim(),
    'ws': (_pendingAuthWs ?? '').trim(),
  }, html.window.location.origin);
}

void notifyLnObserverIframeAuth({
  required String token,
  required String hw,
  required String name,
  required String api,
  required String ws,
}) {
  _pendingAuthToken = token.trim();
  _pendingAuthHw = hw.trim();
  _pendingAuthName = name.trim();
  _pendingAuthApi = api.trim();
  _pendingAuthWs = ws.trim();
  _postAuthToObserverIframe();
}

void disposeLnObserverIframe() {
  _observerIframe = null;
  _pendingAuthToken = null;
  _pendingAuthHw = null;
  _pendingAuthName = null;
  _pendingAuthApi = null;
  _pendingAuthWs = null;
}

Widget buildLnObserverIframe(String url) {
  if (!_observerFactoryRegistered) {
    ui_web.platformViewRegistry.registerViewFactory(
      _observerViewType,
      (int viewId) {
        final iframe = html.IFrameElement()
          ..src = url
          ..style.border = 'none'
          ..style.width = '100%'
          ..style.height = '100%'
          ..allow = 'display-capture; microphone'
          ..setAttribute('allowfullscreen', 'true')
          ..setAttribute(
            'sandbox',
            'allow-scripts allow-same-origin allow-forms allow-popups allow-modals',
          );
        iframe.onLoad.listen((_) => _postAuthToObserverIframe());
        _observerIframe = iframe;
        return iframe;
      },
    );
    _observerFactoryRegistered = true;
  }

  return const HtmlElementView(
    viewType: _observerViewType,
    key: ValueKey(_observerViewType),
  );
}
