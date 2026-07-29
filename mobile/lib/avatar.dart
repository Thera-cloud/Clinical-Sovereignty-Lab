/// ============================================================================
/// LITTLE NATE AVATAR SYSTEM
/// Version: 1.0
/// 
/// Animated therapeutic avatar with voice interaction for Top Tier clients.
/// Features: 10 expressions, 10 gestures, 7 environments, Azure TTS/STT
/// ============================================================================

import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';
import 'package:model_viewer_plus/model_viewer_plus.dart';
import 'dart:io';

import 'config/app_config.dart';

// =============================================================================
// ENUMS - Avatar States
// =============================================================================

/// 12 expression states for therapeutic emotional resonance
enum AvatarExpression {
  neutral,      // Default resting state
  attentive,    // User is speaking - engaged listening
  thoughtful,   // Processing/thinking
  warm,         // General positive response
  empathetic,   // Responding to user pain/struggle
  encouraging,  // Celebrating progress
  curious,      // Asking questions
  calming,      // Stress/anxiety detected
  proud,        // Milestone achievement
  validating,   // Acknowledging feelings
  sad,          // Responding to grief/loss
  frustrated,   // Mirroring user frustration with understanding
}

/// 10 gesture types for non-verbal communication
enum AvatarGesture {
  none,           // No active gesture
  handOnHeart,    // Empathy/connection
  thumbsUp,       // Approval/encouragement
  handsTogether,  // Grounding/meditation
  chinRest,       // Thoughtful listening
  openPalms,      // Welcoming/safe space
  gentleNod,      // Agreement/validation
  wave,           // Greeting
  pointToSelf,    // Self-reference
  breatheGuide,   // Leading breathing exercise
}

/// Body positioning for subtle emotional cues
enum AvatarBodyPosition {
  relaxedNeutral,   // Default comfortable stance
  attentiveLean,    // Leaning in with interest
  openWelcoming,    // Arms open, inviting
  thoughtfulBack,   // Slight lean back, considering
  celebratoryRaise, // Slight rise for celebration
}

/// 7 adaptive environment backgrounds
enum AvatarEnvironment {
  cozyStudy,      // Default - warm wood, books, soft lamp
  sereneNature,   // Forest/garden setting
  beachSunset,    // Calming ocean view
  cloudySky,      // Soft, dreamy atmosphere
  starryNight,    // Night sky, peaceful
  warmFireplace,  // Intimate, grounding
  zenGarden,      // Minimalist, focused
}

/// Voice interaction states
enum VoiceState {
  idle,       // Not in voice mode
  listening,  // Capturing user speech
  thinking,   // Processing response
  speaking,   // Avatar is talking
}

// =============================================================================
// DATA MODELS
// =============================================================================

/// Complete visual state of the avatar at any moment
class AvatarVisualState {
  final AvatarExpression expression;
  final AvatarGesture gesture;
  final AvatarBodyPosition bodyPosition;
  final AvatarEnvironment environment;
  final String lighting; // 'warm', 'cool', 'natural', 'dim'
  final double intensity; // 0.0 - 1.0, how strongly to show expression

  const AvatarVisualState({
    this.expression = AvatarExpression.neutral,
    this.gesture = AvatarGesture.none,
    this.bodyPosition = AvatarBodyPosition.relaxedNeutral,
    this.environment = AvatarEnvironment.cozyStudy,
    this.lighting = 'warm',
    this.intensity = 0.7,
  });

  AvatarVisualState copyWith({
    AvatarExpression? expression,
    AvatarGesture? gesture,
    AvatarBodyPosition? bodyPosition,
    AvatarEnvironment? environment,
    String? lighting,
    double? intensity,
  }) {
    return AvatarVisualState(
      expression: expression ?? this.expression,
      gesture: gesture ?? this.gesture,
      bodyPosition: bodyPosition ?? this.bodyPosition,
      environment: environment ?? this.environment,
      lighting: lighting ?? this.lighting,
      intensity: intensity ?? this.intensity,
    );
  }

  factory AvatarVisualState.fromJson(Map<String, dynamic> json) {
    return AvatarVisualState(
      expression: AvatarExpression.values.firstWhere(
        (e) => e.name.toUpperCase() == (json['expression'] ?? 'NEUTRAL').toString().toUpperCase(),
        orElse: () => AvatarExpression.neutral,
      ),
      gesture: AvatarGesture.values.firstWhere(
        (g) => g.name.toUpperCase() == (json['gesture'] ?? 'NONE').toString().toUpperCase().replaceAll('_', ''),
        orElse: () => AvatarGesture.none,
      ),
      bodyPosition: AvatarBodyPosition.values.firstWhere(
        (b) => b.name.toUpperCase() == (json['body_position'] ?? 'RELAXED_NEUTRAL').toString().toUpperCase().replaceAll('_', ''),
        orElse: () => AvatarBodyPosition.relaxedNeutral,
      ),
      environment: AvatarEnvironment.values.firstWhere(
        (e) => e.name.toUpperCase() == (json['environment'] ?? 'COZY_STUDY').toString().toUpperCase().replaceAll('_', ''),
        orElse: () => AvatarEnvironment.cozyStudy,
      ),
      lighting: json['lighting'] ?? 'warm',
      intensity: (json['intensity'] ?? 0.7).toDouble(),
    );
  }
}

/// Avatar appearance customization
class AvatarAppearanceConfig {
  final String skinTone;       // 'light', 'medium', 'tan', 'dark'
  final String hairStyle;      // 'short_classic', 'balding', 'wavy', etc.
  final String hairColor;      // 'salt_pepper', 'brown', 'gray', etc.
  final String eyeColor;       // 'brown', 'blue', 'green', 'hazel'
  final String? glasses;       // 'thin_metal', 'thick_frame', null for none
  final String clothingStyle;  // 'cardigan', 'sweater', 'blazer'
  final String clothingColor;  // 'navy', 'burgundy', 'forest_green'
  final bool showBeard;
  final String beardStyle;     // 'clean', 'stubble', 'short', 'full'

  const AvatarAppearanceConfig({
    this.skinTone = 'medium',
    this.hairStyle = 'short_classic',
    this.hairColor = 'salt_pepper',
    this.eyeColor = 'brown',
    this.glasses = 'thin_metal',
    this.clothingStyle = 'cardigan',
    this.clothingColor = 'navy',
    this.showBeard = false,
    this.beardStyle = 'clean',
  });

  factory AvatarAppearanceConfig.fromJson(Map<String, dynamic> json) {
    return AvatarAppearanceConfig(
      skinTone: json['skin_tone'] ?? 'medium',
      hairStyle: json['hair_style'] ?? 'short_classic',
      hairColor: json['hair_color'] ?? 'salt_pepper',
      eyeColor: json['eye_color'] ?? 'brown',
      glasses: json['glasses'],
      clothingStyle: json['clothing_style'] ?? 'cardigan',
      clothingColor: json['clothing_color'] ?? 'navy',
      showBeard: json['show_beard'] ?? false,
      beardStyle: json['beard_style'] ?? 'clean',
    );
  }
}

// =============================================================================
// AZURE TTS SERVICE
// =============================================================================

/// Azure Text-to-Speech service with SSML and emotion mapping
class AzureTTSService {
  // Azure Speech credentials — loaded from AppConfig (never hardcode)
  static String get _speechKey => const String.fromEnvironment('AZURE_SPEECH_KEY', defaultValue: '');
  static String get _region => const String.fromEnvironment('AZURE_SPEECH_REGION', defaultValue: 'eastus');
  
  final AudioPlayer _audioPlayer = AudioPlayer();
  String? _accessToken;
  DateTime? _tokenExpiry;

