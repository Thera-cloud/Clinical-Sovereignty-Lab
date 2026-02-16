import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kDebugMode, kIsWeb;

/// Debug-only print: suppressed in production builds.
// ignore: avoid_print
void _debugLog(Object? message) { if (kDebugMode) print(message); }
import 'package:audio_session/audio_session.dart';
import 'package:just_audio/just_audio.dart' as just_audio;
import 'package:speech_to_text/speech_to_text.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:async';
import 'dart:convert';
// dart:io is only used for mobile temp file operations (guarded by !kIsWeb checks)
import 'dart:io' if (dart.library.io) 'dart:io';
import 'dart:math';
import 'dart:typed_data';
import 'package:path_provider/path_provider.dart';

// Conditional import: Web Audio API player for web, no-op stub for mobile
import 'web_pcm_player_stub.dart'
    if (dart.library.js_util) 'web_pcm_player.dart';

// =============================================================================
// VAGUS ENGINE - Audio/Voice Handler
// =============================================================================
class VagusEngine {
  // --- 1. CORE VARIABLES (These were missing in your last build) ---
  final SpeechToText _speech = SpeechToText();
  
  // Mobile audio player (just_audio) for MP3 and PCM playback
  just_audio.AudioPlayer? _mobilePlayer;
  
  // State Flags
  bool isAudioReady = false;
  bool get isListening => _isListening;
  bool _isListening = false;
  bool _isProcessingBuffer = false;
  
  // Buffers & Streams
  final List<Uint8List> _audioBuffer = [];
  final StreamController<String> _transcriptionStream = StreamController.broadcast();
  Stream<String> get onTranscription => _transcriptionStream.stream;
  Timer? _silenceTimer;

  // --- 2. INITIALIZATION (Robust) ---
  Future<void> initializeSystem() async {
    _debugLog(">>> [VAGUS] Initializing Audio Cortex...");
    
    // A. Permission Gate
    var status = await Permission.microphone.request();
    if (status != PermissionStatus.granted) {
      _debugLog("!!! [VAGUS] Mic Permission Denied by User.");
      isAudioReady = false;
      return; 
    }

    // B. Session Configuration
    final session = await AudioSession.instance;
    await session.configure(const AudioSessionConfiguration(
      avAudioSessionCategory: AVAudioSessionCategory.playAndRecord,
      avAudioSessionMode: AVAudioSessionMode.videoChat,
      avAudioSessionRouteSharingPolicy: AVAudioSessionRouteSharingPolicy.defaultPolicy,
      avAudioSessionSetActiveOptions: AVAudioSessionSetActiveOptions.notifyOthersOnDeactivation,
      androidAudioAttributes: AndroidAudioAttributes(
        contentType: AndroidAudioContentType.speech,
        flags: AndroidAudioFlags.audibilityEnforced,
        usage: AndroidAudioUsage.voiceCommunication,
      ),
      androidAudioFocusGainType: AndroidAudioFocusGainType.gain,
      androidWillPauseWhenDucked: true,
    ));

    // C. Interruption Handling
    session.interruptionEventStream.listen((event) {
      if (event.begin) {
        _debugLog(">>> [VAGUS] Audio Interrupted (Call Started)");
      } else {
        _debugLog(">>> [VAGUS] Audio Resumed (Call Ended)");
      }
    });

    session.devicesChangedEventStream.listen((event) {
       _debugLog(">>> [VAGUS] Audio Device Changed: ${event.devicesAdded}");
    });

    // D. Hardware Spin-up
    await session.setActive(true);
    
    // E. Mobile audio player (just_audio) for TTS/MP3 playback
    if (!kIsWeb) {
      try {
        _mobilePlayer = just_audio.AudioPlayer();
        _debugLog(">>> [VAGUS] Mobile audio player (just_audio) initialized");
      } catch (e) {
        _debugLog("!!! [VAGUS] Mobile audio player init failed: $e");
      }
    }
    
    isAudioReady = true;
    _debugLog(">>> [VAGUS] Audio System Online & Ready.");
  }

