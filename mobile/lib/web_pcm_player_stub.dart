// Stub implementation for non-web platforms
// This file is imported on mobile platforms where dart:html is not available

import 'dart:typed_data';

/// No-op stub for mobile platforms. On mobile, audio playback uses native
/// audio players (just_audio / flutter_sound) instead of Web Audio API.
class WebPcmPlayer {
  bool get isSpeaking => false;

  void Function()? onPlaybackComplete;

  void initialize() {}

  void playChunk(Uint8List pcmBytes) {
    // No-op on mobile — native audio player handles this
  }

  void playMp3(Uint8List mp3Bytes) {
    // No-op on mobile — native audio player handles this
  }

  void queueTrailingSilence({int durationMs = 400}) {
    // No-op on mobile
  }

  void stop() {}

  void dispose() {}
}
