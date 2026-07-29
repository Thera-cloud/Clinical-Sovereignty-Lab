// Web-specific morph avatar iframe (three.js + lil_nate_morphs.glb)

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/widgets.dart';

final Map<String, bool> _registeredMorphViews = {};
bool _morphReady = false;
String? _pendingExpression;
String? _pendingVoice;
bool _listenerRegistered = false;
VoidCallback? onMorphViewerReady;

void _ensureReadyListener() {
  if (_listenerRegistered) return;
  _listenerRegistered = true;
  html.window.onMessage.listen((event) {
    final data = event.data;
    if (data is Map && data['type'] == 'spline_ready') {
      _morphReady = true;
      onMorphViewerReady?.call();
      if (_pendingExpression != null) {
        sendExpressionToMorph(_pendingExpression!);
        _pendingExpression = null;
      }
      if (_pendingVoice != null) {
        sendVoiceStateToMorph(_pendingVoice!);
        _pendingVoice = null;
      }
    }
  });
}

bool _isMorphIframe(html.IFrameElement iframe) {
  final src = iframe.src ?? '';
  return src.contains('expression_viewer') || src.contains('avatar-modes');
}

/// postMessage setExpression → morph viewer (same contract as Spline).
void sendExpressionToMorph(String expression) {
  _ensureReadyListener();
  final iframes = html.document.querySelectorAll('iframe');
  var hit = 0;
  for (final el in iframes) {
    if (el is html.IFrameElement && _isMorphIframe(el)) {
      hit++;
      el.contentWindow?.postMessage({
        'type': 'setExpression',
        'expression': expression,
      }, '*');
    }
  }
  if (hit == 0 || !_morphReady) {
    _pendingExpression = expression;
  }
}

void sendVoiceStateToMorph(String state) {
  _ensureReadyListener();
  final iframes = html.document.querySelectorAll('iframe');
  var hit = 0;
  for (final el in iframes) {
    if (el is html.IFrameElement && _isMorphIframe(el)) {
      hit++;
      el.contentWindow?.postMessage({
        'type': 'setVoiceState',
        'state': state,
      }, '*');
    }
  }
  if (hit == 0 || !_morphReady) {
    _pendingVoice = state;
  }
}

Widget buildMorphAvatarIframe(String viewerUrl) {
  _ensureReadyListener();
  final viewType = 'morph-avatar-${viewerUrl.hashCode}';

  if (!_registeredMorphViews.containsKey(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int viewId) {
        final iframe = html.IFrameElement()
          ..src = viewerUrl
          ..style.border = 'none'
          ..style.width = '100%'
          ..style.height = '100%'
          ..style.backgroundColor = '#050505'
          ..setAttribute('allowfullscreen', 'true')
          ..setAttribute(
            'allow',
            'accelerometer; autoplay; encrypted-media; gyroscope',
          );
        return iframe;
      },
    );
    _registeredMorphViews[viewType] = true;
  }

  return HtmlElementView(
    viewType: viewType,
    key: ValueKey(viewerUrl),
  );
}

bool isMorphAvatarAvailable() => true;
