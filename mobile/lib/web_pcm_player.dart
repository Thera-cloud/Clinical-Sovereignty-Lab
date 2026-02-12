// Web-specific PCM audio player using Web Audio API
// This file is only imported on web platform via conditional import

import 'dart:convert';
import 'dart:html';
import 'dart:typed_data';
import 'dart:web_audio' as audio;

/// Plays raw PCM audio chunks (24kHz, 16-bit, mono) using the Web Audio API.
/// Used by VagusEngine to play Azure OpenAI Realtime audio on web.
class WebPcmPlayer {
  audio.AudioContext? _ctx;
  double _nextStartTime = 0;
  int _pendingSources = 0;
  bool _isSpeaking = false;

  bool get isSpeaking => _isSpeaking;

  /// Callback fired when the playback queue drains completely
  void Function()? onPlaybackComplete;

  /// Call this in response to a user gesture to satisfy browser autoplay policy.
  /// Must be called before any audio will play.
  void initialize() {
    _ctx ??= audio.AudioContext();
    // Resume context in case it was created before user gesture
    _ctx!.resume();
    _nextStartTime = 0;
    _pendingSources = 0;
    print(">>> [WEB_AUDIO] AudioContext initialized (state: ${_ctx!.state})");
  }

  /// Enqueue a raw PCM chunk for gapless playback.
  /// [pcmBytes] is raw 16-bit signed little-endian PCM at 24kHz mono.
  void playChunk(Uint8List pcmBytes) {
    if (_ctx == null) initialize();
    final ctx = _ctx!;

    // Resume if suspended (e.g. browser policy)
    if (ctx.state == 'suspended') {
      ctx.resume();
    }

    final numSamples = pcmBytes.length ~/ 2;
    if (numSamples == 0) return;

    // Create an AudioBuffer (1 channel, 24kHz)
    final buffer = ctx.createBuffer(1, numSamples, 24000);
    final channelData = buffer.getChannelData(0);

    // Convert Int16 PCM to Float32 [-1.0, 1.0]
    final view = ByteData.sublistView(pcmBytes);
    for (int i = 0; i < numSamples; i++) {
      channelData[i] = view.getInt16(i * 2, Endian.little) / 32768.0;
    }

    // Create a source node and schedule for gapless playback
    final source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connectNode(ctx.destination!);

    final now = ctx.currentTime!.toDouble();
    final startTime = _nextStartTime > now ? _nextStartTime : now;
    source.start(startTime);
    _nextStartTime = startTime + buffer.duration!.toDouble();
    _pendingSources++;

    if (!_isSpeaking) {
      _isSpeaking = true;
    }

    // Track when this source finishes
    source.onEnded.listen((_) {
      _pendingSources--;
      if (_pendingSources <= 0) {
        _pendingSources = 0;
        _isSpeaking = false;
        onPlaybackComplete?.call();
      }
    });
  }

  /// Play a complete MP3 audio buffer (from Mini-TTS).
  /// [mp3Bytes] is the full MP3 file as bytes.
  void playMp3(Uint8List mp3Bytes) {
    if (mp3Bytes.isEmpty) return;

    // Convert to base64 data URL
    final b64 = base64Encode(mp3Bytes);
    final dataUrl = 'data:audio/mp3;base64,$b64';

    _pendingSources++;
    _isSpeaking = true;

    // Use HTML5 Audio element for MP3 playback
    final audioElement = AudioElement(dataUrl);
    audioElement.play();

    audioElement.onEnded.listen((_) {
      _pendingSources--;
      if (_pendingSources <= 0) {
        _pendingSources = 0;
        _isSpeaking = false;
        onPlaybackComplete?.call();
      }
    });

    audioElement.onError.listen((_) {
      print("!!! [WEB_AUDIO] MP3 playback error");
      _pendingSources--;
      if (_pendingSources <= 0) {
        _pendingSources = 0;
        _isSpeaking = false;
        onPlaybackComplete?.call();
      }
    });

    print(">>> [WEB_AUDIO] Playing MP3 (${mp3Bytes.length} bytes)");
  }

  /// Queue a short silent buffer at the end of the current playback queue.
  /// This prevents the audio from cutting off abruptly after the last spoken word.
  void queueTrailingSilence({int durationMs = 400}) {
    if (_ctx == null) return;
    final ctx = _ctx!;
    // 24kHz * durationMs/1000 = number of silent samples
    final numSamples = (24000 * durationMs / 1000).round();
    final buffer = ctx.createBuffer(1, numSamples, 24000);
    // Channel data is already zero-filled (silence) by default

    final source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connectNode(ctx.destination!);

    final now = ctx.currentTime!.toDouble();
    final startTime = _nextStartTime > now ? _nextStartTime : now;
    source.start(startTime);
    _nextStartTime = startTime + buffer.duration!.toDouble();
    _pendingSources++;

    source.onEnded.listen((_) {
      _pendingSources--;
      if (_pendingSources <= 0) {
        _pendingSources = 0;
        _isSpeaking = false;
        onPlaybackComplete?.call();
      }
    });
  }

  /// Stop all playback immediately by recreating the AudioContext.
  void stop() {
    // Only recreate if there are pending sources to stop
    if (_pendingSources > 0) {
      _ctx?.close();
      _ctx = audio.AudioContext();
      _ctx!.resume(); // Ensure new context is active immediately
    }
    _nextStartTime = 0;
    _pendingSources = 0;
    _isSpeaking = false;
  }

  /// Clean up resources.
  void dispose() {
    _ctx?.close();
    _ctx = null;
    _nextStartTime = 0;
    _pendingSources = 0;
    _isSpeaking = false;
  }
}