  /// Get or refresh Azure access token
  Future<String?> _getAccessToken() async {
    if (_accessToken != null && _tokenExpiry != null && 
        DateTime.now().isBefore(_tokenExpiry!.subtract(const Duration(minutes: 5)))) {
      return _accessToken;
    }

    try {
      final response = await http.post(
        Uri.parse('https://$_region.api.cognitive.microsoft.com/sts/v1.0/issueToken'),
        headers: {
          'Ocp-Apim-Subscription-Key': _speechKey,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      );

      if (response.statusCode == 200) {
        _accessToken = response.body;
        _tokenExpiry = DateTime.now().add(const Duration(minutes: 9));
        return _accessToken;
      }
    } catch (e) {
      debugPrint('[AzureTTS] Token error: $e');
    }
    return null;
  }

  /// Map avatar expression to Azure voice style
  String _mapEmotionToStyle(AvatarExpression expression) {
    switch (expression) {
      case AvatarExpression.empathetic:
      case AvatarExpression.validating:
        return 'empathetic';
      case AvatarExpression.encouraging:
      case AvatarExpression.proud:
        return 'cheerful';
      case AvatarExpression.calming:
        return 'calm';
      case AvatarExpression.curious:
        return 'friendly';
      case AvatarExpression.warm:
        return 'gentle';
      case AvatarExpression.thoughtful:
        return 'serious';
      default:
        return 'friendly';
    }
  }

  /// Build SSML for expressive speech
  String _buildSSML(String text, AvatarExpression expression, {double rate = 1.0, double pitch = 1.0}) {
    final style = _mapEmotionToStyle(expression);
    final pitchPercent = ((pitch - 1.0) * 50).round();
    final pitchStr = pitchPercent >= 0 ? '+$pitchPercent%' : '$pitchPercent%';
    final rateStr = '${(rate * 100).round()}%';

    return '''
<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" 
       xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">
  <voice name="en-US-GuyNeural">
    <mstts:express-as style="$style" styledegree="1.2">
      <prosody rate="$rateStr" pitch="$pitchStr">
        $text
      </prosody>
    </mstts:express-as>
  </voice>
</speak>
''';
  }

  /// Synthesize speech and return audio bytes
  Future<Uint8List?> synthesizeSpeech(
    String text, 
    AvatarExpression expression, {
    double rate = 1.0,
    double pitch = 1.0,
  }) async {
    final token = await _getAccessToken();
    if (token == null) {
      debugPrint('[AzureTTS] Failed to get token');
      return null;
    }

    try {
      final ssml = _buildSSML(text, expression, rate: rate, pitch: pitch);
      
      final response = await http.post(
        Uri.parse('https://$_region.tts.speech.microsoft.com/cognitiveservices/v1'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/ssml+xml',
          'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3',
          'User-Agent': 'LittleNateAvatar',
        },
        body: ssml,
      );

      if (response.statusCode == 200) {
        return response.bodyBytes;
      } else {
        debugPrint('[AzureTTS] Synthesis failed: ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('[AzureTTS] Synthesis error: $e');
    }
    return null;
  }

  /// Play audio bytes through the audio player
  Future<void> playAudio(Uint8List audioBytes) async {
    try {
      // Save to temp file for playback
      final tempDir = await getTemporaryDirectory();
      final tempFile = File('${tempDir.path}/nate_speech_${DateTime.now().millisecondsSinceEpoch}.mp3');
      await tempFile.writeAsBytes(audioBytes);
      
      await _audioPlayer.play(DeviceFileSource(tempFile.path));
      
      // Clean up after playback
      _audioPlayer.onPlayerComplete.first.then((_) {
        tempFile.deleteSync();
      });
    } catch (e) {
      debugPrint('[AzureTTS] Playback error: $e');
    }
  }

  /// Check if currently playing
  bool get isPlaying => _audioPlayer.state == PlayerState.playing;

  /// Stop playback
  Future<void> stop() async {
    await _audioPlayer.stop();
  }

  /// Dispose resources
  void dispose() {
    _audioPlayer.dispose();
  }
}

// =============================================================================
// AZURE STT SERVICE
// =============================================================================

/// Azure Speech-to-Text service for voice input
class AzureSTTService {
  final stt.SpeechToText _speech = stt.SpeechToText();
  bool _isInitialized = false;
  
  final StreamController<String> _partialController = StreamController<String>.broadcast();
  final StreamController<String> _finalController = StreamController<String>.broadcast();
  
  Stream<String> get partialTranscriptions => _partialController.stream;
  Stream<String> get finalTranscriptions => _finalController.stream;

  /// Initialize speech recognition
  Future<bool> initialize() async {
    if (_isInitialized) return true;
    
    try {
      _isInitialized = await _speech.initialize(
        onStatus: (status) {
          debugPrint('[AzureSTT] Status: $status');
        },
        onError: (error) {
          debugPrint('[AzureSTT] Error: ${error.errorMsg}');
        },
      );
      return _isInitialized;
    } catch (e) {
      debugPrint('[AzureSTT] Init error: $e');
      return false;
    }
  }

  /// Start listening for speech
  Future<void> startListening({
    Duration pauseFor = const Duration(seconds: 2),
    Duration listenFor = const Duration(seconds: 30),
  }) async {
    if (!_isInitialized) {
      await initialize();
    }
    
    await _speech.listen(
      onResult: (result) {
        if (result.finalResult) {
          _finalController.add(result.recognizedWords);
        } else {
          _partialController.add(result.recognizedWords);
        }
      },
      pauseFor: pauseFor,
      listenFor: listenFor,
      partialResults: true,
      listenMode: stt.ListenMode.dictation,
    );
  }

  /// Stop listening
  Future<void> stopListening() async {
    await _speech.stop();
  }

  /// Check if currently listening
  bool get isListening => _speech.isListening;

  /// Dispose resources
  void dispose() {
    _partialController.close();
    _finalController.close();
  }
}

// =============================================================================
// EXPRESSION STATE MACHINE
// =============================================================================

/// Manages smooth transitions between avatar expressions
class ExpressionStateMachine {
  AvatarExpression _current = AvatarExpression.neutral;
  AvatarExpression _target = AvatarExpression.neutral;
  double _blendProgress = 1.0;
  DateTime _transitionStart = DateTime.now();
  Duration _transitionDuration = const Duration(milliseconds: 500);

  AvatarExpression get current => _current;
  AvatarExpression get target => _target;
  double get blendProgress => _blendProgress;

  /// Transition to a new expression
  void transitionTo(AvatarExpression expression, {Duration? duration}) {
    if (expression == _target) return;
    
    _current = _target;
    _target = expression;
    _blendProgress = 0.0;
    _transitionStart = DateTime.now();
    _transitionDuration = duration ?? const Duration(milliseconds: 500);
  }

  /// Update blend progress based on time
  void update() {
    if (_blendProgress >= 1.0) return;
    
    final elapsed = DateTime.now().difference(_transitionStart);
    _blendProgress = (elapsed.inMilliseconds / _transitionDuration.inMilliseconds).clamp(0.0, 1.0);
    
    // Apply easing
    _blendProgress = _easeInOutCubic(_blendProgress);
  }

  double _easeInOutCubic(double t) {
    return t < 0.5 
        ? 4 * t * t * t 
        : 1 - math.pow(-2 * t + 2, 3) / 2;
  }

  /// Get interpolated mouth parameters
  Map<String, double> getMouthParams() {
    final currentParams = _mouthParamsFor(_current);
    final targetParams = _mouthParamsFor(_target);
    
    return {
      'openness': _lerp(currentParams['openness']!, targetParams['openness']!, _blendProgress),
      'smile': _lerp(currentParams['smile']!, targetParams['smile']!, _blendProgress),
      'width': _lerp(currentParams['width']!, targetParams['width']!, _blendProgress),
    };
  }

  /// Get interpolated eyebrow parameters
  Map<String, double> getEyebrowParams() {
    final currentParams = _eyebrowParamsFor(_current);
    final targetParams = _eyebrowParamsFor(_target);
    
    return {
      'raise': _lerp(currentParams['raise']!, targetParams['raise']!, _blendProgress),
      'furrow': _lerp(currentParams['furrow']!, targetParams['furrow']!, _blendProgress),
    };
  }

  /// Get interpolated eye parameters
  Map<String, double> getEyeParams() {
    final currentParams = _eyeParamsFor(_current);
    final targetParams = _eyeParamsFor(_target);
    
    return {
      'openness': _lerp(currentParams['openness']!, targetParams['openness']!, _blendProgress),
      'softness': _lerp(currentParams['softness']!, targetParams['softness']!, _blendProgress),
    };
  }

  double _lerp(double a, double b, double t) => a + (b - a) * t;

  Map<String, double> _mouthParamsFor(AvatarExpression expr) {
    switch (expr) {
      case AvatarExpression.neutral:
        return {'openness': 0.0, 'smile': 0.2, 'width': 1.0};
      case AvatarExpression.attentive:
        return {'openness': 0.1, 'smile': 0.3, 'width': 1.0};
      case AvatarExpression.thoughtful:
        return {'openness': 0.0, 'smile': 0.1, 'width': 0.9};
      case AvatarExpression.warm:
        return {'openness': 0.1, 'smile': 0.6, 'width': 1.1};
      case AvatarExpression.empathetic:
        return {'openness': 0.15, 'smile': 0.3, 'width': 1.0};
      case AvatarExpression.encouraging:
        return {'openness': 0.3, 'smile': 0.8, 'width': 1.2};
      case AvatarExpression.curious:
        return {'openness': 0.2, 'smile': 0.4, 'width': 1.0};
      case AvatarExpression.calming:
        return {'openness': 0.0, 'smile': 0.4, 'width': 1.0};
      case AvatarExpression.proud:
        return {'openness': 0.4, 'smile': 0.9, 'width': 1.2};
      case AvatarExpression.validating:
        return {'openness': 0.1, 'smile': 0.5, 'width': 1.0};
      case AvatarExpression.sad:
        return {'openness': 0.0, 'smile': -0.3, 'width': 0.9};
      case AvatarExpression.frustrated:
        return {'openness': 0.05, 'smile': -0.1, 'width': 0.95};
    }
  }

  Map<String, double> _eyebrowParamsFor(AvatarExpression expr) {
    switch (expr) {
      case AvatarExpression.neutral:
        return {'raise': 0.0, 'furrow': 0.0};
      case AvatarExpression.attentive:
        return {'raise': 0.3, 'furrow': 0.0};
      case AvatarExpression.thoughtful:
        return {'raise': 0.1, 'furrow': 0.2};
      case AvatarExpression.warm:
        return {'raise': 0.2, 'furrow': 0.0};
      case AvatarExpression.empathetic:
        return {'raise': 0.4, 'furrow': 0.3};
      case AvatarExpression.encouraging:
        return {'raise': 0.5, 'furrow': 0.0};
      case AvatarExpression.curious:
        return {'raise': 0.6, 'furrow': 0.0};
      case AvatarExpression.calming:
        return {'raise': 0.1, 'furrow': 0.0};
      case AvatarExpression.proud:
        return {'raise': 0.4, 'furrow': 0.0};
      case AvatarExpression.validating:
        return {'raise': 0.3, 'furrow': 0.1};
      case AvatarExpression.sad:
        return {'raise': 0.5, 'furrow': 0.4};
      case AvatarExpression.frustrated:
        return {'raise': 0.2, 'furrow': 0.6};
    }
  }

  Map<String, double> _eyeParamsFor(AvatarExpression expr) {
    switch (expr) {
      case AvatarExpression.neutral:
        return {'openness': 1.0, 'softness': 0.5};
      case AvatarExpression.attentive:
        return {'openness': 1.1, 'softness': 0.3};
      case AvatarExpression.thoughtful:
        return {'openness': 0.85, 'softness': 0.6};
      case AvatarExpression.warm:
        return {'openness': 0.9, 'softness': 0.8};
      case AvatarExpression.empathetic:
        return {'openness': 0.95, 'softness': 0.9};
      case AvatarExpression.encouraging:
        return {'openness': 1.1, 'softness': 0.4};
      case AvatarExpression.curious:
        return {'openness': 1.15, 'softness': 0.3};
      case AvatarExpression.calming:
        return {'openness': 0.85, 'softness': 0.9};
      case AvatarExpression.proud:
        return {'openness': 0.9, 'softness': 0.7};
      case AvatarExpression.validating:
        return {'openness': 0.95, 'softness': 0.8};
      case AvatarExpression.sad:
        return {'openness': 0.9, 'softness': 0.95};
      case AvatarExpression.frustrated:
        return {'openness': 1.05, 'softness': 0.4};
    }
  }
}

// =============================================================================
// ENVIRONMENT RENDERER
// =============================================================================

/// Renders adaptive environment backgrounds
class EnvironmentRenderer {
  /// Get gradient colors for environment
  static List<Color> getGradient(AvatarEnvironment env, String lighting) {
    final baseColors = _getBaseColors(env);
    return _applyLighting(baseColors, lighting);
  }

  static List<Color> _getBaseColors(AvatarEnvironment env) {
    switch (env) {
      case AvatarEnvironment.cozyStudy:
        return [const Color(0xFF2C1810), const Color(0xFF4A3728), const Color(0xFF1A0F0A)];
      case AvatarEnvironment.sereneNature:
        return [const Color(0xFF1A3A2F), const Color(0xFF2D5A4A), const Color(0xFF0F2A1F)];
      case AvatarEnvironment.beachSunset:
        return [const Color(0xFF4A2040), const Color(0xFFB85A30), const Color(0xFF1A1030)];
      case AvatarEnvironment.cloudySky:
        return [const Color(0xFF3A4A5A), const Color(0xFF5A6A7A), const Color(0xFF2A3A4A)];
      case AvatarEnvironment.starryNight:
        return [const Color(0xFF0A0A1A), const Color(0xFF1A1A3A), const Color(0xFF050510)];
      case AvatarEnvironment.warmFireplace:
        return [const Color(0xFF3A1A0A), const Color(0xFF5A2A10), const Color(0xFF1A0A00)];
      case AvatarEnvironment.zenGarden:
        return [const Color(0xFFE8E0D0), const Color(0xFFD0C8B8), const Color(0xFFA09080)];
    }
  }

  static List<Color> _applyLighting(List<Color> colors, String lighting) {
    double factor = 1.0;
    switch (lighting) {
      case 'warm':
        factor = 1.1;
        break;
      case 'cool':
        factor = 0.9;
        break;
      case 'dim':
        factor = 0.7;
        break;
      case 'natural':
      default:
        factor = 1.0;
    }
    
    return colors.map((c) => Color.fromRGBO(
      (c.red * factor).clamp(0, 255).round(),
      (c.green * factor).clamp(0, 255).round(),
      (c.blue * factor).clamp(0, 255).round(),
      c.opacity,
    )).toList();
  }

  /// Build background widget
  static Widget buildBackground(AvatarEnvironment env, String lighting) {
    final colors = getGradient(env, lighting);
    
    return Container(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: colors,
          stops: const [0.0, 0.5, 1.0],
        ),
      ),
      child: _buildEnvironmentDetails(env),
    );
  }

  static Widget _buildEnvironmentDetails(AvatarEnvironment env) {
    switch (env) {
      case AvatarEnvironment.starryNight:
        return _buildStars();
      case AvatarEnvironment.warmFireplace:
        return _buildFireGlow();
      default:
        return const SizedBox.shrink();
    }
  }

  static Widget _buildStars() {
    return CustomPaint(
      painter: _StarsPainter(),
      size: Size.infinite,
    );
  }

  static Widget _buildFireGlow() {
    return Positioned(
      bottom: 50,
      left: 0,
      right: 0,
      child: Container(
        height: 100,
        decoration: BoxDecoration(
          gradient: RadialGradient(
            center: Alignment.bottomCenter,
            radius: 1.5,
            colors: [
              Colors.orange.withOpacity(0.3),
              Colors.transparent,
            ],
          ),
        ),
      ),
    );
  }
}

class _StarsPainter extends CustomPainter {
  final math.Random _random = math.Random(42);

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = Colors.white;
    
