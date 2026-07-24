// Web-specific iframe for LN-Observer (Coach Command)
// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/widgets.dart';

const _observerViewType = 'ln-observer-iframe-coach-command';

html.IFrameElement? _observerIframe;
bool _observerFactoryRegistered = false;
bool _observerParentListen = false;

String? _pendingAuthToken;
String? _pendingAuthHw;
String? _pendingAuthName;
String? _pendingAuthApi;
String? _pendingAuthWs;

void setLnObserverIframePointerEvents(bool enabled) {
  final iframes = html.document.querySelectorAll('iframe');
  for (final el in iframes) {
    final iframe = el as html.IFrameElement;
    final src = iframe.src ?? '';
    if (src.contains('ln-observer') || identical(iframe, _observerIframe)) {
      iframe.style.pointerEvents = enabled ? 'auto' : 'none';
    }
  }
}

void _ensureParentMessageListen() {
  if (_observerParentListen) return;
  _observerParentListen = true;
  html.window.onMessage.listen((event) {
    final data = event.data;
    if (data is Map && data['type'] == 'ln_observer_need_auth') {
      _postAuthToObserverIframe();
    }
  });
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
  _ensureParentMessageListen();
  _pendingAuthToken = token.trim();
  _pendingAuthHw = hw.trim();
  _pendingAuthName = name.trim();
  _pendingAuthApi = api.trim();
  _pendingAuthWs = ws.trim();
  _postAuthToObserverIframe();
}

/// Ask the deck to End session (closing synthesis) before Flutter hides it.
void requestLnObserverIframeEnd() {
  final iframe = _observerIframe;
  final target = iframe?.contentWindow;
  if (target == null) return;
  target.postMessage(
    {'type': 'ln_observer_end'},
    html.window.location.origin,
  );
}

void disposeLnObserverIframe() {
  try {
    _observerIframe?.remove();
  } catch (_) {}
  _observerIframe = null;
  _pendingAuthToken = null;
  _pendingAuthHw = null;
  _pendingAuthName = null;
  _pendingAuthApi = null;
  _pendingAuthWs = null;
}

/// Force a fresh load of the observation deck (after End session / recovery).
void reloadLnObserverIframe() {
  final iframe = _observerIframe;
  if (iframe == null) return;
  final src = iframe.src;
  if (src == null || src.isEmpty) return;
  final uri = Uri.parse(src);
  final q = Map<String, String>.from(uri.queryParameters);
  q['_r'] = DateTime.now().millisecondsSinceEpoch.toString();
  iframe.src = uri.replace(queryParameters: q).toString();
}

Widget buildLnObserverIframe(String url) {
  _ensureParentMessageListen();
  if (!_observerFactoryRegistered) {
    ui_web.platformViewRegistry.registerViewFactory(
      _observerViewType,
      (int viewId) {
        final iframe = html.IFrameElement()
          ..src = url
          ..style.border = 'none'
          ..style.width = '100%'
          ..style.height = '100%'
          ..style.backgroundColor = '#131022'
          ..style.pointerEvents = 'auto'
          // display-capture must be on allow=; omit sandbox so getDisplayMedia
          // is not blocked by nested permission-policy defaults.
          ..allow = 'display-capture *; microphone *'
          ..setAttribute('allowfullscreen', 'true');
        iframe.onLoad.listen((_) {
          _postAuthToObserverIframe();
          setLnObserverIframePointerEvents(true);
        });
        _observerIframe = iframe;
        return iframe;
      },
    );
    _observerFactoryRegistered = true;
  } else {
    final iframe = _observerIframe;
    if (iframe != null) {
      final cur = iframe.src ?? '';
      final base = url.split('?').first;
      if (!cur.contains(base)) {
        iframe.src = url;
      }
      iframe.style.pointerEvents = 'auto';
      iframe.allow = 'display-capture *; microphone *';
    }
  }

  return const HtmlElementView(
    viewType: _observerViewType,
    key: ValueKey(_observerViewType),
  );
}