  // --- 3. INPUT: LISTENING (Speech-to-Text) ---
  Future<void> startListening({required Function(String) onFinalResult}) async {
    if (!isAudioReady) await initializeSystem();
    if (_isListening) return;

    bool available = await _speech.initialize(
      onStatus: (status) => _debugLog('>>> [SPEECH] Status: $status'),
      onError: (error) => _debugLog('!!! [SPEECH] Error: $error'),
    );

    if (available) {
      _isListening = true;
      _speech.listen(
        onResult: (result) {
          _transcriptionStream.add(result.recognizedWords);
          
          _silenceTimer?.cancel();
          _silenceTimer = Timer(const Duration(milliseconds: 1500), () {
            if (result.recognizedWords.isNotEmpty) {
              _debugLog(">>> [VAGUS] Silence Detected. Sending Query.");
              stopListening();
              onFinalResult(result.recognizedWords);
            }
          });
        },
        listenFor: const Duration(seconds: 30),
        pauseFor: const Duration(seconds: 3),
        partialResults: true,
        cancelOnError: true,
        listenMode: ListenMode.dictation,
      );
    }
  }

  Future<void> stopListening() async {
    _silenceTimer?.cancel();
    await _speech.stop();
    _isListening = false;
  }

  // --- 4. OUTPUT: SPEAKING (Buffered Audio) ---
  final WebPcmPlayer _webPlayer = WebPcmPlayer();
  bool get isSpeaking => _webPlayer.isSpeaking;

  /// Initialize the audio player. Call in response to a user gesture (web autoplay policy).
  void initializePlayer() {
    if (kIsWeb) {
      _webPlayer.initialize();
      _debugLog(">>> [VAGUS] Web Audio Player initialized.");
    }
  }

  /// Set a callback for when all queued audio finishes playing.
  set onPlaybackComplete(VoidCallback? cb) {
    _webPlayer.onPlaybackComplete = cb;
  }

  void processAudioChunk(String base64Data) {
    try {
      final bytes = base64Decode(base64Data);
      _audioBuffer.add(bytes);
      if (!_isProcessingBuffer) {
        _playNextChunk();
      }
    } catch (e) {
      _debugLog("!!! [VAGUS] Audio Decode Error: $e");
    }
  }

  /// Process a complete MP3 audio buffer (from Mini-TTS).
  /// Unlike PCM chunks, MP3 is a single complete file.
  void processMp3Audio(String base64Data) {
    try {
      final bytes = base64Decode(base64Data);
      if (kIsWeb) {
        _webPlayer.playMp3(bytes);
      } else {
        // Mobile: Play MP3 via just_audio — write to temp file, then play
        if (_mobilePlayer != null) {
          try {
            final dir = await getTemporaryDirectory();
            final tmpFile = File('${dir.path}/nate_tts_${DateTime.now().millisecondsSinceEpoch}.mp3');
            await tmpFile.writeAsBytes(bytes);
            await _mobilePlayer!.setFilePath(tmpFile.path);
            await _mobilePlayer!.play();
            // Clean up temp file after playback
            _mobilePlayer!.playerStateStream.firstWhere(
              (state) => state.processingState == just_audio.ProcessingState.completed,
            ).then((_) => tmpFile.delete().catchError((_) {}));
            _debugLog(">>> [VAGUS] MP3 playing via just_audio (${bytes.length} bytes)");
          } catch (e) {
            _debugLog("!!! [VAGUS] Mobile MP3 playback error: $e");
          }
        } else {
          _debugLog("!!! [VAGUS] Mobile audio player not initialized");
        }
      }
    } catch (e) {
      _debugLog("!!! [VAGUS] MP3 Decode Error: $e");
    }
  }

  void _playNextChunk() {
    if (_audioBuffer.isEmpty) {
      _isProcessingBuffer = false;
      return;
    }
    
    _isProcessingBuffer = true;
    final chunk = _audioBuffer.removeAt(0);

    if (kIsWeb) {
      // Web: Use Web Audio API for gapless PCM playback
      _webPlayer.playChunk(chunk);
      // Immediately process next chunk (they queue in Web Audio API)
      _playNextChunk();
    } else {
      // Mobile: Play PCM chunk via just_audio by wrapping in a WAV container
      if (_mobilePlayer != null) {
        try {
          // Wrap raw PCM in a minimal WAV header (16-bit, 24kHz, mono)
          final wavBytes = _wrapPcmAsWav(chunk, sampleRate: 24000, bitsPerSample: 16, channels: 1);
          getTemporaryDirectory().then((dir) async {
            final tmpFile = File('${dir.path}/nate_pcm_${DateTime.now().millisecondsSinceEpoch}.wav');
            await tmpFile.writeAsBytes(wavBytes);
            await _mobilePlayer!.setFilePath(tmpFile.path);
            _mobilePlayer!.play();
            // Continue to next chunk after this one finishes
            _mobilePlayer!.playerStateStream.firstWhere(
              (state) => state.processingState == just_audio.ProcessingState.completed,
            ).then((_) {
              tmpFile.delete().catchError((_) {});
              _playNextChunk();
            });
          });
          return; // Don't call _playNextChunk here — it's called in the callback above
        } catch (e) {
          _debugLog("!!! [VAGUS] Mobile PCM playback error: $e");
        }
      }
      // Fallback: drain buffer if player not available
      _playNextChunk();
    }
  }