    for (int i = 0; i < 50; i++) {
      final x = _random.nextDouble() * size.width;
      final y = _random.nextDouble() * size.height * 0.7;
      final radius = _random.nextDouble() * 1.5 + 0.5;
      final opacity = _random.nextDouble() * 0.5 + 0.3;
      
      paint.color = Colors.white.withOpacity(opacity);
      canvas.drawCircle(Offset(x, y), radius, paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

// =============================================================================
// AVATAR FACE PAINTER
// =============================================================================

/// CustomPainter for rendering the avatar face
class AvatarFacePainter extends CustomPainter {
  final ExpressionStateMachine expressionEngine;
  final AvatarAppearanceConfig appearance;
  final double blinkValue; // 0.0 = open, 1.0 = closed
  final double breathValue; // -1.0 to 1.0, affects subtle movement
  final double mouthOpenness; // 0.0 to 1.0, for speech animation

  AvatarFacePainter({
    required this.expressionEngine,
    required this.appearance,
    this.blinkValue = 0.0,
    this.breathValue = 0.0,
    this.mouthOpenness = 0.0,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final faceRadius = size.width * 0.35;

    // Apply subtle breathing movement
    final breathOffset = Offset(0, breathValue * 3);
    final adjustedCenter = center + breathOffset;

    // Draw head/face
    _drawFace(canvas, adjustedCenter, faceRadius);
    
    // Draw hair
    _drawHair(canvas, adjustedCenter, faceRadius);
    
    // Draw eyes
    _drawEyes(canvas, adjustedCenter, faceRadius);
    
    // Draw eyebrows
    _drawEyebrows(canvas, adjustedCenter, faceRadius);
    
    // Draw nose
    _drawNose(canvas, adjustedCenter, faceRadius);
    
    // Draw mouth
    _drawMouth(canvas, adjustedCenter, faceRadius);
    
    // Draw glasses if configured
    if (appearance.glasses != null) {
      _drawGlasses(canvas, adjustedCenter, faceRadius);
    }
    
    // Draw beard if configured
    if (appearance.showBeard) {
      _drawBeard(canvas, adjustedCenter, faceRadius);
    }
  }

  void _drawFace(Canvas canvas, Offset center, double radius) {
    final skinColor = _getSkinColor(appearance.skinTone);
    
    // Face shape - slightly oval
    final faceRect = Rect.fromCenter(
      center: center,
      width: radius * 2,
      height: radius * 2.2,
    );
    
    final facePaint = Paint()
      ..color = skinColor
      ..style = PaintingStyle.fill;
    
    canvas.drawOval(faceRect, facePaint);
    
    // Subtle shadow for depth
    final shadowPaint = Paint()
      ..color = Colors.black.withOpacity(0.1)
      ..style = PaintingStyle.fill;
    
    final shadowPath = Path()
      ..addOval(Rect.fromCenter(
        center: center + const Offset(0, 10),
        width: radius * 2,
        height: radius * 2.2,
      ));
    
    canvas.drawPath(shadowPath, shadowPaint);
  }

  void _drawHair(Canvas canvas, Offset center, double radius) {
    final hairColor = _getHairColor(appearance.hairColor);
    final hairPaint = Paint()
      ..color = hairColor
      ..style = PaintingStyle.fill;

    final hairPath = Path();
    
    // Simple hair shape based on style
    switch (appearance.hairStyle) {
      case 'balding':
        // Receding hairline
        hairPath.moveTo(center.dx - radius * 0.8, center.dy - radius * 0.8);
        hairPath.quadraticBezierTo(
          center.dx, center.dy - radius * 1.4,
          center.dx + radius * 0.8, center.dy - radius * 0.8,
        );
        hairPath.lineTo(center.dx + radius * 0.6, center.dy - radius * 0.6);
        hairPath.quadraticBezierTo(
          center.dx, center.dy - radius * 1.0,
          center.dx - radius * 0.6, center.dy - radius * 0.6,
        );
        hairPath.close();
        break;
      case 'wavy':
        // Fuller wavy hair
        hairPath.moveTo(center.dx - radius, center.dy - radius * 0.5);
        hairPath.quadraticBezierTo(
          center.dx - radius * 0.5, center.dy - radius * 1.5,
          center.dx, center.dy - radius * 1.3,
        );
        hairPath.quadraticBezierTo(
          center.dx + radius * 0.5, center.dy - radius * 1.5,
          center.dx + radius, center.dy - radius * 0.5,
        );
        hairPath.quadraticBezierTo(
          center.dx + radius * 0.7, center.dy - radius * 0.8,
          center.dx, center.dy - radius * 0.7,
        );
        hairPath.quadraticBezierTo(
          center.dx - radius * 0.7, center.dy - radius * 0.8,
          center.dx - radius, center.dy - radius * 0.5,
        );
        break;
      default: // short_classic
        hairPath.moveTo(center.dx - radius * 0.9, center.dy - radius * 0.6);
        hairPath.quadraticBezierTo(
          center.dx, center.dy - radius * 1.3,
          center.dx + radius * 0.9, center.dy - radius * 0.6,
        );
        hairPath.quadraticBezierTo(
          center.dx + radius * 0.6, center.dy - radius * 0.9,
          center.dx, center.dy - radius * 0.85,
        );
        hairPath.quadraticBezierTo(
          center.dx - radius * 0.6, center.dy - radius * 0.9,
          center.dx - radius * 0.9, center.dy - radius * 0.6,
        );
    }
    
    canvas.drawPath(hairPath, hairPaint);
  }

  void _drawEyes(Canvas canvas, Offset center, double radius) {
    final eyeParams = expressionEngine.getEyeParams();
    final eyeOpenness = eyeParams['openness']! * (1 - blinkValue);
    
    final eyeColor = _getEyeColor(appearance.eyeColor);
    final eyeSpacing = radius * 0.35;
    final eyeY = center.dy - radius * 0.15;
    
    for (final side in [-1, 1]) {
      final eyeCenter = Offset(center.dx + side * eyeSpacing, eyeY);
      
      // Eye white
      final eyeWhitePaint = Paint()
        ..color = Colors.white
        ..style = PaintingStyle.fill;
      
      final eyeWidth = radius * 0.25;
      final eyeHeight = radius * 0.15 * eyeOpenness;
      
      canvas.drawOval(
        Rect.fromCenter(center: eyeCenter, width: eyeWidth, height: eyeHeight),
        eyeWhitePaint,
      );
      
      // Iris
      if (eyeOpenness > 0.3) {
        final irisPaint = Paint()
          ..color = eyeColor
          ..style = PaintingStyle.fill;
        
        final irisRadius = radius * 0.08;
        canvas.drawCircle(eyeCenter, irisRadius, irisPaint);
        
        // Pupil
        final pupilPaint = Paint()
          ..color = Colors.black
          ..style = PaintingStyle.fill;
        
        canvas.drawCircle(eyeCenter, irisRadius * 0.5, pupilPaint);
        
        // Eye highlight
        final highlightPaint = Paint()
          ..color = Colors.white.withOpacity(0.8)
          ..style = PaintingStyle.fill;
        
        canvas.drawCircle(
          eyeCenter + Offset(-irisRadius * 0.3, -irisRadius * 0.3),
          irisRadius * 0.25,
          highlightPaint,
        );
      }
    }
  }

  void _drawEyebrows(Canvas canvas, Offset center, double radius) {
    final browParams = expressionEngine.getEyebrowParams();
    final raise = browParams['raise']!;
    final furrow = browParams['furrow']!;
    
    final browColor = _getHairColor(appearance.hairColor);
    final browPaint = Paint()
      ..color = browColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = radius * 0.04
      ..strokeCap = StrokeCap.round;
    
    final eyeSpacing = radius * 0.35;
    final browY = center.dy - radius * 0.35 - raise * radius * 0.1;
    
    for (final side in [-1, 1]) {
      final browStart = Offset(center.dx + side * (eyeSpacing - radius * 0.15), browY + furrow * radius * 0.05);
      final browEnd = Offset(center.dx + side * (eyeSpacing + radius * 0.15), browY - side * furrow * radius * 0.03);
      
      canvas.drawLine(browStart, browEnd, browPaint);
    }
  }

  void _drawNose(Canvas canvas, Offset center, double radius) {
    final nosePaint = Paint()
      ..color = _getSkinColor(appearance.skinTone).withOpacity(0.3)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;
    
    final nosePath = Path()
      ..moveTo(center.dx, center.dy - radius * 0.1)
      ..lineTo(center.dx, center.dy + radius * 0.15)
      ..quadraticBezierTo(
        center.dx + radius * 0.08, center.dy + radius * 0.18,
        center.dx, center.dy + radius * 0.2,
      );
    
    canvas.drawPath(nosePath, nosePaint);
  }

  void _drawMouth(Canvas canvas, Offset center, double radius) {
    final mouthParams = expressionEngine.getMouthParams();
    final baseOpenness = mouthParams['openness']!;
    final smile = mouthParams['smile']!;
    final width = mouthParams['width']!;
    
    // Combine base openness with speech animation
    final openness = math.max(baseOpenness, mouthOpenness);
    
    final mouthY = center.dy + radius * 0.4;
    final mouthWidth = radius * 0.3 * width;
    
    // Lips
    final lipColor = Color.lerp(
      _getSkinColor(appearance.skinTone),
      const Color(0xFFB86B77),
      0.5,
    )!;
    
    final lipPaint = Paint()
      ..color = lipColor
      ..style = PaintingStyle.fill;
    
    final mouthPath = Path();
    
    if (openness > 0.1) {
      // Open mouth
      mouthPath.moveTo(center.dx - mouthWidth, mouthY);
      mouthPath.quadraticBezierTo(
        center.dx, mouthY - smile * radius * 0.1,
        center.dx + mouthWidth, mouthY,
      );
      mouthPath.quadraticBezierTo(
        center.dx, mouthY + openness * radius * 0.2,
        center.dx - mouthWidth, mouthY,
      );
      
      // Draw mouth interior
      final interiorPaint = Paint()
        ..color = const Color(0xFF400020)
        ..style = PaintingStyle.fill;
      
      canvas.drawPath(mouthPath, interiorPaint);
      
      // Draw lips outline
      final outlinePaint = Paint()
        ..color = lipColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = radius * 0.02;
      
      canvas.drawPath(mouthPath, outlinePaint);
    } else {
      // Closed mouth - just a curved line
      mouthPath.moveTo(center.dx - mouthWidth, mouthY);
      mouthPath.quadraticBezierTo(
        center.dx, mouthY - smile * radius * 0.15,
        center.dx + mouthWidth, mouthY,
      );
      
      final closedPaint = Paint()
        ..color = lipColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = radius * 0.03
        ..strokeCap = StrokeCap.round;
      
      canvas.drawPath(mouthPath, closedPaint);
    }
  }

  void _drawGlasses(Canvas canvas, Offset center, double radius) {
    final glassesPaint = Paint()
      ..color = appearance.glasses == 'thick_frame' 
          ? Colors.black 
          : const Color(0xFF808080)
      ..style = PaintingStyle.stroke
      ..strokeWidth = appearance.glasses == 'thick_frame' ? 3.0 : 1.5;
    
    final eyeSpacing = radius * 0.35;
    final eyeY = center.dy - radius * 0.15;
    final lensRadius = radius * 0.18;
    
    // Left lens
    canvas.drawCircle(Offset(center.dx - eyeSpacing, eyeY), lensRadius, glassesPaint);
    
    // Right lens
    canvas.drawCircle(Offset(center.dx + eyeSpacing, eyeY), lensRadius, glassesPaint);
    
    // Bridge
    canvas.drawLine(
      Offset(center.dx - eyeSpacing + lensRadius, eyeY),
      Offset(center.dx + eyeSpacing - lensRadius, eyeY),
      glassesPaint,
    );
    
    // Temple arms (simplified)
    canvas.drawLine(
      Offset(center.dx - eyeSpacing - lensRadius, eyeY),
      Offset(center.dx - radius * 0.9, eyeY - radius * 0.05),
      glassesPaint,
    );
    canvas.drawLine(
      Offset(center.dx + eyeSpacing + lensRadius, eyeY),
      Offset(center.dx + radius * 0.9, eyeY - radius * 0.05),
      glassesPaint,
    );
  }

  void _drawBeard(Canvas canvas, Offset center, double radius) {
    final beardColor = _getHairColor(appearance.hairColor);
    final beardPaint = Paint()
      ..color = beardColor.withOpacity(0.7)
      ..style = PaintingStyle.fill;
    
    final beardPath = Path();
    
    switch (appearance.beardStyle) {
      case 'stubble':
        // Draw dots pattern
        final stubblePaint = Paint()
          ..color = beardColor.withOpacity(0.4)
          ..style = PaintingStyle.fill;
        
        final random = math.Random(42);
        for (int i = 0; i < 100; i++) {
          final x = center.dx + (random.nextDouble() - 0.5) * radius * 1.2;
          final y = center.dy + radius * 0.3 + random.nextDouble() * radius * 0.6;
          if ((Offset(x, y) - center).distance < radius * 0.9) {
            canvas.drawCircle(Offset(x, y), 1, stubblePaint);
          }
        }
        break;
      case 'short':
      case 'full':
        beardPath.moveTo(center.dx - radius * 0.6, center.dy + radius * 0.2);
        beardPath.quadraticBezierTo(
          center.dx - radius * 0.5, center.dy + radius * 0.8,
          center.dx, center.dy + radius * (appearance.beardStyle == 'full' ? 1.0 : 0.7),
        );
        beardPath.quadraticBezierTo(
          center.dx + radius * 0.5, center.dy + radius * 0.8,
          center.dx + radius * 0.6, center.dy + radius * 0.2,
        );
        canvas.drawPath(beardPath, beardPaint);
        break;
    }
  }

  Color _getSkinColor(String tone) {
    switch (tone) {
      case 'light':
        return const Color(0xFFFCE4D6);
      case 'medium':
        return const Color(0xFFE8C4A8);
      case 'tan':
        return const Color(0xFFD4A574);
      case 'dark':
        return const Color(0xFF8B6B4E);
      default:
        return const Color(0xFFE8C4A8);
    }
  }

  Color _getHairColor(String color) {
    switch (color) {
      case 'salt_pepper':
        return const Color(0xFF5A5A5A);
      case 'brown':
        return const Color(0xFF4A3728);
      case 'gray':
        return const Color(0xFF808080);
      case 'black':
        return const Color(0xFF1A1A1A);
      case 'blonde':
        return const Color(0xFFD4B483);
      case 'red':
        return const Color(0xFF8B4513);
      default:
        return const Color(0xFF5A5A5A);
    }
  }

  Color _getEyeColor(String color) {
    switch (color) {
      case 'brown':
        return const Color(0xFF634E34);
      case 'blue':
        return const Color(0xFF4A90A4);
      case 'green':
        return const Color(0xFF2E8B57);
      case 'hazel':
        return const Color(0xFF8E7618);
      default:
        return const Color(0xFF634E34);
    }
  }

  @override
  bool shouldRepaint(AvatarFacePainter oldDelegate) {
    return oldDelegate.blinkValue != blinkValue ||
           oldDelegate.breathValue != breathValue ||
           oldDelegate.mouthOpenness != mouthOpenness ||
           oldDelegate.expressionEngine.blendProgress != expressionEngine.blendProgress;
  }
}

// =============================================================================
// LITTLE NATE AVATAR WIDGET
// =============================================================================

/// Main avatar widget with animations
class LittleNateAvatar extends StatefulWidget {
  final AvatarAppearanceConfig appearance;
  final AvatarVisualState visualState;
  final VoiceState voiceState;
  final double mouthOpenness;
  final VoidCallback? onTap;

  const LittleNateAvatar({
    super.key,
    this.appearance = const AvatarAppearanceConfig(),
    this.visualState = const AvatarVisualState(),
    this.voiceState = VoiceState.idle,
    this.mouthOpenness = 0.0,
    this.onTap,
  });

  @override
  State<LittleNateAvatar> createState() => _LittleNateAvatarState();
}

class _LittleNateAvatarState extends State<LittleNateAvatar> with TickerProviderStateMixin {
  late AnimationController _breathController;
  late AnimationController _blinkController;
  late Animation<double> _breathAnimation;
  late Animation<double> _blinkAnimation;
  
  final ExpressionStateMachine _expressionEngine = ExpressionStateMachine();
  Timer? _blinkTimer;
  Timer? _expressionUpdateTimer;

  @override
  void initState() {
    super.initState();
    
    // Breathing animation - continuous, slow
    _breathController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    )..repeat(reverse: true);
    
    _breathAnimation = Tween<double>(begin: -1, end: 1).animate(
      CurvedAnimation(parent: _breathController, curve: Curves.easeInOut),
    );
    
    // Blink animation - triggered periodically
    _blinkController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 150),
    );
    
    _blinkAnimation = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0, end: 1), weight: 1),
      TweenSequenceItem(tween: Tween(begin: 1, end: 0), weight: 1),
    ]).animate(_blinkController);
    
    // Schedule random blinks
    _scheduleNextBlink();
    
    // Update expression engine periodically
    _expressionUpdateTimer = Timer.periodic(const Duration(milliseconds: 16), (_) {
      _expressionEngine.update();
      if (mounted) setState(() {});
    });
  }

  void _scheduleNextBlink() {
    final delay = Duration(milliseconds: 2000 + math.Random().nextInt(4000));
    _blinkTimer = Timer(delay, () {
      if (mounted) {
        _blinkController.forward(from: 0).then((_) {
          _scheduleNextBlink();
        });
      }
    });
  }

  @override
  void didUpdateWidget(LittleNateAvatar oldWidget) {
    super.didUpdateWidget(oldWidget);
    
    // Update expression when visual state changes
    if (oldWidget.visualState.expression != widget.visualState.expression) {
      _expressionEngine.transitionTo(widget.visualState.expression);
    }
  }

  @override
  void dispose() {
    _breathController.dispose();
    _blinkController.dispose();
    _blinkTimer?.cancel();
    _expressionUpdateTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      child: Stack(
        children: [
          // Background environment
          Positioned.fill(
            child: EnvironmentRenderer.buildBackground(
              widget.visualState.environment,
              widget.visualState.lighting,
            ),
          ),
          
          // Voice state indicator
          if (widget.voiceState != VoiceState.idle)
            Positioned(
              top: 40,
              left: 0,
              right: 0,
              child: _buildVoiceStateIndicator(),
            ),
          
          // Avatar face
          Center(
            child: AnimatedBuilder(
              animation: Listenable.merge([_breathAnimation, _blinkAnimation]),
              builder: (context, child) {
                return CustomPaint(
                  size: const Size(300, 350),
                  painter: AvatarFacePainter(
                    expressionEngine: _expressionEngine,
                    appearance: widget.appearance,
                    blinkValue: _blinkAnimation.value,
                    breathValue: _breathAnimation.value,
                    mouthOpenness: widget.mouthOpenness,
                  ),
                );
              },
            ),
          ),
          
          // Gesture overlay
          if (widget.visualState.gesture != AvatarGesture.none)
            _buildGestureOverlay(),
        ],
      ),
    );
  }

  Widget _buildVoiceStateIndicator() {
    IconData icon;
    String label;
    Color color;
    
    switch (widget.voiceState) {
      case VoiceState.listening:
        icon = Icons.mic;
        label = 'Listening...';
        color = const Color(0xFF4ECDC4);
        break;
      case VoiceState.thinking:
        icon = Icons.psychology;
        label = 'Thinking...';
        color = const Color(0xFFFFD700);
        break;
      case VoiceState.speaking:
        icon = Icons.volume_up;
        label = 'Speaking';
        color = const Color(0xFF9D4EDD);
        break;
      default:
        return const SizedBox.shrink();
    }
    
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      margin: const EdgeInsets.symmetric(horizontal: 50),
      decoration: BoxDecoration(
        color: Colors.black54,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 8),
          Text(label, style: TextStyle(color: color, fontSize: 14)),
        ],
      ),
    );
  }

  Widget _buildGestureOverlay() {
    String gestureText;
    
    switch (widget.visualState.gesture) {
      case AvatarGesture.handOnHeart:
        gestureText = '🤲';
        break;
      case AvatarGesture.thumbsUp:
        gestureText = '👍';
        break;
      case AvatarGesture.handsTogether:
        gestureText = '🙏';
        break;
      case AvatarGesture.wave:
        gestureText = '👋';
        break;
      default:
        return const SizedBox.shrink();
    }
    
    return Positioned(
      bottom: 100,
      right: 50,
      child: TweenAnimationBuilder<double>(
        tween: Tween(begin: 0, end: 1),
        duration: const Duration(milliseconds: 300),
        builder: (context, value, child) {
          return Opacity(
            opacity: value,
            child: Transform.scale(
              scale: 0.5 + value * 0.5,
              child: Text(
                gestureText,
                style: const TextStyle(fontSize: 60),
              ),
            ),
          );
        },
      ),
    );
  }
}

