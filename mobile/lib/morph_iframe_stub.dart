// Stub — morph iframe is web-only

import 'package:flutter/widgets.dart';

VoidCallback? onMorphViewerReady;

void sendExpressionToMorph(String expression) {}

void sendVoiceStateToMorph(String state) {}

Widget buildMorphAvatarIframe(String viewerUrl) {
  return const SizedBox.shrink();
}

bool isMorphAvatarAvailable() => false;