  /// Wrap raw PCM bytes in a minimal WAV file header for just_audio playback.
  Uint8List _wrapPcmAsWav(Uint8List pcmData, {int sampleRate = 24000, int bitsPerSample = 16, int channels = 1}) {
    final dataSize = pcmData.length;
    final byteRate = sampleRate * channels * (bitsPerSample ~/ 8);
    final blockAlign = channels * (bitsPerSample ~/ 8);
    final fileSize = 36 + dataSize;

    final header = ByteData(44);
    // "RIFF"
    header.setUint8(0, 0x52); header.setUint8(1, 0x49); header.setUint8(2, 0x46); header.setUint8(3, 0x46);
    header.setUint32(4, fileSize, Endian.little);
    // "WAVE"
    header.setUint8(8, 0x57); header.setUint8(9, 0x41); header.setUint8(10, 0x56); header.setUint8(11, 0x45);
    // "fmt "
    header.setUint8(12, 0x66); header.setUint8(13, 0x6D); header.setUint8(14, 0x74); header.setUint8(15, 0x20);
    header.setUint32(16, 16, Endian.little);  // Subchunk1Size (PCM = 16)
    header.setUint16(20, 1, Endian.little);   // AudioFormat (PCM = 1)
    header.setUint16(22, channels, Endian.little);
    header.setUint32(24, sampleRate, Endian.little);
    header.setUint32(28, byteRate, Endian.little);
    header.setUint16(32, blockAlign, Endian.little);
    header.setUint16(34, bitsPerSample, Endian.little);
    // "data"
    header.setUint8(36, 0x64); header.setUint8(37, 0x61); header.setUint8(38, 0x74); header.setUint8(39, 0x61);
    header.setUint32(40, dataSize, Endian.little);

    final result = Uint8List(44 + dataSize);
    result.setRange(0, 44, header.buffer.asUint8List());
    result.setRange(44, 44 + dataSize, pcmData);
    return result;
  }

  /// Queue trailing silence so the audio doesn't cut off abruptly.
  void queueTrailingSilence({int durationMs = 400}) {
    if (kIsWeb) {
      _webPlayer.queueTrailingSilence(durationMs: durationMs);
    }
  }

  /// Stop all audio playback immediately.
  void stopPlayback() {
    _audioBuffer.clear();
    _isProcessingBuffer = false;
    _webPlayer.stop();
    _mobilePlayer?.stop();
  }

  /// Clean up audio resources.
  void disposeAudio() {
    _audioBuffer.clear();
    _webPlayer.dispose();
    _mobilePlayer?.dispose();
    _mobilePlayer = null;
  }
}

// =============================================================================
// NATE VOICE - Unified Azure Voice Service for Little Nate
// =============================================================================
/// Sends text to the bridge server via WebSocket (`tts_speak` message),
/// which opens an Azure Realtime session with "alloy" voice and streams
/// audio back as `nate_audio_delta` messages. Handles playback via VagusEngine.
///
/// Usage:
///   final nate = NateVoice();
///   nate.onStart = () => setState(() => _isSpeaking = true);
///   nate.onDone  = () => setState(() => _isSpeaking = false);
///   nate.speak("Hello!", _socket);
///
///   // In your WebSocket listener:
///   if (data['type'] == 'nate_audio_delta') nate.handleAudioDelta(data['payload']);
///   if (data['type'] == 'tts_done') nate.handleTtsDone();
class NateVoice {
  final VagusEngine _audio = VagusEngine();
  bool _isSpeaking = false;
  bool get isSpeaking => _isSpeaking;

  /// Fired when Nate starts speaking (first audio chunk arrives)
  VoidCallback? onStart;
  /// Fired when Nate finishes speaking (tts_done received AND audio finishes playing)
  VoidCallback? onDone;

  bool _ttsDoneReceived = false;

  /// Initialize the audio player. Must be called in response to a user gesture
  /// to satisfy browser autoplay policy.
  void initialize() {
    _audio.initializePlayer();
    _audio.onPlaybackComplete = _onAudioDrained;
  }

  void _onAudioDrained() {
    if (_ttsDoneReceived) {
      _isSpeaking = false;
      onDone?.call();
    }
  }