// =============================================================================
// AVATAR MODE SCREEN
// =============================================================================

/// Full-screen avatar experience with voice pipeline
class AvatarModeScreen extends StatefulWidget {
  final Map<String, dynamic> userProfile;
  final Function(Map<String, dynamic>) onSendMessage;

  const AvatarModeScreen({
    super.key,
    required this.userProfile,
    required this.onSendMessage,
  });

  @override
  State<AvatarModeScreen> createState() => _AvatarModeScreenState();
}

class _AvatarModeScreenState extends State<AvatarModeScreen> {
  final AzureTTSService _tts = AzureTTSService();
  final AzureSTTService _stt = AzureSTTService();
  
  VoiceState _voiceState = VoiceState.idle;
  AvatarVisualState _visualState = const AvatarVisualState();
  AvatarAppearanceConfig _appearance = const AvatarAppearanceConfig();
  double _mouthOpenness = 0.0;
  String _currentTranscript = '';
  
  Timer? _mouthAnimationTimer;

  @override
  void initState() {
    super.initState();
    _initializeServices();
    _loadAvatarConfig();
  }

  Future<void> _initializeServices() async {
    await _stt.initialize();
    
    // Listen for transcriptions
    _stt.partialTranscriptions.listen((text) {
      setState(() => _currentTranscript = text);
    });
    
    _stt.finalTranscriptions.listen((text) {
      _handleUserSpeech(text);
    });
  }

