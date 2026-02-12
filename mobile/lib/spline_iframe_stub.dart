// Stub implementation for non-web platforms
// This file is imported on mobile platforms where dart:html is not available

import 'package:flutter/widgets.dart';

/// Stub - sends expression to Spline (no-op on mobile)
void sendExpressionToSpline(String expression) {
  // No-op on non-web platforms
}

/// Stub - sends voice state to Spline (no-op on mobile)
void sendVoiceStateToSpline(String state) {
  // No-op on non-web platforms
}

/// Stub - returns empty container on non-web platforms
/// (Mobile uses the existing LittleNateAvatar widget instead)
Widget buildSplineAvatarIframe(String splineUrl) {
  return const SizedBox.shrink();
}

/// Returns false - Spline avatar is not available on mobile
bool isSplineAvatarAvailable() => false;
