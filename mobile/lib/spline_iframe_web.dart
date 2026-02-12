// Web-specific Spline avatar iframe implementation
// This file is only imported on web platform

import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/widgets.dart';

// Track registered view factories
final Map<String, bool> _registeredSplineViews = {};

// Track whether the Spline iframe has signaled readiness
bool _splineReady = false;
String? _pendingExpression;

// Listen for spline_ready message from the iframe
bool _listenerRegistered = false;
void _ensureReadyListener() {
  if (_listenerRegistered) return;
  _listenerRegistered = true;
  html.window.onMessage.listen((event) {
    if (event.data is Map && event.data['type'] == 'spline_ready') {
      _splineReady = true;
      // Replay pending expression if one was queued
      if (_pendingExpression != null) {
        sendExpressionToSpline(_pendingExpression!);
        _pendingExpression = null;
      }
    }
  });
}

/// Sends an expression change message to the Spline iframe
void sendExpressionToSpline(String expression) {
  _ensureReadyListener();
  
  // Find the iframe and post message to it
  final iframes = html.document.querySelectorAll('iframe');
  int iframeCount = 0;
  for (final iframe in iframes) {
    if (iframe is html.IFrameElement && 
        iframe.src != null && 
        iframe.src!.contains('spline')) {
      iframeCount++;
      iframe.contentWindow?.postMessage({
        'type': 'setExpression',
        'expression': expression,
      }, '*');
    }
  }
  if (iframeCount == 0) {
    // Iframe not in DOM yet -- queue the expression for replay
    _pendingExpression = expression;
  }
}

/// Sends a voice state change to the Spline iframe
void sendVoiceStateToSpline(String state) {
  final iframes = html.document.querySelectorAll('iframe');
  for (final iframe in iframes) {
    if (iframe is html.IFrameElement && 
        iframe.src != null && 
        iframe.src!.contains('spline')) {
      iframe.contentWindow?.postMessage({
        'type': 'setVoiceState',
        'state': state,
      }, '*');
    }
  }
}

/// Creates a widget that displays the Spline avatar in an iframe (web only)
Widget buildSplineAvatarIframe(String splineUrl) {
  _ensureReadyListener();
  final viewType = 'spline-avatar-${splineUrl.hashCode}';
  
  // Register the view factory for this URL if not already done
  if (!_registeredSplineViews.containsKey(viewType)) {
    ui_web.platformViewRegistry.registerViewFactory(
      viewType,
      (int viewId) {
        final iframe = html.IFrameElement()
          ..src = splineUrl
          ..style.border = 'none'
          ..style.width = '100%'
          ..style.height = '100%'
          ..style.backgroundColor = '#050505'
          ..setAttribute('allowfullscreen', 'true')
          ..setAttribute('allow', 'accelerometer; autoplay; encrypted-media; gyroscope');
        return iframe;
      },
    );
    _registeredSplineViews[viewType] = true;
  }
  
  return HtmlElementView(
    viewType: viewType,
    key: ValueKey(splineUrl),
  );
}

/// Returns true - Spline avatar is available on web
bool isSplineAvatarAvailable() => true;