  void _loadAvatarConfig() {
    // Request config from server
    widget.onSendMessage({'type': 'fetch_avatar_config'});
  }

  void _handleUserSpeech(String text) async {
    if (text.trim().isEmpty) return;
    
    setState(() {
      _voiceState = VoiceState.thinking;
      _visualState = _visualState.copyWith(expression: AvatarExpression.thoughtful);
    });
    
    // Send to server
    widget.onSendMessage({
      'type': 'avatar_user_speech',
      'text': text,
    });
  }

  void handleServerResponse(Map<String, dynamic> response) async {
    final type = response['type'];
    
    if (type == 'avatar_response') {
      final speechData = response['speech'] as Map<String, dynamic>?;
      final avatarState = response['avatar_state'] as Map<String, dynamic>?;
      
      if (avatarState != null) {
        setState(() {
          _visualState = AvatarVisualState.fromJson(avatarState);
        });
      }
      
      if (speechData != null) {
        final text = speechData['text'] as String? ?? '';
        await _speakResponse(text);
      }
    } else if (type == 'avatar_config') {
      final config = response['config'] as Map<String, dynamic>?;
      if (config != null) {
        final appearanceData = config['appearance'] as Map<String, dynamic>?;
        if (appearanceData != null) {
          setState(() {
            _appearance = AvatarAppearanceConfig.fromJson(appearanceData);
          });
        }
      }
    } else if (type == 'avatar_state_update') {
      setState(() {
        _visualState = AvatarVisualState.fromJson(response);
      });
    }
  }