  /// Send a TTS request to the bridge server.
  /// The bridge will open an Azure Realtime session and stream audio back.
  void speak(String text, WebSocketChannel socket) {
    if (text.trim().isEmpty) return;
    _ttsDoneReceived = false;
    _isSpeaking = true;
    onStart?.call();
    socket.sink.add(json.encode({
      "type": "tts_speak",
      "text": text,
    }));
    _debugLog(">>> [NATE_VOICE] Sent tts_speak: ${text.substring(0, text.length.clamp(0, 50))}...");
  }

  /// Route incoming `nate_audio_delta` payload here.
  /// [format] is "pcm" (default, from Realtime API) or "mp3" (from Mini-TTS).
  void handleAudioDelta(String base64Payload, {String format = "pcm"}) {
    if (!_isSpeaking) {
      _isSpeaking = true;
      onStart?.call();
    }
    if (format == "mp3") {
      _audio.processMp3Audio(base64Payload);
    } else {
      _audio.processAudioChunk(base64Payload);
    }
  }

  /// Route incoming `tts_done` message here.
  void handleTtsDone() {
    _debugLog(">>> [NATE_VOICE] tts_done received");
    _ttsDoneReceived = true;
    // Queue a short trailing silence so the audio doesn't cut off abruptly
    _audio.queueTrailingSilence(durationMs: 400);
    // _onAudioDrained will fire when all audio (including trailing silence) completes
  }

  /// Stop speaking immediately.
  void stop() {
    _audio.stopPlayback();
    _isSpeaking = false;
    _ttsDoneReceived = false;
  }

  /// Dispose of resources.
  void dispose() {
    stop();
    _audio.disposeAudio();
  }
}
// =============================================================================
// VISUAL PERSONA - Little Nate Avatar
// =============================================================================
class VisualPersona extends StatefulWidget {
  final bool isTalking, isListening;
  const VisualPersona({super.key, required this.isTalking, required this.isListening});
  @override
  State<VisualPersona> createState() => _VisualPersonaState();
}

class _VisualPersonaState extends State<VisualPersona> with TickerProviderStateMixin {
  late AnimationController _breath, _blink;
  Timer? _blinkTimer;
  
  @override
  void initState() {
    super.initState();
    _breath = AnimationController(vsync: this, duration: const Duration(seconds: 4))..repeat(reverse: true);
    _blink = AnimationController(vsync: this, duration: const Duration(milliseconds: 150));
    
    // 1. FIXED: Timer Check
    _blinkTimer = Timer.periodic(const Duration(seconds: 3), (timer) {
      // CRITICAL SAFETY CHECK: Stop if widget is gone
      if (!mounted) { timer.cancel(); return; }
      
      if (Random().nextDouble() > 0.7) { 
        _blink.forward().then((_) {
          if (mounted) _blink.reverse(); // Double check before reversing
        });
      }
    });
  }

  @override
  void dispose() {
    // 2. FIXED: Proper Cleanup Order
    _blinkTimer?.cancel();
    _breath.dispose();
    _blink.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        CustomPaint(painter: NervousSystemPainter()),
        Center(
          child: AnimatedBuilder(
            animation: _breath,
            builder: (ctx, child) {
              double val = _breath.value;
              Color auraColor = const Color(0xFF00FFFF).withOpacity(0.2 + (0.15 * val));
              return Container(
                width: 180, height: 180,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: const RadialGradient(colors: [Color(0xFF001a33), Color(0xFF000000)], stops: [0.3, 1.0]),
                  boxShadow: [
                    BoxShadow(color: auraColor, blurRadius: 60, spreadRadius: 10 * val),
                    BoxShadow(color: Colors.white.withOpacity(0.1), blurRadius: 10, spreadRadius: -2),
                  ]
                ),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [_buildEye(), const SizedBox(width: 30), _buildEye()]),
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildEye() => AnimatedBuilder(animation: _blink, builder: (ctx, _) {
    double h = 24.0 * (1.0 - _blink.value); if (h < 2) h = 2;
    return Container(width: 24, height: h, decoration: BoxDecoration(color: const Color(0xFF00FFFF).withOpacity(0.6), shape: BoxShape.circle, boxShadow: [BoxShadow(color: const Color(0xFF00FFFF).withOpacity(0.4), blurRadius: 12, spreadRadius: 2)]));
  });
}
class NervousSystemPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = const Color(0xFF00FFFF).withOpacity(0.05);
    for (double i = 0; i < size.width; i += 40) { 
      for (double j = 0; j < size.height; j += 40) { 
        canvas.drawCircle(Offset(i, j), 1, paint); 
      }
    }
  }
  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}