  Future<void> _speakResponse(String text) async {
    setState(() => _voiceState = VoiceState.speaking);
    
    // Start mouth animation
    _startMouthAnimation();
    
    // Synthesize and play speech
    final audioBytes = await _tts.synthesizeSpeech(text, _visualState.expression);
    if (audioBytes != null) {
      await _tts.playAudio(audioBytes);
    }
    
    // Wait for audio to complete
    await Future.delayed(Duration(milliseconds: text.split(' ').length * 300));
    
    _stopMouthAnimation();
    setState(() {
      _voiceState = VoiceState.idle;
      _visualState = _visualState.copyWith(expression: AvatarExpression.warm);
    });
  }

  void _startMouthAnimation() {
    _mouthAnimationTimer = Timer.periodic(const Duration(milliseconds: 50), (_) {
      setState(() {
        _mouthOpenness = 0.3 + math.Random().nextDouble() * 0.4;
      });
    });
  }

  void _stopMouthAnimation() {
    _mouthAnimationTimer?.cancel();
    setState(() => _mouthOpenness = 0.0);
  }

  void _toggleListening() async {
    if (_voiceState == VoiceState.listening) {
      await _stt.stopListening();
      setState(() => _voiceState = VoiceState.idle);
    } else if (_voiceState == VoiceState.idle) {
      setState(() {
        _voiceState = VoiceState.listening;
        _visualState = _visualState.copyWith(expression: AvatarExpression.attentive);
      });
      await _stt.startListening();
    }
  }

  @override
  void dispose() {
    _tts.dispose();
    _stt.dispose();
    _mouthAnimationTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(
          children: [
            // Avatar
            LittleNateAvatar(
              appearance: _appearance,
              visualState: _visualState,
              voiceState: _voiceState,
              mouthOpenness: _mouthOpenness,
            ),
            
            // Transcript display
            if (_currentTranscript.isNotEmpty && _voiceState == VoiceState.listening)
              Positioned(
                bottom: 150,
                left: 20,
                right: 20,
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    _currentTranscript,
                    style: const TextStyle(color: Colors.white, fontSize: 16),
                    textAlign: TextAlign.center,
                  ),
                ),
              ),
            
            // Controls
            Positioned(
              bottom: 40,
              left: 0,
              right: 0,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  // Back button
                  IconButton(
                    icon: const Icon(Icons.arrow_back, color: Colors.white54),
                    onPressed: () => Navigator.pop(context),
                  ),
                  
                  const SizedBox(width: 40),
                  
                  // Mic button
                  GestureDetector(
                    onTap: _voiceState == VoiceState.speaking ? null : _toggleListening,
                    child: Container(
                      width: 80,
                      height: 80,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: _voiceState == VoiceState.listening
                            ? const Color(0xFF4ECDC4)
                            : _voiceState == VoiceState.speaking
                                ? Colors.grey
                                : const Color(0xFFFFD700),
                        boxShadow: [
                          BoxShadow(
                            color: (_voiceState == VoiceState.listening
                                    ? const Color(0xFF4ECDC4)
                                    : const Color(0xFFFFD700))
                                .withOpacity(0.3),
                            blurRadius: 20,
                            spreadRadius: 5,
                          ),
                        ],
                      ),
                      child: Icon(
                        _voiceState == VoiceState.listening ? Icons.stop : Icons.mic,
                        color: Colors.black,
                        size: 36,
                      ),
                    ),
                  ),
                  
                  const SizedBox(width: 40),
                  
                  // Settings button
                  IconButton(
                    icon: const Icon(Icons.settings, color: Colors.white54),
                    onPressed: () {
                      // Open avatar settings
                    },
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// =============================================================================
// TIER ELIGIBILITY CHECK
// =============================================================================

/// Check if user is eligible for avatar mode
bool canUseAvatarMode(Map<String, dynamic> userProfile) {
  final tier = (userProfile['tier'] ?? '').toString().toUpperCase();
  final familyId = userProfile['family_id'];
  
  // Top tier users
  if (tier == 'TOP_TIER' || tier == 'SOVEREIGN_CIRCLE') {
    return true;
  }
  
  // Family members under a top tier account
  if (familyId != null && familyId.toString().isNotEmpty) {
    return true;
  }
  
  return false;
}

// =============================================================================
// GLB 3D AVATAR WIDGET
// =============================================================================

/// Canonical avatar mesh (2026-07-29 lil_nate kit). Single Y-up textured GLB.
/// Expression sync still drives AvatarExpression / server avatar_state; visual
/// morph targets land after Blender shape keys (eyeBlink, jawOpen, mouthSmile_*,
/// browInnerUp) are baked — until then all logical states share this mesh.
const String _glbLilNate = 'lil_nate.glb';

/// Maps server avatar_state strings (SCREAMING_SNAKE) to client enum.
AvatarExpression avatarExpressionFromServer(String? raw) {
  switch ((raw ?? '').trim().toUpperCase()) {
    case 'ATTENTIVE':
      return AvatarExpression.attentive;
    case 'THOUGHTFUL':
      return AvatarExpression.thoughtful;
    case 'WARM':
      return AvatarExpression.warm;
    case 'EMPATHETIC':
      return AvatarExpression.empathetic;
    case 'CALMING':
      return AvatarExpression.calming;
    case 'VALIDATING':
      return AvatarExpression.validating;
    case 'CURIOUS':
      return AvatarExpression.curious;
    case 'ENCOURAGING':
      return AvatarExpression.encouraging;
    case 'PROUD':
      return AvatarExpression.proud;
    case 'SAD':
      return AvatarExpression.sad;
    case 'FRUSTRATED':
      return AvatarExpression.frustrated;
    case 'NEUTRAL':
    default:
      return AvatarExpression.neutral;
  }
}

/// Lowercase wire name shared with Spline postMessage contract.
String avatarExpressionWireName(AvatarExpression e) =>
    e.toString().split('.').last.toLowerCase();

/// All expressions → lil_nate.glb until morph-target export lands.
const Map<AvatarExpression, String> _expressionToGlb = {
  AvatarExpression.neutral:     _glbLilNate,
  AvatarExpression.attentive:   _glbLilNate,
  AvatarExpression.thoughtful:  _glbLilNate,
  AvatarExpression.warm:        _glbLilNate,
  AvatarExpression.empathetic:  _glbLilNate,
  AvatarExpression.calming:     _glbLilNate,
  AvatarExpression.validating:  _glbLilNate,
  AvatarExpression.curious:     _glbLilNate,
  AvatarExpression.encouraging: _glbLilNate,
  AvatarExpression.proud:       _glbLilNate,
  AvatarExpression.sad:         _glbLilNate,
  AvatarExpression.frustrated:  _glbLilNate,
};

/// 3D GLB avatar that renders the current expression model.
/// Uses a single ModelViewer keyed by the current GLB URL so the widget
/// rebuilds cleanly when the expression changes.
class GlbAvatarWidget extends StatefulWidget {
  final AvatarExpression expression;
  final VoiceState voiceState;
  final VoidCallback? onTap;

  const GlbAvatarWidget({
    super.key,
    this.expression = AvatarExpression.neutral,
    this.voiceState = VoiceState.idle,
    this.onTap,
  });

  @override
  State<GlbAvatarWidget> createState() => _GlbAvatarWidgetState();
}

enum _GlbLoadPhase { loading, assumedLoaded, failed }

class _GlbAvatarWidgetState extends State<GlbAvatarWidget> {
  _GlbLoadPhase _phase = _GlbLoadPhase.loading;

  // Bottom layer: the expression currently fully on-screen.
  String _baseGlb = '';
  int _loadAttempt = 0;

  // Top layer: the next expression cross-fading in over the base. Null
  // when no transition is in flight. Morph-target blending on the GLB
  // itself isn't possible yet (see tools/avatar_morph_pipeline —
  // production exports aren't vertex-compatible), so this cross-fade is
  // the smoothest transition achievable without new 3D assets: it
  // replaces the old hard "spinner flash" cut with a 450ms dissolve.
  String? _incomingGlb;
  double _incomingOpacity = 0.0;
  int _crossfadeAttempt = 0;
  Timer? _revealTimer;
  Timer? _promoteTimer;

  static const _assumeLoadedAfter = Duration(seconds: 12);
  static const _failAfter = Duration(seconds: 30);

  /// Head start given to the incoming model-viewer to parse/render its
  /// first frame before it starts fading in, so the dissolve doesn't
  /// reveal a blank canvas.
  static const _crossfadeRevealDelay = Duration(milliseconds: 180);
  /// Fade tempo -- matches TRANSITION_MS in the morph-target viewer
  /// (tools/avatar_morph_pipeline/expression_viewer.html) so motion feels
  /// consistent once true blending ships.
  static const _crossfadeDuration = Duration(milliseconds: 450);

  @override
  void initState() {
    super.initState();
    _baseGlb = _glbForExpression(widget.expression);
    _beginLoadCycle();
  }

  @override
  void didUpdateWidget(GlbAvatarWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.expression != widget.expression) {
      final newGlb = _glbForExpression(widget.expression);
      if (newGlb != _baseGlb && newGlb != _incomingGlb) {
        _startCrossfadeTo(newGlb);
      }
    }
  }

  @override
  void dispose() {
    _revealTimer?.cancel();
    _promoteTimer?.cancel();
    super.dispose();
  }

  void _beginLoadCycle() {
    final attempt = ++_loadAttempt;
    Future.delayed(_assumeLoadedAfter, () {
      if (mounted && attempt == _loadAttempt && _phase == _GlbLoadPhase.loading) {
        setState(() => _phase = _GlbLoadPhase.assumedLoaded);
      }
    });
    Future.delayed(_failAfter, () {
      if (mounted && attempt == _loadAttempt && _phase == _GlbLoadPhase.loading) {
        setState(() => _phase = _GlbLoadPhase.failed);
      }
    });
  }

  /// Transitions to [glb] with a cross-fade instead of remounting the
  /// base layer directly. The incoming model loads behind the current
  /// one, gets a brief head start to render, then dissolves in. Once the
  /// fade completes it's promoted to the base layer so a rapid run of
  /// expression changes never stacks up extra layers.
  void _startCrossfadeTo(String glb) {
    _revealTimer?.cancel();
    _promoteTimer?.cancel();
    final attempt = ++_crossfadeAttempt;
    setState(() {
      _incomingGlb = glb;
      _incomingOpacity = 0.0;
    });
    _revealTimer = Timer(_crossfadeRevealDelay, () {
      if (!mounted || attempt != _crossfadeAttempt) return;
      setState(() => _incomingOpacity = 1.0);
    });
    _promoteTimer = Timer(_crossfadeRevealDelay + _crossfadeDuration, () {
      if (!mounted || attempt != _crossfadeAttempt) return;
      setState(() {
        _baseGlb = glb;
        _incomingGlb = null;
        _incomingOpacity = 0.0;
      });
    });
    // Keep the loading/failed safety net alive if the base itself hasn't
    // finished its very first load yet.
    if (_phase != _GlbLoadPhase.assumedLoaded) {
      _beginLoadCycle();
    }
  }

  void _retry() {
    setState(() => _phase = _GlbLoadPhase.loading);
    _beginLoadCycle();
  }

  String _glbForExpression(AvatarExpression expr) {
    return _expressionToGlb[expr] ?? _glbLilNate;
  }

  Widget _modelLayer(String glb, Key key) {
    final src = '${AppConfig.avatarGlbBaseUrl}/$glb';
    return ModelViewer(
      key: key,
      src: src,
      backgroundColor: const Color(0xFF050505),
      autoRotate: false,
      cameraControls: true,
      disableZoom: true,
      autoPlay: true,
      loading: Loading.eager,
      // lil_nate ~1.53m Y-up; frame upper torso / face
      cameraOrbit: '0deg 85deg 3.2m',
      cameraTarget: '0m 1.05m 0m',
      fieldOfView: '30deg',
      exposure: 1.05,
      interactionPrompt: InteractionPrompt.none,
    );
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      child: Stack(
        children: [
          Positioned.fill(
            child: Container(color: const Color(0xFF050505)),
          ),
          Positioned.fill(
            child: _modelLayer(
              _baseGlb,
              ValueKey('glb-base#$_baseGlb#$_loadAttempt'),
            ),
          ),
          if (_incomingGlb != null)
            Positioned.fill(
              child: AnimatedOpacity(
                opacity: _incomingOpacity,
                duration: _crossfadeDuration,
                curve: Curves.easeInOut,
                child: _modelLayer(
                  _incomingGlb!,
                  ValueKey('glb-incoming#$_incomingGlb#$_crossfadeAttempt'),
                ),
              ),
            ),
          if (_phase == _GlbLoadPhase.loading && _incomingGlb == null)
            Positioned.fill(
              child: Container(
                color: const Color(0xFF050505),
                child: const Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      CircularProgressIndicator(
                        valueColor: AlwaysStoppedAnimation(Color(0xFFC9A962)),
                        strokeWidth: 2,
                      ),
                      SizedBox(height: 16),
                      Text(
                        'Little Nate is on his way...',
                        style: TextStyle(
                          color: Color(0xFFC9A962),
                          fontSize: 14,
                          fontFamily: 'DM Sans',
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          if (_phase == _GlbLoadPhase.failed)
            Positioned.fill(
              child: Container(
                color: const Color(0xFF050505),
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.cloud_off,
                          color: Color(0xFFC9A962), size: 40),
                      SizedBox(height: 12),
                      Text(
                        "Little Nate couldn't load right now.",
                        style: TextStyle(
                          color: Color(0xFFC9A962),
                          fontSize: 14,
                          fontFamily: 'DM Sans',
                        ),
                      ),
                      SizedBox(height: 16),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          OutlinedButton(
                            onPressed: _retry,
                            style: OutlinedButton.styleFrom(
                              foregroundColor: Color(0xFFC9A962),
                              side: BorderSide(color: Color(0xFFC9A962)),
                            ),
                            child: Text('Try Again'),
                          ),
                          SizedBox(width: 12),
                          TextButton(
                            onPressed: widget.onTap,
                            style: TextButton.styleFrom(
                              foregroundColor: Colors.grey,
                            ),
                            child: Text('Back to Orb'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
          if (widget.voiceState != VoiceState.idle)
            Positioned(
              top: 40,
              left: 0,
              right: 0,
              child: _buildVoiceIndicator(),
            ),
        ],
      ),
    );
  }

  Widget _buildVoiceIndicator() {
    IconData icon;
    String label;
    Color color;

    switch (widget.voiceState) {
      case VoiceState.listening:
        icon = Icons.mic;
        label = 'Listening...';
        color = const Color(0xFF4ECDC4);
        break;
      case VoiceState.thinking:
        icon = Icons.psychology;
        label = 'Thinking...';
        color = const Color(0xFFFFD700);
        break;
      case VoiceState.speaking:
        icon = Icons.volume_up;
        label = 'Speaking';
        color = const Color(0xFF9D4EDD);
        break;
      default:
        return const SizedBox.shrink();
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
      margin: const EdgeInsets.symmetric(horizontal: 50),
      decoration: BoxDecoration(
        color: Colors.black54,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 8),
          Text(label, style: TextStyle(color: color, fontSize: 14)),
        ],
      ),
    );
  }
}

// =============================================================================
// ANIMATED BUILDER HELPER
// =============================================================================

/// Helper widget for combining multiple animations
class AnimatedBuilder extends StatelessWidget {
  final Listenable animation;
  final Widget Function(BuildContext, Widget?) builder;
  final Widget? child;

  const AnimatedBuilder({
    super.key,
    required this.animation,
    required this.builder,
    this.child,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder2(
      listenable: animation,
      builder: builder,
      child: child,
    );
  }
}

class AnimatedBuilder2 extends AnimatedWidget {
  final Widget Function(BuildContext, Widget?) builder;
  final Widget? child;

  const AnimatedBuilder2({
    super.key,
    required super.listenable,
    required this.builder,
    this.child,
  }) : super();

  Listenable get animation => listenable;

  @override
  Widget build(BuildContext context) {
    return builder(context, child);
  }
}
