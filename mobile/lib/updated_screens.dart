import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/foundation.dart'
    show kDebugMode, kIsWeb, debugPrint, VoidCallback;
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:speech_to_text/speech_to_text.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:pointer_interceptor/pointer_interceptor.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:io' show File;
import 'metrics_widgets.dart';

// Conditional import for web iframe support
import 'dojo_iframe_stub.dart' if (dart.library.html) 'dojo_iframe_web.dart';
import 'dojo_parent_message_stub.dart'
    if (dart.library.html) 'dojo_parent_message_web.dart';

import 'shared_widgets.dart';
import 'widgets/calendar_views.dart';
import 'widgets/conversation_log_view.dart';
import 'services/nevedal_flutter.dart';
import 'services/large_video_upload.dart';
import 'main.dart'
    show
        defaultWsUrl,
        defaultApiBaseUrl,
        LobbyScreen,
        FamilySanctuaryScreen,
        ClientScheduleScreen,
        isNativeIOS,
        ClientWsHub;
import 'debug_logger.dart';
import 'avatar.dart' hide AnimatedBuilder;
import 'screens/settings_screen.dart';
import 'screens/billing_screens.dart';
import 'screens/payment_confirmation_screen.dart';
import 'services/export_service.dart';
import 'screens/coaching_mesh_screen.dart';
import 'screens/onboarding_paid_screen.dart';
import 'screens/community_mesh_screen.dart';
import 'screens/sensitive_clinical_profile_screen.dart';
import 'screens/intake_form_coach_panel.dart';
import 'config/app_config.dart';
import 'services/vault_entitlement.dart';
import 'widgets/vault_attachment_button.dart';
import 'widgets/upload_progress_indicator.dart';

/// Debug-only print: suppressed in production builds.
// ignore: avoid_print
void _debugLog(Object? message) {
  if (kDebugMode) print(message);
}

// =============================================================================
// LITTLE NATE - UPDATED SCREENS WITH METRICS
// Version: 2.0 | January 23, 2026
// =============================================================================

// Add this import at the top of main.dart:
// import 'metrics_widgets.dart';

// =============================================================================
// ONBOARDING TUTORIAL SCREEN - Avatar-narrated walkthrough
// =============================================================================

class OnboardingTutorialScreen extends StatefulWidget {
  final String role; // "CLIENT" or "COACH"
  final Map<String, dynamic> userData;
  final String wsUrl;

  const OnboardingTutorialScreen({
    super.key,
    required this.role,
    required this.userData,
    this.wsUrl = "wss://api.sovereignsanctuary.net/ws",
  });

  @override
  State<OnboardingTutorialScreen> createState() =>
      _OnboardingTutorialScreenState();
}

class _OnboardingTutorialScreenState extends State<OnboardingTutorialScreen>
    with TickerProviderStateMixin {
  final PageController _pageController = PageController();
  final NateVoice _nateVoice = NateVoice();
  bool _isSpeaking = false;
  bool _hasStarted = false; // Gate for browser autoplay policy
  bool _socketReady = false; // True once WebSocket auth is confirmed
  int _currentPage = 0;
  Timer? _speakTimer; // Cancellable timer for delayed speech start
  late AnimationController _breatheController;
  late AnimationController _pulseController;
  WebSocketChannel? _socket;
  StreamSubscription? _socketSub;

  // --- Step definitions ---
  static const List<Map<String, String>> _clientSteps = [
    {
      "title": "Welcome to the Sanctuary",
      "icon": "shield",
      "speech":
          "Hey there! I'm Little Nate, your AI companion in the Sovereign Sanctuary. Let me show you around so you know what's possible here. Click next to continue.",
      "description":
          "I'm your personal AI companion — always here, always listening, always growing with you.",
      "expression": "warm",
    },
    {
      "title": "Chat With Me",
      "icon": "chat",
      "speech":
          "You can talk to me anytime about anything on your mind. I'm here to listen, reflect, and help you grow. Just type or tap the mic.",
      "description":
          "Text or voice — share what's on your mind. I'll listen, reflect, and offer insights tailored to you.",
      "expression": "attentive",
    },
    {
      "title": "Voice Mode",
      "icon": "mic",
      "speech":
          "Don't feel like typing? Just tap the mic and talk to me. I'll listen and respond with my voice too. It's like having a conversation with a friend.",
      "description":
          "Tap the microphone to speak naturally. I'll respond with my voice — like a real conversation.",
      "expression": "curious",
    },
    {
      "title": "Your Metrics",
      "icon": "metrics",
      "speech":
          "I track your emotional patterns over time. Mood, coherence, engagement. You'll see your growth mapped out beautifully.",
      "description":
          "Track your emotional coherence, mood trends, engagement scores, and breakthroughs over time.",
      "expression": "proud",
    },
    {
      "title": "Avatar Mode",
      "icon": "avatar",
      "speech":
          "At the Sovereign Circle tier, I come alive as a 3D avatar. You'll see my expressions change as we talk. It makes our connection feel even more real.",
      "description":
          "In Sovereign Circle, I become a 3D avatar with real-time expressions that respond to our conversation.",
      "expression": "empathetic",
    },
    {
      "title": "Family Sanctuary",
      "icon": "family",
      "speech":
          "Bring your whole family into the Sanctuary. Group sessions, private coaching, real-time wellness tracking for everyone you love.",
      "description":
          "Group sessions, private coaching, and wellness tracking for your whole family — spouse and dependents included.",
      "expression": "warm",
    },
    {
      "title": "Your Journey Awaits",
      "icon": "pricing",
      "speech":
          "Here's what each tier offers. Start with Threshold to explore, upgrade to Inner Chamber for unlimited access, or go all in with Sovereign Circle for the full experience. Let's begin this journey together.",
      "description": "",
      "expression": "proud",
    },
  ];

  static const List<Map<String, String>> _coachSteps = [
    {
      "title": "Welcome, Coach",
      "icon": "shield",
      "speech":
          "Welcome to Coach Command. I'm Little Nate — your AI co-pilot for every session. Let me show you what we've built for you. Click next to continue.",
      "description":
          "I'm your AI co-pilot. I observe sessions, prepare briefings, and help you serve your clients better.",
      "expression": "warm",
    },
    {
      "title": "Your Clients",
      "icon": "clients",
      "speech":
          "See all your clients at a glance. Tiers, session history, family groups — everything in one place. You'll never feel unprepared.",
      "description":
          "View all clients with their tiers, session history, family groups, and quick actions — all in one dashboard.",
      "expression": "attentive",
    },
    {
      "title": "Scheduling",
      "icon": "calendar",
      "speech":
          "Manage your calendar, set availability, and connect via Zoom or FaceTime — all built in. Your clients book right from the app.",
      "description":
          "Set availability, manage bookings, and launch Zoom or FaceTime sessions — all integrated seamlessly.",
      "expression": "neutral",
    },
    {
      "title": "Insights & Briefings",
      "icon": "insights",
      "speech":
          "Before each session, I'll prepare a briefing with client history, mood trends, and topics to address. You'll walk in fully prepared.",
      "description":
          "Pre-session briefings with client history, mood analysis, risk flags, and suggested talking points.",
      "expression": "curious",
    },
    {
      "title": "The DOJO",
      "icon": "dojo",
      "speech":
          "The DOJO is your training ground. This is where you sharpen your mentoring skills through real-world simulations. I'll challenge you with tough client scenarios, push your techniques, and give you honest feedback so you grow with every session. Think of it as a sparring partner that never holds back.",
      "description":
          "Adversarial simulation training that sharpens your mentoring and coaching skills through realistic scenarios and real-time AI feedback.",
      "expression": "proud",
    },
    {
      "title": "DOJO Tools",
      "icon": "tools",
      "speech":
          "Generate PDF assessments, run secure internet searches, upload case documents, and export session logs — all from the DOJO sidebar. Judge DOJO coaches can also request courtroom debates and access LexisNexis case law search.",
      "description":
          "PDF assessments, secure internet search, case document upload, LexisNexis integration, courtroom debates, session export, and real-time performance metrics.",
      "expression": "attentive",
    },
    {
      "title": "Classroom",
      "icon": "classroom",
      "speech":
          "After sessions, upload recordings and I'll analyze them. Insights, transcripts, coaching suggestions — I help you improve with every session.",
      "description":
          "Upload session recordings for AI-powered analysis — transcripts, insights, and coaching feedback.",
      "expression": "empathetic",
    },
    {
      "title": "Client Pricing Overview",
      "icon": "pricing",
      "speech":
          "Here's what your clients see. There's also a Coach Only option for clients who just need scheduling with you — no AI access included. Understanding the tiers helps you guide them to the right plan for their needs.",
      "description": "",
      "expression": "warm",
    },
    {
      "title": "Your Fees & Earnings",
      "icon": "fees",
      "speech":
          "Let's talk business. When a client books with you, the platform takes a 30 percent fee with a 30 dollar minimum per session. You set your own rate and track everything in your Financials tab. You're a 1099 independent contractor — we collected your W-9 at signup and will issue a 1099 at year-end if you earn over 600 dollars. One important note: all clients must accept our Sovereign Covenant consent form before they can book with you. This protects both you and the platform. Let's begin this journey together.",
      "description": "",
      "expression": "attentive",
    },
  ];

  List<Map<String, String>> get _steps =>
      widget.role == "COACH" ? _coachSteps : _clientSteps;

  @override
  void initState() {
    super.initState();
    _breatheController =
        AnimationController(vsync: this, duration: const Duration(seconds: 3))
          ..repeat(reverse: true);
    _pulseController = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 1500))
      ..repeat(reverse: true);
    _initNateVoice();
    _connectSocket();
    // NOTE: Do NOT auto-speak here. Browsers block audio until a user gesture.
    // Speech starts when user taps "Begin Tour" (see _beginTour).
  }

  void _connectSocket() {
    try {
      _socket = WebSocketChannel.connect(Uri.parse(widget.wsUrl));
      // Auth with existing token
      final token = widget.userData["token"];
      if (token != null) {
        _socket!.sink.add(json.encode({
          "type": "auth",
          "token": token,
          "hardware_id": widget.userData["hardware_id"] ?? ""
        }));
      }
      // FIX-H: NOT ClientWsHub — tour uses a dedicated short-lived WS + `auth` (not lobby
      // login_request). Hub is client main-context only; double-listen on one channel N/A here.
      _socketSub = _socket!.stream.listen((message) {
        try {
          final data = json.decode(message);
          final type = data['type'];
          if (type == 'nate_audio_delta') {
            _nateVoice.handleAudioDelta(data['payload'],
                format: data['format'] ?? 'pcm',
                requestId: data['request_id'] ?? '');
          } else if (type == 'tts_done') {
            _nateVoice.handleTtsDone(requestId: data['request_id'] ?? '');
          } else if (type == 'connected' ||
              type == 'auth_success' ||
              type == 'login_success') {
            if (mounted) setState(() => _socketReady = true);
            debugPrint("[Onboarding] WebSocket authenticated");
          }
        } catch (e) {
          debugPrint("[Onboarding] Message parse error: $e");
        }
      }, onError: (e) {
        debugPrint("[Onboarding] WebSocket error: $e");
      });
    } catch (e) {
      debugPrint("[Onboarding] WebSocket connect error: $e");
    }
  }

  void _initNateVoice() {
    _nateVoice.onStart = () {
      if (mounted) setState(() => _isSpeaking = true);
    };
    _nateVoice.onDone = () {
      if (mounted) setState(() => _isSpeaking = false);
    };
  }

  /// Called by the "Begin Tour" button — this tap satisfies the browser's
  /// autoplay policy (initializes Web Audio API AudioContext with user gesture).
  Future<void> _beginTour() async {
    // Initialize Web Audio API player (must happen during user gesture for autoplay)
    _nateVoice.initialize();
    if (mounted) setState(() => _hasStarted = true);
    // Small delay so the UI transitions, then speak the first step
    await Future.delayed(const Duration(milliseconds: 400));
    if (mounted) _speakStep(0);
  }

  void _speakStep(int index) {
    if (index >= _steps.length) return;
    // Cancel any previously scheduled speech to prevent overlap/cut-off
    _speakTimer?.cancel();
    _nateVoice.stop(); // Stop any current speech
    final speech = _steps[index]["speech"] ?? "";
    if (speech.isNotEmpty && _socket != null && _socketReady) {
      // Buffer delay: let the audio pipeline fully flush and give the user
      // a beat to absorb the new page before Nate starts speaking.
      _speakTimer = Timer(const Duration(milliseconds: 600), () {
        if (mounted && _socket != null && _socketReady) {
          _nateVoice.speak(speech, _socket!);
        }
      });
    } else if (speech.isNotEmpty && !_socketReady) {
      debugPrint(
          "[Onboarding] Socket not ready, skipping speech for step $index");
    }
  }

  /// Restore the default onDone handler after a navigation-override completes.
  void _resetOnDone() {
    _nateVoice.onDone = () {
      if (mounted) setState(() => _isSpeaking = false);
    };
  }

  void _nextPage() {
    if (_isSpeaking) {
      // Wait for Nate to finish speaking before advancing
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text("Waiting for Nate to finish..."),
            duration: Duration(seconds: 2)),
      );
      _nateVoice.onDone = () {
        if (mounted) {
          setState(() => _isSpeaking = false);
          _resetOnDone(); // Restore default handler
          _advancePage();
        }
      };
      // Safety timeout in case onDone never fires (30 seconds)
      Future.delayed(const Duration(seconds: 30), () {
        if (mounted && _isSpeaking) {
          _nateVoice.stop();
          setState(() => _isSpeaking = false);
          _resetOnDone();
          _advancePage();
        }
      });
    } else {
      _advancePage();
    }
  }

  void _advancePage() {
    if (_currentPage < _steps.length - 1) {
      _pageController.nextPage(
          duration: const Duration(milliseconds: 400), curve: Curves.easeInOut);
    } else {
      _completeOnboarding();
    }
  }

  void _prevPage() {
    if (_currentPage > 0) {
      if (_isSpeaking) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Waiting for Nate to finish..."),
              duration: Duration(seconds: 2)),
        );
        _nateVoice.onDone = () {
          if (mounted) {
            setState(() => _isSpeaking = false);
            _resetOnDone(); // Restore default handler
            _pageController.previousPage(
                duration: const Duration(milliseconds: 400),
                curve: Curves.easeInOut);
          }
        };
        Future.delayed(const Duration(seconds: 30), () {
          if (mounted && _isSpeaking) {
            _nateVoice.stop();
            setState(() => _isSpeaking = false);
            _resetOnDone();
            _pageController.previousPage(
                duration: const Duration(milliseconds: 400),
                curve: Curves.easeInOut);
          }
        });
      } else {
        _pageController.previousPage(
            duration: const Duration(milliseconds: 400),
            curve: Curves.easeInOut);
      }
    }
  }

  void _completeOnboarding() {
    // Send completion to backend
    try {
      _socket?.sink.add(json.encode({"type": "mark_onboarding_complete"}));
    } catch (e) {
      debugPrint("[Onboarding] Error sending completion: $e");
    }
    // Navigate to the appropriate screen (userData already has token from OnboardingTutorialScreen ctor)
    final role = widget.role;
    final profile = widget.userData;
    final username = (profile["username"] ?? "").toString();
    final password = (profile["password"] ?? "").toString();
    if (role == "ADMIN") {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
            builder: (_) => AdminDashboardScreen(
                currentUserProfile: profile,
                username: username,
                password: password)),
        (route) => false,
      );
    } else if (role == "COACH") {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
            builder: (_) => CoachDashboardScreenV2(
                currentUserProfile: profile,
                username: username,
                password: password)),
        (route) => false,
      );
    } else {
      // CLIENT
      final plan =
          (profile["subscription_plan"] ?? "").toString().toUpperCase();
      final canAccessNate = profile["can_access_nate"] ?? true;
      if (plan == "COACH_ONLY" || canAccessNate == false) {
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(
              builder: (_) => ClientScheduleScreen(
                  currentUserProfile: profile,
                  username: username,
                  password: password)),
          (route) => false,
        );
      } else {
        Navigator.of(context).pushAndRemoveUntil(
          MaterialPageRoute(
              builder: (_) => NeuralInterfaceV2(
                  currentUserProfile: profile,
                  username: username,
                  password: password)),
          (route) => false,
        );
      }
    }
  }

  IconData _iconForStep(String icon) {
    switch (icon) {
      case "shield":
        return Icons.shield_outlined;
      case "chat":
        return Icons.chat_bubble_outline;
      case "mic":
        return Icons.mic_none;
      case "metrics":
        return Icons.show_chart;
      case "avatar":
        return Icons.face_retouching_natural;
      case "family":
        return Icons.family_restroom;
      case "pricing":
        return Icons.diamond_outlined;
      case "clients":
        return Icons.people_outline;
      case "calendar":
        return Icons.calendar_month_outlined;
      case "insights":
        return Icons.psychology_outlined;
      case "dojo":
        return Icons.sports_martial_arts;
      case "tools":
        return Icons.build_outlined;
      case "classroom":
        return Icons.school_outlined;
      default:
        return Icons.star_outline;
    }
  }

  @override
  void dispose() {
    _speakTimer?.cancel();
    _nateVoice.dispose();
    _socketSub?.cancel();
    _breatheController.dispose();
    _pulseController.dispose();
    _pageController.dispose();
    _socket?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final steps = _steps;
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0F),
      body: SafeArea(
        child: _hasStarted ? _buildTourContent(steps) : _buildWelcomeGate(),
      ),
    );
  }

  /// Welcome gate — requires a tap to unlock browser audio before tour starts.
  Widget _buildWelcomeGate() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Nate's orb (breathing)
          AnimatedBuilder(
            animation: _breatheController,
            builder: (context, _) {
              final s = 1.0 + (_breatheController.value * 0.04);
              return Transform.scale(
                scale: s,
                child: Container(
                  width: 140,
                  height: 140,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: const RadialGradient(
                        colors: [Color(0xFF001A33), Color(0xFF000000)]),
                    border: Border.all(
                        color: const Color(0xFF4ECDC4).withOpacity(0.6),
                        width: 2.5),
                    boxShadow: [
                      BoxShadow(
                          color: const Color(0xFF4ECDC4).withOpacity(0.2),
                          blurRadius: 25,
                          spreadRadius: 5)
                    ],
                  ),
                  child: Center(
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _buildEye(),
                        const SizedBox(width: 12),
                        _buildEye()
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
          const SizedBox(height: 24),
          const Text("LITTLE NATE",
              style: TextStyle(
                  fontFamily: 'Courier',
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFFFD700),
                  letterSpacing: 3)),
          const SizedBox(height: 8),
          Text(
            widget.role == "COACH"
                ? "Welcome, Coach"
                : "Welcome to the Sanctuary",
            style: const TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.bold,
                color: Colors.white,
                letterSpacing: 1),
          ),
          const SizedBox(height: 12),
          Text(
            _socketReady
                ? "I'd like to show you around.\nTap below to begin — I'll narrate the tour."
                : "Connecting to the Sanctuary...",
            textAlign: TextAlign.center,
            style: const TextStyle(
                fontSize: 14, color: Colors.white60, height: 1.5),
          ),
          const SizedBox(height: 36),
          ElevatedButton.icon(
            onPressed: _beginTour,
            icon: const Icon(Icons.volume_up, size: 20),
            label: const Text("BEGIN TOUR",
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    letterSpacing: 2,
                    fontSize: 14)),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF4ECDC4),
              foregroundColor: Colors.black,
              padding: const EdgeInsets.symmetric(horizontal: 36, vertical: 16),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(30)),
            ),
          ),
          const SizedBox(height: 16),
          TextButton(
            onPressed: () {
              setState(() => _hasStarted = true);
              // Skip audio, just show the tour silently
            },
            child: const Text("Skip audio",
                style: TextStyle(color: Colors.white38, fontSize: 12)),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _completeOnboarding,
            child: const Text("Skip tutorial entirely",
                style: TextStyle(
                    color: Colors.white24,
                    fontSize: 12,
                    decoration: TextDecoration.underline)),
          ),
        ],
      ),
    );
  }

  Widget _buildTourContent(List<Map<String, String>> steps) {
    return Column(
      children: [
        // --- Avatar section (~30%) ---
        Expanded(
          flex: 3,
          child: _buildAvatarSection(),
        ),
        // --- Feature card section (~50%) ---
        Expanded(
          flex: 5,
          child: PageView.builder(
            controller: _pageController,
            // Disable swiping entirely — navigation is button-driven only
            // (Next / Back / Let's Begin) to ensure Nate finishes speaking
            physics: const NeverScrollableScrollPhysics(),
            itemCount: steps.length,
            onPageChanged: (index) {
              setState(() => _currentPage = index);
              _speakStep(index);
            },
            itemBuilder: (context, index) {
              final step = steps[index];
              if (step["icon"] == "pricing") {
                return _buildPricingCard();
              }
              if (step["icon"] == "fees") {
                return _buildFeesCard();
              }
              return _buildFeatureCard(step);
            },
          ),
        ),
        // --- Navigation section (~20%) ---
        _buildNavigation(steps.length),
      ],
    );
  }

  Widget _buildAvatarSection() {
    return AnimatedBuilder(
      animation: _breatheController,
      builder: (context, child) {
        final breathScale = 1.0 + (_breatheController.value * 0.03);
        return Center(
          child: Transform.scale(
            scale: breathScale,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Nate avatar orb
                Container(
                  width: 120,
                  height: 120,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: const RadialGradient(
                      colors: [Color(0xFF001A33), Color(0xFF000000)],
                    ),
                    border: Border.all(
                      color: _isSpeaking
                          ? const Color(0xFF4ECDC4)
                          : const Color(0xFF4ECDC4).withOpacity(0.5),
                      width: _isSpeaking ? 3 : 2,
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: const Color(0xFF4ECDC4)
                            .withOpacity(_isSpeaking ? 0.4 : 0.15),
                        blurRadius: _isSpeaking ? 30 : 15,
                        spreadRadius: _isSpeaking ? 8 : 2,
                      ),
                    ],
                  ),
                  child: Center(
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        _buildEye(),
                        const SizedBox(width: 12),
                        _buildEye(),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                AnimatedDefaultTextStyle(
                  duration: const Duration(milliseconds: 300),
                  style: TextStyle(
                    fontFamily: 'Courier',
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                    color: _isSpeaking
                        ? const Color(0xFF4ECDC4)
                        : const Color(0xFFFFD700),
                    letterSpacing: 2,
                  ),
                  child:
                      Text(_isSpeaking ? "NATE IS SPEAKING..." : "LITTLE NATE"),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildEye() {
    return AnimatedBuilder(
      animation: _pulseController,
      builder: (context, _) {
        final glow = 0.6 + (_pulseController.value * 0.4);
        return Container(
          width: 14,
          height: 14,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: Color.fromRGBO(78, 205, 196, glow),
            boxShadow: [
              BoxShadow(
                color: const Color(0xFF4ECDC4).withOpacity(glow * 0.6),
                blurRadius: 8,
                spreadRadius: 2,
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildFeatureCard(Map<String, String> step) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 8),
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: const Color(0xFF252525)),
          boxShadow: [
            BoxShadow(
              color: const Color(0xFF9D4EDD).withOpacity(0.08),
              blurRadius: 20,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Icon
              Container(
                width: 64,
                height: 64,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: const Color(0xFF9D4EDD).withOpacity(0.15),
                  border: Border.all(
                      color: const Color(0xFF9D4EDD).withOpacity(0.4)),
                ),
                child: Icon(
                  _iconForStep(step["icon"] ?? ""),
                  color: const Color(0xFF9D4EDD),
                  size: 30,
                ),
              ),
              const SizedBox(height: 20),
              // Title
              Text(
                step["title"] ?? "",
                style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFFFD700),
                  letterSpacing: 1,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              // Description
              Text(
                step["description"] ?? "",
                style: const TextStyle(
                  fontSize: 15,
                  color: Color(0xFF888888),
                  height: 1.6,
                ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildPricingCard() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: SingleChildScrollView(
        child: Column(
          children: [
            const Text(
              "Choose Your Path",
              style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFFFD700),
                  letterSpacing: 1),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            // Threshold
            _buildTierCard(
              name: "THRESHOLD",
              subtitle: "Trial",
              price: "Free",
              priceSub: "7 days",
              color: const Color(0xFF888888),
              features: [
                "Limited AI conversations",
                "Basic mood tracking",
                "Explore the Sanctuary"
              ],
            ),
            const SizedBox(height: 10),
            // Inner Chamber
            _buildTierCard(
              name: "INNER CHAMBER",
              subtitle: "Standard",
              price: "\$49",
              priceSub: "per month",
              color: const Color(0xFFFFD700),
              features: [
                "Unlimited AI conversations",
                "Voice mode",
                "Full emotional metrics",
                "Progress tracking"
              ],
            ),
            const SizedBox(height: 10),
            // Sovereign Circle
            _buildTierCard(
              name: "SOVEREIGN CIRCLE",
              subtitle: "Premium",
              price: "\$149",
              priceSub: "per month",
              color: const Color(0xFF9D4EDD),
              features: [
                "Everything in Inner Chamber",
                "3D Avatar Mode",
                "Family Sanctuary (spouse + 1 included)",
                "Live coaching sessions",
                "Additional family: +\$75/mo each",
              ],
              highlighted: true,
            ),
            const SizedBox(height: 10),
            // Live Coaching add-on
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF252525)),
              ),
              child: Column(
                children: [
                  const Text("LIVE COACHING ADD-ON",
                      style: TextStyle(
                          fontSize: 10,
                          color: Color(0xFF4ECDC4),
                          fontWeight: FontWeight.bold,
                          letterSpacing: 2)),
                  const SizedBox(height: 8),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                      _buildPriceChip("1 Session", "\$175"),
                      _buildPriceChip("4-Pack", "\$600"),
                      _buildPriceChip("8-Pack", "\$1,120"),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 10),
            // Coach Only
            _buildTierCard(
              name: "COACH ONLY",
              subtitle: "Scheduling Only",
              price: "Free",
              priceSub: "no AI access",
              color: const Color(0xFF4ECDC4),
              features: [
                "Scheduling with your coach",
                "No AI conversations",
                "No mood tracking or metrics",
                "Coach manages sessions directly",
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFeesCard() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: SingleChildScrollView(
        child: Column(
          children: [
            const Text(
              "Your Fees & Earnings",
              style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                  color: Color(0xFFFFD700),
                  letterSpacing: 1),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),

            // Platform Fee
            _buildFeeInfoCard(
              icon: Icons.account_balance,
              iconColor: const Color(0xFFFFD700),
              title: "PLATFORM FEE",
              children: [
                const Text("30% of your session fee",
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 14,
                        fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
                Text("Minimum \$30 per approved session",
                    style: TextStyle(color: Colors.grey[400], fontSize: 12)),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.white.withOpacity(0.05),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.white10),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text("EXAMPLE BREAKDOWN",
                          style: TextStyle(
                              color: Colors.grey[500],
                              fontSize: 10,
                              letterSpacing: 1,
                              fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      _buildFeeRow("Your rate", "\$150/hr", Colors.white),
                      _buildFeeRow(
                          "Platform fee (30%)", "- \$45.00", Colors.red[300]!),
                      const Divider(color: Colors.white12, height: 16),
                      _buildFeeRow(
                          "You keep", "\$105.00", const Color(0xFF00F5D4)),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),

            // Payment Modes
            _buildFeeInfoCard(
              icon: Icons.payment,
              iconColor: const Color(0xFF4ECDC4),
              title: "PAYMENT MODES",
              children: [
                _buildPaymentMode(
                  "Coach Handles",
                  "You collect payment from your client directly. The platform invoices you for the platform fee.",
                  Icons.person,
                ),
                const SizedBox(height: 8),
                _buildPaymentMode(
                  "Platform Handles",
                  "The platform collects from the client and pays you net (after platform fee).",
                  Icons.store,
                ),
              ],
            ),
            const SizedBox(height: 10),

            // 1099 Status
            _buildFeeInfoCard(
              icon: Icons.description,
              iconColor: const Color(0xFF9D4EDD),
              title: "1099 CONTRACTOR STATUS",
              children: [
                Text("You are an independent contractor (1099-NEC).",
                    style: TextStyle(
                        color: Colors.grey[300], fontSize: 13, height: 1.4)),
                const SizedBox(height: 8),
                _buildCheckItem("W-9 collected at registration"),
                _buildCheckItem(
                    "1099-NEC issued if earnings exceed \$600/year"),
                _buildCheckItem(
                    "Track all tax documents in your Financials tab"),
              ],
            ),
            const SizedBox(height: 10),

            // Client Consent Requirement
            _buildFeeInfoCard(
              icon: Icons.verified_user,
              iconColor: Colors.blueAccent,
              title: "CLIENT CONSENT REQUIRED",
              children: [
                Text(
                  "All clients must accept the Sovereign Covenant consent form before they can book coaching sessions through this platform.",
                  style: TextStyle(
                      color: Colors.grey[300], fontSize: 13, height: 1.4),
                ),
                const SizedBox(height: 8),
                _buildCheckItem("AI disclosure & biometric consent"),
                _buildCheckItem("Hold harmless waiver"),
                _buildCheckItem("Binding arbitration agreement"),
                _buildCheckItem("Platform immunity acknowledgment"),
                const SizedBox(height: 8),
                Text(
                  "This protects both you and the platform legally.",
                  style: TextStyle(
                      color: const Color(0xFFFFD700).withOpacity(0.8),
                      fontSize: 12,
                      fontStyle: FontStyle.italic),
                ),
              ],
            ),
            const SizedBox(height: 10),

            // Financials Tab note
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                borderRadius: BorderRadius.circular(12),
                border:
                    Border.all(color: const Color(0xFFFFD700).withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.analytics,
                      color: Color(0xFFFFD700), size: 24),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text("FINANCIALS TAB",
                            style: TextStyle(
                                color: Color(0xFFFFD700),
                                fontSize: 11,
                                fontWeight: FontWeight.bold,
                                letterSpacing: 1)),
                        const SizedBox(height: 4),
                        Text(
                            "Track earnings, fees, transactions, and tax documents all in one place.",
                            style: TextStyle(
                                color: Colors.grey[400], fontSize: 12)),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFeeInfoCard(
      {required IconData icon,
      required Color iconColor,
      required String title,
      required List<Widget> children}) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF252525)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: iconColor, size: 18),
              const SizedBox(width: 8),
              Text(title,
                  style: TextStyle(
                      fontSize: 10,
                      color: iconColor,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 2)),
            ],
          ),
          const SizedBox(height: 10),
          ...children,
        ],
      ),
    );
  }

  Widget _buildFeeRow(String label, String value, Color valueColor) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: Colors.grey[400], fontSize: 12)),
          Text(value,
              style: TextStyle(
                  color: valueColor,
                  fontSize: 13,
                  fontWeight: FontWeight.bold,
                  fontFamily: 'Courier')),
        ],
      ),
    );
  }

  Widget _buildPaymentMode(String title, String desc, IconData icon) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: const Color(0xFF4ECDC4), size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 13,
                        fontWeight: FontWeight.w600)),
                const SizedBox(height: 2),
                Text(desc,
                    style: TextStyle(
                        color: Colors.grey[500], fontSize: 11, height: 1.3)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCheckItem(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.check_circle, color: Color(0xFF00F5D4), size: 14),
          const SizedBox(width: 8),
          Expanded(
              child: Text(text,
                  style: TextStyle(color: Colors.grey[400], fontSize: 12))),
        ],
      ),
    );
  }

  Widget _buildTierCard({
    required String name,
    required String subtitle,
    required String price,
    required String priceSub,
    required Color color,
    required List<String> features,
    bool highlighted = false,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: highlighted ? color.withOpacity(0.08) : const Color(0xFF111111),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
            color:
                highlighted ? color.withOpacity(0.5) : const Color(0xFF252525),
            width: highlighted ? 2 : 1),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Price column
          SizedBox(
            width: 70,
            child: Column(
              children: [
                Text(price,
                    style: TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.bold,
                        color: color)),
                Text(priceSub,
                    style:
                        const TextStyle(fontSize: 9, color: Color(0xFF888888))),
                const SizedBox(height: 4),
                Text(subtitle,
                    style: TextStyle(
                        fontSize: 8,
                        color: color.withOpacity(0.7),
                        fontWeight: FontWeight.w600,
                        letterSpacing: 1)),
              ],
            ),
          ),
          const SizedBox(width: 12),
          // Features column
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name,
                    style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        color: color,
                        letterSpacing: 1)),
                const SizedBox(height: 6),
                ...features.map((f) => Padding(
                      padding: const EdgeInsets.only(bottom: 3),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text("+ ",
                              style: TextStyle(
                                  color: color,
                                  fontSize: 11,
                                  fontWeight: FontWeight.bold)),
                          Expanded(
                              child: Text(f,
                                  style: const TextStyle(
                                      color: Color(0xFFCCCCCC),
                                      fontSize: 11,
                                      height: 1.3))),
                        ],
                      ),
                    )),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPriceChip(String label, String price) {
    return Column(
      children: [
        Text(price,
            style: const TextStyle(
                color: Color(0xFF4ECDC4),
                fontSize: 14,
                fontWeight: FontWeight.bold)),
        Text(label,
            style: const TextStyle(color: Color(0xFF888888), fontSize: 9)),
      ],
    );
  }

  Widget _buildNavigation(int totalSteps) {
    final isLast = _currentPage == totalSteps - 1;
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 12, 24, 20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Progress dots
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: List.generate(
                totalSteps,
                (i) => AnimatedContainer(
                      duration: const Duration(milliseconds: 300),
                      margin: const EdgeInsets.symmetric(horizontal: 3),
                      width: i == _currentPage ? 24 : 8,
                      height: 8,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(4),
                        color: i == _currentPage
                            ? const Color(0xFF9D4EDD)
                            : const Color(0xFF252525),
                      ),
                    )),
          ),
          const SizedBox(height: 16),
          // Skip tutorial link (always visible during tour)
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: () {
                _nateVoice.stop();
                _speakTimer?.cancel();
                _completeOnboarding();
              },
              child: const Text("Skip tutorial",
                  style: TextStyle(
                      color: Colors.white30,
                      fontSize: 12,
                      decoration: TextDecoration.underline)),
            ),
          ),
          const SizedBox(height: 4),
          // Step counter + buttons
          Row(
            children: [
              // Back button
              if (_currentPage > 0)
                GestureDetector(
                  onTap: _prevPage,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 20, vertical: 14),
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFF252525)),
                    ),
                    child: const Text("Back",
                        style:
                            TextStyle(color: Color(0xFF888888), fontSize: 14)),
                  ),
                )
              else
                const SizedBox(width: 80),
              const Spacer(),
              // Step counter
              Text(
                "${_currentPage + 1} / $totalSteps",
                style: const TextStyle(
                    color: Color(0xFF888888),
                    fontSize: 12,
                    fontFamily: 'Courier'),
              ),
              const Spacer(),
              // Next / Begin button
              GestureDetector(
                onTap: _nextPage,
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 28, vertical: 14),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    gradient: LinearGradient(
                      colors: isLast
                          ? [const Color(0xFF9D4EDD), const Color(0xFF6B2FA0)]
                          : [const Color(0xFFFFD700), const Color(0xFFCC9900)],
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: (isLast
                                ? const Color(0xFF9D4EDD)
                                : const Color(0xFFFFD700))
                            .withOpacity(0.3),
                        blurRadius: 12,
                        offset: const Offset(0, 4),
                      ),
                    ],
                  ),
                  child: Text(
                    isLast ? "Let's Begin!" : "Next",
                    style: TextStyle(
                      color: isLast ? Colors.white : Colors.black,
                      fontSize: 15,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// UPDATED NEURAL INTERFACE - Client chat with metrics access
// Replace the existing NeuralInterface class with this one
// =============================================================================

class NeuralInterfaceV2 extends StatefulWidget {
  final Map<String, dynamic>? currentUserProfile;
  final String? username;
  final String? password;

  const NeuralInterfaceV2(
      {super.key, this.currentUserProfile, this.username, this.password});

  @override
  State<NeuralInterfaceV2> createState() => _NeuralInterfaceV2State();
}

class _VocabEntry {
  final String canonical;
  final List<String> aliases;

  const _VocabEntry({required this.canonical, required this.aliases});

  Map<String, dynamic> toJson() => {
        'canonical': canonical,
        'aliases': aliases,
      };

  static _VocabEntry? tryFromJson(dynamic v) {
    if (v is! Map) return null;
    final m = Map<String, dynamic>.from(v as Map);
    final c = (m['canonical'] ?? '').toString().trim();
    if (c.isEmpty) return null;
    final aRaw = m['aliases'];
    final a = (aRaw is List)
        ? aRaw
            .map((e) => e.toString())
            .where((s) => s.trim().isNotEmpty)
            .map((s) => s.trim())
            .toList()
        : <String>[];
    return _VocabEntry(canonical: c, aliases: a);
  }
}

class _NeuralInterfaceV2State extends State<NeuralInterfaceV2>
    with WidgetsBindingObserver {
  final VagusEngine _audio = VagusEngine();
  final _dbg = getDebugLogger();

  WebSocketChannel? _socket;
  StreamSubscription<dynamic>? _socketSub;
  StreamSubscription<Object>? _socketErrSub;
  StreamSubscription<void>? _socketDoneSub;
  String get _serverUrl => defaultWsUrl;
  StreamSubscription<String>? _audioSub;
  Timer? _talkingTimer;
  Timer? _reconnectTimer;
  int _reconnectAttempts = 0;

  bool _restartScheduled = false;

  /// Merged on return from Settings (timezone PATCH / health-check sync).
  final Map<String, dynamic> _profilePatchOverrides = {};

  Map<String, dynamic> _clientProfile() {
    final base = Map<String, dynamic>.from(widget.currentUserProfile ?? {});
    base.addAll(_profilePatchOverrides);
    return base;
  }

  final List<String> _chatHistory = [];
  static const int _kMaxTurnBubbleMap = 200;
  final Map<String, int> _turnIdToChatIndex = {};
  final Map<String, String> _latestNateTextByTurnForTts = {};
  final Map<String, Timer> _ttsDebounceByTurn = {};

  void _pruneTurnBubbleMapIfNeeded() {
    while (_turnIdToChatIndex.length > _kMaxTurnBubbleMap) {
      final k = _turnIdToChatIndex.keys.first;
      _turnIdToChatIndex.remove(k);
    }
  }

  /// One TTS invocation per logical `turn_id`; uses latest accumulated text after stream settles.
  void _scheduleTtsOncePerTurn(
      String? turnId, String reply, bool voiceDefault) {
    if (!voiceDefault || reply.trim().isEmpty || !mounted) return;
    final tid = turnId?.trim() ?? '';
    if (tid.isEmpty) {
      _speakNateMessage(reply);
      return;
    }
    _latestNateTextByTurnForTts[tid] = reply;
    _ttsDebounceByTurn[tid]?.cancel();
    _ttsDebounceByTurn[tid] = Timer(const Duration(milliseconds: 420), () {
      _ttsDebounceByTurn.remove(tid);
      if (!mounted) return;
      final latest = _latestNateTextByTurnForTts.remove(tid);
      if (latest != null && latest.trim().isNotEmpty) {
        _speakNateMessage(latest);
      }
    });
  }

  final TextEditingController _chatController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final SpeechToText _speech = SpeechToText();
  bool _isTalking = false;
  bool _isListening = false;
  bool _speechAvailable = false;
  DateTime? _suppressSpeechUntil;
  bool _dictationArmed = false; // mic mode (auto-restart on pauses)
  String _dictationBaseText = ''; // text before current listen session
  String _dictationSessionText = ''; // rolling transcript for current session
  DateTime? _voiceCommandCooldownUntil;
  int? _selectionStart;
  int? _selectionEnd;
  bool _isTextSelected = false;
  final List<_VocabEntry> _customVocab = [];
  final FlutterTts _tts = FlutterTts();
  bool _isSpeaking = false;
  bool _ttsUnlocked = false;
  String _connectionStatus = "Initializing...";

  // NEW: Metrics data
  Map<String, dynamic> _metrics = {};
  List<dynamic> _moodHistory = [];

  // Avatar Mode state (Top Tier / Sovereign Circle only)
  bool _avatarModeEnabled = false;
  AvatarVisualState _avatarState = AvatarVisualState();
  AvatarAppearanceConfig _avatarAppearance = AvatarAppearanceConfig();
  VoiceState _voiceState = VoiceState.idle;
  double _mouthOpenness = 0.0;

  // ── Nate Nudge state ──
  List<Map<String, dynamic>> _pendingNudges = [];
  bool _nudgeBannerDismissed = false;

  // ── AI Modes state ──
  String? _activeAiMode; // 'tri_corder', 'archivist', 'guardian', 'supervisor'
  Map<String, dynamic>? _aiModeOutput;

  // ── Sovereign Vault upload progress ──
  UploadProgressState _uploadProgressState = UploadProgressState.idle();

  // ── SSE Story Journey ──
  bool _sseIntakePending = false;
  Map<String, dynamic>? _recapData;
  bool _recapDismissed = false;
  Timer? _recapTimer;
  final Set<int> _dismissedSuggestions = {};

  // Nevedal biometric integration
  final NevedalService _nevedal = NevedalService();

  // AI data-sharing consent (Apple 5.1.1(i) / 5.1.2(i))
  bool _aiDataConsentGiven = false;
  static const _aiConsentKey = 'ai_data_consent_v1';

  Future<void> _loadAiConsent() async {
    try {
      const storage = FlutterSecureStorage();
      final stored = await storage.read(key: _aiConsentKey);
      if (stored == 'true' && mounted)
        setState(() => _aiDataConsentGiven = true);
    } catch (_) {}
  }

  Future<void> _showAiDataConsentDialog() async {
    final agreed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => Dialog(
        backgroundColor: const Color(0xFF111111),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: Container(
          constraints: const BoxConstraints(maxWidth: 420),
          padding: const EdgeInsets.all(24),
          child: SingleChildScrollView(
              child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Center(
                  child: Icon(Icons.shield_outlined,
                      color: Color(0xFFC9A962), size: 40)),
              const SizedBox(height: 12),
              const Center(
                  child: Text("AI Data Processing Consent",
                      style: TextStyle(
                          color: Color(0xFFC9A962),
                          fontSize: 18,
                          fontWeight: FontWeight.bold))),
              const SizedBox(height: 16),
              const Text(
                  "Before you start chatting with Little Nate, please review how your data is processed:",
                  style: TextStyle(color: Colors.white70, fontSize: 14)),
              const SizedBox(height: 16),
              _consentBullet(Icons.chat_bubble_outline, "Your Messages",
                  "Text messages and voice transcriptions are sent to Microsoft Azure OpenAI to generate Little Nate's responses."),
              _consentBullet(Icons.mic_outlined, "Voice Biometrics",
                  "Voice features (pitch, energy, speech rate, pause ratio) are analyzed locally and sent to our secure server for emotional coherence scoring."),
              _consentBullet(Icons.lock_outline, "Data Protection",
                  "All data is encrypted in transit (TLS 1.2+) and at rest (AES-256). Microsoft Azure operates under enterprise data protection agreements — your data is NOT used to train their AI models."),
              _consentBullet(Icons.delete_outline, "Your Rights",
                  "You can delete your data at any time via Settings > Data Deletion. See our Privacy Policy for full details."),
              const SizedBox(height: 8),
              const Divider(color: Colors.white24),
              const SizedBox(height: 8),
              RichText(
                  text: const TextSpan(
                      style: TextStyle(color: Colors.white60, fontSize: 12),
                      children: [
                    TextSpan(text: "Third-party AI provider: "),
                    TextSpan(
                        text: "Microsoft Azure OpenAI Service",
                        style: TextStyle(
                            color: Color(0xFFC9A962),
                            fontWeight: FontWeight.w600)),
                  ])),
              const SizedBox(height: 4),
              const Text(
                  "Full details in our Privacy Policy (Settings > Legal & Privacy).",
                  style: TextStyle(color: Colors.white38, fontSize: 11)),
              const SizedBox(height: 20),
              Row(children: [
                Expanded(
                    child: OutlinedButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: Colors.white24),
                      padding: const EdgeInsets.symmetric(vertical: 14)),
                  child: const Text("Decline",
                      style: TextStyle(color: Colors.white54)),
                )),
                const SizedBox(width: 12),
                Expanded(
                    child: ElevatedButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFC9A962),
                      padding: const EdgeInsets.symmetric(vertical: 14)),
                  child: const Text("I Understand & Consent",
                      style: TextStyle(
                          color: Colors.black,
                          fontWeight: FontWeight.bold,
                          fontSize: 13)),
                )),
              ]),
            ],
          )),
        ),
      ),
    );
    if (agreed == true) {
      setState(() => _aiDataConsentGiven = true);
      try {
        const storage = FlutterSecureStorage();
        await storage.write(key: _aiConsentKey, value: 'true');
      } catch (_) {}
    }
  }

  static Widget _consentBullet(IconData icon, String title, String body) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: const Color(0xFF4ECDC4), size: 20),
        const SizedBox(width: 10),
        Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title,
              style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w600,
                  fontSize: 13)),
          const SizedBox(height: 2),
          Text(body,
              style: const TextStyle(
                  color: Colors.white60, fontSize: 12.5, height: 1.4)),
        ])),
      ]),
    );
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadAiConsent();
    _connectToCortex();
    _initSpeechToText();
    _loadCustomVocabulary();
    _initTts();
    _chatController.addListener(_onDraftChanged);
    _fetchRecap();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      if (_wsCh != null) _wsSend(jsonEncode({"type": "get_profile"})); // FIX-H
      if (PaymentConfirmationScreen.pendingCheckout && mounted) {
        PaymentConfirmationScreen.pendingCheckout = false;
        Navigator.push(
            context,
            MaterialPageRoute(
                builder: (_) => PaymentConfirmationScreen(
                      profile: widget.currentUserProfile ?? {},
                      checkoutType:
                          PaymentConfirmationScreen.pendingCheckoutType,
                    )));
      }
    }
  }

  void _onDraftChanged() {
    // Keep base text in sync with manual edits.
    if (!_isListening) {
      _dictationBaseText = _chatController.text;
      // #region agent log
      _dbgLog('H3', 'draft_changed_manual', {
        'len': _chatController.text.length,
        'dictationArmed': _dictationArmed,
        'isListening': _isListening,
      });
      // #endregion
      if (mounted) setState(() {});
    }
    // Selection becomes stale whenever the draft changes.
    _clearSelection();
  }

  void _dbgLog(String hypothesisId, String message, Map<String, dynamic> data) {
    // #region agent log
    _dbg.log({
      'sessionId': 'debug-session',
      'runId': 'run1',
      'hypothesisId': hypothesisId,
      'location': 'updated_screens.dart:_NeuralInterfaceV2State',
      'message': message,
      'data': data,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
    });
    // #endregion
  }

  WebSocketChannel? get _wsCh => ClientWsHub.channel ?? _socket; // FIX-H
  void _wsSend(String payload) => _wsCh?.sink.add(payload); // FIX-H
  bool _nevedalReady = false;
  DateTime? _lastConnectAttempt;
  Timer? _backoffResetTimer;
  void _cancelNeuralWsSubs() {
    _socketSub?.cancel();
    _socketSub = null;
    _socketErrSub?.cancel();
    _socketErrSub = null;
    _socketDoneSub?.cancel();
    _socketDoneSub = null;
  }

  String get _clientContext => kIsWeb ? 'client_web' : 'client_mobile';

  void _initNevedalOnce(WebSocketChannel sock, String sessionId) {
    if (_nevedalReady) return;
    _nevedalReady = true;
    _nevedal.initialize(
      socket: sock,
      sessionId: sessionId,
      userId: widget.username ?? 'unknown',
    );
  }

  void _scheduleBackoffDecay() {
    _backoffResetTimer?.cancel();
    _backoffResetTimer = Timer(const Duration(seconds: 30), () {
      _reconnectAttempts = 0;
    });
  }

  void _applyHubWarmStart() {
    _scheduleBackoffDecay();
    if (mounted) setState(() => _connectionStatus = "ONLINE (SECURE)");
    _addSystemMsg("Neural Link Established.");
    _updateMetricsFromProfile(widget.currentUserProfile ?? {});
    _requestMetrics();
    _wsSend(jsonEncode({"type": "get_pending_nudges"}));
    _checkSseIntake();
    _initNevedalOnce(
      ClientWsHub.channel!,
      'session_${DateTime.now().millisecondsSinceEpoch}',
    );
  }

  void _connectToCortex() {
    final now = DateTime.now();
    if (_lastConnectAttempt != null &&
        now.difference(_lastConnectAttempt!).inSeconds < 3) {
      return;
    }
    _lastConnectAttempt = now;
    setState(() => _connectionStatus = "Dialing Neural Core...");
    _cancelNeuralWsSubs();
    if (ClientWsHub.channel != null) {
      try {
        _socket?.sink.close();
      } catch (_) {}
      _socket = null;
      _socketSub = ClientWsHub.inbound.listen(_handleSocketMessage);
      _socketErrSub = ClientWsHub.errors.listen((e) {
        _debugLog("Neural socket error: $e");
        if (mounted)
          setState(() =>
              _connectionStatus = "Connection interrupted. Reconnecting...");
        _scheduleReconnect();
      });
      _socketDoneSub = ClientWsHub.done.listen((_) {
        _nevedalReady = false;
        if (mounted) setState(() => _connectionStatus = "Reconnecting...");
        _scheduleReconnect();
      });
      _applyHubWarmStart();
    } else {
      try {
        _socket?.sink.close();
      } catch (_) {}
      _socket = null;
      try {
        _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));
        ClientWsHub.attach(_socket!);
        _socketSub = ClientWsHub.inbound.listen(_handleSocketMessage);
        _socketErrSub = ClientWsHub.errors.listen((e) {
          _debugLog("Neural socket error: $e");
          if (mounted)
            setState(() =>
                _connectionStatus = "Connection interrupted. Reconnecting...");
          _scheduleReconnect();
        });
        _socketDoneSub = ClientWsHub.done.listen((_) {
          _nevedalReady = false;
          if (mounted) setState(() => _connectionStatus = "Reconnecting...");
          _scheduleReconnect();
        });
        if (kDebugMode) print(">>> NEURAL INTERFACE: Sending Login...");
        _socket!.sink.add(jsonEncode({
          "type": "login_request",
          "username": widget.username,
          "password": widget.password,
          "expected_role": "CLIENT",
          "client_context": _clientContext,
        }));
      } catch (e) {
        _debugLog("Connection error: $e");
        _scheduleReconnect();
      }
    }

    _audioSub?.cancel();
    _audioSub = _audio.onTranscription.listen((text) {
      if (_dictationArmed || _isListening) return;
      if (mounted) setState(() => _chatController.text = text);
    });
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _backoffResetTimer?.cancel();
    final attempt = _reconnectAttempts.clamp(0, 10);
    final baseMs = (5000 * (1 << attempt)).clamp(5000, 30000);
    final jitterMs =
        (baseMs * 0.2 * (DateTime.now().millisecondsSinceEpoch % 100) / 100)
            .toInt();
    _reconnectAttempts = (_reconnectAttempts + 1).clamp(0, 10);
    _reconnectTimer = Timer(Duration(milliseconds: baseMs + jitterMs), () {
      if (!mounted) return;
      if (_connectionStatus.contains("ONLINE")) return;
      _connectToCortex();
    });
  }

  void _handleSocketMessage(dynamic message) {
    try {
      final data = jsonDecode(message);
      if (kDebugMode) print(">>> CORTEX SAYS: $data");

      if (data['type'] == 'login_success') {
        _scheduleBackoffDecay();
        setState(() => _connectionStatus = "ONLINE (SECURE)");
        _addSystemMsg("Neural Link Established.");

        final profile = data['profile'] ?? {};
        _updateMetricsFromProfile(profile);
        _requestMetrics();
        _wsSend(jsonEncode({"type": "get_pending_nudges"}));
        _checkSseIntake();

        final sk = ClientWsHub.channel ?? _socket;
        if (sk != null) {
          final sessionId = data['session_id'] as String? ??
              'session_${DateTime.now().millisecondsSinceEpoch}';
          _initNevedalOnce(sk, sessionId);
        }
      } else if (data['type'] == 'nate_thinking') {
        final thinking = data['text'] ?? 'Little Nate is thinking...';
        final turnId = data['turn_id'] as String?;
        setState(() {
          final prefix = "Little Nate: ";
          final line = "$prefix$thinking";
          if (turnId != null && turnId.trim().isNotEmpty) {
            final tid = turnId.trim();
            final existing = _turnIdToChatIndex[tid];
            if (existing != null &&
                existing >= 0 &&
                existing < _chatHistory.length) {
              _chatHistory[existing] = line;
            } else {
              _chatHistory.add(line);
              _turnIdToChatIndex[tid] = _chatHistory.length - 1;
              _pruneTurnBubbleMapIfNeeded();
            }
          } else {
            if (_chatHistory.isNotEmpty &&
                _chatHistory.last.startsWith("Little Nate:")) {
              _chatHistory[_chatHistory.length - 1] = line;
            } else {
              _chatHistory.add(line);
            }
          }
          _scrollToBottom();
        });
      } else if (data['type'] == 'nate_response' ||
          data['type'] == 'chat_reply') {
        String reply = data['text'] ?? "";
        final turnId = data['turn_id'] as String?;
        setState(() {
          final prefix = "Little Nate: ";
          final line = "$prefix$reply";
          if (turnId != null && turnId.trim().isNotEmpty) {
            final tid = turnId.trim();
            final existing = _turnIdToChatIndex[tid];
            if (existing != null &&
                existing >= 0 &&
                existing < _chatHistory.length) {
              _chatHistory[existing] = line;
            } else {
              _chatHistory.add(line);
              _turnIdToChatIndex[tid] = _chatHistory.length - 1;
              _pruneTurnBubbleMapIfNeeded();
            }
          } else {
            if (_chatHistory.isNotEmpty &&
                _chatHistory.last.startsWith("Little Nate:")) {
              _chatHistory[_chatHistory.length - 1] = line;
            } else {
              _chatHistory.add(line);
            }
          }
          _scrollToBottom();
        });

        // Auto-speak if voice mode default is enabled
        final voiceDefault =
            widget.currentUserProfile?['voice_mode_default'] == true ||
                widget.currentUserProfile?['notification_prefs']
                        ?['voice_mode_default'] ==
                    true;
        if (voiceDefault && reply.trim().isNotEmpty && mounted) {
          _scheduleTtsOncePerTurn(turnId, reply, true);
        }

        // Update avatar expression based on AI response mood/sentiment
        if (_avatarModeEnabled && _canUseAvatarMode()) {
          final sentiment =
              data['sentiment'] ?? data['mood'] ?? _metrics['mood_current'];
          _updateAvatarFromSentiment(sentiment, reply);
        }
      } else if (data['type'] == 'offer_coach_handoff') {
        final coachName = (data['coach_name'] as String?)?.trim().isNotEmpty == true
            ? data['coach_name'] as String
            : 'your coach';
        final handoffTurnId = (data['turn_id'] as String?)?.trim();
        if (mounted) {
          setState(() {
            _chatHistory.add('System: [Reach out to $coachName]');
            _scrollToBottom();
          });
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Want to bring $coachName into this?',
                style: const TextStyle(color: Colors.white)),
            backgroundColor: const Color(0xFF1A1A2E),
            duration: const Duration(seconds: 8),
            action: SnackBarAction(
              label: 'Reach out',
              textColor: const Color(0xFFC9A962),
              onPressed: () {
                if (handoffTurnId != null && handoffTurnId.isNotEmpty) {
                  _wsSend(jsonEncode({
                    'type': 'coach_handoff_accepted',
                    'turn_id': handoffTurnId,
                  }));
                }
              },
            ),
          ));
        }
      } else if (data['type'] == 'search_consent_request') {
        final query = data['query'] ?? '';
        if (query.isNotEmpty && mounted) {
          showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF1A1A2E),
              title: const Text('Web Search Request',
                  style: TextStyle(
                      color: Color(0xFFC9A962),
                      fontFamily: 'Cormorant Garamond')),
              content: Text(
                'Nate would like to search the web for:\n\n"$query"\n\nAllow this search?',
                style: const TextStyle(
                    color: Colors.white70, fontFamily: 'DM Sans'),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text('Deny',
                      style: TextStyle(color: Colors.white54)),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF4ECDC4)),
                  onPressed: () {
                    Navigator.pop(ctx);
                    _wsSend(jsonEncode({
                      // FIX-H
                      'type': 'search_consent_approved',
                      'query': query,
                    }));
                    setState(() {
                      _chatHistory.add('[SYSTEM]: Searching the web...');
                      _scrollToBottom();
                    });
                  },
                  child: const Text('Allow Search',
                      style: TextStyle(color: Colors.black)),
                ),
              ],
            ),
          );
        }
      }
      // === CONVERSATION EXPORT READY ===
      else if (data['type'] == 'export_ready') {
        _handleExportReady(
          data['content'] as String? ?? '',
          data['filename'] as String? ?? 'sovereign_sanctuary_export.txt',
          data['suggested_destination'] as String?,
        );
      }
      // === CHAT SCHEDULING: open-slot chips from Little Nate ===
      else if (data['type'] == 'scheduling_slots') {
        if ((data['surface'] ?? '').toString() == 'chat') {
          _handleSchedulingSlots(Map<String, dynamic>.from(data));
        }
      }
      // === CHAT SCHEDULING: booking outcome ===
      else if (data['type'] == 'session_booked') {
        final sess = (data['session'] is Map)
            ? Map<String, dynamic>.from(data['session'])
            : <String, dynamic>{};
        final status = (sess['status'] ?? '').toString();
        final when = _fmtSessionWhen(sess['scheduled_start']?.toString() ?? '');
        final pending = status == 'pending_approval';
        final line = pending
            ? 'Session requested${when.isNotEmpty ? ' for $when' : ''} — pending your coach\'s approval.'
            : 'Session booked${when.isNotEmpty ? ' for $when' : ''}.';
        if (mounted) {
          _addSystemMsg(line);
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(line, style: const TextStyle(color: Colors.white)),
            backgroundColor: const Color(0xFF1A1A2E),
          ));
        }
      } else if (data['type'] == 'metrics_update' ||
          data['type'] == 'client_metrics') {
        // Handle real-time metrics updates
        setState(() {
          _metrics = data['metrics'] ?? data['data'] ?? {};
          final mh = data['mood_history'];
          if (mh is List) {
            // Normalize entries (support older keys like anxiety_level)
            _moodHistory = mh.map((e) {
              if (e is Map) {
                final m = Map<String, dynamic>.from(e);
                if (!m.containsKey('anxiety') &&
                    m.containsKey('anxiety_level')) {
                  m['anxiety'] = m['anxiety_level'];
                }
                return m;
              }
              return e;
            }).toList();
          } else if (mh != null) {
            _moodHistory = _moodHistory;
          }
        });
      } else if (data['type'] == 'metrics_data') {
        // Snapshot metrics response (string-formatted percentages)
        setState(() {
          _metrics = data['metrics'] ?? _metrics;
          final mh = data['mood_history'];
          if (mh is List) {
            _moodHistory = mh.map((e) {
              if (e is Map) {
                final m = Map<String, dynamic>.from(e);
                if (!m.containsKey('anxiety') &&
                    m.containsKey('anxiety_level')) {
                  m['anxiety'] = m['anxiety_level'];
                }
                return m;
              }
              return e;
            }).toList();
          }
        });
      } else if (data['type'] == 'nate_audio_delta') {
        if (mounted) setState(() => _isTalking = true);
        final format = data['format'] ?? 'pcm';
        if (format == 'mp3') {
          _audio.processMp3Audio(data['payload']);
        } else {
          _audio.processAudioChunk(data['payload']);
        }
        try {
          final bytes = base64Decode(data['payload'] as String);
          _nevedal.processNateAudio(bytes);
        } catch (_) {}
        _talkingTimer?.cancel();
        _talkingTimer = Timer(const Duration(milliseconds: 500), () {
          if (mounted) setState(() => _isTalking = false);
        });
      } else if (data['type'] == 'nevedal_state') {
        _nevedal.handleServerUpdate(data['data'] ?? data);
      } else if (data['type'] == 'login_failed' ||
          data['type'] == 'login_failure') {
        final msg =
            (data['message'] ?? data['error'] ?? 'Login failed').toString();
        final errorCode = (data['error_code'] ?? '').toString();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(msg),
            backgroundColor: errorCode == 'WRONG_PORTAL'
                ? const Color(0xFFC9A962)
                : Colors.red,
            duration: Duration(seconds: errorCode == 'WRONG_PORTAL' ? 6 : 4),
          ));
          Navigator.of(context).pop();
        }
      }
      // ── Nate Nudges ──
      else if (data['type'] == 'pending_nudges') {
        final nudges =
            (data['nudges'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        setState(() {
          _pendingNudges = nudges;
          _nudgeBannerDismissed = false;
        });
      } else if (data['type'] == 'nate_nudge') {
        // Real-time incoming nudge
        final nudge = Map<String, dynamic>.from(data);
        setState(() {
          _pendingNudges.insert(0, nudge);
          _nudgeBannerDismissed = false;
        });
      }
      // ── AI Mode responses ──
      else if (data['type'] == 'ai_mode_activated') {
        setState(() => _activeAiMode = data['mode']);
        _addSystemMsg(
            "AI Mode activated: ${data['mode']?.toString().toUpperCase() ?? 'UNKNOWN'}");
      } else if (data['type'] == 'ai_mode_output') {
        setState(() => _aiModeOutput = Map<String, dynamic>.from(data));
        _showAiModeOutputSheet();
      } else if (data['type'] == 'ai_mode_deactivated') {
        setState(() {
          _activeAiMode = null;
          _aiModeOutput = null;
        });
      }
      // ── Swarm Relay responses ──
      else if (data['type'] == 'swarm_response') {
        // Handle swarm responses if needed in UI
        if (kDebugMode)
          print("Swarm response: ${data['action']} → ${data['result']}");
      } else if (data['type'] == 'error') {
        final code = (data['message'] ?? data['error'] ?? 'An error occurred')
            .toString();
        final detail = (data['detail'] ?? '').toString();
        const schedCodes = {'COVENANT_REQUIRED', 'SESSION_LIMIT_REACHED'};
        if (schedCodes.contains(code) || code == 'Time slot conflict') {
          final friendly = detail.isNotEmpty ? detail : code;
          _addSystemMsg(friendly);
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(friendly, style: const TextStyle(color: Colors.white)),
              backgroundColor: const Color(0xFF8B2E2E),
            ));
          }
        } else if (!code.startsWith('Unknown message type')) {
          _addSystemMsg(code);
        }
      } else if (data['type'] == 'payment_confirmed') {
        final pType = data['payment_type'] ?? '';
        final plan = data['plan'] ?? '';
        final tokens = data['tokens_added'] ?? 0;
        final label = pType == 'token_purchase'
            ? '$tokens tokens added!'
            : 'Welcome to $plan!';
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Payment confirmed — $label'),
            backgroundColor: const Color(0xFF4ECDC4),
          ));
          _wsSend(jsonEncode({"type": "get_profile"})); // FIX-H
        }
      }
    } catch (e) {
      _debugLog("Parse Error: $e");
    }
  }

  // ── Chat Scheduling ──

  void _handleSchedulingSlots(Map<String, dynamic> data) {
    final slots = (data['slots'] is List) ? List.from(data['slots']) : [];
    if (slots.isEmpty) return; // prose already shown via nate_response
    final coachId = (data['coach_id'] ?? '').toString();
    final coachName = (data['coach_name'] ?? 'your coach').toString();
    final date = (data['date'] ?? '').toString();
    if (!mounted) return;
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF111111),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Open times with $coachName',
                style: const TextStyle(
                    color: Color(0xFFC9A962),
                    fontSize: 18,
                    fontFamily: 'Cormorant Garamond')),
            const SizedBox(height: 4),
            Text(_fmtSchedDate(date),
                style: const TextStyle(color: Colors.white54, fontSize: 13)),
            const SizedBox(height: 16),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final s in slots)
                  ActionChip(
                    backgroundColor: const Color(0xFF1A1A2E),
                    label: Text(_fmtSlotLabel((s['start'] ?? '').toString()),
                        style: const TextStyle(color: Color(0xFF4ECDC4))),
                    onPressed: () {
                      Navigator.pop(ctx);
                      _bookSchedulingSlot(
                        coachId,
                        (s['start'] ?? '').toString(),
                        (s['end'] ?? '').toString(),
                      );
                    },
                  ),
              ],
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  void _bookSchedulingSlot(String coachId, String startIso, String endIso) {
    if (startIso.isEmpty || endIso.isEmpty) return;
    // Prefer server-resolved coach_id; fall back to profile fields.
    final resolvedCoach = coachId.isNotEmpty
        ? coachId
        : ((widget.currentUserProfile?['coach_id'] ??
                    widget.currentUserProfile?['assigned_coach_id'] ??
                    '')
                .toString());
    _wsSend(jsonEncode({
      'type': 'client_book_session',
      'coach_id': resolvedCoach,
      'scheduled_start': startIso,
      'scheduled_end': endIso,
    }));
    _addSystemMsg('Requesting ${_fmtSlotLabel(startIso)}…');
  }

  String _fmtSlotLabel(String iso) {
    try {
      final dt = DateTime.parse(iso);
      final h = dt.hour % 12 == 0 ? 12 : dt.hour % 12;
      final m = dt.minute.toString().padLeft(2, '0');
      final ap = dt.hour < 12 ? 'AM' : 'PM';
      return '$h:$m $ap';
    } catch (_) {
      return iso;
    }
  }

  String _fmtSchedDate(String iso) {
    try {
      final d = DateTime.parse(iso);
      const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const months = [
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
      ];
      return '${days[d.weekday - 1]}, ${months[d.month - 1]} ${d.day}';
    } catch (_) {
      return iso;
    }
  }

  String _fmtSessionWhen(String iso) {
    if (iso.isEmpty) return '';
    return '${_fmtSchedDate(iso)} at ${_fmtSlotLabel(iso)}';
  }

  // ── Nudge Actions ──

  void _markNudgeOpened(String nudgeId) {
    _wsSend(jsonEncode(
        {"type": "nudge_mark_opened", "nudge_id": nudgeId})); // FIX-H
    setState(() {
      _pendingNudges.removeWhere((n) => n['nudge_id'] == nudgeId);
    });
  }

  void _dismissNudge(String nudgeId) {
    _wsSend(
        jsonEncode({"type": "nudge_dismiss", "nudge_id": nudgeId})); // FIX-H
    setState(() {
      _pendingNudges.removeWhere((n) => n['nudge_id'] == nudgeId);
    });
  }

  void _showNudgesSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0A),
      isScrollControlled: true,
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.5,
        maxChildSize: 0.85,
        expand: false,
        builder: (_, scrollCtrl) => Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  const Icon(Icons.auto_awesome, color: Color(0xFFC9A962)),
                  const SizedBox(width: 8),
                  const Text(
                    'MESSAGES FROM NATE',
                    style: TextStyle(
                        color: Color(0xFFC9A962),
                        fontFamily: 'Cormorant Garamond',
                        fontSize: 20,
                        fontWeight: FontWeight.bold),
                  ),
                  const Spacer(),
                  Text('${_pendingNudges.length}',
                      style: const TextStyle(color: Colors.white54)),
                ],
              ),
            ),
            Expanded(
              child: ListView.builder(
                controller: scrollCtrl,
                itemCount: _pendingNudges.length,
                itemBuilder: (_, idx) {
                  final nudge = _pendingNudges[idx];
                  final title = nudge['title']?.toString() ?? 'From Nate';
                  final body = nudge['body']?.toString() ??
                      nudge['message']?.toString() ??
                      '';
                  final nudgeId = nudge['nudge_id']?.toString() ?? '';
                  final urgency = nudge['urgency']?.toString() ?? 'normal';
                  final color = urgency == 'high'
                      ? Colors.red
                      : urgency == 'gentle'
                          ? const Color(0xFF4ECDC4)
                          : const Color(0xFFC9A962);

                  return Container(
                    margin:
                        const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                    decoration: BoxDecoration(
                      color: const Color(0xFF111111),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: color.withOpacity(0.3)),
                    ),
                    child: ListTile(
                      leading: Icon(Icons.auto_awesome, color: color, size: 28),
                      title: Text(title,
                          style: TextStyle(
                              color: color,
                              fontWeight: FontWeight.bold,
                              fontSize: 14)),
                      subtitle: Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(body,
                            style: const TextStyle(
                                color: Colors.white70,
                                fontSize: 13,
                                height: 1.4)),
                      ),
                      trailing: IconButton(
                        icon: const Icon(Icons.check_circle_outline,
                            color: Colors.green),
                        onPressed: () {
                          _markNudgeOpened(nudgeId);
                          if (_pendingNudges.isEmpty) Navigator.pop(ctx);
                        },
                      ),
                      onTap: () {
                        _markNudgeOpened(nudgeId);
                        Navigator.pop(ctx);
                        final meta = nudge['metadata'] is String
                            ? jsonDecode(nudge['metadata'])
                            : (nudge['metadata'] ?? {});
                        final action = meta['action']?.toString() ??
                            nudge['action']?.toString();
                        if (action == 'start_session') {
                          _addSystemMsg("Nate says: $body");
                        } else if (action == 'open_intake') {
                          Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => IntakeConversationScreen(
                                  profileWithToken:
                                      widget.currentUserProfile ?? {},
                                  onComplete: () {
                                    Navigator.pop(context);
                                    _checkSseIntake();
                                  },
                                ),
                              ));
                        }
                      },
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── AI Mode Actions ──

  void _activateAiMode(String mode) {
    _wsSend(jsonEncode({
      // FIX-H
      "type": "ai_mode_activate",
      "mode": mode,
      "session_id": widget.currentUserProfile?['hardware_id'] ?? 'default',
    }));
  }

  void _deactivateAiMode() {
    if (_activeAiMode == null) return;
    _wsSend(jsonEncode({
      // FIX-H
      "type": "ai_mode_deactivate",
      "session_id": widget.currentUserProfile?['hardware_id'] ?? 'default',
    }));
  }

  void _showAiModeOutputSheet() {
    if (_aiModeOutput == null) return;
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF111111),
      isScrollControlled: true,
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.65,
        maxChildSize: 0.9,
        expand: false,
        builder: (_, scrollCtrl) => SingleChildScrollView(
          controller: scrollCtrl,
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.psychology, color: Color(0xFF9D4EDD)),
                  const SizedBox(width: 8),
                  Text(
                    'AI MODE: ${_activeAiMode?.toUpperCase() ?? ""}',
                    style: const TextStyle(
                        color: Color(0xFFC9A962),
                        fontFamily: 'Cormorant Garamond',
                        fontSize: 20,
                        fontWeight: FontWeight.bold),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Text(
                _aiModeOutput?['output']?.toString() ??
                    _aiModeOutput?['result']?.toString() ??
                    'Processing...',
                style: const TextStyle(
                    color: Colors.white70,
                    fontFamily: 'DM Sans',
                    fontSize: 14,
                    height: 1.5),
              ),
              const SizedBox(height: 20),
              ElevatedButton.icon(
                icon: const Icon(Icons.close, size: 16),
                label: const Text('DEACTIVATE'),
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.red.withOpacity(0.3)),
                onPressed: () {
                  _deactivateAiMode();
                  Navigator.pop(ctx);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showAiModePicker() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0A),
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                'AI INTELLIGENCE MODES',
                style: TextStyle(
                    color: Color(0xFFC9A962),
                    fontFamily: 'Cormorant Garamond',
                    fontSize: 20,
                    fontWeight: FontWeight.bold),
              ),
            ),
            _aiModeTile(
                ctx,
                'tri_corder',
                'Tri-Corder',
                'Deep diagnostic scan of emotional patterns',
                Icons.radar,
                const Color(0xFF4ECDC4)),
            _aiModeTile(
                ctx,
                'archivist',
                'Archivist',
                'Narrative synthesis of therapeutic journey',
                Icons.auto_stories,
                const Color(0xFF9D4EDD)),
            _aiModeTile(
                ctx,
                'guardian',
                'Guardian',
                'Protective monitoring for risk indicators',
                Icons.shield,
                const Color(0xFFEF4444)),
            _aiModeTile(
                ctx,
                'supervisor',
                'Supervisor',
                'Clinical quality oversight and recommendations',
                Icons.supervisor_account,
                const Color(0xFFE8D5A3)),
            _aiModeTile(
                ctx,
                'editor',
                'Editor',
                'Literary writing companion — 7 master writers as collective intelligence',
                Icons.edit_note,
                const Color(0xFFF59E0B)),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  Widget _aiModeTile(BuildContext ctx, String mode, String title,
      String subtitle, IconData icon, Color color) {
    final isActive = _activeAiMode == mode;
    return ListTile(
      leading: Icon(icon, color: isActive ? color : color.withOpacity(0.5)),
      title: Text(title,
          style: TextStyle(
              color: isActive ? color : Colors.white,
              fontWeight: FontWeight.bold)),
      subtitle: Text(subtitle,
          style: const TextStyle(color: Colors.white38, fontSize: 12)),
      trailing: isActive
          ? const Icon(Icons.check_circle, color: Colors.green)
          : const Icon(Icons.arrow_forward_ios,
              color: Colors.white24, size: 14),
      onTap: () {
        Navigator.pop(ctx);
        if (isActive) {
          _deactivateAiMode();
        } else {
          _activateAiMode(mode);
        }
      },
    );
  }

  Future<void> _checkSseIntake() async {
    try {
      final uid =
          widget.currentUserProfile?['hardware_id'] ?? widget.username ?? '';
      final tok = widget.currentUserProfile?['token']?.toString() ?? '';
      if (uid.isEmpty || tok.isEmpty) return;
      final resp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/sse-client/intake/status/$uid'),
        headers: {'Authorization': 'Bearer $tok'},
      );
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body);
        setState(() => _sseIntakePending = data['completed'] != true);
      }
    } catch (_) {}
  }

  Future<void> _fetchRecap() async {
    try {
      final tok = widget.currentUserProfile?['token']?.toString() ?? '';
      if (tok.isEmpty) return;
      final resp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/sse-client/recap'),
        headers: {'Authorization': 'Bearer $tok'},
      );
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body);
        if (data['journey'] != null ||
            (data['active_quests'] as List?)?.isNotEmpty == true) {
          setState(() => _recapData = data);
          _recapTimer = Timer(const Duration(seconds: 30), () {
            if (mounted) setState(() => _recapDismissed = true);
          });
        }
      }
    } catch (_) {}
  }

  void _dismissRecap() {
    _recapTimer?.cancel();
    setState(() => _recapDismissed = true);
  }

  Widget _recapBtn(String label, VoidCallback onTap) {
    return GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              border:
                  Border.all(color: const Color(0xFFC9A962).withOpacity(0.5))),
          child: Text(label,
              style: const TextStyle(
                  color: Color(0xFFE8D5A3),
                  fontSize: 11,
                  fontWeight: FontWeight.w500)),
        ));
  }

  void _sendPresetMessage(String text) {
    _chatController.text = text;
    _sendMessage();
  }

  void _showNewQuestDialog() {
    final ctrl = TextEditingController();
    showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF1A1A1A),
              title: const Text('Start a New Quest',
                  style: TextStyle(color: Color(0xFFE8D5A3))),
              content: TextField(
                  controller: ctrl,
                  autofocus: true,
                  maxLines: 2,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                      hintText: 'What do you want to work on?',
                      hintStyle: TextStyle(color: Colors.white38),
                      enabledBorder: UnderlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFF8B7355))),
                      focusedBorder: UnderlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFFC9A962))))),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text('Cancel')),
                TextButton(
                    onPressed: () async {
                      final goal = ctrl.text.trim();
                      if (goal.isEmpty) return;
                      Navigator.pop(ctx);
                      await _createQuestWithGoal(goal);
                    },
                    child: const Text('Start Quest',
                        style: TextStyle(color: Color(0xFFC9A962)))),
              ],
            ));
  }

  void _showNewMissionDialog() {
    final targetCtrl = TextEditingController();
    showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF1A1A1A),
              title: const Text('Start a New Mission',
                  style: TextStyle(color: Color(0xFFE8D5A3))),
              content: TextField(
                  controller: targetCtrl,
                  autofocus: true,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                      hintText:
                          'Who is this about? (e.g. my mother, my partner)',
                      hintStyle: TextStyle(color: Colors.white38),
                      enabledBorder: UnderlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFF8B7355))),
                      focusedBorder: UnderlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFFC9A962))))),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text('Cancel')),
                TextButton(
                    onPressed: () async {
                      final target = targetCtrl.text.trim();
                      if (target.isEmpty) return;
                      Navigator.pop(ctx);
                      await _createMissionWithTarget(target);
                    },
                    child: const Text('Start Mission',
                        style: TextStyle(color: Color(0xFFC9A962)))),
              ],
            ));
  }

  Future<void> _createQuestFromContext() async {
    final userMsgs = _chatHistory.where((m) => m.startsWith("You:")).toList();
    final last3 =
        userMsgs.length > 3 ? userMsgs.sublist(userMsgs.length - 3) : userMsgs;
    final goal = last3.map((m) => m.replaceFirst("You: ", "")).join(" ").trim();
    if (goal.isEmpty) {
      _showNewQuestDialog();
      return;
    }
    await _createQuestWithGoal(
        goal.length > 200 ? goal.substring(0, 200) : goal);
  }

  Future<void> _createQuestWithGoal(String goal) async {
    final tok = widget.currentUserProfile?['token']?.toString() ?? '';
    try {
      final resp = await http.post(
          Uri.parse('${AppConfig.apiBaseUrl}/api/sse-client/quest/create'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $tok'
          },
          body: jsonEncode({'goal': goal}));
      if (mounted && resp.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Quest started: $goal'),
            backgroundColor: const Color(0xFFC9A962)));
        _sendPresetMessage("I just started a quest: $goal");
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not create quest: $e')));
    }
  }

  Future<void> _createMissionWithTarget(String target) async {
    final tok = widget.currentUserProfile?['token']?.toString() ?? '';
    try {
      final resp = await http.post(
          Uri.parse('${AppConfig.apiBaseUrl}/api/sse-client/mission/create'),
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer $tok'
          },
          body: jsonEncode({
            'relationship_target': target,
            'relationship_type': 'personal'
          }));
      if (mounted && resp.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Mission started: $target'),
            backgroundColor: const Color(0xFFC9A962)));
        _sendPresetMessage("I just started a mission about $target");
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not create mission: $e')));
    }
  }

  void _updateMetricsFromProfile(Map<String, dynamic> profile) {
    setState(() {
      _metrics = {
        'C_emo': profile['C_emo'] ?? 0.5,
        'GAP': profile['GAP'] ?? 0.3,
        'Quantum': profile['Quantum'] ?? 0.5,
        'anxiety_level': profile['anxiety_level'] ?? 0,
        'stress_level': profile['stress_level'] ?? 0,
        'engagement': profile['engagement'] ?? 0.5,
        'risk_level': profile['risk_level'] ?? 'LOW',
        'mood_current': profile['mood_current'] ?? 'neutral',
        'mood_trend': profile['mood_trend'] ?? 'stable',
      };
    });
  }

  double _toDouble(dynamic value, {double fallback = 0.5}) {
    if (value is double) return value;
    if (value is int) return value.toDouble();
    if (value is String) {
      final cleaned = value.replaceAll('%', '').trim();
      final d = double.tryParse(cleaned);
      if (d != null) return d > 1.0 ? d / 100.0 : d;
    }
    return fallback;
  }

  void _requestMetrics() {
    _wsSend(jsonEncode({"type": "get_metrics"})); // FIX-H
  }

  // ===========================================================================
  // CUSTOM VOCABULARY (ACCESSIBILITY / AUTHENTICITY)
  // ===========================================================================

  static const String _prefsVocabKey = 'stt_custom_vocab_v1';

  Future<void> _loadCustomVocabulary() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_prefsVocabKey);
      if (raw == null || raw.trim().isEmpty) return;
      final decoded = jsonDecode(raw);
      if (decoded is! List) return;
      _customVocab
        ..clear()
        ..addAll(decoded.map(_VocabEntry.tryFromJson).whereType<_VocabEntry>());
      if (mounted) setState(() {});
    } catch (e) {
      _debugLog('Vocab load error: $e');
    }
  }

  Future<void> _saveCustomVocabulary() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = jsonEncode(_customVocab.map((e) => e.toJson()).toList());
      await prefs.setString(_prefsVocabKey, raw);
    } catch (e) {
      _debugLog('Vocab save error: $e');
    }
  }

  String _reEscape(String s) => RegExp.escape(s);

  String _applyCustomVocabulary(String input) {
    var s = input;
    if (s.trim().isEmpty) return s;
    if (_customVocab.isEmpty) return s;

    for (final entry in _customVocab) {
      final canonical = entry.canonical;
      final candidates = <String>{...entry.aliases}
          .where((a) => a.trim().isNotEmpty)
          .toList()
        ..sort((a, b) => b.length.compareTo(a.length)); // longer first
      for (final alias in candidates) {
        // Use non-word boundaries so phrases with spaces work too.
        final rx = RegExp(r'(?<!\w)' + _reEscape(alias) + r'(?!\w)',
            caseSensitive: false);
        s = s.replaceAll(rx, canonical);
      }
    }
    return s;
  }

  void _openVocabularySheet() {
    final canonicalCtrl = TextEditingController();
    final aliasesCtrl = TextEditingController();

    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0F),
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: MediaQuery.of(context).viewInsets.bottom + 16,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Custom Vocabulary',
              style: TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            const Text(
              'Add names/terms and common mis-hearings (aliases). We will convert aliases → canonical in dictation.',
              style: TextStyle(color: Colors.white60, fontSize: 12),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: canonicalCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: 'Canonical word/phrase (e.g. Nevedal)',
                labelStyle: TextStyle(color: Colors.white60),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: aliasesCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText:
                    'Aliases (comma-separated) (e.g. never dull, nevada)',
                labelStyle: TextStyle(color: Colors.white60),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFC9A962),
                      foregroundColor: Colors.black,
                    ),
                    onPressed: () async {
                      final c = canonicalCtrl.text.trim();
                      if (c.isEmpty) return;
                      final aliases = aliasesCtrl.text
                          .split(',')
                          .map((s) => s.trim())
                          .where((s) => s.isNotEmpty)
                          .toList();
                      setState(() {
                        _customVocab
                            .add(_VocabEntry(canonical: c, aliases: aliases));
                      });
                      await _saveCustomVocabulary();
                      canonicalCtrl.clear();
                      aliasesCtrl.clear();
                    },
                    child: const Text('Add'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (_customVocab.isNotEmpty)
              SizedBox(
                height: 220,
                child: ListView.builder(
                  itemCount: _customVocab.length,
                  itemBuilder: (context, i) {
                    final e = _customVocab[i];
                    return ListTile(
                      dense: true,
                      title: Text(e.canonical,
                          style: const TextStyle(color: Colors.white)),
                      subtitle: e.aliases.isEmpty
                          ? null
                          : Text(e.aliases.join(', '),
                              style: const TextStyle(color: Colors.white60)),
                      trailing: IconButton(
                        icon: const Icon(Icons.delete, color: Colors.redAccent),
                        onPressed: () async {
                          setState(() => _customVocab.removeAt(i));
                          await _saveCustomVocabulary();
                        },
                      ),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }

  void _addSystemMsg(String msg) {
    final tagged = "[SYSTEM]: $msg";
    if (_chatHistory.isNotEmpty && _chatHistory.last == tagged) return;
    setState(() {
      _chatHistory.add(tagged);
      _scrollToBottom();
    });
  }

  // ===========================================================================
  // TEXT-TO-SPEECH (READ BACK)
  // ===========================================================================

  Future<void> _initTts() async {
    try {
      await _tts.setLanguage('en-US');
    } catch (_) {}
    try {
      await _tts.awaitSpeakCompletion(true);
    } catch (_) {}
    try {
      await _tts.setSpeechRate(0.48);
    } catch (_) {}
    try {
      await _tts.setPitch(1.0);
    } catch (_) {}
    try {
      await _tts.setVolume(1.0);
    } catch (_) {}

    _tts.setStartHandler(() {
      if (mounted) setState(() => _isSpeaking = true);
      // #region agent log
      _dbgLog('H2', 'tts_start', {
        'dictationArmed': _dictationArmed,
        'isListening': _isListening,
      });
      // #endregion
    });
    _tts.setCompletionHandler(() {
      if (mounted) setState(() => _isSpeaking = false);
      // #region agent log
      _dbgLog('H2', 'tts_complete', {
        'dictationArmed': _dictationArmed,
        'isListening': _isListening,
      });
      // #endregion
      if (_dictationArmed) {
        _scheduleDictationRestart(delayMs: 400);
      }
    });
    _tts.setCancelHandler(() {
      if (mounted) setState(() => _isSpeaking = false);
      // #region agent log
      _dbgLog('H2', 'tts_cancel', {
        'dictationArmed': _dictationArmed,
        'isListening': _isListening,
      });
      // #endregion
      if (_dictationArmed) {
        _scheduleDictationRestart(delayMs: 400);
      }
    });
    _tts.setErrorHandler((_) {
      if (mounted) setState(() => _isSpeaking = false);
      // #region agent log
      _dbgLog('H2', 'tts_error', {
        'dictationArmed': _dictationArmed,
        'isListening': _isListening,
      });
      // #endregion
      if (_dictationArmed) {
        _scheduleDictationRestart(delayMs: 400);
      }
    });

    // Best-effort: pick an English voice if available (web often needs this).
    try {
      final voices = await _tts.getVoices;
      if (voices is List) {
        Map<String, dynamic>? pick;
        for (final v in voices) {
          if (v is Map) {
            final m = Map<String, dynamic>.from(v);
            final locale = (m['locale'] ?? '').toString().toLowerCase();
            if (locale.startsWith('en-')) {
              pick = m;
              break;
            }
          }
        }
        if (pick != null) {
          final name = (pick['name'] ?? '').toString();
          final locale = (pick['locale'] ?? '').toString();
          if (name.isNotEmpty && locale.isNotEmpty) {
            await _tts.setVoice({'name': name, 'locale': locale});
          }
        }
      }
    } catch (_) {}
  }

  Future<void> _unlockTtsOnce() async {
    if (_ttsUnlocked) return;
    _ttsUnlocked = true;
    // On web, SpeechSynthesis often requires a user gesture. Calling speak from
    // a tap/click handler is a reliable way to unlock future voice commands.
    try {
      await _tts.speak(' ');
      await _tts.stop();
    } catch (_) {}
  }

  String _draftForReadback({int? sentenceNumber}) {
    final full = _chatController.text.trim();
    if (full.isEmpty) return '';

    final start = _selectionStart;
    final end = _selectionEnd;
    if (sentenceNumber == null &&
        start != null &&
        end != null &&
        start >= 0 &&
        end <= full.length &&
        start < end) {
      return full.substring(start, end).trim();
    }

    if (sentenceNumber != null) {
      final spans = _sentenceSpans(full);
      if (sentenceNumber <= 0 || sentenceNumber > spans.length) return '';
      final span = spans[sentenceNumber - 1];
      return full.substring(span.start, span.end).trim();
    }

    return full;
  }

  Future<void> _readBackDraft() async {
    final text = _draftForReadback();
    if (text.isEmpty) {
      _addSystemMsg('Nothing to read back yet.');
      return;
    }
    // #region agent log
    _dbgLog('H1', 'read_back_request', {
      'textLen': text.length,
      'selectionActive': _selectionStart != null && _selectionEnd != null,
      'dictationArmed': _dictationArmed,
      'isSpeaking': _isSpeaking,
    });
    // #endregion
    // Pause dictation while speaking to prevent feedback loops.
    await _stopSpeechAndSuppressLateResults();
    try {
      await _tts.stop();
    } catch (_) {}
    // Set speaking true optimistically to avoid a race where dictation restarts
    // before the TTS start handler fires.
    if (mounted) setState(() => _isSpeaking = true);
    try {
      final r = await _tts.speak(text);
      if (r == 0 || r == false) {
        if (mounted) setState(() => _isSpeaking = false);
        _addSystemMsg(
            'Read back blocked by the browser. Tap the speaker icon once, then say “read it back”.');
      }
    } catch (e) {
      if (mounted) setState(() => _isSpeaking = false);
      _addSystemMsg(
          'Read back failed. If on web, click the speaker icon once to allow audio.');
      _debugLog('TTS speak error: $e');
    }
  }

  Future<void> _readBackSentence(int sentenceNumber) async {
    final text = _draftForReadback(sentenceNumber: sentenceNumber);
    if (text.isEmpty) {
      _addSystemMsg('Sentence $sentenceNumber not found to read back.');
      return;
    }
    await _stopSpeechAndSuppressLateResults();
    try {
      await _tts.stop();
    } catch (_) {}
    await _tts.speak(text);
  }

  Future<void> _stopReading() async {
    try {
      await _tts.stop();
    } catch (_) {}
    if (mounted) setState(() => _isSpeaking = false);
  }

  // ===========================================================================
  // SPEECH-TO-TEXT (NEURAL INTERFACE V2)
  // ===========================================================================

  void _scheduleDictationRestart({int delayMs = 150}) {
    if (_restartScheduled) return;
    _restartScheduled = true;
    // #region agent log
    _dbgLog('H2', 'schedule_restart', {
      'delayMs': delayMs,
      'dictationArmed': _dictationArmed,
      'isListening': _isListening,
      'isSpeaking': _isSpeaking,
      'restartScheduled': _restartScheduled,
    });
    // #endregion
    Future.delayed(Duration(milliseconds: delayMs), () {
      _restartScheduled = false;
      if (!mounted) return;
      if (_dictationArmed && !_isListening && !_isSpeaking) {
        _startListeningSession();
      }
    });
  }

  Future<void> _initSpeechToText() async {
    try {
      _speechAvailable = await _speech.initialize(
        onError: (error) {
          _debugLog('Speech error: ${error.errorMsg}');
          if (mounted) setState(() => _isListening = false);
        },
        onStatus: (status) {
          _debugLog('Speech status: $status');
          if (status == 'done' || status == 'notListening') {
            if (mounted) setState(() => _isListening = false);
            // Keep dictation continuous for accessibility: if the user pauses and
            // STT stops, auto-restart without losing existing text.
            if (_dictationArmed) {
              _scheduleDictationRestart(delayMs: 50);
            }
          }
        },
      );
      if (mounted) setState(() {});
    } catch (e) {
      _debugLog('Speech init error: $e');
      _speechAvailable = false;
    }
  }

  Future<void> _stopSpeechAndSuppressLateResults() async {
    // Keep this short: long suppression creates a "dead zone" where commands
    // like "send" get swallowed right after a pause.
    _suppressSpeechUntil =
        DateTime.now().add(const Duration(milliseconds: 800));
    if (_isListening) {
      try {
        await _speech.stop();
      } catch (_) {}
      try {
        await _speech.cancel();
      } catch (_) {}
      if (mounted) setState(() => _isListening = false);
    }
  }

  String _composeDictation(String base, String addition) {
    final b = base;
    final a = addition;
    if (b.trim().isEmpty) return a;
    if (a.trim().isEmpty) return b;
    if (b.endsWith(' ') || b.endsWith('\n') || b.endsWith('\t')) return '$b$a';
    return '$b $a';
  }

  String _deleteLastWord(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;
    final m = RegExp(r'^(.*?)(\S+)\s*$').firstMatch(s);
    if (m == null) return '';
    return (m.group(1) ?? '').trimRight();
  }

  String _deleteLastSentence(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;

    // Find sentence boundaries.
    final matches = RegExp(r'[.!?]+').allMatches(s).toList();
    if (matches.isEmpty) {
      // No punctuation: remove last line or clear.
      final nl = s.lastIndexOf('\n');
      if (nl != -1) return s.substring(0, nl).trimRight();
      return '';
    }
    if (matches.length == 1) return ''; // only one sentence → clear it
    final prev = matches[matches.length - 2];
    var cut = prev.end;
    while (cut < s.length && s[cut] == ' ') cut++;
    return s.substring(0, cut).trimRight();
  }

  String _replaceLastOccurrenceCaseInsensitive(
      String input, String from, String to) {
    final hay = input;
    final needle = from.trim();
    if (needle.isEmpty) return hay;
    final lowerHay = hay.toLowerCase();
    final lowerNeedle = needle.toLowerCase();
    final idx = lowerHay.lastIndexOf(lowerNeedle);
    if (idx == -1) return hay;
    return hay.substring(0, idx) + to + hay.substring(idx + needle.length);
  }

  String _autoFormat(String input) {
    var s = input;
    if (s.trim().isEmpty) return s;

    // Normalize whitespace a bit (without being destructive).
    s = s.replaceAll(RegExp(r'[ \t]{2,}'), ' ');

    // Capitalize standalone "i" and common contractions.
    s = s.replaceAllMapped(RegExp(r'\bi\b'), (m) => 'I');
    s = s.replaceAllMapped(
        RegExp(r"\bi(['’]m)\b", caseSensitive: false), (m) => "I'm");
    s = s.replaceAllMapped(
        RegExp(r"\bi(['’]ll)\b", caseSensitive: false), (m) => "I'll");
    s = s.replaceAllMapped(
        RegExp(r"\bi(['’]ve)\b", caseSensitive: false), (m) => "I've");
    s = s.replaceAllMapped(
        RegExp(r"\bi(['’]d)\b", caseSensitive: false), (m) => "I'd");

    // Capitalize first letter of the message and after sentence boundaries.
    String capAt(String str, int idx) {
      if (idx < 0 || idx >= str.length) return str;
      final ch = str[idx];
      if (!RegExp(r'[A-Za-z]').hasMatch(ch)) return str;
      return str.substring(0, idx) + ch.toUpperCase() + str.substring(idx + 1);
    }

    // First alpha character.
    final firstAlpha = RegExp(r'[A-Za-z]').firstMatch(s);
    if (firstAlpha != null) s = capAt(s, firstAlpha.start);

    // After . ! ? and newlines.
    for (final m in RegExp(r'([.!?]\s+|\n+)([A-Za-z])')
        .allMatches(s)
        .toList()
        .reversed) {
      final idx = m.start + (m.group(1)?.length ?? 0);
      s = capAt(s, idx);
    }

    return s;
  }

  String _postProcessFinalDictation(String input) {
    var s = input;
    s = _applyCustomVocabulary(s);
    s = _autoFormat(s);
    return s;
  }

  int? _parseSmallNumber(String raw) {
    final t = raw.trim().toLowerCase();
    final asInt = int.tryParse(t);
    if (asInt != null) return asInt;
    const map = <String, int>{
      'one': 1,
      'two': 2,
      'three': 3,
      'four': 4,
      'five': 5,
      'six': 6,
      'seven': 7,
      'eight': 8,
      'nine': 9,
      'ten': 10,
      'eleven': 11,
      'twelve': 12,
      'thirteen': 13,
      'fourteen': 14,
      'fifteen': 15,
      'sixteen': 16,
      'seventeen': 17,
      'eighteen': 18,
      'nineteen': 19,
      'twenty': 20,
    };
    return map[t];
  }

  List<({int start, int end})> _sentenceSpans(String input) {
    final s = input;
    final spans = <({int start, int end})>[];
    int start = 0;
    for (final m in RegExp(r'[.!?]+').allMatches(s)) {
      final end = m.end;
      spans.add((start: start, end: end));
      start = end;
      // consume whitespace after punctuation
      while (start < s.length && s[start] == ' ') start++;
    }
    if (start < s.length) spans.add((start: start, end: s.length));
    return spans;
  }

  void _selectLastPhrase(String phrase) {
    final p = phrase.trim();
    if (p.isEmpty) return;
    final hay = _chatController.text;
    final idx = hay.toLowerCase().lastIndexOf(p.toLowerCase());
    if (idx == -1) {
      _addSystemMsg('Selection not found: "$p"');
      return;
    }
    _selectionStart = idx;
    _selectionEnd = idx + p.length;
  }

  void _clearSelection() {
    _selectionStart = null;
    _selectionEnd = null;
  }

  // Returns (commandType, optionalBody) where body is text spoken before the command.
  ({String type, String body})? _extractVoiceCommand(String raw) {
    String stripWake(String s) {
      return s
          .trim()
          .replaceFirst(
            RegExp(r'^(?:hey\s+)?(?:little\s+nate|nate)\s*[, ]+\s*',
                caseSensitive: false),
            '',
          )
          .trim();
    }

    final rawTrimmed = raw.trim();
    final cmdText = stripWake(rawTrimmed);
    final lower = cmdText.toLowerCase();
    final cooldown = _voiceCommandCooldownUntil;
    if (cooldown != null && DateTime.now().isBefore(cooldown)) return null;

    final clearExact = RegExp(
      r'^(delete message and start over|delete message|clear message|start over|clear)$',
      caseSensitive: false,
    );
    final deleteLastSentence = RegExp(
      r'^(delete last sentence|remove last sentence|delete last line|undo that|scratch that|undo)$',
      caseSensitive: false,
    );
    final deleteLastWord = RegExp(
      r'^(delete last word|remove last word)$',
      caseSensitive: false,
    );

    // Recognize TTS controls even inside longer phrases.
    final stopReadingAnywhere = RegExp(
      r'\b(stop reading|stop speaking|cancel reading)\b|\b(stop)\b$',
      caseSensitive: false,
    );
    final readSentenceAnywhere = RegExp(
      r'\bread sentence (.+?)\b',
      caseSensitive: false,
    );
    final readBackAnywhere = RegExp(
      r'\b(read it back|read that back|read back|read message|read draft|read it|read that)\b',
      caseSensitive: false,
    );
    final sendAnywhere = RegExp(
      // Do NOT include bare "sent" here (false-positive: "I sent an email...").
      r'\b(send message|send it|send this|send|message sent|sand|said|cent|sin)\b',
      caseSensitive: false,
    );
    final clearAnywhere = RegExp(
      r'\b(delete message and start over|delete message|clear message|start over|clear)\b',
      caseSensitive: false,
    );
    final deleteLastSentenceAnywhere = RegExp(
      r'\b(delete last sentence|remove last sentence|delete last line|undo that|scratch that|undo)\b',
      caseSensitive: false,
    );
    final deleteLastWordAnywhere = RegExp(
      r'\b(delete last word|remove last word)\b',
      caseSensitive: false,
    );
    final replaceAllCmd = RegExp(r'\breplace\s+all\s+(.+?)\s+with\s+(.+?)\s*$',
        caseSensitive: false);
    final replaceFirstCmd = RegExp(
        r'\breplace\s+first\s+(.+?)\s+with\s+(.+?)\s*$',
        caseSensitive: false);
    final replaceLastCmd = RegExp(
        r'\breplace\s+last\s+(.+?)\s+with\s+(.+?)\s*$',
        caseSensitive: false);
    final replaceSentenceCmd = RegExp(
        r'\breplace\s+sentence\s+(.+?)\s+with\s+(.+?)\s*$',
        caseSensitive: false);
    final deleteSentenceCmd =
        RegExp(r'\bdelete\s+sentence\s+(.+?)\s*$', caseSensitive: false);
    final selectCmd = RegExp(r'\bselect\s+(.+?)\s*$', caseSensitive: false);
    final replaceThatCmd =
        RegExp(r'\breplace\s+that\s+with\s+(.+?)\s*$', caseSensitive: false);
    final deleteThatCmd = RegExp(r'\bdelete\s+that\s*$', caseSensitive: false);
    final replaceCmd =
        RegExp(r'\breplace\s+(.+?)\s+with\s+(.+?)\s*$', caseSensitive: false);

    if (clearExact.hasMatch(lower)) return (type: 'clear_all', body: '');
    if (deleteLastSentence.hasMatch(lower))
      return (type: 'delete_last_sentence', body: '');
    if (deleteLastWord.hasMatch(lower))
      return (type: 'delete_last_word', body: '');
    if (stopReadingAnywhere.hasMatch(lower))
      return (type: 'stop_reading', body: '');

    // Natural language support (e.g. "can you clear message", "please delete last sentence")
    if (clearAnywhere.hasMatch(lower)) return (type: 'clear_all', body: '');
    if (deleteLastSentenceAnywhere.hasMatch(lower))
      return (type: 'delete_last_sentence', body: '');
    if (deleteLastWordAnywhere.hasMatch(lower))
      return (type: 'delete_last_word', body: '');

    final rsm = readSentenceAnywhere.firstMatch(raw);
    if (rsm != null)
      return (type: 'read_sentence:${(rsm.group(1) ?? '').trim()}', body: '');

    // Treat a standalone "sent"/misheard variants as a send command.
    if (RegExp(r'^(sent|sand|said|cent|sin)$', caseSensitive: false)
        .hasMatch(lower)) {
      return (type: 'send', body: '');
    }

    // SEND should win if present (often appended to longer utterances).
    // Require it to be at/near the end to avoid false positives like "I sent an email".
    final sendTrail = RegExp(
        r'(?:\b(send message|send it|send this|send|message sent|sand|said|cent|sin)\b)[\s,.;:!?]*$',
        caseSensitive: false);
    final sm = sendTrail.firstMatch(cmdText);
    if (sm != null) {
      final body = cmdText.substring(0, sm.start).trim();
      // #region agent log
      _dbgLog('H1', 'send_match', {
        'rawLen': raw.length,
        'bodyLen': body.length,
      });
      // #endregion
      return (type: 'send', body: body);
    }

    // Read-back should capture any body spoken before the command.
    final rbm = readBackAnywhere.firstMatch(cmdText);
    if (rbm != null) {
      final body = cmdText.substring(0, rbm.start).trim();
      // #region agent log
      _dbgLog('H1', 'read_back_match', {
        'rawLen': raw.length,
        'bodyLen': body.length,
      });
      // #endregion
      return (type: 'read_back', body: body);
    }
    Match? rm;

    rm = replaceAllCmd.firstMatch(cmdText);
    if (rm != null)
      return (
        type:
            'replace_all:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}',
        body: ''
      );

    rm = replaceFirstCmd.firstMatch(cmdText);
    if (rm != null)
      return (
        type:
            'replace_first:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}',
        body: ''
      );

    rm = replaceLastCmd.firstMatch(cmdText);
    if (rm != null)
      return (
        type:
            'replace_last:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}',
        body: ''
      );

    rm = replaceSentenceCmd.firstMatch(cmdText);
    if (rm != null)
      return (
        type:
            'replace_sentence:${(rm.group(1) ?? '').trim()}=>${(rm.group(2) ?? '').trim()}',
        body: ''
      );

    rm = deleteSentenceCmd.firstMatch(cmdText);
    if (rm != null)
      return (type: 'delete_sentence:${(rm.group(1) ?? '').trim()}', body: '');

    rm = selectCmd.firstMatch(cmdText);
    if (rm != null)
      return (type: 'select:${(rm.group(1) ?? '').trim()}', body: '');

    rm = replaceThatCmd.firstMatch(cmdText);
    if (rm != null)
      return (type: 'replace_that:${(rm.group(1) ?? '').trim()}', body: '');

    if (deleteThatCmd.hasMatch(lower)) return (type: 'delete_that', body: '');

    rm = replaceCmd.firstMatch(cmdText);
    if (rm != null) {
      final from = (rm.group(1) ?? '').trim();
      final to = (rm.group(2) ?? '').trim();
      if (from.isNotEmpty) return (type: 'replace_last:$from=>$to', body: '');
    }

    return null;
  }

  Future<void> _handleVoiceCommand(String type, {String body = ''}) async {
    // prevent double-triggering on repeated final results
    _voiceCommandCooldownUntil = DateTime.now().add(const Duration(seconds: 2));
    // #region agent log
    _dbgLog('H1', 'command_fired', {
      'type': type,
      'bodyLen': body.length,
      'dictationArmed': _dictationArmed,
      'isListening': _isListening,
      'isSpeaking': _isSpeaking,
    });
    // #endregion

    String stripTrailingSendTokens(String input) {
      var s = input.trimRight();
      final rx = RegExp(
        // Remove repeated trailing send tokens, plus surrounding punctuation/spaces.
        r'(?:[\s,.;:!?]*\b(?:send message|send it|send|message sent|sent)\b[\s,.;:!?]*)+\s*$',
        caseSensitive: false,
      );
      while (true) {
        final m = rx.firstMatch(s);
        if (m == null) break;
        s = s.substring(0, m.start).trimRight();
      }
      return s;
    }

    bool looksLikeCommandText(String s) {
      // Be conservative: only treat clear command-phrases as commands.
      // Do NOT blacklist generic words like "sentence" or "read" which can be normal message content.
      final t = s.toLowerCase();
      return RegExp(
            r'\b(delete message|start over|clear message|clear|replace that|replace all|replace first|replace last|replace sentence|delete sentence|select|read it back|read that back|read back|read sentence|stop reading|stop speaking|cancel reading)\b',
            caseSensitive: false,
          ).hasMatch(t) ||
          t.trim() == 'message sent' ||
          t.trim() == 'sent';
    }

    if (type == 'send') {
      final b = stripTrailingSendTokens(body).trim();
      // If the user said "send" as part of a request phrase, do NOT treat the
      // prefix as message content—just send the existing draft.
      if (b.isNotEmpty && !looksLikeCommandText(b)) {
        final normalized = _postProcessFinalDictation(_normalizeDictation(b));
        setState(() {
          _chatController.text =
              _composeDictation(_dictationBaseText, normalized);
        });
      } else {
        // If we didn't extract a clean body, at least strip any trailing
        // command tokens that STT may have appended into the draft.
        setState(() {
          final cleaned = stripTrailingSendTokens(_chatController.text);
          _chatController.text = cleaned;
          _dictationBaseText = cleaned;
          _dictationSessionText = '';
        });
      }

      // Always sanitize the draft/base before sending (interim STT can still
      // append "send message" into the textbox prior to command firing).
      setState(() {
        final cleaned = stripTrailingSendTokens(_chatController.text);
        _chatController.text = cleaned;
        _dictationBaseText = stripTrailingSendTokens(_dictationBaseText);
        _dictationSessionText = '';
      });

      _addSystemMsg('VOICE CMD: SEND');
      await _sendMessage();
    } else if (type == 'clear_all') {
      setState(() {
        _chatController.clear();
        _dictationBaseText = '';
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'delete_last_sentence') {
      setState(() {
        _chatController.text = _deleteLastSentence(_chatController.text);
        _dictationBaseText = _chatController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'delete_last_word') {
      setState(() {
        _chatController.text = _deleteLastWord(_chatController.text);
        _dictationBaseText = _chatController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type == 'read_back') {
      // Commit any body spoken before "read it back", then read aloud.
      final b = body.trim();
      if (b.isNotEmpty && !looksLikeCommandText(b)) {
        final normalized = _postProcessFinalDictation(_normalizeDictation(b));
        setState(() {
          _chatController.text =
              _composeDictation(_dictationBaseText, normalized);
          _dictationBaseText = _chatController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      }
      await _readBackDraft();
    } else if (type == 'stop_reading') {
      await _stopReading();
    } else if (type.startsWith('select:')) {
      final phrase = type.substring('select:'.length).trim();
      setState(() {
        _selectLastPhrase(phrase);
      });
    } else if (type.startsWith('replace_that:')) {
      final to = type.substring('replace_that:'.length);
      final start = _selectionStart;
      final end = _selectionEnd;
      if (start != null &&
          end != null &&
          start >= 0 &&
          end <= _chatController.text.length &&
          start < end) {
        setState(() {
          final t = _chatController.text;
          _chatController.text = t.substring(0, start) + to + t.substring(end);
          _dictationBaseText = _chatController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      } else {
        _addSystemMsg(
            'No active selection to replace. Say “select <phrase>” first.');
      }
    } else if (type == 'delete_that') {
      final start = _selectionStart;
      final end = _selectionEnd;
      if (start != null &&
          end != null &&
          start >= 0 &&
          end <= _chatController.text.length &&
          start < end) {
        setState(() {
          final t = _chatController.text;
          _chatController.text =
              (t.substring(0, start) + t.substring(end)).trimRight();
          _dictationBaseText = _chatController.text;
          _dictationSessionText = '';
          _clearSelection();
        });
      } else {
        _addSystemMsg(
            'No active selection to delete. Say “select <phrase>” first.');
      }
    } else if (type.startsWith('replace_sentence:')) {
      final payload = type.substring('replace_sentence:'.length);
      final parts = payload.split('=>');
      final idxRaw = parts.isNotEmpty ? parts[0] : '';
      final replacement = parts.length > 1 ? parts[1] : '';
      final idx = _parseSmallNumber(idxRaw);
      if (idx == null || idx <= 0) {
        _addSystemMsg('Could not parse sentence number.');
      } else {
        final spans = _sentenceSpans(_chatController.text);
        if (idx > spans.length) {
          _addSystemMsg('Sentence $idx not found.');
        } else {
          final span = spans[idx - 1];
          setState(() {
            final t = _chatController.text;
            _chatController.text = (t.substring(0, span.start) +
                    replacement +
                    t.substring(span.end))
                .trimRight();
            _dictationBaseText = _chatController.text;
            _dictationSessionText = '';
            _clearSelection();
          });
        }
      }
    } else if (type.startsWith('delete_sentence:')) {
      final idxRaw = type.substring('delete_sentence:'.length);
      final idx = _parseSmallNumber(idxRaw);
      if (idx == null || idx <= 0) {
        _addSystemMsg('Could not parse sentence number.');
      } else {
        final spans = _sentenceSpans(_chatController.text);
        if (idx > spans.length) {
          _addSystemMsg('Sentence $idx not found.');
        } else {
          final span = spans[idx - 1];
          setState(() {
            final t = _chatController.text;
            _chatController.text =
                (t.substring(0, span.start) + t.substring(span.end))
                    .trimRight();
            _dictationBaseText = _chatController.text;
            _dictationSessionText = '';
            _clearSelection();
          });
        }
      }
    } else if (type.startsWith('replace_all:') ||
        type.startsWith('replace_first:') ||
        type.startsWith('replace_last:')) {
      final mode =
          type.split(':').first; // replace_all / replace_first / replace_last
      final payload = type.substring(mode.length + 1);
      final parts = payload.split('=>');
      final from = parts.isNotEmpty ? parts[0] : '';
      final to = parts.length > 1 ? parts[1] : '';
      setState(() {
        final t = _chatController.text;
        if (from.trim().isEmpty) return;
        if (mode == 'replace_all') {
          final rx = RegExp(RegExp.escape(from), caseSensitive: false);
          _chatController.text = t.replaceAll(rx, to);
        } else if (mode == 'replace_first') {
          final rx = RegExp(RegExp.escape(from), caseSensitive: false);
          _chatController.text = t.replaceFirst(rx, to);
        } else {
          _chatController.text =
              _replaceLastOccurrenceCaseInsensitive(t, from, to);
        }
        _dictationBaseText = _chatController.text;
        _dictationSessionText = '';
        _clearSelection();
      });
    } else if (type.startsWith('read_sentence:')) {
      final rawIdx = type.substring('read_sentence:'.length);
      final idx = _parseSmallNumber(rawIdx);
      if (idx == null) {
        _addSystemMsg('Could not parse sentence number to read.');
      } else {
        await _readBackSentence(idx);
      }
    }

    // Continue dictation automatically if armed.
    if (_dictationArmed) {
      await _stopSpeechAndSuppressLateResults();
      _scheduleDictationRestart(delayMs: 150);
    }
  }

  Future<void> _startListeningSession() async {
    if (!_speechAvailable) return;
    _dictationBaseText = _chatController.text;
    _dictationSessionText = '';

    setState(() => _isListening = true);
    await _speech.listen(
      onResult: (result) {
        // Guard against "late" final callbacks repopulating input after Stop/Send.
        if (!_isListening) return;
        final until = _suppressSpeechUntil;
        if (until != null && DateTime.now().isBefore(until)) return;

        final raw = result.recognizedWords.trim();
        if (raw.isEmpty) return;

        // Detect commands on BOTH partial and final results.
        // On partials, only fire when the utterance looks like a command.
        final cmd = _extractVoiceCommand(raw);
        String stripWake(String s) {
          return s
              .trim()
              .replaceFirst(
                RegExp(r'^(?:hey\s+)?(?:little\s+nate|nate)\s*[, ]+\s*',
                    caseSensitive: false),
                '',
              )
              .trim();
        }

        bool isCommandLikeUtterance(String s) {
          final t = stripWake(s)
              .toLowerCase()
              .trimRight()
              .replaceAll(RegExp(r'[.!,;:]+$'), '');
          return RegExp(
            r'^(send|send it|send message|message sent|sent|read|read it|read it back|read back|read sentence|stop|stop reading|stop speaking|clear|start over|delete|undo|scratch that|replace|select)\b',
            caseSensitive: false,
          ).hasMatch(t);
        }

        if (cmd != null) {
          if (result.finalResult || isCommandLikeUtterance(raw)) {
            _handleVoiceCommand(cmd.type, body: cmd.body);
            return;
          }
        }

        final normalized = _normalizeDictation(raw);
        if (mounted) {
          setState(() {
            if (result.finalResult) {
              // Commit final segments into the base so pauses/restarts don't overwrite prior text.
              final committed = _postProcessFinalDictation(normalized);
              _dictationBaseText =
                  _composeDictation(_dictationBaseText, committed);
              _dictationSessionText = '';
              _chatController.text = _dictationBaseText;
              _clearSelection();
            } else {
              _dictationSessionText = normalized;
              _chatController.text =
                  _composeDictation(_dictationBaseText, _dictationSessionText);
            }
          });
        }
      },
      listenFor: const Duration(seconds: 60),
      pauseFor: const Duration(seconds: 6),
      partialResults: true,
      cancelOnError: true,
      listenMode: ListenMode.dictation,
    );
  }

  void _toggleListening() async {
    if (!_speechAvailable) {
      _addSystemMsg('Speech recognition not available');
      return;
    }

    if (_dictationArmed) {
      // Turn off dictation mode but keep whatever text exists.
      _dictationArmed = false;
      await _stopSpeechAndSuppressLateResults();
      return;
    }

    // Arm dictation mode (continuous, pause-friendly).
    _dictationArmed = true;
    await _startListeningSession();
  }

  Future<void> _sendMessage() async {
    await _stopSpeechAndSuppressLateResults();
    String text = _chatController.text.trim();
    if (text.isEmpty) return;

    if (!_aiDataConsentGiven) {
      await _showAiDataConsentDialog();
      if (!_aiDataConsentGiven) return;
    }

    if (_wsCh == null || _connectionStatus.contains("DISCONNECTED")) {
      // FIX-H
      _addSystemMsg("Link is dead. Reconnecting...");
      _connectToCortex();
      return;
    }

    if (kDebugMode) print(">>> SENDING: $text");
    _wsSend(jsonEncode({
      // FIX-H
      "type": "nate_query",
      "nate_query": text,
      "modality": "General"
    }));

    setState(() {
      _chatHistory.add("You: $text");
      _chatController.clear();
      _scrollToBottom();
    });
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      Future.delayed(const Duration(milliseconds: 100), () {
        _scrollController.animateTo(_scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Conversation Export Handler
  // ---------------------------------------------------------------------------
  void _handleExportReady(
      String content, String filename, String? suggestedDest) async {
    if (!mounted) return;

    final exportService = ConversationExportService();

    // Show the destination picker
    final destination = await ConversationExportService.showDestinationPicker(
      context,
      suggested: suggestedDest,
    );

    if (destination == null || !mounted) {
      // User dismissed the picker
      setState(() {
        _chatHistory.add("[SYSTEM]: Export cancelled.");
        _scrollToBottom();
      });
      return;
    }

    // Show a saving indicator
    setState(() {
      _chatHistory.add("[SYSTEM]: Saving to ${_destLabel(destination)}...");
      _scrollToBottom();
    });

    bool success = false;
    try {
      switch (destination) {
        case 'google_drive':
          success = await exportService.saveToGoogleDrive(content, filename);
          break;
        case 'onedrive':
          success = await exportService.saveToOneDrive(content, filename);
          break;
        case 'local':
          success = await exportService.saveToLocal(content, filename);
          break;
      }
    } catch (e) {
      debugPrint('[ExportHandler] Error: $e');
    }

    if (!mounted) return;

    setState(() {
      if (success) {
        _chatHistory.add("[SYSTEM]: Saved to ${_destLabel(destination)}!");
      } else {
        _chatHistory.add("[SYSTEM]: Could not save — please try again.");
      }
      _scrollToBottom();
    });

    // Notify backend that export was completed
    if (_wsCh != null) {
      // FIX-H
      _wsSend(jsonEncode({
        "type": "export_completed",
        "destination": destination,
        "success": success,
        "filename": filename,
      }));
    }

    // Show snackbar feedback
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(
          success
              ? 'Saved "$filename" to ${_destLabel(destination)}'
              : 'Export failed — please try again',
        ),
        backgroundColor:
            success ? const Color(0xFF00FF88) : const Color(0xFFEF4444),
        duration: const Duration(seconds: 3),
      ));
    }
  }

  String _destLabel(String dest) {
    switch (dest) {
      case 'google_drive':
        return 'Google Drive';
      case 'onedrive':
        return 'OneDrive';
      case 'local':
        return kIsWeb ? 'your computer' : 'your phone';
      default:
        return dest;
    }
  }

  String _normalizeDictation(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;

    final rules = <MapEntry<RegExp, String>>[
      MapEntry(RegExp(r'\bquestion mark\b', caseSensitive: false), '?'),
      MapEntry(RegExp(r'\bexclamation point\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation mark\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bfull stop\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bperiod\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bcomma\b', caseSensitive: false), ','),
      MapEntry(RegExp(r'\bcolon\b', caseSensitive: false), ':'),
      MapEntry(RegExp(r'\bsemicolon\b', caseSensitive: false), ';'),
      MapEntry(RegExp(r'\bat sign\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bat symbol\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bhashtag\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bpound sign\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bnumber sign\b', caseSensitive: false), '#'),
      // NOTE: `$` must be escaped in RegExp replacement strings.
      MapEntry(RegExp(r'\bdollar sign\b', caseSensitive: false), r'\$'),
      MapEntry(RegExp(r'\bpercent\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bpercent sign\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bampersand\b', caseSensitive: false), '&'),
      MapEntry(RegExp(r'\bunderscore\b', caseSensitive: false), '_'),
      MapEntry(RegExp(r'\bplus sign\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bequal sign\b', caseSensitive: false), '='),
      MapEntry(RegExp(r'\bless than\b', caseSensitive: false), '<'),
      MapEntry(RegExp(r'\bgreater than\b', caseSensitive: false), '>'),
      MapEntry(RegExp(r'\bopen parenthesis\b', caseSensitive: false), '('),
      MapEntry(RegExp(r'\bclose parenthesis\b', caseSensitive: false), ')'),
      MapEntry(RegExp(r'\bopen paren\b', caseSensitive: false), '('),
      MapEntry(RegExp(r'\bclose paren\b', caseSensitive: false), ')'),
      MapEntry(RegExp(r'\bopen bracket\b', caseSensitive: false), '['),
      MapEntry(RegExp(r'\bclose bracket\b', caseSensitive: false), ']'),
      MapEntry(RegExp(r'\bopen brace\b', caseSensitive: false), '{'),
      MapEntry(RegExp(r'\bclose brace\b', caseSensitive: false), '}'),
      MapEntry(RegExp(r'\bslash\b', caseSensitive: false), '/'),
      MapEntry(RegExp(r'\bforward slash\b', caseSensitive: false), '/'),
      MapEntry(RegExp(r'\bbackslash\b', caseSensitive: false), '\\\\'),
      MapEntry(RegExp(r'\bcaret\b', caseSensitive: false), '^'),
      MapEntry(RegExp(r'\btilde\b', caseSensitive: false), '~'),
      MapEntry(RegExp(r'\bnew line\b', caseSensitive: false), '\n'),
      MapEntry(RegExp(r'\bnew paragraph\b', caseSensitive: false), '\n\n'),

      // Ambiguous tokens: only insert when user explicitly says "insert/type/say".
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+dot\b', caseSensitive: false), '.'),
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+dash\b', caseSensitive: false), '-'),
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+hyphen\b', caseSensitive: false),
          '-'),
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+hash\b', caseSensitive: false), '#'),
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+plus\b', caseSensitive: false), '+'),
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+equals\b', caseSensitive: false),
          '='),
      MapEntry(RegExp(r'\b(?:insert|type|say)\s+quote\b', caseSensitive: false),
          '"'),
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+asterisk\b', caseSensitive: false),
          '*'),
      MapEntry(
          RegExp(r'\b(?:insert|type|say)\s+star\b', caseSensitive: false), '*'),
    ];
    for (final r in rules) {
      s = s.replaceAll(r.key, r.value);
    }

    // Dart `replaceAll` does NOT support `$1` capture substitution.
    // Use `replaceAllMapped` so punctuation is preserved.
    s = s.replaceAllMapped(RegExp(r'\s+([?.!,;:])'), (m) => m.group(1) ?? '');
    s = s.replaceAllMapped(
        RegExp(r'([?.!,;:])(?=\w)'), (m) => '${m.group(1) ?? ''} ');
    s = s.replaceAll(RegExp(r' {2,}'), ' ');
    return s;
  }

  void _showMetricsSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0F),
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        minChildSize: 0.4,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) => SingleChildScrollView(
          controller: scrollController,
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 40,
                  height: 4,
                  decoration: BoxDecoration(
                    color: Colors.grey[600],
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 20),
              const Text(
                "MY WELLNESS METRICS",
                style: TextStyle(
                  color: Color(0xFF00FFFF),
                  fontWeight: FontWeight.bold,
                  letterSpacing: 2,
                  fontSize: 16,
                ),
              ),
              const SizedBox(height: 20),

              // Current mood
              MoodIndicator(
                mood: _metrics['mood_current'] ?? 'neutral',
                trend: _metrics['mood_trend'],
                large: true,
              ),

              const SizedBox(height: 20),

              // Nevedal metrics
              NevedalMetricsGrid(metrics: _metrics),

              const SizedBox(height: 20),

              // Mood history
              MoodHistoryChart(moodHistory: _moodHistory, height: 150),

              const SizedBox(height: 20),

              // Session stats
              SessionStatsCard(
                totalSessions:
                    widget.currentUserProfile?['total_sessions_count'] ?? 0,
                breakthroughs: _metrics['breakthrough_count'] ?? 0,
                tokensUsed:
                    widget.currentUserProfile?['token_usage_month'] ?? 0,
                tokensRemaining:
                    widget.currentUserProfile?['token_balance'] ?? 10000,
              ),

              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }

  /// Check if user has TTS read-aloud access (Inner Chamber+ tiers)
  bool _canUseTtsReadAloud() {
    // Primary: backend-computed premium_features (authoritative)
    final premiumFeatures = widget.currentUserProfile?['premium_features'];
    if (premiumFeatures != null && premiumFeatures is Map) {
      return premiumFeatures['tts_read_aloud'] == true;
    }
    // Fallback: Inner Chamber and above get read-aloud
    final tier =
        (widget.currentUserProfile?['tier'] ?? '').toString().toUpperCase();
    final plan = (widget.currentUserProfile?['subscription_plan'] ?? '')
        .toString()
        .toUpperCase();
    const ttsEligible = {
      'STANDARD',
      'INNER_CHAMBER',
      'TOP_TIER',
      'SOVEREIGN_CIRCLE'
    };
    return ttsEligible.contains(tier) || ttsEligible.contains(plan);
  }

  /// Speak a Nate message aloud via Mini-TTS
  void _speakNateMessage(String text) {
    if (text.trim().isEmpty || _wsCh == null) return; // FIX-H
    _wsSend(json.encode({
      // FIX-H
      "type": "tts_speak",
      "text": text,
    }));
    debugPrint(
        "[NeuralInterfaceV2] Sent tts_speak: ${text.substring(0, text.length.clamp(0, 50))}...");
  }

  /// Check if user is eligible for Avatar Mode
  /// Uses backend-computed premium_features for integrity (family members inherit from head)
  bool _canUseAvatarMode() {
    // Primary: Use backend-computed premium_features (authoritative)
    final premiumFeatures = widget.currentUserProfile?['premium_features'];
    if (premiumFeatures != null && premiumFeatures is Map) {
      return premiumFeatures['avatar'] == true;
    }

    // Fallback: Check tier/subscription_plan directly (for backwards compatibility)
    final tier =
        (widget.currentUserProfile?['tier'] ?? '').toString().toUpperCase();
    final subscriptionPlan =
        (widget.currentUserProfile?['subscription_plan'] ?? '')
            .toString()
            .toUpperCase();

    const premiumTiers = {'TOP_TIER', 'SOVEREIGN_CIRCLE'};
    return premiumTiers.contains(tier) ||
        premiumTiers.contains(subscriptionPlan);
  }

  bool _canUseVault() =>
      AppConfig.ENABLE_SOVEREIGN_VAULT &&
      VaultEntitlement.canUseVault(widget.currentUserProfile);

  /// Toggle avatar mode on/off
  void _toggleAvatarMode(bool enabled) {
    if (!_canUseAvatarMode()) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content:
              Text('Avatar Mode is available for Sovereign Circle members'),
          backgroundColor: Color(0xFF8B0000),
        ),
      );
      return;
    }

    setState(() {
      _avatarModeEnabled = enabled;
      if (enabled) {
        _avatarState = AvatarVisualState(
          expression: AvatarExpression.neutral,
          gesture: AvatarGesture.none,
          environment: AvatarEnvironment.cozyStudy,
        );
      }
    });
  }

  /// Update avatar expression — GlbAvatarWidget rebuilds via setState
  void _updateAvatarExpression(AvatarExpression expression) {
    if (_avatarState.expression == expression) return;
    setState(() {
      _avatarState = _avatarState.copyWith(expression: expression);
    });
  }

  /// Determine Nate's avatar expression from two inputs:
  ///   1. Client mood (from the mood indicator / metrics) — Nate responds therapeutically
  ///   2. Nate's own message content — his words carry their own emotional weight
  ///
  /// 3 GLB model groups:
  ///   Neutral  — resting, attentive, thoughtful (baseline)
  ///   Soft     — warm, empathetic, calming, validating, curious (nurturing)
  ///   Intense  — proud, encouraging, sad, frustrated (strong emotion)
  void _updateAvatarFromSentiment(dynamic sentiment, String responseText) {
    final sentimentStr = (sentiment ?? 'neutral').toString().toLowerCase();
    final textLower = responseText.toLowerCase();
    final clientMood =
        (_metrics['mood_current'] ?? 'neutral').toString().toLowerCase();

    // --- Step 1: Detect Nate's own expression from his message content ---
    AvatarExpression? nateExpression;

    if (textLower.contains('proud of you') ||
        textLower.contains('great job') ||
        textLower.contains('wonderful') ||
        textLower.contains('amazing') ||
        textLower.contains('incredible') ||
        textLower.contains('that\'s huge')) {
      nateExpression = AvatarExpression.proud;
    } else if (textLower.contains('tell me more') ||
        textLower.contains('what happened') ||
        textLower.contains('how did') ||
        textLower.contains('can you describe') ||
        textLower.contains('what was that like') ||
        textLower.contains('i\'m curious')) {
      nateExpression = AvatarExpression.curious;
    } else if (textLower.contains('take a breath') ||
        textLower.contains('it\'s okay') ||
        textLower.contains('let\'s slow down') ||
        textLower.contains('you\'re safe') ||
        textLower.contains('ground yourself') ||
        textLower.contains('breathe')) {
      nateExpression = AvatarExpression.calming;
    } else if (textLower.contains('i hear you') ||
        textLower.contains('listening') ||
        textLower.contains('go on') ||
        textLower.contains('i\'m here')) {
      nateExpression = AvatarExpression.attentive;
    } else if (textLower.contains('i understand') ||
        textLower.contains('that sounds') ||
        textLower.contains('must be') ||
        textLower.contains('i can see') ||
        textLower.contains('that\'s really') ||
        textLower.contains('makes sense')) {
      nateExpression = AvatarExpression.empathetic;
    } else if (textLower.contains('sorry to hear') ||
        textLower.contains('that must be hard') ||
        textLower.contains('i\'m sorry') ||
        textLower.contains('loss') ||
        textLower.contains('grief') ||
        textLower.contains('hold space')) {
      nateExpression = AvatarExpression.sad;
    }

    // --- Step 2: If Nate's message didn't signal clearly, respond to client mood ---
    if (nateExpression == null) {
      if (sentimentStr.contains('happy') || sentimentStr.contains('joy')) {
        nateExpression = AvatarExpression.proud;
      } else if (sentimentStr.contains('sad') ||
          sentimentStr.contains('grief')) {
        nateExpression = AvatarExpression.empathetic;
      } else if (sentimentStr.contains('anxious') ||
          sentimentStr.contains('worried')) {
        nateExpression = AvatarExpression.calming;
      } else if (sentimentStr.contains('angry') ||
          sentimentStr.contains('frustrat')) {
        nateExpression = AvatarExpression.calming;
      } else if (sentimentStr.contains('empathy') ||
          sentimentStr.contains('compassion')) {
        nateExpression = AvatarExpression.empathetic;
      } else if (sentimentStr.contains('curious')) {
        nateExpression = AvatarExpression.curious;
      }
    }

    // --- Step 3: Factor in the client's UX mood icon for therapeutic response ---
    if (nateExpression == null) {
      switch (clientMood) {
        case 'sad':
        case 'down':
          nateExpression = AvatarExpression.empathetic;
          break;
        case 'anxious':
        case 'worried':
          nateExpression = AvatarExpression.calming;
          break;
        case 'angry':
        case 'frustrated':
          nateExpression = AvatarExpression.calming;
          break;
        case 'happy':
        case 'positive':
          nateExpression = AvatarExpression.warm;
          break;
        case 'calm':
        case 'peaceful':
          nateExpression = AvatarExpression.warm;
          break;
        default:
          nateExpression = AvatarExpression.warm;
      }
    }

    debugPrint(
        '[Avatar] ClientMood: $clientMood | Sentiment: $sentimentStr → Expression: ${nateExpression.toString().split('.').last}');
    _updateAvatarExpression(nateExpression);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _nevedal.dispose();
    _audioSub?.cancel();
    _talkingTimer?.cancel();
    _reconnectTimer?.cancel();
    _backoffResetTimer?.cancel();
    _recapTimer?.cancel();
    for (final t in _ttsDebounceByTurn.values) {
      t.cancel();
    }
    _ttsDebounceByTurn.clear();
    _latestNateTextByTurnForTts.clear();
    _turnIdToChatIndex.clear();
    _chatController.dispose();
    _scrollController.dispose();
    _tts.stop();
    _speech.stop();
    _cancelNeuralWsSubs(); // FIX-H hub: cancel only; cold: subs + socket
    if (_socket != null) _socket!.sink.close(); // FIX-H shared hub: skip close
    _socket = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.currentUserProfile?['name'] ?? "SUBJECT",
                style: const TextStyle(
                    fontFamily: "Courier",
                    color: Colors.cyanAccent,
                    fontSize: 16)),
            Text(_connectionStatus,
                style: TextStyle(
                    fontFamily: "Courier",
                    color: _connectionStatus.contains("ONLINE")
                        ? Colors.green
                        : Colors.red,
                    fontSize: 10)),
          ],
        ),
        backgroundColor: Colors.transparent,
        elevation: 0,
        actions: [
          // Avatar Mode Toggle (only visible to eligible users)
          if (_canUseAvatarMode())
            IconButton(
              icon: Icon(
                _avatarModeEnabled ? Icons.face : Icons.face_outlined,
                color: _avatarModeEnabled
                    ? const Color(0xFFFFD700)
                    : Colors.white54,
              ),
              tooltip:
                  _avatarModeEnabled ? 'Avatar Mode ON' : 'Avatar Mode OFF',
              onPressed: () => _toggleAvatarMode(!_avatarModeEnabled),
            ),
          // Family Sanctuary button
          IconButton(
            icon: const Icon(Icons.family_restroom, color: Colors.amber),
            onPressed: () async {
              // Close parent socket -- iOS Safari struggles with concurrent
              // WebSocket connections to the same origin for the same user
              _wsCh?.sink.close(); // FIX-H shared or owned channel
              await Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => FamilySanctuaryScreen(
                      profile: widget.currentUserProfile ?? {},
                      username: widget.username,
                      password: widget.password,
                    ),
                  ));
              // Reconnect when returning from Family Sanctuary
              if (mounted) _connectToCortex();
            },
            tooltip: "Family Sanctuary",
          ),
          // AI Modes button
          IconButton(
            icon: Icon(
              _activeAiMode != null
                  ? Icons.psychology
                  : Icons.psychology_outlined,
              color: _activeAiMode != null
                  ? const Color(0xFF9D4EDD)
                  : Colors.white54,
            ),
            onPressed: _showAiModePicker,
            tooltip: _activeAiMode != null
                ? 'AI Mode: ${_activeAiMode!.toUpperCase()}'
                : 'AI Modes',
          ),
          // Nudge badge button
          if (_pendingNudges.isNotEmpty)
            Stack(
              children: [
                IconButton(
                  icon: const Icon(Icons.notifications_active,
                      color: Color(0xFFC9A962)),
                  onPressed: _showNudgesSheet,
                  tooltip: 'Nate Nudges',
                ),
                Positioned(
                  right: 6,
                  top: 6,
                  child: Container(
                    padding: const EdgeInsets.all(3),
                    decoration: const BoxDecoration(
                        color: Colors.red, shape: BoxShape.circle),
                    child: Text('${_pendingNudges.length}',
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 9,
                            fontWeight: FontWeight.bold)),
                  ),
                ),
              ],
            ),
          // Metrics button
          IconButton(
            icon: const Icon(Icons.analytics, color: Colors.cyanAccent),
            onPressed: _showMetricsSheet,
            tooltip: "View Metrics",
          ),
          IconButton(
            icon: const Icon(Icons.menu_book, color: Color(0xFFC9A962)),
            onPressed: _openVocabularySheet,
            tooltip: "Custom Vocabulary",
          ),
          IconButton(
            icon: Icon(_isSpeaking ? Icons.stop_circle : Icons.volume_up,
                color: Colors.white70),
            onPressed: _isSpeaking
                ? _stopReading
                : () async {
                    await _unlockTtsOnce();
                    await _readBackDraft();
                  },
            tooltip: _isSpeaking ? "Stop reading" : "Read draft aloud",
          ),
          IconButton(
            icon: const Icon(Icons.settings, color: Color(0xFFC9A962)),
            tooltip: 'Settings',
            onPressed: () {
              Navigator.push<dynamic>(
                  context,
                  MaterialPageRoute(
                    builder: (_) => ClientSettingsScreen(
                      profile: _clientProfile(),
                      socket: _wsCh,
                      onLogout: () {
                        _wsCh?.sink.close(); // FIX-H
                      },
                    ),
                  )).then((result) {
                if (result is Map && result['profilePatch'] is Map && mounted) {
                  setState(() {
                    _profilePatchOverrides.addAll(
                      Map<String, dynamic>.from(result['profilePatch'] as Map),
                    );
                  });
                }
                if (mounted) _checkSseIntake();
                if (result is Map &&
                    result['askNateVault'] != null &&
                    mounted) {
                  final itemId = result['askNateVault'].toString();
                  _chatController.text =
                      '${_chatController.text}[Vault:$itemId] '.trim();
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'Vault item attached. Tap Send to ask Nate.',
                      ),
                      backgroundColor: Color(0xFFC9A962),
                      duration: Duration(seconds: 4),
                    ),
                  );
                  FocusScope.of(context).requestFocus(FocusNode());
                }
              });
            },
          ),
          IconButton(
              icon: const Icon(Icons.logout, color: Colors.red),
              onPressed: () {
                _wsCh?.sink.close(); // FIX-H
                Navigator.pushReplacement(context,
                    MaterialPageRoute(builder: (_) => const LobbyScreen()));
              })
        ],
      ),
      body: Column(
        children: [
          // Quick metrics bar at top
          if (_metrics.isNotEmpty)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              color: Colors.black.withOpacity(0.7),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _buildQuickStat(
                      "C", _metrics['C_emo'] ?? 0.5, const Color(0xFF00FFFF)),
                  _buildQuickStat(
                      "G", _metrics['GAP'] ?? 0.3, const Color(0xFF9D4EDD)),
                  _buildQuickStat(
                      "Q", _metrics['Quantum'] ?? 0.5, const Color(0xFFFFD700)),
                  MoodIndicator(mood: _metrics['mood_current'] ?? 'neutral'),
                ],
              ),
            ),
          // SSE Story Journey banner
          if (_sseIntakePending)
            GestureDetector(
              onTap: () async {
                await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => IntakeConversationScreen(
                        profileWithToken: widget.currentUserProfile ?? {},
                        onComplete: () => Navigator.pop(context),
                      ),
                    ));
                if (mounted) _checkSseIntake();
              },
              child: Container(
                margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                      colors: [Color(0xFF1A1A2E), Color(0xFF0A0A1A)]),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                      color: const Color(0xFFC9A962).withOpacity(0.4)),
                ),
                child: Row(children: [
                  const Icon(Icons.auto_stories,
                      color: Color(0xFFC9A962), size: 20),
                  const SizedBox(width: 10),
                  const Expanded(
                      child: Text('Begin Your Story Journey',
                          style: TextStyle(
                              color: Color(0xFFE8D5A3),
                              fontSize: 13,
                              fontWeight: FontWeight.w500))),
                  const Icon(Icons.arrow_forward_ios,
                      color: Color(0xFF8B7355), size: 14),
                ]),
              ),
            ),
          // Recap card — shown after login when journey data exists
          if (_recapData != null && !_recapDismissed && !_sseIntakePending)
            Container(
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF0A0A1A),
                borderRadius: BorderRadius.circular(12),
                border:
                    Border.all(color: const Color(0xFFC9A962).withOpacity(0.5)),
              ),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                        'Welcome back${_recapData!["user_name"] != null ? ", ${_recapData!["user_name"]}" : ""}.',
                        style: const TextStyle(
                            color: Color(0xFFE8D5A3),
                            fontSize: 14,
                            fontWeight: FontWeight.w600)),
                    const SizedBox(height: 6),
                    if (_recapData!["journey"] != null)
                      Text(
                          '\u{1F5FA} Journey: ${(_recapData!["journey"]["biome"] ?? "unknown").toString().replaceAll("_", " ")} — Panel ${_recapData!["journey"]["panel_count"] ?? 0}',
                          style: const TextStyle(
                              color: Colors.white70, fontSize: 12)),
                    if ((_recapData!["active_quests"] as List?)?.isNotEmpty ==
                        true)
                      Text(
                          '\u{2694} Quest: ${_recapData!["active_quests"][0]["goal"] ?? "Active"} (Day ${_recapData!["active_quests"][0]["days_active"] ?? 0})',
                          style: const TextStyle(
                              color: Colors.white70, fontSize: 12)),
                    if ((_recapData!["active_missions"] as List?)?.isNotEmpty ==
                        true)
                      Text(
                          '\u{1F91D} Mission: ${_recapData!["active_missions"][0]["relationship_target"] ?? "Active"} (Day ${_recapData!["active_missions"][0]["days_active"] ?? 0})',
                          style: const TextStyle(
                              color: Colors.white70, fontSize: 12)),
                    if (_recapData!["crystal_insight"] != null)
                      Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                              '\u{1F4A1} ${(_recapData!["crystal_insight"] as String).length > 80 ? (_recapData!["crystal_insight"] as String).substring(0, 80) + "..." : _recapData!["crystal_insight"]}',
                              style: const TextStyle(
                                  color: Color(0xFF4ECDC4),
                                  fontSize: 11,
                                  fontStyle: FontStyle.italic))),
                    const SizedBox(height: 8),
                    Wrap(spacing: 8, runSpacing: 4, children: [
                      _recapBtn('Continue Journey', () {
                        _dismissRecap();
                        _sendPresetMessage("Let's talk about my journey today");
                      }),
                      if ((_recapData!["active_quests"] as List?)?.isNotEmpty ==
                          true)
                        _recapBtn('Work on Quest', () {
                          _dismissRecap();
                          _sendPresetMessage(
                              "I want to work on my ${_recapData!["active_quests"][0]["goal"] ?? "quest"}");
                        }),
                      if ((_recapData!["active_quests"] as List?)?.isNotEmpty !=
                          true)
                        _recapBtn('New Quest', () {
                          _dismissRecap();
                          _showNewQuestDialog();
                        }),
                      if ((_recapData!["active_missions"] as List?)
                              ?.isNotEmpty ==
                          true)
                        _recapBtn('Talk About Mission', () {
                          _dismissRecap();
                          _sendPresetMessage(
                              "Let's talk about my mission with ${_recapData!["active_missions"][0]["relationship_target"] ?? "my relationship"}");
                        }),
                      _recapBtn('Just Chat', _dismissRecap),
                    ]),
                  ]),
            ),
          if ((widget.currentUserProfile?['subscription_status'] ?? '')
                  .toString()
                  .toUpperCase() ==
              'TRIAL_ACTIVE')
            TrialBannerWidget(userProfile: widget.currentUserProfile ?? {}),
          // Main content area - Background visual + Chat overlay
          Expanded(
            child: Stack(
              children: [
                // BACK LAYER: Visual (GLB 3D avatar or orb)
                Positioned.fill(
                  child: _avatarModeEnabled && _canUseAvatarMode()
                      ? GlbAvatarWidget(
                          expression: _avatarState.expression,
                          voiceState: _voiceState,
                          onTap: () => _toggleAvatarMode(false),
                        )
                      : VisualPersona(
                          isTalking: _isTalking,
                          isListening: _audio.isListening),
                ),
                // FRONT LAYER: Chat messages (with PointerInterceptor for web iframe)
                Positioned.fill(
                  child: _wrapWithPointerInterceptorIfNeeded(
                    GestureDetector(
                      onTap: () {
                        if (_isTextSelected) {
                          setState(() => _isTextSelected = false);
                        }
                      },
                      child: SelectionArea(
                        onSelectionChanged: (value) {
                          final selecting =
                              value != null && value.plainText.isNotEmpty;
                          if (selecting != _isTextSelected) {
                            setState(() => _isTextSelected = selecting);
                          }
                        },
                        child: ListView.builder(
                          controller: _scrollController,
                          physics: _isTextSelected
                              ? const NeverScrollableScrollPhysics()
                              : const ClampingScrollPhysics(),
                          itemCount: _chatHistory.length,
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          itemBuilder: (ctx, i) {
                            final msg = _chatHistory[i];
                            final isNate = msg.startsWith("Little Nate:");
                            final isYou = msg.startsWith("You:");
                            final isSystem = msg.startsWith("[SYSTEM]");
                            final textColor = isYou
                                ? Colors.grey.shade400
                                : (isSystem ? Colors.yellow : Colors.white);
                            final textWidget = Text(
                              msg,
                              style: TextStyle(
                                fontFamily: "Courier",
                                color: textColor,
                                fontSize: 14,
                                shadows: const [
                                  Shadow(
                                      color: Colors.black,
                                      blurRadius: 4,
                                      offset: Offset(1, 1)),
                                  Shadow(
                                      color: Colors.black,
                                      blurRadius: 8,
                                      offset: Offset(0, 0)),
                                ],
                              ),
                            );
                            final bool hasQuestSuggestion = isNate &&
                                !_dismissedSuggestions.contains(i) &&
                                msg.toLowerCase().contains('make this a quest');
                            final bool hasMissionSuggestion = isNate &&
                                !_dismissedSuggestions.contains(i) &&
                                msg
                                    .toLowerCase()
                                    .contains('could be a mission');
                            Widget suggestionRow = const SizedBox.shrink();
                            if (hasQuestSuggestion || hasMissionSuggestion) {
                              suggestionRow = Padding(
                                  padding:
                                      const EdgeInsets.only(top: 4, left: 20),
                                  child: Wrap(spacing: 8, children: [
                                    _recapBtn(
                                        hasQuestSuggestion
                                            ? 'Start Quest'
                                            : 'Start Mission', () {
                                      setState(
                                          () => _dismissedSuggestions.add(i));
                                      if (hasQuestSuggestion) {
                                        _createQuestFromContext();
                                      } else {
                                        _showNewMissionDialog();
                                      }
                                    }),
                                    _recapBtn(
                                        'Not right now',
                                        () => setState(() =>
                                            _dismissedSuggestions.add(i))),
                                  ]));
                            }
                            if (isNate && _canUseTtsReadAloud()) {
                              final nateText =
                                  msg.replaceFirst("Little Nate: ", "");
                              return Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Padding(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 20, vertical: 4),
                                      child: Row(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Expanded(child: textWidget),
                                          const SizedBox(width: 4),
                                          GestureDetector(
                                            onTap: () =>
                                                _speakNateMessage(nateText),
                                            child: Icon(
                                              _isTalking
                                                  ? Icons.volume_up
                                                  : Icons.volume_up_outlined,
                                              color: const Color(0xFFC9A962),
                                              size: 18,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                    suggestionRow,
                                  ]);
                            }
                            return Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Padding(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 20, vertical: 4),
                                    child: textWidget,
                                  ),
                                  suggestionRow,
                                ]);
                          },
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          // Draft preview (using ValueListenableBuilder to avoid full rebuilds)
          ValueListenableBuilder<TextEditingValue>(
            valueListenable: _chatController,
            builder: (context, value, child) {
              if (value.text.trim().isEmpty) return const SizedBox.shrink();
              return Container(
                width: double.infinity,
                margin: const EdgeInsets.symmetric(horizontal: 20, vertical: 6),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF0A0A0A),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: Colors.white.withOpacity(0.08)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.edit_note,
                            size: 16, color: Colors.white54),
                        const SizedBox(width: 8),
                        Text(
                          _dictationArmed ? 'Draft (dictating)' : 'Draft',
                          style: const TextStyle(
                              color: Colors.white54,
                              fontSize: 12,
                              fontWeight: FontWeight.w600),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 140),
                      child: SingleChildScrollView(
                        child: Text(
                          value.text,
                          style: const TextStyle(
                              color: Colors.white70,
                              fontSize: 14,
                              height: 1.25),
                        ),
                      ),
                    ),
                  ],
                ),
              );
            },
          ),
          // Upload progress (compact, above input)
          if (_uploadProgressState.isVisible)
            UploadProgressIndicator(
              state: _uploadProgressState,
              onCancel: () => setState(
                  () => _uploadProgressState = UploadProgressState.idle()),
              onDismiss: () => setState(
                  () => _uploadProgressState = UploadProgressState.idle()),
            ),
          // Input bar - always at bottom, never overlapped
          Container(
            color: const Color(0xFF050505),
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
            child: Row(
              children: [
                IconButton(
                  icon: Icon(
                    (_dictationArmed || _isListening)
                        ? Icons.mic
                        : Icons.mic_none,
                    color: _isListening
                        ? Colors.red
                        : (_dictationArmed
                            ? Colors.amber
                            : (_speechAvailable ? Colors.white : Colors.grey)),
                  ),
                  onPressed: _speechAvailable
                      ? () async {
                          await _unlockTtsOnce();
                          _toggleListening();
                        }
                      : null,
                  tooltip: !_speechAvailable
                      ? 'Speech not available'
                      : (_dictationArmed
                          ? 'Stop dictation'
                          : 'Speak your message'),
                ),
                if (AppConfig.ENABLE_SOVEREIGN_VAULT && _canUseVault()) ...[
                  const SizedBox(width: 4),
                  VaultAttachmentButton(
                    profile: widget.currentUserProfile,
                    socket: _wsCh,
                    onVaultItemSelected: (itemId) {
                      if (itemId != null && itemId.isNotEmpty) {
                        _chatController.text =
                            '${_chatController.text}[Vault:$itemId] '.trim();
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text(
                              'Vault item attached. Tap Send to ask Nate.',
                            ),
                            backgroundColor: Color(0xFFC9A962),
                            duration: Duration(seconds: 4),
                          ),
                        );
                      }
                    },
                    onUploadProgress: (s) =>
                        setState(() => _uploadProgressState = s),
                  ),
                ],
                const SizedBox(width: 10),
                Expanded(
                  child: TextField(
                    controller: _chatController,
                    style: const TextStyle(
                        color: Colors.white, fontFamily: "Courier"),
                    decoration: InputDecoration(
                        hintText: _isListening
                            ? "Listening..."
                            : (_dictationArmed
                                ? "Listening (paused)..."
                                : "Input..."),
                        filled: true,
                        fillColor: Colors.white10,
                        border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(30))),
                    readOnly: _isListening,
                    keyboardType: TextInputType.multiline,
                    minLines: 1,
                    maxLines: 4,
                    onSubmitted: (_) => _sendMessage(),
                  ),
                ),
                const SizedBox(width: 10),
                FloatingActionButton(
                    mini: true,
                    backgroundColor: Colors.cyan,
                    onPressed: _sendMessage,
                    child: const Icon(Icons.send, color: Colors.black))
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// Wraps widget with PointerInterceptor on web when 3D avatar is active
  Widget _wrapWithPointerInterceptorIfNeeded(Widget child) {
    if (kIsWeb && _avatarModeEnabled && _canUseAvatarMode()) {
      return PointerInterceptor(child: child);
    }
    return child;
  }

  Widget _buildQuickStat(String label, dynamic value, Color color) {
    final double v = _toDouble(value);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          "${(v * 100).toInt()}%",
          style: TextStyle(
              color: color,
              fontWeight: FontWeight.bold,
              fontSize: 14,
              fontFamily: 'Courier'),
        ),
        Text(label, style: const TextStyle(color: Colors.grey, fontSize: 9)),
      ],
    );
  }
}

// =============================================================================
// UPDATED COACH DASHBOARD - With client briefs and metrics
// Replace the existing CoachDashboardScreen class with this one
// =============================================================================

class _CoachDojoTabKeepAlive extends StatefulWidget {
  const _CoachDojoTabKeepAlive({required this.builder});

  final Widget Function() builder;

  @override
  State<_CoachDojoTabKeepAlive> createState() => _CoachDojoTabKeepAliveState();
}

class _CoachDojoTabKeepAliveState extends State<_CoachDojoTabKeepAlive>
    with AutomaticKeepAliveClientMixin {
  @override
  bool get wantKeepAlive => true;

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return widget.builder();
  }
}

class CoachDashboardScreenV2 extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final String username;
  final String password;

  const CoachDashboardScreenV2(
      {super.key,
      required this.currentUserProfile,
      required this.username,
      required this.password});

  @override
  _CoachDashboardScreenV2State createState() => _CoachDashboardScreenV2State();
}

class _CoachDashboardScreenV2State extends State<CoachDashboardScreenV2>
    with SingleTickerProviderStateMixin {
  WebSocketChannel? _socket;
  // Resolve dynamically so `/#/?ws=...` overrides apply without rebuilding.
  String get _serverUrl => defaultWsUrl;
  String get _apiBaseUrl => defaultApiBaseUrl;

  final StreamController<Map<String, dynamic>> _messageRelay =
      StreamController<Map<String, dynamic>>.broadcast();

  List<dynamic> _clients = [];
  List<dynamic> _schedule = [];
  Map<String, dynamic>? _selectedClientBrief;
  final Map<String, bool> _assistEnabledBySession = {};
  final Map<String, String> _sessionServiceMode =
      {}; // live_id -> green|yellow|blue|grey
  final ValueNotifier<List<Map<String, dynamic>>> _liveNotes =
      ValueNotifier<List<Map<String, dynamic>>>([]);
  final ValueNotifier<List<Map<String, dynamic>>> _liveObservations =
      ValueNotifier<List<Map<String, dynamic>>>([]);
  Map<String, dynamic>? _activeLiveSession;
  bool _liveSheetOpen = false;

  // Live session note dictation (speech_to_text — same package/pattern as coach_portal Ask Nate tab)
  final SpeechToText _liveNoteSpeech = SpeechToText();
  bool _liveNoteSpeechInited = false;
  bool _liveNoteSpeechAvailable = false;
  bool _liveNoteDictationArmed = false;
  bool _liveNoteListening = false;
  bool _liveNoteSttRestartScheduled = false;
  String _liveNoteDictationBase = '';
  String _liveNoteDictationSession = '';
  DateTime? _liveNoteSuppressUntil;
  TextEditingController? _liveNoteSttBoundController;
  VoidCallback? _liveSheetRebuild;

  String? _selectedFolderId; // "family:<id>" or "client:<id>"
  String? _selectedFamilyId;
  String? _selectedFolderLabel;
  List<Map<String, dynamic>> _selectedFolderClients = [];
  List<Map<String, dynamic>> _selectedFolderNotes = [];
  bool _notesLoading = false;
  bool _isLoading = true;
  String _statusMessage = "Initializing...";

  // Client filter/search state (shared across Clients, Insights, Briefings)
  String _clientFilterMode = 'ALL'; // ALL, CLIENTS, FAMILY, COACH_ONLY, COMPANY
  String _clientSearchQuery = '';
  final TextEditingController _clientSearchController = TextEditingController();

  // Classroom video upload state
  String? _classroomUploadedVideoId;
  String? _classroomUploadedVideoName;
  double _classroomUploadProgress = 0.0;
  bool _classroomUploading = false;
  Timer? _classroomVideoPollTimer;
  bool _classroomVideoPipelineActive = false;
  int _classroomVideoStageIndex = 0;

  /// Server-reported live stage (from pipeline_stage in classroom_sessions) while processing video.
  String? _classroomServerPipelineLabel;
  int? _classroomServerPipelineIndex;
  static const List<String> _classroomVideoStages = [
    "Extracting audio...",
    "Transcribing session...",
    "Analyzing voice patterns...",
    "Detecting key moments...",
    "Generating insights...",
  ];
  final TextEditingController _classroomCoachQueryController =
      TextEditingController();

  // Inbound coach requests from clients
  List<Map<String, dynamic>> _inboundRequests = [];

  // Pending bookings & Financial state
  List<Map<String, dynamic>> _pendingBookings = [];
  Map<String, dynamic> _financialData = {};
  bool _financialsLoading = false;
  final TextEditingController _coachFeeController = TextEditingController();

  // ===== AVAILABILITY / CALENDAR STATE (coach Schedule tab) =====
  // Recurring availability: list of {day_of_week:int, start_time:"HH:MM", end_time:"HH:MM"}
  List<Map<String, dynamic>> _myRecurring = [];
  // Blocked specific dates: list of {block_id, date:"YYYY-MM-DD", reason}
  List<Map<String, dynamic>> _myBlocks = [];
  bool _myAvailabilityLoaded = false;
  // Calendar navigation
  DateTime _calMonth = DateTime(DateTime.now().year, DateTime.now().month, 1);
  DateTime? _calSelectedDay;
  CalendarView _calView = CalendarView.month;
  DateTime _calFocusedDate = DateTime.now();

  /// Correlates `coach_create_consultation` WebSocket replies with the open dialog.
  Completer<Map<String, dynamic>>? _consultationCreateCompleter;
  String? _consultationCreateRequestId;

  // Payout / Stripe Connect state
  Map<String, dynamic> _connectStatus = {};
  bool _connectLoading = false;
  bool _connectOnboarding = false;

  // DOJO Subscription management state
  Map<String, dynamic> _dojoSubscriptions = {};
  List<String> _activeDojos = [];
  int _dojoDiscountPct = 0;
  double _dojoMonthlyPrice = 0.0;
  bool _dojoSubsLoading = false;

  // Tab menu button key for positioning the popup menu
  final GlobalKey _tabMenuButtonKey = GlobalKey();

  late TabController _tabController;
  final TextEditingController _dojoResponseController = TextEditingController();
  final TextEditingController _dojoPromptController = TextEditingController();
  final ScrollController _dojoScrollController = ScrollController();

  // Classroom state
  final TextEditingController _classroomTranscriptController =
      TextEditingController();
  final TextEditingController _classroomLearningFocusController =
      TextEditingController();
  final TextEditingController _classroomZoomIdController =
      TextEditingController();
  bool _classroomAnalyzing = false;
  Map<String, dynamic>? _classroomAnalysis;
  List<Map<String, dynamic>> _classroomHistory = [];
  List<Map<String, dynamic>> _classroomSessions = [];
  Map<String, dynamic>? _classroomProgress;
  String? _classroomSelectedSessionId;
  String _classroomFocusArea = "general therapeutic skills";
  DateTime? _classroomDueDate;
  Map<String, TextEditingController> _classroomReflectionControllers = {};

  // Live Analysis state
  bool _classroomLiveAnalyzing = false;
  Map<String, dynamic>? _classroomRecordingStatus;
  Map<String, dynamic>? _classroomMeetingStatus;
  Map<String, dynamic>? _classroomLiveAnalysis;
  bool _classroomCheckingRecording = false;

  final List<Map<String, dynamic>> _dojoLog = [];
  final Set<String> _dojoSelectedPersonas = {
    'HOSTILE',
  };
  List<String> _dojoPersonaQueue = ['HOSTILE'];
  int _dojoPersonaIndex = 0;
  String? _dojoSessionId;
  String? _dojoActivePersona;
  String? _dojoAdversarialPrompt;
  Map<String, dynamic>? _dojoLastAnalysis;
  bool _dojoBusy = false;
  String? _dojoError;

  // Consultation timer state
  String? _activeConsultationId;
  int _consultationRemainingSeconds = 0;
  String? _consultationWarningMessage;

  // Auth state for WebView
  String? _authToken;

  // Dojo WebView (hybrid approach - loads web page for easy updates)
  WebViewController? _dojoWebViewController;
  bool _dojoWebViewLoading = true;
  bool _dojoWebViewReady = false;
  bool _useDojoWebView = !kIsWeb; // Use WebView on mobile, native on web
  String? _coachHardwareId;

  // Insights chat state
  final List<Map<String, String>> _insightsChatMessages = [];
  final TextEditingController _insightsChatController = TextEditingController();
  bool _insightsChatLoading = false;
  final ScrollController _insightsChatScrollController = ScrollController();
  Map<String, dynamic>? _lastNevedalReport;

  // Coach override protocol (Thera-World calibration) — Insights tab
  String _coachOverrideClientId = '';
  Map<String, dynamic> _coachOverrideRow = {};
  List<Map<String, dynamic>> _coachOverrideHistory = [];
  List<String> _coachOverrideAllowedDomains = const [
    'clinical',
    'coaching',
    'family_systems',
    'crisis',
    'mindfulness',
    'boundaries',
    'trauma_informed',
    'attachment',
    'general',
    'cbt_techniques',
    'motivational',
  ];

  // Assistant Coaches tab state
  List<Map<String, dynamic>> _assistantMetrics = [];
  bool _assistantsTabLoading = false;
  String? _expandedAssistant;
  List<Map<String, dynamic>> _expandedAssistantClients = [];
  bool _expandedClientsLoading = false;
  final List<Map<String, String>> _assistantChatMessages = [];
  final TextEditingController _assistantChatController =
      TextEditingController();
  bool _assistantChatLoading = false;
  final ScrollController _assistantChatScrollController = ScrollController();

  // WebSocket reconnect state
  int _wsReconnectAttempts = 0;
  Timer? _wsReconnectTimer;
  VoidCallback? _dojoBackUnregister;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 10, vsync: this);
    _tabController.addListener(() {
      if (_tabController.indexIsChanging) return;
      if (_tabController.index == 1) {
        _emitFetchCoachCalendar();
      }
      if (_tabController.index == 9 &&
          _assistantMetrics.isEmpty &&
          !_assistantsTabLoading) {
        _loadAssistantMetrics();
      }
    });
    _connectToBridge();
    if (kIsWeb) {
      _dojoBackUnregister = registerDojoBackListener(() {
        if (!mounted) return;
        if (_tabController.index == 4) {
          _tabController.animateTo(0);
        }
      });
    }
  }

  void _connectToBridge() {
    _debugLog(">>> COACH DASHBOARD: WS URL = $_serverUrl");
    setState(() => _statusMessage = "Connecting to HQ...\n$_serverUrl");

    try {
      _socket?.sink.close();
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));

      // FIX-H: NOT ClientWsHub — static hub is client-lobby/Neural V2/Schedule handoff only.
      // Coach `login_request` must stay its own socket or it would overwrite client channel on same isolate.
      // On Flutter web, websocket failures can surface as unhandled async errors unless
      // we provide an explicit onError handler.
      _socket!.stream.listen(
        _handleSocketMessage,
        onError: (e) {
          _debugLog("Coach Socket Error: $e");
          if (mounted)
            setState(() {
              _statusMessage = "Connection Failed\n$_serverUrl";
              _classroomAnalyzing = false;
              _classroomLiveAnalyzing = false;
            });
          _scheduleWsReconnect();
        },
        onDone: () {
          _debugLog("Coach Socket Closed");
          if (mounted)
            setState(() {
              _statusMessage = "Disconnected — reconnecting...\n$_serverUrl";
              _classroomAnalyzing = false;
              _classroomLiveAnalyzing = false;
            });
          _scheduleWsReconnect();
        },
        cancelOnError: true,
      );

      _debugLog(">>> COACH DASHBOARD: Sending Login...");
      _socket!.sink.add(jsonEncode({
        "type": "login_request",
        "username": widget.username,
        "password": widget.password,
        "expected_role": "COACH"
      }));
    } catch (e) {
      _debugLog("Fatal Connection Error: $e");
    }
  }

  void _scheduleWsReconnect() {
    _wsReconnectTimer?.cancel();
    final attempt = _wsReconnectAttempts.clamp(0, 10);
    final baseMs = (1000 * (1 << attempt)).clamp(1000, 30000);
    final jitterMs =
        (baseMs * 0.2 * (DateTime.now().millisecondsSinceEpoch % 100) / 100)
            .toInt();
    _wsReconnectAttempts++;
    _wsReconnectTimer = Timer(Duration(milliseconds: baseMs + jitterMs), () {
      if (!mounted) return;
      _debugLog(
          "Coach WS reconnect attempt $_wsReconnectAttempts (delay ${baseMs + jitterMs}ms)");
      _connectToBridge();
    });
  }

  void _refreshDojoQueue() {
    if (_dojoSelectedPersonas.isEmpty) {
      _dojoSelectedPersonas.add('HOSTILE');
    }
    _dojoPersonaQueue = _dojoSelectedPersonas.toList();
    _dojoPersonaQueue.sort();
    if (_dojoPersonaIndex >= _dojoPersonaQueue.length) {
      _dojoPersonaIndex = 0;
    }
  }

  String _currentDojoPersona() {
    if (_dojoPersonaQueue.isEmpty) return 'HOSTILE';
    return _dojoPersonaQueue[
        _dojoPersonaIndex.clamp(0, _dojoPersonaQueue.length - 1)];
  }

  void _startDojoSession() {
    if (_socket == null) return;
    _refreshDojoQueue();
    final persona = _currentDojoPersona();
    setState(() {
      _dojoBusy = true;
      _dojoError = null;
      _dojoActivePersona = persona;
    });
    _socket?.sink.add(jsonEncode({
      "type": "dojo_start",
      "persona": persona,
    }));
  }

  void _endDojoSession({bool clearPrompt = true}) {
    if (_socket == null) return;
    _socket?.sink.add(jsonEncode({
      "type": "dojo_end",
    }));
    if (clearPrompt) {
      setState(() {
        _dojoAdversarialPrompt = null;
        _dojoSessionId = null;
      });
    }
  }

  void _nextDojoPersona() {
    if (_dojoPersonaQueue.isEmpty) return;
    _dojoPersonaIndex = (_dojoPersonaIndex + 1) % _dojoPersonaQueue.length;
    _endDojoSession(clearPrompt: true);
    _startDojoSession();
  }

  void _sendDojoTest() {
    final prompt = (_dojoAdversarialPrompt ?? '').trim();
    final response = _dojoResponseController.text.trim();
    if (prompt.isEmpty || response.isEmpty) return;
    _socket?.sink.add(jsonEncode({
      "type": "dojo_test_message",
      "user_message": prompt,
      "nate_response": response,
    }));
    setState(() {
      _dojoLog.add({
        "type": "response",
        "persona": _dojoActivePersona,
        "text": response,
      });
      _dojoResponseController.clear();
    });
  }

  void _shareDojoLearning(Map<String, dynamic> analysis) {
    if (_socket == null) return;
    final persona = (_dojoActivePersona ?? '').trim();
    final prompt = (_dojoAdversarialPrompt ?? '').trim();
    String lastResponse = '';
    for (final raw in _dojoLog.reversed) {
      if (raw is! Map) continue;
      final m = Map<String, dynamic>.from(raw);
      if ((m['type'] ?? '').toString() == 'response') {
        lastResponse = (m['text'] ?? '').toString().trim();
        if (lastResponse.isNotEmpty) break;
      }
    }

    if (prompt.isEmpty && lastResponse.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Nothing to share yet.")),
      );
      return;
    }

    _socket?.sink.add(jsonEncode({
      "type": "dojo_share_learning",
      "session_id": _dojoSessionId ?? "",
      "persona": persona.isEmpty ? "HOSTILE" : persona,
      "prompt": prompt,
      "coach_response": lastResponse,
      "analysis": analysis,
    }));
  }

  void _showConnectionInfo() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: const Text("Connection",
            style: TextStyle(color: Color(0xFF00F5D4))),
        content: SelectableText(
          _serverUrl,
          style: const TextStyle(
              color: Colors.white, fontFamily: 'Courier', fontSize: 12),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child:
                const Text("Close", style: TextStyle(color: Color(0xFFFFD700))),
          ),
        ],
      ),
    );
  }

  /// Sends visible calendar month so bridge PG merge returns sessions for May/June/etc.
  void _emitFetchCoachCalendar() {
    if (_socket == null) return;
    _socket!.sink.add(jsonEncode({
      "type": "fetch_coach_calendar",
      "month": _calMonth.month,
      "year": _calMonth.year,
    }));
  }

  void _fetchDashboard() {
    _socket?.sink.add(jsonEncode({"type": "coach_get_clients"}));
    _emitFetchCoachCalendar();
    _socket?.sink.add(jsonEncode({"type": "coach_get_inbound_requests"}));
    _socket?.sink.add(jsonEncode({"type": "coach_get_my_availability"}));
    _requestPendingBookings();
    _requestFinancials();
    _loadConnectStatus();
    _requestDojoSubscriptions();
    // Classroom: Fetch sessions and progress for the Classroom tab
    _requestClassroomSessions();
    _requestClassroomProgress();
    _loadAssistantMetrics();
  }

  void _refreshMyAvailability() {
    _socket?.sink.add(jsonEncode({"type": "coach_get_my_availability"}));
  }

  Map<String, String> _restHeaders({bool json = true}) {
    final h = <String, String>{};
    if (json) h['Content-Type'] = 'application/json';
    final tok =
        _authToken ?? widget.currentUserProfile['token']?.toString() ?? '';
    if (tok.isNotEmpty) h['Authorization'] = 'Bearer $tok';
    return h;
  }

  Uri _apiUri(String path, {Map<String, String>? query}) {
    final base = _apiBaseUrl.replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base$path');
    if (query == null || query.isEmpty) return uri;
    return uri.replace(queryParameters: {...uri.queryParameters, ...query});
  }

  Uri _scheduleSessionEndpoint() => _apiUri('/api/sessions/schedule');

  Uri _sessionZoomDeleteEndpoint(String sessionId) =>
      _apiUri('/api/sessions/$sessionId/zoom/delete');

  Uri _sessionZoomArchiveTranscriptEndpoint(String sessionId) => _apiUri(
        '/api/sessions/$sessionId/zoom/archive_transcript',
        query: const {"delete_recordings": "true", "delete_meeting": "false"},
      );

  Uri _sessionZoomRecordingStatusEndpoint(String sessionId) => _apiUri(
        '/api/sessions/$sessionId/zoom/recording_status',
      );

  Future<Map<String, dynamic>?> _checkRecordingStatus(String sessionId) async {
    try {
      final resp = await http.get(
          _sessionZoomRecordingStatusEndpoint(sessionId),
          headers: _restHeaders());
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw Exception("HTTP ${resp.statusCode}: ${resp.body}");
      }
      return jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Status check failed: $e")),
        );
      }
      return null;
    }
  }

  Future<void> _showRecordingStatus(String sessionId) async {
    // Show loading indicator
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => const AlertDialog(
        backgroundColor: Color(0xFF0A0A0F),
        content: Row(
          children: [
            CircularProgressIndicator(color: Color(0xFFFFD700)),
            SizedBox(width: 20),
            Text("Checking recording status...",
                style: TextStyle(color: Colors.white70)),
          ],
        ),
      ),
    );

    final status = await _checkRecordingStatus(sessionId);
    if (!mounted) return;
    Navigator.of(context).pop(); // Close loading dialog

    if (status == null) return;

    final statusValue = status['status'] ?? 'unknown';
    final message = status['message'] ?? 'Unknown status';
    final canArchive = status['can_archive'] ?? false;
    final hasTranscript = status['has_transcript'] ?? false;
    final alreadyArchived = status['already_archived'] ?? false;
    final estimatedWait = status['estimated_wait_minutes'] ?? 0;

    Color statusColor;
    IconData statusIcon;

    if (alreadyArchived) {
      statusColor = Colors.green;
      statusIcon = Icons.check_circle;
    } else if (canArchive) {
      statusColor = const Color(0xFF00F5D4);
      statusIcon = Icons.cloud_download;
    } else if (statusValue == 'processing') {
      statusColor = Colors.orange;
      statusIcon = Icons.hourglass_top;
    } else if (statusValue == 'recording') {
      statusColor = Colors.red;
      statusIcon = Icons.fiber_manual_record;
    } else {
      statusColor = Colors.grey;
      statusIcon = Icons.warning;
    }

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: Row(
          children: [
            Icon(statusIcon, color: statusColor, size: 28),
            const SizedBox(width: 10),
            Text("Recording Status", style: TextStyle(color: statusColor)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(message, style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 16),
            if (!alreadyArchived) ...[
              _buildStatusRow("Status", statusValue.toUpperCase(), statusColor),
              _buildStatusRow(
                  "Transcript Available",
                  hasTranscript ? "Yes" : "No",
                  hasTranscript ? Colors.green : Colors.red),
              _buildStatusRow("Ready to Archive", canArchive ? "Yes" : "No",
                  canArchive ? Colors.green : Colors.orange),
              if (estimatedWait > 0)
                _buildStatusRow(
                    "Est. Wait", "$estimatedWait minutes", Colors.orange),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Close", style: TextStyle(color: Colors.grey)),
          ),
          if (canArchive && !alreadyArchived)
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFFFD700),
                foregroundColor: Colors.black,
              ),
              icon: const Icon(Icons.archive),
              label: const Text("Archive Now"),
              onPressed: () {
                Navigator.pop(ctx);
                _archiveZoomTranscriptForSession(sessionId);
              },
            ),
        ],
      ),
    );
  }

  Widget _buildStatusRow(String label, String value, Color valueColor) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.grey)),
          Text(value,
              style: TextStyle(color: valueColor, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  Future<void> _deleteZoomMeetingForSession(String sessionId) async {
    try {
      final resp = await http.post(_sessionZoomDeleteEndpoint(sessionId),
          headers: _restHeaders());
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw Exception("HTTP ${resp.statusCode}: ${resp.body}");
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text("Zoom meeting deleted")));
      }
      _emitFetchCoachCalendar();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text("Delete Zoom failed: $e")));
      }
    }
  }

  Future<void> _deleteSessionPermanently(String sessionId) async {
    try {
      final uri =
          _apiUri('/api/sessions/$sessionId', query: {"hard_delete": "true"});
      final resp = await http.delete(uri, headers: _restHeaders());
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw Exception("HTTP ${resp.statusCode}: ${resp.body}");
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Session deleted"), backgroundColor: Colors.green),
        );
      }
      // Refresh the schedule
      _emitFetchCoachCalendar();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text("Delete session failed: $e"),
              backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _archiveZoomTranscriptForSession(String sessionId) async {
    try {
      final resp = await http.post(
          _sessionZoomArchiveTranscriptEndpoint(sessionId),
          headers: _restHeaders());
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw Exception("HTTP ${resp.statusCode}: ${resp.body}");
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Transcript archived; recordings cleaned up")));
      }
      _emitFetchCoachCalendar();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text("Archive transcript failed: $e")));
      }
    }
  }

  Future<void> _resendSessionLink(String sessionId) async {
    try {
      final uri = _apiUri('/api/sessions/$sessionId/resend-link');
      final resp = await http.post(uri, headers: _restHeaders());
      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw Exception("HTTP ${resp.statusCode}: ${resp.body}");
      }
      final body = jsonDecode(resp.body) as Map<String, dynamic>;
      final sent = body['sent'] == true;
      final channels =
          (body['notification']?['channels'] as List?)?.join(', ') ?? '';
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(sent
              ? "Zoom link sent ($channels)"
              : (body['message'] ?? 'No deliverable channels')),
          backgroundColor: sent ? Colors.green : Colors.orange,
        ));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text("Resend link failed: $e"),
              backgroundColor: Colors.red),
        );
      }
    }
  }

  Future<void> _scheduleSessionViaApi({
    required String clientId,
    required String clientName,
    required String coachId,
    required DateTime scheduledStartLocal,
    required int durationMinutes,
    String familyId = "",
    String sessionType = "COACH",
    String notes = "",
    bool disableRecording = false,
  }) async {
    final stUtc = scheduledStartLocal.toUtc();
    final enUtc = stUtc.add(Duration(minutes: durationMinutes));

    final payload = <String, dynamic>{
      "client_id": clientId,
      "coach_id": coachId,
      "family_id": familyId,
      "client_name": clientName,
      "scheduled_start": stUtc.toIso8601String(),
      "scheduled_end": enUtc.toIso8601String(),
      "session_type": sessionType,
      "notes": notes,
      "zoom_link": "",
      "disable_recording": disableRecording,
    };

    try {
      final resp = await http.post(
        _scheduleSessionEndpoint(),
        headers: _restHeaders(),
        body: jsonEncode(payload),
      );

      if (resp.statusCode < 200 || resp.statusCode >= 300) {
        throw Exception("HTTP ${resp.statusCode}: ${resp.body}");
      }

      final decoded = jsonDecode(resp.body);
      final zoomError =
          (decoded is Map) ? (decoded["zoom_error"]?.toString() ?? "") : "";

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(zoomError.isNotEmpty
                  ? "Scheduled (Zoom error: $zoomError)"
                  : "Session scheduled")),
        );
      }

      // Refresh schedule view immediately.
      _emitFetchCoachCalendar();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Schedule failed: $e")),
        );
      }
    }
  }

  /// External consultee — WebSocket `coach_create_consultation` (bridge + Zoom + email).
  Future<void> _submitConsultationFromDialog({
    required BuildContext dialogContext,
    required TextEditingController emailCtrl,
    required TextEditingController nameCtrl,
    required TextEditingController subjectCtrl,
    required DateTime startLocal,
    required int durationMinutes,
    required bool disableRecording,
  }) async {
    void showCoachSnack(String msg) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    }

    if (_socket == null) {
      showCoachSnack("Not connected — sign in again.");
      return;
    }
    final reqId = DateTime.now().millisecondsSinceEpoch.toString();
    _consultationCreateRequestId = reqId;
    _consultationCreateCompleter = Completer<Map<String, dynamic>>();

    final stUtc = startLocal.toUtc();
    _socket!.sink.add(jsonEncode({
      "type": "coach_create_consultation",
      "request_id": reqId,
      "consultee_email": emailCtrl.text.trim(),
      "consultee_name": nameCtrl.text.trim(),
      "subject": subjectCtrl.text.trim(),
      "scheduled_start": stUtc.toIso8601String(),
      "duration_minutes": durationMinutes,
      "disable_recording": disableRecording,
    }));

    try {
      final data = await _consultationCreateCompleter!.future.timeout(
        const Duration(seconds: 90),
        onTimeout: () => throw TimeoutException("consultation"),
      );
      if (!dialogContext.mounted) return;
      Navigator.of(dialogContext).pop();
      _emitFetchCoachCalendar();
      if (!mounted) return;
      final link = data["zoom_link"]?.toString() ?? "";
      final host = data["zoom_host_url"]?.toString() ?? "";
      final buf = StringBuffer("Consultation created.");
      if (link.isNotEmpty) {
        buf.write("\n\nGuest Zoom:\n$link");
      }
      if (host.isNotEmpty) {
        buf.write("\n\nHost Zoom:\n$host");
      }
      buf.write(
          "\n\nConfirmation emails are sent when the server is configured.");
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          backgroundColor: const Color(0xFF1A1A2E),
          duration: const Duration(seconds: 14),
          content: Text(
            buf.toString(),
            style: const TextStyle(color: Colors.white, fontSize: 12),
          ),
        ),
      );
    } on TimeoutException {
      showCoachSnack(
          "Consultation request timed out — check Schedule tab or try again.");
    } catch (e) {
      showCoachSnack("Consultation failed: $e");
    } finally {
      _consultationCreateCompleter = null;
      _consultationCreateRequestId = null;
    }
  }

  Future<void> _openCreateSessionDialog() async {
    final coachId = (widget.currentUserProfile["hardware_id"] ??
            widget.currentUserProfile["coach_id"] ??
            "")
        .toString();
    if (coachId.trim().isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Missing coach_id in profile")),
        );
      }
      return;
    }

    // Build full client list with all grouping fields
    final allClients = <Map<String, String>>[];
    for (final raw in _clients) {
      if (raw is! Map) continue;
      final c = Map<String, dynamic>.from(raw);
      final id = (c["hardware_id"] ?? c["client_id"] ?? c["id"] ?? "")
          .toString()
          .trim();
      if (id.isEmpty) continue;
      final name = (c["name"] ?? c["client_name"] ?? id).toString().trim();
      allClients.add({
        "id": id,
        "name": name,
        "family_id": (c["family_id"] ?? "").toString().trim(),
        "group_id": (c["group_id"] ?? "").toString().trim(),
        "company_id": (c["company_id"] ?? "").toString().trim(),
        "company_name": (c["company_name"] ?? "").toString().trim(),
      });
    }

    // Derive unique IDs for secondary dropdowns
    final familyIds = allClients
        .map((c) => c["family_id"]!)
        .where((f) => f.isNotEmpty)
        .toSet()
        .toList()
      ..sort();
    final groupIds = allClients
        .map((c) => c["group_id"]!)
        .where((g) => g.isNotEmpty)
        .toSet()
        .toList()
      ..sort();
    final companyMap = <String, String>{};
    for (final c in allClients) {
      final cid = c["company_id"]!;
      if (cid.isNotEmpty)
        companyMap[cid] =
            c["company_name"]!.isNotEmpty ? c["company_name"]! : cid;
    }
    final companyIds = companyMap.keys.toList()..sort();

    // Active assistant coaches for COACH type
    final activeAssistants =
        _assistantMetrics.where((a) => a['status'] == 'active').toList();

    // CONSULTATION sessions do not require roster clients or assistants.
    if (allClients.isEmpty && activeAssistants.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
                "No clients or assistants on file — you can still schedule a CONSULTATION."),
            duration: Duration(seconds: 4),
          ),
        );
      }
    }

    String sessionType = "CLIENT";
    String selectedSecondaryId = "";
    String selectedClientId =
        allClients.isNotEmpty ? allClients.first["id"]! : "";
    String selectedClientName =
        allClients.isNotEmpty ? allClients.first["name"]! : "";
    DateTime startLocal = DateTime.now().add(const Duration(minutes: 10));
    int durationMinutes = 50;
    String notes = "";
    bool disableRecording = false;
    bool consultationSubmitting = false;
    final consulteeEmailCtrl = TextEditingController();
    final consulteeNameCtrl = TextEditingController();
    final consulteeSubjectCtrl = TextEditingController();

    bool consulteeEmailValid(String e) {
      final t = e.trim();
      if (t.isEmpty || !t.contains("@")) return false;
      return RegExp(r'^[\w.+-]+@[\w.-]+\.\w{2,}$').hasMatch(t);
    }

    // Returns the visible entries for the person/client dropdown based on current type + secondary filter
    List<Map<String, String>> _visibleEntries(String type, String secId) {
      switch (type) {
        case "CONSULTATION":
          return [];
        case "COACH":
          return activeAssistants
              .map((a) => {
                    "id": (a["assistant_id"] ?? a["hardware_id"] ?? "")
                        .toString(),
                    "name":
                        (a["display_name"] ?? a["username"] ?? "").toString(),
                  })
              .where((e) => e["id"]!.isNotEmpty)
              .toList();
        case "FAMILY":
          if (secId.isEmpty) return allClients;
          return allClients.where((c) => c["family_id"] == secId).toList();
        case "GROUP":
          if (secId.isEmpty) return allClients;
          return allClients.where((c) => c["group_id"] == secId).toList();
        case "CORPORATE":
          if (secId.isEmpty) return allClients;
          return allClients.where((c) => c["company_id"] == secId).toList();
        default:
          return allClients;
      }
    }

    await showDialog(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setLocal) {
            final visibleList =
                _visibleEntries(sessionType, selectedSecondaryId);
            final bool hasEntries = visibleList.isNotEmpty;
            // CONSULTATION: keep Create tappable; validate on submit (avoids web autofill / paste
            // skipping onChanged so the button stays wrongly disabled).
            final bool canCreateSession =
                sessionType == "CONSULTATION" ? true : hasEntries;
            final bool createButtonEnabled =
                canCreateSession && !consultationSubmitting;
            if (hasEntries &&
                !visibleList.any((e) => e["id"] == selectedClientId)) {
              selectedClientId = visibleList.first["id"]!;
              selectedClientName = visibleList.first["name"]!;
            }

            Future<void> pickDateTime() async {
              final pickedDate = await showDatePicker(
                context: ctx,
                initialDate: startLocal,
                firstDate: DateTime.now().subtract(const Duration(days: 1)),
                lastDate: DateTime.now().add(const Duration(days: 365)),
              );
              if (pickedDate == null) return;
              final pickedTime = await showTimePicker(
                context: ctx,
                initialTime: TimeOfDay.fromDateTime(startLocal),
              );
              if (pickedTime == null) return;
              setLocal(() {
                startLocal = DateTime(
                  pickedDate.year,
                  pickedDate.month,
                  pickedDate.day,
                  pickedTime.hour,
                  pickedTime.minute,
                );
              });
            }

            // Build the secondary dropdown (Family ID / Group ID / Company) based on session type
            Widget? secondaryDropdown;
            if (sessionType == "FAMILY" && familyIds.isNotEmpty) {
              secondaryDropdown = DropdownButtonFormField<String>(
                key: const ValueKey("family_dd"),
                value: selectedSecondaryId.isNotEmpty &&
                        familyIds.contains(selectedSecondaryId)
                    ? selectedSecondaryId
                    : null,
                dropdownColor: const Color(0xFF111118),
                hint: const Text("All families",
                    style: TextStyle(color: Colors.white38)),
                items: familyIds
                    .map((f) => DropdownMenuItem<String>(
                        value: f,
                        child: Text(f,
                            style: const TextStyle(color: Colors.white))))
                    .toList(),
                onChanged: (v) => setLocal(() {
                  selectedSecondaryId = v ?? "";
                  selectedClientId = "";
                  selectedClientName = "";
                }),
                decoration: InputDecoration(
                  labelText: "Family ID",
                  labelStyle: const TextStyle(color: Colors.white70),
                  filled: true,
                  fillColor: Colors.white.withOpacity(0.06),
                  border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10)),
                ),
              );
            } else if (sessionType == "GROUP" && groupIds.isNotEmpty) {
              secondaryDropdown = DropdownButtonFormField<String>(
                key: const ValueKey("group_dd"),
                value: selectedSecondaryId.isNotEmpty &&
                        groupIds.contains(selectedSecondaryId)
                    ? selectedSecondaryId
                    : null,
                dropdownColor: const Color(0xFF111118),
                hint: const Text("All groups",
                    style: TextStyle(color: Colors.white38)),
                items: groupIds
                    .map((g) => DropdownMenuItem<String>(
                        value: g,
                        child: Text(g,
                            style: const TextStyle(color: Colors.white))))
                    .toList(),
                onChanged: (v) => setLocal(() {
                  selectedSecondaryId = v ?? "";
                  selectedClientId = "";
                  selectedClientName = "";
                }),
                decoration: InputDecoration(
                  labelText: "Group ID",
                  labelStyle: const TextStyle(color: Colors.white70),
                  filled: true,
                  fillColor: Colors.white.withOpacity(0.06),
                  border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10)),
                ),
              );
            } else if (sessionType == "CORPORATE" && companyIds.isNotEmpty) {
              secondaryDropdown = DropdownButtonFormField<String>(
                key: const ValueKey("corp_dd"),
                value: selectedSecondaryId.isNotEmpty &&
                        companyIds.contains(selectedSecondaryId)
                    ? selectedSecondaryId
                    : null,
                dropdownColor: const Color(0xFF111118),
                hint: const Text("All companies",
                    style: TextStyle(color: Colors.white38)),
                items: companyIds
                    .map((cid) => DropdownMenuItem<String>(
                          value: cid,
                          child: Text(companyMap[cid] ?? cid,
                              style: const TextStyle(color: Colors.white)),
                        ))
                    .toList(),
                onChanged: (v) => setLocal(() {
                  selectedSecondaryId = v ?? "";
                  selectedClientId = "";
                  selectedClientName = "";
                }),
                decoration: InputDecoration(
                  labelText: "Company",
                  labelStyle: const TextStyle(color: Colors.white70),
                  filled: true,
                  fillColor: Colors.white.withOpacity(0.06),
                  border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10)),
                ),
              );
            }

            final personLabel = sessionType == "COACH"
                ? "Assistant Coach"
                : sessionType == "CONSULTATION"
                    ? ""
                    : "Client";

            return AlertDialog(
              backgroundColor: const Color(0xFF0A0A0F),
              title: const Text("Create Session",
                  style: TextStyle(
                      color: Color(0xFFFFD700), fontFamily: 'Courier')),
              content: SizedBox(
                width: 520,
                child: Stack(
                  children: [
                    SingleChildScrollView(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text("API: $_apiBaseUrl",
                              style: TextStyle(
                                  color: Colors.grey[500], fontSize: 11)),
                          const SizedBox(height: 12),

                          // Session Type dropdown (full width)
                          // menuMaxHeight: show all 6 types without hiding CONSULTATION below the fold (web + mobile).
                          DropdownButtonFormField<String>(
                            value: sessionType,
                            menuMaxHeight: 360,
                            dropdownColor: const Color(0xFF111118),
                            items: const [
                              DropdownMenuItem(
                                  value: "CLIENT",
                                  child: Text("CLIENT",
                                      style: TextStyle(color: Colors.white))),
                              DropdownMenuItem(
                                  value: "COACH",
                                  child: Text("COACH",
                                      style: TextStyle(color: Colors.white))),
                              DropdownMenuItem(
                                  value: "FAMILY",
                                  child: Text("FAMILY",
                                      style: TextStyle(color: Colors.white))),
                              DropdownMenuItem(
                                  value: "GROUP",
                                  child: Text("GROUP",
                                      style: TextStyle(color: Colors.white))),
                              DropdownMenuItem(
                                  value: "CORPORATE",
                                  child: Text("CORPORATE",
                                      style: TextStyle(color: Colors.white))),
                              DropdownMenuItem(
                                  value: "CONSULTATION",
                                  child: Text("CONSULTATION",
                                      style: TextStyle(color: Colors.white))),
                            ],
                            onChanged: (v) => setLocal(() {
                              sessionType = v ?? "CLIENT";
                              selectedSecondaryId = "";
                              selectedClientId = "";
                              selectedClientName = "";
                            }),
                            decoration: InputDecoration(
                              labelText: "Session Type",
                              labelStyle:
                                  const TextStyle(color: Colors.white70),
                              filled: true,
                              fillColor: Colors.white.withOpacity(0.06),
                              border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(10)),
                            ),
                          ),
                          const SizedBox(height: 12),

                          // Secondary dropdown (Family ID / Group ID / Company) — only when relevant
                          if (secondaryDropdown != null) ...[
                            secondaryDropdown,
                            const SizedBox(height: 12),
                          ],

                          // CONSULTATION: external consultee fields — otherwise client / assistant dropdown
                          if (sessionType == "CONSULTATION") ...[
                            TextFormField(
                              controller: consulteeEmailCtrl,
                              keyboardType: TextInputType.emailAddress,
                              style: const TextStyle(color: Colors.white),
                              decoration: InputDecoration(
                                labelText: "Consultee Email (required)",
                                labelStyle:
                                    const TextStyle(color: Colors.white70),
                                errorText: consulteeEmailCtrl.text.isNotEmpty &&
                                        !consulteeEmailValid(
                                            consulteeEmailCtrl.text)
                                    ? "Enter a valid email"
                                    : null,
                                filled: true,
                                fillColor: Colors.white.withOpacity(0.06),
                                border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(10)),
                              ),
                              onChanged: (_) => setLocal(() {}),
                            ),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: consulteeNameCtrl,
                              style: const TextStyle(color: Colors.white),
                              decoration: InputDecoration(
                                labelText:
                                    "Consultee Name (required, min 2 characters)",
                                labelStyle:
                                    const TextStyle(color: Colors.white70),
                                errorText: consulteeNameCtrl.text.isNotEmpty &&
                                        consulteeNameCtrl.text.trim().length < 2
                                    ? "At least 2 characters"
                                    : null,
                                filled: true,
                                fillColor: Colors.white.withOpacity(0.06),
                                border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(10)),
                              ),
                              onChanged: (_) => setLocal(() {}),
                            ),
                            const SizedBox(height: 12),
                            TextFormField(
                              controller: consulteeSubjectCtrl,
                              minLines: 1,
                              maxLines: 3,
                              style: const TextStyle(color: Colors.white),
                              decoration: InputDecoration(
                                labelText: "Subject / Reason (optional)",
                                labelStyle:
                                    const TextStyle(color: Colors.white70),
                                filled: true,
                                fillColor: Colors.white.withOpacity(0.06),
                                border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(10)),
                              ),
                              onChanged: (_) => setLocal(() {}),
                            ),
                            const SizedBox(height: 12),
                          ] else ...[
                            if (personLabel.isNotEmpty)
                              Text(personLabel,
                                  style:
                                      const TextStyle(color: Colors.white70)),
                            if (personLabel.isNotEmpty)
                              const SizedBox(height: 6),
                            if (!hasEntries)
                              Container(
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: Colors.white.withOpacity(0.04),
                                  borderRadius: BorderRadius.circular(10),
                                  border: Border.all(
                                      color: Colors.orange.withOpacity(0.3)),
                                ),
                                child: Text(
                                  sessionType == "COACH"
                                      ? "No active assistant coaches found"
                                      : selectedSecondaryId.isNotEmpty
                                          ? "No clients found for selected ${sessionType == 'FAMILY' ? 'family' : sessionType == 'GROUP' ? 'group' : 'company'}"
                                          : "No clients available",
                                  style: const TextStyle(
                                      color: Colors.orange, fontSize: 13),
                                ),
                              )
                            else
                              DropdownButtonFormField<String>(
                                value: visibleList
                                        .any((e) => e["id"] == selectedClientId)
                                    ? selectedClientId
                                    : visibleList.first["id"]!,
                                dropdownColor: const Color(0xFF111118),
                                items: visibleList
                                    .map((c) => DropdownMenuItem<String>(
                                          value: c["id"]!,
                                          child: Text(c["name"] ?? c["id"]!,
                                              style: const TextStyle(
                                                  color: Colors.white)),
                                        ))
                                    .toList(),
                                onChanged: (v) {
                                  if (v == null) return;
                                  final match = visibleList.firstWhere(
                                      (c) => c["id"] == v,
                                      orElse: () => visibleList.first);
                                  setLocal(() {
                                    selectedClientId = match["id"]!;
                                    selectedClientName =
                                        match["name"] ?? match["id"]!;
                                  });
                                },
                                decoration: InputDecoration(
                                  filled: true,
                                  fillColor: Colors.white.withOpacity(0.06),
                                  border: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(10)),
                                ),
                              ),
                            const SizedBox(height: 12),
                          ],

                          // Date/time + duration row
                          Row(
                            children: [
                              Expanded(
                                child: OutlinedButton.icon(
                                  icon: const Icon(Icons.schedule,
                                      color: Color(0xFF00F5D4)),
                                  label: Text(
                                    "${startLocal.toLocal().toString().substring(0, 16)} (local)",
                                    style: const TextStyle(
                                        color: Color(0xFF00F5D4)),
                                  ),
                                  style: OutlinedButton.styleFrom(
                                    side: const BorderSide(
                                        color: Color(0xFF00F5D4)),
                                  ),
                                  onPressed: pickDateTime,
                                ),
                              ),
                              const SizedBox(width: 10),
                              SizedBox(
                                width: 110,
                                child: TextFormField(
                                  initialValue: durationMinutes.toString(),
                                  keyboardType: TextInputType.number,
                                  style: const TextStyle(color: Colors.white),
                                  decoration: InputDecoration(
                                    labelText: "Minutes",
                                    labelStyle:
                                        const TextStyle(color: Colors.white70),
                                    filled: true,
                                    fillColor: Colors.white.withOpacity(0.06),
                                    border: OutlineInputBorder(
                                        borderRadius:
                                            BorderRadius.circular(10)),
                                  ),
                                  onChanged: (v) => setLocal(() =>
                                      durationMinutes =
                                          int.tryParse(v) ?? durationMinutes),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),

                          // Notes (not used for CONSULTATION — subject field above)
                          if (sessionType != "CONSULTATION")
                            TextFormField(
                              minLines: 2,
                              maxLines: 5,
                              style: const TextStyle(color: Colors.white),
                              decoration: InputDecoration(
                                labelText: "Notes (optional)",
                                labelStyle:
                                    const TextStyle(color: Colors.white70),
                                filled: true,
                                fillColor: Colors.white.withOpacity(0.06),
                                border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(10)),
                              ),
                              onChanged: (v) => notes = v,
                            ),
                          if (sessionType != "CONSULTATION")
                            const SizedBox(height: 12),

                          // Recording opt-out toggle
                          Container(
                            decoration: BoxDecoration(
                              color: Colors.white.withOpacity(0.04),
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: Colors.white10),
                            ),
                            child: SwitchListTile(
                              title: const Text("Disable Recording",
                                  style: TextStyle(color: Colors.white)),
                              subtitle: Text(
                                disableRecording
                                    ? "This session will NOT be recorded"
                                    : "Session will auto-record to cloud",
                                style: TextStyle(
                                    color: disableRecording
                                        ? Colors.orange
                                        : Colors.grey,
                                    fontSize: 12),
                              ),
                              value: disableRecording,
                              onChanged: (v) =>
                                  setLocal(() => disableRecording = v),
                              activeColor: Colors.orange,
                              inactiveThumbColor: const Color(0xFF00F5D4),
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            "Zoom auto-create happens server-side when ENABLE_ZOOM=true.",
                            style: TextStyle(
                                color: Colors.grey[500], fontSize: 11),
                          ),
                        ],
                      ),
                    ),
                    if (consultationSubmitting)
                      Positioned.fill(
                        child: AbsorbPointer(
                          child: Container(
                            alignment: Alignment.center,
                            color: Colors.black.withOpacity(0.45),
                            child: const Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                CircularProgressIndicator(
                                    color: Color(0xFFFFD700)),
                                SizedBox(height: 12),
                                Text("Creating…",
                                    style: TextStyle(
                                        color: Colors.white70, fontSize: 13)),
                              ],
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: consultationSubmitting
                      ? null
                      : () => Navigator.of(ctx).pop(),
                  child: const Text("Cancel",
                      style: TextStyle(color: Colors.grey)),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFFFD700),
                    foregroundColor: Colors.black,
                  ),
                  onPressed: createButtonEnabled
                      ? () async {
                          if (durationMinutes < 5) durationMinutes = 5;
                          if (sessionType == "CONSULTATION") {
                            if (!consulteeEmailValid(consulteeEmailCtrl.text)) {
                              if (mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                      content: Text(
                                          "Enter a valid consultee email.")),
                                );
                              }
                              return;
                            }
                            if (consulteeNameCtrl.text.trim().length < 2) {
                              if (mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                      content: Text(
                                          "Consultee name must be at least 2 characters.")),
                                );
                              }
                              return;
                            }
                            setLocal(() => consultationSubmitting = true);
                            try {
                              await _submitConsultationFromDialog(
                                dialogContext: ctx,
                                emailCtrl: consulteeEmailCtrl,
                                nameCtrl: consulteeNameCtrl,
                                subjectCtrl: consulteeSubjectCtrl,
                                startLocal: startLocal,
                                durationMinutes: durationMinutes,
                                disableRecording: disableRecording,
                              );
                            } finally {
                              if (ctx.mounted) {
                                setLocal(() => consultationSubmitting = false);
                              }
                            }
                            return;
                          }
                          String familyIdForPayload = "";
                          if (sessionType == "FAMILY")
                            familyIdForPayload = selectedSecondaryId;
                          else if (sessionType == "GROUP")
                            familyIdForPayload = selectedSecondaryId;
                          else if (sessionType == "CORPORATE")
                            familyIdForPayload = selectedSecondaryId;
                          await _scheduleSessionViaApi(
                            clientId: selectedClientId,
                            clientName: selectedClientName,
                            coachId: coachId,
                            familyId: familyIdForPayload,
                            scheduledStartLocal: startLocal,
                            durationMinutes: durationMinutes,
                            sessionType: sessionType,
                            notes: notes,
                            disableRecording: disableRecording,
                          );
                          if (ctx.mounted) Navigator.of(ctx).pop();
                        }
                      : null,
                  child: const Text("Create"),
                ),
              ],
            );
          },
        );
      },
    ).then((_) {
      consulteeEmailCtrl.dispose();
      consulteeNameCtrl.dispose();
      consulteeSubjectCtrl.dispose();
    });
  }

  /// Coach-scheduled external consultee (non-roster); distinct from master free consultation.
  bool _isCoachExternalConsultation(Map<String, dynamic> session) {
    final st = (session['session_type'] ?? session['type'] ?? '')
        .toString()
        .toLowerCase();
    if (st == 'consultation') return true;
    if ((session['booked_by'] ?? '').toString() == 'COACH_CONSULTATION')
      return true;
    final cid = (session['client_id'] ?? '').toString();
    return cid.startsWith('consultation_');
  }

  void _fetchClientBrief(String clientId) {
    _socket?.sink.add(
        jsonEncode({"type": "get_presession_brief", "client_id": clientId}));
  }

  void _refreshCoachOverridePanel() {
    final id = _coachOverrideClientId.trim();
    if (id.isEmpty || _socket == null) return;
    _socket!.sink.add(jsonEncode(
        {"type": "coach_get_client_override", "client_user_id": id}));
    _socket!.sink.add(jsonEncode(
        {"type": "coach_get_override_history", "client_user_id": id}));
  }

  void _showCoachOverrideModal() {
    final clientId = _coachOverrideClientId.trim();
    if (clientId.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('Select a client first'),
            backgroundColor: Colors.orange),
      );
      return;
    }
    final cur = _coachOverrideRow;
    String pacing = (cur['pacing'] ?? 'normal').toString();
    String? focus = cur['focus_domain']?.toString();
    if (focus != null && focus.isEmpty) focus = null;
    bool hold = cur['clinical_hold'] == true || cur['clinical_hold'] == 'true';
    final missionCtrl =
        TextEditingController(text: (cur['mission_priority'] ?? '').toString());
    final notesCtrl =
        TextEditingController(text: (cur['notes'] ?? '').toString());
    final reasonCtrl = TextEditingController();

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) {
          return AlertDialog(
            backgroundColor: const Color(0xFF0A0A0F),
            title: const Text('Set clinical override',
                style: TextStyle(color: Color(0xFFFFD700))),
            content: SizedBox(
              width: 420,
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text('Client: $clientId',
                        style: const TextStyle(
                            color: Colors.white54, fontSize: 12)),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      value: pacing,
                      dropdownColor: const Color(0xFF111118),
                      decoration: _coachOvInputDeco('Pacing'),
                      items: const [
                        DropdownMenuItem(
                            value: 'slow',
                            child: Text('slow',
                                style: TextStyle(color: Colors.white))),
                        DropdownMenuItem(
                            value: 'normal',
                            child: Text('normal',
                                style: TextStyle(color: Colors.white))),
                        DropdownMenuItem(
                            value: 'fast',
                            child: Text('fast',
                                style: TextStyle(color: Colors.white))),
                      ],
                      onChanged: (v) => setLocal(() => pacing = v ?? 'normal'),
                    ),
                    const SizedBox(height: 10),
                    DropdownButtonFormField<String?>(
                      value: focus,
                      hint: const Text('Focus domain (optional)',
                          style: TextStyle(color: Colors.white38)),
                      dropdownColor: const Color(0xFF111118),
                      decoration: _coachOvInputDeco('Focus domain'),
                      items: [
                        const DropdownMenuItem<String?>(
                          value: null,
                          child: Text('— none —',
                              style: TextStyle(color: Colors.white54)),
                        ),
                        ..._coachOverrideAllowedDomains.map(
                          (d) => DropdownMenuItem<String?>(
                              value: d,
                              child: Text(d,
                                  style: const TextStyle(color: Colors.white))),
                        ),
                      ],
                      onChanged: (v) => setLocal(() => focus = v),
                    ),
                    const SizedBox(height: 10),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('Clinical hold',
                          style:
                              TextStyle(color: Colors.white70, fontSize: 14)),
                      value: hold,
                      activeColor: const Color(0xFFFFD700),
                      onChanged: (v) => setLocal(() => hold = v),
                    ),
                    TextField(
                      controller: missionCtrl,
                      style: const TextStyle(color: Colors.white),
                      decoration:
                          _coachOvInputDeco('Mission / quest id (UUID)'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: notesCtrl,
                      maxLines: 2,
                      style: const TextStyle(color: Colors.white),
                      decoration: _coachOvInputDeco('Notes (optional)'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: reasonCtrl,
                      maxLines: 3,
                      style: const TextStyle(color: Colors.white),
                      decoration: _coachOvInputDeco('Reason (required)'),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Slow → fast pacing requires ≥ 20 characters in reason.',
                      style: TextStyle(color: Colors.white38, fontSize: 11),
                    ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: () {
                  missionCtrl.dispose();
                  notesCtrl.dispose();
                  reasonCtrl.dispose();
                  Navigator.pop(ctx);
                },
                child:
                    const Text('Cancel', style: TextStyle(color: Colors.grey)),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFFFFD700),
                  foregroundColor: Colors.black,
                ),
                onPressed: () {
                  final r = reasonCtrl.text.trim();
                  if (r.isEmpty) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Reason is required')),
                    );
                    return;
                  }
                  _socket?.sink.add(jsonEncode({
                    'type': 'coach_set_client_override',
                    'client_user_id': clientId,
                    'pacing': pacing,
                    'focus_domain': focus,
                    'clinical_hold': hold,
                    'mission_priority': missionCtrl.text.trim().isEmpty
                        ? null
                        : missionCtrl.text.trim(),
                    'notes': notesCtrl.text.trim().isEmpty
                        ? null
                        : notesCtrl.text.trim(),
                    'override_reason': r,
                  }));
                  missionCtrl.dispose();
                  notesCtrl.dispose();
                  reasonCtrl.dispose();
                  Navigator.pop(ctx);
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                        content: Text('Override submitted'),
                        backgroundColor: Color(0xFF22C55E)),
                  );
                },
                child: const Text('Save'),
              ),
            ],
          );
        },
      ),
    );
  }

  InputDecoration _coachOvInputDeco(String label) {
    return InputDecoration(
      labelText: label,
      labelStyle: const TextStyle(color: Colors.white54),
      filled: true,
      fillColor: Colors.white.withOpacity(0.06),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
    );
  }

  Future<void> _promptOverrideReasonThen(
    String title,
    void Function(String reason) onOk,
  ) async {
    final ctrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: Text(title,
            style: const TextStyle(color: Color(0xFFFFD700), fontSize: 16)),
        content: TextField(
          controller: ctrl,
          maxLines: 3,
          style: const TextStyle(color: Colors.white),
          decoration: _coachOvInputDeco('Reason (required)'),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child:
                  const Text('Cancel', style: TextStyle(color: Colors.grey))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFFFD700),
                foregroundColor: Colors.black),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Continue'),
          ),
        ],
      ),
    );
    final reason = ctrl.text.trim();
    ctrl.dispose();
    if (ok == true && reason.isNotEmpty) onOk(reason);
  }

  Widget _buildCoachOverrideInsightsSection() {
    final clients = _getFilteredClients();
    if (clients.isEmpty) {
      return const SizedBox.shrink();
    }
    final ids = clients
        .map((c) => (c['hardware_id'] ?? c['id'] ?? '').toString())
        .where((x) => x.isNotEmpty)
        .toList();
    final ddVal = (_coachOverrideClientId.isNotEmpty &&
            ids.contains(_coachOverrideClientId))
        ? _coachOverrideClientId
        : (ids.isNotEmpty ? ids.first : '');
    if (ddVal.isNotEmpty && ddVal != _coachOverrideClientId) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        if (ddVal != _coachOverrideClientId) {
          setState(() => _coachOverrideClientId = ddVal);
          _refreshCoachOverridePanel();
        }
      });
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 20),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A2E),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.gavel, color: Color(0xFFC9A962), size: 20),
              const SizedBox(width: 8),
              const Text(
                'THERAPEUTIC OVERRIDES',
                style: TextStyle(
                    color: Color(0xFFC9A962),
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.2,
                    fontSize: 12),
              ),
            ],
          ),
          const SizedBox(height: 10),
          DropdownButtonFormField<String>(
            value: ddVal.isEmpty ? null : ddVal,
            dropdownColor: const Color(0xFF111118),
            decoration: _coachOvInputDeco('Client'),
            items: clients.map((c) {
              final id = (c['hardware_id'] ?? c['id'] ?? '').toString();
              final name = (c['name'] ?? id).toString();
              return DropdownMenuItem(
                  value: id,
                  child: Text('$name ($id)',
                      style:
                          const TextStyle(color: Colors.white, fontSize: 12)));
            }).toList(),
            onChanged: (v) {
              if (v == null) return;
              setState(() => _coachOverrideClientId = v);
              _refreshCoachOverridePanel();
            },
          ),
          const SizedBox(height: 12),
          if (_coachOverrideRow.isNotEmpty) ...[
            _coachOvRow('Pacing', '${_coachOverrideRow['pacing'] ?? '—'}'),
            _coachOvRow('Focus', '${_coachOverrideRow['focus_domain'] ?? '—'}'),
            _coachOvRow('Clinical hold',
                '${_coachOverrideRow['clinical_hold'] == true || _coachOverrideRow['clinical_hold'] == 'true'}'),
            _coachOvRow('Mission priority',
                '${_coachOverrideRow['mission_priority'] ?? '—'}'),
            _coachOvRow(
                'Pacing expires', '${_coachOverrideRow['expires_at'] ?? '—'}'),
            _coachOvRow('Focus expires',
                '${_coachOverrideRow['focus_domain_expires_at'] ?? '—'}'),
            _coachOvRow('Updated', '${_coachOverrideRow['updated_at'] ?? '—'}'),
          ] else
            const Text('No override row for this dyad yet.',
                style: TextStyle(color: Colors.white38, fontSize: 12)),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ElevatedButton.icon(
                onPressed: _showCoachOverrideModal,
                icon: const Icon(Icons.edit, size: 16),
                label: const Text('Set override'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFFC9A962).withOpacity(0.25),
                  foregroundColor: const Color(0xFFC9A962),
                ),
              ),
              OutlinedButton(
                onPressed: _coachOverrideRow.isEmpty
                    ? null
                    : () =>
                        _promptOverrideReasonThen('Renew pacing TTL', (reason) {
                          _socket?.sink.add(jsonEncode({
                            'type': 'coach_renew_override',
                            'client_user_id': _coachOverrideClientId,
                            'renew_type': 'pacing',
                            'override_reason': reason,
                          }));
                        }),
                child: const Text('Renew pacing'),
              ),
              OutlinedButton(
                onPressed: _coachOverrideRow.isEmpty
                    ? null
                    : () => _promptOverrideReasonThen('Renew focus domain TTL',
                            (reason) {
                          _socket?.sink.add(jsonEncode({
                            'type': 'coach_renew_override',
                            'client_user_id': _coachOverrideClientId,
                            'renew_type': 'focus_domain',
                            'override_reason': reason,
                          }));
                        }),
                child: const Text('Renew focus'),
              ),
              OutlinedButton(
                onPressed: _coachOverrideRow.isEmpty
                    ? null
                    : () => _promptOverrideReasonThen('Clear all overrides',
                            (reason) {
                          _socket?.sink.add(jsonEncode({
                            'type': 'coach_clear_client_override',
                            'client_user_id': _coachOverrideClientId,
                            'override_reason': reason,
                          }));
                        }),
                style:
                    OutlinedButton.styleFrom(foregroundColor: Colors.redAccent),
                child: const Text('Clear'),
              ),
            ],
          ),
          if (_coachOverrideHistory.isNotEmpty) ...[
            const SizedBox(height: 16),
            const Text('History',
                style: TextStyle(
                    color: Colors.white54,
                    fontSize: 11,
                    fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            ..._coachOverrideHistory.take(20).map((e) {
              final t = (e['override_type'] ?? '').toString();
              final at = (e['created_at'] ?? '').toString();
              final pv = (e['previous_value'] ?? '').toString();
              final nv = (e['new_value'] ?? '').toString();
              final rs = (e['reason'] ?? '').toString();
              return Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.circle, size: 6, color: Color(0xFF6B7280)),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '$at · $t\n  $pv → $nv${rs.isNotEmpty ? '\n  reason: $rs' : ''}',
                        style: const TextStyle(
                            color: Colors.white60, fontSize: 11, height: 1.25),
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ],
      ),
    );
  }

  Widget _coachOvRow(String k, String v) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(k,
                style: const TextStyle(color: Colors.white38, fontSize: 11)),
          ),
          Expanded(
              child: Text(v,
                  style: const TextStyle(color: Colors.white, fontSize: 12))),
        ],
      ),
    );
  }

  Future<void> _cancelConsultationSession(Map<String, dynamic> session) async {
    final sessionId = (session['session_id'] ?? session['id'] ?? '').toString();
    if (sessionId.isEmpty) return;
    final consultee = (session['consultation_name'] ??
            session['client_name'] ??
            'the consultee')
        .toString();
    if (!mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: const Text('Cancel consultation?',
            style: TextStyle(color: Color(0xFFC9A962))),
        content: Text(
          'This will email $consultee, delete the Zoom meeting, and remove the session from your schedule.',
          style: const TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Back', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: Colors.redAccent,
                foregroundColor: Colors.white),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Cancel consultation'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    _socket?.sink.add(jsonEncode({
      'type': 'coach_cancel_consultation',
      'session_id': sessionId,
    }));
  }

  void _startLiveSession(Map<String, dynamic> session) {
    if (_isCoachExternalConsultation(session)) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Live session workspace is for roster clients. Use Start Zoom for consultations.',
            ),
            backgroundColor: Color(0xFF8B7355),
          ),
        );
      }
      return;
    }
    final sessionId = (session['id'] ?? session['session_id'] ?? '').toString();
    final clientId =
        (session['client_id'] ?? session['client'] ?? '').toString();
    final familyId = (session['family_id'] ?? '').toString();
    final label = (session['label'] ??
            session['type'] ??
            session['title'] ??
            'Live Coaching Session')
        .toString();
    final meetingUrl =
        (session['zoom_link'] ?? session['meeting_url'] ?? '').toString();
    final hostUrl =
        (session['zoom_host_url'] ?? '').toString(); // Host URL for coaches
    final zoomMeetingId = (session['zoom_meeting_id'] ?? '').toString();
    final dynamic durRaw = session['duration'] ??
        session['duration_minutes'] ??
        session['scheduled_duration_minutes'];
    int? scheduledMinutes;
    if (durRaw is int) {
      scheduledMinutes = durRaw;
    } else if (durRaw is double) {
      scheduledMinutes = durRaw.round();
    } else if (durRaw is String) {
      scheduledMinutes = int.tryParse(durRaw);
    }
    _activeLiveSession = null;
    _liveNotes.value = [];
    _liveObservations.value = [];

    _socket?.sink.add(jsonEncode({
      "type": "coach_start_live_session",
      "client_id": clientId,
      "family_id": familyId,
      "schedule_session_id": sessionId,
      "scheduled_duration_minutes": scheduledMinutes,
      "label": label,
      "meeting_url": meetingUrl,
      "zoom_meeting_id": zoomMeetingId,
      "service_mode": "green",
    }));

    _showLiveSessionSheet(
        initialLabel: label,
        initialMeetingUrl: meetingUrl,
        initialHostUrl: hostUrl);
  }

  void _sendLiveNote(String text) {
    final liveId = (_activeLiveSession?['id'] ?? '').toString();
    if (liveId.isEmpty) return;
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    _socket?.sink.add(jsonEncode({
      "type": "coach_live_note",
      "live_session_id": liveId,
      "text": trimmed,
    }));
  }

  void _endLiveSession({required bool shareWithNate}) {
    final liveId = (_activeLiveSession?['id'] ?? '').toString();
    if (liveId.isEmpty) return;
    _socket?.sink.add(jsonEncode({
      "type": "coach_end_live_session",
      "live_session_id": liveId,
      "share_with_nate": shareWithNate,
    }));
  }

  void _fetchFolderNotes(
      {String? folderId, String? familyId, String? clientId}) {
    setState(() => _notesLoading = true);
    _socket?.sink.add(jsonEncode({
      "type": "coach_get_session_notes",
      "folder_id": folderId,
      "family_id": familyId,
      "client_id": clientId,
    }));
  }

  void _addFolderNote({
    required String noteText,
    String? folderId,
    String? familyId,
    String? clientId,
    bool shareWithNate = false,
  }) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_add_session_note",
      "folder_id": folderId,
      "family_id": familyId,
      "client_id": clientId,
      "note_text": noteText,
      "share_with_nate": shareWithNate,
    }));
  }

  void _handleSocketMessage(dynamic message) {
    try {
      final data = jsonDecode(message);

      if (!_messageRelay.isClosed && data is Map<String, dynamic>) {
        _messageRelay.add(data);
      }

      if (data['type'] == 'login_success') {
        _debugLog(">>> COACH AUTHENTICATED. Fetching Data...");
        _wsReconnectAttempts = 0;
        _authToken = data['token']?.toString();
        final profile = data['profile'] as Map<String, dynamic>?;
        _coachHardwareId = profile?['hardware_id']?.toString();
        _pushDojoIframeAuthIfNeeded();
        _fetchDashboard();
      } else if (data['type'] == 'coach_clients') {
        if (mounted) {
          setState(() {
            _clients = data['clients'] ?? [];
            _isLoading = false;
            if (_coachOverrideClientId.isEmpty && _clients.isNotEmpty) {
              final c0 = _clients.first;
              if (c0 is Map) {
                final m = Map<String, dynamic>.from(c0);
                _coachOverrideClientId =
                    (m['hardware_id'] ?? m['client_id'] ?? m['id'] ?? '')
                        .toString();
              }
            }
          });
          _refreshCoachOverridePanel();
        }
      } else if (data['type'] == 'coach_client_override' ||
          data['type'] == 'coach_client_override_saved' ||
          data['type'] == 'coach_override_renewed') {
        if (mounted) {
          setState(() {
            final o = data['override'];
            _coachOverrideRow = o is Map ? Map<String, dynamic>.from(o) : {};
            final ad = data['allowed_focus_domains'];
            if (ad is List && ad.isNotEmpty) {
              _coachOverrideAllowedDomains =
                  ad.map((e) => e.toString()).toList();
            }
          });
        }
      } else if (data['type'] == 'coach_override_history') {
        if (mounted) {
          setState(() {
            _coachOverrideHistory = List<Map<String, dynamic>>.from(
              (data['entries'] as List? ?? []).map((e) {
                if (e is Map) return Map<String, dynamic>.from(e);
                return <String, dynamic>{};
              }),
            );
          });
        }
      } else if (data['type'] == 'coach_client_override_cleared') {
        if (mounted) {
          setState(() {
            _coachOverrideRow = {};
          });
        }
        _refreshCoachOverridePanel();
      } else if (data['type'] == 'coach_calendar_data') {
        if (mounted) {
          setState(() {
            _schedule = data['data']?['schedule'] ?? [];
          });
        }
      } else if (data['type'] == 'consultation_created') {
        final rid = data['request_id']?.toString();
        if (rid != null &&
            rid == _consultationCreateRequestId &&
            _consultationCreateCompleter != null &&
            !_consultationCreateCompleter!.isCompleted) {
          _consultationCreateCompleter!
              .complete(Map<String, dynamic>.from(data));
        }
      } else if (data['type'] == 'consultation_cancelled') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                  'Consultation cancelled. The consultee was notified and the Zoom meeting was removed.'),
              backgroundColor: Color(0xFF22C55E),
            ),
          );
          _emitFetchCoachCalendar();
        }
      } else if (data['type'] == 'availability_updated') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content:
                Text("✓ Published ${data['added'] ?? 0} availability slot(s)"),
            backgroundColor: const Color(0xFF22C55E),
          ));
          _refreshMyAvailability();
        }
      } else if (data['type'] == 'my_availability_loaded') {
        if (mounted) {
          setState(() {
            _myRecurring = List<Map<String, dynamic>>.from(
              (data['recurring'] as List? ?? [])
                  .map((e) => Map<String, dynamic>.from(e)),
            );
            _myBlocks = List<Map<String, dynamic>>.from(
              (data['blocks'] as List? ?? [])
                  .map((e) => Map<String, dynamic>.from(e)),
            );
            _myAvailabilityLoaded = true;
          });
        }
      } else if (data['type'] == 'time_blocked') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text("✓ Blocked ${data['added'] ?? 0} date(s)"),
            backgroundColor: const Color(0xFF8B5CF6),
          ));
          _refreshMyAvailability();
        }
      } else if (data['type'] == 'time_unblocked') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("✓ Date unblocked"),
            backgroundColor: Color(0xFF22C55E),
          ));
          _refreshMyAvailability();
        }
      } else if (data['type'] == 'presession_brief') {
        if (mounted) {
          setState(() {
            _selectedClientBrief = data['brief'];
          });
          _showClientBriefSheet();
        }
      } else if (data['type'] == 'session_assistant_data') {
        if (mounted)
          _handleSessionAssistantData(Map<String, dynamic>.from(data));
      } else if (data['type'] == 'session_assistant_response') {
        if (mounted && data['nate_response'] != null) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(data['nate_response'],
                style: const TextStyle(color: Colors.white)),
            backgroundColor: const Color(0xFF1A1A2E),
            duration: const Duration(seconds: 8),
            action: SnackBarAction(
                label: 'OK',
                textColor: const Color(0xFF4ECDC4),
                onPressed: () {}),
          ));
        }
      } else if (data['type'] == 'session_assistant_toggle_ack') {
        if (mounted) {
          _assistEnabledBySession[data['session_id'] ?? ''] =
              data['nate_enabled'] ?? true;
          setState(() {});
        }
      } else if (data['type'] == 'session_service_mode_ack') {
        final liveId = (data['live_session_id'] ?? '').toString();
        if (liveId.isNotEmpty && mounted) {
          _sessionServiceMode[liveId] =
              (data['service_mode'] ?? 'green').toString();
          _assistEnabledBySession[liveId] = data['assist_enabled'] ?? true;
          setState(() {});
        }
      } else if (data['type'] == 'coach_live_session_started') {
        final live = (data['live_session'] is Map)
            ? Map<String, dynamic>.from(data['live_session'])
            : <String, dynamic>{};
        final liveId = (live['id'] ?? '').toString();
        if (liveId.isNotEmpty) {
          _sessionServiceMode[liveId] =
              (live['service_mode'] ?? 'green').toString();
        }
        setState(() {
          _activeLiveSession = live;
        });
        try {
          final notes =
              List<Map<String, dynamic>>.from((live['notes'] ?? []) as List);
          final obs = List<Map<String, dynamic>>.from(
              (live['observations'] ?? []) as List);
          _liveNotes.value = notes;
          _liveObservations.value = obs;
        } catch (_) {}
      } else if (data['type'] == 'coach_live_note_ack') {
        final note = (data['note'] is Map)
            ? Map<String, dynamic>.from(data['note'])
            : null;
        if (note != null) {
          final next = List<Map<String, dynamic>>.from(_liveNotes.value);
          next.add(note);
          _liveNotes.value = next;
        }
      } else if (data['type'] == 'coach_live_observation') {
        final obs = (data['observation'] is Map)
            ? Map<String, dynamic>.from(data['observation'])
            : null;
        if (obs != null) {
          final next = List<Map<String, dynamic>>.from(_liveObservations.value);
          next.add(obs);
          _liveObservations.value = next;
        }
      } else if (data['type'] == 'coach_live_session_ended') {
        setState(() {
          _activeLiveSession = null;
        });
        if (_liveSheetOpen) {
          Navigator.of(context).maybePop();
        }
      } else if (data['type'] == 'coach_learning_enqueued') {
        if (mounted) {
          final qid = (data['queue_id'] ?? '').toString();
          final st = (data['status'] ?? '').toString();
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text(qid.isNotEmpty
                    ? "Shared with Nate ($st) • $qid"
                    : "Shared with Nate ($st)")),
          );
        }
      } else if (data['type'] == 'coach_learning_not_enqueued') {
        if (mounted) {
          final reason = (data['reason'] ?? 'UNKNOWN').toString();
          final msg = reason == 'NO_NOTES'
              ? "Nothing shared: add at least one note first."
              : "Share w/ Nate failed: $reason";
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(msg)),
          );
        }
      } else if (data['type'] == 'coach_inbound_requests') {
        if (mounted) {
          setState(() {
            _inboundRequests = List<Map<String, dynamic>>.from(
              (data['requests'] ?? []).map((r) => Map<String, dynamic>.from(r)),
            );
          });
        }
      } else if (data['type'] == 'coach_request_new') {
        if (mounted) {
          final name = data['client_name'] ?? 'A client';
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text('$name sent you a coaching request'),
                backgroundColor: const Color(0xFFC9A962)),
          );
          _socket?.sink.add(jsonEncode({"type": "coach_get_inbound_requests"}));
        }
      } else if (data['type'] == 'coach_request_accepted_confirm') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content:
                    Text('Client accepted — they\'re now on your caseload'),
                backgroundColor: Color(0xFF4ECDC4)),
          );
          _socket?.sink.add(jsonEncode({"type": "coach_get_inbound_requests"}));
          _socket?.sink.add(jsonEncode({"type": "coach_get_clients"}));
        }
      } else if (data['type'] == 'coach_request_declined_confirm') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text('Request declined'),
                backgroundColor: Colors.grey),
          );
          _socket?.sink.add(jsonEncode({"type": "coach_get_inbound_requests"}));
        }
      } else if (data['type'] == 'coach_request_nudge_alert') {
        if (mounted) {
          final name = data['client_name'] ?? 'A client';
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text(
                    '$name nudged you — they\'re waiting for your response'),
                backgroundColor: const Color(0xFF4ECDC4)),
          );
        }
      } else if (data['type'] == 'coach_message_sent') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text('Message sent to client'),
                backgroundColor: Color(0xFF4ECDC4)),
          );
        }
      } else if (data['type'] == 'coach_session_notes') {
        if (mounted) {
          setState(() {
            _selectedFolderNotes =
                List<Map<String, dynamic>>.from((data['notes'] ?? []) as List);
            _notesLoading = false;
          });
        }
      } else if (data['type'] == 'coach_session_note_saved') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text("Note saved")),
          );
        }
      } else if (data['type'] == 'consultation_started') {
        if (mounted) {
          setState(() {
            _activeConsultationId =
                (data['session']?['session_id'] ?? '').toString();
            _consultationRemainingSeconds =
                (data['duration_seconds'] ?? 900) as int;
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content:
                  Text(data['message']?.toString() ?? 'Consultation started'),
              backgroundColor: const Color(0xFF4ECDC4),
              duration: const Duration(seconds: 4),
            ),
          );
        }
      } else if (data['type'] == 'consultation_timer_update') {
        if (mounted) {
          setState(() {
            _consultationRemainingSeconds =
                (data['remaining_seconds'] ?? 0) as int;
          });
        }
      } else if (data['type'] == 'consultation_warning') {
        if (mounted) {
          final msg = data['message']?.toString() ?? 'Time running out';
          setState(() => _consultationWarningMessage = msg);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(msg),
              backgroundColor: const Color(0xFFEF4444),
              duration: const Duration(seconds: 5),
            ),
          );
          Future.delayed(const Duration(seconds: 6), () {
            if (mounted) setState(() => _consultationWarningMessage = null);
          });
        }
      } else if (data['type'] == 'consultation_ended') {
        if (mounted) {
          setState(() {
            _activeConsultationId = null;
            _consultationRemainingSeconds = 0;
            _consultationWarningMessage = null;
          });
          showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF1A1A2E),
              title: const Text('Consultation Complete',
                  style: TextStyle(color: Color(0xFFC9A962))),
              content: Text(
                data['message']?.toString() ?? 'The consultation has ended.',
                style: const TextStyle(color: Colors.white70),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text('OK',
                      style: TextStyle(color: Color(0xFF4ECDC4))),
                ),
              ],
            ),
          );
        }
      } else if (data['type'] == 'dojo_started') {
        setState(() {
          _dojoSessionId = (data['session_id'] ?? '').toString();
          _dojoBusy = false;
        });
      } else if (data['type'] == 'dojo_prompt') {
        setState(() {
          _dojoAdversarialPrompt = (data['prompt'] ?? '').toString();
          _dojoBusy = false;
          _dojoLog.add({
            "type": "prompt",
            "persona": _dojoActivePersona,
            "text": _dojoAdversarialPrompt,
          });
        });
        Future.delayed(const Duration(milliseconds: 100), () {
          _dojoScrollController.animateTo(
            _dojoScrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOut,
          );
        });
      } else if (data['type'] == 'dojo_analysis') {
        final analysis = (data['analysis'] is Map)
            ? Map<String, dynamic>.from(data['analysis'])
            : null;
        setState(() {
          _dojoLastAnalysis = analysis;
          _dojoBusy = false;
          if (analysis != null) {
            _dojoLog.add({
              "type": "analysis",
              "data": analysis,
            });
          }
        });
        Future.delayed(const Duration(milliseconds: 100), () {
          _dojoScrollController.animateTo(
            _dojoScrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOut,
          );
        });
      } else if (data['type'] == 'dojo_ended') {
        setState(() {
          _dojoSessionId = null;
          _dojoActivePersona = null;
          _dojoAdversarialPrompt = null;
          _dojoBusy = false;
        });
      }
      // ===== CLASSROOM HANDLERS =====
      else if (data['type'] == 'classroom_sessions') {
        if (mounted) {
          final incoming =
              List<Map<String, dynamic>>.from(data['sessions'] ?? []);
          setState(() {
            _classroomSessions = incoming;
          });
          // Tab-switch / page-refresh restoration:
          // If we don't currently have an active video in the UI but the
          // backend reports a device-upload that's still being analyzed
          // (status uploading/uploaded — i.e. analyze_video has not finished
          // writing transcript_location + flipping status to analyzed), pick
          // it back up and resume the analysis-in-progress UI. This means
          // the coach can switch tabs / refresh the browser during the long
          // (5-15 min) STT + analysis run and still find their video here
          // when they return, without re-uploading.
          if (_classroomUploadedVideoId == null &&
              _classroomAnalysis == null &&
              !_classroomAnalyzing) {
            try {
              final pending = incoming.firstWhere(
                (s) {
                  final sid = (s['session_id'] ?? '').toString();
                  final st = (s['status'] ?? '').toString().toLowerCase();
                  final type = (s['type'] ?? '').toString();
                  if (sid.isEmpty) return false;
                  if (type != 'uploaded_video') return false;
                  return st == 'uploading' ||
                      st == 'uploaded' ||
                      st == 'analyzing';
                },
                orElse: () => <String, dynamic>{},
              );
              final pendingId = (pending['session_id'] ?? '').toString();
              if (pendingId.isNotEmpty) {
                _classroomUploadedVideoId = pendingId;
                _startClassroomVideoAnalysisPoll(pendingId);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(
                        'Resumed analysis for ${pending['filename'] ?? pendingId}'),
                    backgroundColor: const Color(0xFF4ECDC4),
                    duration: const Duration(seconds: 3),
                  ),
                );
              }
            } catch (_) {}
          }
        }
      } else if (data['type'] == 'classroom_progress') {
        if (mounted) {
          setState(() {
            _classroomProgress = (data['progress'] is Map)
                ? Map<String, dynamic>.from(data['progress'])
                : null;
          });
        }
      } else if (data['type'] == 'classroom_analysis_started') {
        if (mounted) {
          setState(() {
            _classroomAnalyzing = true;
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                  "Analysis started... Little Nate is reviewing the session"),
              duration: Duration(seconds: 3),
            ),
          );
        }
      } else if (data['type'] == 'classroom_analysis_complete') {
        if (mounted) {
          _cancelClassroomVideoPoll();
          Map<String, dynamic>? analysis = (data['analysis'] is Map)
              ? Map<String, dynamic>.from(data['analysis'] as Map)
              : null;
          analysis = _flattenClassroomAnalysis(analysis);
          final err = analysis != null ? '${analysis['error'] ?? ''}' : '';
          final hasErr = err.isNotEmpty;
          if (!hasErr) {
            setState(() {
              _classroomServerPipelineLabel = null;
              _classroomServerPipelineIndex = null;
              _classroomVideoPipelineActive = false;
              _classroomAnalyzing = false;
              _classroomAnalysis = analysis;
              if (analysis != null) {
                _classroomHistory.insert(0, analysis);
                _classroomReflectionControllers = {};
                final questions =
                    List<String>.from(analysis['reflection_questions'] ?? []);
                for (int i = 0; i < questions.length; i++) {
                  _classroomReflectionControllers['q_$i'] =
                      TextEditingController();
                }
              }
            });
            if (analysis != null) {
              final tps = (analysis['therapeutic_presence_score'] is num)
                  ? (analysis['therapeutic_presence_score'] as num).toDouble()
                  : 0.0;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                      "Analysis complete! Therapeutic presence: ${tps.toStringAsFixed(1)}/10"),
                  backgroundColor: const Color(0xFF4ECDC4),
                  duration: const Duration(seconds: 4),
                ),
              );
            }
            _requestClassroomSessions();
          } else {
            setState(() {
              _classroomServerPipelineLabel = null;
              _classroomServerPipelineIndex = null;
              _classroomVideoPipelineActive = false;
              _classroomAnalyzing = false;
            });
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text("Video analysis failed: $err"),
                backgroundColor: const Color(0xFFEF4444),
                duration: const Duration(seconds: 5),
              ),
            );
            _requestClassroomSessions();
          }
        }
      } else if (data['type'] == 'classroom_analysis') {
        if (mounted) {
          Map<String, dynamic>? analysis = (data['analysis'] is Map)
              ? Map<String, dynamic>.from(data['analysis'] as Map)
              : null;
          analysis = _flattenClassroomAnalysis(analysis);
          final done = _isClassroomSessionAnalysisComplete(analysis);
          if (done) {
            _cancelClassroomVideoPoll();
          }
          setState(() {
            if (done) {
              _classroomServerPipelineLabel = null;
              _classroomServerPipelineIndex = null;
              _classroomVideoPipelineActive = false;
              _classroomAnalyzing = false;
              _classroomAnalysis = analysis;
              _classroomReflectionControllers = {};
              final questions =
                  List<String>.from(analysis?['reflection_questions'] ?? []);
              for (int i = 0; i < questions.length; i++) {
                _classroomReflectionControllers['q_$i'] =
                    TextEditingController();
              }
            } else {
              final pl = analysis?['pipeline_stage']?.toString();
              if (pl != null && pl.isNotEmpty) {
                _classroomServerPipelineLabel = pl;
                final pi = analysis!['pipeline_stage_index'];
                if (pi is int) {
                  _classroomServerPipelineIndex = pi;
                } else if (pi is num) {
                  _classroomServerPipelineIndex = pi.toInt();
                } else {
                  _classroomServerPipelineIndex = null;
                }
                if (_classroomServerPipelineIndex != null) {
                  _classroomVideoStageIndex =
                      _classroomServerPipelineIndex!.clamp(
                    0,
                    _classroomVideoStages.length - 1,
                  );
                }
                _classroomVideoPipelineActive = true;
                _classroomAnalyzing = true;
              }
            }
          });
        }
      } else if (data['type'] == 'classroom_reflection_submitted') {
        if (mounted) {
          setState(() {
            if (_classroomAnalysis != null) {
              _classroomAnalysis!['reflection_submitted_at'] =
                  DateTime.now().toIso8601String();
            }
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                  "Reflection submitted! Great work on your professional development."),
              backgroundColor: Color(0xFF9D4EDD),
              duration: Duration(seconds: 3),
            ),
          );
          // Refresh progress
          _requestClassroomProgress();
        }
      }
      // ===== LIVE ANALYSIS HANDLERS =====
      else if (data['type'] == 'classroom_recording_status') {
        if (mounted) {
          final recording = (data['recording'] is Map)
              ? Map<String, dynamic>.from(data['recording'])
              : null;
          final meetingStatus = (data['meeting_status'] is Map)
              ? Map<String, dynamic>.from(data['meeting_status'])
              : null;
          setState(() {
            _classroomCheckingRecording = false;
            _classroomRecordingStatus = recording;
            _classroomMeetingStatus = meetingStatus;
          });
        }
      } else if (data['type'] == 'classroom_live_analysis') {
        if (mounted) {
          final analysis = (data['analysis'] is Map)
              ? Map<String, dynamic>.from(data['analysis'])
              : null;
          final success = data['success'] == true;

          setState(() {
            _classroomLiveAnalyzing = false;
            if (success && analysis != null) {
              _classroomLiveAnalysis = analysis;
              // Also set as current analysis for display
              _classroomAnalysis = analysis;
            }
          });

          if (success) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text("Live analysis complete!"),
                backgroundColor: Color(0xFF4ECDC4),
                duration: Duration(seconds: 2),
              ),
            );
          } else {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(
                content: Text(data['message'] ?? "Live analysis failed"),
                backgroundColor: Colors.red,
                duration: const Duration(seconds: 3),
              ),
            );
          }
        }
      } else if (data['type'] == 'classroom_live_transcript') {
        // Handle live transcript updates if needed
        if (mounted && data['available'] == true) {
          // Could display live transcript preview
        }
      }
      // ===== FINANCIAL / BOOKING APPROVAL HANDLERS =====
      else if (data['type'] == 'pending_booking_notification') {
        if (mounted) {
          final session = (data['session'] is Map)
              ? Map<String, dynamic>.from(data['session'])
              : <String, dynamic>{};
          setState(() {
            _pendingBookings.add(session);
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                  "New booking request from ${session['client_name'] ?? 'client'}"),
              backgroundColor: const Color(0xFFFFD700),
              duration: const Duration(seconds: 4),
            ),
          );
        }
      } else if (data['type'] == 'coach_pending_bookings') {
        if (mounted) {
          setState(() {
            _pendingBookings =
                List<Map<String, dynamic>>.from(data['sessions'] ?? []);
          });
        }
      } else if (data['type'] == 'booking_approved') {
        if (mounted) {
          final sessionId =
              (data['session'] is Map) ? data['session']['session_id'] : '';
          setState(() {
            _pendingBookings.removeWhere((s) => s['session_id'] == sessionId);
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text("Booking approved!"),
                backgroundColor: Color(0xFF4ECDC4)),
          );
          _fetchDashboard();
        }
      } else if (data['type'] == 'booking_declined') {
        if (mounted) {
          final sessionId = data['session_id'] ?? '';
          setState(() {
            _pendingBookings.removeWhere((s) => s['session_id'] == sessionId);
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text("Booking declined"),
                backgroundColor: Colors.orange),
          );
        }
      } else if (data['type'] == 'coach_financials') {
        if (mounted) {
          setState(() {
            _financialData = Map<String, dynamic>.from(data);
            _financialsLoading = false;
            final fee = data['coaching_fee'];
            if (fee != null) {
              _coachFeeController.text = fee.toString();
            }
          });
        }
      } else if (data['type'] == 'coach_fee_updated') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content:
                    Text("Coaching rate updated to \$${data['coaching_fee']}")),
          );
          _requestFinancials();
        }
      } else if (data['type'] == 'coach_payment_mode_updated') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text(
                    "Payment mode: ${data['payment_mode'] == 'platform_handles' ? 'Platform handles payments' : 'You collect payments'}")),
          );
          _requestFinancials();
        }
      } else if (data['type'] == 'w9_submitted') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text("W-9 form submitted successfully!"),
                backgroundColor: Color(0xFF4ECDC4)),
          );
          _requestFinancials();
        }
      }
      // === DOJO Subscription responses ===
      else if (data['type'] == 'dojo_subscriptions_data') {
        if (mounted) {
          setState(() {
            _dojoSubscriptions = (data['dojo_subscriptions'] is Map)
                ? Map<String, dynamic>.from(data['dojo_subscriptions'])
                : {};
            _activeDojos = (data['active_dojos'] is List)
                ? List<String>.from(data['active_dojos'])
                : [];
            _dojoDiscountPct = (data['dojo_discount_pct'] is num)
                ? (data['dojo_discount_pct'] as num).toInt()
                : 0;
            _dojoMonthlyPrice = (data['dojo_monthly_price'] is num)
                ? (data['dojo_monthly_price'] as num).toDouble()
                : 0.0;
            _dojoSubsLoading = false;
          });
        }
      } else if (data['type'] == 'dojo_subscription_cancelled') {
        if (mounted) {
          final dojoKey = data['dojo_key'] ?? '';
          final accessEnd = data['access_end_date'] ?? '';
          setState(() {
            _dojoSubscriptions = (data['dojo_subscriptions'] is Map)
                ? Map<String, dynamic>.from(data['dojo_subscriptions'])
                : _dojoSubscriptions;
            _activeDojos = (data['active_dojos'] is List)
                ? List<String>.from(data['active_dojos'])
                : _activeDojos;
            _dojoDiscountPct = (data['dojo_discount_pct'] is num)
                ? (data['dojo_discount_pct'] as num).toInt()
                : _dojoDiscountPct;
            _dojoMonthlyPrice = (data['dojo_monthly_price'] is num)
                ? (data['dojo_monthly_price'] as num).toDouble()
                : _dojoMonthlyPrice;
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text("$dojoKey cancelled. Access until $accessEnd"),
                backgroundColor: Colors.orange),
          );
        }
      } else if (data['type'] == 'dojo_subscription_added') {
        if (mounted) {
          final dojoKey = data['dojo_key'] ?? '';
          setState(() {
            _dojoSubscriptions = (data['dojo_subscriptions'] is Map)
                ? Map<String, dynamic>.from(data['dojo_subscriptions'])
                : _dojoSubscriptions;
            _activeDojos = (data['active_dojos'] is List)
                ? List<String>.from(data['active_dojos'])
                : _activeDojos;
            _dojoDiscountPct = (data['dojo_discount_pct'] is num)
                ? (data['dojo_discount_pct'] as num).toInt()
                : _dojoDiscountPct;
            _dojoMonthlyPrice = (data['dojo_monthly_price'] is num)
                ? (data['dojo_monthly_price'] as num).toDouble()
                : _dojoMonthlyPrice;
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text("$dojoKey added to your subscriptions!"),
                backgroundColor: const Color(0xFF4ECDC4)),
          );
        }
      }
      // ===== AI MODE RESPONSES (COACH) =====
      else if (data['type'] == 'ai_mode_activated') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                  "AI Mode activated: ${data['mode']?.toString().toUpperCase() ?? 'UNKNOWN'}"),
              backgroundColor: const Color(0xFF9D4EDD),
            ),
          );
        }
      } else if (data['type'] == 'ai_mode_output') {
        if (mounted) {
          _showAiModeOutputDialog(Map<String, dynamic>.from(data));
        }
      } else if (data['type'] == 'ai_mode_deactivated') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text("AI Mode deactivated"),
                backgroundColor: Color(0xFF4ECDC4)),
          );
        }
      } else if (data['type'] == 'error') {
        final rid = data['request_id']?.toString();
        if (rid != null &&
            rid == _consultationCreateRequestId &&
            _consultationCreateCompleter != null &&
            !_consultationCreateCompleter!.isCompleted) {
          _consultationCreateCompleter!.completeError(
            Exception(data['message']?.toString() ?? 'Request failed'),
          );
        }
        if (mounted) {
          setState(() {
            _notesLoading = false;
            _dojoBusy = false;
            _classroomAnalyzing = false;
            _classroomLiveAnalyzing = false;
            final msg = (data['message'] ?? 'Unknown error').toString();
            final lowerMsg = msg.toLowerCase();
            // Check if this is a Dojo-related error
            if (lowerMsg.contains('dojo') || lowerMsg.contains('persona')) {
              _dojoError = msg;
            } else if (lowerMsg.contains('not available') ||
                lowerMsg.contains('unavailable') ||
                lowerMsg.contains('module not')) {
              // Graceful degradation for unavailable modules — show non-alarming message
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: const Text(
                      'This feature is currently being prepared. Please try again later.'),
                  backgroundColor: const Color(0xFF8B7355),
                  duration: const Duration(seconds: 3),
                ),
              );
            } else {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(msg)),
              );
            }
          });
        }
      }
    } catch (e) {
      _debugLog("Error parsing socket message: $e");
    }
  }

  // ── AI Mode Output Dialog (Coach) ──
  void _showAiModeOutputDialog(Map<String, dynamic> data) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: Row(
          children: [
            const Icon(Icons.psychology, color: Color(0xFF9D4EDD)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'AI MODE: ${data['mode']?.toString().toUpperCase() ?? "OUTPUT"}',
                style: const TextStyle(
                    color: Color(0xFFC9A962),
                    fontFamily: 'Cormorant Garamond',
                    fontSize: 18),
              ),
            ),
          ],
        ),
        content: SingleChildScrollView(
          child: Text(
            data['output']?.toString() ??
                data['result']?.toString() ??
                'No output',
            style: const TextStyle(
                color: Colors.white70, fontSize: 13, height: 1.5),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child:
                const Text('CLOSE', style: TextStyle(color: Color(0xFFC9A962))),
          ),
        ],
      ),
    );
  }

  // ── AI Mode Trigger (Coach) ──
  void _showCoachAiModePicker(String clientId) {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0A),
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                'AI INTELLIGENCE MODES',
                style: TextStyle(
                    color: Color(0xFFC9A962),
                    fontFamily: 'Cormorant Garamond',
                    fontSize: 20,
                    fontWeight: FontWeight.bold),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.radar, color: Color(0xFF4ECDC4)),
              title: const Text('Tri-Corder',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.bold)),
              subtitle: const Text('Deep diagnostic scan of emotional patterns',
                  style: TextStyle(color: Colors.white38, fontSize: 12)),
              onTap: () {
                Navigator.pop(ctx);
                _activateCoachAiMode('tri_corder', clientId);
              },
            ),
            ListTile(
              leading: const Icon(Icons.auto_stories, color: Color(0xFF9D4EDD)),
              title: const Text('Archivist',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.bold)),
              subtitle: const Text('Narrative synthesis of therapeutic journey',
                  style: TextStyle(color: Colors.white38, fontSize: 12)),
              onTap: () {
                Navigator.pop(ctx);
                _activateCoachAiMode('archivist', clientId);
              },
            ),
            ListTile(
              leading: const Icon(Icons.shield, color: Color(0xFFEF4444)),
              title: const Text('Guardian',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.bold)),
              subtitle: const Text('Protective monitoring for risk indicators',
                  style: TextStyle(color: Colors.white38, fontSize: 12)),
              onTap: () {
                Navigator.pop(ctx);
                _activateCoachAiMode('guardian', clientId);
              },
            ),
            ListTile(
              leading: const Icon(Icons.supervisor_account,
                  color: Color(0xFFE8D5A3)),
              title: const Text('Supervisor',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.bold)),
              subtitle: const Text(
                  'Clinical quality oversight and recommendations',
                  style: TextStyle(color: Colors.white38, fontSize: 12)),
              onTap: () {
                Navigator.pop(ctx);
                _activateCoachAiMode('supervisor', clientId);
              },
            ),
            ListTile(
              leading: const Icon(Icons.edit_note, color: Color(0xFFF59E0B)),
              title: const Text('Editor',
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.bold)),
              subtitle: const Text(
                  'Literary writing companion — 7 master writers as collective intelligence',
                  style: TextStyle(color: Colors.white38, fontSize: 12)),
              onTap: () {
                Navigator.pop(ctx);
                _activateCoachAiMode('editor', clientId);
              },
            ),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  void _activateCoachAiMode(String mode, String clientId) {
    _socket?.sink.add(jsonEncode({
      "type": "ai_mode_activate",
      "mode": mode,
      "session_id": clientId,
    }));
  }

  // ── Nevedal Report Generator (Coach) ──
  void _showNevedalReportDialog() {
    String reportType = 'individual_coherence';
    String? targetClientId;
    bool generating = false;

    showDialog(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(builder: (sCtx, setLocal) {
          return AlertDialog(
            backgroundColor: const Color(0xFF111111),
            title: const Text(
              'NEVEDAL COHERENCE REPORT',
              style: TextStyle(
                  color: Color(0xFFC9A962),
                  fontFamily: 'Cormorant Garamond',
                  fontSize: 18),
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text("Report Type",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 6),
                  DropdownButtonFormField<String>(
                    value: reportType,
                    dropdownColor: const Color(0xFF111118),
                    items: const [
                      DropdownMenuItem(
                          value: "individual_coherence",
                          child: Text("Individual Coherence",
                              style: TextStyle(color: Colors.white))),
                      DropdownMenuItem(
                          value: "dyad_comparison",
                          child: Text("Dyad Comparison",
                              style: TextStyle(color: Colors.white))),
                      DropdownMenuItem(
                          value: "family_dynamics",
                          child: Text("Family Dynamics",
                              style: TextStyle(color: Colors.white))),
                      DropdownMenuItem(
                          value: "longitudinal_trends",
                          child: Text("Longitudinal Trends",
                              style: TextStyle(color: Colors.white))),
                      DropdownMenuItem(
                          value: "coach_efficacy",
                          child: Text("Coach Efficacy",
                              style: TextStyle(color: Colors.white))),
                    ],
                    onChanged: (v) =>
                        setLocal(() => reportType = v ?? reportType),
                    decoration: InputDecoration(
                      filled: true,
                      fillColor: Colors.white.withOpacity(0.06),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                  const SizedBox(height: 14),
                  const Text("Client",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 6),
                  DropdownButtonFormField<String>(
                    value: targetClientId,
                    dropdownColor: const Color(0xFF111118),
                    hint: const Text("Select client...",
                        style: TextStyle(color: Colors.white38)),
                    items: _clients.map<DropdownMenuItem<String>>((c) {
                      final id = (c['hardware_id'] ?? c['id'] ?? '').toString();
                      final name = (c['name'] ?? id).toString();
                      return DropdownMenuItem(
                          value: id,
                          child: Text(name,
                              style: const TextStyle(color: Colors.white)));
                    }).toList(),
                    onChanged: (v) => setLocal(() => targetClientId = v),
                    decoration: InputDecoration(
                      filled: true,
                      fillColor: Colors.white.withOpacity(0.06),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                  if (generating)
                    const Padding(
                      padding: EdgeInsets.only(top: 16),
                      child: Center(
                          child: CircularProgressIndicator(
                              color: Color(0xFFC9A962))),
                    ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('CANCEL',
                    style: TextStyle(color: Colors.white54)),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFC9A962)),
                onPressed: generating
                    ? null
                    : () async {
                        if (targetClientId == null || targetClientId!.isEmpty) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                                content: Text("Please select a client"),
                                backgroundColor: Colors.orange),
                          );
                          return;
                        }
                        setLocal(() => generating = true);
                        try {
                          final uri = Uri.parse(
                              '$_apiBaseUrl/api/research/nevedal/reports/generate');
                          final resp = await http.post(
                            uri,
                            headers: {
                              'Content-Type': 'application/json',
                              'Authorization':
                                  'Bearer ${widget.currentUserProfile['token']}',
                            },
                            body: jsonEncode({
                              'report_type': reportType,
                              'user_ids': [targetClientId],
                            }),
                          );
                          setLocal(() => generating = false);
                          if (resp.statusCode == 200) {
                            final result = jsonDecode(resp.body);
                            Navigator.pop(ctx);
                            _showNevedalReportResult(result);
                          } else {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                  content:
                                      Text("Report failed: ${resp.statusCode}"),
                                  backgroundColor: Colors.red),
                            );
                          }
                        } catch (e) {
                          setLocal(() => generating = false);
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                                content: Text("Error: $e"),
                                backgroundColor: Colors.red),
                          );
                        }
                      },
                child: const Text('GENERATE',
                    style: TextStyle(color: Colors.black)),
              ),
            ],
          );
        });
      },
    );
  }

  void _showNevedalReportResult(Map<String, dynamic> result) {
    setState(() => _lastNevedalReport = result);

    if (result['status'] == 'no_data') {
      showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: const Text('NO DATA AVAILABLE',
              style: TextStyle(
                  color: Color(0xFFC9A962),
                  fontFamily: 'Cormorant Garamond',
                  fontSize: 16)),
          content: const Text(
            'No coherence measurements found for this client in the selected period. '
            'Data is recorded during live sessions with the Nevedal engine active.',
            style: TextStyle(color: Colors.white70, fontSize: 14, height: 1.5),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('OK',
                    style: TextStyle(color: Color(0xFFC9A962)))),
          ],
        ),
      );
      return;
    }

    final summary = result['summary'];
    final weeklyAverages = result['weekly_averages'] as List<dynamic>? ?? [];
    final userName = result['user_name']?.toString() ?? 'Unknown';
    final periodDays = result['period_days']?.toString() ?? '84';
    final generatedAt = result['generated_at']?.toString() ?? '';
    final reportType =
        result['report_type']?.toString().replaceAll('_', ' ').toUpperCase() ??
            'REPORT';

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: Row(
          children: [
            const Icon(Icons.science, color: Color(0xFF9D4EDD)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(reportType,
                  style: const TextStyle(
                      color: Color(0xFFC9A962),
                      fontFamily: 'Cormorant Garamond',
                      fontSize: 16)),
            ),
          ],
        ),
        content: SizedBox(
          width: double.maxFinite,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Subject: $userName',
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 14,
                        fontWeight: FontWeight.w600)),
                Text('Period: $periodDays days',
                    style:
                        const TextStyle(color: Colors.white54, fontSize: 12)),
                if (generatedAt.isNotEmpty)
                  Text(
                      'Generated: ${generatedAt.substring(0, generatedAt.length > 19 ? 19 : generatedAt.length).replaceAll('T', ' ')}',
                      style:
                          const TextStyle(color: Colors.white38, fontSize: 11)),
                const SizedBox(height: 14),
                if (summary != null && summary is Map) ...[
                  const Text('SUMMARY',
                      style: TextStyle(
                          color: Color(0xFF4ECDC4),
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1.2)),
                  const SizedBox(height: 8),
                  ...((summary as Map<String, dynamic>).entries.map((e) {
                    final label = e.key
                        .toString()
                        .replaceAll('_', ' ')
                        .replaceFirst(e.key[0], e.key[0].toUpperCase());
                    final value = e.value;
                    Color valueColor = Colors.white;
                    if (e.key == 'trend') {
                      valueColor = value == 'improving'
                          ? const Color(0xFF22C55E)
                          : value == 'declining'
                              ? const Color(0xFFEF4444)
                              : const Color(0xFFC9A962);
                    }
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Flexible(
                              child: Text(label,
                                  style: const TextStyle(
                                      color: Colors.white54, fontSize: 13))),
                          Text(
                              value is double
                                  ? value.toStringAsFixed(4)
                                  : value.toString(),
                              style: TextStyle(
                                  color: valueColor,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600)),
                        ],
                      ),
                    );
                  })),
                ],
                if (weeklyAverages.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  const Text('WEEKLY TREND',
                      style: TextStyle(
                          color: Color(0xFF4ECDC4),
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 1.2)),
                  const SizedBox(height: 8),
                  ...weeklyAverages.take(12).map((w) {
                    if (w is! Map) return const SizedBox.shrink();
                    final week = w['week']?.toString() ?? '?';
                    final avg =
                        (w['avg'] is num) ? (w['avg'] as num).toDouble() : 0.0;
                    final count = w['count']?.toString() ?? '0';
                    final barWidth = (avg * 200).clamp(0.0, 200.0);
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        children: [
                          SizedBox(
                              width: 70,
                              child: Text(week,
                                  style: const TextStyle(
                                      color: Colors.white38, fontSize: 11))),
                          Container(
                              width: barWidth,
                              height: 12,
                              decoration: BoxDecoration(
                                color: avg > 0.6
                                    ? const Color(0xFF22C55E)
                                    : avg > 0.3
                                        ? const Color(0xFFC9A962)
                                        : const Color(0xFFEF4444),
                                borderRadius: BorderRadius.circular(3),
                              )),
                          const SizedBox(width: 6),
                          Text('${avg.toStringAsFixed(3)} ($count)',
                              style: const TextStyle(
                                  color: Colors.white54, fontSize: 10)),
                        ],
                      ),
                    );
                  }),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              final reportSummary = summary is Map
                  ? (summary as Map)
                      .entries
                      .map((e) => '${e.key}: ${e.value}')
                      .join(', ')
                  : 'Report generated';
              _sendInsightsChat(
                  'I just generated a ${reportType.toLowerCase()} report for $userName. Summary: $reportSummary. What insights can you share about this?');
            },
            child: const Text('DISCUSS WITH NATE',
                style: TextStyle(color: Color(0xFF4ECDC4))),
          ),
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('CLOSE',
                  style: TextStyle(color: Color(0xFFC9A962)))),
        ],
      ),
    );
  }

  void _showClientBriefSheet() {
    if (_selectedClientBrief == null) return;

    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0F),
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => DraggableScrollableSheet(
        initialChildSize: 0.85,
        minChildSize: 0.5,
        maxChildSize: 0.95,
        expand: false,
        builder: (context, scrollController) =>
            _buildClientBriefContent(scrollController),
      ),
    );
  }

  Widget _buildClientBriefContent(ScrollController scrollController) {
    final brief = _selectedClientBrief!;
    final client = brief['client'] ?? {};
    final metrics = brief['metrics'] ?? {};
    final moodHistory = List<dynamic>.from(brief['mood_history'] ?? []);
    final recentConversations =
        List<dynamic>.from(brief['recent_conversations'] ?? []);
    final recentTopics = List<String>.from(brief['recent_topics'] ?? []);

    return SingleChildScrollView(
      controller: scrollController,
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Handle
          Center(
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: Colors.grey[600],
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
          const SizedBox(height: 20),

          // Header
          Row(
            children: [
              CircleAvatar(
                radius: 30,
                backgroundColor: const Color(0xFF9D4EDD).withOpacity(0.3),
                child: Text(
                  (client['name'] ?? '?')[0].toUpperCase(),
                  style: const TextStyle(
                      color: Color(0xFF9D4EDD),
                      fontWeight: FontWeight.bold,
                      fontSize: 24),
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      client['name'] ?? 'Unknown',
                      style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 22),
                    ),
                    Text(
                      "Client since ${client['joined_date'] ?? 'Unknown'} • ${client['total_sessions'] ?? 0} sessions",
                      style: TextStyle(color: Colors.grey[400], fontSize: 12),
                    ),
                  ],
                ),
              ),
              RiskBadge(riskLevel: metrics['risk_level'] ?? 'LOW', large: true),
            ],
          ),

          const SizedBox(height: 24),

          // PATH-C SENSITIVE PROFILE ENTRY POINT (M215+M216)
          // Layout: MoodIndicator (Happy emoji box, left) + "Sensitive Profile"
          // pill (right). brief['sensitive_bridge_visibility'].button_state:
          //   hidden           → coach not authorized → no pill
          //   enroll_available → coach OK, client not enrolled → muted pill (tap → enroll UI)
          //   active           → enrolled → emphasized pill (tap → profile)
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: MoodIndicator(
                  mood: metrics['mood_current'] ?? 'neutral',
                  trend: metrics['mood_trend'],
                  large: true,
                ),
              ),
              const SizedBox(width: 12),
              _buildSensitiveProfilePill(brief),
            ],
          ),

          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerRight,
            child: _buildIntakeButton(brief),
          ),

          const SizedBox(height: 24),

          // Nevedal metrics
          NevedalMetricsGrid(metrics: metrics),

          const SizedBox(height: 24),

          // Mood history chart
          MoodHistoryChart(moodHistory: moodHistory, height: 150),

          const SizedBox(height: 24),

          // Recent topics
          if (recentTopics.isNotEmpty) ...[
            const Text(
              "RECENT TOPICS",
              style: TextStyle(
                  color: Colors.grey,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5,
                  fontSize: 12),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: recentTopics
                  .map((topic) => Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(
                          color: const Color(0xFF4361EE).withOpacity(0.2),
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                              color: const Color(0xFF4361EE).withOpacity(0.3)),
                        ),
                        child: Text(topic,
                            style: const TextStyle(
                                color: Color(0xFF4361EE), fontSize: 12)),
                      ))
                  .toList(),
            ),
            const SizedBox(height: 24),
          ],

          // Recent conversations (shared threaded log)
          if (recentConversations.isNotEmpty) ...[
            const Text(
              "RECENT CONVERSATIONS",
              style: TextStyle(
                  color: Colors.grey,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5,
                  fontSize: 12),
            ),
            const SizedBox(height: 12),
            ConversationLogView(
              entries: ConversationLogView.parseEntries(recentConversations),
              clientFirstName: ((client['name'] ?? 'Client')
                  .toString()
                  .trim()
                  .split(RegExp(r'\s+'))
                  .first),
              emptyText: 'No recent conversation captured.',
            ),
          ],

          const SizedBox(height: 40),
        ],
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // PATH-C: SENSITIVE PROFILE PILL (M215+M216)
  //
  // Three states from brief['sensitive_bridge_visibility'].button_state:
  //   hidden           → no pill (coach not authorized)
  //   enroll_available → muted pill, onPressed navigates (Path-C enrollment UI)
  //   active           → emphasized pill, onPressed navigates
  // Legacy 'disabled' from older bridges is treated as shrink (fail-closed UI).
  // ---------------------------------------------------------------------------
  Widget _buildSensitiveProfilePill(Map<String, dynamic> brief) {
    final vis = brief['sensitive_bridge_visibility'];
    if (vis is! Map) return const SizedBox.shrink();

    final state = vis['button_state']?.toString() ?? 'hidden';
    final rawClient = vis['client_username'];
    final clientUsername = rawClient == null ? '' : rawClient.toString().trim();

    if (state == 'hidden' || clientUsername.isEmpty) {
      return const SizedBox.shrink();
    }

    final isEnrollAvailable = state == 'enroll_available';
    final isActive = state == 'active';
    if (!isEnrollAvailable && !isActive) {
      return const SizedBox.shrink();
    }

    const Color activeFg = Color(0xFF050505);
    const Color activeBg = Color(0xFF4ECDC4);
    final Color mutedFg = const Color(0xFF4ECDC4).withValues(alpha: 0.85);
    final Color mutedBg = const Color(0xFF4ECDC4).withValues(alpha: 0.14);

    // v1.4 addiction overlay — active/crisis badge on the pill
    final addSummary = vis['addiction_summary'];
    final int addActiveCount =
        (addSummary is Map ? addSummary['active_count'] : 0) ?? 0;
    final int addCrisisCount =
        (addSummary is Map ? addSummary['crisis_count'] : 0) ?? 0;
    final bool hasAddictionAlert = addActiveCount > 0;

    final bool crossActive =
        addSummary is Map && addSummary['cross_addiction_active'] == true;

    String pillLabel;
    if (isEnrollAvailable) {
      pillLabel = 'Sensitive Profile · Enroll';
    } else if (hasAddictionAlert) {
      pillLabel = addCrisisCount > 0
          ? 'Sensitive Profile · $addActiveCount active ($addCrisisCount crisis)'
          : 'Sensitive Profile · $addActiveCount active';
      if (crossActive) pillLabel = '$pillLabel · multi-register';
    } else if (crossActive) {
      pillLabel = 'Sensitive Profile · multi-register';
    } else {
      pillLabel = 'Sensitive Profile';
    }

    String tooltip;
    if (isEnrollAvailable) {
      tooltip = 'Client not enrolled — tap to begin enrollment';
    } else if (hasAddictionAlert) {
      final branches =
          (addSummary is Map ? addSummary['active_branches'] : null);
      final branchStr = branches is List ? branches.join(', ') : '';
      tooltip = 'Active addictions: $branchStr';
      if (crossActive) {
        tooltip = '$tooltip · Cross-addiction flagged in profile.';
      }
    } else if (crossActive) {
      tooltip = 'Cross-addiction flagged — open Sensitive Clinical Profile';
    } else {
      tooltip = 'Open Sensitive Clinical Profile';
    }

    Color pillBg = isActive ? activeBg : mutedBg;
    Color pillFg = isActive ? activeFg : mutedFg;
    if (isActive && addCrisisCount > 0) {
      pillBg = const Color(0xFFEF4444);
      pillFg = Colors.white;
    } else if (isActive && hasAddictionAlert) {
      pillBg = const Color(0xFFF59E0B);
      pillFg = const Color(0xFF050505);
    }

    return Tooltip(
      message: tooltip,
      child: TextButton.icon(
        onPressed: () => _openSensitiveProfile(clientUsername),
        icon: Icon(
          crossActive
              ? Icons.merge_type
              : (hasAddictionAlert
                  ? Icons.warning_amber_rounded
                  : Icons.shield_outlined),
          size: 18,
          color: pillFg,
        ),
        label: Text(
          pillLabel,
          style: TextStyle(
            color: pillFg,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
        style: ButtonStyle(
          backgroundColor: WidgetStateProperty.all(pillBg),
          padding: WidgetStateProperty.all(
            const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          ),
          shape: WidgetStateProperty.all(
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          ),
        ),
      ),
    );
  }

  Widget _buildIntakeButton(Map<String, dynamic> brief) {
    final summary = (brief['intake_summary'] is Map)
        ? (brief['intake_summary'] as Map)
        : const {};
    final pct = (summary['section_1_completion_pct'] is num)
        ? (summary['section_1_completion_pct'] as num).toInt()
        : 0;
    final label = pct <= 0
        ? 'Intake • ○○○○'
        : pct < 25
            ? 'Intake • ◔○○○'
            : pct < 50
                ? 'Intake • ◕◔○○'
                : pct < 75
                    ? 'Intake • ●◕◔○'
                    : pct < 100
                        ? 'Intake • ●●◕◔'
                        : 'Intake • ●●●●';
    return ElevatedButton(
      onPressed: () => _openIntakePanel(brief),
      style: ElevatedButton.styleFrom(
        backgroundColor: const Color(0xFF9D4EDD),
        foregroundColor: Colors.white,
      ),
      child: Text(label),
    );
  }

  void _openIntakePanel(Map<String, dynamic> brief) {
    final visibility = brief['sensitive_bridge_visibility'];
    final usernameFromVisibility =
        (visibility is Map) ? (visibility['client_username'] ?? '').toString() : '';
    final usernameFromClient =
        (brief['client'] is Map) ? (brief['client']['username'] ?? '').toString() : '';
    final clientUsername = usernameFromVisibility.trim().isNotEmpty
        ? usernameFromVisibility.trim()
        : usernameFromClient.trim();
    if (clientUsername.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Intake unavailable: missing client username in brief payload.')),
      );
      return;
    }
    final token = (widget.currentUserProfile['token'] ?? '').toString();
    final displayName = ((brief['client'] is Map) ? (brief['client']['name'] ?? '') : '').toString();
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => IntakeFormCoachPanel(
          clientUsername: clientUsername,
          token: token,
          clientDisplayName: displayName.isEmpty ? clientUsername : displayName,
        ),
      ),
    );
  }

  Future<void> _openSensitiveProfile(String clientUsername) async {
    // Emit audit event BEFORE navigating so the row is durable even if the
    // coach immediately backs out. payload mirrors bridge handler contract.
    try {
      _socket?.sink.add(jsonEncode({
        "type": "sensitive_profile_screen_opened",
        "client_id": clientUsername,
        "entry_point": "coach_command_briefings_view_brief",
      }));
    } catch (_) {}
    if (!mounted) return;
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => SensitiveClinicalProfileScreen(
        currentUserProfile: widget.currentUserProfile,
        targetUserId: clientUsername,
        closeBriefSheetOnExit: true,
      ),
    ));
  }

  @override
  void dispose() {
    _cancelClassroomVideoPoll();
    _messageRelay.close();
    _dojoResponseController.dispose();
    _dojoScrollController.dispose();
    _liveNotes.dispose();
    _liveObservations.dispose();
    try {
      _liveNoteSpeech.stop();
    } catch (_) {}
    try {
      _liveNoteSpeech.cancel();
    } catch (_) {}
    _assistantChatController.dispose();
    _assistantChatScrollController.dispose();
    _dojoBackUnregister?.call();
    if (kIsWeb) disposeDojoIframe();
    _tabController.dispose();
    _wsReconnectTimer?.cancel();
    _socket?.sink.close();
    super.dispose();
  }

  // Tab labels for mobile dropdown
  static const _tabLabels = [
    "CLIENTS",
    "SCHEDULE",
    "INSIGHTS",
    "BRIEFINGS",
    "DOJO",
    "CLASSROOM",
    "TRAINING",
    "FINANCIALS",
    "FOLDER",
    "ASSISTANTS"
  ];
  static const _tabIcons = [
    Icons.people,
    Icons.calendar_today,
    Icons.insights,
    Icons.folder_shared,
    Icons.sports_martial_arts,
    Icons.school,
    Icons.fitness_center,
    Icons.account_balance_wallet,
    Icons.folder_copy,
    Icons.supervisor_account
  ];

  @override
  Widget build(BuildContext context) {
    final isMobile = MediaQuery.of(context).size.width < 768;

    final scaffold = Scaffold(
      backgroundColor: const Color(0xFF0A0A0F),
      appBar: AppBar(
        title: isMobile
            ? _buildMobileNavDropdown()
            : const Text(
                "COACH COMMAND",
                style: TextStyle(
                    fontFamily: 'Courier',
                    color: Color(0xFFFFD700),
                    fontWeight: FontWeight.bold,
                    letterSpacing: 2),
              ),
        backgroundColor: Colors.transparent,
        elevation: 0,
        toolbarHeight: isMobile ? 56 : kToolbarHeight,
        bottom: isMobile
            ? null // No tab bar on mobile — using dropdown instead
            : TabBar(
                controller: _tabController,
                indicatorColor: const Color(0xFFFFD700),
                labelColor: const Color(0xFFFFD700),
                unselectedLabelColor: Colors.grey,
                isScrollable: true,
                tabs: const [
                  Tab(icon: Icon(Icons.people), text: "CLIENTS"),
                  Tab(icon: Icon(Icons.calendar_today), text: "SCHEDULE"),
                  Tab(icon: Icon(Icons.insights), text: "INSIGHTS"),
                  Tab(icon: Icon(Icons.folder_shared), text: "BRIEFINGS"),
                  Tab(icon: Icon(Icons.sports_martial_arts), text: "DOJO"),
                  Tab(icon: Icon(Icons.school), text: "CLASSROOM"),
                  Tab(icon: Icon(Icons.fitness_center), text: "TRAINING"),
                  Tab(
                      icon: Icon(Icons.account_balance_wallet),
                      text: "FINANCIALS"),
                  Tab(icon: Icon(Icons.folder_copy), text: "FOLDER"),
                  Tab(icon: Icon(Icons.supervisor_account), text: "ASSISTANTS"),
                ],
              ),
        actions: [
          if (!isMobile)
            IconButton(
              tooltip: "Connection",
              icon: const Icon(Icons.wifi, color: Colors.grey),
              onPressed: _showConnectionInfo,
            ),
          IconButton(
              icon: Icon(Icons.refresh,
                  color: Colors.grey, size: isMobile ? 20 : 24),
              onPressed: () {
                setState(() => _isLoading = true);
                _fetchDashboard();
              }),
          IconButton(
            icon: Icon(Icons.settings,
                color: const Color(0xFFC9A962), size: isMobile ? 20 : 24),
            tooltip: 'Settings',
            onPressed: () {
              Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => CoachSettingsScreen(
                      profile: widget.currentUserProfile ?? {},
                      socket: _socket,
                      messageStream: _messageRelay.stream,
                      onLogout: () {
                        _socket?.sink.close();
                      },
                    ),
                  ));
            },
          ),
          IconButton(
            icon:
                Icon(Icons.logout, color: Colors.red, size: isMobile ? 20 : 24),
            onPressed: () {
              _socket?.sink.close();
              Navigator.of(context).pushReplacement(
                  MaterialPageRoute(builder: (_) => const LobbyScreen()));
            },
          )
        ],
      ),
      body: _isLoading
          ? Center(
              child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const CircularProgressIndicator(color: Color(0xFFFFD700)),
                const SizedBox(height: 20),
                Text(_statusMessage, style: const TextStyle(color: Colors.grey))
              ],
            ))
          : TabBarView(
              controller: _tabController,
              physics: isMobile ? const NeverScrollableScrollPhysics() : null,
              children: [
                _buildClientsTab(),
                _buildScheduleTab(),
                _buildInsightsTab(),
                _buildBriefingsTab(),
                _CoachDojoTabKeepAlive(builder: _buildDojoTab),
                _buildClassroomTab(),
                _buildTrainingTab(),
                _buildFinancialsTab(),
                _buildFolderTab(),
                _buildAssistantsTab(),
              ],
            ),
    );

    return Stack(
      children: [
        scaffold,
        _buildSessionAssistantOverlay(),
        if (_activeConsultationId != null) _buildConsultationTimerOverlay(),
      ],
    );
  }

  Widget _buildConsultationTimerOverlay() {
    final remaining = _consultationRemainingSeconds;
    final minutes = remaining ~/ 60;
    final seconds = remaining % 60;
    final progress = remaining / 900.0;
    final isUrgent = remaining <= 60;
    final barColor = isUrgent
        ? Colors.red
        : remaining <= 300
            ? Colors.orange
            : const Color(0xFF4ECDC4);

    return Positioned(
      top: 0,
      left: 0,
      right: 0,
      child: SafeArea(
        child: Column(
          children: [
            Container(
              margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: barColor.withOpacity(0.6)),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      Icon(Icons.timer, color: barColor, size: 18),
                      const SizedBox(width: 8),
                      Text(
                        'FREE CONSULTATION',
                        style: TextStyle(
                          color: barColor,
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1,
                        ),
                      ),
                      const Spacer(),
                      Text(
                        '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}',
                        style: TextStyle(
                          color: barColor,
                          fontSize: 20,
                          fontWeight: FontWeight.bold,
                          fontFamily: 'Courier',
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: LinearProgressIndicator(
                      value: progress.clamp(0.0, 1.0),
                      backgroundColor: Colors.grey[900],
                      valueColor: AlwaysStoppedAnimation<Color>(barColor),
                      minHeight: 4,
                    ),
                  ),
                  if (_consultationWarningMessage != null) ...[
                    const SizedBox(height: 6),
                    Text(
                      _consultationWarningMessage!,
                      style: TextStyle(
                        color: isUrgent ? Colors.red : Colors.orange,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMobileNavDropdown() {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text(
          "COACH ",
          style: TextStyle(
              fontFamily: 'Courier',
              color: Color(0xFFFFD700),
              fontWeight: FontWeight.bold,
              fontSize: 13,
              letterSpacing: 1),
        ),
        GestureDetector(
          key: _tabMenuButtonKey,
          onTap: () async {
            // Disable pointer events on iframes to prevent platform view z-index conflicts.
            // The iframe stays alive (preserving DOJO session state) but can't steal taps
            // from the Flutter popup menu overlay.
            setDojoIframePointerEvents(false);

            final RenderBox button = _tabMenuButtonKey.currentContext!
                .findRenderObject() as RenderBox;
            final RenderBox overlay = Navigator.of(context)
                .overlay!
                .context
                .findRenderObject() as RenderBox;
            final buttonPos =
                button.localToGlobal(Offset.zero, ancestor: overlay);
            final buttonSize = button.size;

            final selected = await showMenu<int>(
              context: context,
              color: const Color(0xFF1A1A2E),
              position: RelativeRect.fromLTRB(
                buttonPos.dx,
                buttonPos.dy + buttonSize.height,
                overlay.size.width - buttonPos.dx - buttonSize.width,
                0,
              ),
              items: List.generate(
                  _tabLabels.length,
                  (i) => PopupMenuItem<int>(
                        value: i,
                        height: 40,
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(_tabIcons[i],
                                color: _tabController.index == i
                                    ? const Color(0xFFFFD700)
                                    : Colors.grey,
                                size: 16),
                            const SizedBox(width: 8),
                            Text(
                              _tabLabels[i],
                              style: TextStyle(
                                color: _tabController.index == i
                                    ? const Color(0xFFFFD700)
                                    : Colors.white,
                                fontFamily: 'Courier',
                                fontWeight: FontWeight.bold,
                                fontSize: 12,
                              ),
                            ),
                            if (_tabController.index == i) ...[
                              const SizedBox(width: 6),
                              const Text("✓",
                                  style: TextStyle(
                                      color: Color(0xFFFFD700), fontSize: 12)),
                            ],
                          ],
                        ),
                      )),
            );

            // Re-enable pointer events on iframes after menu closes
            setDojoIframePointerEvents(true);

            if (selected != null) {
              setState(() => _tabController.animateTo(selected));
            }
          },
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: const Color(0xFFFFD700).withOpacity(0.15),
              borderRadius: BorderRadius.circular(6),
              border:
                  Border.all(color: const Color(0xFFFFD700).withOpacity(0.4)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(_tabIcons[_tabController.index],
                    color: const Color(0xFFFFD700), size: 16),
                const SizedBox(width: 6),
                Text(
                  _tabLabels[_tabController.index],
                  style: const TextStyle(
                      color: Color(0xFFFFD700),
                      fontFamily: 'Courier',
                      fontWeight: FontWeight.bold,
                      fontSize: 12),
                ),
                const Icon(Icons.arrow_drop_down,
                    color: Color(0xFFFFD700), size: 18),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildClientsTab() {
    if (_clients.isEmpty) {
      return const Center(
        child:
            Text("No clients assigned", style: TextStyle(color: Colors.grey)),
      );
    }

    final folders = _buildFolderGroups();
    return Column(
      children: [
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
          child: _buildClientSearchAndFilter(),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            itemCount: folders.length,
            itemBuilder: (context, index) {
              final f = folders[index];
              final title = (f['label'] ?? 'Folder').toString();
              final subtitle = (f['subtitle'] ?? '').toString();
              final risk = (f['risk_level'] ?? 'LOW').toString();
              final folderType = (f['folder_type'] ?? 'family').toString();

              // Type-appropriate icon
              IconData folderIcon;
              Color iconColor;
              switch (folderType) {
                case 'company':
                  folderIcon = Icons.business;
                  iconColor = const Color(0xFF4ECDC4);
                  break;
                case 'coach_only':
                  folderIcon = Icons.calendar_today;
                  iconColor = const Color(0xFFC9A962);
                  break;
                default:
                  folderIcon = Icons.folder;
                  iconColor = const Color(0xFF9D4EDD);
              }

              return Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF16213E),
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: Colors.white10),
                ),
                child: Row(
                  children: [
                    CircleAvatar(
                      backgroundColor: iconColor.withOpacity(0.25),
                      child: Icon(folderIcon, color: iconColor),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Flexible(
                                child: Text(
                                  title,
                                  style: const TextStyle(
                                      color: Colors.white,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 15),
                                ),
                              ),
                              if (f['subscription_plan'] != null &&
                                  f['subscription_plan']
                                      .toString()
                                      .isNotEmpty) ...[
                                const SizedBox(width: 6),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 6, vertical: 2),
                                  decoration: BoxDecoration(
                                    color: const Color(0xFFC9A962)
                                        .withOpacity(0.15),
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: Text(
                                    f['subscription_plan'].toString(),
                                    style: const TextStyle(
                                        color: Color(0xFFC9A962),
                                        fontSize: 8,
                                        fontWeight: FontWeight.w600),
                                  ),
                                ),
                              ],
                            ],
                          ),
                          const SizedBox(height: 4),
                          Text(
                            subtitle,
                            style: TextStyle(
                                color: Colors.grey[400], fontSize: 11),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    RiskBadge(riskLevel: risk),
                    const SizedBox(width: 8),
                    TextButton(
                      onPressed: () {
                        _openFolder(
                          folderId: f['folder_id'],
                          label: f['label'],
                          familyId: f['family_id'],
                          clients: List<Map<String, dynamic>>.from(
                              f['clients'] ?? []),
                        );
                        _tabController.animateTo(8); // FOLDER
                      },
                      style: TextButton.styleFrom(
                        foregroundColor: const Color(0xFFFFD700),
                      ),
                      child: const Text("Open Folder"),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildScheduleTab() {
    final bool hasPending = _pendingBookings.isNotEmpty;
    final Widget content = ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // ===== AVAILABILITY SUMMARY + CALENDAR (always visible) =====
        _buildAvailabilitySummaryCard(),
        CalendarToolbar(
          view: _calView,
          focusedDate: _calFocusedDate,
          onViewChanged: (v) => setState(() => _calView = v),
          onDateChanged: (d) => setState(() {
            _calFocusedDate = d;
            _calMonth = DateTime(d.year, d.month, 1);
          }),
        ),
        const SizedBox(height: 8),
        if (_calView == CalendarView.month)
          _buildCalendarGrid()
        else
          SizedBox(height: 480, child: _buildCoachSwitchedCalendar()),

        // ===== INBOUND COACH REQUESTS =====
        if (_inboundRequests.isNotEmpty) ...[
          Container(
            margin: const EdgeInsets.only(bottom: 16),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFF0A1A1A),
              borderRadius: BorderRadius.circular(16),
              border:
                  Border.all(color: const Color(0xFFC9A962).withOpacity(0.4)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Icon(Icons.person_add,
                      color: Color(0xFFC9A962), size: 20),
                  const SizedBox(width: 8),
                  Text(
                    "CLIENT REQUESTS (${_inboundRequests.length})",
                    style: const TextStyle(
                        color: Color(0xFFC9A962),
                        fontWeight: FontWeight.bold,
                        fontFamily: 'Courier',
                        fontSize: 13,
                        letterSpacing: 1),
                  ),
                ]),
                const SizedBox(height: 12),
                ..._inboundRequests.map((req) {
                  final reqId = (req['request_id'] ?? '').toString();
                  final clientName =
                      (req['client_name'] ?? 'Client').toString();
                  final intakeNote = (req['intake_note'] ?? '').toString();
                  final daysElapsed = (req['days_elapsed'] ?? 0) as int;
                  final nudgeCount = (req['nudge_count'] ?? 0) as int;
                  return Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFF0A0A0F),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          const Icon(Icons.person,
                              color: Color(0xFF4ECDC4), size: 18),
                          const SizedBox(width: 8),
                          Expanded(
                              child: Text(clientName,
                                  style: const TextStyle(
                                      color: Colors.white,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 15))),
                          if (nudgeCount > 0)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                  color:
                                      const Color(0xFFC9A962).withOpacity(0.2),
                                  borderRadius: BorderRadius.circular(8)),
                              child: Text("${nudgeCount}x nudged",
                                  style: const TextStyle(
                                      color: Color(0xFFC9A962),
                                      fontSize: 10,
                                      fontWeight: FontWeight.bold)),
                            ),
                        ]),
                        if (intakeNote.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Text(intakeNote,
                              maxLines: 3,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                  color: Colors.grey[400], fontSize: 13)),
                        ],
                        const SizedBox(height: 4),
                        Text("${daysElapsed}d ago",
                            style: TextStyle(
                                color: Colors.grey[600], fontSize: 11)),
                        const SizedBox(height: 12),
                        Row(children: [
                          Expanded(
                              child: ElevatedButton.icon(
                            icon: const Icon(Icons.check, size: 18),
                            label: const Text("Accept"),
                            style: ElevatedButton.styleFrom(
                                backgroundColor:
                                    const Color(0xFF4ECDC4).withOpacity(0.2),
                                foregroundColor: const Color(0xFF4ECDC4),
                                side:
                                    const BorderSide(color: Color(0xFF4ECDC4)),
                                padding:
                                    const EdgeInsets.symmetric(vertical: 12)),
                            onPressed: () => _socket?.sink.add(jsonEncode({
                              "type": "coach_accept_request",
                              "request_id": reqId
                            })),
                          )),
                          const SizedBox(width: 8),
                          Expanded(
                              child: OutlinedButton.icon(
                            icon: const Icon(Icons.message, size: 16),
                            label: const Text("Message"),
                            style: OutlinedButton.styleFrom(
                                foregroundColor: const Color(0xFFC9A962),
                                side:
                                    const BorderSide(color: Color(0xFFC9A962)),
                                padding:
                                    const EdgeInsets.symmetric(vertical: 12)),
                            onPressed: () =>
                                _showCoachMessageDialog(reqId, clientName),
                          )),
                          const SizedBox(width: 8),
                          IconButton(
                            icon: const Icon(Icons.close,
                                color: Colors.redAccent, size: 20),
                            tooltip: "Decline",
                            onPressed: () => _showCoachDeclineDialog(reqId),
                          ),
                        ]),
                      ],
                    ),
                  );
                }).toList(),
              ],
            ),
          ),
        ],
        // ===== PENDING BOOKINGS APPROVAL SECTION =====
        if (hasPending) ...[
          Container(
            margin: const EdgeInsets.only(bottom: 16),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A0A),
              borderRadius: BorderRadius.circular(16),
              border:
                  Border.all(color: const Color(0xFFFFD700).withOpacity(0.4)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.pending_actions,
                        color: Color(0xFFFFD700), size: 20),
                    const SizedBox(width: 8),
                    Text(
                      "AWAITING YOUR APPROVAL (${_pendingBookings.length})",
                      style: const TextStyle(
                        color: Color(0xFFFFD700),
                        fontWeight: FontWeight.bold,
                        fontFamily: 'Courier',
                        fontSize: 13,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                ..._pendingBookings.map((booking) {
                  final bookingSessionId =
                      (booking['session_id'] ?? '').toString();
                  final clientName =
                      (booking['client_name'] ?? 'Client').toString();
                  final notes = (booking['notes'] ?? '').toString();
                  final zoomLink = (booking['zoom_link'] ?? '').toString();
                  final sessionType =
                      (booking['session_type'] ?? 'COACH').toString();
                  final platform = (booking['platform'] ?? 'Zoom').toString();
                  final scheduledStart =
                      (booking['scheduled_start'] ?? '').toString();
                  String date = (booking['date'] ?? '').toString();
                  String time = (booking['time'] ?? '').toString();
                  try {
                    if (scheduledStart.isNotEmpty) {
                      final dt = DateTime.parse(scheduledStart).toLocal();
                      const months = [
                        '',
                        'Jan',
                        'Feb',
                        'Mar',
                        'Apr',
                        'May',
                        'Jun',
                        'Jul',
                        'Aug',
                        'Sep',
                        'Oct',
                        'Nov',
                        'Dec'
                      ];
                      const weekdays = [
                        'Mon',
                        'Tue',
                        'Wed',
                        'Thu',
                        'Fri',
                        'Sat',
                        'Sun'
                      ];
                      date =
                          '${weekdays[dt.weekday - 1]}, ${months[dt.month]} ${dt.day}, ${dt.year}';
                      final h12 = dt.hour == 0
                          ? 12
                          : (dt.hour > 12 ? dt.hour - 12 : dt.hour);
                      final ap = dt.hour >= 12 ? 'PM' : 'AM';
                      time = '$h12:${dt.minute.toString().padLeft(2, '0')} $ap';
                    }
                  } catch (_) {}
                  final duration =
                      (booking['duration'] ?? booking['duration_minutes'] ?? 50)
                          .toString();
                  final coachFee = (booking['coach_fee'] is num)
                      ? (booking['coach_fee'] as num).toDouble()
                      : 0.0;
                  final platformFee = (booking['platform_fee'] is num)
                      ? (booking['platform_fee'] as num).toDouble()
                      : 0.0;
                  final coachNet = coachFee - platformFee;

                  return Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFF0A0A0F),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.person,
                                color: Color(0xFF4ECDC4), size: 18),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                clientName,
                                style: const TextStyle(
                                    color: Colors.white,
                                    fontWeight: FontWeight.bold,
                                    fontSize: 15),
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 8, vertical: 3),
                              decoration: BoxDecoration(
                                color:
                                    const Color(0xFFFFD700).withOpacity(0.15),
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: const Text("PENDING",
                                  style: TextStyle(
                                      color: Color(0xFFFFD700),
                                      fontSize: 10,
                                      fontWeight: FontWeight.bold)),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            const Icon(Icons.event,
                                color: Color(0xFFC9A962), size: 14),
                            const SizedBox(width: 6),
                            Expanded(
                                child: Text(date,
                                    style: TextStyle(
                                        color: Colors.grey[300],
                                        fontSize: 12.5,
                                        fontWeight: FontWeight.w600))),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Row(
                          children: [
                            const Icon(Icons.access_time,
                                color: Color(0xFFC9A962), size: 14),
                            const SizedBox(width: 6),
                            Expanded(
                                child: Text(
                                    '$time  •  $duration min  •  $sessionType  •  $platform',
                                    style: TextStyle(
                                        color: Colors.grey[400],
                                        fontSize: 12))),
                          ],
                        ),
                        if (notes.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          Container(
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: const Color(0xFF111111),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Icon(Icons.notes,
                                    color: Color(0xFF9D4EDD), size: 14),
                                const SizedBox(width: 6),
                                Expanded(
                                    child: Text(notes,
                                        style: TextStyle(
                                            color: Colors.grey[300],
                                            fontSize: 12,
                                            fontStyle: FontStyle.italic))),
                              ],
                            ),
                          ),
                        ],
                        if (zoomLink.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Row(
                            children: [
                              const Icon(Icons.videocam,
                                  color: Color(0xFF2D8CFF), size: 13),
                              const SizedBox(width: 6),
                              Expanded(
                                  child: Text('Zoom link prepared',
                                      style: TextStyle(
                                          color: Colors.grey[500],
                                          fontSize: 11))),
                            ],
                          ),
                        ],
                        if (coachFee > 0) ...[
                          const SizedBox(height: 10),
                          Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: const Color(0xFF111111),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    children: [
                                      Text("\$${coachFee.toStringAsFixed(2)}",
                                          style: const TextStyle(
                                              color: Colors.white,
                                              fontWeight: FontWeight.bold,
                                              fontSize: 14)),
                                      const Text("Session Fee",
                                          style: TextStyle(
                                              color: Colors.grey,
                                              fontSize: 10)),
                                    ],
                                  ),
                                ),
                                Container(
                                    width: 1,
                                    height: 30,
                                    color: Colors.white10),
                                Expanded(
                                  child: Column(
                                    children: [
                                      Text(
                                          "-\$${platformFee.toStringAsFixed(2)}",
                                          style: const TextStyle(
                                              color: Colors.redAccent,
                                              fontWeight: FontWeight.bold,
                                              fontSize: 14)),
                                      const Text("Platform Fee",
                                          style: TextStyle(
                                              color: Colors.grey,
                                              fontSize: 10)),
                                    ],
                                  ),
                                ),
                                Container(
                                    width: 1,
                                    height: 30,
                                    color: Colors.white10),
                                Expanded(
                                  child: Column(
                                    children: [
                                      Text("\$${coachNet.toStringAsFixed(2)}",
                                          style: const TextStyle(
                                              color: Color(0xFF4ECDC4),
                                              fontWeight: FontWeight.bold,
                                              fontSize: 14)),
                                      const Text("Your Net",
                                          style: TextStyle(
                                              color: Colors.grey,
                                              fontSize: 10)),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            Expanded(
                              child: ElevatedButton.icon(
                                icon: const Icon(Icons.check, size: 18),
                                label: const Text("Approve"),
                                style: ElevatedButton.styleFrom(
                                  backgroundColor:
                                      const Color(0xFF4ECDC4).withOpacity(0.2),
                                  foregroundColor: const Color(0xFF4ECDC4),
                                  side: const BorderSide(
                                      color: Color(0xFF4ECDC4)),
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 12),
                                ),
                                onPressed: () =>
                                    _approveBooking(bookingSessionId),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: OutlinedButton.icon(
                                icon: const Icon(Icons.close, size: 18),
                                label: const Text("Decline"),
                                style: OutlinedButton.styleFrom(
                                  side:
                                      const BorderSide(color: Colors.redAccent),
                                  foregroundColor: Colors.redAccent,
                                  padding:
                                      const EdgeInsets.symmetric(vertical: 12),
                                ),
                                onPressed: () =>
                                    _showDeclineDialog(bookingSessionId),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  );
                }).toList(),
              ],
            ),
          ),
        ],
        // ===== CONFIRMED SESSIONS =====
        if (_schedule.isNotEmpty) ...[
          if (hasPending) ...[
            const Padding(
              padding: EdgeInsets.only(bottom: 12),
              child: Text("CONFIRMED SESSIONS",
                  style: TextStyle(
                      color: Colors.white54,
                      fontFamily: 'Courier',
                      fontSize: 12,
                      letterSpacing: 1)),
            ),
          ],
          ..._schedule.asMap().entries.map((entry) {
            final index = entry.key;
            final raw = entry.value;
            final session = (raw is Map)
                ? Map<String, dynamic>.from(raw)
                : <String, dynamic>{};
            final sessionId =
                (session['id'] ?? session['session_id'] ?? 'idx_$index')
                    .toString();
            final isConsult = _isCoachExternalConsultation(session);
            final displayName = isConsult
                ? (session['consultation_name'] ??
                        session['client_name'] ??
                        session['client'] ??
                        'Consultee')
                    .toString()
                : (session['client_name'] ??
                        session['client'] ??
                        session['client_id'] ??
                        'Session')
                    .toString();
            final date = (session['date'] ?? '').toString();
            final time = _formatScheduledTime(session); // COACH-SCHEDULE-LOCAL
            final consultSubject =
                (session['consultation_subject'] ?? '').toString().trim();
            final meetingUrl =
                (session['zoom_link'] ?? session['meeting_url'] ?? '')
                    .toString();
            final zoomHostUrl = (session['zoom_host_url'] ?? '').toString();
            final zoomMeetingId = (session['zoom_meeting_id'] ?? '').toString();
            const consultAccent = Color(0xFF9D4EDD);
            const consultBorder = Color(0xFF7C3AED);

            if (isConsult) {
              return Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF1F1528),
                  borderRadius: BorderRadius.circular(16),
                  border:
                      Border.all(color: consultBorder.withValues(alpha: 0.65)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.person_search,
                            color: consultAccent, size: 22),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: consultAccent.withValues(alpha: 0.2),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(
                                color: consultAccent.withValues(alpha: 0.5)),
                          ),
                          child: const Text(
                            'Consultation',
                            style: TextStyle(
                              color: consultAccent,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                              letterSpacing: 0.6,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Text(
                      displayName,
                      style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 16),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (consultSubject.isNotEmpty) ...[
                      const SizedBox(height: 6),
                      Text(
                        consultSubject,
                        style: TextStyle(color: Colors.grey[400], fontSize: 12),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                    const SizedBox(height: 6),
                    Text(
                      [date, time]
                          .where((s) => s.trim().isNotEmpty)
                          .join(' at '),
                      style: TextStyle(color: Colors.grey[400], fontSize: 12),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: ElevatedButton.icon(
                            icon: const Icon(Icons.videocam, size: 18),
                            label: const Text('Start Zoom'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor:
                                  consultAccent.withValues(alpha: 0.22),
                              foregroundColor: consultAccent,
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              side: const BorderSide(
                                  color: consultAccent, width: 0.8),
                            ),
                            onPressed: () =>
                                _launchZoomMeeting(zoomHostUrl, meetingUrl),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: OutlinedButton.icon(
                            icon: const Icon(Icons.event_busy, size: 18),
                            label: const Text('Cancel'),
                            style: OutlinedButton.styleFrom(
                              side: const BorderSide(color: Colors.redAccent),
                              foregroundColor: Colors.redAccent,
                              padding: const EdgeInsets.symmetric(vertical: 12),
                            ),
                            onPressed: () =>
                                _cancelConsultationSession(session),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            }

            return Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A2E),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: Colors.white10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.videocam, color: Color(0xFF00F5D4)),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          displayName,
                          style: const TextStyle(
                              color: Colors.white, fontWeight: FontWeight.bold),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    [date, time].where((s) => s.trim().isNotEmpty).join(' at '),
                    style: TextStyle(color: Colors.grey[400], fontSize: 12),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton.icon(
                          icon: const Icon(Icons.videocam, size: 18),
                          label: const Text("Start Zoom"),
                          style: ElevatedButton.styleFrom(
                            backgroundColor:
                                const Color(0xFF00F5D4).withOpacity(0.18),
                            foregroundColor: const Color(0xFF00F5D4),
                            padding: const EdgeInsets.symmetric(vertical: 12),
                            side: const BorderSide(
                                color: Color(0xFF00F5D4), width: 0.8),
                          ),
                          onPressed: () =>
                              _launchZoomMeeting(zoomHostUrl, meetingUrl),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: OutlinedButton.icon(
                          icon: const Icon(Icons.folder_open, size: 18),
                          label: const Text("Open Briefing"),
                          style: OutlinedButton.styleFrom(
                            side: const BorderSide(color: Color(0xFFFFD700)),
                            foregroundColor: const Color(0xFFFFD700),
                            padding: const EdgeInsets.symmetric(vertical: 12),
                          ),
                          onPressed: () {
                            _openBriefingsForSession(session);
                            _tabController.animateTo(3);
                          },
                        ),
                      ),
                      // Always show the 3-dot menu for session management
                      const SizedBox(width: 10),
                      PopupMenuButton<String>(
                        tooltip: "Session actions",
                        color: const Color(0xFF0A0A0F),
                        icon:
                            const Icon(Icons.more_vert, color: Colors.white70),
                        onSelected: (v) async {
                          if (v == "resend_link") {
                            await _resendSessionLink(sessionId);
                          }
                          if (v == "check_status") {
                            await _showRecordingStatus(sessionId);
                          }
                          if (v == "archive_transcript") {
                            final ok = await showDialog<bool>(
                              context: context,
                              builder: (ctx) => AlertDialog(
                                backgroundColor: const Color(0xFF0A0A0F),
                                title: const Text("Archive transcript?",
                                    style: TextStyle(color: Color(0xFF00F5D4))),
                                content: const Text(
                                  "This will attempt to save ONLY transcript artifacts (VTT/CC) and delete Zoom recordings to avoid storage waste.",
                                  style: TextStyle(color: Colors.white70),
                                ),
                                actions: [
                                  TextButton(
                                      onPressed: () =>
                                          Navigator.pop(ctx, false),
                                      child: const Text("Cancel",
                                          style:
                                              TextStyle(color: Colors.grey))),
                                  ElevatedButton(
                                    style: ElevatedButton.styleFrom(
                                        backgroundColor:
                                            const Color(0xFFFFD700),
                                        foregroundColor: Colors.black),
                                    onPressed: () => Navigator.pop(ctx, true),
                                    child: const Text("Archive"),
                                  ),
                                ],
                              ),
                            );
                            if (ok == true)
                              await _archiveZoomTranscriptForSession(sessionId);
                          }
                          if (v == "delete_meeting") {
                            final ok = await showDialog<bool>(
                              context: context,
                              builder: (ctx) => AlertDialog(
                                backgroundColor: const Color(0xFF0A0A0F),
                                title: const Text("Delete Zoom meeting?",
                                    style: TextStyle(color: Color(0xFF00F5D4))),
                                content: const Text(
                                  "This deletes the meeting object in Zoom. Recommended after you’ve archived the transcript.",
                                  style: TextStyle(color: Colors.white70),
                                ),
                                actions: [
                                  TextButton(
                                      onPressed: () =>
                                          Navigator.pop(ctx, false),
                                      child: const Text("Cancel",
                                          style:
                                              TextStyle(color: Colors.grey))),
                                  ElevatedButton(
                                    style: ElevatedButton.styleFrom(
                                        backgroundColor: Colors.redAccent,
                                        foregroundColor: Colors.white),
                                    onPressed: () => Navigator.pop(ctx, true),
                                    child: const Text("Delete"),
                                  ),
                                ],
                              ),
                            );
                            if (ok == true)
                              await _deleteZoomMeetingForSession(sessionId);
                          }
                          if (v == "delete_session") {
                            final ok = await showDialog<bool>(
                              context: context,
                              builder: (ctx) => AlertDialog(
                                backgroundColor: const Color(0xFF0A0A0F),
                                title: const Text("Delete Session?",
                                    style: TextStyle(color: Colors.redAccent)),
                                content: const Text(
                                  "This will permanently remove this session from the schedule. This cannot be undone.",
                                  style: TextStyle(color: Colors.white70),
                                ),
                                actions: [
                                  TextButton(
                                      onPressed: () =>
                                          Navigator.pop(ctx, false),
                                      child: const Text("Cancel",
                                          style:
                                              TextStyle(color: Colors.grey))),
                                  ElevatedButton(
                                    style: ElevatedButton.styleFrom(
                                        backgroundColor: Colors.redAccent,
                                        foregroundColor: Colors.white),
                                    onPressed: () => Navigator.pop(ctx, true),
                                    child: const Text("Delete"),
                                  ),
                                ],
                              ),
                            );
                            if (ok == true)
                              await _deleteSessionPermanently(sessionId);
                          }
                        },
                        itemBuilder: (ctx) => [
                          // Only show Zoom options if there's a Zoom meeting ID
                          if (zoomMeetingId.trim().isNotEmpty) ...[
                            const PopupMenuItem(
                              value: "resend_link",
                              child: Row(
                                children: [
                                  Icon(Icons.send,
                                      size: 18, color: Color(0xFFC9A962)),
                                  SizedBox(width: 8),
                                  Text("Resend Zoom Link",
                                      style:
                                          TextStyle(color: Color(0xFFC9A962))),
                                ],
                              ),
                            ),
                            const PopupMenuDivider(),
                            const PopupMenuItem(
                              value: "check_status",
                              child: Row(
                                children: [
                                  Icon(Icons.info_outline,
                                      size: 18, color: Color(0xFF00F5D4)),
                                  SizedBox(width: 8),
                                  Text("Check Recording Status",
                                      style:
                                          TextStyle(color: Color(0xFF00F5D4))),
                                ],
                              ),
                            ),
                            const PopupMenuItem(
                              value: "archive_transcript",
                              child: Text("Archive Transcript",
                                  style: TextStyle(color: Colors.white)),
                            ),
                            const PopupMenuItem(
                              value: "delete_meeting",
                              child: Text("Delete Zoom Meeting",
                                  style: TextStyle(color: Colors.white)),
                            ),
                            const PopupMenuDivider(),
                          ],
                          // Always show delete session option
                          const PopupMenuItem(
                            value: "delete_session",
                            child: Text("Delete Session",
                                style: TextStyle(color: Colors.redAccent)),
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      icon: const Icon(Icons.play_arrow),
                      label: const Text("Start Live Session"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFFFD700),
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                      onPressed: () => _startLiveSession(session),
                    ),
                  ),
                ],
              ),
            );
          }).toList(),
        ],
      ],
    );

    return Stack(
      children: [
        content,
        Positioned(
          right: 16,
          bottom: 16,
          child: FloatingActionButton.extended(
            backgroundColor: const Color(0xFFFFD700),
            foregroundColor: Colors.black,
            icon: const Icon(Icons.add),
            label: const Text("Create Session"),
            onPressed: _openCreateSessionDialog,
          ),
        ),
        Positioned(
          right: 16,
          bottom: 80,
          child: FloatingActionButton.extended(
            backgroundColor: const Color(0xFFC9A962),
            foregroundColor: Colors.black,
            icon: const Icon(Icons.schedule),
            label: const Text("Set My Hours"),
            onPressed: _openAvailabilityDialog,
          ),
        ),
      ],
    );
  }

  // --- Helpers for availability/calendar ---
  /// Prefer UTC ISO scheduled_start converted to device-local HH:mm; else wire `time`. // COACH-SCHEDULE-LOCAL
  String _formatScheduledTime(Map session) {
    final ss = (session['scheduled_start'] ?? '').toString().trim();
    if (ss.isNotEmpty) {
      try {
        final dt = DateTime.parse(ss).toLocal();
        return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
      } catch (_) {}
    }
    return (session['time'] ?? '').toString().trim();
  }

  static const List<String> _dayShort = [
    'Mon',
    'Tue',
    'Wed',
    'Thu',
    'Fri',
    'Sat',
    'Sun'
  ];
  static const List<String> _dayLong = [
    'Monday',
    'Tuesday',
    'Wednesday',
    'Thursday',
    'Friday',
    'Saturday',
    'Sunday'
  ];

  TimeOfDay _parseHHMM(String s) {
    final parts = s.split(':');
    if (parts.length < 2) return const TimeOfDay(hour: 9, minute: 0);
    return TimeOfDay(
        hour: int.tryParse(parts[0]) ?? 9, minute: int.tryParse(parts[1]) ?? 0);
  }

  String _fmtHHMM(TimeOfDay t) =>
      "${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}";
  String _fmt12(TimeOfDay t) {
    final h = t.hourOfPeriod == 0 ? 12 : t.hourOfPeriod;
    final ampm = t.period == DayPeriod.am ? 'AM' : 'PM';
    return "$h:${t.minute.toString().padLeft(2, '0')} $ampm";
  }

  // Mon=0..Sun=6 from a DateTime (DateTime.weekday is Mon=1..Sun=7)
  int _dowMonZero(DateTime d) => d.weekday - 1;
  String _fmtDate(DateTime d) =>
      "${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}";

  bool _isDateBlocked(DateTime d) {
    final s = _fmtDate(d);
    return _myBlocks.any((b) => (b['date'] ?? '').toString() == s);
  }

  bool _hasRecurringForDay(int dow) =>
      _myRecurring.any((r) => (r['day_of_week'] ?? -1) == dow);

  // Build CalendarEvent list from _schedule + _pendingBookings for switched views.
  List<CalendarEvent> _buildCoachCalendarEvents() {
    final out = <CalendarEvent>[];
    void addFromMap(Map<String, dynamic> m, {required bool pending}) {
      DateTime? start;
      DateTime? end;
      try {
        final ss = (m['scheduled_start'] ?? '').toString();
        if (ss.isNotEmpty) start = DateTime.parse(ss).toLocal();
      } catch (_) {}
      try {
        final se = (m['scheduled_end'] ?? '').toString();
        if (se.isNotEmpty) end = DateTime.parse(se).toLocal();
      } catch (_) {}
      if (start == null) {
        try {
          final ds = (m['date'] ?? '').toString();
          final ts = (m['time'] ?? '09:00 AM').toString();
          if (ds.isNotEmpty) {
            start = DateTime.parse(ds);
          }
        } catch (_) {}
      }
      if (start == null) return;
      final dur = (m['duration_minutes'] is int)
          ? m['duration_minutes'] as int
          : int.tryParse('${m['duration_minutes'] ?? ''}') ?? 60;
      end ??= start.add(Duration(minutes: dur));
      final isConsultMap = _isCoachExternalConsultation(m);
      final displayTitle = isConsultMap
          ? (m['consultation_name'] ?? m['client_name'] ?? 'Consultee')
              .toString()
          : (m['client_name'] ?? 'Client').toString();
      final status = (m['status'] ?? '').toString();
      final Color color;
      if (pending) {
        color = const Color(0xFFC9A962);
      } else if (isConsultMap) {
        color = const Color(0xFF9D4EDD);
      } else if (status == 'pending_approval') {
        color = const Color(0xFFC9A962);
      } else {
        color = const Color(0xFF4ECDC4);
      }
      final subtitle =
          isConsultMap ? 'Consultation' : (m['session_type'] ?? '').toString();
      out.add(CalendarEvent(
        id: (m['session_id'] ??
                m['booking_id'] ??
                '${start.millisecondsSinceEpoch}')
            .toString(),
        start: start,
        end: end,
        title: displayTitle,
        subtitle: subtitle,
        color: color,
        tooltip:
            '${isConsultMap ? 'Consultation: ' : ''}$displayTitle • ${m['time'] ?? ''}${pending ? ' (pending)' : ''}',
        source: 'sanctuary',
        raw: m,
      ));
    }

    for (final raw in _schedule) {
      if (raw is Map)
        addFromMap(Map<String, dynamic>.from(raw), pending: false);
    }
    for (final raw in _pendingBookings) {
      addFromMap(Map<String, dynamic>.from(raw), pending: true);
    }
    return out;
  }

  Widget _buildCoachSwitchedCalendar() {
    final events = _buildCoachCalendarEvents();
    void onTap(CalendarEvent ev) {
      final raw = ev.raw is Map<String, dynamic>
          ? ev.raw as Map<String, dynamic>
          : <String, dynamic>{};
      final isC = raw.isNotEmpty && _isCoachExternalConsultation(raw);
      final subj = (raw['consultation_subject'] ?? '').toString().trim();
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: Text(ev.title,
              style: TextStyle(
                  color:
                      isC ? const Color(0xFF9D4EDD) : const Color(0xFFC9A962))),
          content: Text(
            '${isC ? 'Consultation\n' : ''}'
            '${raw['date'] ?? ''} ${raw['time'] ?? ''}\n'
            '${isC ? '' : '${raw['session_type'] ?? ''}\n'}'
            '${subj.isNotEmpty ? 'Topic: $subj\n' : ''}'
            'Status: ${raw['status'] ?? ''}',
            style: const TextStyle(color: Colors.white),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Close'))
          ],
        ),
      );
    }

    switch (_calView) {
      case CalendarView.week:
        return CalendarWeekGrid(
            focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.day:
        return CalendarDayGrid(
            focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.list:
        return CalendarListView(
            focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.timeline:
        return CalendarTimelineView(
            focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.month:
        return _buildCalendarGrid();
    }
  }

  /// True if session belongs on [d] in local timezone (PG payloads often omit/wrong `date`).
  bool _sessionMatchesCalendarDay(Map<String, dynamic> m, DateTime d) {
    final iso = _fmtDate(d);
    final ds = (m['date'] ?? '').toString();
    if (ds.startsWith(iso)) return true;
    try {
      final ss = (m['scheduled_start'] ?? '').toString();
      if (ss.isEmpty) return false;
      final local = DateTime.parse(ss).toLocal();
      return local.year == d.year &&
          local.month == d.month &&
          local.day == d.day;
    } catch (_) {
      return false;
    }
  }

  // List of confirmed sessions on a given date (best-effort match against _schedule items)
  List<Map<String, dynamic>> _sessionsOnDate(DateTime d) {
    final out = <Map<String, dynamic>>[];
    for (final raw in _schedule) {
      if (raw is! Map) continue;
      final m = Map<String, dynamic>.from(raw);
      if (_sessionMatchesCalendarDay(m, d)) out.add(m);
    }
    return out;
  }

  void _openAvailabilityDialog() {
    // day_of_week (Mon=0..Sun=6) -> list of {start: TimeOfDay, end: TimeOfDay}
    final Map<int, List<Map<String, TimeOfDay>>> dayBlocks = {
      for (int i = 0; i < 7; i++) i: <Map<String, TimeOfDay>>[]
    };
    // Pre-populate from _myRecurring
    for (final r in _myRecurring) {
      final dow = (r['day_of_week'] is int)
          ? r['day_of_week'] as int
          : int.tryParse('${r['day_of_week']}');
      if (dow == null || dow < 0 || dow > 6) continue;
      dayBlocks[dow]!.add({
        'start': _parseHHMM((r['start_time'] ?? '09:00').toString()),
        'end': _parseHHMM((r['end_time'] ?? '17:00').toString()),
      });
    }

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF1A1A1A),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          title: const Text(
            "SET AVAILABLE HOURS",
            style: TextStyle(
                color: Color(0xFFC9A962), fontSize: 16, letterSpacing: 1.5),
          ),
          content: SizedBox(
            width: 460,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Toggle each day on/off and set time blocks. Use + to add a second block (e.g. morning + afternoon).",
                    style: TextStyle(color: Colors.grey, fontSize: 12),
                  ),
                  const SizedBox(height: 12),
                  ...List.generate(7, (i) {
                    final blocks = dayBlocks[i]!;
                    final enabled = blocks.isNotEmpty;
                    return Container(
                      margin: const EdgeInsets.only(bottom: 8),
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 8),
                      decoration: BoxDecoration(
                        color: const Color(0xFF111111),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(
                          color: enabled
                              ? const Color(0xFFC9A962).withOpacity(0.35)
                              : Colors.white12,
                        ),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              SizedBox(
                                width: 56,
                                child: Text(
                                  _dayShort[i],
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                              const Spacer(),
                              Text(
                                enabled ? "On" : "Off",
                                style: TextStyle(
                                  color: enabled
                                      ? const Color(0xFF22C55E)
                                      : Colors.grey,
                                  fontSize: 12,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Switch(
                                value: enabled,
                                activeColor: const Color(0xFFC9A962),
                                onChanged: (v) {
                                  setLocal(() {
                                    if (v && blocks.isEmpty) {
                                      blocks.add({
                                        'start':
                                            const TimeOfDay(hour: 9, minute: 0),
                                        'end': const TimeOfDay(
                                            hour: 17, minute: 0),
                                      });
                                    } else if (!v) {
                                      blocks.clear();
                                    }
                                  });
                                },
                              ),
                            ],
                          ),
                          if (enabled) ...[
                            const SizedBox(height: 6),
                            ...List.generate(blocks.length, (bi) {
                              final blk = blocks[bi];
                              return Padding(
                                padding: const EdgeInsets.only(bottom: 6),
                                child: Row(
                                  children: [
                                    Expanded(
                                      child: OutlinedButton(
                                        onPressed: () async {
                                          final t = await showTimePicker(
                                            context: ctx,
                                            initialTime: blk['start']!,
                                          );
                                          if (t != null) {
                                            setLocal(() => blk['start'] = t);
                                          }
                                        },
                                        child: Text(
                                          _fmt12(blk['start']!),
                                          style: const TextStyle(
                                              color: Color(0xFFC9A962)),
                                        ),
                                      ),
                                    ),
                                    const Padding(
                                      padding:
                                          EdgeInsets.symmetric(horizontal: 6),
                                      child: Text("→",
                                          style: TextStyle(color: Colors.grey)),
                                    ),
                                    Expanded(
                                      child: OutlinedButton(
                                        onPressed: () async {
                                          final t = await showTimePicker(
                                            context: ctx,
                                            initialTime: blk['end']!,
                                          );
                                          if (t != null) {
                                            setLocal(() => blk['end'] = t);
                                          }
                                        },
                                        child: Text(
                                          _fmt12(blk['end']!),
                                          style: const TextStyle(
                                              color: Color(0xFFC9A962)),
                                        ),
                                      ),
                                    ),
                                    if (blocks.length > 1)
                                      IconButton(
                                        tooltip: "Remove block",
                                        icon: const Icon(
                                            Icons.remove_circle_outline,
                                            color: Colors.redAccent,
                                            size: 20),
                                        onPressed: () =>
                                            setLocal(() => blocks.removeAt(bi)),
                                      ),
                                  ],
                                ),
                              );
                            }),
                            Align(
                              alignment: Alignment.centerLeft,
                              child: TextButton.icon(
                                icon: const Icon(Icons.add,
                                    size: 16, color: Color(0xFFC9A962)),
                                label: const Text("Add Block",
                                    style: TextStyle(color: Color(0xFFC9A962))),
                                onPressed: () => setLocal(() {
                                  blocks.add({
                                    'start':
                                        const TimeOfDay(hour: 13, minute: 0),
                                    'end': const TimeOfDay(hour: 17, minute: 0),
                                  });
                                }),
                              ),
                            ),
                          ],
                        ],
                      ),
                    );
                  }),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFC9A962),
                foregroundColor: Colors.black,
              ),
              onPressed: () {
                final slots = <Map<String, dynamic>>[];
                bool invalid = false;
                for (int i = 0; i < 7; i++) {
                  for (final blk in dayBlocks[i]!) {
                    final s = blk['start']!;
                    final e = blk['end']!;
                    final sm = s.hour * 60 + s.minute;
                    final em = e.hour * 60 + e.minute;
                    if (em <= sm) {
                      invalid = true;
                      continue;
                    }
                    slots.add({
                      "day_of_week": i,
                      "start_time": _fmtHHMM(s),
                      "end_time": _fmtHHMM(e),
                    });
                  }
                }
                if (invalid) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                    content: Text("Each block's End must be after Start"),
                    backgroundColor: Colors.redAccent,
                  ));
                  return;
                }
                // Send clean-slate update (replace_recurring=true)
                _socket?.sink.add(jsonEncode({
                  "type": "update_availability",
                  "slots": slots,
                  "replace_recurring": true,
                }));
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text(slots.isEmpty
                      ? "Cleared all recurring availability"
                      : "Publishing ${slots.length} slot(s)..."),
                  backgroundColor: const Color(0xFFC9A962),
                ));
              },
              child: const Text("Publish"),
            ),
          ],
        ),
      ),
    );
  }

  // ===== BLOCK TIME / VACATION DIALOG =====
  void _openBlockTimeDialog({DateTime? initialDate}) {
    DateTime startDate = initialDate ?? DateTime.now();
    DateTime endDate = initialDate ?? DateTime.now();
    final reasonCtrl = TextEditingController();

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF1A1A1A),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          title: const Text(
            "BLOCK TIME",
            style: TextStyle(
                color: Color(0xFF8B5CF6), fontSize: 16, letterSpacing: 1.5),
          ),
          content: SizedBox(
            width: 360,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  "Block specific dates so clients cannot book sessions (vacation, sick day, etc).",
                  style: TextStyle(color: Colors.grey, fontSize: 12),
                ),
                const SizedBox(height: 12),
                Row(children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () async {
                        final picked = await showDatePicker(
                          context: ctx,
                          initialDate: startDate,
                          firstDate:
                              DateTime.now().subtract(const Duration(days: 1)),
                          lastDate:
                              DateTime.now().add(const Duration(days: 365)),
                        );
                        if (picked != null) {
                          setLocal(() {
                            startDate = picked;
                            if (endDate.isBefore(startDate))
                              endDate = startDate;
                          });
                        }
                      },
                      child: Text("From: ${_fmtDate(startDate)}",
                          style: const TextStyle(color: Color(0xFF8B5CF6))),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () async {
                        final picked = await showDatePicker(
                          context: ctx,
                          initialDate: endDate,
                          firstDate: startDate,
                          lastDate:
                              DateTime.now().add(const Duration(days: 365)),
                        );
                        if (picked != null) setLocal(() => endDate = picked);
                      },
                      child: Text("To: ${_fmtDate(endDate)}",
                          style: const TextStyle(color: Color(0xFF8B5CF6))),
                    ),
                  ),
                ]),
                const SizedBox(height: 12),
                TextField(
                  controller: reasonCtrl,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                    labelText: "Reason (optional)",
                    labelStyle: TextStyle(color: Colors.grey),
                    border: OutlineInputBorder(),
                    enabledBorder: OutlineInputBorder(
                      borderSide: BorderSide(color: Colors.white24),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderSide: BorderSide(color: Color(0xFF8B5CF6)),
                    ),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF8B5CF6),
                foregroundColor: Colors.white,
              ),
              onPressed: () {
                final dates = <String>[];
                DateTime cursor = startDate;
                while (!cursor.isAfter(endDate)) {
                  dates.add(_fmtDate(cursor));
                  cursor = cursor.add(const Duration(days: 1));
                  if (dates.length > 366) break;
                }
                if (dates.isEmpty) {
                  Navigator.pop(ctx);
                  return;
                }
                _socket?.sink.add(jsonEncode({
                  "type": "coach_block_time",
                  "dates": dates,
                  "reason": reasonCtrl.text.trim(),
                }));
                Navigator.pop(ctx);
              },
              child: const Text("Block"),
            ),
          ],
        ),
      ),
    );
  }

  void _unblockDate(String dateIso) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_unblock_time",
      "date": dateIso,
    }));
  }

  // ===== SUMMARY CARD: Your Available Hours =====
  Widget _buildAvailabilitySummaryCard() {
    // Group recurring rows by day_of_week
    final Map<int, List<Map<String, dynamic>>> byDay = {
      for (int i = 0; i < 7; i++) i: []
    };
    for (final r in _myRecurring) {
      final dow = (r['day_of_week'] is int)
          ? r['day_of_week'] as int
          : int.tryParse('${r['day_of_week']}') ?? -1;
      if (dow >= 0 && dow <= 6) byDay[dow]!.add(r);
    }
    final hasAny = byDay.values.any((l) => l.isNotEmpty);

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0F0A),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            const Icon(Icons.schedule, color: Color(0xFFC9A962), size: 18),
            const SizedBox(width: 8),
            const Expanded(
              child: Text(
                "YOUR AVAILABLE HOURS",
                style: TextStyle(
                  color: Color(0xFFC9A962),
                  fontWeight: FontWeight.bold,
                  fontFamily: 'Courier',
                  fontSize: 13,
                  letterSpacing: 1,
                ),
              ),
            ),
            TextButton.icon(
              icon: const Icon(Icons.edit, size: 14, color: Color(0xFFC9A962)),
              label: const Text("Edit Hours",
                  style: TextStyle(color: Color(0xFFC9A962), fontSize: 12)),
              onPressed: _openAvailabilityDialog,
            ),
          ]),
          const SizedBox(height: 6),
          if (!_myAvailabilityLoaded)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text("Loading…",
                  style: TextStyle(color: Colors.grey, fontSize: 12)),
            )
          else if (!hasAny)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text(
                "No hours published yet. Tap Edit Hours to set your weekly schedule.",
                style: TextStyle(color: Colors.grey, fontSize: 12),
              ),
            )
          else
            ...List.generate(7, (i) {
              final blocks = byDay[i]!;
              final label = blocks.isEmpty
                  ? "Not available"
                  : blocks
                      .map((b) =>
                          "${_fmt12(_parseHHMM((b['start_time'] ?? '').toString()))} - ${_fmt12(_parseHHMM((b['end_time'] ?? '').toString()))}")
                      .join(', ');
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 80,
                      child: Text(_dayLong[i],
                          style: const TextStyle(
                              color: Colors.white70,
                              fontWeight: FontWeight.bold,
                              fontSize: 12)),
                    ),
                    Expanded(
                      child: Text(label,
                          style: TextStyle(
                              color: blocks.isEmpty
                                  ? Colors.grey
                                  : const Color(0xFF22C55E),
                              fontSize: 12)),
                    ),
                  ],
                ),
              );
            }),
          if (_myBlocks.isNotEmpty) ...[
            const Divider(color: Colors.white10, height: 20),
            Row(children: [
              const Icon(Icons.event_busy, color: Color(0xFF8B5CF6), size: 14),
              const SizedBox(width: 6),
              Text("Blocked Dates (${_myBlocks.length})",
                  style: const TextStyle(
                      color: Color(0xFF8B5CF6),
                      fontSize: 11,
                      fontWeight: FontWeight.bold)),
            ]),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: _myBlocks.map((b) {
                final ds = (b['date'] ?? '').toString();
                return InputChip(
                  label: Text(ds,
                      style:
                          const TextStyle(color: Colors.white, fontSize: 11)),
                  backgroundColor: const Color(0xFF1A1A2E),
                  deleteIconColor: Colors.redAccent,
                  onDeleted: () => _unblockDate(ds),
                );
              }).toList(),
            ),
          ],
        ],
      ),
    );
  }

  // ===== MONTHLY CALENDAR GRID =====
  Widget _buildCalendarGrid() {
    final first = DateTime(_calMonth.year, _calMonth.month, 1);
    final lastDay = DateTime(_calMonth.year, _calMonth.month + 1, 0).day;
    // Mon=0..Sun=6
    final leadingBlanks = first.weekday - 1;
    final cells = <Widget>[];
    final headerRow = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

    final inboundCount = _inboundRequests.length;
    final pendingCount = _pendingBookings.length;

    Widget headerCell(String s) => Center(
          child: Text(s,
              style: const TextStyle(
                  color: Colors.grey,
                  fontSize: 11,
                  fontWeight: FontWeight.bold)),
        );
    cells.addAll(headerRow.map(headerCell));

    for (int i = 0; i < leadingBlanks; i++) {
      cells.add(const SizedBox.shrink());
    }
    for (int day = 1; day <= lastDay; day++) {
      final d = DateTime(_calMonth.year, _calMonth.month, day);
      final isToday = _fmtDate(d) == _fmtDate(DateTime.now());
      final isSelected =
          _calSelectedDay != null && _fmtDate(d) == _fmtDate(_calSelectedDay!);
      final blocked = _isDateBlocked(d);
      final available = _hasRecurringForDay(_dowMonZero(d)) && !blocked;
      final daySessions = _sessionsOnDate(d);
      final hasApproved = daySessions.any((s) =>
          (s['status'] ?? '') == 'scheduled' ||
          (s['status'] ?? '') == 'active');
      final hasPending =
          daySessions.any((s) => (s['status'] ?? '') == 'pending_approval');
      final hasSession = daySessions.isNotEmpty;

      // Build tooltip text for the cell
      String tooltipText = '';
      if (hasSession) {
        final lines = <String>[];
        for (final s in daySessions) {
          final clientNm = (s['client_name'] ?? 'Client').toString();
          String pretty = (s['time'] ?? '').toString();
          try {
            final dtFull =
                DateTime.parse((s['scheduled_start'] ?? '').toString())
                    .toLocal();
            final h12 = dtFull.hour == 0
                ? 12
                : (dtFull.hour > 12 ? dtFull.hour - 12 : dtFull.hour);
            final ap = dtFull.hour >= 12 ? 'PM' : 'AM';
            pretty = '$h12:${dtFull.minute.toString().padLeft(2, '0')} $ap';
          } catch (_) {}
          final st = (s['status'] ?? '').toString();
          final tag = st == 'pending_approval' ? ' (pending)' : '';
          lines.add('$clientNm • $pretty$tag');
        }
        tooltipText = lines.join('\n');
      }

      Color bg;
      if (blocked) {
        bg = const Color(0xFF2A2A2A);
      } else if (hasApproved) {
        bg = const Color(0xFF4ECDC4).withOpacity(0.22);
      } else if (hasPending) {
        bg = const Color(0xFFC9A962).withOpacity(0.22);
      } else if (available) {
        bg = const Color(0xFF22C55E).withOpacity(0.18);
      } else {
        bg = const Color(0xFF111111);
      }

      Widget cellInner = Container(
        margin: const EdgeInsets.all(2),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: isSelected
                ? const Color(0xFFC9A962)
                : (isToday ? const Color(0xFF4ECDC4) : Colors.white10),
            width: isSelected || isToday ? 1.5 : 0.5,
          ),
        ),
        child: Stack(
          children: [
            Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    "$day",
                    style: TextStyle(
                      color: blocked ? Colors.grey : Colors.white,
                      fontSize: 12,
                      fontWeight: isToday ? FontWeight.bold : FontWeight.normal,
                    ),
                  ),
                  if (hasSession)
                    Padding(
                      padding: const EdgeInsets.only(top: 1),
                      child: Text(
                        (() {
                          final s = daySessions.first;
                          final nm = (s['client_name'] ?? 'Client').toString();
                          return nm.length > 7 ? nm.substring(0, 7) : nm;
                        })(),
                        style: TextStyle(
                          color: hasApproved
                              ? const Color(0xFF4ECDC4)
                              : const Color(0xFFC9A962),
                          fontSize: 8,
                          fontWeight: FontWeight.w700,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
              ),
            ),
            if (hasApproved)
              Positioned(
                top: 2,
                right: 3,
                child: Container(
                  width: 5,
                  height: 5,
                  decoration: const BoxDecoration(
                    color: Color(0xFF4ECDC4),
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            if (hasPending && !hasApproved)
              Positioned(
                top: 2,
                right: 3,
                child: Container(
                  width: 5,
                  height: 5,
                  decoration: const BoxDecoration(
                    color: Color(0xFFC9A962),
                    shape: BoxShape.circle,
                  ),
                ),
              ),
          ],
        ),
      );

      if (tooltipText.isNotEmpty) {
        cellInner = Tooltip(
          message: tooltipText,
          waitDuration: const Duration(milliseconds: 200),
          child: cellInner,
        );
      }

      cells.add(GestureDetector(
        onTap: () => setState(() => _calSelectedDay = d),
        child: cellInner,
      ));
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0F),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              IconButton(
                icon: const Icon(Icons.chevron_left, color: Color(0xFFC9A962)),
                onPressed: () {
                  setState(() {
                    _calMonth =
                        DateTime(_calMonth.year, _calMonth.month - 1, 1);
                  });
                  _emitFetchCoachCalendar();
                },
              ),
              Expanded(
                child: Center(
                  child: Text(
                    "${_monthName(_calMonth.month)} ${_calMonth.year}",
                    style: const TextStyle(
                      color: Color(0xFFC9A962),
                      fontWeight: FontWeight.bold,
                      fontSize: 14,
                      letterSpacing: 1,
                    ),
                  ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.chevron_right, color: Color(0xFFC9A962)),
                onPressed: () {
                  setState(() {
                    _calMonth =
                        DateTime(_calMonth.year, _calMonth.month + 1, 1);
                  });
                  _emitFetchCoachCalendar();
                },
              ),
            ],
          ),
          const SizedBox(height: 4),
          GridView.count(
            crossAxisCount: 7,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            childAspectRatio: 1.1,
            children: cells,
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              _legendDot(const Color(0xFF22C55E), "Available"),
              _legendDot(const Color(0xFFC9A962), "Booked"),
              _legendDot(const Color(0xFF2A2A2A), "Blocked"),
              if (inboundCount + pendingCount > 0)
                _legendDot(Colors.redAccent,
                    "Pending (${inboundCount + pendingCount})"),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.event_busy,
                      size: 16, color: Color(0xFF8B5CF6)),
                  label: const Text("Block Time",
                      style: TextStyle(color: Color(0xFF8B5CF6))),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: Color(0xFF8B5CF6)),
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  onPressed: () =>
                      _openBlockTimeDialog(initialDate: _calSelectedDay),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton.icon(
                  icon: const Icon(Icons.today,
                      size: 16, color: Color(0xFF4ECDC4)),
                  label: const Text("Today",
                      style: TextStyle(color: Color(0xFF4ECDC4))),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: Color(0xFF4ECDC4)),
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  onPressed: () {
                    setState(() {
                      final now = DateTime.now();
                      _calMonth = DateTime(now.year, now.month, 1);
                      _calSelectedDay = now;
                    });
                    _emitFetchCoachCalendar();
                  },
                ),
              ),
            ],
          ),
          if (_calSelectedDay != null) ...[
            const Divider(color: Colors.white10, height: 18),
            _buildSelectedDayDetail(_calSelectedDay!),
          ],
        ],
      ),
    );
  }

  Widget _legendDot(Color c, String label) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
          const SizedBox(width: 4),
          Text(label, style: const TextStyle(color: Colors.grey, fontSize: 10)),
        ],
      );

  String _monthName(int m) => const [
        'January',
        'February',
        'March',
        'April',
        'May',
        'June',
        'July',
        'August',
        'September',
        'October',
        'November',
        'December'
      ][m - 1];

  Widget _buildSelectedDayDetail(DateTime d) {
    final dow = _dowMonZero(d);
    final blocked = _isDateBlocked(d);
    final recur =
        _myRecurring.where((r) => (r['day_of_week'] ?? -1) == dow).toList();
    final sessions = _sessionsOnDate(d);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          "${_dayLong[dow]}, ${_monthName(d.month)} ${d.day}, ${d.year}",
          style: const TextStyle(
              color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13),
        ),
        const SizedBox(height: 6),
        if (blocked)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            decoration: BoxDecoration(
              color: const Color(0xFF8B5CF6).withOpacity(0.15),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(children: [
              const Icon(Icons.event_busy, color: Color(0xFF8B5CF6), size: 14),
              const SizedBox(width: 6),
              const Expanded(
                child: Text("Blocked (no client bookings)",
                    style: TextStyle(color: Color(0xFF8B5CF6), fontSize: 12)),
              ),
              TextButton(
                onPressed: () => _unblockDate(_fmtDate(d)),
                child: const Text("Unblock",
                    style: TextStyle(color: Colors.redAccent, fontSize: 12)),
              ),
            ]),
          )
        else if (recur.isEmpty)
          const Text("No recurring availability",
              style: TextStyle(color: Colors.grey, fontSize: 12))
        else
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: recur.map((r) {
              return Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: const Color(0xFF22C55E).withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  "${_fmt12(_parseHHMM((r['start_time'] ?? '').toString()))} - ${_fmt12(_parseHHMM((r['end_time'] ?? '').toString()))}",
                  style:
                      const TextStyle(color: Color(0xFF22C55E), fontSize: 11),
                ),
              );
            }).toList(),
          ),
        if (sessions.isNotEmpty) ...[
          const SizedBox(height: 8),
          const Text("SESSIONS THIS DAY",
              style: TextStyle(
                  color: Colors.white54, fontSize: 11, letterSpacing: 1)),
          const SizedBox(height: 4),
          ...sessions.map((s) {
            final sm = Map<String, dynamic>.from(s);
            final isC = _isCoachExternalConsultation(sm);
            final cl = isC
                ? (sm['consultation_name'] ??
                        sm['client_name'] ??
                        sm['client'] ??
                        'Consultee')
                    .toString()
                : (sm['client_name'] ?? sm['client'] ?? 'Client').toString();
            final tm = _formatScheduledTime(sm); // COACH-SCHEDULE-LOCAL
            return Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(children: [
                Icon(
                  isC ? Icons.person_search : Icons.videocam,
                  color:
                      isC ? const Color(0xFF9D4EDD) : const Color(0xFFC9A962),
                  size: 14,
                ),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    "${isC ? 'Consultation · ' : ''}$cl${tm.isNotEmpty ? ' • $tm' : ''}",
                    style: const TextStyle(color: Colors.white, fontSize: 12),
                  ),
                ),
              ]),
            );
          }),
        ],
      ],
    );
  }

  void _openBriefingsForSession(Map<String, dynamic> session) {
    if (_isCoachExternalConsultation(session)) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
                'Briefings are for assigned clients. Consultations stay on the Schedule tab.'),
            backgroundColor: Color(0xFF8B7355),
          ),
        );
      }
      return;
    }
    final familyId = (session['family_id'] ?? '').toString();
    final clientId = (session['client_id'] ?? '').toString();
    final folders = _buildFolderGroups();

    if (familyId.isNotEmpty) {
      final match = folders.firstWhere(
        (f) => (f['family_id'] ?? '').toString() == familyId,
        orElse: () => <String, dynamic>{},
      );
      if (match.isNotEmpty) {
        _openFolder(
          folderId: match['folder_id'],
          label: match['label'],
          familyId: match['family_id'],
          clients: List<Map<String, dynamic>>.from(match['clients'] ?? []),
        );
        return;
      }
    }

    if (clientId.isNotEmpty) {
      final match = folders.firstWhere(
        (f) => (f['folder_id'] ?? '').toString() == 'client:$clientId',
        orElse: () => <String, dynamic>{},
      );
      if (match.isNotEmpty) {
        _openFolder(
          folderId: match['folder_id'],
          label: match['label'],
          familyId: match['family_id'],
          clients: List<Map<String, dynamic>>.from(match['clients'] ?? []),
        );
        return;
      }
    }
  }

  /// Launch Zoom meeting directly - opens in Zoom app or browser
  /// Prefers host URL (coach enters as host with waiting room control)
  /// Falls back to join URL if host URL not available
  Future<void> _launchZoomMeeting(String hostUrl, String joinUrl) async {
    // Prefer host URL - this makes the coach the host with waiting room control
    final urlToLaunch = hostUrl.isNotEmpty ? hostUrl : joinUrl;

    if (urlToLaunch.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text("No Zoom link found for this session yet."),
          backgroundColor: Colors.orange,
        ),
      );
      return;
    }

    // On web, use the dart:html window.open directly (via conditional import)
    // This avoids url_launcher plugin issues on Flutter web
    if (kIsWeb) {
      launchDojoUrl(urlToLaunch); // Uses html.window.open under the hood
      return;
    }

    // On mobile, use url_launcher to open in Zoom app
    try {
      final uri = Uri.parse(urlToLaunch);
      final launched = await launchUrl(
        uri,
        mode: LaunchMode.externalApplication,
      );

      if (!launched) {
        _showMeetingLinkDialog(urlToLaunch);
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text("Could not open Zoom: $e"),
          backgroundColor: Colors.red,
        ),
      );
    }
  }

  void _showMeetingLinkDialog(String url) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title:
            const Text("Zoom Link", style: TextStyle(color: Color(0xFF00F5D4))),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              url.isEmpty
                  ? "No Zoom link found for this session yet."
                  : "Copy/paste into your browser:",
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 10),
            SelectableText(
              url.isEmpty ? "—" : url,
              style: const TextStyle(
                  color: Colors.white54, fontFamily: 'Courier', fontSize: 12),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Close", style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            onPressed: url.isEmpty
                ? null
                : () {
                    Clipboard.setData(ClipboardData(text: url));
                    Navigator.pop(ctx);
                    ScaffoldMessenger.of(context)
                        .showSnackBar(const SnackBar(content: Text("Copied")));
                  },
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF00F5D4),
                foregroundColor: Colors.black),
            child: const Text("Copy"),
          ),
        ],
      ),
    );
  }

  Future<void> _sendInsightsChat(String message) async {
    if (message.trim().isEmpty) return;
    setState(() {
      _insightsChatMessages.add({'role': 'user', 'content': message});
      _insightsChatLoading = true;
    });
    _insightsChatController.clear();
    _scrollInsightsChat();
    try {
      final token = widget.currentUserProfile['token'] ?? '';
      final coachUsername = widget.currentUserProfile['username'] ?? '';
      final coachRole = widget.currentUserProfile['role'] ?? 'COACH';

      final clientDetails = _clients
          .take(30)
          .map((c) => {
                'name': c['name'] ?? 'Unknown',
                'id': c['hardware_id'] ?? c['id'] ?? '',
                'tier': c['tier'] ?? '',
                'risk': c['risk_level'] ?? c['coherence_risk'] ?? '',
              })
          .toList();

      final contextPayload = <String, dynamic>{
        'coach_username': coachUsername,
        'coach_role': coachRole,
        'total_clients': _clients.length,
        'client_names': clientDetails,
        'is_master_coach': widget.currentUserProfile['is_master_coach'] == true,
      };

      if (_lastNevedalReport != null) {
        contextPayload['last_report'] = _lastNevedalReport;
      }

      if (_selectedClientBrief != null) {
        contextPayload['briefing_data'] = _selectedClientBrief;
      }

      final uri = Uri.parse('$_apiBaseUrl/api/coach/nate-chat');
      final resp = await http.post(
        uri,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode({
          'message': message,
          'mode': 'inquiry',
          'context': contextPayload,
        }),
      );
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _insightsChatMessages.add({
            'role': 'assistant',
            'content': (data['response'] ?? data['message'] ?? 'No response')
                .toString(),
          });
        });
      } else {
        setState(() {
          _insightsChatMessages.add({
            'role': 'assistant',
            'content': 'Connection issue (${resp.statusCode}). Try again.',
          });
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _insightsChatMessages.add({
          'role': 'assistant',
          'content': 'Connection error. Check your network.'
        });
      });
    }
    if (mounted) setState(() => _insightsChatLoading = false);
    _scrollInsightsChat();
  }

  void _scrollInsightsChat() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_insightsChatScrollController.hasClients) {
        _insightsChatScrollController.animateTo(
          _insightsChatScrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Widget _buildInsightsChatBox() {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0A),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.3)),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: const Color(0xFF4ECDC4).withOpacity(0.08),
              borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(12), topRight: Radius.circular(12)),
            ),
            child: Row(
              children: const [
                Icon(Icons.psychology, color: Color(0xFF4ECDC4), size: 16),
                SizedBox(width: 6),
                Text('LITTLE NATE',
                    style: TextStyle(
                        color: Color(0xFF4ECDC4),
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1)),
                Spacer(),
                Text('COACHING INSIGHTS',
                    style: TextStyle(
                        color: Colors.white38,
                        fontSize: 9,
                        letterSpacing: 0.5)),
              ],
            ),
          ),
          Expanded(
            child: _insightsChatMessages.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(
                        'Ask about client patterns, coherence trends, risk indicators, or session insights...',
                        style: TextStyle(
                            color: Colors.white.withOpacity(0.3), fontSize: 12),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  )
                : ListView.builder(
                    controller: _insightsChatScrollController,
                    padding: const EdgeInsets.all(8),
                    itemCount: _insightsChatMessages.length,
                    itemBuilder: (ctx, i) {
                      final msg = _insightsChatMessages[i];
                      final isUser = msg['role'] == 'user';
                      return Align(
                        alignment: isUser
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 6),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 10, vertical: 8),
                          constraints: BoxConstraints(
                              maxWidth: MediaQuery.of(ctx).size.width * 0.55),
                          decoration: BoxDecoration(
                            color: isUser
                                ? const Color(0xFFC9A962).withOpacity(0.15)
                                : const Color(0xFF4ECDC4).withOpacity(0.1),
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(
                              color: isUser
                                  ? const Color(0xFFC9A962).withOpacity(0.2)
                                  : const Color(0xFF4ECDC4).withOpacity(0.15),
                            ),
                          ),
                          child: SelectableText(
                            msg['content'] ?? '',
                            style: TextStyle(
                                color: isUser
                                    ? const Color(0xFFE8D5A3)
                                    : Colors.white70,
                                fontSize: 12,
                                height: 1.4),
                          ),
                        ),
                      );
                    },
                  ),
          ),
          if (_insightsChatLoading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 4),
              child: SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(
                      strokeWidth: 1.5, color: Color(0xFF4ECDC4))),
            ),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              border: Border(
                  top: BorderSide(color: Colors.white.withOpacity(0.06))),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _insightsChatController,
                    style: const TextStyle(color: Colors.white, fontSize: 12),
                    decoration: InputDecoration(
                      hintText: 'Ask Nate about your clients...',
                      hintStyle: TextStyle(
                          color: Colors.white.withOpacity(0.25), fontSize: 12),
                      isDense: true,
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 8),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide.none),
                      filled: true,
                      fillColor: Colors.white.withOpacity(0.04),
                    ),
                    onSubmitted: _sendInsightsChat,
                  ),
                ),
                const SizedBox(width: 6),
                IconButton(
                  icon: const Icon(Icons.send,
                      color: Color(0xFF4ECDC4), size: 18),
                  onPressed: () =>
                      _sendInsightsChat(_insightsChatController.text),
                  padding: EdgeInsets.zero,
                  constraints:
                      const BoxConstraints(minWidth: 32, minHeight: 32),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // ════════════════════════════════════════════════════════════════════════
  // ASSISTANT COACHES TAB — master coach only
  // ════════════════════════════════════════════════════════════════════════

  Future<void> _loadAssistantMetrics() async {
    if (_assistantsTabLoading) return;
    setState(() => _assistantsTabLoading = true);
    try {
      final resp = await http.get(
        Uri.parse('$_apiBaseUrl/api/coach/hierarchy/assistant-metrics?days=30'),
        headers: _restHeaders(json: false),
      );
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _assistantMetrics =
              List<Map<String, dynamic>>.from(data['assistants'] ?? []);
        });
      } else if (mounted && resp.statusCode == 401) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
                'Assistants tab: session auth failed — pull to refresh or re-login.'),
            backgroundColor: Colors.orange,
          ),
        );
      }
    } catch (e) {
      _debugLog("Assistant metrics error: $e");
    }
    if (mounted) setState(() => _assistantsTabLoading = false);
  }

  Future<void> _loadAssistantClients(String username) async {
    setState(() => _expandedClientsLoading = true);
    try {
      final resp = await http.get(
        Uri.parse(
            '$_apiBaseUrl/api/coach/hierarchy/assistant-clients/$username'),
        headers: _restHeaders(json: false),
      );
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _expandedAssistantClients =
              List<Map<String, dynamic>>.from(data['clients'] ?? []);
        });
      }
    } catch (e) {
      _debugLog("Assistant clients error: $e");
    }
    if (mounted) setState(() => _expandedClientsLoading = false);
  }

  void _startConsultation(Map<String, dynamic> assistant) {
    final assistantId =
        (assistant['assistant_id'] ?? assistant['hardware_id'] ?? '')
            .toString();
    final displayName =
        assistant['display_name'] ?? assistant['username'] ?? 'Assistant';
    final username = (assistant['username'] ?? '').toString();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A1A1A),
        title: const Text('Start Free Consultation',
            style: TextStyle(color: Color(0xFFC9A962))),
        content: Text(
          'Start a 15-minute consultation with $displayName (@$username)?\n\nThis is a free coaching session limited to one per assistant per day.',
          style: const TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child:
                const Text('Cancel', style: TextStyle(color: Colors.white38)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF4ECDC4)),
            onPressed: () {
              Navigator.pop(ctx);
              _socket?.sink.add(jsonEncode({
                'type': 'master_consultation_request',
                'assistant_id': assistantId,
                'assistant_username': username,
              }));
            },
            child: const Text('Start',
                style: TextStyle(
                    color: Colors.black, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  void _sendAssistantChat(String message) async {
    if (message.trim().isEmpty) return;
    setState(() {
      _assistantChatMessages.add({'role': 'user', 'content': message});
      _assistantChatLoading = true;
    });
    _assistantChatController.clear();
    _scrollAssistantChat();
    try {
      final coachUsername = widget.currentUserProfile['username'] ?? '';

      final assistantNames = _assistantMetrics.map((a) {
        return {
          'name': a['display_name'] ?? a['username'] ?? '',
          'username': a['username'] ?? '',
          'client_count': a['client_count'] ?? 0,
          'sessions_total': a['sessions']?['total'] ?? 0,
          'sessions_completed': a['sessions']?['completed'] ?? 0,
          'avg_coherence': a['sessions']?['avg_coherence'] ?? 0,
          'supervised_hours': a['supervised_hours'] ?? 0,
        };
      }).toList();

      final contextPayload = <String, dynamic>{
        'coach_username': coachUsername,
        'coach_role': 'MASTER_COACH',
        'is_master_coach': true,
        'total_assistants': _assistantMetrics.length,
        'assistant_details': assistantNames,
        'client_names': assistantNames.map((a) => a['name']).toList(),
        'total_clients': assistantNames.fold<int>(
            0, (sum, a) => sum + ((a['client_count'] as int?) ?? 0)),
      };

      if (_expandedAssistant != null) {
        contextPayload['focused_assistant'] = _expandedAssistant;
        contextPayload['focused_assistant_clients'] = _expandedAssistantClients
            .map((c) => {
                  'name': c['name'] ?? c['username'] ?? '',
                  'tier': c['tier'] ?? '',
                  'risk': c['risk'] ?? '',
                })
            .toList();
      }

      final uri = Uri.parse('$_apiBaseUrl/api/coach/nate-chat');
      final resp = await http.post(
        uri,
        headers: _restHeaders(),
        body: jsonEncode({
          'message': message,
          'mode': 'assistant_inquiry',
          'context': contextPayload,
        }),
      );
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _assistantChatMessages.add({
            'role': 'assistant',
            'content': (data['response'] ?? data['message'] ?? 'No response')
                .toString(),
          });
        });
      } else {
        setState(() {
          _assistantChatMessages.add({
            'role': 'assistant',
            'content': 'Connection issue (${resp.statusCode}). Try again.',
          });
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _assistantChatMessages.add({
          'role': 'assistant',
          'content': 'Connection error. Check your network.'
        });
      });
    }
    if (mounted) setState(() => _assistantChatLoading = false);
    _scrollAssistantChat();
  }

  void _scrollAssistantChat() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_assistantChatScrollController.hasClients) {
        _assistantChatScrollController.animateTo(
          _assistantChatScrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Widget _buildAssistantChatBox() {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0A),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
      ),
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: const Color(0xFF9D4EDD).withOpacity(0.08),
              borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(12), topRight: Radius.circular(12)),
            ),
            child: Row(
              children: const [
                Icon(Icons.psychology, color: Color(0xFF9D4EDD), size: 16),
                SizedBox(width: 6),
                Text('LITTLE NATE',
                    style: TextStyle(
                        color: Color(0xFF9D4EDD),
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1)),
                Spacer(),
                Text('ASSISTANT INSIGHTS',
                    style: TextStyle(
                        color: Colors.white38,
                        fontSize: 9,
                        letterSpacing: 0.5)),
              ],
            ),
          ),
          Expanded(
            child: _assistantChatMessages.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text(
                        'Ask about your assistant coaches, their client progress, session quality, or areas where they need support...',
                        style: TextStyle(
                            color: Colors.white.withOpacity(0.3), fontSize: 12),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  )
                : ListView.builder(
                    controller: _assistantChatScrollController,
                    padding: const EdgeInsets.all(8),
                    itemCount: _assistantChatMessages.length,
                    itemBuilder: (ctx, i) {
                      final msg = _assistantChatMessages[i];
                      final isUser = msg['role'] == 'user';
                      return Align(
                        alignment: isUser
                            ? Alignment.centerRight
                            : Alignment.centerLeft,
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 6),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 10, vertical: 8),
                          constraints: BoxConstraints(
                              maxWidth: MediaQuery.of(ctx).size.width * 0.55),
                          decoration: BoxDecoration(
                            color: isUser
                                ? const Color(0xFFC9A962).withOpacity(0.15)
                                : const Color(0xFF9D4EDD).withOpacity(0.1),
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(
                              color: isUser
                                  ? const Color(0xFFC9A962).withOpacity(0.2)
                                  : const Color(0xFF9D4EDD).withOpacity(0.15),
                            ),
                          ),
                          child: SelectableText(
                            msg['content'] ?? '',
                            style: TextStyle(
                                color: isUser
                                    ? const Color(0xFFE8D5A3)
                                    : Colors.white70,
                                fontSize: 12,
                                height: 1.4),
                          ),
                        ),
                      );
                    },
                  ),
          ),
          if (_assistantChatLoading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 4),
              child: SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(
                      strokeWidth: 1.5, color: Color(0xFF9D4EDD))),
            ),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              border: Border(
                  top: BorderSide(color: Colors.white.withOpacity(0.06))),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _assistantChatController,
                    style: const TextStyle(color: Colors.white, fontSize: 12),
                    decoration: InputDecoration(
                      hintText: 'Ask Nate about your assistants...',
                      hintStyle: TextStyle(
                          color: Colors.white.withOpacity(0.25), fontSize: 12),
                      isDense: true,
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 8),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                          borderSide: BorderSide.none),
                      filled: true,
                      fillColor: Colors.white.withOpacity(0.04),
                    ),
                    onSubmitted: _sendAssistantChat,
                  ),
                ),
                const SizedBox(width: 6),
                IconButton(
                  icon: const Icon(Icons.send,
                      color: Color(0xFF9D4EDD), size: 18),
                  onPressed: () =>
                      _sendAssistantChat(_assistantChatController.text),
                  padding: EdgeInsets.zero,
                  constraints:
                      const BoxConstraints(minWidth: 32, minHeight: 32),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAssistantCard(Map<String, dynamic> assistant) {
    final name = assistant['display_name'] ?? assistant['username'] ?? '—';
    final username = assistant['username'] ?? '';
    final clientCount = assistant['client_count'] ?? 0;
    final sessions = assistant['sessions'] ?? {};
    final totalSessions = sessions['total'] ?? 0;
    final completedSessions = sessions['completed'] ?? 0;
    final avgCoherence = (sessions['avg_coherence'] ?? 0.0).toDouble();
    final hours = (assistant['supervised_hours'] ?? 0).toDouble();
    final isExpanded = _expandedAssistant == username;
    final status = assistant['status'] ?? 'active';

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: isExpanded
              ? const Color(0xFF9D4EDD).withOpacity(0.5)
              : Colors.white.withOpacity(0.06),
        ),
      ),
      child: Column(
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () {
              setState(() {
                if (isExpanded) {
                  _expandedAssistant = null;
                  _expandedAssistantClients = [];
                } else {
                  _expandedAssistant = username;
                  _loadAssistantClients(username);
                }
              });
            },
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 36,
                        height: 36,
                        decoration: BoxDecoration(
                          color: const Color(0xFF9D4EDD).withOpacity(0.15),
                          borderRadius: BorderRadius.circular(18),
                        ),
                        child: Center(
                          child: Text(
                            name.isNotEmpty ? name[0].toUpperCase() : '?',
                            style: const TextStyle(
                                color: Color(0xFF9D4EDD),
                                fontWeight: FontWeight.bold,
                                fontSize: 16),
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(name,
                                style: const TextStyle(
                                    color: Colors.white,
                                    fontWeight: FontWeight.bold,
                                    fontSize: 14)),
                            Text('@$username',
                                style: TextStyle(
                                    color: Colors.white.withOpacity(0.4),
                                    fontSize: 11)),
                          ],
                        ),
                      ),
                      if (status == 'active' || status == 'accepted')
                        Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: SizedBox(
                            height: 26,
                            child: ElevatedButton(
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFF4ECDC4),
                                padding:
                                    const EdgeInsets.symmetric(horizontal: 10),
                                shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(13)),
                              ),
                              onPressed: () => _startConsultation(assistant),
                              child: const Text('Consult',
                                  style: TextStyle(
                                      color: Colors.black,
                                      fontSize: 10,
                                      fontWeight: FontWeight.w600)),
                            ),
                          ),
                        ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: status == 'active' || status == 'accepted'
                              ? Colors.green.withOpacity(0.15)
                              : Colors.orange.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          status.toUpperCase(),
                          style: TextStyle(
                            color: status == 'active' || status == 'accepted'
                                ? Colors.green
                                : Colors.orange,
                            fontSize: 9,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 0.5,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      Icon(isExpanded ? Icons.expand_less : Icons.expand_more,
                          color: Colors.white38, size: 20),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      _metricChip(Icons.people, '$clientCount', 'Clients'),
                      const SizedBox(width: 8),
                      _metricChip(Icons.event_note,
                          '$completedSessions/$totalSessions', 'Sessions'),
                      const SizedBox(width: 8),
                      _metricChip(Icons.timeline,
                          avgCoherence.toStringAsFixed(2), 'Avg CEE'),
                      const SizedBox(width: 8),
                      _metricChip(Icons.timer, '${hours.toStringAsFixed(1)}h',
                          'Supervised'),
                    ],
                  ),
                ],
              ),
            ),
          ),
          if (isExpanded) ...[
            Divider(height: 1, color: Colors.white.withOpacity(0.06)),
            _expandedClientsLoading
                ? const Padding(
                    padding: EdgeInsets.all(16),
                    child: Center(
                        child: SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(
                                strokeWidth: 1.5, color: Color(0xFF9D4EDD)))),
                  )
                : _expandedAssistantClients.isEmpty
                    ? Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text('No clients assigned',
                            style: TextStyle(
                                color: Colors.white.withOpacity(0.3),
                                fontSize: 12)),
                      )
                    : Padding(
                        padding: const EdgeInsets.all(10),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Padding(
                              padding:
                                  const EdgeInsets.only(bottom: 8, left: 4),
                              child: Text(
                                'ASSIGNED CLIENTS',
                                style: TextStyle(
                                    color: Colors.white.withOpacity(0.4),
                                    fontSize: 10,
                                    fontWeight: FontWeight.bold,
                                    letterSpacing: 1),
                              ),
                            ),
                            ..._expandedAssistantClients.map((c) => Container(
                                  margin: const EdgeInsets.only(bottom: 4),
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 10, vertical: 8),
                                  decoration: BoxDecoration(
                                    color: Colors.white.withOpacity(0.02),
                                    borderRadius: BorderRadius.circular(6),
                                  ),
                                  child: Row(
                                    children: [
                                      Icon(Icons.person,
                                          color: Colors.white.withOpacity(0.3),
                                          size: 14),
                                      const SizedBox(width: 8),
                                      Expanded(
                                        child: Text(
                                          c['name'] ?? c['username'] ?? '—',
                                          style: const TextStyle(
                                              color: Colors.white70,
                                              fontSize: 12),
                                        ),
                                      ),
                                      Container(
                                        padding: const EdgeInsets.symmetric(
                                            horizontal: 6, vertical: 2),
                                        decoration: BoxDecoration(
                                          color:
                                              _riskColor(c['risk'] ?? 'normal')
                                                  .withOpacity(0.15),
                                          borderRadius:
                                              BorderRadius.circular(4),
                                        ),
                                        child: Text(
                                          (c['risk'] ?? 'normal')
                                              .toString()
                                              .toUpperCase(),
                                          style: TextStyle(
                                              color: _riskColor(
                                                  c['risk'] ?? 'normal'),
                                              fontSize: 9,
                                              fontWeight: FontWeight.bold),
                                        ),
                                      ),
                                      const SizedBox(width: 6),
                                      Text(c['tier'] ?? '',
                                          style: TextStyle(
                                              color:
                                                  Colors.white.withOpacity(0.3),
                                              fontSize: 10)),
                                    ],
                                  ),
                                )),
                          ],
                        ),
                      ),
          ],
        ],
      ),
    );
  }

  Widget _metricChip(IconData icon, String value, String label) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.03),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Column(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, color: const Color(0xFF9D4EDD), size: 12),
                const SizedBox(width: 3),
                Flexible(
                    child: Text(value,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                            fontWeight: FontWeight.bold),
                        overflow: TextOverflow.ellipsis)),
              ],
            ),
            const SizedBox(height: 2),
            Text(label,
                style: TextStyle(
                    color: Colors.white.withOpacity(0.3), fontSize: 9)),
          ],
        ),
      ),
    );
  }

  Color _riskColor(String risk) {
    switch (risk.toLowerCase()) {
      case 'high':
        return const Color(0xFFEF4444);
      case 'elevated':
        return Colors.orange;
      case 'low':
        return Colors.green;
      default:
        return const Color(0xFFC9A962);
    }
  }

  Widget _buildAssistantsTab() {
    final profile = widget.currentUserProfile;
    final roleUpper = (profile['role'] ?? '').toString().toUpperCase();
    // login_success sets _authToken; profile map may not include token. COACH/ADMIN
    // always see this tab (API returns [] for non-master coaches).
    final isMaster = _assistantMetrics.isNotEmpty ||
        profile['is_master_coach'] == true ||
        profile['master_coach_approved'] == true ||
        profile['master_coach_approved'] == 'true' ||
        roleUpper == 'COACH' ||
        roleUpper == 'ADMIN';

    if (!isMaster && !_assistantsTabLoading && _assistantMetrics.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.supervisor_account,
                color: Colors.white.withOpacity(0.15), size: 64),
            const SizedBox(height: 16),
            Text('Master Coach Access',
                style: TextStyle(
                    color: Colors.white.withOpacity(0.5),
                    fontSize: 16,
                    fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            Text(
              'This tab is available when you have\nassistant coaches under your supervision.',
              style:
                  TextStyle(color: Colors.white.withOpacity(0.3), fontSize: 13),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      );
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.supervisor_account,
                  color: Color(0xFF9D4EDD), size: 20),
              const SizedBox(width: 8),
              const Text(
                'ASSISTANT COACHES',
                style: TextStyle(
                    color: Color(0xFF9D4EDD),
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5),
              ),
              const Spacer(),
              if (_assistantsTabLoading)
                const SizedBox(
                    height: 16,
                    width: 16,
                    child: CircularProgressIndicator(
                        strokeWidth: 1.5, color: Color(0xFF9D4EDD)))
              else
                IconButton(
                  icon: const Icon(Icons.refresh,
                      color: Color(0xFF9D4EDD), size: 18),
                  onPressed: _loadAssistantMetrics,
                  padding: EdgeInsets.zero,
                  constraints:
                      const BoxConstraints(minWidth: 32, minHeight: 32),
                ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            '${_assistantMetrics.length} assistant${_assistantMetrics.length == 1 ? '' : 's'} under your supervision',
            style:
                TextStyle(color: Colors.white.withOpacity(0.4), fontSize: 12),
          ),
          const SizedBox(height: 16),
          SizedBox(
            height: 260,
            child: Row(
              children: [
                Expanded(flex: 3, child: _buildAssistantChatBox()),
                const SizedBox(width: 12),
                Expanded(
                  flex: 2,
                  child: Container(
                    decoration: BoxDecoration(
                      color: const Color(0xFF0A0A0A),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white.withOpacity(0.06)),
                    ),
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('OVERVIEW',
                            style: TextStyle(
                                color: Colors.white.withOpacity(0.4),
                                fontSize: 10,
                                fontWeight: FontWeight.bold,
                                letterSpacing: 1)),
                        const SizedBox(height: 12),
                        _overviewStat('Total Assistants',
                            '${_assistantMetrics.length}', Icons.people_alt),
                        const SizedBox(height: 8),
                        _overviewStat(
                          'Total Clients',
                          '${_assistantMetrics.fold<int>(0, (s, a) => s + ((a['client_count'] as int?) ?? 0))}',
                          Icons.person,
                        ),
                        const SizedBox(height: 8),
                        _overviewStat(
                          'Sessions (30d)',
                          '${_assistantMetrics.fold<int>(0, (s, a) => s + (((a['sessions'] ?? {})['total'] as int?) ?? 0))}',
                          Icons.event_note,
                        ),
                        const SizedBox(height: 8),
                        _overviewStat(
                          'Avg Coherence',
                          _assistantMetrics.isNotEmpty
                              ? (_assistantMetrics.fold<double>(
                                          0,
                                          (s, a) =>
                                              s +
                                              ((a['sessions'] ??
                                                          {})['avg_coherence']
                                                      as double? ??
                                                  0)) /
                                      _assistantMetrics.length)
                                  .toStringAsFixed(3)
                              : '—',
                          Icons.timeline,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
          ..._assistantMetrics.map((a) => _buildAssistantCard(a)),
          if (_assistantMetrics.isEmpty && !_assistantsTabLoading)
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.02),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Center(
                child: Text(
                  'No assistant coaches found. Invite assistants from Settings > My Assistants.',
                  style: TextStyle(
                      color: Colors.white.withOpacity(0.3), fontSize: 13),
                  textAlign: TextAlign.center,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _overviewStat(String label, String value, IconData icon) {
    return Row(
      children: [
        Icon(icon, color: const Color(0xFF9D4EDD), size: 14),
        const SizedBox(width: 8),
        Expanded(
            child: Text(label,
                style: TextStyle(
                    color: Colors.white.withOpacity(0.5), fontSize: 11))),
        Text(value,
            style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.bold)),
      ],
    );
  }

  Widget _buildInsightsTab() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Intelligence Actions ──
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  icon: const Icon(Icons.psychology, size: 18),
                  label: const Text("AI MODES", style: TextStyle(fontSize: 11)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF9D4EDD).withOpacity(0.2),
                    foregroundColor: const Color(0xFF9D4EDD),
                    side:
                        const BorderSide(color: Color(0xFF9D4EDD), width: 0.5),
                  ),
                  onPressed: () {
                    final clientId = _getFilteredClients().isNotEmpty
                        ? (_getFilteredClients().first['hardware_id'] ??
                                _getFilteredClients().first['id'] ??
                                '')
                            .toString()
                        : '';
                    if (clientId.isNotEmpty) {
                      _showCoachAiModePicker(clientId);
                    } else {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(
                            content: Text("No clients available"),
                            backgroundColor: Colors.orange),
                      );
                    }
                  },
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton.icon(
                  icon: const Icon(Icons.science, size: 18),
                  label: const Text("NEVEDAL REPORT",
                      style: TextStyle(fontSize: 11)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFC9A962).withOpacity(0.2),
                    foregroundColor: const Color(0xFFC9A962),
                    side:
                        const BorderSide(color: Color(0xFFC9A962), width: 0.5),
                  ),
                  onPressed: _showNevedalReportDialog,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // ── Chat Box + 2x2 Stats Grid ──
          SizedBox(
            height: 240,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Chat box (left — takes ~60% width)
                Expanded(
                  flex: 3,
                  child: _buildInsightsChatBox(),
                ),
                const SizedBox(width: 10),
                // 2x2 stat grid (right — takes ~40% width)
                Expanded(
                  flex: 2,
                  child: Column(
                    children: [
                      Expanded(
                        child: Row(
                          children: [
                            Expanded(
                                child: _buildStatCard(
                                    "Total Clients",
                                    _clients.length.toString(),
                                    Icons.people,
                                    const Color(0xFF4361EE))),
                            const SizedBox(width: 8),
                            Expanded(
                                child: _buildStatCard("High Risk", "0",
                                    Icons.warning, const Color(0xFFFF9F1C))),
                          ],
                        ),
                      ),
                      const SizedBox(height: 8),
                      Expanded(
                        child: Row(
                          children: [
                            Expanded(
                                child: _buildStatCard(
                                    "Sessions Today",
                                    _schedule.length.toString(),
                                    Icons.calendar_today,
                                    const Color(0xFF00F5D4))),
                            const SizedBox(width: 8),
                            Expanded(
                                child: _buildStatCard("Breakthroughs", "0",
                                    Icons.star, const Color(0xFFFFD700))),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),

          // Search and filter
          _buildClientSearchAndFilter(),

          _buildCoachOverrideInsightsSection(),

          const Text(
            "CLIENT OVERVIEW",
            style: TextStyle(
                color: Colors.grey,
                fontWeight: FontWeight.bold,
                letterSpacing: 1.5,
                fontSize: 12),
          ),
          const SizedBox(height: 12),

          // Client metrics overview
          ..._getFilteredClients().map((client) {
            final metrics = (client['metrics'] is Map)
                ? Map<String, dynamic>.from(client['metrics'])
                : <String, dynamic>{};
            final plan = (client['subscription_plan'] ?? client['tier'] ?? '')
                .toString()
                .toUpperCase();
            final companyName = (client['company_name'] ?? '').toString();
            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A2E),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          client['name'] ?? 'Unknown',
                          style: const TextStyle(
                              color: Colors.white, fontWeight: FontWeight.w500),
                        ),
                        if (plan == 'COACH_ONLY' || companyName.isNotEmpty)
                          Row(
                            children: [
                              if (plan == 'COACH_ONLY')
                                Container(
                                  margin:
                                      const EdgeInsets.only(top: 2, right: 4),
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 4, vertical: 1),
                                  decoration: BoxDecoration(
                                    color: const Color(0xFFC9A962)
                                        .withOpacity(0.15),
                                    borderRadius: BorderRadius.circular(4),
                                  ),
                                  child: const Text('COACH-ONLY',
                                      style: TextStyle(
                                          color: Color(0xFFC9A962),
                                          fontSize: 8,
                                          fontWeight: FontWeight.w600)),
                                ),
                              if (companyName.isNotEmpty)
                                Flexible(
                                  child: Text(companyName,
                                      style: const TextStyle(
                                          color: Colors.grey, fontSize: 9),
                                      overflow: TextOverflow.ellipsis),
                                ),
                            ],
                          ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: Text(
                      metrics['coherence']?.toString() ?? '—',
                      style: const TextStyle(
                          color: Color(0xFF00FFFF), fontFamily: 'Courier'),
                      textAlign: TextAlign.center,
                    ),
                  ),
                  Expanded(
                    child: Text(
                      (metrics['growth'] ??
                              metrics['growth_potential'] ??
                              metrics['GAP'] ??
                              '—')
                          .toString(),
                      style: const TextStyle(
                          color: Color(0xFF9D4EDD), fontFamily: 'Courier'),
                      textAlign: TextAlign.center,
                    ),
                  ),
                  RiskBadge(
                      riskLevel: (metrics['risk_level'] ?? 'LOW').toString()),
                ],
              ),
            );
          }).toList(),
        ],
      ),
    );
  }

  Widget _buildBriefingsTab() {
    if (_clients.isEmpty) {
      return _buildEmptyStateTab(
        icon: Icons.folder,
        title: "BRIEFINGS",
        subtitle: "No folders yet (no clients assigned).",
      );
    }

    final folders = _buildFolderGroups();
    final isWide = MediaQuery.of(context).size.width > 980;

    // Auto-select first folder on wide screens only (mobile shows full folder list first)
    if (_selectedFolderId == null && isWide) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        if (folders.isEmpty) return;
        final first = folders.first;
        _openFolder(
          folderId: first['folder_id'],
          label: first['label'],
          familyId: first['family_id'],
          clients: List<Map<String, dynamic>>.from(first['clients'] ?? []),
        );
      });
    }
    final folderList = Column(
      children: [
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: _buildClientSearchAndFilter(),
        ),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            itemCount: folders.length,
            itemBuilder: (context, index) {
              final f = folders[index];
              final selected = f['folder_id'] == _selectedFolderId;
              final folderType = (f['folder_type'] ?? 'family').toString();

              // Type-appropriate icons
              IconData folderIcon;
              Color iconColor;
              switch (folderType) {
                case 'company':
                  folderIcon = Icons.business;
                  iconColor = const Color(0xFF4ECDC4);
                  break;
                case 'coach_only':
                  folderIcon = Icons.calendar_today;
                  iconColor = const Color(0xFFC9A962);
                  break;
                default:
                  folderIcon = Icons.folder;
                  iconColor = const Color(0xFFFFD700);
              }

              return InkWell(
                onTap: () => _openFolder(
                  folderId: f['folder_id'],
                  label: f['label'],
                  familyId: f['family_id'],
                  clients: List<Map<String, dynamic>>.from(f['clients'] ?? []),
                ),
                borderRadius: BorderRadius.circular(12),
                child: Container(
                  margin: const EdgeInsets.only(bottom: 10),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: selected
                        ? Colors.white.withOpacity(0.06)
                        : Colors.white.withOpacity(0.03),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                        color: selected
                            ? const Color(0xFFFFD700).withOpacity(0.4)
                            : Colors.white10),
                  ),
                  child: Row(
                    children: [
                      Icon(folderIcon, color: iconColor, size: 18),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          (f['label'] ?? 'Folder').toString(),
                          style: TextStyle(
                            color: selected ? Colors.white : Colors.white70,
                            fontWeight:
                                selected ? FontWeight.bold : FontWeight.w500,
                            fontSize: 12,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );

    final folderContent = _buildFolderContent();

    if (!isWide) {
      if (_selectedFolderId != null) {
        return Column(
          children: [
            _buildMobileFilterBar(),
            const Divider(color: Colors.white10, height: 1),
            Expanded(child: folderContent),
          ],
        );
      }
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
            child: _buildClientSearchAndFilter(),
          ),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              itemCount: folders.length,
              itemBuilder: (context, index) {
                final f = folders[index];
                final folderType = (f['folder_type'] ?? 'family').toString();
                IconData folderIcon;
                Color iconColor;
                switch (folderType) {
                  case 'company':
                    folderIcon = Icons.business;
                    iconColor = const Color(0xFF4ECDC4);
                    break;
                  case 'coach_only':
                    folderIcon = Icons.calendar_today;
                    iconColor = const Color(0xFFC9A962);
                    break;
                  default:
                    folderIcon = Icons.folder;
                    iconColor = const Color(0xFFFFD700);
                }
                return InkWell(
                  onTap: () => _openFolder(
                    folderId: f['folder_id'],
                    label: f['label'],
                    familyId: f['family_id'],
                    clients:
                        List<Map<String, dynamic>>.from(f['clients'] ?? []),
                  ),
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: Colors.white.withOpacity(0.03),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Row(
                      children: [
                        Icon(folderIcon, color: iconColor, size: 20),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            (f['label'] ?? 'Folder').toString(),
                            style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.w500,
                              fontSize: 14,
                            ),
                          ),
                        ),
                        Text(
                          '${(f['clients'] as List?)?.length ?? 0}',
                          style:
                              const TextStyle(color: Colors.grey, fontSize: 12),
                        ),
                        const SizedBox(width: 4),
                        const Icon(Icons.chevron_right,
                            color: Colors.grey, size: 18),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      );
    }

    return Row(
      children: [
        SizedBox(width: 320, child: folderList),
        const VerticalDivider(color: Colors.white10, width: 1),
        Expanded(child: folderContent),
      ],
    );
  }

  /// Compact mobile header when a folder is open — shows folder name + back button
  Widget _buildMobileFilterBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: const BoxDecoration(
        color: Color(0xFF111118),
        border: Border(bottom: BorderSide(color: Colors.white10, width: 0.5)),
      ),
      child: Row(
        children: [
          InkWell(
            onTap: () => setState(() {
              _selectedFolderId = null;
              _selectedFolderLabel = null;
              _selectedFolderClients = [];
            }),
            borderRadius: BorderRadius.circular(8),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.06),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.arrow_back_ios,
                      color: Color(0xFFC9A962), size: 14),
                  SizedBox(width: 4),
                  Text("Folders",
                      style: TextStyle(
                          color: Color(0xFFC9A962),
                          fontSize: 12,
                          fontWeight: FontWeight.w600)),
                ],
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              _selectedFolderLabel ?? "Briefing",
              style: const TextStyle(
                color: Colors.white,
                fontSize: 15,
                fontWeight: FontWeight.bold,
                letterSpacing: 0.5,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Text(
            '${_selectedFolderClients.length} member${_selectedFolderClients.length == 1 ? '' : 's'}',
            style: const TextStyle(color: Colors.grey, fontSize: 11),
          ),
        ],
      ),
    );
  }

  /// Builds the reusable search bar + toggle chips for client filtering
  Widget _buildClientSearchAndFilter() {
    return Column(
      children: [
        // Search bar
        Container(
          margin: const EdgeInsets.only(bottom: 10),
          child: TextField(
            controller: _clientSearchController,
            style: const TextStyle(color: Colors.white, fontSize: 13),
            decoration: InputDecoration(
              hintText: 'Search by name, company, or family...',
              hintStyle: const TextStyle(color: Colors.grey, fontSize: 12),
              prefixIcon:
                  const Icon(Icons.search, color: Colors.grey, size: 20),
              suffixIcon: _clientSearchQuery.isNotEmpty
                  ? IconButton(
                      icon:
                          const Icon(Icons.clear, color: Colors.grey, size: 18),
                      onPressed: () {
                        _clientSearchController.clear();
                        setState(() => _clientSearchQuery = '');
                      },
                    )
                  : null,
              filled: true,
              fillColor: const Color(0xFF1A1A1A),
              contentPadding:
                  const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: Color(0xFF252525)),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: Color(0xFF252525)),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: Color(0xFFC9A962)),
              ),
            ),
            onChanged: (val) => setState(() => _clientSearchQuery = val),
          ),
        ),
        // Toggle chips
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              _buildFilterChip('All', 'ALL'),
              const SizedBox(width: 6),
              _buildFilterChip('Clients', 'CLIENTS'),
              const SizedBox(width: 6),
              _buildFilterChip('Families', 'FAMILY'),
              const SizedBox(width: 6),
              _buildFilterChip('Coach-Only', 'COACH_ONLY'),
              const SizedBox(width: 6),
              _buildFilterChip('Company', 'COMPANY'),
            ],
          ),
        ),
        const SizedBox(height: 10),
      ],
    );
  }

  Widget _buildFilterChip(String label, String mode) {
    final isActive = _clientFilterMode == mode;
    return ChoiceChip(
      label: Text(label,
          style: TextStyle(
            color: isActive ? Colors.black : Colors.grey,
            fontSize: 11,
            fontWeight: isActive ? FontWeight.w600 : FontWeight.normal,
          )),
      selected: isActive,
      selectedColor: const Color(0xFFC9A962),
      backgroundColor: const Color(0xFF1A1A1A),
      side: BorderSide(
          color: isActive ? const Color(0xFFC9A962) : const Color(0xFF252525)),
      visualDensity: VisualDensity.compact,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      onSelected: (selected) {
        if (selected) setState(() => _clientFilterMode = mode);
      },
    );
  }

  /// Returns filtered clients based on search query and filter mode
  List<Map<String, dynamic>> _getFilteredClients() {
    List<Map<String, dynamic>> filtered = [];
    for (final c in _clients) {
      if (c is! Map) continue;
      final m = Map<String, dynamic>.from(c as Map);

      // Apply filter mode
      final plan =
          (m['subscription_plan'] ?? m['tier'] ?? '').toString().toUpperCase();
      final familyId = (m['family_id'] ?? '').toString().trim();
      final companyId = (m['company_id'] ?? '').toString().trim();

      switch (_clientFilterMode) {
        case 'CLIENTS':
          break;
        case 'FAMILY':
          if (familyId.isEmpty || plan == 'COACH_ONLY') continue;
          break;
        case 'COACH_ONLY':
          if (plan != 'COACH_ONLY') continue;
          break;
        case 'COMPANY':
          if (companyId.isEmpty) continue;
          break;
        case 'ALL':
        default:
          break;
      }

      // Apply search query
      if (_clientSearchQuery.isNotEmpty) {
        final q = _clientSearchQuery.toLowerCase();
        final name = (m['name'] ?? '').toString().toLowerCase();
        final companyName = (m['company_name'] ?? '').toString().toLowerCase();
        final cId = (m['company_id'] ?? '').toString().toLowerCase();
        final fId = (m['family_id'] ?? '').toString().toLowerCase();
        if (!name.contains(q) &&
            !companyName.contains(q) &&
            !cId.contains(q) &&
            !fId.contains(q)) {
          continue;
        }
      }

      filtered.add(m);
    }
    return filtered;
  }

  List<Map<String, dynamic>> _buildFolderGroups() {
    // Group assigned clients into family/company folders when possible.
    final filteredClients = _getFilteredClients();
    final Map<String, List<Map<String, dynamic>>> byFamily = {};
    final Map<String, List<Map<String, dynamic>>> byCompany = {};
    final List<Map<String, dynamic>> individuals = [];

    for (final m in filteredClients) {
      final familyId = (m['family_id'] ?? '').toString().trim();
      final companyId = (m['company_id'] ?? '').toString().trim();
      final plan =
          (m['subscription_plan'] ?? m['tier'] ?? '').toString().toUpperCase();

      if (_clientFilterMode == 'CLIENTS') {
        individuals.add(m);
      } else if (_clientFilterMode == 'COMPANY' && companyId.isNotEmpty) {
        byCompany.putIfAbsent(companyId, () => []).add(m);
      } else if (_clientFilterMode == 'COACH_ONLY') {
        if (companyId.isNotEmpty) {
          byCompany.putIfAbsent(companyId, () => []).add(m);
        } else {
          individuals.add(m);
        }
      } else if (familyId.isNotEmpty) {
        byFamily.putIfAbsent(familyId, () => []).add(m);
      } else if (companyId.isNotEmpty) {
        byCompany.putIfAbsent(companyId, () => []).add(m);
      } else {
        individuals.add(m);
      }
    }

    final List<Map<String, dynamic>> out = [];

    String folderLabelForFamily(List<Map<String, dynamic>> members) {
      final names = members
          .map((e) => (e['name'] ?? '').toString())
          .where((s) => s.trim().isNotEmpty)
          .toList();
      if (names.isEmpty) return "Family";
      // Try common last name heuristic
      String lastNameOf(String full) {
        final parts = full.trim().split(RegExp(r"\s+"));
        return parts.isNotEmpty ? parts.last : full.trim();
      }

      final lastNames = names.map(lastNameOf).toList();
      final common = lastNames.toSet().length == 1 ? lastNames.first : '';
      return common.isNotEmpty ? "$common Family" : "${names.first} Family";
    }

    String worstRisk(List<Map<String, dynamic>> members) {
      int rank(String risk) {
        final r = risk.toUpperCase();
        if (r == 'CRITICAL' || r == 'RED' || r == 'P0' || r == 'P1') return 4;
        if (r == 'HIGH') return 3;
        if (r == 'MEDIUM' || r == 'MODERATE' || r == 'YELLOW') return 2;
        return 1;
      }

      String pick = 'LOW';
      int best = 0;
      for (final m in members) {
        final metrics = (m['metrics'] is Map)
            ? Map<String, dynamic>.from(m['metrics'])
            : <String, dynamic>{};
        final ns = (m['nevedal_state'] is Map)
            ? Map<String, dynamic>.from(m['nevedal_state'])
            : <String, dynamic>{};
        final risk =
            (metrics['risk_level'] ?? ns['risk_level'] ?? 'LOW').toString();
        final r = rank(risk);
        if (r > best) {
          best = r;
          pick = risk;
        }
      }
      return pick.toUpperCase();
    }

    String subtitleForFamily(List<Map<String, dynamic>> members) {
      final names = members
          .map((e) => (e['name'] ?? '').toString())
          .where((s) => s.trim().isNotEmpty)
          .toList();
      final joined = names.take(4).join(', ');
      final extra = names.length > 4 ? " +${names.length - 4}" : "";
      // Best-effort "last session" using last_login
      String last = "";
      for (final m in members) {
        final ll = (m['last_login'] ?? '').toString();
        if (ll.isNotEmpty && (last.isEmpty || ll.compareTo(last) > 0))
          last = ll;
      }
      final lastTxt =
          last.isNotEmpty ? " • Last: ${last.substring(0, 10)}" : "";
      return "$joined$extra$lastTxt";
    }

    // Merge family entries that resolve to the same folder label (dedup)
    final Map<String, String> famLabelToId = {};
    for (final fid in byFamily.keys.toList()) {
      final label = folderLabelForFamily(byFamily[fid]!);
      if (famLabelToId.containsKey(label)) {
        byFamily[famLabelToId[label]!]!.addAll(byFamily[fid]!);
        byFamily.remove(fid);
      } else {
        famLabelToId[label] = fid;
      }
    }

    // Merge company entries that resolve to the same display name (dedup)
    final Map<String, String> compLabelToId = {};
    for (final cid in byCompany.keys.toList()) {
      final cName = byCompany[cid]!.isNotEmpty
          ? (byCompany[cid]!.first['company_name'] ?? cid).toString()
          : cid;
      if (compLabelToId.containsKey(cName)) {
        byCompany[compLabelToId[cName]!]!.addAll(byCompany[cid]!);
        byCompany.remove(cid);
      } else {
        compLabelToId[cName] = cid;
      }
    }

    byFamily.forEach((familyId, members) {
      out.add({
        "folder_id": "family:$familyId",
        "family_id": familyId,
        "label": folderLabelForFamily(members),
        "subtitle": subtitleForFamily(members),
        "risk_level": worstRisk(members),
        "clients": members,
        "folder_type": "family",
      });
    });

    byCompany.forEach((companyId, members) {
      final companyName = members.isNotEmpty
          ? (members.first['company_name'] ?? companyId).toString()
          : companyId;
      out.add({
        "folder_id": "company:$companyId",
        "company_id": companyId,
        "family_id": "",
        "label": companyName,
        "subtitle": subtitleForFamily(members),
        "risk_level": worstRisk(members),
        "clients": members,
        "folder_type": "company",
      });
    });

    for (final c in individuals) {
      final plan =
          (c['subscription_plan'] ?? c['tier'] ?? '').toString().toUpperCase();
      final isCoachOnly = plan == 'COACH_ONLY';
      final cFamilyId = (c['family_id'] ?? '').toString().trim();
      final lastLogin = (c['last_login'] ?? '').toString();
      final lastTxt = lastLogin.isNotEmpty && lastLogin.length >= 10
          ? lastLogin.substring(0, 10)
          : '—';
      String tag = isCoachOnly
          ? 'Coach-Only'
          : (cFamilyId.isNotEmpty ? 'Family Member' : 'Individual');
      out.add({
        "folder_id": "client:${(c['id'] ?? '').toString()}",
        "family_id": cFamilyId,
        "company_id": (c['company_id'] ?? '').toString(),
        "label": (c['name'] ?? 'Client').toString(),
        "subtitle": "$tag • Last: $lastTxt",
        "risk_level": ((c['metrics'] is Map)
                ? (c['metrics']['risk_level'] ?? 'LOW')
                : 'LOW')
            .toString(),
        "clients": [c],
        "folder_type": isCoachOnly ? "coach_only" : "individual",
        "subscription_plan": plan,
      });
    }

    // Stable sort: risk desc, then label
    int riskRank(String risk) {
      final r = risk.toUpperCase();
      if (r == 'CRITICAL' || r == 'RED' || r == 'P0' || r == 'P1') return 4;
      if (r == 'HIGH') return 3;
      if (r == 'MEDIUM' || r == 'MODERATE' || r == 'YELLOW') return 2;
      return 1;
    }

    out.sort((a, b) {
      final ra = riskRank((a['risk_level'] ?? 'LOW').toString());
      final rb = riskRank((b['risk_level'] ?? 'LOW').toString());
      if (ra != rb) return rb.compareTo(ra);
      return (a['label'] ?? '')
          .toString()
          .compareTo((b['label'] ?? '').toString());
    });

    return out;
  }

  void _openFolder({
    required String folderId,
    required String label,
    required String familyId,
    required List<Map<String, dynamic>> clients,
  }) {
    if (!mounted) return;
    setState(() {
      _selectedFolderId = folderId;
      _selectedFamilyId = familyId;
      _selectedFolderLabel = label;
      _selectedFolderClients = clients;
      _selectedFolderNotes = [];
    });
    _fetchFolderNotes(
        folderId: folderId,
        familyId: familyId,
        clientId: (clients.length == 1
            ? (clients.first['id'] ?? '')?.toString()
            : null));
  }

  Widget _buildFolderContent() {
    final title = _selectedFolderLabel ?? "Folder";
    final members = _selectedFolderClients;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title.toUpperCase(),
            style: const TextStyle(
                color: Colors.white70,
                fontWeight: FontWeight.bold,
                letterSpacing: 1.5,
                fontSize: 12),
          ),
          const SizedBox(height: 10),

          // Coach Briefing section (best-effort, per-member for now)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A2E),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Colors.white10),
            ),
            child: Row(
              children: [
                const Icon(Icons.assignment,
                    color: Color(0xFFFFD700), size: 18),
                const SizedBox(width: 10),
                const Expanded(
                  child: Text(
                    "COACH BRIEFING",
                    style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1.2,
                        fontSize: 12),
                  ),
                ),
                TextButton(
                  onPressed: () {
                    // For now: refresh notes + allow opening per-member briefings below.
                    _fetchFolderNotes(
                        folderId: _selectedFolderId,
                        familyId: _selectedFamilyId);
                    ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text("Folder refreshed")));
                  },
                  style: TextButton.styleFrom(
                      foregroundColor: const Color(0xFFFFD700)),
                  child: const Text("Refresh"),
                ),
              ],
            ),
          ),

          const SizedBox(height: 14),
          const Text(
            "FAMILY MEMBERS",
            style: TextStyle(
                color: Colors.grey,
                fontWeight: FontWeight.bold,
                letterSpacing: 1.5,
                fontSize: 12),
          ),
          const SizedBox(height: 10),
          ...members.map((m) => _buildFolderMemberCard(m)).toList(),

          const SizedBox(height: 18),
          Row(
            children: [
              const Text(
                "SESSION NOTES",
                style: TextStyle(
                    color: Colors.grey,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5,
                    fontSize: 12),
              ),
              const Spacer(),
              TextButton.icon(
                onPressed:
                    _selectedFolderId == null ? null : _showAddNoteDialog,
                icon: const Icon(Icons.add, size: 18),
                label: const Text("Add"),
                style: TextButton.styleFrom(
                    foregroundColor: const Color(0xFFFFD700)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _notesLoading
              ? const Center(
                  child: Padding(
                      padding: EdgeInsets.all(16),
                      child:
                          CircularProgressIndicator(color: Color(0xFFFFD700))))
              : _buildNotesList(),

          const SizedBox(height: 24),

          // Nate's Memory Section - Shows what Little Nate remembers about sessions
          _buildNateMemorySection(),

          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _buildNateMemorySection() {
    // Get client IDs for this folder
    final clientIds = _selectedFolderClients
        .map((c) => (c['hardware_id'] ?? c['client_id'] ?? '').toString())
        .where((id) => id.isNotEmpty)
        .toList();

    if (clientIds.isEmpty) {
      return const SizedBox.shrink();
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A1A),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: const Color(0xFF4ECDC4).withOpacity(0.2),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Icon(Icons.psychology,
                    color: Color(0xFF4ECDC4), size: 18),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  "NATE'S MEMORY",
                  style: TextStyle(
                    color: Color(0xFF4ECDC4),
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5,
                    fontSize: 12,
                  ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.refresh,
                    size: 18, color: Color(0xFF4ECDC4)),
                tooltip: "Refresh memories",
                onPressed: () => setState(() {}), // Force rebuild
              ),
            ],
          ),
          const SizedBox(height: 12),
          const Text(
            "What Little Nate remembers from coaching sessions:",
            style: TextStyle(color: Colors.white54, fontSize: 11),
          ),
          const SizedBox(height: 10),

          // Memory entries would come from API
          // For now, show a sample structure
          FutureBuilder<List<Map<String, dynamic>>>(
            future: _fetchMemoriesForClients(clientIds),
            builder: (context, snapshot) {
              if (snapshot.connectionState == ConnectionState.waiting) {
                return const Center(
                  child: Padding(
                    padding: EdgeInsets.all(20),
                    child: CircularProgressIndicator(
                      color: Color(0xFF4ECDC4),
                      strokeWidth: 2,
                    ),
                  ),
                );
              }

              final memories = snapshot.data ?? [];

              if (memories.isEmpty) {
                return Container(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    children: [
                      Icon(Icons.memory,
                          color: Colors.grey.withOpacity(0.3), size: 40),
                      const SizedBox(height: 10),
                      const Text(
                        "No memories yet",
                        style: TextStyle(color: Colors.grey, fontSize: 12),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        "Archive Zoom transcripts to build Nate's memory",
                        style: TextStyle(
                            color: Colors.grey.withOpacity(0.6), fontSize: 10),
                      ),
                    ],
                  ),
                );
              }

              return Column(
                children: memories
                    .take(5)
                    .map((memory) => _buildMemoryCard(memory))
                    .toList(),
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _buildMemoryCard(Map<String, dynamic> memory) {
    final sessionId = memory['session_id'] ?? '';
    final summary = memory['summary'] ?? 'Session recorded';
    final techniques = List<String>.from(memory['techniques'] ?? []);
    final createdAt = memory['created_at'] ?? '';
    final growthAreas = List<String>.from(memory['growth_areas'] ?? []);

    // Format date
    String dateStr = '';
    try {
      final dt = DateTime.parse(createdAt);
      dateStr = "${dt.month}/${dt.day}/${dt.year}";
    } catch (_) {
      dateStr = createdAt;
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.auto_stories,
                  size: 14, color: Color(0xFFFFD700)),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  "Session $sessionId",
                  style: const TextStyle(
                    color: Colors.white70,
                    fontWeight: FontWeight.w600,
                    fontSize: 11,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                dateStr,
                style: TextStyle(
                    color: Colors.grey.withOpacity(0.6), fontSize: 10),
              ),
            ],
          ),
          if (summary.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              summary,
              style: const TextStyle(color: Colors.white54, fontSize: 11),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          if (techniques.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: techniques
                  .take(3)
                  .map((t) => Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: const Color(0xFF00F5D4).withOpacity(0.15),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          t,
                          style: const TextStyle(
                              color: Color(0xFF00F5D4), fontSize: 9),
                        ),
                      ))
                  .toList(),
            ),
          ],
          if (growthAreas.isNotEmpty) ...[
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: growthAreas
                  .take(2)
                  .map((g) => Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: Colors.orange.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          g,
                          style: const TextStyle(
                              color: Colors.orange, fontSize: 9),
                        ),
                      ))
                  .toList(),
            ),
          ],
        ],
      ),
    );
  }

  Future<List<Map<String, dynamic>>> _fetchMemoriesForClients(
      List<String> clientIds) async {
    // This would call the backend API to get memories
    // For now, return empty list - will be populated when backend is running
    if (clientIds.isEmpty) return [];

    try {
      // Try to fetch from API
      final clientId = clientIds.first;
      final uri = _apiUri('/api/night-school/memories/client/$clientId');
      final resp = await http
          .get(uri, headers: _restHeaders())
          .timeout(const Duration(seconds: 5));

      if (resp.statusCode >= 200 && resp.statusCode < 300) {
        final data = jsonDecode(resp.body);
        if (data is Map && data['memories'] is List) {
          return List<Map<String, dynamic>>.from(data['memories']);
        }
      }
    } catch (e) {
      // API not available yet, return empty
      debugPrint('[Briefings] Memory fetch error: $e');
    }

    return [];
  }

  Widget _buildFolderMemberCard(Map<String, dynamic> member) {
    final id = (member['id'] ?? '').toString();
    final name = (member['name'] ?? 'Member').toString();
    final ns = (member['nevedal_state'] is Map)
        ? Map<String, dynamic>.from(member['nevedal_state'])
        : <String, dynamic>{};
    final metrics = (member['metrics'] is Map)
        ? Map<String, dynamic>.from(member['metrics'])
        : <String, dynamic>{};
    final risk =
        (metrics['risk_level'] ?? ns['risk_level'] ?? 'LOW').toString();

    final cEmo = ns['C_emo'] ?? metrics['C_emo'] ?? metrics['coherence'];
    final gap = ns['GAP'] ??
        metrics['GAP'] ??
        metrics['growth'] ??
        metrics['growth_potential'];
    final quantum = ns['Quantum'] ??
        metrics['Quantum'] ??
        metrics['wellness'] ??
        metrics['wellness_score'];

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.03),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: const Color(0xFF9D4EDD).withOpacity(0.25),
            child: Text(
              name.isNotEmpty ? name[0].toUpperCase() : '?',
              style: const TextStyle(
                  color: Color(0xFF9D4EDD), fontWeight: FontWeight.bold),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(name,
                          style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold)),
                    ),
                    RiskBadge(riskLevel: risk),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  "C_emo: ${_fmt01(cEmo)}   GAP: ${_fmt01(gap)}   Quantum: ${_fmt01(quantum)}",
                  style: TextStyle(
                      color: Colors.grey[400],
                      fontSize: 11,
                      fontFamily: 'Courier'),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          OutlinedButton(
            onPressed: id.isEmpty ? null : () => _fetchClientBrief(id),
            style: OutlinedButton.styleFrom(
              side: const BorderSide(color: Color(0xFFFFD700)),
              foregroundColor: const Color(0xFFFFD700),
            ),
            child: const Text("View Brief"),
          ),
        ],
      ),
    );
  }

  String _fmt01(dynamic v) {
    if (v == null) return "—";
    if (v is num) return v.toStringAsFixed(2);
    final s = v.toString().replaceAll('%', '').trim();
    final d = double.tryParse(s);
    if (d == null) return s;
    return d > 1 ? (d / 100.0).toStringAsFixed(2) : d.toStringAsFixed(2);
  }

  Widget _buildNotesList() {
    final notes = _selectedFolderNotes;
    if (notes.isEmpty) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Colors.white.withOpacity(0.03),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white10),
        ),
        child:
            const Text("No notes yet.", style: TextStyle(color: Colors.grey)),
      );
    }

    return Column(
      children: notes.reversed.take(20).map((n) {
        final when = (n['created_at'] ?? '').toString();
        final who = (n['coach_username'] ?? '').toString();
        final text = (n['note_text'] ?? '').toString();
        final shared = (n['share_with_nate'] ?? false) == true;
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A2E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white10),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(
                    when.isNotEmpty ? when.substring(0, 16) : "—",
                    style: TextStyle(
                        color: Colors.grey[500],
                        fontSize: 10,
                        fontFamily: 'Courier'),
                  ),
                  const SizedBox(width: 10),
                  if (who.isNotEmpty)
                    Text(
                      who,
                      style:
                          const TextStyle(color: Colors.white54, fontSize: 10),
                    ),
                  const Spacer(),
                  if (shared)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: const Color(0xFF00F5D4).withOpacity(0.12),
                        borderRadius: BorderRadius.circular(999),
                        border: Border.all(
                            color: const Color(0xFF00F5D4).withOpacity(0.3)),
                      ),
                      child: const Text("Shared with Nate",
                          style: TextStyle(
                              color: Color(0xFF00F5D4), fontSize: 10)),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                text,
                style: const TextStyle(
                    color: Colors.white70, fontSize: 12, height: 1.35),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  void _showAddNoteDialog() {
    final controller = TextEditingController();
    bool share = true;
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF0A0A0F),
          title: const Text("Add Session Note",
              style: TextStyle(color: Color(0xFFFFD700))),
          content: SizedBox(
            width: 520,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: controller,
                  maxLines: 6,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                    hintText: "Type your note…",
                    hintStyle: TextStyle(color: Colors.grey),
                    border: OutlineInputBorder(),
                    enabledBorder: OutlineInputBorder(
                        borderSide: BorderSide(color: Colors.white10)),
                    focusedBorder: OutlineInputBorder(
                        borderSide: BorderSide(color: Color(0xFFFFD700))),
                  ),
                ),
                const SizedBox(height: 10),
                CheckboxListTile(
                  value: share,
                  onChanged: (v) => setLocal(() => share = (v ?? true)),
                  activeColor: const Color(0xFFFFD700),
                  checkColor: Colors.black,
                  title: const Text("Share with Little Nate for learning",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  contentPadding: EdgeInsets.zero,
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFFFFD700),
                  foregroundColor: Colors.black),
              onPressed: () {
                final text = controller.text.trim();
                if (text.isEmpty) return;
                Navigator.pop(ctx);
                final folderId = _selectedFolderId;
                final familyId = _selectedFamilyId;
                final clientId = (_selectedFolderClients.length == 1)
                    ? (_selectedFolderClients.first['id'] ?? '').toString()
                    : '';
                _addFolderNote(
                  noteText: text,
                  folderId: folderId,
                  familyId: familyId,
                  clientId: clientId.isNotEmpty ? clientId : null,
                  shareWithNate: share,
                );
              },
              child: const Text("Save"),
            ),
          ],
        ),
      ),
    );
  }

  String _composeLiveNoteDictation(String base, String addition) {
    final b = base;
    final a = addition.trim();
    if (b.trim().isEmpty) return a;
    if (a.isEmpty) return b;
    if (b.endsWith(' ') || b.endsWith('\n') || b.endsWith('\t')) return '$b$a';
    return '$b $a';
  }

  Future<void> _ensureLiveNoteSpeechInitialized() async {
    if (_liveNoteSpeechInited) return;
    if (kIsWeb) {
      _liveNoteSpeechInited = true;
      _liveNoteSpeechAvailable = false;
      return;
    }
    try {
      _liveNoteSpeechAvailable = await _liveNoteSpeech.initialize(
        onError: (err) {
          if (kDebugMode) debugPrint('[Live session STT] $err');
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'Dictation needs microphone access. ${err.errorMsg.isNotEmpty ? err.errorMsg : 'Allow the microphone in Settings.'}',
              ),
              backgroundColor: const Color(0xFF8B7355),
            ),
          );
        },
        onStatus: (status) {
          if (status == 'done' || status == 'notListening') {
            if (mounted) setState(() => _liveNoteListening = false);
            _liveSheetRebuild?.call();
            if (_liveNoteDictationArmed) _scheduleLiveNoteDictationRestart();
          }
        },
      );
    } catch (e) {
      if (kDebugMode) debugPrint('[Live session STT] init failed: $e');
      _liveNoteSpeechAvailable = false;
    }
    _liveNoteSpeechInited = true;
  }

  Future<void> _suppressAndStopLiveNoteSpeech() async {
    _liveNoteSuppressUntil =
        DateTime.now().add(const Duration(milliseconds: 800));
    if (_liveNoteListening) {
      try {
        await _liveNoteSpeech.stop();
      } catch (_) {}
      try {
        await _liveNoteSpeech.cancel();
      } catch (_) {}
      if (mounted) setState(() => _liveNoteListening = false);
      _liveSheetRebuild?.call();
    }
  }

  void _scheduleLiveNoteDictationRestart({int delayMs = 150}) {
    if (_liveNoteSttRestartScheduled) return;
    _liveNoteSttRestartScheduled = true;
    Future.delayed(Duration(milliseconds: delayMs), () {
      _liveNoteSttRestartScheduled = false;
      if (!mounted) return;
      final ctrl = _liveNoteSttBoundController;
      if (_liveNoteDictationArmed && !_liveNoteListening && ctrl != null) {
        _startLiveNoteListeningSession(ctrl);
      }
    });
  }

  Future<void> _startLiveNoteListeningSession(
      TextEditingController noteCtrl) async {
    if (kIsWeb || !_liveNoteSpeechAvailable) return;
    _liveNoteSttBoundController = noteCtrl;
    _liveNoteDictationBase = noteCtrl.text;
    _liveNoteDictationSession = '';
    if (mounted) setState(() => _liveNoteListening = true);
    _liveSheetRebuild?.call();
    await _liveNoteSpeech.listen(
      onResult: (result) {
        final ctrl = _liveNoteSttBoundController;
        if (ctrl == null) return;
        if (!_liveNoteListening) return;

        final until = _liveNoteSuppressUntil;
        if (until != null && DateTime.now().isBefore(until)) return;

        final raw = result.recognizedWords.trim();
        if (raw.isEmpty) return;

        if (!mounted) return;
        if (result.finalResult) {
          _liveNoteDictationBase =
              _composeLiveNoteDictation(_liveNoteDictationBase, raw);
          _liveNoteDictationSession = '';
          ctrl.text = _liveNoteDictationBase;
        } else {
          _liveNoteDictationSession = raw;
          ctrl.text = _composeLiveNoteDictation(
              _liveNoteDictationBase, _liveNoteDictationSession);
        }
        _liveSheetRebuild?.call();
        setState(() {});
      },
      listenFor: const Duration(seconds: 60),
      pauseFor: const Duration(seconds: 6),
      partialResults: true,
      cancelOnError: true,
      listenMode: ListenMode.dictation,
    );
  }

  Future<void> _toggleLiveNoteDictation(TextEditingController noteCtrl) async {
    if (kIsWeb) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Dictation available on mobile app only'),
          backgroundColor: Color(0xFF1A1A2E),
        ),
      );
      return;
    }
    await _ensureLiveNoteSpeechInitialized();
    if (!_liveNoteSpeechAvailable) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Microphone access is required for dictation. Allow it when prompted, or enable it in your device settings.',
          ),
          backgroundColor: Color(0xFF8B7355),
        ),
      );
      return;
    }
    if (_liveNoteDictationArmed) {
      _liveNoteDictationArmed = false;
      await _suppressAndStopLiveNoteSpeech();
      _liveSheetRebuild?.call();
      return;
    }
    _liveNoteDictationArmed = true;
    await _startLiveNoteListeningSession(noteCtrl);
  }

  void _showLiveSessionSheet(
      {required String initialLabel,
      required String initialMeetingUrl,
      String initialHostUrl = ''}) {
    if (_liveSheetOpen) return;
    _liveSheetOpen = true;
    final noteCtrl = TextEditingController();
    bool shareAtEnd = true;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF0A0A0F),
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(18))),
      builder: (context) => StatefulBuilder(
        builder: (context, setLocal) {
          _liveSheetRebuild = () => setLocal(() {});
          return DraggableScrollableSheet(
            initialChildSize: 0.92,
            minChildSize: 0.65,
            maxChildSize: 0.97,
            expand: false,
            builder: (context, scrollController) {
              final liveId = (_activeLiveSession?['id'] ?? '').toString();
              final meetingUrl =
                  (_activeLiveSession?['meeting_url'] ?? initialMeetingUrl)
                      .toString();
              final label =
                  (_activeLiveSession?['label'] ?? initialLabel).toString();

              return SingleChildScrollView(
                controller: scrollController,
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(
                      child: Container(
                        width: 44,
                        height: 4,
                        decoration: BoxDecoration(
                            color: Colors.white24,
                            borderRadius: BorderRadius.circular(999)),
                      ),
                    ),
                    const SizedBox(height: 14),
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            label,
                            style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: 16),
                          ),
                        ),
                        if (liveId.isNotEmpty) ...[
                          GestureDetector(
                            onTap: () {
                              final clientId =
                                  (_activeLiveSession?['client_id'] ?? '')
                                      .toString();
                              if (clientId.isNotEmpty) {
                                Navigator.pop(context);
                                _openSessionAssistant(clientId, liveId);
                              }
                            },
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 8, vertical: 6),
                              margin: const EdgeInsets.only(right: 6),
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(999),
                                border: Border.all(
                                    color: const Color(0xFF9D4EDD)
                                        .withOpacity(0.4)),
                                color:
                                    const Color(0xFF9D4EDD).withOpacity(0.10),
                              ),
                              child: const Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(Icons.psychology,
                                        color: Color(0xFF9D4EDD), size: 14),
                                    SizedBox(width: 4),
                                    Text("AI",
                                        style: TextStyle(
                                            color: Color(0xFF9D4EDD),
                                            fontWeight: FontWeight.bold,
                                            fontSize: 12)),
                                  ]),
                            ),
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 10, vertical: 6),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(999),
                              border: Border.all(
                                  color:
                                      const Color(0xFF00F5D4).withOpacity(0.4)),
                              color: const Color(0xFF00F5D4).withOpacity(0.10),
                            ),
                            child: const Text("LIVE",
                                style: TextStyle(
                                    color: Color(0xFF00F5D4),
                                    fontWeight: FontWeight.bold)),
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: 10),

                    // Video link row - launches Zoom directly
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.white.withOpacity(0.03),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: Colors.white10),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.videocam, color: Color(0xFF00F5D4)),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              meetingUrl.isEmpty
                                  ? "No Zoom link yet"
                                  : "Zoom ready",
                              style: const TextStyle(color: Colors.white70),
                            ),
                          ),
                          ElevatedButton.icon(
                            icon: const Icon(Icons.launch, size: 16),
                            label: const Text("Open Zoom"),
                            onPressed: () =>
                                _launchZoomMeeting(initialHostUrl, meetingUrl),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFF00F5D4),
                              foregroundColor: Colors.black,
                            ),
                          ),
                        ],
                      ),
                    ),

                    const SizedBox(height: 14),
                    const Text(
                      "LITTLE NATE OBSERVATION WINDOW",
                      style: TextStyle(
                          color: Colors.grey,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1.5,
                          fontSize: 12),
                    ),
                    const SizedBox(height: 8),
                    ValueListenableBuilder<List<Map<String, dynamic>>>(
                      valueListenable: _liveObservations,
                      builder: (context, obs, _) {
                        if (obs.isEmpty) {
                          return Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: const Color(0xFF1A1A2E),
                              borderRadius: BorderRadius.circular(14),
                              border: Border.all(color: Colors.white10),
                            ),
                            child: const Text(
                              "Waiting for coach notes…",
                              style: TextStyle(color: Colors.white54),
                            ),
                          );
                        }
                        return Column(
                          children: obs.reversed.take(8).map((o) {
                            final ts = (o['timestamp'] ?? '').toString();
                            final msg = (o['message'] ?? '').toString();
                            final ev = (o['evidence'] ?? '').toString();
                            return Container(
                              width: double.infinity,
                              margin: const EdgeInsets.only(bottom: 10),
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: const Color(0xFF1A1A2E),
                                borderRadius: BorderRadius.circular(14),
                                border: Border.all(color: Colors.white10),
                              ),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    ts.isNotEmpty && ts.length >= 19
                                        ? ts.substring(11, 19)
                                        : "—",
                                    style: TextStyle(
                                        color: Colors.grey[500],
                                        fontSize: 10,
                                        fontFamily: 'Courier'),
                                  ),
                                  const SizedBox(height: 6),
                                  Text(msg,
                                      style: const TextStyle(
                                          color: Colors.white,
                                          fontSize: 12,
                                          height: 1.3)),
                                  if (ev.isNotEmpty) ...[
                                    const SizedBox(height: 6),
                                    Text("“$ev”",
                                        style: const TextStyle(
                                            color: Colors.white54,
                                            fontSize: 11,
                                            fontStyle: FontStyle.italic)),
                                  ],
                                ],
                              ),
                            );
                          }).toList(),
                        );
                      },
                    ),

                    const SizedBox(height: 14),
                    const Text(
                      "SESSION NOTES",
                      style: TextStyle(
                          color: Colors.grey,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1.5,
                          fontSize: 12),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: TextField(
                            controller: noteCtrl,
                            readOnly: _liveNoteListening,
                            maxLines: 4,
                            style: const TextStyle(color: Colors.white),
                            decoration: const InputDecoration(
                              hintText: "Type quick notes (send often)…",
                              hintStyle: TextStyle(color: Colors.grey),
                              border: OutlineInputBorder(),
                              enabledBorder: OutlineInputBorder(
                                  borderSide:
                                      BorderSide(color: Colors.white10)),
                              focusedBorder: OutlineInputBorder(
                                  borderSide:
                                      BorderSide(color: Color(0xFFFFD700))),
                            ),
                          ),
                        ),
                        const SizedBox(width: 6),
                        Column(
                          children: [
                            IconButton(
                              tooltip:
                                  kIsWeb ? 'Dictation (mobile app)' : 'Dictate',
                              onPressed: () =>
                                  _toggleLiveNoteDictation(noteCtrl),
                              icon: Icon(
                                Icons.mic,
                                color: _liveNoteListening
                                    ? Colors.redAccent
                                    : Colors.grey,
                              ),
                            ),
                            if (_liveNoteListening)
                              const Padding(
                                padding: EdgeInsets.only(top: 2),
                                child: Text(
                                  'Recording...',
                                  style: TextStyle(
                                      color: Colors.redAccent, fontSize: 10),
                                ),
                              ),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: ElevatedButton.icon(
                            onPressed: liveId.isEmpty
                                ? null
                                : () {
                                    final t = noteCtrl.text;
                                    if (t.trim().isEmpty) return;
                                    noteCtrl.clear();
                                    _sendLiveNote(t);
                                  },
                            icon: const Icon(Icons.send, size: 18),
                            label: const Text("Send Note"),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFFFFD700),
                              foregroundColor: Colors.black,
                              padding: const EdgeInsets.symmetric(vertical: 12),
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: OutlinedButton.icon(
                            onPressed: () =>
                                setLocal(() => shareAtEnd = !shareAtEnd),
                            icon: Icon(
                                shareAtEnd
                                    ? Icons.check_box
                                    : Icons.check_box_outline_blank,
                                size: 18),
                            label: const Text("Share w/ Nate"),
                            style: OutlinedButton.styleFrom(
                              side: const BorderSide(color: Color(0xFF00F5D4)),
                              foregroundColor: const Color(0xFF00F5D4),
                              padding: const EdgeInsets.symmetric(vertical: 12),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: liveId.isEmpty
                            ? null
                            : () => _endLiveSession(shareWithNate: shareAtEnd),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.red.withOpacity(0.20),
                          foregroundColor: Colors.redAccent,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          side: BorderSide(
                              color: Colors.redAccent.withOpacity(0.5)),
                        ),
                        child: const Text("End Session & Save"),
                      ),
                    ),
                    const SizedBox(height: 18),
                    ValueListenableBuilder<List<Map<String, dynamic>>>(
                      valueListenable: _liveNotes,
                      builder: (context, notes, _) {
                        if (notes.isEmpty) return const SizedBox();
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              "NOTES SENT",
                              style: TextStyle(
                                  color: Colors.grey,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1.5,
                                  fontSize: 12),
                            ),
                            const SizedBox(height: 8),
                            ...notes.reversed.take(8).map((n) {
                              final ts = (n['timestamp'] ?? '').toString();
                              final tx = (n['text'] ?? '').toString();
                              return Container(
                                width: double.infinity,
                                margin: const EdgeInsets.only(bottom: 8),
                                padding: const EdgeInsets.all(10),
                                decoration: BoxDecoration(
                                  color: Colors.white.withOpacity(0.03),
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(color: Colors.white10),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      ts.isNotEmpty && ts.length >= 19
                                          ? ts.substring(11, 19)
                                          : "—",
                                      style: TextStyle(
                                          color: Colors.grey[600],
                                          fontSize: 10,
                                          fontFamily: 'Courier'),
                                    ),
                                    const SizedBox(height: 6),
                                    Text(tx,
                                        style: const TextStyle(
                                            color: Colors.white70,
                                            fontSize: 12)),
                                  ],
                                ),
                              );
                            }).toList(),
                          ],
                        );
                      },
                    ),
                    const SizedBox(height: 24),
                  ],
                ),
              );
            },
          );
        },
      ),
    ).whenComplete(() async {
      _liveNoteDictationArmed = false;
      _liveNoteSttBoundController = null;
      _liveSheetRebuild = null;
      await _suppressAndStopLiveNoteSpeech();
      _liveSheetOpen = false;
      noteCtrl.dispose();
    });
  }

  // === SESSION ASSISTANT AI POP-UP (Phase 4) ===
  Map<String, dynamic>? _sessionAssistantData;
  bool _sessionAssistantOpen = false;
  String _sessionAssistantMode = 'observe'; // observe, suggest, challenge

  void _openSessionAssistant(String clientId, String sessionId) {
    final msg = json.encode({
      "type": "session_assistant_open",
      "client_id": clientId,
      "session_id": sessionId,
    });
    _sendMessage(msg);
    setState(() => _sessionAssistantOpen = true);
  }

  void _handleSessionAssistantData(Map<String, dynamic> data) {
    setState(() {
      _sessionAssistantData = data;
    });
  }

  void _sendSessionCheckin(String sessionId, String mood, String note) {
    final msg = json.encode({
      "type": "session_assistant_checkin",
      "session_id": sessionId,
      "mood": mood,
      "note": note,
      "nate_mode": _sessionAssistantMode,
    });
    _sendMessage(msg);
  }

  void _toggleNateAssist(String sessionId, bool enabled) {
    _assistEnabledBySession[sessionId] = enabled;
    final msg = json.encode({
      "type": "session_assistant_nate_toggle",
      "session_id": sessionId,
      "enabled": enabled,
    });
    _sendMessage(msg);
    setState(() {});
  }

  void _setSessionServiceMode(String liveId, String mode) {
    _sessionServiceMode[liveId] = mode;
    _assistEnabledBySession[liveId] = (mode == 'green' || mode == 'yellow');
    _socket?.sink.add(jsonEncode({
      "type": "session_service_mode_change",
      "live_session_id": liveId,
      "service_mode": mode,
    }));
    setState(() {});
  }

  Widget _buildServiceModeSelector(String liveId) {
    final mode = _sessionServiceMode[liveId] ?? 'green';
    const modes = [
      {
        'key': 'green',
        'label': 'Full',
        'color': Color(0xFF22C55E),
        'icon': Icons.visibility
      },
      {
        'key': 'yellow',
        'label': 'Assist',
        'color': Color(0xFFF59E0B),
        'icon': Icons.psychology
      },
      {
        'key': 'blue',
        'label': 'Camera',
        'color': Color(0xFF3B82F6),
        'icon': Icons.videocam
      },
      {
        'key': 'grey',
        'label': 'Paused',
        'color': Color(0xFF6B7280),
        'icon': Icons.pause
      },
    ];
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: modes.map((m) {
        final active = mode == m['key'];
        final c = m['color'] as Color;
        return Padding(
          padding: const EdgeInsets.only(left: 3),
          child: GestureDetector(
            onTap: () => _setSessionServiceMode(liveId, m['key'] as String),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
              decoration: BoxDecoration(
                color: active ? c.withOpacity(0.25) : Colors.transparent,
                borderRadius: BorderRadius.circular(6),
                border: Border.all(
                    color: active ? c : Colors.white12,
                    width: active ? 1.5 : 0.5),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(m['icon'] as IconData,
                    size: 12, color: active ? c : Colors.grey),
                const SizedBox(width: 3),
                Text(m['label'] as String,
                    style: TextStyle(
                        color: active ? c : Colors.grey,
                        fontSize: 9,
                        fontWeight:
                            active ? FontWeight.bold : FontWeight.normal)),
              ]),
            ),
          ),
        );
      }).toList(),
    );
  }

  Future<bool> _checkRecordingConsent(String clientId) async {
    final clientData = _clients.cast<Map<String, dynamic>>().firstWhere(
          (c) => c['id'] == clientId,
          orElse: () => <String, dynamic>{},
        );
    final consent = clientData['recording_consent'];
    if (consent is Map && consent['granted'] == true) return true;

    final result = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: Color(0xFFC9A962), width: 0.5)),
        title: const Text('Recording Consent',
            style: TextStyle(color: Color(0xFFC9A962), fontSize: 16)),
        content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                  'This session uses AI observation and may capture visual data. Please confirm client awareness:',
                  style: TextStyle(color: Colors.white70, fontSize: 13)),
              const SizedBox(height: 16),
              _consentOption(
                  ctx,
                  'permanent',
                  'Client is aware and agrees to recording features',
                  'Consent saved — will not ask again for this client.'),
              const SizedBox(height: 10),
              _consentOption(
                  ctx,
                  'remind',
                  'I will inform the client — remind me next time',
                  'Prompt will appear before every session with this client.'),
            ]),
      ),
    );
    if (result == null) return false;

    _socket?.sink.add(jsonEncode({
      "type": "save_recording_consent",
      "client_id": clientId,
      "consent_type": result,
    }));
    return true;
  }

  Widget _consentOption(
      BuildContext ctx, String value, String title, String subtitle) {
    return InkWell(
      onTap: () => Navigator.of(ctx).pop(value),
      borderRadius: BorderRadius.circular(10),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: Colors.white12),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(
                value == 'permanent'
                    ? Icons.check_circle_outline
                    : Icons.notifications_active,
                color: const Color(0xFF4ECDC4),
                size: 16),
            const SizedBox(width: 8),
            Expanded(
                child: Text(title,
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.w500))),
          ]),
          const SizedBox(height: 4),
          Padding(
            padding: const EdgeInsets.only(left: 24),
            child: Text(subtitle,
                style: TextStyle(color: Colors.grey[500], fontSize: 10)),
          ),
        ]),
      ),
    );
  }

  Widget _buildSessionAssistantOverlay() {
    if (!_sessionAssistantOpen || _sessionAssistantData == null)
      return const SizedBox.shrink();
    final d = _sessionAssistantData!;
    final clientName = d['client_name'] ?? 'Client';
    final sessionId = d['session_id'] ?? '';
    final nateEnabled =
        _assistEnabledBySession[sessionId] ?? (d['nate_enabled'] ?? true);
    final pmb = d['pmb'] ?? {};
    final crisis = d['crisis_perception'] ?? {};
    final shame = d['shame_profile'] ?? {};
    final fcodes = (d['fcodes'] is List)
        ? List<Map<String, dynamic>>.from(d['fcodes'])
        : <Map<String, dynamic>>[];
    final legacy = (d['legacy_patterns'] is List)
        ? List<Map<String, dynamic>>.from(d['legacy_patterns'])
        : <Map<String, dynamic>>[];

    return Positioned(
      right: 12,
      top: 80,
      width: 320,
      child: Material(
        elevation: 12,
        borderRadius: BorderRadius.circular(16),
        color: const Color(0xFF0A0A0F),
        child: Container(
          constraints: const BoxConstraints(maxHeight: 480),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.4)),
          ),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(children: [
                  const Icon(Icons.psychology,
                      color: Color(0xFF4ECDC4), size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                      child: Text("Session Assistant: $clientName",
                          style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold,
                              fontSize: 13))),
                  GestureDetector(
                    onTap: () => setState(() => _sessionAssistantOpen = false),
                    child:
                        const Icon(Icons.close, color: Colors.grey, size: 18),
                  ),
                ]),
                const Divider(color: Colors.white12, height: 16),
                Row(children: [
                  const Text("Nate Mode:",
                      style: TextStyle(color: Colors.grey, fontSize: 10)),
                  const Spacer(),
                  ...['observe', 'suggest', 'challenge'].map((m) => Padding(
                        padding: const EdgeInsets.only(left: 4),
                        child: GestureDetector(
                          onTap: () =>
                              setState(() => _sessionAssistantMode = m),
                          child: Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 8, vertical: 3),
                            decoration: BoxDecoration(
                              color: _sessionAssistantMode == m
                                  ? const Color(0xFF4ECDC4).withOpacity(0.2)
                                  : Colors.transparent,
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(
                                  color: _sessionAssistantMode == m
                                      ? const Color(0xFF4ECDC4)
                                      : Colors.white12),
                            ),
                            child: Text(m[0].toUpperCase() + m.substring(1),
                                style: TextStyle(
                                    color: _sessionAssistantMode == m
                                        ? const Color(0xFF4ECDC4)
                                        : Colors.grey,
                                    fontSize: 10)),
                          ),
                        ),
                      )),
                ]),
                if (_activeLiveSession != null) ...[
                  const SizedBox(height: 6),
                  _buildServiceModeSelector(
                      (_activeLiveSession?['id'] ?? '').toString()),
                ],
                const SizedBox(height: 8),
                if (pmb['reconsolidation_readiness'] != null &&
                    (pmb['reconsolidation_readiness'] as num) > 0.6)
                  Container(
                    padding: const EdgeInsets.all(8),
                    margin: const EdgeInsets.only(bottom: 8),
                    decoration: BoxDecoration(
                      color: const Color(0xFF9D4EDD).withOpacity(0.15),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                          color: const Color(0xFF9D4EDD).withOpacity(0.4)),
                    ),
                    child: Row(children: [
                      const Icon(Icons.auto_awesome,
                          color: Color(0xFF9D4EDD), size: 14),
                      const SizedBox(width: 6),
                      Expanded(
                          child: Text(
                              "Reconsolidation window open (${((pmb['reconsolidation_readiness'] as num) * 100).toInt()}%)",
                              style: const TextStyle(
                                  color: Color(0xFF9D4EDD),
                                  fontSize: 11,
                                  fontWeight: FontWeight.bold))),
                    ]),
                  ),
                _buildAssistantMetricRow(
                    "Crisis Baseline", crisis['baseline'] ?? '-'),
                _buildAssistantMetricRow(
                    "Shame Index", "${((shame['index'] ?? 0) * 100).toInt()}%"),
                _buildAssistantMetricRow(
                    "Reactivity", pmb['reactivity'] ?? '-'),
                if (fcodes.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const Text("ACTIVE F-CODES",
                      style: TextStyle(
                          color: Color(0xFF8B7355),
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1)),
                  const SizedBox(height: 4),
                  ...fcodes.map((fc) => Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: Text("${fc['code']}: ${fc['description']}",
                            style: const TextStyle(
                                color: Colors.white70, fontSize: 11)),
                      )),
                ],
                if (legacy.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const Text("LEGACY PATTERNS",
                      style: TextStyle(
                          color: Color(0xFF8B7355),
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1)),
                  const SizedBox(height: 4),
                  ...legacy.map((lp) => Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: Row(children: [
                          Icon(
                              lp['reflected'] == true
                                  ? Icons.link
                                  : Icons.link_off,
                              color: lp['reflected'] == true
                                  ? const Color(0xFF4ECDC4)
                                  : Colors.grey,
                              size: 12),
                          const SizedBox(width: 4),
                          Expanded(
                              child: Text("${lp['source']}: ${lp['pattern']}",
                                  style: const TextStyle(
                                      color: Colors.white70, fontSize: 11))),
                        ]),
                      )),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildAssistantMetricRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(label, style: const TextStyle(color: Colors.grey, fontSize: 11)),
        Text(value,
            style: const TextStyle(
                color: Colors.white,
                fontSize: 11,
                fontWeight: FontWeight.bold)),
      ]),
    );
  }

  // Dojo embed URL locked once per dashboard session (token via postMessage on web).
  String? _cachedDojoUrl;

  String? _dojoLastPushedAuthToken;

  void _pushDojoIframeAuthIfNeeded() {
    if (!kIsWeb) return;
    final token = (_authToken ?? '').trim();
    if (token.isEmpty || token == _dojoLastPushedAuthToken) return;
    _dojoLastPushedAuthToken = token;
    notifyDojoIframeAuth(
      token: token,
      hw: (_coachHardwareId ?? '').trim(),
      ws: _serverUrl,
    );
  }

  Widget _buildDojoTab() {
    // =========================================================================
    // HYBRID DOJO - Night School Dojo page
    // - Mobile: Embedded WebView showing night_school_dojo.html
    // - Web: Embedded iframe (URL cached once to prevent reload flicker)
    // =========================================================================

    final tokenNow = (_authToken ?? '').trim();

    // Lock embed URL once (hw/ws only on web — token via postMessage).
    if (_cachedDojoUrl == null && tokenNow.isNotEmpty) {
      if (kIsWeb) {
        final params = Uri(queryParameters: {
          'embed': 'coach',
          'hw': (_coachHardwareId ?? '').trim(),
          'ws': _serverUrl,
        }).query;
        _cachedDojoUrl = '/night_school_dojo.html?$params';
      } else {
        final baseUrl = _apiBaseUrl
            .replaceAll(RegExp(r'/api/?$'), '')
            .replaceAll(RegExp(r'/+$'), '')
            .replaceFirst(
                'api.sovereignsanctuary.net', 'app.sovereignsanctuary.net');
        _cachedDojoUrl = Uri.parse('$baseUrl/night_school_dojo.html')
            .replace(queryParameters: {
          'token': tokenNow,
          'hw': (_coachHardwareId ?? '').trim(),
          'ws': _serverUrl,
        }).toString();
        _dojoWebViewController = WebViewController()
          ..setJavaScriptMode(JavaScriptMode.unrestricted)
          ..setBackgroundColor(const Color(0xFF050505))
          ..setNavigationDelegate(
            NavigationDelegate(
              onPageStarted: (String url) {
                _debugLog('>>> Dojo WebView loading: $url');
              },
              onPageFinished: (String url) {
                _debugLog('>>> Dojo WebView loaded: $url');
              },
              onWebResourceError: (WebResourceError error) {
                _debugLog('>>> Dojo WebView error: ${error.description}');
              },
            ),
          )
          ..loadRequest(Uri.parse(_cachedDojoUrl!));
      }
    }
    final dojoUrl = _cachedDojoUrl;

    // -------------------------------------------------------------------------
    // WEB PLATFORM: Embed Dojo page inline as iframe
    // -------------------------------------------------------------------------
    if (kIsWeb) {
      if (tokenNow.isEmpty) {
        return const Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.fitness_center, size: 80, color: Color(0xFF9D4EDD)),
              SizedBox(height: 24),
              Text('THE DOJO',
                  style: TextStyle(
                      color: Color(0xFF9D4EDD),
                      fontSize: 28,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 2)),
              SizedBox(height: 16),
              Text('Waiting for login…',
                  style: TextStyle(color: Colors.grey, fontSize: 14)),
            ],
          ),
        );
      }
      if (dojoUrl == null) {
        return const Center(child: CircularProgressIndicator());
      }
      return buildDojoIframe(dojoUrl);
    }

    // -------------------------------------------------------------------------
    // MOBILE PLATFORM: Embed WebView directly (URL locked once per session)
    // -------------------------------------------------------------------------
    if (_dojoWebViewController != null) {
      return WebViewWidget(controller: _dojoWebViewController!);
    }
    return const Center(child: CircularProgressIndicator());
  }

  void _launchDojo(String url) {
    // Web: uses dart:html window.open via conditional import (`launchDojoUrl`)
    // Mobile: this button is not shown (mobile embeds WebView instead)
    try {
      launchDojoUrl(url);
    } catch (e) {
      _debugLog('>>> Dojo launch error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Open manually: $url'),
            duration: const Duration(seconds: 6),
          ),
        );
      }
    }
  }

  // Native Flutter Dojo tab (fallback for web platform where WebView is not supported)
  Widget _buildDojoTabNative() {
    return Column(
      children: [
        // Persona Selection & Controls
        Container(
          padding: const EdgeInsets.all(16),
          decoration: const BoxDecoration(
            color: Color(0xFF111111),
            border: Border(bottom: BorderSide(color: Color(0xFF222222))),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                "DOJO TRAINING",
                style: TextStyle(
                  color: Color(0xFFFFD700),
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.2,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                _dojoSessionId != null
                    ? "Training with ${_dojoActivePersona ?? 'Little Nate'}"
                    : "Select persona types to train with",
                style: const TextStyle(color: Colors.white60, fontSize: 12),
              ),
              const SizedBox(height: 16),

              // Persona toggles
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _buildPersonaChip('HOSTILE'),
                  _buildPersonaChip('CRISIS'),
                  _buildPersonaChip('SKEPTICAL'),
                  _buildPersonaChip('MINOR'),
                  _buildPersonaChip('MANIPULATION'),
                ],
              ),

              const SizedBox(height: 16),

              // Control buttons
              Row(
                children: [
                  if (_dojoSessionId == null) ...[
                    ElevatedButton.icon(
                      onPressed: _dojoBusy ? null : _startDojoSession,
                      icon: const Icon(Icons.play_arrow, size: 18),
                      label: Text(_dojoBusy ? "Starting..." : "Start Session"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF4ECDC4),
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(
                            horizontal: 20, vertical: 12),
                      ),
                    ),
                  ] else ...[
                    ElevatedButton.icon(
                      onPressed: _dojoBusy
                          ? null
                          : () => _endDojoSession(clearPrompt: true),
                      icon: const Icon(Icons.stop, size: 18),
                      label: const Text("End Session"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFEF4444),
                        foregroundColor: Colors.white,
                        padding: const EdgeInsets.symmetric(
                            horizontal: 20, vertical: 12),
                      ),
                    ),
                    const SizedBox(width: 10),
                    if (_dojoPersonaQueue.length > 1)
                      ElevatedButton.icon(
                        onPressed: _dojoBusy ? null : _nextDojoPersona,
                        icon: const Icon(Icons.skip_next, size: 18),
                        label: Text(
                            "Next (${_dojoPersonaIndex + 1}/${_dojoPersonaQueue.length})"),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF9D4EDD),
                          foregroundColor: Colors.white,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 16, vertical: 12),
                        ),
                      ),
                    const SizedBox(width: 10),
                    ElevatedButton.icon(
                      onPressed: () {
                        setState(() {
                          _dojoLog.clear();
                          _dojoLastAnalysis = null;
                        });
                      },
                      icon: const Icon(Icons.clear_all, size: 18),
                      label: const Text("Clear Log"),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.white12,
                        foregroundColor: Colors.white70,
                        padding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 12),
                      ),
                    ),
                  ],
                ],
              ),

              // Error display
              if (_dojoError != null) ...[
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFEF4444).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: const Color(0xFFEF4444)),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline,
                          color: Color(0xFFEF4444), size: 20),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _dojoError!,
                          style: const TextStyle(
                              color: Color(0xFFEF4444), fontSize: 12),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close, size: 18),
                        color: const Color(0xFFEF4444),
                        onPressed: () => setState(() => _dojoError = null),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),

        // Session log
        Expanded(
          child: _dojoLog.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.sports_martial_arts,
                        color: Colors.white24,
                        size: 64,
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        "No active session",
                        style: TextStyle(color: Colors.white38, fontSize: 16),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        "Select personas and click Start Session",
                        style: TextStyle(color: Colors.white24, fontSize: 12),
                      ),
                    ],
                  ),
                )
              : ListView.builder(
                  controller: _dojoScrollController,
                  padding: const EdgeInsets.all(16),
                  itemCount: _dojoLog.length,
                  itemBuilder: (context, i) => _buildDojoLogItem(_dojoLog[i]),
                ),
        ),

        // Response input area (only show when there's an active prompt)
        if (_dojoSessionId != null && _dojoAdversarialPrompt != null)
          Container(
            padding: const EdgeInsets.all(16),
            decoration: const BoxDecoration(
              color: Color(0xFF111111),
              border: Border(top: BorderSide(color: Color(0xFF222222))),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _dojoResponseController,
                    style: const TextStyle(color: Colors.white),
                    maxLines: 3,
                    decoration: InputDecoration(
                      hintText:
                          "Your response to the ${_dojoActivePersona?.toLowerCase()} client...",
                      hintStyle: const TextStyle(color: Colors.grey),
                      filled: true,
                      fillColor: Colors.white.withOpacity(0.05),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide.none,
                      ),
                      contentPadding: const EdgeInsets.all(12),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                FloatingActionButton(
                  onPressed: _dojoBusy ? null : _sendDojoTest,
                  backgroundColor: const Color(0xFF4ECDC4),
                  child: _dojoBusy
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            valueColor:
                                AlwaysStoppedAnimation<Color>(Colors.black),
                          ),
                        )
                      : const Icon(Icons.send, color: Colors.black),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildPersonaChip(String persona) {
    final isSelected = _dojoSelectedPersonas.contains(persona);
    final color = _getPersonaColor(persona);

    return FilterChip(
      label: Text(persona),
      selected: isSelected,
      onSelected: _dojoSessionId == null
          ? (selected) {
              setState(() {
                if (selected) {
                  _dojoSelectedPersonas.add(persona);
                } else {
                  _dojoSelectedPersonas.remove(persona);
                }
                _refreshDojoQueue();
              });
            }
          : null,
      selectedColor: color.withOpacity(0.3),
      checkmarkColor: color,
      backgroundColor: Colors.white12,
      labelStyle: TextStyle(
        color: isSelected ? color : Colors.white60,
        fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
        fontSize: 12,
      ),
      side: BorderSide(color: isSelected ? color : Colors.white24),
      showCheckmark: true,
    );
  }

  Color _getPersonaColor(String persona) {
    switch (persona) {
      case 'HOSTILE':
        return const Color(0xFFEF4444);
      case 'CRISIS':
        return const Color(0xFFFF6B6B);
      case 'SKEPTICAL':
        return const Color(0xFFFFA500);
      case 'MINOR':
        return const Color(0xFF9D4EDD);
      case 'MANIPULATION':
        return const Color(0xFFDC2626);
      default:
        return Colors.grey;
    }
  }

  Widget _buildDojoLogItem(Map<String, dynamic> item) {
    final type = item['type'] ?? '';

    if (type == 'prompt') {
      final persona = item['persona'] ?? '';
      final text = item['text'] ?? '';
      final color = _getPersonaColor(persona);

      return Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: color.withOpacity(0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: color.withOpacity(0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.person, color: color, size: 18),
                const SizedBox(width: 8),
                Text(
                  "$persona CLIENT",
                  style: TextStyle(
                    color: color,
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              text,
              style: const TextStyle(color: Colors.white, fontSize: 14),
            ),
          ],
        ),
      );
    } else if (type == 'response') {
      final text = item['text'] ?? '';

      return Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF4ECDC4).withOpacity(0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.record_voice_over,
                    color: Color(0xFF4ECDC4), size: 18),
                const SizedBox(width: 8),
                const Text(
                  "YOUR RESPONSE",
                  style: TextStyle(
                    color: Color(0xFF4ECDC4),
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              text,
              style: const TextStyle(color: Colors.white, fontSize: 14),
            ),
          ],
        ),
      );
    } else if (type == 'analysis') {
      final data = item['data'] as Map<String, dynamic>?;
      if (data == null) return const SizedBox.shrink();

      final score = data['score'] ?? 0.0;
      final feedback = data['feedback'] ?? '';
      final strengths = List<String>.from(data['strengths'] ?? []);
      final improvements = List<String>.from(data['improvements'] ?? []);

      return Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFFFFD700).withOpacity(0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.analytics, color: Color(0xFFFFD700), size: 18),
                const SizedBox(width: 8),
                const Text(
                  "ANALYSIS",
                  style: TextStyle(
                    color: Color(0xFFFFD700),
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                    letterSpacing: 0.5,
                  ),
                ),
                const Spacer(),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  decoration: BoxDecoration(
                    color: _getScoreColor(score).withOpacity(0.2),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: _getScoreColor(score)),
                  ),
                  child: Text(
                    "Score: ${(score * 100).toStringAsFixed(0)}%",
                    style: TextStyle(
                      color: _getScoreColor(score),
                      fontWeight: FontWeight.bold,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
            if (feedback.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                feedback,
                style: const TextStyle(color: Colors.white, fontSize: 14),
              ),
            ],
            if (strengths.isNotEmpty) ...[
              const SizedBox(height: 12),
              const Text(
                "Strengths:",
                style: TextStyle(
                  color: Color(0xFF4ECDC4),
                  fontWeight: FontWeight.bold,
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: 4),
              ...strengths.map((s) => Padding(
                    padding: const EdgeInsets.only(left: 8, top: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text("• ",
                            style: TextStyle(color: Color(0xFF4ECDC4))),
                        Expanded(
                          child: Text(
                            s,
                            style: const TextStyle(
                                color: Colors.white70, fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  )),
            ],
            if (improvements.isNotEmpty) ...[
              const SizedBox(height: 12),
              const Text(
                "Improvements:",
                style: TextStyle(
                  color: Color(0xFFFFA500),
                  fontWeight: FontWeight.bold,
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: 4),
              ...improvements.map((i) => Padding(
                    padding: const EdgeInsets.only(left: 8, top: 4),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text("• ",
                            style: TextStyle(color: Color(0xFFFFA500))),
                        Expanded(
                          child: Text(
                            i,
                            style: const TextStyle(
                                color: Colors.white70, fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  )),
            ],
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed:
                        _dojoBusy ? null : () => _shareDojoLearning(data),
                    icon: const Icon(Icons.school, size: 18),
                    label: const Text("Send to Nate (approval)"),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFF4ECDC4),
                      side: const BorderSide(color: Color(0xFF4ECDC4)),
                      padding: const EdgeInsets.symmetric(vertical: 12),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      );
    }

    return const SizedBox.shrink();
  }

  Color _getScoreColor(double score) {
    if (score >= 0.8) return const Color(0xFF4ECDC4);
    if (score >= 0.6) return const Color(0xFFFFD700);
    if (score >= 0.4) return const Color(0xFFFFA500);
    return const Color(0xFFEF4444);
  }

  // ===========================================================================
  // CLASSROOM TAB - Session analysis for coach development
  // ===========================================================================

  Widget _buildClassroomTab() {
    return RefreshIndicator(
      onRefresh: () async {
        _requestClassroomSessions();
        _requestClassroomProgress();
      },
      child: SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            _buildClassroomHeader(),
            const SizedBox(height: 20),

            // Progress Summary (if available)
            if (_classroomProgress != null) ...[
              _buildClassroomProgressCard(),
              const SizedBox(height: 20),
            ],

            // Session Selector
            _buildSessionSelector(),
            const SizedBox(height: 16),

            // Analysis Options (when session selected)
            if (_classroomSelectedSessionId != null) ...[
              _buildAnalysisOptions(),
              const SizedBox(height: 16),
            ],

            // Analysis Results
            if (_classroomAnalyzing) ...[
              _buildAnalyzingState(),
            ] else if (_classroomAnalysis != null) ...[
              _buildAnalysisResults(),
            ],

            // Recent History
            if (_classroomHistory.isNotEmpty && _classroomAnalysis == null) ...[
              const SizedBox(height: 24),
              _buildClassroomHistorySection(),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildClassroomHeader() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            const Color(0xFF9D4EDD).withOpacity(0.2),
            const Color(0xFF4ECDC4).withOpacity(0.1),
          ],
        ),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF9D4EDD).withOpacity(0.2),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Icon(Icons.school, color: Color(0xFF9D4EDD), size: 28),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  "THE CLASSROOM",
                  style: TextStyle(
                    color: Color(0xFF9D4EDD),
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  "Session Analysis & Professional Development",
                  style: TextStyle(color: Colors.grey[400], fontSize: 12),
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Color(0xFF4ECDC4)),
            onPressed: () {
              _requestClassroomSessions();
              _requestClassroomProgress();
            },
            tooltip: "Refresh",
          ),
        ],
      ),
    );
  }

  Widget _buildClassroomProgressCard() {
    final progress = _classroomProgress!;
    final totalSessions = (progress['total_sessions_reviewed'] ?? 0) as int;
    final avgScore = (progress['average_presence_score'] ?? 0.0) as double;
    final completed = (progress['assignments_completed'] ?? 0) as int;
    final pending = (progress['assignments_pending'] ?? 0) as int;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "Your Progress",
            style: TextStyle(
                color: Colors.white70,
                fontSize: 14,
                fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _buildProgressStat("Sessions", totalSessions.toString(),
                  const Color(0xFF9D4EDD)),
              _buildProgressStat(
                  "Avg Score",
                  "${avgScore.toStringAsFixed(1)}/10",
                  _getScoreColor(avgScore / 10)),
              _buildProgressStat(
                  "Completed", completed.toString(), const Color(0xFF4ECDC4)),
              _buildProgressStat("Pending", pending.toString(),
                  pending > 0 ? const Color(0xFFFFD700) : Colors.grey),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildProgressStat(String label, String value, Color color) {
    return Expanded(
      child: Column(
        children: [
          Text(
            value,
            style: TextStyle(
                color: color, fontSize: 20, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: TextStyle(color: Colors.grey[500], fontSize: 11),
          ),
        ],
      ),
    );
  }

  Widget _buildSessionSelector() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0F),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "Select Session to Analyze",
            style: TextStyle(
                color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 12),
          if (_classroomSessions.isEmpty) ...[
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                children: [
                  Icon(Icons.video_library_outlined,
                      color: Colors.grey[600], size: 40),
                  const SizedBox(height: 12),
                  Text(
                    "No sessions with transcripts available",
                    style: TextStyle(color: Colors.grey[500], fontSize: 13),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    "Archive Zoom transcripts from the Schedule tab to analyze them here",
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.grey[600], fontSize: 11),
                  ),
                ],
              ),
            ),
          ] else ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.white10),
              ),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _classroomSelectedSessionId,
                  hint: const Text("Choose a session...",
                      style: TextStyle(color: Colors.grey)),
                  isExpanded: true,
                  dropdownColor: const Color(0xFF111111),
                  items: _classroomSessions.map((session) {
                    final id = (session['session_id'] ?? session['id'] ?? '')
                        .toString();
                    final clientName = (session['client_name'] ??
                            session['client'] ??
                            'Unknown Client')
                        .toString();
                    final date =
                        (session['scheduled_time'] ?? session['date'] ?? '')
                            .toString();
                    final hasAnalysis = session['has_analysis'] == true;
                    final pending = session['analysis_pending'] == true;
                    final isUpload =
                        (session['type'] ?? '').toString() == 'uploaded_video';
                    final prefix = isUpload ? '[Upload] ' : '';
                    return DropdownMenuItem<String>(
                      value: id,
                      child: Row(
                        children: [
                          Icon(
                            pending
                                ? Icons.hourglass_top
                                : (hasAnalysis
                                    ? Icons.check_circle
                                    : Icons.videocam),
                            color: pending
                                ? const Color(0xFFFFD700)
                                : (hasAnalysis
                                    ? const Color(0xFF4ECDC4)
                                    : Colors.grey),
                            size: 18,
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              "$prefix$clientName — $date",
                              style: const TextStyle(color: Colors.white),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ),
                    );
                  }).toList(),
                  onChanged: (value) {
                    setState(() {
                      _classroomSelectedSessionId = value;
                      _classroomAnalysis = null;
                      _classroomRecordingStatus = null;
                      _classroomMeetingStatus = null;
                      _classroomLiveAnalysis = null;
                    });
                    if (value != null) {
                      _loadSessionAnalysis(value);
                      _checkRecordingAvailability();
                    }
                  },
                ),
              ),
            ),
          ],

          // Video upload section
          const SizedBox(height: 16),
          Row(
            children: [
              const Expanded(child: Divider(color: Colors.white24)),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Text('OR',
                    style: TextStyle(
                        color: Colors.grey[500],
                        fontSize: 11,
                        fontWeight: FontWeight.w600)),
              ),
              const Expanded(child: Divider(color: Colors.white24)),
            ],
          ),
          const SizedBox(height: 12),
          ElevatedButton.icon(
            icon: _classroomUploading
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.black))
                : const Icon(Icons.upload_file, size: 18),
            label: Text(
              _classroomUploadedVideoName != null
                  ? _classroomUploadedVideoName!
                  : 'Upload Video from Device',
              style: const TextStyle(fontSize: 12),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFC9A962),
              foregroundColor: Colors.black,
              minimumSize: const Size(double.infinity, 44),
            ),
            onPressed: _classroomUploading ? null : _pickAndUploadVideo,
          ),
          if (_classroomUploading)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: LinearProgressIndicator(
                value: _classroomUploadProgress,
                backgroundColor: Colors.white10,
                valueColor:
                    const AlwaysStoppedAnimation<Color>(Color(0xFFC9A962)),
              ),
            ),
          if (_classroomUploadedVideoId != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(
                children: [
                  const Icon(Icons.check_circle,
                      color: Color(0xFF4ECDC4), size: 16),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      'Video uploaded: ${_classroomUploadedVideoId}',
                      style: const TextStyle(
                          color: Color(0xFF4ECDC4), fontSize: 11),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _pickAndUploadVideo() async {
    // Direct browser → Cloudflare R2 multipart upload. Bytes never travel
    // through our origin or the Cloudflare proxy, so we can ship videos
    // up to 5 GiB (the API hard-caps at MAX_DIRECT_VIDEO_SIZE). On web the
    // file is sliced via Blob.slice and read 8 MiB at a time, so we do
    // NOT load the whole file into the JS heap (no more ArrayBuffer crash).
    const int maxUploadBytes = 5 * 1024 * 1024 * 1024; // 5 GiB

    PickedLargeVideo? picked;
    try {
      try {
        picked = await pickLargeVideo();
      } catch (pickErr) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('Could not open file picker: $pickErr'),
              backgroundColor: Colors.red,
              duration: const Duration(seconds: 6),
            ),
          );
        }
        return;
      }
      if (picked == null) return; // user cancelled

      final fileSize = picked.size;
      if (fileSize <= 0) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Selected file is empty')),
          );
        }
        return;
      }
      if (fileSize > maxUploadBytes) {
        if (mounted) {
          final gb = (fileSize / (1024 * 1024 * 1024)).toStringAsFixed(2);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'Video is ${gb} GiB. Maximum upload is 5 GiB. '
                'Please trim the recording, or let Zoom auto-import the cloud recording.',
              ),
              backgroundColor: Colors.red,
              duration: const Duration(seconds: 6),
            ),
          );
        }
        return;
      }

      setState(() {
        _classroomUploading = true;
        _classroomUploadProgress = 0.0;
        _classroomUploadedVideoName = picked!.name;
      });

      final tok =
          (_authToken ?? widget.currentUserProfile?['token']?.toString() ?? '')
              .trim();
      final coachId =
          (widget.currentUserProfile?['hardware_id'] ?? '').toString();
      final clientId =
          _clients.isNotEmpty ? (_clients.first['id'] ?? '').toString() : '';

      final result = await uploadLargeVideoDirectToR2(
        file: picked,
        apiBaseUrl: _apiBaseUrl,
        bearerToken: tok,
        coachId: coachId,
        clientId: clientId,
        onProgress: (p) {
          if (!mounted) return;
          setState(() => _classroomUploadProgress = p);
        },
      );

      // uploadLargeVideoDirectToR2 disposed the picker handle in its
      // finally block; clear our local reference to avoid double-dispose.
      picked = null;

      setState(() {
        _classroomUploading = false;
        _classroomUploadProgress = 1.0;
        _classroomUploadedVideoId = result.videoId;
      });
      // Refresh the Select Session to Analyze dropdown immediately so the
      // newly-uploaded video shows up without the user having to hit refresh.
      // The bridge merges classroom_sessions.json on every classroom_get_sessions
      // and special-cases uploaded_video records to bypass the transcript
      // requirement, so the in-progress / just-completed upload appears.
      _requestClassroomSessions();
      _startClassroomVideoAnalysisPoll(result.videoId);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Upload complete. Running Classroom analysis…'),
            backgroundColor: Color(0xFF4ECDC4),
            duration: Duration(seconds: 3),
          ),
        );
      }
    } catch (e) {
      setState(() {
        _classroomUploading = false;
        _classroomUploadProgress = 0.0;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Upload failed: $e'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 8),
          ),
        );
      }
    } finally {
      try {
        picked?.dispose();
      } catch (_) {}
    }
  }

  Widget _buildAnalysisOptions() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "Analysis Options",
            style: TextStyle(
                color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 16),

          // Learning Focus
          const Text("Learning Focus",
              style: TextStyle(color: Colors.grey, fontSize: 12)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _buildFocusChip("general therapeutic skills", "General"),
              _buildFocusChip("therapeutic presence & attunement", "Presence"),
              _buildFocusChip("questioning techniques", "Questions"),
              _buildFocusChip("handling resistance", "Resistance"),
              _buildFocusChip("emotional validation", "Validation"),
              _buildFocusChip("session pacing & structure", "Pacing"),
            ],
          ),
          const SizedBox(height: 16),

          // Custom Focus
          TextField(
            controller: _classroomLearningFocusController,
            style: const TextStyle(color: Colors.white),
            decoration: InputDecoration(
              hintText: "Or enter custom focus area...",
              hintStyle: TextStyle(color: Colors.grey[600]),
              filled: true,
              fillColor: const Color(0xFF0A0A0F),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide.none,
              ),
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
            ),
            onChanged: (value) {
              if (value.isNotEmpty) {
                setState(() => _classroomFocusArea = value);
              }
            },
          ),
          const SizedBox(height: 16),

          // Coach Query - specific observations for Little Nate
          const Text("Ask Little Nate Specific Observations",
              style: TextStyle(color: Colors.grey, fontSize: 12)),
          const SizedBox(height: 8),
          TextField(
            controller: _classroomCoachQueryController,
            style: const TextStyle(color: Colors.white, fontSize: 13),
            maxLines: 3,
            decoration: InputDecoration(
              hintText:
                  "e.g., 'What attachment patterns do you see?' or 'How does the client respond to emotional bids?'",
              hintStyle: TextStyle(color: Colors.grey[700], fontSize: 12),
              filled: true,
              fillColor: const Color(0xFF0A0A0F),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide.none,
              ),
              contentPadding: const EdgeInsets.all(12),
            ),
          ),
          const SizedBox(height: 16),

          // Due Date
          Row(
            children: [
              const Text("Assignment Due Date (optional):",
                  style: TextStyle(color: Colors.grey, fontSize: 12)),
              const Spacer(),
              TextButton.icon(
                onPressed: () async {
                  final date = await showDatePicker(
                    context: context,
                    initialDate: DateTime.now().add(const Duration(days: 7)),
                    firstDate: DateTime.now(),
                    lastDate: DateTime.now().add(const Duration(days: 90)),
                  );
                  if (date != null) {
                    setState(() => _classroomDueDate = date);
                  }
                },
                icon: const Icon(Icons.calendar_today, size: 16),
                label: Text(
                  _classroomDueDate != null
                      ? "${_classroomDueDate!.month}/${_classroomDueDate!.day}/${_classroomDueDate!.year}"
                      : "Set Date",
                  style: const TextStyle(fontSize: 12),
                ),
                style: TextButton.styleFrom(
                    foregroundColor: const Color(0xFFFFD700)),
              ),
            ],
          ),
          const SizedBox(height: 16),

          // Recording Status Indicator
          if (_classroomRecordingStatus != null ||
              _classroomCheckingRecording) ...[
            _buildRecordingStatusIndicator(),
            const SizedBox(height: 12),
          ],

          // Action Buttons Row
          Row(
            children: [
              // Analyze Archived Button
              Expanded(
                child: ElevatedButton.icon(
                  onPressed:
                      _classroomAnalyzing ? null : _analyzeSelectedSession,
                  icon: _classroomAnalyzing
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.black))
                      : const Icon(Icons.psychology, size: 20),
                  label: Text(_classroomAnalyzing
                      ? "Analyzing..."
                      : "Analyze Archived"),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF9D4EDD),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10)),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              // Live Analysis Button
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: (_classroomLiveAnalyzing || !_canAnalyzeLive)
                      ? null
                      : _analyzeLiveSession,
                  icon: _classroomLiveAnalyzing
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: Colors.black))
                      : Icon(
                          _isSessionLive
                              ? Icons.videocam
                              : Icons.cloud_download,
                          size: 20,
                        ),
                  label: Text(
                    _classroomLiveAnalyzing
                        ? "Analyzing..."
                        : (_isSessionLive
                            ? "Live Analysis"
                            : "Cloud Recording"),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _canAnalyzeLive
                        ? (_isSessionLive
                            ? const Color(0xFFEF4444)
                            : const Color(0xFF4ECDC4))
                        : Colors.grey[700],
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10)),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildRecordingStatusIndicator() {
    if (_classroomCheckingRecording) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: Colors.grey[800],
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(
                    strokeWidth: 2, color: Colors.white)),
            SizedBox(width: 8),
            Text("Checking recording...",
                style: TextStyle(color: Colors.white70, fontSize: 12)),
          ],
        ),
      );
    }

    final recording = _classroomRecordingStatus;
    if (recording == null) return const SizedBox.shrink();

    final available = recording['available'] == true;
    final status = recording['status'] as String?;
    final daysRemaining = (recording['days_remaining'] ?? 0) as int;

    IconData icon;
    Color color;
    String text;

    if (!available) {
      icon = Icons.videocam_off;
      color = Colors.grey;
      text = "No recording available";
    } else if (status == 'recording') {
      icon = Icons.fiber_manual_record;
      color = const Color(0xFFEF4444);
      text = "LIVE - Recording in progress";
    } else if (status == 'processing') {
      icon = Icons.hourglass_bottom;
      color = Colors.orange;
      text = "Recording processing...";
    } else {
      icon = Icons.cloud_done;
      color = const Color(0xFF4ECDC4);
      text = "Cloud recording • $daysRemaining days remaining";
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                  color: color, fontSize: 12, fontWeight: FontWeight.w500),
            ),
          ),
          if (available && status == 'recording') ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(4),
              ),
              child: const Text(
                "LIVE",
                style: TextStyle(
                    color: Colors.white,
                    fontSize: 10,
                    fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildFocusChip(String value, String label) {
    final isSelected = _classroomFocusArea == value;
    return FilterChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (selected) {
        setState(() {
          _classroomFocusArea = value;
          _classroomLearningFocusController.clear();
        });
      },
      selectedColor: const Color(0xFF9D4EDD).withOpacity(0.3),
      checkmarkColor: const Color(0xFF9D4EDD),
      backgroundColor: const Color(0xFF0A0A0F),
      labelStyle: TextStyle(
        color: isSelected ? const Color(0xFF9D4EDD) : Colors.grey,
        fontSize: 12,
      ),
      side: BorderSide(
        color: isSelected ? const Color(0xFF9D4EDD) : Colors.white10,
      ),
    );
  }

  Widget _buildAnalyzingState() {
    final fromServer = _classroomServerPipelineLabel?.trim();
    final fromUi =
        _classroomVideoPipelineActive && _classroomVideoStages.isNotEmpty
            ? _classroomVideoStages[_classroomVideoStageIndex.clamp(
                0, _classroomVideoStages.length - 1)]
            : null;
    final stage =
        (fromServer != null && fromServer.isNotEmpty) ? fromServer : fromUi;
    return Container(
      padding: const EdgeInsets.all(40),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
      ),
      child: Column(
        children: [
          const CircularProgressIndicator(color: Color(0xFF9D4EDD)),
          const SizedBox(height: 20),
          Text(
            stage ?? "Little Nate is reviewing your session...",
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white, fontSize: 16),
          ),
          const SizedBox(height: 8),
          Text(
            stage != null
                ? "You can leave this tab open; results appear when processing finishes."
                : "Analyzing therapeutic techniques, talk-time ratios, and generating personalized feedback",
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.grey[500], fontSize: 12),
          ),
          if (_classroomServerPipelineIndex != null) ...[
            const SizedBox(height: 6),
            Text(
              "Stage ${(_classroomServerPipelineIndex! + 1)}/5",
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey[600], fontSize: 11),
            ),
          ],
          if (_classroomVideoPipelineActive) ...[
            const SizedBox(height: 20),
            ..._classroomVideoStages.asMap().entries.map((e) {
              final i = e.key;
              final label = e.value;
              final active = i == _classroomVideoStageIndex;
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    Icon(
                      active
                          ? Icons.radio_button_checked
                          : Icons.radio_button_off,
                      size: 16,
                      color:
                          active ? const Color(0xFF9D4EDD) : Colors.grey[700]!,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        label,
                        style: TextStyle(
                          color: active ? Colors.white : Colors.grey[600],
                          fontSize: 12,
                          fontWeight:
                              active ? FontWeight.w600 : FontWeight.normal,
                        ),
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ],
      ),
    );
  }

  Widget _buildAnalysisResults() {
    final analysis = _classroomAnalysis!;
    final metrics = (analysis['metrics'] is Map)
        ? Map<String, dynamic>.from(analysis['metrics'] as Map)
        : <String, dynamic>{};
    final strengths = List<String>.from(analysis['strengths'] ?? []);
    final growthAreas = List<String>.from(analysis['growth_areas'] ?? []);
    final keyMoments = List<Map<String, dynamic>>.from(
        (analysis['key_moments'] ?? [])
            .map((e) => Map<String, dynamic>.from(e as Map)));
    final presenceScore = (analysis['therapeutic_presence_score'] is num)
        ? (analysis['therapeutic_presence_score'] as num).toDouble()
        : 0.0;
    final transcriptSummary =
        (analysis['transcript_summary'] ?? '').toString().trim();
    final visualObs =
        (analysis['visual_observations_summary'] ?? '').toString().trim();
    final facialSummary = (analysis['facial_summary'] is Map)
        ? Map<String, dynamic>.from(analysis['facial_summary'] as Map)
        : <String, dynamic>{};
    final emotionalTimeline = (analysis['emotional_timeline'] is List)
        ? List<dynamic>.from(analysis['emotional_timeline'] as List)
        : <dynamic>[];
    final voiceSeriesRaw = analysis['voice_stress_timeline'] ??
        analysis['voice_metrics_timeline'] ??
        analysis['stress_over_time'];
    final crystalRaw = analysis['crystal_entries'] ??
        analysis['crystal_memory'] ??
        analysis['crystals_created'];
    final focusFeedback =
        (analysis['focus_specific_feedback'] ?? '').toString();
    final reflectionQuestions =
        List<String>.from(analysis['reflection_questions'] ?? []);
    final dojoScenarios = List<Map<String, dynamic>>.from(
        (analysis['dojo_scenarios'] ?? [])
            .map((e) => Map<String, dynamic>.from(e as Map)));
    final workbookRecs =
        List<String>.from(analysis['workbook_recommendations'] ?? []);
    final reflectionSubmitted = analysis['reflection_submitted_at'] != null;
    final multimodalFusion = (analysis['multimodal_fusion'] is Map)
        ? Map<String, dynamic>.from(analysis['multimodal_fusion'] as Map)
        : <String, dynamic>{};
    final clinicalFlags = (analysis['clinical_flags'] is List)
        ? List<dynamic>.from(analysis['clinical_flags'] as List)
        : (multimodalFusion['clinical_flags'] is List
            ? List<dynamic>.from(multimodalFusion['clinical_flags'] as List)
            : <dynamic>[]);
    final sessionArc = (analysis['session_arc'] is Map)
        ? Map<String, dynamic>.from(analysis['session_arc'] as Map)
        : (multimodalFusion['session_arc'] is Map
            ? Map<String, dynamic>.from(multimodalFusion['session_arc'] as Map)
            : <String, dynamic>{});
    final longitudinalPatterns = (analysis['longitudinal_patterns'] is Map)
        ? Map<String, dynamic>.from(analysis['longitudinal_patterns'] as Map)
        : <String, dynamic>{};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Back button
        TextButton.icon(
          onPressed: () {
            setState(() {
              _classroomAnalysis = null;
              _classroomSelectedSessionId = null;
            });
          },
          icon: const Icon(Icons.arrow_back, size: 18),
          label: const Text("Back to Session List"),
          style: TextButton.styleFrom(foregroundColor: Colors.grey),
        ),
        const SizedBox(height: 12),

        // Therapeutic Presence Score
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              colors: [
                _getScoreColor(presenceScore / 10).withOpacity(0.2),
                Colors.transparent,
              ],
            ),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
                color: _getScoreColor(presenceScore / 10).withOpacity(0.5)),
          ),
          child: Row(
            children: [
              Column(
                children: [
                  Text(
                    presenceScore.toStringAsFixed(1),
                    style: TextStyle(
                      color: _getScoreColor(presenceScore / 10),
                      fontSize: 48,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  Text("/10",
                      style: TextStyle(color: Colors.grey[500], fontSize: 16)),
                ],
              ),
              const SizedBox(width: 20),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      "Therapeutic Presence",
                      style: TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      presenceScore >= 9
                          ? "Exceptional session!"
                          : presenceScore >= 7
                              ? "Strong therapeutic presence"
                              : presenceScore >= 5
                                  ? "Good foundation, room for growth"
                                  : "Focus on fundamentals",
                      style: TextStyle(color: Colors.grey[400], fontSize: 12),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        // Session Metrics
        Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF111111),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text("Session Metrics",
                  style: TextStyle(
                      color: Colors.white70,
                      fontSize: 14,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              Row(
                children: [
                  _buildMetricItem(
                      "Duration",
                      "${(metrics['total_duration_minutes'] ?? 0).toStringAsFixed(0)} min",
                      Icons.timer),
                  _buildMetricItem(
                      "Coach Talk",
                      "${(metrics['coach_talk_time_percent'] ?? 0).toStringAsFixed(0)}%",
                      Icons.mic),
                  _buildMetricItem(
                      "Client Talk",
                      "${(metrics['client_talk_time_percent'] ?? 0).toStringAsFixed(0)}%",
                      Icons.person),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  _buildMetricItem("Open Q's",
                      "${metrics['open_questions'] ?? 0}", Icons.help_outline),
                  _buildMetricItem(
                      "Closed Q's",
                      "${metrics['closed_questions'] ?? 0}",
                      Icons.check_circle_outline),
                  _buildMetricItem(
                      "Reflections",
                      "${metrics['reflection_count'] ?? 0}",
                      Icons.format_quote),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        // Focus-Specific Feedback
        if (focusFeedback.isNotEmpty) ...[
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF9D4EDD).withOpacity(0.1),
              borderRadius: BorderRadius.circular(12),
              border:
                  Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.lightbulb,
                        color: Color(0xFF9D4EDD), size: 20),
                    const SizedBox(width: 8),
                    Text(
                      "Focus: ${_classroomFocusArea}",
                      style: const TextStyle(
                          color: Color(0xFF9D4EDD),
                          fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(focusFeedback,
                    style: const TextStyle(color: Colors.white70, height: 1.5)),
              ],
            ),
          ),
          const SizedBox(height: 16),
        ],

        // Strengths & Growth Areas
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
                child: _buildFeedbackSection("Strengths", strengths,
                    const Color(0xFF4ECDC4), Icons.thumb_up)),
            const SizedBox(width: 12),
            Expanded(
                child: _buildFeedbackSection("Growth Areas", growthAreas,
                    const Color(0xFFFFD700), Icons.trending_up)),
          ],
        ),
        const SizedBox(height: 16),

        // Key Moments
        if (keyMoments.isNotEmpty) ...[
          _buildKeyMomentsSection(keyMoments),
          const SizedBox(height: 16),
        ],

        if (transcriptSummary.isNotEmpty) ...[
          _buildClassroomTextCard(
              "Transcript summary", transcriptSummary, Icons.subject),
          const SizedBox(height: 16),
        ],
        if (visualObs.isNotEmpty) ...[
          _buildClassroomTextCard(
              "Visual observations", visualObs, Icons.videocam_outlined),
          const SizedBox(height: 16),
        ],
        if (facialSummary.isNotEmpty) ...[
          _buildFacialSummarySection(facialSummary, emotionalTimeline),
          const SizedBox(height: 16),
        ],
        if (voiceSeriesRaw is List && voiceSeriesRaw.isNotEmpty) ...[
          _buildVoiceTimelineSection(List<dynamic>.from(voiceSeriesRaw)),
          const SizedBox(height: 16),
        ],
        if (crystalRaw is List && crystalRaw.isNotEmpty) ...[
          _buildCrystalEntriesSection(List<dynamic>.from(crystalRaw)),
          const SizedBox(height: 16),
        ],
        if (multimodalFusion.isNotEmpty) ...[
          _buildMultiModalSection(multimodalFusion, sessionArc),
          const SizedBox(height: 16),
        ],
        if (clinicalFlags.isNotEmpty) ...[
          _buildClinicalFlagsSection(clinicalFlags),
          const SizedBox(height: 16),
        ],
        if (longitudinalPatterns.isNotEmpty &&
            (longitudinalPatterns['patterns'] is List) &&
            (longitudinalPatterns['patterns'] as List).isNotEmpty) ...[
          _buildLongitudinalPatternsSection(longitudinalPatterns),
          const SizedBox(height: 16),
        ],

        // Assignments Section
        _buildAssignmentsSection(reflectionQuestions, dojoScenarios,
            workbookRecs, reflectionSubmitted),
      ],
    );
  }

  Widget _buildMetricItem(String label, String value, IconData icon) {
    return Expanded(
      child: Column(
        children: [
          Icon(icon, color: Colors.grey, size: 20),
          const SizedBox(height: 4),
          Text(value,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.bold)),
          Text(label, style: TextStyle(color: Colors.grey[600], fontSize: 10)),
        ],
      ),
    );
  }

  Widget _buildFeedbackSection(
      String title, List<String> items, Color color, IconData icon) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 16),
              const SizedBox(width: 6),
              Text(title,
                  style: TextStyle(
                      color: color, fontWeight: FontWeight.w600, fontSize: 13)),
            ],
          ),
          const SizedBox(height: 8),
          ...items.take(4).map((item) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text("• ", style: TextStyle(color: color)),
                    Expanded(
                        child: Text(item,
                            style: const TextStyle(
                                color: Colors.white70,
                                fontSize: 12,
                                height: 1.3))),
                  ],
                ),
              )),
        ],
      ),
    );
  }

  Widget _buildKeyMomentsSection(List<Map<String, dynamic>> moments) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.star, color: Color(0xFFFFD700), size: 20),
              SizedBox(width: 8),
              Text("Key Moments",
                  style: TextStyle(
                      color: Colors.white70, fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: 12),
          ...moments.take(5).map((moment) => Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF0A0A0F),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: const Color(0xFF9D4EDD).withOpacity(0.2),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            moment['timestamp']?.toString() ?? '',
                            style: const TextStyle(
                                color: Color(0xFF9D4EDD),
                                fontSize: 11,
                                fontFamily: 'Courier'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            moment['description']?.toString() ?? '',
                            style: const TextStyle(
                                color: Colors.white, fontSize: 12),
                          ),
                        ),
                      ],
                    ),
                    if (moment['feedback'] != null) ...[
                      const SizedBox(height: 8),
                      Text(
                        moment['feedback'].toString(),
                        style: TextStyle(
                            color: Colors.grey[400],
                            fontSize: 11,
                            fontStyle: FontStyle.italic),
                      ),
                    ],
                  ],
                ),
              )),
        ],
      ),
    );
  }

  Widget _buildClassroomTextCard(String title, String body, IconData icon) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: const Color(0xFF9D4EDD), size: 20),
              const SizedBox(width: 8),
              Text(title,
                  style: const TextStyle(
                      color: Colors.white70, fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: 10),
          Text(body,
              style: const TextStyle(
                  color: Colors.white70, fontSize: 13, height: 1.45)),
        ],
      ),
    );
  }

  /// Facial expression analysis summary card (MediaPipe FaceMesh-derived).
  /// Shows aggregate engagement / aversion / dominant expression and the
  /// emotional inference timeline as a compact strip of colored dots.
  Widget _buildFacialSummarySection(
    Map<String, dynamic> summary,
    List<dynamic> timeline,
  ) {
    final framesWithFace = (summary['frames_with_face'] ?? 0) as int;
    final framesTotal = (summary['frames_total'] ?? 0) as int;
    final avgEngagement = (summary['avg_engagement'] is num)
        ? (summary['avg_engagement'] as num).toDouble()
        : 0.0;
    final aversion = (summary['gaze_aversion_ratio'] is num)
        ? (summary['gaze_aversion_ratio'] as num).toDouble()
        : 0.0;
    final variability = (summary['expression_variability'] is num)
        ? (summary['expression_variability'] as num).toDouble()
        : 0.0;
    final dominant = (summary['dominant_expression'] ?? 'neutral').toString();
    final indicators = List<String>.from(summary['potential_indicators'] ?? []);

    Color colorFor(String emotion) {
      switch (emotion) {
        case 'engaged':
          return const Color(0xFF4ECDC4);
        case 'attentive':
          return const Color(0xFF8BC34A);
        case 'anxious':
          return const Color(0xFFFFB74D);
        case 'distressed':
          return const Color(0xFFEF4444);
        case 'withdrawn':
          return const Color(0xFF9D4EDD);
        case 'surprised':
          return const Color(0xFFE8D5A3);
        case 'no_face':
          return Colors.white12;
        default:
          return Colors.grey;
      }
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.face_retouching_natural,
                  color: Color(0xFF4ECDC4), size: 20),
              const SizedBox(width: 8),
              const Text(
                "Facial Expression Analysis",
                style: TextStyle(
                    color: Colors.white70, fontWeight: FontWeight.w600),
              ),
              const Spacer(),
              Text(
                "$framesWithFace / $framesTotal frames",
                style: TextStyle(color: Colors.grey[500], fontSize: 11),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _buildFacialMetric("Engagement",
                  "${(avgEngagement * 100).round()}%", Icons.visibility),
              _buildFacialMetric(
                  "Gaze aversion",
                  "${(aversion * 100).round()}%",
                  Icons.remove_red_eye_outlined),
              _buildFacialMetric("Variability", variability.toStringAsFixed(2),
                  Icons.timeline),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              const Icon(Icons.mood, color: Colors.white54, size: 16),
              const SizedBox(width: 6),
              Text("Dominant expression: ",
                  style: TextStyle(color: Colors.grey[400], fontSize: 12)),
              Text(
                dominant,
                style: TextStyle(
                    color: colorFor(dominant),
                    fontSize: 12,
                    fontWeight: FontWeight.w600),
              ),
            ],
          ),
          if (timeline.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text("Emotional timeline",
                style: TextStyle(color: Colors.grey[400], fontSize: 11)),
            const SizedBox(height: 6),
            SizedBox(
              height: 18,
              child: Row(
                children: [
                  for (final e in timeline)
                    if (e is Map)
                      Expanded(
                        child: Container(
                          margin: const EdgeInsets.symmetric(horizontal: 1),
                          decoration: BoxDecoration(
                            color: colorFor(
                                (e['emotional_inference'] ?? 'neutral')
                                    .toString()),
                            borderRadius: BorderRadius.circular(2),
                          ),
                        ),
                      ),
                ],
              ),
            ),
          ],
          if (indicators.isNotEmpty) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFFEF4444).withOpacity(0.08),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(
                    color: const Color(0xFFEF4444).withOpacity(0.25)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: const [
                      Icon(Icons.warning_amber_rounded,
                          color: Color(0xFFEF4444), size: 16),
                      SizedBox(width: 6),
                      Text("Potential indicators",
                          style: TextStyle(
                              color: Color(0xFFEF4444),
                              fontSize: 12,
                              fontWeight: FontWeight.w600)),
                    ],
                  ),
                  const SizedBox(height: 6),
                  ...indicators.map((i) => Padding(
                        padding: const EdgeInsets.only(top: 2.0),
                        child: Text("• $i",
                            style: const TextStyle(
                                color: Colors.white70,
                                fontSize: 12,
                                height: 1.4)),
                      )),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildFacialMetric(String label, String value, IconData icon) {
    return Expanded(
      child: Column(
        children: [
          Icon(icon, color: const Color(0xFF4ECDC4), size: 18),
          const SizedBox(height: 4),
          Text(value,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w600)),
          Text(label, style: TextStyle(color: Colors.grey[500], fontSize: 11)),
        ],
      ),
    );
  }

  /// Stress / engagement samples: list of maps with keys like stress, engagement, t, time, score (0–1).
  Widget _buildVoiceTimelineSection(List<dynamic> series) {
    final values = <double>[];
    for (final e in series) {
      if (e is Map) {
        final m = Map<String, dynamic>.from(e);
        final v = m['stress'] ?? m['engagement'] ?? m['score'] ?? m['arousal'];
        if (v is num) values.add(v.toDouble().clamp(0.0, 1.0));
      } else if (e is num) {
        values.add(e.toDouble().clamp(0.0, 1.0));
      }
    }
    if (values.isEmpty) {
      return const SizedBox.shrink();
    }
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.graphic_eq, color: Color(0xFF4ECDC4), size: 20),
              SizedBox(width: 8),
              Text(
                "Voice / engagement (over time)",
                style: TextStyle(
                    color: Colors.white70, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 72,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: values.take(48).map((v) {
                return Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 1),
                    child: Container(
                      height: 8 + v * 56,
                      decoration: BoxDecoration(
                        color: Color.lerp(
                          const Color(0xFF4ECDC4),
                          const Color(0xFFFF6B6B),
                          v,
                        ),
                        borderRadius: BorderRadius.circular(2),
                      ),
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            "${values.length} samples · low → high intensity",
            style: TextStyle(color: Colors.grey[600], fontSize: 11),
          ),
        ],
      ),
    );
  }

  Widget _buildCrystalEntriesSection(List<dynamic> entries) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0F),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.auto_awesome, color: Color(0xFFFFD700), size: 20),
              SizedBox(width: 8),
              Text(
                "Crystal memory (this session)",
                style: TextStyle(
                    color: Color(0xFFFFD700), fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ...entries.take(8).map((e) {
            String line = e.toString();
            if (e is Map) {
              final m = Map<String, dynamic>.from(e);
              line = (m['text'] ??
                      m['content'] ??
                      m['summary'] ??
                      m['title'] ??
                      jsonEncode(m))
                  .toString();
            }
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text("◇ ",
                      style: TextStyle(color: Color(0xFFFFD700), fontSize: 12)),
                  Expanded(
                    child: Text(line,
                        style: const TextStyle(
                            color: Colors.white70, fontSize: 12, height: 1.35)),
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }

  // ===== MULTI-MODAL FUSION DISPLAY =====
  Widget _buildMultiModalSection(
    Map<String, dynamic> fusion,
    Map<String, dynamic> sessionArc,
  ) {
    final unified = (fusion['unified_timeline'] is List)
        ? List<dynamic>.from(fusion['unified_timeline'] as List)
        : <dynamic>[];
    final incongruent = (fusion['incongruence_moments'] is List)
        ? List<dynamic>.from(fusion['incongruence_moments'] as List)
        : <dynamic>[];
    final modalities = (fusion['modalities_present'] is Map)
        ? Map<String, dynamic>.from(fusion['modalities_present'] as Map)
        : <String, dynamic>{};

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.layers, color: Color(0xFF4ECDC4), size: 20),
              const SizedBox(width: 8),
              const Text("Multi-Modal Analysis",
                  style: TextStyle(
                      color: Colors.white70, fontWeight: FontWeight.w600)),
              const Spacer(),
              if (modalities.isNotEmpty)
                Text(
                  [
                    if (modalities['text'] == true) "text",
                    if (modalities['voice'] == true) "voice",
                    if (modalities['facial'] == true) "face",
                  ].join(" + "),
                  style: TextStyle(color: Colors.grey[500], fontSize: 11),
                ),
            ],
          ),
          const SizedBox(height: 12),
          if (sessionArc.isNotEmpty &&
              sessionArc['arc_description'] != null) ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: const Color(0xFF0A0A0F),
                borderRadius: BorderRadius.circular(6),
                border:
                    Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.timeline,
                      color: Color(0xFF9D4EDD), size: 14),
                  const SizedBox(width: 6),
                  Text("Session arc:",
                      style: TextStyle(color: Colors.grey[400], fontSize: 11)),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      sessionArc['arc_description']?.toString() ?? '',
                      style: const TextStyle(
                        color: Color(0xFFE8D5A3),
                        fontSize: 12,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
          ],
          if (unified.isNotEmpty) ...[
            Text("Unified timeline (${unified.length} moments)",
                style: TextStyle(color: Colors.grey[400], fontSize: 11)),
            const SizedBox(height: 6),
            ...unified.take(8).map((entry) {
              final m = (entry is Map)
                  ? Map<String, dynamic>.from(entry)
                  : <String, dynamic>{};
              final isIncongruent = m['incongruence'] != null;
              return Container(
                margin: const EdgeInsets.only(bottom: 6),
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: isIncongruent
                      ? const Color(0xFFEF4444).withOpacity(0.08)
                      : const Color(0xFF0A0A0F),
                  borderRadius: BorderRadius.circular(6),
                  border: isIncongruent
                      ? Border.all(
                          color: const Color(0xFFEF4444).withOpacity(0.4))
                      : null,
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: const Color(0xFF9D4EDD).withOpacity(0.2),
                        borderRadius: BorderRadius.circular(3),
                      ),
                      child: Text(
                        "${(m['timestamp'] is num) ? (m['timestamp'] as num).toStringAsFixed(0) : '0'}s",
                        style: const TextStyle(
                            color: Color(0xFF9D4EDD),
                            fontSize: 10,
                            fontFamily: 'Courier'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          if ((m['text'] ?? '').toString().isNotEmpty)
                            Text(
                              m['text'].toString(),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                  color: isIncongruent
                                      ? Colors.white
                                      : Colors.white70,
                                  fontSize: 12),
                            ),
                          const SizedBox(height: 2),
                          Wrap(
                            spacing: 6,
                            children: [
                              _modalityChip(
                                  "text", m['text_sentiment']?.toString()),
                              _modalityChip(
                                  "voice", m['voice_emotion']?.toString()),
                              _modalityChip(
                                  "face", m['facial_emotion']?.toString()),
                              _modalityChip("gaze", m['gaze']?.toString()),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
          if (incongruent.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              "${incongruent.length} incongruence moment${incongruent.length == 1 ? '' : 's'} flagged",
              style: const TextStyle(
                  color: Color(0xFFEF4444),
                  fontSize: 12,
                  fontWeight: FontWeight.w600),
            ),
          ],
        ],
      ),
    );
  }

  Widget _modalityChip(String label, String? value) {
    final v = (value ?? '').trim();
    if (v.isEmpty || v == 'unknown' || v == 'no_face' || v == 'silence') {
      return const SizedBox.shrink();
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: Colors.white.withOpacity(0.05),
        borderRadius: BorderRadius.circular(3),
        border: Border.all(color: Colors.white.withOpacity(0.1)),
      ),
      child: Text(
        "$label:$v",
        style: const TextStyle(color: Colors.white60, fontSize: 10),
      ),
    );
  }

  // ===== CLINICAL FLAGS =====
  Widget _buildClinicalFlagsSection(List<dynamic> flags) {
    Color sevColor(String s) {
      switch (s.toLowerCase()) {
        case 'high':
          return const Color(0xFFEF4444);
        case 'medium':
          return const Color(0xFFFFD700);
        default:
          return const Color(0xFF4ECDC4);
      }
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.flag, color: Color(0xFFEF4444), size: 20),
              SizedBox(width: 8),
              Text("Clinical Flags",
                  style: TextStyle(
                      color: Colors.white70, fontWeight: FontWeight.w600)),
            ],
          ),
          const SizedBox(height: 12),
          ...flags.map((f) {
            final m =
                (f is Map) ? Map<String, dynamic>.from(f) : <String, dynamic>{};
            final flag = m['flag']?.toString() ?? 'FLAG';
            final note = m['clinical_note']?.toString() ?? '';
            final sev = m['severity']?.toString() ?? 'low';
            final color = sevColor(sev);
            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: const Color(0xFF0A0A0F),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: color.withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          flag.replaceAll('_', ' '),
                          style: TextStyle(
                              color: color,
                              fontWeight: FontWeight.w700,
                              fontSize: 12),
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: color.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(3),
                        ),
                        child: Text(sev.toUpperCase(),
                            style: TextStyle(
                                color: color,
                                fontSize: 10,
                                fontWeight: FontWeight.w600)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(note,
                      style: const TextStyle(
                          color: Colors.white70, fontSize: 12, height: 1.3)),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }

  // ===== LONGITUDINAL PATTERNS =====
  Widget _buildLongitudinalPatternsSection(Map<String, dynamic> longitudinal) {
    final patterns = (longitudinal['patterns'] is List)
        ? List<dynamic>.from(longitudinal['patterns'] as List)
        : <dynamic>[];
    final sessionsAnalyzed = longitudinal['sessions_analyzed'] ?? 0;
    final trend = (longitudinal['trend_direction'] ?? '').toString();

    Color trendColor() {
      switch (trend) {
        case 'improving':
          return const Color(0xFF4ECDC4);
        case 'declining':
          return const Color(0xFFEF4444);
        case 'stable':
          return const Color(0xFFFFD700);
        default:
          return Colors.grey;
      }
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.insights, color: Color(0xFF9D4EDD), size: 20),
              const SizedBox(width: 8),
              const Text("Longitudinal Patterns",
                  style: TextStyle(
                      color: Colors.white70, fontWeight: FontWeight.w600)),
              const Spacer(),
              Text("$sessionsAnalyzed sessions",
                  style: TextStyle(color: Colors.grey[500], fontSize: 11)),
            ],
          ),
          if (trend.isNotEmpty && trend != 'insufficient_data') ...[
            const SizedBox(height: 8),
            Row(
              children: [
                Icon(
                  trend == 'improving'
                      ? Icons.trending_up
                      : trend == 'declining'
                          ? Icons.trending_down
                          : Icons.trending_flat,
                  color: trendColor(),
                  size: 14,
                ),
                const SizedBox(width: 6),
                Text("Trend: $trend",
                    style: TextStyle(
                        color: trendColor(),
                        fontSize: 11,
                        fontWeight: FontWeight.w600)),
              ],
            ),
          ],
          const SizedBox(height: 12),
          ...patterns.map((p) {
            final m =
                (p is Map) ? Map<String, dynamic>.from(p) : <String, dynamic>{};
            final isTransgen =
                (m['pattern']?.toString() ?? '') == 'TRANSGENERATIONAL';
            final matches = (m['matches'] is List)
                ? List<dynamic>.from(m['matches'] as List)
                : <dynamic>[];
            return _buildPatternCard(m,
                isTransgen: isTransgen, matches: matches);
          }),
        ],
      ),
    );
  }

  Widget _buildPatternCard(
    Map<String, dynamic> p, {
    bool isTransgen = false,
    List<dynamic> matches = const [],
  }) {
    final accent =
        isTransgen ? const Color(0xFFEF4444) : const Color(0xFF9D4EDD);
    final pattern = p['pattern']?.toString() ?? 'PATTERN';
    final note = p['clinical_note']?.toString() ?? '';
    final freq = p['frequency']?.toString() ?? p['trend']?.toString() ?? '';
    final focus = p['recommended_focus']?.toString() ?? '';

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0F),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: accent.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                isTransgen ? Icons.family_restroom : Icons.repeat,
                color: accent,
                size: 14,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  pattern.replaceAll('_', ' '),
                  style: TextStyle(
                      color: accent, fontWeight: FontWeight.w700, fontSize: 12),
                ),
              ),
              if (freq.isNotEmpty)
                Text(freq,
                    style: TextStyle(color: Colors.grey[500], fontSize: 10)),
            ],
          ),
          const SizedBox(height: 6),
          Text(note,
              style: const TextStyle(
                  color: Colors.white70, fontSize: 12, height: 1.3)),
          if (focus.isNotEmpty) ...[
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: accent.withOpacity(0.15),
                borderRadius: BorderRadius.circular(3),
              ),
              child: Text("Focus: $focus",
                  style: TextStyle(
                      color: accent,
                      fontSize: 10,
                      fontWeight: FontWeight.w600)),
            ),
          ],
          if (isTransgen && matches.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text("Shared with:",
                style: TextStyle(
                    color: Colors.white60,
                    fontSize: 11,
                    fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            ...matches.map((mm) {
              final mp = (mm is Map)
                  ? Map<String, dynamic>.from(mm)
                  : <String, dynamic>{};
              final name = mp['family_member']?.toString() ?? 'family member';
              final shared = (mp['shared_patterns'] is List)
                  ? (mp['shared_patterns'] as List).join(', ')
                  : '';
              return Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text("• $name: $shared",
                    style:
                        const TextStyle(color: Colors.white60, fontSize: 11)),
              );
            }),
            const SizedBox(height: 6),
            Text(
              "Recommend exploring in Family Sanctuary",
              style: TextStyle(
                  color: accent, fontSize: 10, fontStyle: FontStyle.italic),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildAssignmentsSection(
    List<String> reflectionQuestions,
    List<Map<String, dynamic>> dojoScenarios,
    List<String> workbookRecs,
    bool reflectionSubmitted,
  ) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0F),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.assignment, color: Color(0xFF4ECDC4), size: 20),
              const SizedBox(width: 8),
              const Text("Your Assignments",
                  style: TextStyle(
                      color: Color(0xFF4ECDC4), fontWeight: FontWeight.w600)),
              const Spacer(),
              if (reflectionSubmitted)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: const Color(0xFF4ECDC4).withOpacity(0.2),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.check, color: Color(0xFF4ECDC4), size: 14),
                      SizedBox(width: 4),
                      Text("Submitted",
                          style: TextStyle(
                              color: Color(0xFF4ECDC4), fontSize: 11)),
                    ],
                  ),
                ),
            ],
          ),
          const SizedBox(height: 16),

          // Reflection Questions
          if (reflectionQuestions.isNotEmpty) ...[
            const Text("Reflection Questions",
                style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 8),
            ...reflectionQuestions.asMap().entries.map((entry) {
              final index = entry.key;
              final question = entry.value;
              final controller = _classroomReflectionControllers['q_$index'] ??
                  TextEditingController();
              return Container(
                margin: const EdgeInsets.only(bottom: 12),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF111111),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(question,
                        style:
                            const TextStyle(color: Colors.white, fontSize: 13)),
                    const SizedBox(height: 8),
                    TextField(
                      controller: controller,
                      enabled: !reflectionSubmitted,
                      style:
                          const TextStyle(color: Colors.white70, fontSize: 12),
                      maxLines: 3,
                      decoration: InputDecoration(
                        hintText: reflectionSubmitted
                            ? "Response submitted"
                            : "Your reflection...",
                        hintStyle: TextStyle(color: Colors.grey[700]),
                        filled: true,
                        fillColor: const Color(0xFF0A0A0F),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(6),
                          borderSide: BorderSide.none,
                        ),
                        contentPadding: const EdgeInsets.all(10),
                      ),
                    ),
                  ],
                ),
              );
            }),
            if (!reflectionSubmitted) ...[
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: _submitReflections,
                  icon: const Icon(Icons.send, size: 18),
                  label: const Text("Submit Reflections"),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4ECDC4),
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ),
            ],
            const SizedBox(height: 16),
          ],

          // Dojo Scenarios
          if (dojoScenarios.isNotEmpty) ...[
            const Text("Recommended Dojo Practice",
                style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 8),
            ...dojoScenarios.take(3).map((scenario) => Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF9D4EDD).withOpacity(0.1),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                        color: const Color(0xFF9D4EDD).withOpacity(0.3)),
                  ),
                  child: Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: const Color(0xFF9D4EDD).withOpacity(0.3),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          scenario['persona']?.toString() ?? 'PRACTICE',
                          style: const TextStyle(
                              color: Color(0xFF9D4EDD),
                              fontSize: 10,
                              fontWeight: FontWeight.bold),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          scenario['scenario']?.toString() ?? '',
                          style: const TextStyle(
                              color: Colors.white70, fontSize: 12),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.play_arrow,
                            color: Color(0xFF9D4EDD), size: 20),
                        onPressed: () {
                          // Navigate to Dojo tab
                          _tabController.animateTo(4); // Dojo tab index
                        },
                        tooltip: "Practice in Dojo",
                      ),
                    ],
                  ),
                )),
            const SizedBox(height: 16),
          ],

          // Workbook Recommendations
          if (workbookRecs.isNotEmpty) ...[
            const Text("Recommended Reading",
                style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 8),
            ...workbookRecs.take(3).map((rec) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    children: [
                      const Icon(Icons.menu_book,
                          color: Color(0xFFFFD700), size: 16),
                      const SizedBox(width: 8),
                      Expanded(
                          child: Text(rec,
                              style: const TextStyle(
                                  color: Colors.white70, fontSize: 12))),
                    ],
                  ),
                )),
          ],
        ],
      ),
    );
  }

  Widget _buildClassroomHistorySection() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text("Recent Analyses",
              style: TextStyle(
                  color: Colors.white70, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          ..._classroomHistory.take(5).map((analysis) {
            final score =
                (analysis['therapeutic_presence_score'] ?? 0.0) as double;
            final date =
                (analysis['analyzed_at'] ?? '').toString().split('T').first;
            return ListTile(
              contentPadding: EdgeInsets.zero,
              leading: CircleAvatar(
                backgroundColor: _getScoreColor(score / 10).withOpacity(0.2),
                child: Text(
                  score.toStringAsFixed(0),
                  style: TextStyle(
                      color: _getScoreColor(score / 10),
                      fontWeight: FontWeight.bold),
                ),
              ),
              title: Text(
                analysis['client_id']?.toString() ?? 'Session',
                style: const TextStyle(color: Colors.white, fontSize: 14),
              ),
              subtitle: Text(date,
                  style: TextStyle(color: Colors.grey[600], fontSize: 12)),
              trailing: IconButton(
                icon: const Icon(Icons.arrow_forward_ios,
                    size: 16, color: Colors.grey),
                onPressed: () {
                  setState(() {
                    _classroomAnalysis = analysis;
                    _classroomSelectedSessionId =
                        analysis['session_id']?.toString();
                  });
                },
              ),
            );
          }),
        ],
      ),
    );
  }

  // Classroom helper methods

  void _cancelClassroomVideoPoll() {
    _classroomVideoPollTimer?.cancel();
    _classroomVideoPollTimer = null;
  }

  /// Distinguish finished session analysis from in-flight rows (status=analyzing) or empty metadata.
  bool _isClassroomSessionAnalysisComplete(Map<String, dynamic>? a) {
    if (a == null || a.isEmpty) return false;
    final err = '${a['error'] ?? ''}';
    if (err.isNotEmpty) return false;
    final st = (a['status'] ?? '').toString().toLowerCase();
    if (st == 'analyzing') return false;
    if (st == 'analyzed' || st == 'complete') return true;
    if (a['therapeutic_presence_score'] != null) return true;
    return false;
  }

  /// Merge nested `analysis` (device-upload records) into one map for the results UI.
  Map<String, dynamic>? _flattenClassroomAnalysis(Map<String, dynamic>? raw) {
    if (raw == null) return null;
    final inner = raw['analysis'];
    if (inner is Map) {
      final merged = Map<String, dynamic>.from(inner as Map);
      raw.forEach((k, v) {
        if (k == 'analysis') return;
        merged[k] = v;
      });
      return merged;
    }
    return raw;
  }

  void _startClassroomVideoAnalysisPoll(String videoSessionId) {
    _cancelClassroomVideoPoll();
    if (!mounted) return;
    setState(() {
      _classroomServerPipelineLabel = null;
      _classroomServerPipelineIndex = null;
      _classroomVideoPipelineActive = true;
      _classroomVideoStageIndex = 0;
      _classroomAnalyzing = true;
      _classroomSelectedSessionId = videoSessionId;
      _classroomAnalysis = null;
    });
    _requestClassroomSessions();
    var ticks = 0;
    _classroomVideoPollTimer =
        Timer.periodic(const Duration(seconds: 5), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      ticks += 1;
      // 30-min ceiling: a 90-min Zoom recording typically needs ~5-8 min for
      // whisper STT plus 2-4 min for the rest of the pipeline, but very long
      // or contention-heavy runs can push past 15 min. Don't kill the poll
      // prematurely — the backend keeps working in the background, and the
      // tab-restoration logic in classroom_sessions handler will reconnect
      // automatically if the user switches tabs and comes back.
      if (ticks * 5 > 1800) {
        _cancelClassroomVideoPoll();
        setState(() {
          _classroomServerPipelineLabel = null;
          _classroomServerPipelineIndex = null;
          _classroomVideoPipelineActive = false;
          _classroomAnalyzing = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Analysis is still running in the background. '
              'Switch tabs freely \u2014 it will reappear here when ready.',
            ),
            duration: Duration(seconds: 6),
          ),
        );
        return;
      }
      setState(() {
        if (_classroomServerPipelineLabel == null) {
          _classroomVideoStageIndex = ticks % _classroomVideoStages.length;
        }
      });
      _loadSessionAnalysis(videoSessionId);
    });
    _loadSessionAnalysis(videoSessionId);
  }

  void _requestClassroomSessions() {
    _socket?.sink.add(jsonEncode({
      "type": "classroom_get_sessions",
      "coach_id": widget.username,
    }));
  }

  void _requestClassroomProgress() {
    _socket?.sink.add(jsonEncode({
      "type": "classroom_get_progress",
      "coach_id": widget.username,
    }));
  }

  void _loadSessionAnalysis(String sessionId) {
    _socket?.sink.add(jsonEncode({
      "type": "classroom_get_analysis",
      "session_id": sessionId,
    }));
  }

  void _analyzeSelectedSession() {
    if (_classroomSelectedSessionId == null) return;

    setState(() => _classroomAnalyzing = true);

    _socket?.sink.add(jsonEncode({
      "type": "classroom_analyze_session",
      "session_id": _classroomSelectedSessionId,
      "coach_id": widget.username,
      "focus_area": _classroomFocusArea,
      "due_date": _classroomDueDate?.toIso8601String(),
      "coach_query": _classroomCoachQueryController.text.trim(),
    }));
  }

  void _submitReflections() {
    if (_classroomAnalysis == null || _classroomSelectedSessionId == null)
      return;

    final responses = <String, String>{};
    _classroomReflectionControllers.forEach((key, controller) {
      if (controller.text.trim().isNotEmpty) {
        responses[key] = controller.text.trim();
      }
    });

    if (responses.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text("Please answer at least one reflection question")),
      );
      return;
    }

    _socket?.sink.add(jsonEncode({
      "type": "classroom_submit_reflection",
      "session_id": _classroomSelectedSessionId,
      "coach_id": widget.username,
      "reflection_responses": responses,
    }));
  }

  // Live Analysis Methods

  void _checkRecordingAvailability() {
    if (_classroomSelectedSessionId == null) return;

    setState(() => _classroomCheckingRecording = true);

    _socket?.sink.add(jsonEncode({
      "type": "classroom_check_recording",
      "session_id": _classroomSelectedSessionId,
    }));
  }

  void _analyzeLiveSession() {
    if (_classroomSelectedSessionId == null) return;

    setState(() => _classroomLiveAnalyzing = true);

    _socket?.sink.add(jsonEncode({
      "type": "classroom_analyze_live",
      "session_id": _classroomSelectedSessionId,
      "focus_area": _classroomFocusArea,
    }));
  }

  bool get _canAnalyzeLive {
    final recording = _classroomRecordingStatus;
    if (recording == null) return false;

    final available = recording['available'] == true;
    final status = recording['status'];

    // Can analyze if recording is in progress or completed
    return available && (status == 'recording' || status == 'completed');
  }

  bool get _isSessionLive {
    final meeting = _classroomMeetingStatus;
    if (meeting == null) return false;
    return meeting['status'] == 'started';
  }

  int get _recordingDaysRemaining {
    final recording = _classroomRecordingStatus;
    if (recording == null) return 0;
    return (recording['days_remaining'] ?? 0) as int;
  }

  Widget _buildEmptyStateTab(
      {required IconData icon,
      required String title,
      required String subtitle}) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: Colors.white24, size: 56),
            const SizedBox(height: 14),
            Text(
              title,
              style: const TextStyle(
                  color: Colors.white70,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.5),
            ),
            const SizedBox(height: 8),
            Text(
              subtitle,
              style: const TextStyle(color: Colors.grey),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatCard(
      String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(height: 8),
          Text(
            value,
            style: TextStyle(
                color: color,
                fontWeight: FontWeight.bold,
                fontSize: 24,
                fontFamily: 'Courier'),
          ),
          Text(label, style: TextStyle(color: Colors.grey[400], fontSize: 11)),
        ],
      ),
    );
  }

  // =============================================================================
  // FINANCIAL METHODS - Request data, approve/decline bookings, set fee/mode
  // =============================================================================

  void _requestFinancials() {
    _socket?.sink.add(jsonEncode({
      "type": "coach_get_financials",
      "coach_id": widget.username,
    }));
  }

  Future<void> _loadConnectStatus() async {
    if (_connectLoading) return;
    setState(() => _connectLoading = true);
    try {
      final token = widget.currentUserProfile['token'] ?? '';
      final resp = await http.get(
        Uri.parse('$defaultApiBaseUrl/api/billing/connect/status'),
        headers: {'Authorization': 'Bearer $token'},
      );
      if (resp.statusCode == 200 && mounted) {
        setState(() {
          _connectStatus = Map<String, dynamic>.from(jsonDecode(resp.body));
          _connectLoading = false;
        });
        return;
      }
    } catch (_) {}
    if (mounted) setState(() => _connectLoading = false);
  }

  Future<void> _startConnectOnboarding() async {
    if (_connectOnboarding) return;
    setState(() => _connectOnboarding = true);
    try {
      final token = widget.currentUserProfile['token'] ?? '';
      final resp = await http.post(
        Uri.parse('$defaultApiBaseUrl/api/billing/connect/onboard'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json'
        },
      );
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body);
        final url = data['url'] as String?;
        if (url != null && url.isNotEmpty) {
          final uri = Uri.parse(url);
          if (await canLaunchUrl(uri)) {
            await launchUrl(uri, mode: LaunchMode.externalApplication);
          }
        } else if (data['status'] == 'already_connected') {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text('Stripe Connect already set up'),
                backgroundColor: Color(0xFF4ECDC4)),
          );
        }
      } else if (mounted) {
        final err = jsonDecode(resp.body);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text(err['detail']?.toString() ?? 'Onboarding failed'),
              backgroundColor: Colors.redAccent),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content: Text('Connection error: $e'),
              backgroundColor: Colors.redAccent),
        );
      }
    }
    if (mounted) {
      setState(() => _connectOnboarding = false);
      _loadConnectStatus();
    }
  }

  Future<void> _openConnectDashboard() async {
    try {
      final token = widget.currentUserProfile['token'] ?? '';
      final resp = await http.post(
        Uri.parse('$defaultApiBaseUrl/api/billing/connect/dashboard'),
        headers: {
          'Authorization': 'Bearer $token',
          'Content-Type': 'application/json'
        },
      );
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body);
        final url = data['url'] as String?;
        if (url != null && url.isNotEmpty) {
          final uri = Uri.parse(url);
          if (await canLaunchUrl(uri)) {
            await launchUrl(uri, mode: LaunchMode.externalApplication);
          }
        }
      }
    } catch (_) {}
  }

  void _requestDojoSubscriptions() {
    setState(() => _dojoSubsLoading = true);
    _socket?.sink.add(jsonEncode({
      "type": "get_dojo_subscriptions",
    }));
  }

  void _cancelDojoSubscription(String dojoKey) {
    _socket?.sink.add(jsonEncode({
      "type": "cancel_dojo_subscription",
      "dojo_key": dojoKey,
    }));
  }

  void _addDojoSubscription(String dojoKey) {
    _socket?.sink.add(jsonEncode({
      "type": "add_dojo_subscription",
      "dojo_key": dojoKey,
    }));
  }

  void _requestPendingBookings() {
    _socket?.sink.add(jsonEncode({
      "type": "coach_get_pending_bookings",
      "coach_id": widget.username,
    }));
  }

  void _approveBooking(String sessionId) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_approve_booking",
      "session_id": sessionId,
      "coach_id": widget.username,
    }));
  }

  void _declineBooking(String sessionId, String reason) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_decline_booking",
      "session_id": sessionId,
      "coach_id": widget.username,
      "reason": reason,
    }));
  }

  void _showDeclineDialog(String sessionId) {
    final reasonController = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: const Text("Decline Booking",
            style: TextStyle(color: Colors.redAccent)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Provide a reason (optional):",
                style: TextStyle(color: Colors.white70)),
            const SizedBox(height: 12),
            TextField(
              controller: reasonController,
              style: const TextStyle(color: Colors.white),
              maxLines: 3,
              decoration: InputDecoration(
                hintText: "e.g., Schedule conflict, not available...",
                hintStyle: TextStyle(color: Colors.grey[600]),
                filled: true,
                fillColor: const Color(0xFF111111),
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide.none),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: Colors.redAccent,
                foregroundColor: Colors.white),
            onPressed: () {
              Navigator.pop(ctx);
              _declineBooking(sessionId, reasonController.text.trim());
            },
            child: const Text("Decline"),
          ),
        ],
      ),
    );
  }

  void _showCoachMessageDialog(String requestId, String clientName) {
    final msgController = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: Text("Message $clientName",
            style: const TextStyle(color: Color(0xFFC9A962))),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Send a message before accepting:",
                style: TextStyle(color: Colors.white70)),
            const SizedBox(height: 12),
            TextField(
              controller: msgController,
              style: const TextStyle(color: Colors.white),
              maxLines: 4,
              maxLength: 500,
              decoration: InputDecoration(
                hintText: "e.g., Tell me more about your goals...",
                hintStyle: TextStyle(color: Colors.grey[600]),
                filled: true,
                fillColor: const Color(0xFF111111),
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide.none),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child:
                  const Text("Cancel", style: TextStyle(color: Colors.grey))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFC9A962),
                foregroundColor: Colors.black),
            onPressed: () {
              Navigator.pop(ctx);
              final text = msgController.text.trim();
              if (text.isNotEmpty) {
                _socket?.sink.add(jsonEncode({
                  "type": "coach_send_message",
                  "request_id": requestId,
                  "message_text": text
                }));
              }
            },
            child: const Text("Send"),
          ),
        ],
      ),
    );
  }

  void _showCoachDeclineDialog(String requestId) {
    final reasonController = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: const Text("Decline Request",
            style: TextStyle(color: Colors.redAccent)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Provide a reason (optional):",
                style: TextStyle(color: Colors.white70)),
            const SizedBox(height: 12),
            TextField(
              controller: reasonController,
              style: const TextStyle(color: Colors.white),
              maxLines: 3,
              decoration: InputDecoration(
                hintText: "e.g., Caseload full, specialty mismatch...",
                hintStyle: TextStyle(color: Colors.grey[600]),
                filled: true,
                fillColor: const Color(0xFF111111),
                border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide.none),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child:
                  const Text("Cancel", style: TextStyle(color: Colors.grey))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: Colors.redAccent,
                foregroundColor: Colors.white),
            onPressed: () {
              Navigator.pop(ctx);
              _socket?.sink.add(jsonEncode({
                "type": "coach_decline_request",
                "request_id": requestId,
                "decline_reason": reasonController.text.trim()
              }));
            },
            child: const Text("Decline"),
          ),
        ],
      ),
    );
  }

  void _setCoachFee(double fee) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_set_fee",
      "coach_id": widget.username,
      "coaching_fee": fee,
    }));
  }

  void _setPaymentMode(String mode) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_set_payment_mode",
      "coach_id": widget.username,
      "payment_mode": mode,
    }));
  }

  void _submitW9(Map<String, dynamic> w9Data) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_submit_w9",
      "coach_id": widget.username,
      "w9_data": w9Data,
    }));
  }

  // =============================================================================
  // TRAINING TAB — Coaching Mesh & Community Circle
  // =============================================================================

  Widget _buildTrainingTab() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text("TRAINING",
              style: TextStyle(
                  color: Color(0xFFFFD700),
                  fontFamily: 'Cormorant Garamond',
                  fontSize: 22,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          const Text("Group training sessions, coaching mesh, and community",
              style: TextStyle(color: Colors.grey, fontSize: 12)),
          const SizedBox(height: 24),

          // Start Training Session (Master Coach)
          _buildTrainingAction(
            icon: Icons.play_circle_fill,
            iconColor: const Color(0xFFFFD700),
            title: "Start Training Session",
            subtitle: "Create a BLE coaching mesh as master coach",
            onTap: () {
              Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => _lazyCoachingMeshScreen(isMaster: true),
                  ));
            },
          ),
          const SizedBox(height: 12),

          // Join Training Session
          _buildTrainingAction(
            icon: Icons.login,
            iconColor: const Color(0xFF4ECDC4),
            title: "Join Training Session",
            subtitle: "Connect to a master coach's active session",
            onTap: () {
              Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => _lazyCoachingMeshScreen(isMaster: false),
                  ));
            },
          ),
          const SizedBox(height: 24),

          const Divider(color: Color(0xFF333333)),
          const SizedBox(height: 16),

          const Text("COMMUNITY",
              style: TextStyle(
                  color: Color(0xFF4ECDC4),
                  fontFamily: 'Courier',
                  fontSize: 14,
                  fontWeight: FontWeight.bold)),
          const SizedBox(height: 12),

          _buildTrainingAction(
            icon: Icons.group_work,
            iconColor: const Color(0xFF9D4EDD),
            title: "Community Circle",
            subtitle: "Nate-to-Nate peer group wisdom sessions",
            onTap: () {
              Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => _lazyCommunityMeshScreen(),
                  ));
            },
          ),
          const SizedBox(height: 24),

          const Divider(color: Color(0xFF333333)),
          const SizedBox(height: 16),

          const Text("RECENT SESSIONS",
              style: TextStyle(
                  color: Color(0xFF888888),
                  fontFamily: 'Courier',
                  fontSize: 12)),
          const SizedBox(height: 8),

          FutureBuilder<List<dynamic>>(
            future: _fetchRecentTrainingSessions(),
            builder: (ctx, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Center(
                    child: CircularProgressIndicator(
                        color: Color(0xFFFFD700), strokeWidth: 2));
              }
              final sessions = snap.data ?? [];
              if (sessions.isEmpty) {
                return const Padding(
                  padding: EdgeInsets.symmetric(vertical: 20),
                  child: Center(
                      child: Text("No training sessions yet",
                          style: TextStyle(color: Colors.grey, fontSize: 13))),
                );
              }
              return Column(
                children: sessions.take(5).map<Widget>((s) {
                  return ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.fitness_center,
                        color: Color(0xFFFFD700), size: 20),
                    title: Text(s['title'] ?? 'Training Session',
                        style:
                            const TextStyle(color: Colors.white, fontSize: 14)),
                    subtitle: Text(
                      '${s['session_type'] ?? ''} · ${s['participant_count'] ?? 0} participants',
                      style: const TextStyle(color: Colors.grey, fontSize: 11),
                    ),
                    trailing: Text(
                      s['started_at'] != null
                          ? s['started_at'].toString().substring(0, 10)
                          : '',
                      style: const TextStyle(color: Colors.grey, fontSize: 11),
                    ),
                  );
                }).toList(),
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _buildTrainingAction({
    required IconData icon,
    required Color iconColor,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFF333333)),
        ),
        child: Row(
          children: [
            Icon(icon, color: iconColor, size: 32),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: const TextStyle(
                          color: Colors.white,
                          fontSize: 15,
                          fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Text(subtitle,
                      style: const TextStyle(color: Colors.grey, fontSize: 12)),
                ],
              ),
            ),
            const Icon(Icons.arrow_forward_ios, color: Colors.grey, size: 16),
          ],
        ),
      ),
    );
  }

  Widget _lazyCoachingMeshScreen({required bool isMaster}) {
    final ethicsVersion =
        widget.currentUserProfile['coach_ethics_version'] ?? '';
    if (ethicsVersion != 'v1.0_2026') {
      return Scaffold(
        backgroundColor: const Color(0xFF050505),
        appBar: AppBar(
          title: const Text('DOJO ACCESS'),
          backgroundColor: const Color(0xFF111111),
          foregroundColor: const Color(0xFFC9A962),
        ),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.shield_outlined,
                    color: Color(0xFFC9A962), size: 64),
                const SizedBox(height: 24),
                const Text(
                  'Coach Ethics & Code of Conduct Required',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                      color: Color(0xFFE8D5A3),
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      fontFamily: 'Cormorant Garamond'),
                ),
                const SizedBox(height: 16),
                const Text(
                  'You must accept the Coach Ethics & Code of Conduct before accessing DOJO training sessions.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Color(0xFF999999), fontSize: 14),
                ),
                const SizedBox(height: 32),
                ElevatedButton(
                  onPressed: () => Navigator.pop(context),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFC9A962),
                    foregroundColor: const Color(0xFF050505),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 32, vertical: 14),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8)),
                  ),
                  child: const Text('GO BACK',
                      style: TextStyle(fontWeight: FontWeight.bold)),
                ),
              ],
            ),
          ),
        ),
      );
    }
    return CoachingMeshScreen(
      profile: widget.currentUserProfile,
      token: widget.currentUserProfile['token'] ?? '',
      isMaster: isMaster,
    );
  }

  Widget _lazyCommunityMeshScreen() {
    return CommunityMeshScreen(
      profile: widget.currentUserProfile,
    );
  }

  Future<List<dynamic>> _fetchRecentTrainingSessions() async {
    try {
      final hwId = widget.currentUserProfile['hardware_id'] ?? '';
      final url =
          '${AppConfig.apiBaseUrl}/api/coach/mesh/sessions/$hwId?limit=5';
      final resp = await http.get(
        Uri.parse(url),
        headers: {
          'Authorization': 'Bearer ${widget.currentUserProfile['token']}'
        },
      );
      if (resp.statusCode == 200) return jsonDecode(resp.body) as List;
    } catch (_) {}
    return [];
  }

  // =============================================================================
  // PAYOUT SETTINGS (Stripe Connect Express)
  // =============================================================================

  Widget _buildPayoutSettingsSection() {
    final connected = _connectStatus['connected'] == true;
    final payoutsEnabled = _connectStatus['payouts_enabled'] == true;
    final detailsSubmitted = _connectStatus['details_submitted'] == true;

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A2E),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text("PAYOUT SETTINGS",
                  style: TextStyle(
                      color: Color(0xFFFFD700),
                      fontFamily: 'Courier',
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1)),
              const Spacer(),
              if (_connectLoading)
                const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Color(0xFFFFD700)))
              else
                InkWell(
                  onTap: _loadConnectStatus,
                  child:
                      const Icon(Icons.refresh, color: Colors.grey, size: 18),
                ),
            ],
          ),
          const SizedBox(height: 12),
          if (!connected) ...[
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF0A0A0F),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.white10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.account_balance, color: Colors.grey, size: 20),
                      SizedBox(width: 8),
                      Expanded(
                          child: Text("No payout account linked",
                              style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600))),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    "Set up Stripe Express to receive payouts directly to your bank account. Quick 2-minute process.",
                    style: TextStyle(color: Colors.grey[500], fontSize: 12),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFFFD700),
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(vertical: 12),
                      ),
                      onPressed:
                          _connectOnboarding ? null : _startConnectOnboarding,
                      icon: _connectOnboarding
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.black))
                          : const Icon(Icons.launch, size: 18),
                      label: Text(
                          _connectOnboarding ? "Opening..." : "Set Up Payouts"),
                    ),
                  ),
                ],
              ),
            ),
          ] else ...[
            // Connected — show status
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF0A0A0F),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                    color: payoutsEnabled
                        ? const Color(0xFF4ECDC4).withOpacity(0.3)
                        : Colors.orange.withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        payoutsEnabled ? Icons.check_circle : Icons.pending,
                        color: payoutsEnabled
                            ? const Color(0xFF4ECDC4)
                            : Colors.orange,
                        size: 20,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          payoutsEnabled
                              ? "Payouts Active"
                              : (detailsSubmitted
                                  ? "Verification Pending"
                                  : "Setup Incomplete"),
                          style: TextStyle(
                            color: payoutsEnabled
                                ? const Color(0xFF4ECDC4)
                                : Colors.orange,
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    payoutsEnabled
                        ? "Your bank account is connected and payouts are enabled."
                        : (detailsSubmitted
                            ? "Your details are submitted and under review by Stripe."
                            : "Please complete the Stripe onboarding to enable payouts."),
                    style: TextStyle(color: Colors.grey[500], fontSize: 12),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      if (!detailsSubmitted)
                        Expanded(
                          child: ElevatedButton.icon(
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.orange,
                              foregroundColor: Colors.white,
                              padding: const EdgeInsets.symmetric(vertical: 10),
                            ),
                            onPressed: _connectOnboarding
                                ? null
                                : _startConnectOnboarding,
                            icon: const Icon(Icons.launch, size: 16),
                            label: const Text("Complete Setup",
                                style: TextStyle(fontSize: 12)),
                          ),
                        ),
                      if (payoutsEnabled) ...[
                        Expanded(
                          child: ElevatedButton.icon(
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFF1A1A2E),
                              foregroundColor: const Color(0xFF4ECDC4),
                              side: const BorderSide(
                                  color: Color(0xFF4ECDC4), width: 1),
                              padding: const EdgeInsets.symmetric(vertical: 10),
                            ),
                            onPressed: _openConnectDashboard,
                            icon: const Icon(Icons.dashboard, size: 16),
                            label: const Text("Stripe Dashboard",
                                style: TextStyle(fontSize: 12)),
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  // =============================================================================
  // FINANCIALS TAB
  // =============================================================================

  Widget _buildFinancialsTab() {
    if (_financialsLoading) {
      return const Center(
          child: CircularProgressIndicator(color: Color(0xFFFFD700)));
    }

    final coachFee = (_financialData['coaching_fee'] is num)
        ? (_financialData['coaching_fee'] as num).toDouble()
        : 0.0;
    final paymentMode =
        (_financialData['payment_mode'] ?? 'coach_handles').toString();
    final earningsYtd = (_financialData['total_earnings_ytd'] is num)
        ? (_financialData['total_earnings_ytd'] as num).toDouble()
        : 0.0;
    final platformFeesYtd = (_financialData['total_platform_fees_ytd'] is num)
        ? (_financialData['total_platform_fees_ytd'] as num).toDouble()
        : 0.0;
    final netPayoutYtd = earningsYtd - platformFeesYtd;
    final sessionsBilled =
        (_financialData['total_sessions_billable'] ?? 0).toString();
    final w9Submitted = _financialData['w9_submitted'] == true;
    final requires1099 = _financialData['requires_1099'] == true;
    final ledger = (_financialData['ledger'] is List)
        ? List<Map<String, dynamic>>.from(_financialData['ledger'])
        : (_financialData['financial_ledger'] is List)
            ? List<Map<String, dynamic>>.from(
                _financialData['financial_ledger'])
            : <Map<String, dynamic>>[];

    // Monthly calculations
    final now = DateTime.now();
    final monthStr = '${now.year}-${now.month.toString().padLeft(2, '0')}';
    final monthlyTxns = ledger
        .where((t) => (t['date'] ?? '').toString().startsWith(monthStr))
        .toList();
    final earningsMonth = monthlyTxns.fold<double>(
        0.0,
        (sum, t) =>
            sum +
            ((t['coach_fee'] is num)
                ? (t['coach_fee'] as num).toDouble()
                : 0.0));
    final feesMonth = monthlyTxns.fold<double>(
        0.0,
        (sum, t) =>
            sum +
            ((t['platform_fee'] is num)
                ? (t['platform_fee'] as num).toDouble()
                : 0.0));

    return RefreshIndicator(
      onRefresh: () async => _requestFinancials(),
      color: const Color(0xFFFFD700),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // ===== SUMMARY CARDS =====
          const Text("EARNINGS OVERVIEW",
              style: TextStyle(
                  color: Color(0xFFFFD700),
                  fontFamily: 'Courier',
                  fontSize: 13,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1)),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                  child: _buildFinancialCard(
                      "This Month",
                      "\$${earningsMonth.toStringAsFixed(2)}",
                      Icons.calendar_month,
                      const Color(0xFF4ECDC4))),
              const SizedBox(width: 10),
              Expanded(
                  child: _buildFinancialCard(
                      "Year to Date",
                      "\$${earningsYtd.toStringAsFixed(2)}",
                      Icons.trending_up,
                      const Color(0xFFFFD700))),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                  child: _buildFinancialCard(
                      "Platform Fees (Month)",
                      "-\$${feesMonth.toStringAsFixed(2)}",
                      Icons.receipt_long,
                      Colors.redAccent)),
              const SizedBox(width: 10),
              Expanded(
                  child: _buildFinancialCard(
                      "Platform Fees (YTD)",
                      "-\$${platformFeesYtd.toStringAsFixed(2)}",
                      Icons.receipt,
                      Colors.redAccent)),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                  child: _buildFinancialCard(
                      "Net Payout (YTD)",
                      "\$${netPayoutYtd.toStringAsFixed(2)}",
                      Icons.account_balance_wallet,
                      const Color(0xFF4ECDC4))),
              const SizedBox(width: 10),
              Expanded(
                  child: _buildFinancialCard("Sessions Billed", sessionsBilled,
                      Icons.event_available, const Color(0xFF9D4EDD))),
            ],
          ),

          const SizedBox(height: 24),

          // ===== COACHING RATE =====
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A2E),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("MY COACHING RATE",
                    style: TextStyle(
                        color: Color(0xFFFFD700),
                        fontFamily: 'Courier',
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1)),
                const SizedBox(height: 12),
                Row(
                  children: [
                    const Text("\$",
                        style: TextStyle(
                            color: Color(0xFFFFD700),
                            fontSize: 24,
                            fontWeight: FontWeight.bold)),
                    const SizedBox(width: 4),
                    SizedBox(
                      width: 100,
                      child: TextField(
                        controller: _coachFeeController,
                        style: const TextStyle(
                            color: Colors.white,
                            fontSize: 24,
                            fontWeight: FontWeight.bold),
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                        decoration: InputDecoration(
                          hintText: "0.00",
                          hintStyle: TextStyle(color: Colors.grey[700]),
                          border: InputBorder.none,
                        ),
                      ),
                    ),
                    const Text(" / session",
                        style: TextStyle(color: Colors.grey, fontSize: 14)),
                    const Spacer(),
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFFFD700),
                        foregroundColor: Colors.black,
                        padding: const EdgeInsets.symmetric(
                            horizontal: 20, vertical: 10),
                      ),
                      onPressed: () {
                        final fee =
                            double.tryParse(_coachFeeController.text.trim());
                        if (fee != null && fee > 0) {
                          _setCoachFee(fee);
                        } else {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                                content:
                                    Text("Please enter a valid fee amount")),
                          );
                        }
                      },
                      child: const Text("Update Rate"),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  coachFee > 0
                      ? "Platform fee: \$${(coachFee * 0.30 < 30 ? 30.0 : coachFee * 0.30).toStringAsFixed(2)} (30%, min \$30) per approved session"
                      : "Set your rate to see fee breakdown",
                  style: TextStyle(color: Colors.grey[500], fontSize: 12),
                ),
              ],
            ),
          ),

          const SizedBox(height: 16),

          // ===== PAYMENT MODE =====
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A2E),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("PAYMENT MODE",
                    style: TextStyle(
                        color: Color(0xFFFFD700),
                        fontFamily: 'Courier',
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1)),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: GestureDetector(
                        onTap: () => _setPaymentMode('coach_handles'),
                        child: Container(
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: paymentMode == 'coach_handles'
                                ? const Color(0xFFFFD700).withOpacity(0.15)
                                : const Color(0xFF0A0A0F),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: paymentMode == 'coach_handles'
                                  ? const Color(0xFFFFD700)
                                  : Colors.white10,
                              width: paymentMode == 'coach_handles' ? 2 : 1,
                            ),
                          ),
                          child: Column(
                            children: [
                              Icon(Icons.person,
                                  color: paymentMode == 'coach_handles'
                                      ? const Color(0xFFFFD700)
                                      : Colors.grey,
                                  size: 28),
                              const SizedBox(height: 8),
                              Text("I Collect Payment",
                                  style: TextStyle(
                                      color: paymentMode == 'coach_handles'
                                          ? Colors.white
                                          : Colors.grey,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 13)),
                              const SizedBox(height: 4),
                              Text("You handle billing directly",
                                  style: TextStyle(
                                      color: Colors.grey[600], fontSize: 11),
                                  textAlign: TextAlign.center),
                            ],
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: GestureDetector(
                        onTap: () => _setPaymentMode('platform_handles'),
                        child: Container(
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: paymentMode == 'platform_handles'
                                ? const Color(0xFF4ECDC4).withOpacity(0.15)
                                : const Color(0xFF0A0A0F),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: paymentMode == 'platform_handles'
                                  ? const Color(0xFF4ECDC4)
                                  : Colors.white10,
                              width: paymentMode == 'platform_handles' ? 2 : 1,
                            ),
                          ),
                          child: Column(
                            children: [
                              Icon(Icons.account_balance,
                                  color: paymentMode == 'platform_handles'
                                      ? const Color(0xFF4ECDC4)
                                      : Colors.grey,
                                  size: 28),
                              const SizedBox(height: 8),
                              Text("Platform Handles",
                                  style: TextStyle(
                                      color: paymentMode == 'platform_handles'
                                          ? Colors.white
                                          : Colors.grey,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 13)),
                              const SizedBox(height: 4),
                              Text("We bill & disburse to you",
                                  style: TextStyle(
                                      color: Colors.grey[600], fontSize: 11),
                                  textAlign: TextAlign.center),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),

          const SizedBox(height: 24),

          // ===== PAYOUT SETTINGS (Stripe Connect) =====
          _buildPayoutSettingsSection(),

          const SizedBox(height: 24),

          // ===== DOJO SUBSCRIPTIONS =====
          _buildDojoSubscriptionsSection(),

          const SizedBox(height: 24),

          // ===== TRANSACTION LEDGER =====
          const Text("TRANSACTION LEDGER",
              style: TextStyle(
                  color: Color(0xFFFFD700),
                  fontFamily: 'Courier',
                  fontSize: 13,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1)),
          const SizedBox(height: 12),
          if (ledger.isEmpty)
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A2E),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Center(
                child: Text("No transactions yet",
                    style: TextStyle(color: Colors.grey)),
              ),
            )
          else
            ...ledger.reversed.take(50).map((txn) {
              final txnDate = (txn['date'] ?? '').toString();
              final clientName = (txn['client_name'] ?? '').toString();
              final gross = (txn['coach_fee'] is num)
                  ? (txn['coach_fee'] as num).toDouble()
                  : 0.0;
              final platFee = (txn['platform_fee'] is num)
                  ? (txn['platform_fee'] as num).toDouble()
                  : 0.0;
              final net = (txn['coach_payout'] is num)
                  ? (txn['coach_payout'] as num).toDouble()
                  : gross - platFee;
              final status = (txn['status'] ?? 'recorded').toString();

              return Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF1A1A2E),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white10),
                ),
                child: Row(
                  children: [
                    Expanded(
                      flex: 3,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(clientName.isEmpty ? "Session" : clientName,
                              style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.w600,
                                  fontSize: 13)),
                          const SizedBox(height: 2),
                          Text(txnDate,
                              style: TextStyle(
                                  color: Colors.grey[500], fontSize: 11)),
                        ],
                      ),
                    ),
                    Expanded(
                      flex: 2,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text("\$${gross.toStringAsFixed(2)}",
                              style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13)),
                          Text("-\$${platFee.toStringAsFixed(2)}",
                              style: const TextStyle(
                                  color: Colors.redAccent, fontSize: 11)),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      flex: 2,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text("\$${net.toStringAsFixed(2)}",
                              style: const TextStyle(
                                  color: Color(0xFF4ECDC4),
                                  fontWeight: FontWeight.bold,
                                  fontSize: 13)),
                          Text(
                            status.toUpperCase(),
                            style: TextStyle(
                              color: status == 'paid' || status == 'disbursed'
                                  ? const Color(0xFF4ECDC4)
                                  : Colors.grey,
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }).toList(),

          const SizedBox(height: 24),

          // ===== TAX DOCUMENTS =====
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A2E),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("TAX DOCUMENTS",
                    style: TextStyle(
                        color: Color(0xFFFFD700),
                        fontFamily: 'Courier',
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1)),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Icon(
                      w9Submitted ? Icons.check_circle : Icons.warning,
                      color:
                          w9Submitted ? const Color(0xFF4ECDC4) : Colors.orange,
                      size: 20,
                    ),
                    const SizedBox(width: 8),
                    Text(
                      w9Submitted ? "W-9 Submitted" : "W-9 Not Submitted",
                      style: TextStyle(
                          color: w9Submitted
                              ? const Color(0xFF4ECDC4)
                              : Colors.orange,
                          fontWeight: FontWeight.bold),
                    ),
                    const Spacer(),
                    OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: Color(0xFFFFD700)),
                        foregroundColor: const Color(0xFFFFD700),
                        padding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 8),
                      ),
                      onPressed: () => _showW9Dialog(),
                      child: Text(w9Submitted ? "Update W-9" : "Submit W-9"),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Icon(
                      requires1099
                          ? Icons.description
                          : Icons.description_outlined,
                      color:
                          requires1099 ? const Color(0xFFFFD700) : Colors.grey,
                      size: 20,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        requires1099
                            ? "1099-NEC: On track (YTD earnings \$${earningsYtd.toStringAsFixed(2)} >= \$600)"
                            : "1099-NEC: Not yet required (YTD earnings < \$600)",
                        style: TextStyle(
                            color: requires1099
                                ? const Color(0xFFFFD700)
                                : Colors.grey,
                            fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),

          const SizedBox(height: 40),
        ],
      ),
    );
  }

  Widget _buildDojoSubscriptionsSection() {
    const dojoLabels = {
      'therapist': 'Therapist',
      'project_pm': 'Project PM',
      'business': 'Business',
      'cnc': 'CNC',
      'mcat': 'MCAT',
      'teacher': 'Teacher',
      'judge': 'Judge',
      'coach_nate': 'Coach Nate',
    };
    const dojoPrices = {
      'therapist': 175.0,
      'project_pm': 250.0,
      'business': 325.0,
      'cnc': 150.0,
      'mcat': 500.0,
      'teacher': 225.0,
      'judge': 2100.0,
      'coach_nate': 90.0,
    };

    // Determine which dojos can be added (not currently active)
    final availableToAdd = <String>[];
    for (final key in dojoLabels.keys) {
      final sub = _dojoSubscriptions[key];
      if (sub == null || (sub is Map && sub['status'] != 'active')) {
        availableToAdd.add(key);
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "DOJO SUBSCRIPTIONS",
          style: TextStyle(
            color: Color(0xFFFFD700),
            fontFamily: 'Courier',
            fontSize: 13,
            fontWeight: FontWeight.bold,
            letterSpacing: 1,
          ),
        ),
        const SizedBox(height: 12),

        // Loading state
        if (_dojoSubsLoading)
          Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A2E),
              borderRadius: BorderRadius.circular(12),
            ),
            child: const Center(
              child: SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Color(0xFFFFD700)),
                ),
              ),
            ),
          )
        else ...[
          // Monthly total & discount summary
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFF4ECDC4).withOpacity(0.08),
              borderRadius: BorderRadius.circular(14),
              border:
                  Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.25)),
            ),
            child: Row(
              children: [
                const Icon(Icons.school, color: Color(0xFF4ECDC4), size: 22),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "\$${_dojoMonthlyPrice.toStringAsFixed(2)} / month",
                        style: const TextStyle(
                          color: Color(0xFF4ECDC4),
                          fontWeight: FontWeight.bold,
                          fontSize: 18,
                          fontFamily: 'Courier',
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        "${_dojoSubscriptions.values.where((s) => s is Map && s['status'] == 'active').length} active DOJO${_dojoSubscriptions.values.where((s) => s is Map && s['status'] == 'active').length == 1 ? '' : 's'}"
                        "${_dojoDiscountPct > 0 ? '  •  $_dojoDiscountPct% multi-DOJO discount' : ''}",
                        style: TextStyle(color: Colors.grey[400], fontSize: 11),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // Active & cancelled subscriptions
          if (_dojoSubscriptions.isEmpty)
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A2E),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Center(
                child: Text("No DOJO subscriptions yet",
                    style: TextStyle(color: Colors.grey)),
              ),
            )
          else
            ..._dojoSubscriptions.entries.map((entry) {
              final dojoKey = entry.key;
              final sub = (entry.value is Map)
                  ? Map<String, dynamic>.from(entry.value)
                  : <String, dynamic>{};
              final status = (sub['status'] ?? 'unknown').toString();
              final startDate = (sub['start_date'] ?? '').toString();
              final termEnd = (sub['term_end_date'] ?? '').toString();
              final monthlyRate = (sub['monthly_rate'] is num)
                  ? (sub['monthly_rate'] as num).toDouble()
                  : 0.0;
              final discountPct = (sub['discount_pct'] is num)
                  ? (sub['discount_pct'] as num).toInt()
                  : 0;
              final accessEnd = (sub['access_end_date'] ?? '').toString();
              final cancelDate =
                  (sub['cancellation_requested'] ?? '').toString();
              final label = dojoLabels[dojoKey] ?? dojoKey;

              final isActive = status == 'active';
              final isCancelled = status == 'cancelled';
              final isExpired = status == 'expired';

              final statusColor = isActive
                  ? const Color(0xFF4ECDC4)
                  : isCancelled
                      ? Colors.orange
                      : Colors.grey;

              final discountedRate = discountPct > 0
                  ? monthlyRate * (1 - discountPct / 100)
                  : monthlyRate;

              return Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF1A1A2E),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: isActive
                        ? const Color(0xFF4ECDC4).withOpacity(0.3)
                        : isCancelled
                            ? Colors.orange.withOpacity(0.3)
                            : Colors.white10,
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Header row: name, status, price
                    Row(
                      children: [
                        Icon(
                          isActive
                              ? Icons.check_circle
                              : isCancelled
                                  ? Icons.schedule
                                  : Icons.cancel,
                          color: statusColor,
                          size: 18,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            label,
                            style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold,
                              fontSize: 14,
                            ),
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: statusColor.withOpacity(0.15),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            status.toUpperCase(),
                            style: TextStyle(
                              color: statusColor,
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 0.5,
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            if (discountPct > 0) ...[
                              Text(
                                "\$${monthlyRate.toStringAsFixed(0)}",
                                style: const TextStyle(
                                  color: Colors.grey,
                                  fontSize: 11,
                                  decoration: TextDecoration.lineThrough,
                                ),
                              ),
                            ],
                            Text(
                              "\$${discountedRate.toStringAsFixed(2)}/mo",
                              style: TextStyle(
                                color: isExpired
                                    ? Colors.grey
                                    : const Color(0xFFFFD700),
                                fontWeight: FontWeight.bold,
                                fontSize: 13,
                                fontFamily: 'Courier',
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),

                    // Date info row
                    Wrap(
                      spacing: 16,
                      runSpacing: 4,
                      children: [
                        if (startDate.isNotEmpty)
                          Text("Started: $startDate",
                              style: TextStyle(
                                  color: Colors.grey[500], fontSize: 11)),
                        if (termEnd.isNotEmpty)
                          Text("Term ends: $termEnd",
                              style: TextStyle(
                                  color: Colors.grey[500], fontSize: 11)),
                        if (isCancelled && cancelDate.isNotEmpty)
                          Text("Cancelled: $cancelDate",
                              style: const TextStyle(
                                  color: Colors.orange, fontSize: 11)),
                        if (isCancelled && accessEnd.isNotEmpty)
                          Text("Access until: $accessEnd",
                              style: const TextStyle(
                                  color: Colors.orange,
                                  fontSize: 11,
                                  fontWeight: FontWeight.bold)),
                      ],
                    ),

                    // Cancel button for active subscriptions
                    if (isActive) ...[
                      const SizedBox(height: 10),
                      Align(
                        alignment: Alignment.centerRight,
                        child: TextButton.icon(
                          style: TextButton.styleFrom(
                            foregroundColor: Colors.redAccent,
                            padding: const EdgeInsets.symmetric(
                                horizontal: 12, vertical: 6),
                          ),
                          icon: const Icon(Icons.cancel_outlined, size: 16),
                          label: const Text("Cancel Subscription",
                              style: TextStyle(fontSize: 12)),
                          onPressed: () {
                            if (isNativeIOS) {
                              showDialog(
                                context: context,
                                builder: (ctx) => AlertDialog(
                                  backgroundColor: const Color(0xFF0A0A0F),
                                  title: Text("Cancel $label DOJO?",
                                      style: const TextStyle(
                                          color: Color(0xFFFFD700))),
                                  content: Text(
                                    "To cancel your $label DOJO subscription, go to:\n\n"
                                    "Settings > Apple ID > Subscriptions\n\n"
                                    "Find Sovereign Sanctuary and manage from there.",
                                    style: TextStyle(
                                        color: Colors.grey[400],
                                        fontSize: 13,
                                        height: 1.5),
                                  ),
                                  actions: [
                                    TextButton(
                                      onPressed: () => Navigator.pop(ctx),
                                      child: const Text("OK",
                                          style: TextStyle(
                                              color: Color(0xFFFFD700))),
                                    ),
                                  ],
                                ),
                              );
                            } else {
                              showDialog(
                                context: context,
                                builder: (ctx) => AlertDialog(
                                  backgroundColor: const Color(0xFF0A0A0F),
                                  title: Text("Cancel $label DOJO?",
                                      style: const TextStyle(
                                          color: Color(0xFFFFD700))),
                                  content: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      const Text(
                                        "30-day cancellation notice applies.",
                                        style: TextStyle(
                                            color: Colors.white,
                                            fontWeight: FontWeight.bold),
                                      ),
                                      const SizedBox(height: 8),
                                      Text(
                                        "You will retain access to the $label DOJO for 30 days after cancellation. "
                                        "Your multi-DOJO discount will be recalculated.",
                                        style: TextStyle(
                                            color: Colors.grey[400],
                                            fontSize: 13),
                                      ),
                                    ],
                                  ),
                                  actions: [
                                    TextButton(
                                      onPressed: () => Navigator.pop(ctx),
                                      child: const Text("Keep Subscription",
                                          style: TextStyle(color: Colors.grey)),
                                    ),
                                    ElevatedButton(
                                      style: ElevatedButton.styleFrom(
                                        backgroundColor: Colors.redAccent,
                                      ),
                                      onPressed: () {
                                        Navigator.pop(ctx);
                                        _cancelDojoSubscription(dojoKey);
                                      },
                                      child: const Text("Confirm Cancel"),
                                    ),
                                  ],
                                ),
                              );
                            }
                          },
                        ),
                      ),
                    ],
                  ],
                ),
              );
            }).toList(),

          // Add DOJO button
          if (availableToAdd.isNotEmpty) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: const Color(0xFF4ECDC4),
                  side: const BorderSide(color: Color(0xFF4ECDC4), width: 1),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12)),
                ),
                icon: const Icon(Icons.add_circle_outline, size: 20),
                label: const Text("Add DOJO Subscription",
                    style:
                        TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
                onPressed: () =>
                    _showAddDojoDialog(availableToAdd, dojoLabels, dojoPrices),
              ),
            ),
          ],

          // Policy text
          const SizedBox(height: 14),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFFFD700).withOpacity(0.05),
              borderRadius: BorderRadius.circular(10),
              border:
                  Border.all(color: const Color(0xFFFFD700).withOpacity(0.15)),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline, color: Colors.grey[600], size: 16),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    "12-month subscription term. 30-day cancellation notice required. "
                    "You retain access through your current billing cycle. "
                    "Multi-DOJO discounts recalculate automatically.",
                    style: TextStyle(
                        color: Colors.grey[500], fontSize: 11, height: 1.4),
                  ),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  void _showAddDojoDialog(List<String> availableKeys,
      Map<String, String> labels, Map<String, double> prices) {
    // Calculate what discount would apply with one more
    final currentActive = _dojoSubscriptions.values
        .where((s) => s is Map && s['status'] == 'active')
        .length;
    final discounts = [0, 0, 10, 15, 20, 25, 30];

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF0A0A0F),
        title: const Text("Add DOJO Subscription",
            style: TextStyle(color: Color(0xFFFFD700))),
        content: SizedBox(
          width: 400,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  "Select a DOJO to subscribe to. Each adds a 12-month term.",
                  style: TextStyle(color: Colors.grey[400], fontSize: 13),
                ),
                const SizedBox(height: 16),
                ...availableKeys.map((key) {
                  final label = labels[key] ?? key;
                  final price = prices[key] ?? 0.0;
                  final newCount = currentActive + 1;
                  final newDiscount = discounts[newCount.clamp(0, 6)];
                  final discountedPrice = price * (1 - newDiscount / 100);

                  return Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: Material(
                      color: const Color(0xFF1A1A2E),
                      borderRadius: BorderRadius.circular(10),
                      child: InkWell(
                        borderRadius: BorderRadius.circular(10),
                        onTap: () {
                          Navigator.pop(ctx);
                          // Confirm before adding
                          showDialog(
                            context: context,
                            builder: (ctx2) => AlertDialog(
                              backgroundColor: const Color(0xFF0A0A0F),
                              title: Text("Subscribe to $label DOJO?",
                                  style: const TextStyle(
                                      color: Color(0xFFFFD700))),
                              content: Column(
                                mainAxisSize: MainAxisSize.min,
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    "12-month commitment at \$${price.toStringAsFixed(0)}/month"
                                    "${newDiscount > 0 ? ' ($newDiscount% discount = \$${discountedPrice.toStringAsFixed(2)}/mo)' : ''}",
                                    style: const TextStyle(
                                        color: Colors.white, fontSize: 14),
                                  ),
                                  const SizedBox(height: 8),
                                  Text(
                                    "30-day cancellation notice required.",
                                    style: TextStyle(
                                        color: Colors.grey[400], fontSize: 13),
                                  ),
                                ],
                              ),
                              actions: [
                                TextButton(
                                  onPressed: () => Navigator.pop(ctx2),
                                  child: const Text("Cancel",
                                      style: TextStyle(color: Colors.grey)),
                                ),
                                ElevatedButton(
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: const Color(0xFF4ECDC4),
                                    foregroundColor: Colors.black,
                                  ),
                                  onPressed: () {
                                    Navigator.pop(ctx2);
                                    _addDojoSubscription(key);
                                  },
                                  child: const Text("Subscribe"),
                                ),
                              ],
                            ),
                          );
                        },
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Row(
                            children: [
                              const Icon(Icons.school,
                                  color: Color(0xFF4ECDC4), size: 20),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(label,
                                        style: const TextStyle(
                                            color: Colors.white,
                                            fontWeight: FontWeight.bold,
                                            fontSize: 14)),
                                    const SizedBox(height: 2),
                                    Text(
                                      "\$${price.toStringAsFixed(0)}/mo"
                                      "${newDiscount > 0 ? '  →  \$${discountedPrice.toStringAsFixed(2)}/mo with $newDiscount% discount' : ''}",
                                      style: TextStyle(
                                          color: Colors.grey[400],
                                          fontSize: 11),
                                    ),
                                  ],
                                ),
                              ),
                              const Icon(Icons.arrow_forward_ios,
                                  color: Colors.grey, size: 14),
                            ],
                          ),
                        ),
                      ),
                    ),
                  );
                }).toList(),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Close", style: TextStyle(color: Colors.grey)),
          ),
        ],
      ),
    );
  }

  Widget _buildFinancialCard(
      String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withOpacity(0.08),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withOpacity(0.25)),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 22),
          const SizedBox(height: 6),
          Text(
            value,
            style: TextStyle(
                color: color,
                fontWeight: FontWeight.bold,
                fontSize: 18,
                fontFamily: 'Courier'),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 2),
          Text(label,
              style: TextStyle(color: Colors.grey[400], fontSize: 10),
              textAlign: TextAlign.center),
        ],
      ),
    );
  }

  void _showW9Dialog() {
    final legalNameCtrl = TextEditingController();
    final businessNameCtrl = TextEditingController();
    final streetCtrl = TextEditingController();
    final cityCtrl = TextEditingController();
    final stateCtrl = TextEditingController();
    final zipCtrl = TextEditingController();
    final tinCtrl = TextEditingController();
    final signatureCtrl = TextEditingController();
    String taxClass = 'individual';
    bool certified = false;

    // Pre-fill from existing W-9 data
    final existingW9 = (_financialData['w9_data'] is Map)
        ? Map<String, dynamic>.from(_financialData['w9_data'])
        : <String, dynamic>{};
    if (existingW9.isNotEmpty) {
      legalNameCtrl.text = (existingW9['legal_name'] ?? '').toString();
      businessNameCtrl.text = (existingW9['business_name'] ?? '').toString();
      streetCtrl.text = (existingW9['street'] ?? '').toString();
      cityCtrl.text = (existingW9['city'] ?? '').toString();
      stateCtrl.text = (existingW9['state'] ?? '').toString();
      zipCtrl.text = (existingW9['zip'] ?? '').toString();
      taxClass = (existingW9['tax_classification'] ?? 'individual').toString();
    }

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: const Color(0xFF0A0A0F),
          title: const Text("W-9 Tax Information",
              style: TextStyle(color: Color(0xFFFFD700))),
          content: SizedBox(
            width: 500,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text("Legal Name (as shown on tax return)",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 4),
                  _buildW9Field(legalNameCtrl, "Full legal name"),
                  const SizedBox(height: 12),
                  const Text("Business Name (if different)",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 4),
                  _buildW9Field(businessNameCtrl, "Business or DBA name"),
                  const SizedBox(height: 12),
                  const Text("Tax Classification",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 8,
                    children: [
                      _buildTaxClassChip(
                          'individual',
                          'Individual / Sole Proprietor',
                          taxClass,
                          (v) => setDialogState(() => taxClass = v)),
                      _buildTaxClassChip('llc', 'LLC', taxClass,
                          (v) => setDialogState(() => taxClass = v)),
                      _buildTaxClassChip('corporation', 'Corporation', taxClass,
                          (v) => setDialogState(() => taxClass = v)),
                      _buildTaxClassChip('partnership', 'Partnership', taxClass,
                          (v) => setDialogState(() => taxClass = v)),
                    ],
                  ),
                  const SizedBox(height: 12),
                  const Text("Address",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 4),
                  _buildW9Field(streetCtrl, "Street address"),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(flex: 3, child: _buildW9Field(cityCtrl, "City")),
                      const SizedBox(width: 8),
                      Expanded(
                          flex: 1, child: _buildW9Field(stateCtrl, "State")),
                      const SizedBox(width: 8),
                      Expanded(flex: 2, child: _buildW9Field(zipCtrl, "ZIP")),
                    ],
                  ),
                  const SizedBox(height: 12),
                  const Text("Taxpayer ID (SSN or EIN)",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 4),
                  _buildW9Field(tinCtrl, "XXX-XX-XXXX", obscure: true),
                  const SizedBox(height: 16),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Checkbox(
                        value: certified,
                        onChanged: (v) =>
                            setDialogState(() => certified = v ?? false),
                        activeColor: const Color(0xFFFFD700),
                      ),
                      Expanded(
                        child: Text(
                          "Under penalties of perjury, I certify that the information provided is correct and I am a U.S. person.",
                          style:
                              TextStyle(color: Colors.grey[400], fontSize: 11),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  const Text("Electronic Signature",
                      style: TextStyle(color: Colors.white70, fontSize: 12)),
                  const SizedBox(height: 4),
                  _buildW9Field(signatureCtrl, "Type your full name"),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFFFFD700),
                  foregroundColor: Colors.black),
              onPressed: () {
                if (legalNameCtrl.text.trim().isEmpty ||
                    tinCtrl.text.trim().isEmpty ||
                    !certified ||
                    signatureCtrl.text.trim().isEmpty) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                        content: Text(
                            "Please fill all required fields, certify, and sign")),
                  );
                  return;
                }
                Navigator.pop(ctx);
                _submitW9({
                  "legal_name": legalNameCtrl.text.trim(),
                  "business_name": businessNameCtrl.text.trim(),
                  "tax_classification": taxClass,
                  "street": streetCtrl.text.trim(),
                  "city": cityCtrl.text.trim(),
                  "state": stateCtrl.text.trim(),
                  "zip": zipCtrl.text.trim(),
                  "tin": tinCtrl.text.trim(),
                  "certified": true,
                  "signature": signatureCtrl.text.trim(),
                  "signed_date": DateTime.now().toIso8601String(),
                });
              },
              child: const Text("Submit W-9"),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildW9Field(TextEditingController controller, String hint,
      {bool obscure = false}) {
    return TextField(
      controller: controller,
      obscureText: obscure,
      style: const TextStyle(color: Colors.white, fontSize: 14),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: TextStyle(color: Colors.grey[700]),
        filled: true,
        fillColor: const Color(0xFF111111),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: BorderSide.none),
      ),
    );
  }

  Widget _buildTaxClassChip(
      String value, String label, String selected, Function(String) onSelect) {
    final isSelected = selected == value;
    return GestureDetector(
      onTap: () => onSelect(value),
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected
              ? const Color(0xFFFFD700).withOpacity(0.15)
              : const Color(0xFF111111),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
              color: isSelected ? const Color(0xFFFFD700) : Colors.white10),
        ),
        child: Text(label,
            style: TextStyle(
                color: isSelected ? const Color(0xFFFFD700) : Colors.grey,
                fontSize: 12)),
      ),
    );
  }

  void _sendMessage(dynamic msg) {
    if (msg is String) {
      _socket?.sink.add(msg);
    } else {
      _socket?.sink.add(jsonEncode(msg));
    }
  }

  // ===========================================================================
  // FOLDER TAB — File storage & form templates
  // ===========================================================================

  List<Map<String, dynamic>> _coachFolderList = [];
  List<Map<String, dynamic>> _coachFolderFiles = [];
  String? _coachActiveFolderId;
  String? _coachActiveFolderName;
  bool _coachFoldersLoading = false;

  Widget _buildFolderTab() {
    return RefreshIndicator(
      onRefresh: () async => _coachFetchFolders(),
      color: const Color(0xFFFFD700),
      child: _coachFoldersLoading
          ? const Center(
              child: CircularProgressIndicator(color: Color(0xFFFFD700)))
          : _coachActiveFolderId != null
              ? _buildCoachFolderDetail()
              : _buildCoachFolderList(),
    );
  }

  Widget _buildCoachFolderList() {
    if (_coachFolderList.isEmpty && !_coachFoldersLoading) {
      _coachFetchFolders();
    }

    final personal =
        _coachFolderList.where((f) => f['folder_type'] == 'personal').toList();
    final clients =
        _coachFolderList.where((f) => f['folder_type'] == 'client').toList();
    final families =
        _coachFolderList.where((f) => f['folder_type'] == 'family').toList();
    final groups =
        _coachFolderList.where((f) => f['folder_type'] == 'group').toList();
    final companies =
        _coachFolderList.where((f) => f['folder_type'] == 'company').toList();

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text("FILE MANAGER",
                style: TextStyle(
                    color: Color(0xFFFFD700),
                    fontFamily: 'Courier',
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 2)),
            IconButton(
              icon: const Icon(Icons.create_new_folder,
                  color: Color(0xFFC9A962), size: 20),
              tooltip: "New Folder",
              onPressed: _coachCreateFolder,
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (personal.isNotEmpty) ...[
          _buildCoachFolderSection("MY FILES", Icons.person, personal),
          const SizedBox(height: 16),
        ],
        if (clients.isNotEmpty) ...[
          _buildCoachFolderSection("CLIENT FOLDERS", Icons.people, clients),
          const SizedBox(height: 16),
        ],
        if (families.isNotEmpty) ...[
          _buildCoachFolderSection(
              "FAMILY FOLDERS", Icons.family_restroom, families),
          const SizedBox(height: 16),
        ],
        if (groups.isNotEmpty) ...[
          _buildCoachFolderSection("GROUP FOLDERS", Icons.groups, groups),
          const SizedBox(height: 16),
        ],
        if (companies.isNotEmpty) ...[
          _buildCoachFolderSection(
              "COMPANY FOLDERS", Icons.business, companies),
        ],
        if (_coachFolderList.isEmpty)
          Center(
            child: Padding(
              padding: const EdgeInsets.all(40),
              child: Column(children: [
                Icon(Icons.folder_open, color: Colors.grey[600], size: 48),
                const SizedBox(height: 12),
                Text("No folders yet",
                    style: TextStyle(color: Colors.grey[500], fontSize: 14)),
                const SizedBox(height: 4),
                Text("Folders auto-populate from your assigned clients",
                    style: TextStyle(color: Colors.grey[600], fontSize: 12)),
              ]),
            ),
          ),
      ],
    );
  }

  Widget _buildCoachFolderSection(
      String title, IconData icon, List<Map<String, dynamic>> folders) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          Icon(icon, color: const Color(0xFF8B7355), size: 16),
          const SizedBox(width: 8),
          Text(title,
              style: const TextStyle(
                  color: Color(0xFF8B7355),
                  fontFamily: 'Courier',
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1)),
          const SizedBox(width: 8),
          Text("(${folders.length})",
              style: TextStyle(color: Colors.grey[600], fontSize: 11)),
        ]),
        const SizedBox(height: 8),
        ...folders.map((f) => _buildCoachFolderCard(f)),
      ],
    );
  }

  Widget _buildCoachFolderCard(Map<String, dynamic> folder) {
    final name = folder['entity_name'] ?? folder['entity_id'] ?? 'Unnamed';
    final type = folder['folder_type'] ?? '';
    final typeIcons = {
      'personal': Icons.person,
      'client': Icons.person_outline,
      'family': Icons.family_restroom,
      'group': Icons.groups,
      'company': Icons.business,
    };

    return GestureDetector(
      onTap: () {
        setState(() {
          _coachActiveFolderId = folder['id'];
          _coachActiveFolderName = name;
          _coachFolderFiles = [];
        });
        _coachFetchFolderFiles(folder['id']);
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFF222222)),
        ),
        child: Row(
          children: [
            Icon(typeIcons[type] ?? Icons.folder,
                color: const Color(0xFFC9A962), size: 20),
            const SizedBox(width: 12),
            Expanded(
              child: Text(name,
                  style: const TextStyle(color: Colors.white, fontSize: 14)),
            ),
            const Icon(Icons.chevron_right, color: Colors.grey, size: 18),
          ],
        ),
      ),
    );
  }

  bool _coachFileUploading = false;
  String? _coachUploadFileName;
  String? _coachUploadError;
  bool _coachUploadSuccess = false;

  Widget _buildCoachFolderDetail() {
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          color: const Color(0xFF0D0D0D),
          child: Row(
            children: [
              GestureDetector(
                onTap: () => setState(() {
                  _coachActiveFolderId = null;
                  _coachActiveFolderName = null;
                }),
                child: const Row(children: [
                  Icon(Icons.arrow_back, color: Color(0xFFC9A962), size: 18),
                  SizedBox(width: 6),
                  Text("Back",
                      style: TextStyle(color: Color(0xFFC9A962), fontSize: 13)),
                ]),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(_coachActiveFolderName ?? "Folder",
                    style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 14)),
              ),
              InkWell(
                onTap: _coachFileUploading ? null : _coachPickAndUploadFile,
                borderRadius: BorderRadius.circular(6),
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: const Color(0xFFC9A962).withOpacity(0.15),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(
                        color: const Color(0xFFC9A962).withOpacity(0.4)),
                  ),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(
                        _coachFileUploading
                            ? Icons.hourglass_top
                            : Icons.upload_file,
                        color: const Color(0xFFC9A962),
                        size: 16),
                    const SizedBox(width: 4),
                    Text(_coachFileUploading ? "Uploading..." : "Upload",
                        style: const TextStyle(
                            color: Color(0xFFC9A962),
                            fontSize: 12,
                            fontWeight: FontWeight.w600)),
                  ]),
                ),
              ),
            ],
          ),
        ),
        if (_coachFileUploading && _coachUploadFileName != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: const Color(0xFF0A0A0A),
            child: Row(children: [
              const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: Color(0xFF4ECDC4))),
              const SizedBox(width: 10),
              Expanded(
                  child: Text("Uploading ${_coachUploadFileName!}...",
                      style: const TextStyle(
                          color: Color(0xFF4ECDC4), fontSize: 12))),
            ]),
          ),
        if (_coachUploadSuccess)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: const Color(0xFF0A0A0A),
            child: Row(children: [
              const Icon(Icons.check_circle,
                  color: Color(0xFF22C55E), size: 16),
              const SizedBox(width: 10),
              const Expanded(
                  child: Text("File uploaded successfully",
                      style:
                          TextStyle(color: Color(0xFF22C55E), fontSize: 12))),
              IconButton(
                  icon: const Icon(Icons.close, size: 14, color: Colors.grey),
                  onPressed: () => setState(() => _coachUploadSuccess = false)),
            ]),
          ),
        if (_coachUploadError != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            color: const Color(0xFF0A0A0A),
            child: Row(children: [
              const Icon(Icons.error, color: Color(0xFFEF4444), size: 16),
              const SizedBox(width: 10),
              Expanded(
                  child: Text(_coachUploadError!,
                      style: const TextStyle(
                          color: Color(0xFFEF4444), fontSize: 12))),
              IconButton(
                  icon: const Icon(Icons.close, size: 14, color: Colors.grey),
                  onPressed: () => setState(() => _coachUploadError = null)),
            ]),
          ),
        Expanded(
          child: _coachFolderFiles.isEmpty
              ? Center(
                  child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.insert_drive_file,
                            color: Colors.grey[700], size: 40),
                        const SizedBox(height: 8),
                        Text("No files yet",
                            style: TextStyle(
                                color: Colors.grey[500], fontSize: 13)),
                        const SizedBox(height: 16),
                        ElevatedButton.icon(
                          icon: const Icon(Icons.upload_file, size: 16),
                          label: const Text("Upload a File"),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: const Color(0xFFC9A962),
                            foregroundColor: Colors.black,
                            padding: const EdgeInsets.symmetric(
                                horizontal: 20, vertical: 10),
                          ),
                          onPressed: _coachFileUploading
                              ? null
                              : _coachPickAndUploadFile,
                        ),
                      ]),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(12),
                  itemCount: _coachFolderFiles.length,
                  itemBuilder: (context, index) {
                    final file = _coachFolderFiles[index];
                    final filename = file['filename'] ?? 'Unknown';
                    final fileType = file['file_type'] ?? 'document';
                    final created = file['created_at'] ?? '';
                    final fileId = file['id'] ?? '';
                    final sizeBytes = file['file_size_bytes'] ?? 0;

                    final typeIcon = fileType.contains('pdf')
                        ? Icons.picture_as_pdf
                        : fileType.contains('xls') ||
                                fileType.contains('spread')
                            ? Icons.table_chart
                            : fileType.contains('image')
                                ? Icons.image
                                : Icons.insert_drive_file;

                    String sizeStr = '';
                    if (sizeBytes > 0) {
                      if (sizeBytes > 1024 * 1024) {
                        sizeStr =
                            '${(sizeBytes / (1024 * 1024)).toStringAsFixed(1)} MB';
                      } else if (sizeBytes > 1024) {
                        sizeStr = '${(sizeBytes / 1024).toStringAsFixed(0)} KB';
                      } else {
                        sizeStr = '$sizeBytes B';
                      }
                    }

                    return Container(
                      margin: const EdgeInsets.only(bottom: 6),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: const Color(0xFF111111),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: const Color(0xFF222222)),
                      ),
                      child: Row(children: [
                        Icon(typeIcon,
                            color: const Color(0xFF4ECDC4), size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(filename,
                                    style: const TextStyle(
                                        color: Colors.white, fontSize: 13)),
                                Row(children: [
                                  if (created.isNotEmpty)
                                    Text(created.toString().substring(0, 10),
                                        style: TextStyle(
                                            color: Colors.grey[600],
                                            fontSize: 11)),
                                  if (sizeStr.isNotEmpty) ...[
                                    Text('  ·  ',
                                        style: TextStyle(
                                            color: Colors.grey[700],
                                            fontSize: 11)),
                                    Text(sizeStr,
                                        style: TextStyle(
                                            color: Colors.grey[600],
                                            fontSize: 11)),
                                  ],
                                ]),
                              ]),
                        ),
                        PopupMenuButton<String>(
                          icon: Icon(Icons.more_vert,
                              color: Colors.grey[600], size: 18),
                          color: const Color(0xFF1A1A1A),
                          onSelected: (val) {
                            if (val == 'delete') _coachDeleteFile(fileId);
                          },
                          itemBuilder: (ctx) => [
                            const PopupMenuItem(
                                value: 'delete',
                                child: Text('Delete',
                                    style: TextStyle(
                                        color: Color(0xFFEF4444),
                                        fontSize: 13))),
                          ],
                        ),
                      ]),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Future<void> _coachPickAndUploadFile() async {
    if (_coachActiveFolderId == null) return;
    try {
      final result = await FilePicker.platform.pickFiles(allowMultiple: false);
      if (result == null || result.files.isEmpty) return;
      final file = result.files.single;
      final bytes = file.bytes;
      if (bytes == null && file.path == null) return;

      final fileName = file.name;
      setState(() {
        _coachFileUploading = true;
        _coachUploadFileName = fileName;
        _coachUploadError = null;
        _coachUploadSuccess = false;
      });

      final token =
          _authToken ?? widget.currentUserProfile?['token']?.toString() ?? '';
      final baseUrl = AppConfig.apiBaseUrl;
      final uri = Uri.parse('$baseUrl/api/coach/folders/upload');
      final request = http.MultipartRequest('POST', uri);
      request.headers['Authorization'] = 'Bearer $token';
      request.fields['folder_id'] = _coachActiveFolderId!;

      final data = bytes ?? (await File(file.path!).readAsBytes());
      request.files
          .add(http.MultipartFile.fromBytes('file', data, filename: fileName));

      final streamedResp =
          await request.send().timeout(const Duration(seconds: 120));
      final respBody = await streamedResp.stream.bytesToString();

      if (!mounted) return;
      if (streamedResp.statusCode == 200) {
        setState(() {
          _coachFileUploading = false;
          _coachUploadFileName = null;
          _coachUploadSuccess = true;
        });
        _coachFetchFolderFiles(_coachActiveFolderId!);
        Future.delayed(const Duration(seconds: 3), () {
          if (mounted) setState(() => _coachUploadSuccess = false);
        });
      } else {
        String errMsg = 'Upload failed (${streamedResp.statusCode})';
        try {
          final errData = json.decode(respBody);
          errMsg = errData['detail'] ?? errMsg;
        } catch (_) {}
        setState(() {
          _coachFileUploading = false;
          _coachUploadFileName = null;
          _coachUploadError = errMsg;
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _coachFileUploading = false;
        _coachUploadFileName = null;
        _coachUploadError = 'Upload error: $e';
      });
    }
  }

  void _coachDeleteFile(String fileId) {
    final token =
        _authToken ?? widget.currentUserProfile?['token']?.toString() ?? '';
    if (token.isEmpty || _coachActiveFolderId == null) return;
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Delete File?",
            style: TextStyle(color: Color(0xFFEF4444), fontSize: 16)),
        content: const Text("This cannot be undone.",
            style: TextStyle(color: Colors.white70, fontSize: 13)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Cancel",
                  style: TextStyle(color: Colors.white54))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFEF4444)),
            onPressed: () {
              Navigator.pop(ctx);
              final baseUrl = AppConfig.apiBaseUrl;
              final url = Uri.parse('$baseUrl/api/coach/folders/files/$fileId');
              http.delete(url,
                  headers: {'Authorization': 'Bearer $token'}).then((resp) {
                if (resp.statusCode == 200 && mounted) {
                  _coachFetchFolderFiles(_coachActiveFolderId!);
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                        content: Text("File deleted"),
                        backgroundColor: Colors.green),
                  );
                }
              });
            },
            child: const Text("Delete"),
          ),
        ],
      ),
    );
  }

  void _coachFetchFolders() {
    final token =
        _authToken ?? widget.currentUserProfile?['token']?.toString() ?? '';
    if (token.isEmpty) return;
    setState(() => _coachFoldersLoading = true);

    final baseUrl = AppConfig.apiBaseUrl;
    final url = Uri.parse('$baseUrl/api/coach/folders');
    http.get(url, headers: {'Authorization': 'Bearer $token'}).then((resp) {
      if (resp.statusCode == 200 && mounted) {
        try {
          final data = json.decode(resp.body);
          setState(() {
            _coachFolderList =
                List<Map<String, dynamic>>.from(data['folders'] ?? []);
            _coachFoldersLoading = false;
          });
        } catch (_) {
          if (mounted) setState(() => _coachFoldersLoading = false);
        }
      } else if (mounted) {
        setState(() => _coachFoldersLoading = false);
      }
    }).catchError((_) {
      if (mounted) setState(() => _coachFoldersLoading = false);
    });
  }

  void _coachFetchFolderFiles(String folderId) {
    final token =
        _authToken ?? widget.currentUserProfile?['token']?.toString() ?? '';
    if (token.isEmpty) return;

    final baseUrl = AppConfig.apiBaseUrl;
    final url = Uri.parse('$baseUrl/api/coach/folders/$folderId/files');
    http.get(url, headers: {'Authorization': 'Bearer $token'}).then((resp) {
      if (resp.statusCode == 200 && mounted) {
        try {
          final data = json.decode(resp.body);
          setState(() {
            _coachFolderFiles =
                List<Map<String, dynamic>>.from(data['files'] ?? []);
          });
        } catch (_) {}
      }
    }).catchError((_) {});
  }

  void _coachCreateFolder() {
    final nameCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Create Folder",
            style: TextStyle(color: Color(0xFFFFD700), fontSize: 16)),
        content: TextField(
          controller: nameCtrl,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            labelText: "Folder Name",
            labelStyle: TextStyle(color: Colors.grey),
            enabledBorder: UnderlineInputBorder(
                borderSide: BorderSide(color: Colors.grey)),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFC9A962)),
            onPressed: () {
              Navigator.pop(ctx);
              final name = nameCtrl.text.trim();
              if (name.isEmpty) return;
              final token = _authToken ??
                  widget.currentUserProfile?['token']?.toString() ??
                  '';
              if (token.isEmpty) return;
              final baseUrl = AppConfig.apiBaseUrl;
              final url = Uri.parse('$baseUrl/api/coach/folders/create');
              http
                  .post(url,
                      headers: {
                        'Authorization': 'Bearer $token',
                        'Content-Type': 'application/json'
                      },
                      body: json.encode(
                          {'folder_type': 'personal', 'entity_name': name}))
                  .then((resp) {
                if (resp.statusCode == 200 && mounted) _coachFetchFolders();
              }).catchError((_) {});
            },
            child: const Text("Create", style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// ADMIN DASHBOARD - NEW SCREEN
// Add this as a new class in main.dart
// =============================================================================

class AdminDashboardScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final String username;
  final String password;

  const AdminDashboardScreen({
    super.key,
    required this.currentUserProfile,
    required this.username,
    required this.password,
  });

  @override
  _AdminDashboardScreenState createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen>
    with SingleTickerProviderStateMixin {
  WebSocketChannel? _socket;
  final String _serverUrl = defaultWsUrl;

  Map<String, dynamic> _stats = {};
  List<dynamic> _users = [];
  List<dynamic> _crisisWatchlist = [];
  List<dynamic> _pendingCoaches = [];
  List<dynamic> _pendingUpgrades = [];
  List<dynamic> _pendingSearches = [];
  List<dynamic> _pendingStudents = [];
  List<dynamic> _coachLearningItems = [];
  String _coachLearningStatus = "PENDING";
  bool _coachLearningLoading = false;
  bool _isLoading = true;
  String _statusMessage = "Initializing...";
  int _wsReconnectAttempts = 0;
  Timer? _wsReconnectTimer;

  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 5, vsync: this);
    _connectToBridge();
  }

  void _connectToBridge() {
    setState(() => _statusMessage = "Connecting to Command Center...");

    try {
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));

      // FIX-H: NOT ClientWsHub — admin MAIN_CONTEXT WS is separate from client `_ClientWsHub` singleton.
      _socket!.stream.listen(
        _handleSocketMessage,
        onError: (e) {
          if (mounted) setState(() => _statusMessage = "Connection Failed");
          _scheduleWsReconnect();
        },
        onDone: () {
          if (mounted)
            setState(() => _statusMessage = "Disconnected — reconnecting...");
          _scheduleWsReconnect();
        },
        cancelOnError: true,
      );

      _socket!.sink.add(jsonEncode({
        "type": "login_request",
        "username": widget.username,
        "password": widget.password,
        "expected_role": "ADMIN"
      }));
    } catch (e) {
      _debugLog("Fatal Connection Error: $e");
      _scheduleWsReconnect();
    }
  }

  void _scheduleWsReconnect() {
    _wsReconnectTimer?.cancel();
    final attempt = _wsReconnectAttempts.clamp(0, 10);
    final baseMs = (1000 * (1 << attempt)).clamp(1000, 30000);
    final jitterMs =
        (baseMs * 0.2 * (DateTime.now().millisecondsSinceEpoch % 100) / 100)
            .toInt();
    _wsReconnectAttempts++;
    _wsReconnectTimer = Timer(Duration(milliseconds: baseMs + jitterMs), () {
      if (!mounted) return;
      _debugLog(
          "Admin WS reconnect attempt $_wsReconnectAttempts (delay ${baseMs + jitterMs}ms)");
      _connectToBridge();
    });
  }

  void _fetchDashboard() {
    _socket?.sink.add(jsonEncode({"type": "admin_get_stats"}));
    _socket?.sink.add(jsonEncode({"type": "admin_get_users"}));
    _socket?.sink.add(jsonEncode({"type": "admin_get_crisis_watchlist"}));
    _socket?.sink.add(jsonEncode({"type": "admin_get_pending_coaches"}));
    _socket?.sink.add(jsonEncode({"type": "admin_get_pending_upgrades"}));
    _socket?.sink.add(jsonEncode({"type": "admin_get_pending_searches"}));
    _socket?.sink.add(jsonEncode({"type": "admin_get_pending_students"}));
    _fetchCoachLearningQueue(status: _coachLearningStatus);
  }

  void _fetchCoachLearningQueue({String status = "PENDING"}) {
    if (mounted) setState(() => _coachLearningLoading = true);
    _socket?.sink.add(jsonEncode(
        {"type": "admin_get_coach_learning_queue", "status": status}));
  }

  void _approveCoachLearning(String queueId, {String editedContent = ""}) {
    _socket?.sink.add(jsonEncode({
      "type": "admin_approve_coach_learning",
      "queue_id": queueId,
      "edited_content": editedContent,
    }));
  }

  void _rejectCoachLearning(String queueId, {String reason = ""}) {
    _socket?.sink.add(jsonEncode({
      "type": "admin_reject_coach_learning",
      "queue_id": queueId,
      "reason": reason,
    }));
  }

  void _handleSocketMessage(dynamic message) {
    try {
      final data = jsonDecode(message);

      if (data['type'] == 'login_success') {
        _wsReconnectAttempts = 0;
        _fetchDashboard();
      } else if (data['type'] == 'admin_stats') {
        setState(() {
          _stats = data['stats'] ?? {};
          _isLoading = false;
        });
      } else if (data['type'] == 'admin_users') {
        setState(() => _users = data['users'] ?? []);
      } else if (data['type'] == 'crisis_watchlist') {
        setState(() => _crisisWatchlist = data['watchlist'] ?? []);
      } else if (data['type'] == 'pending_coaches') {
        setState(() => _pendingCoaches = data['coaches'] ?? []);
      } else if (data['type'] == 'coach_approved') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Coach approved successfully"),
              backgroundColor: Color(0xFF00F5D4)),
        );
        _fetchDashboard();
      } else if (data['type'] == 'pending_upgrades') {
        setState(() => _pendingUpgrades = data['upgrades'] ?? []);
      } else if (data['type'] == 'upgrade_approved') {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
              content:
                  Text("${data['username'] ?? 'Client'} upgraded to Coach"),
              backgroundColor: const Color(0xFF00F5D4)),
        );
        _fetchDashboard();
      } else if (data['type'] == 'upgrade_rejected') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Upgrade request rejected"),
              backgroundColor: Color(0xFFEF4444)),
        );
        _fetchDashboard();
      } else if (data['type'] == 'pending_students_list') {
        setState(() => _pendingStudents = data['students'] ?? []);
      } else if (data['type'] == 'student_verification_approved') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Student verified for JUDGE DOJO access"),
              backgroundColor: Color(0xFF00F5D4)),
        );
        _fetchDashboard();
      } else if (data['type'] == 'student_verification_rejected') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Student verification rejected"),
              backgroundColor: Color(0xFFEF4444)),
        );
        _fetchDashboard();
      } else if (data['type'] == 'crisis_resolved') {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text("Crisis marked as resolved"),
              backgroundColor: Color(0xFF00F5D4)),
        );
        _fetchDashboard();
      } else if (data['type'] == 'admin_coach_learning_queue') {
        if (mounted) {
          setState(() {
            _coachLearningStatus =
                (data['status'] ?? _coachLearningStatus).toString();
            _coachLearningItems = (data['items'] ?? []) as List<dynamic>;
            _coachLearningLoading = false;
          });
        }
      } else if (data['type'] == 'admin_coach_learning_queue_updated') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text("Learning queue updated"),
                backgroundColor: Color(0xFF00F5D4)),
          );
          _fetchCoachLearningQueue(status: _coachLearningStatus);
        }
      } else if (data['type'] == 'admin_coach_learning_queue_new') {
        // Real-time push from bridge when a coach submits a new learning item
        if (mounted) {
          final item = (data['item'] is Map)
              ? Map<String, dynamic>.from(data['item'])
              : null;
          if (item != null) {
            final status = (item['status'] ?? '').toString().toUpperCase();
            if (status == _coachLearningStatus.toUpperCase()) {
              final next = List<dynamic>.from(_coachLearningItems);
              next.add(item);
              setState(() => _coachLearningItems = next);
            }
          }
        }
      }
      // --- SEARCH APPROVAL MESSAGES ---
      else if (data['type'] == 'search_pending_admin') {
        // Real-time push: a coach requested a search
        if (mounted) {
          final req = data['request'];
          if (req != null) {
            final exists = _pendingSearches
                .any((r) => r['request_id'] == req['request_id']);
            if (!exists) {
              setState(() => _pendingSearches = [..._pendingSearches, req]);
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                      "Search request from ${req['coach_name'] ?? 'Coach'}: \"${(req['suggested_search'] ?? '').toString().substring(0, (req['suggested_search'] ?? '').toString().length > 60 ? 60 : (req['suggested_search'] ?? '').toString().length)}\""),
                  backgroundColor: const Color(0xFFFF9500),
                  duration: const Duration(seconds: 5),
                  action: SnackBarAction(
                    label: "REVIEW",
                    textColor: Colors.black,
                    onPressed: () =>
                        _tabController.animateTo(3), // Switch to Approvals tab
                  ),
                ),
              );
            }
          }
        }
      } else if (data['type'] == 'admin_pending_searches') {
        if (mounted) {
          setState(() => _pendingSearches = data['requests'] ?? []);
        }
      } else if (data['type'] == 'search_admin_confirmed') {
        if (mounted) {
          final approved = data['approved'] == true;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                  "Search ${approved ? 'approved' : 'denied'} for ${data['coach_name'] ?? 'coach'}"),
              backgroundColor: approved ? const Color(0xFF00F5D4) : Colors.red,
            ),
          );
        }
      } else if (data['type'] == 'coach_rejected') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text(data['message'] ?? "Coach application rejected"),
                backgroundColor: Colors.orange),
          );
          _fetchDashboard();
        }
      } else if (data['type'] == 'error') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text("Error: ${data['message'] ?? 'Unknown error'}"),
              backgroundColor: Colors.red,
              duration: const Duration(seconds: 5),
            ),
          );
        }
      }
    } catch (e) {
      _debugLog("Parse error: $e");
    }
  }

  void _approveCoach(String coachId) {
    _debugLog("[Admin] Approving coach: $coachId");
    _socket?.sink
        .add(jsonEncode({"type": "admin_approve_coach", "coach_id": coachId}));
  }

  void _rejectCoach(String coachId) {
    showDialog(
      context: context,
      builder: (ctx) {
        final reasonCtrl = TextEditingController();
        return AlertDialog(
          backgroundColor: const Color(0xFF1A1A2E),
          title: const Text("Reject Coach Application",
              style: TextStyle(color: Colors.white)),
          content: TextField(
            controller: reasonCtrl,
            style: const TextStyle(color: Colors.white),
            maxLines: 3,
            decoration: const InputDecoration(
              hintText: "Reason for rejection (optional)",
              hintStyle: TextStyle(color: Colors.white38),
              enabledBorder: OutlineInputBorder(
                  borderSide: BorderSide(color: Colors.white24)),
              focusedBorder:
                  OutlineInputBorder(borderSide: BorderSide(color: Colors.red)),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              onPressed: () {
                _socket?.sink.add(jsonEncode({
                  "type": "admin_reject_coach",
                  "coach_id": coachId,
                  "reason": reasonCtrl.text.trim(),
                }));
                Navigator.pop(ctx);
              },
              style: ElevatedButton.styleFrom(backgroundColor: Colors.red),
              child:
                  const Text("Reject", style: TextStyle(color: Colors.white)),
            ),
          ],
        );
      },
    );
  }

  void _approveSearch(String requestId) {
    _socket?.sink.add(jsonEncode({
      "type": "search_admin_decision",
      "request_id": requestId,
      "approved": true,
    }));
    setState(() {
      _pendingSearches =
          _pendingSearches.where((r) => r['request_id'] != requestId).toList();
    });
  }

  void _denySearch(String requestId, String reason) {
    _socket?.sink.add(jsonEncode({
      "type": "search_admin_decision",
      "request_id": requestId,
      "approved": false,
      "reason": reason,
    }));
    setState(() {
      _pendingSearches =
          _pendingSearches.where((r) => r['request_id'] != requestId).toList();
    });
  }

  void _resolveCrisis(String eventId) {
    _socket?.sink.add(jsonEncode({
      "type": "admin_resolve_crisis",
      "event_id": eventId,
      "resolution_notes": "Reviewed by admin"
    }));
  }

  @override
  void dispose() {
    _tabController.dispose();
    _wsReconnectTimer?.cancel();
    _socket?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0F),
      appBar: AppBar(
        title: const Text(
          "ADMIN COMMAND",
          style: TextStyle(
              fontFamily: 'Courier',
              color: Color(0xFFFF006E),
              fontWeight: FontWeight.bold,
              letterSpacing: 2),
        ),
        backgroundColor: Colors.transparent,
        elevation: 0,
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: const Color(0xFFFF006E),
          labelColor: const Color(0xFFFF006E),
          unselectedLabelColor: Colors.grey,
          isScrollable: true,
          tabs: const [
            Tab(icon: Icon(Icons.dashboard), text: "OVERVIEW"),
            Tab(icon: Icon(Icons.warning), text: "CRISIS"),
            Tab(icon: Icon(Icons.people), text: "USERS"),
            Tab(icon: Icon(Icons.verified_user), text: "APPROVALS"),
            Tab(icon: Icon(Icons.school), text: "LEARNING"),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.grey),
            onPressed: () {
              setState(() => _isLoading = true);
              _fetchDashboard();
            },
          ),
          IconButton(
            icon: const Icon(Icons.logout, color: Colors.red),
            onPressed: () {
              _socket?.sink.close();
              Navigator.of(context).pushReplacement(
                MaterialPageRoute(builder: (_) => const LobbyScreen()),
              );
            },
          ),
        ],
      ),
      body: _isLoading
          ? const Center(
              child: CircularProgressIndicator(color: Color(0xFFFF006E)))
          : TabBarView(
              controller: _tabController,
              children: [
                _buildOverviewTab(),
                _buildCrisisTab(),
                _buildUsersTab(),
                _buildApprovalsTab(),
                _buildLearningTab(),
              ],
            ),
    );
  }

  void _openLearningItemDialog(Map<String, dynamic> item) {
    final id = (item['id'] ?? '').toString();
    final content = (item['content'] ?? '').toString();
    final editCtrl = TextEditingController(text: content);
    final reasonCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: const Color(0xFF0A0A0F),
          title: Text(
            "Coach Learning • $id",
            style: const TextStyle(
                color: Color(0xFFFFD700),
                fontFamily: 'Courier',
                fontWeight: FontWeight.bold),
          ),
          content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    "${item['source'] ?? ''} • ${(item['created_at'] ?? '').toString()}",
                    style: const TextStyle(color: Colors.grey),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    "Folder: ${(item['folder_id'] ?? '').toString()}",
                    style: const TextStyle(color: Colors.white70),
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: editCtrl,
                    maxLines: 10,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: "Content (editable)",
                      labelStyle: TextStyle(color: Colors.grey),
                      enabledBorder: OutlineInputBorder(
                          borderSide: BorderSide(color: Colors.white24)),
                      focusedBorder: OutlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFF00F5D4))),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: reasonCtrl,
                    maxLines: 2,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: "Reject reason (optional)",
                      labelStyle: TextStyle(color: Colors.grey),
                      enabledBorder: OutlineInputBorder(
                          borderSide: BorderSide(color: Colors.white24)),
                      focusedBorder: OutlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFF00F5D4))),
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text("Close", style: TextStyle(color: Colors.grey)),
            ),
            TextButton(
              onPressed: () {
                _rejectCoachLearning(id, reason: reasonCtrl.text.trim());
                Navigator.of(ctx).pop();
              },
              child: const Text("Reject",
                  style: TextStyle(color: Color(0xFFEF4444))),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF00F5D4),
                  foregroundColor: Colors.black),
              onPressed: () {
                _approveCoachLearning(id, editedContent: editCtrl.text.trim());
                Navigator.of(ctx).pop();
              },
              child: const Text("Approve"),
            ),
          ],
        );
      },
    );
  }

  // =============================================================================
  // FOLDER TAB — File storage & form templates
  // =============================================================================

  List<Map<String, dynamic>> _folderList = [];
  List<Map<String, dynamic>> _folderFiles = [];
  List<Map<String, dynamic>> _formTemplates = [];
  String? _activeFolderId;
  String? _activeFolderName;
  bool _foldersLoading = false;

  Widget _buildFolderTab() {
    return RefreshIndicator(
      onRefresh: () async => _fetchFolders(),
      color: const Color(0xFFFFD700),
      child: _foldersLoading
          ? const Center(
              child: CircularProgressIndicator(color: Color(0xFFFFD700)))
          : _activeFolderId != null
              ? _buildFolderDetail()
              : _buildFolderList(),
    );
  }

  Widget _buildFolderList() {
    if (_folderList.isEmpty && !_foldersLoading) {
      _fetchFolders();
    }

    final personal =
        _folderList.where((f) => f['folder_type'] == 'personal').toList();
    final clients =
        _folderList.where((f) => f['folder_type'] == 'client').toList();
    final families =
        _folderList.where((f) => f['folder_type'] == 'family').toList();
    final groups =
        _folderList.where((f) => f['folder_type'] == 'group').toList();
    final companies =
        _folderList.where((f) => f['folder_type'] == 'company').toList();

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text("FILE MANAGER",
                style: TextStyle(
                    color: Color(0xFFFFD700),
                    fontFamily: 'Courier',
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 2)),
            Row(children: [
              IconButton(
                icon: const Icon(Icons.note_add,
                    color: Color(0xFF4ECDC4), size: 20),
                tooltip: "Form Templates",
                onPressed: _showFormTemplates,
              ),
              IconButton(
                icon: const Icon(Icons.create_new_folder,
                    color: Color(0xFFC9A962), size: 20),
                tooltip: "New Folder",
                onPressed: _createCustomFolder,
              ),
            ]),
          ],
        ),
        const SizedBox(height: 12),
        if (personal.isNotEmpty) ...[
          _buildFolderSection("MY FILES", Icons.person, personal),
          const SizedBox(height: 16),
        ],
        if (clients.isNotEmpty) ...[
          _buildFolderSection("CLIENT FOLDERS", Icons.people, clients),
          const SizedBox(height: 16),
        ],
        if (families.isNotEmpty) ...[
          _buildFolderSection(
              "FAMILY FOLDERS", Icons.family_restroom, families),
          const SizedBox(height: 16),
        ],
        if (groups.isNotEmpty) ...[
          _buildFolderSection("GROUP FOLDERS", Icons.groups, groups),
          const SizedBox(height: 16),
        ],
        if (companies.isNotEmpty) ...[
          _buildFolderSection("COMPANY FOLDERS", Icons.business, companies),
        ],
        if (_folderList.isEmpty)
          Center(
            child: Padding(
              padding: const EdgeInsets.all(40),
              child: Column(children: [
                Icon(Icons.folder_open, color: Colors.grey[600], size: 48),
                const SizedBox(height: 12),
                Text("No folders yet",
                    style: TextStyle(color: Colors.grey[500], fontSize: 14)),
                const SizedBox(height: 4),
                Text("Folders auto-populate from your assigned clients",
                    style: TextStyle(color: Colors.grey[600], fontSize: 12)),
              ]),
            ),
          ),
      ],
    );
  }

  Widget _buildFolderSection(
      String title, IconData icon, List<Map<String, dynamic>> folders) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(children: [
          Icon(icon, color: const Color(0xFF8B7355), size: 16),
          const SizedBox(width: 8),
          Text(title,
              style: const TextStyle(
                  color: Color(0xFF8B7355),
                  fontFamily: 'Courier',
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1)),
          const SizedBox(width: 8),
          Text("(${folders.length})",
              style: TextStyle(color: Colors.grey[600], fontSize: 11)),
        ]),
        const SizedBox(height: 8),
        ...folders.map((f) => _buildFolderCard(f)),
      ],
    );
  }

  Widget _buildFolderCard(Map<String, dynamic> folder) {
    final name = folder['entity_name'] ?? folder['entity_id'] ?? 'Unnamed';
    final type = folder['folder_type'] ?? '';
    final typeIcons = {
      'personal': Icons.person,
      'client': Icons.person_outline,
      'family': Icons.family_restroom,
      'group': Icons.groups,
      'company': Icons.business,
    };

    return GestureDetector(
      onTap: () {
        setState(() {
          _activeFolderId = folder['id'];
          _activeFolderName = name;
          _folderFiles = [];
        });
        _fetchFolderFiles(folder['id']);
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xFF222222)),
        ),
        child: Row(
          children: [
            Icon(typeIcons[type] ?? Icons.folder,
                color: const Color(0xFFC9A962), size: 20),
            const SizedBox(width: 12),
            Expanded(
              child: Text(name,
                  style: const TextStyle(color: Colors.white, fontSize: 14)),
            ),
            const Icon(Icons.chevron_right, color: Colors.grey, size: 18),
          ],
        ),
      ),
    );
  }

  Widget _buildFolderDetail() {
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          color: const Color(0xFF0D0D0D),
          child: Row(
            children: [
              GestureDetector(
                onTap: () => setState(() {
                  _activeFolderId = null;
                  _activeFolderName = null;
                }),
                child: const Row(children: [
                  Icon(Icons.arrow_back, color: Color(0xFFC9A962), size: 18),
                  SizedBox(width: 6),
                  Text("Back",
                      style: TextStyle(color: Color(0xFFC9A962), fontSize: 13)),
                ]),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(_activeFolderName ?? "Folder",
                    style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 14)),
              ),
            ],
          ),
        ),
        Expanded(
          child: _folderFiles.isEmpty
              ? Center(
                  child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.insert_drive_file,
                            color: Colors.grey[700], size: 40),
                        const SizedBox(height: 8),
                        Text("No files yet",
                            style: TextStyle(
                                color: Colors.grey[500], fontSize: 13)),
                      ]),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(12),
                  itemCount: _folderFiles.length,
                  itemBuilder: (context, index) {
                    final file = _folderFiles[index];
                    final filename = file['filename'] ?? 'Unknown';
                    final fileType = file['file_type'] ?? 'document';
                    final created = file['created_at'] ?? '';

                    final typeIcon = fileType.contains('pdf')
                        ? Icons.picture_as_pdf
                        : fileType.contains('xls')
                            ? Icons.table_chart
                            : fileType.contains('image')
                                ? Icons.image
                                : Icons.insert_drive_file;

                    return Container(
                      margin: const EdgeInsets.only(bottom: 6),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: const Color(0xFF111111),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: const Color(0xFF222222)),
                      ),
                      child: Row(children: [
                        Icon(typeIcon,
                            color: const Color(0xFF4ECDC4), size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(filename,
                                    style: const TextStyle(
                                        color: Colors.white, fontSize: 13)),
                                if (created.isNotEmpty)
                                  Text(created.substring(0, 10),
                                      style: TextStyle(
                                          color: Colors.grey[600],
                                          fontSize: 11)),
                              ]),
                        ),
                      ]),
                    );
                  },
                ),
        ),
      ],
    );
  }

  void _fetchFolders() {
    final token = widget.currentUserProfile?['token'] ?? '';
    if (token.isEmpty) return;
    setState(() => _foldersLoading = true);

    final baseUrl = AppConfig.apiBaseUrl;
    final url = Uri.parse('$baseUrl/api/coach/folders');
    _makeApiRequest(url, token, (data) {
      if (mounted) {
        setState(() {
          _folderList = List<Map<String, dynamic>>.from(data['folders'] ?? []);
          _foldersLoading = false;
        });
      }
    });
  }

  void _fetchFolderFiles(String folderId) {
    final token = widget.currentUserProfile?['token'] ?? '';
    if (token.isEmpty) return;

    final baseUrl = AppConfig.apiBaseUrl;
    final url = Uri.parse('$baseUrl/api/coach/folders/$folderId/files');
    _makeApiRequest(url, token, (data) {
      if (mounted) {
        setState(() {
          _folderFiles = List<Map<String, dynamic>>.from(data['files'] ?? []);
        });
      }
    });
  }

  void _showFormTemplates() {
    final token = widget.currentUserProfile?['token'] ?? '';
    if (token.isEmpty) return;

    final baseUrl = AppConfig.apiBaseUrl;
    final url = Uri.parse('$baseUrl/api/coach/forms/templates');
    _makeApiRequest(url, token, (data) {
      if (!mounted) return;
      final templates =
          List<Map<String, dynamic>>.from(data['templates'] ?? []);
      showDialog(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: const Text("Form Templates",
              style: TextStyle(color: Color(0xFFFFD700), fontSize: 16)),
          content: SizedBox(
            width: double.maxFinite,
            height: 400,
            child: ListView.builder(
              itemCount: templates.length,
              itemBuilder: (ctx, idx) {
                final t = templates[idx];
                return ListTile(
                  leading: Icon(
                    t['created_by_ai'] == true
                        ? Icons.auto_awesome
                        : Icons.description,
                    color: t['form_type'] == 'system'
                        ? const Color(0xFFC9A962)
                        : const Color(0xFF4ECDC4),
                    size: 20,
                  ),
                  title: Text(t['title'] ?? '',
                      style:
                          const TextStyle(color: Colors.white, fontSize: 13)),
                  subtitle: Text(t['description'] ?? '',
                      style: TextStyle(color: Colors.grey[500], fontSize: 11),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis),
                  onTap: () => Navigator.pop(ctx),
                );
              },
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text("Close",
                  style: TextStyle(color: Color(0xFFC9A962))),
            ),
          ],
        ),
      );
    });
  }

  void _createCustomFolder() {
    final nameCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Create Folder",
            style: TextStyle(color: Color(0xFFFFD700), fontSize: 16)),
        content: TextField(
          controller: nameCtrl,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            labelText: "Folder Name",
            labelStyle: TextStyle(color: Colors.grey),
            enabledBorder: UnderlineInputBorder(
                borderSide: BorderSide(color: Colors.grey)),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text("Cancel", style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFC9A962)),
            onPressed: () {
              Navigator.pop(ctx);
              _doCreateFolder(nameCtrl.text.trim());
            },
            child: const Text("Create", style: TextStyle(color: Colors.black)),
          ),
        ],
      ),
    );
  }

  void _doCreateFolder(String name) {
    if (name.isEmpty) return;
    final token = widget.currentUserProfile?['token'] ?? '';
    if (token.isEmpty) return;

    final baseUrl = AppConfig.apiBaseUrl;
    final url = Uri.parse('$baseUrl/api/coach/folders/create');
    _makeApiPost(url, token, {'folder_type': 'personal', 'entity_name': name},
        (data) {
      if (mounted) {
        _fetchFolders();
      }
    });
  }

  void _makeApiRequest(
      Uri url, String token, void Function(Map<String, dynamic>) onData) {
    http.get(url, headers: {'Authorization': 'Bearer $token'}).then((resp) {
      if (resp.statusCode == 200) {
        try {
          final data = json.decode(resp.body);
          onData(data is Map<String, dynamic> ? data : {});
        } catch (_) {}
      }
    }).catchError((_) {});
  }

  void _makeApiPost(Uri url, String token, Map<String, dynamic> body,
      void Function(Map<String, dynamic>) onData) {
    http
        .post(url,
            headers: {
              'Authorization': 'Bearer $token',
              'Content-Type': 'application/json'
            },
            body: json.encode(body))
        .then((resp) {
      if (resp.statusCode == 200) {
        try {
          final data = json.decode(resp.body);
          onData(data is Map<String, dynamic> ? data : {});
        } catch (_) {}
      }
    }).catchError((_) {});
  }

  Widget _buildLearningTab() {
    final items = List<dynamic>.from(_coachLearningItems);
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
          child: Row(
            children: [
              ChoiceChip(
                label: const Text("PENDING"),
                selected: _coachLearningStatus.toUpperCase() == "PENDING",
                onSelected: (_) {
                  setState(() => _coachLearningStatus = "PENDING");
                  _fetchCoachLearningQueue(status: "PENDING");
                },
              ),
              const SizedBox(width: 8),
              ChoiceChip(
                label: const Text("APPROVED"),
                selected: _coachLearningStatus.toUpperCase() == "APPROVED",
                onSelected: (_) {
                  setState(() => _coachLearningStatus = "APPROVED");
                  _fetchCoachLearningQueue(status: "APPROVED");
                },
              ),
              const SizedBox(width: 8),
              ChoiceChip(
                label: const Text("REJECTED"),
                selected: _coachLearningStatus.toUpperCase() == "REJECTED",
                onSelected: (_) {
                  setState(() => _coachLearningStatus = "REJECTED");
                  _fetchCoachLearningQueue(status: "REJECTED");
                },
              ),
              const Spacer(),
              if (_coachLearningLoading)
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: Color(0xFF00F5D4)),
                ),
            ],
          ),
        ),
        Expanded(
          child: items.isEmpty
              ? const Center(
                  child: Text("No learning items",
                      style: TextStyle(color: Colors.grey)))
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                  itemCount: items.length,
                  itemBuilder: (context, idx) {
                    final raw = items[items.length - 1 - idx];
                    final item = (raw is Map)
                        ? Map<String, dynamic>.from(raw)
                        : <String, dynamic>{};
                    final id = (item['id'] ?? '').toString();
                    final source = (item['source'] ?? '').toString();
                    final created = (item['created_at'] ?? '').toString();
                    final folder = (item['folder_id'] ?? '').toString();
                    final preview = (item['content'] ?? '').toString();
                    return InkWell(
                      onTap: () => _openLearningItemDialog(item),
                      child: Container(
                        margin: const EdgeInsets.only(bottom: 10),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: const Color(0xFF111118),
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: Colors.white10),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    "$source • $created",
                                    style: const TextStyle(
                                        color: Colors.white70,
                                        fontFamily: 'Courier'),
                                  ),
                                ),
                                Text(id,
                                    style: const TextStyle(
                                        color: Colors.grey, fontSize: 12)),
                              ],
                            ),
                            const SizedBox(height: 6),
                            Text("Folder: $folder",
                                style: const TextStyle(
                                    color: Colors.grey, fontSize: 12)),
                            const SizedBox(height: 10),
                            Text(
                              preview.length > 220
                                  ? "${preview.substring(0, 220)}…"
                                  : preview,
                              style: const TextStyle(color: Colors.white),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildOverviewTab() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Stats grid
          Row(
            children: [
              Expanded(
                  child: _buildStatCard(
                      "Total Users",
                      _stats['total_users']?.toString() ?? '0',
                      Icons.people,
                      const Color(0xFF4361EE))),
              const SizedBox(width: 12),
              Expanded(
                  child: _buildStatCard(
                      "Active Today",
                      _stats['active_today']?.toString() ?? '0',
                      Icons.trending_up,
                      const Color(0xFF00F5D4))),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                  child: _buildStatCard(
                      "Messages",
                      _stats['total_messages']?.toString() ?? '0',
                      Icons.chat,
                      const Color(0xFF9D4EDD))),
              const SizedBox(width: 12),
              Expanded(
                  child: _buildStatCard(
                      "Crisis Alerts",
                      _crisisWatchlist
                          .where((c) => !(c['resolved'] ?? false))
                          .length
                          .toString(),
                      Icons.warning,
                      const Color(0xFFFF4757))),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                  child: _buildStatCard(
                      "Coaches",
                      _stats['total_coaches']?.toString() ?? '0',
                      Icons.school,
                      const Color(0xFFFFD700))),
              const SizedBox(width: 12),
              Expanded(
                  child: _buildStatCard(
                      "Pending",
                      _pendingCoaches.length.toString(),
                      Icons.pending,
                      const Color(0xFFFF9F1C))),
            ],
          ),

          const SizedBox(height: 24),

          // Revenue (if available)
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  const Color(0xFF00F5D4).withOpacity(0.2),
                  const Color(0xFF4361EE).withOpacity(0.2)
                ],
              ),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white10),
            ),
            child: Row(
              children: [
                const Icon(Icons.attach_money,
                    color: Color(0xFF00F5D4), size: 40),
                const SizedBox(width: 16),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text("Monthly Revenue",
                        style: TextStyle(color: Colors.grey, fontSize: 12)),
                    Text(
                      "\$${_stats['revenue_month']?.toStringAsFixed(2) ?? '0.00'}",
                      style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 28,
                          fontFamily: 'Courier'),
                    ),
                  ],
                ),
              ],
            ),
          ),

          const SizedBox(height: 24),

          // Coaching Hierarchy Metrics
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF111111),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFF333333)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.fitness_center,
                        color: Color(0xFFFFD700), size: 20),
                    SizedBox(width: 8),
                    Text('COACHING MESH',
                        style: TextStyle(
                            color: Color(0xFFFFD700),
                            fontFamily: 'Courier',
                            fontWeight: FontWeight.bold,
                            fontSize: 14)),
                  ],
                ),
                const SizedBox(height: 12),
                FutureBuilder<Map<String, dynamic>>(
                  future: _fetchCoachingMetrics(),
                  builder: (ctx, snap) {
                    if (snap.connectionState != ConnectionState.done) {
                      return const Center(
                          child: CircularProgressIndicator(
                              color: Color(0xFFFFD700), strokeWidth: 2));
                    }
                    final data = snap.data ?? {};
                    return Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        _miniStat(
                            'Hierarchies',
                            '${data['active_relationships'] ?? 0}',
                            const Color(0xFFFFD700)),
                        _miniStat(
                            'Hours',
                            '${data['total_supervised_hours'] ?? 0}',
                            const Color(0xFF4ECDC4)),
                        _miniStat(
                            'Sessions',
                            '${data['total_mesh_sessions'] ?? 0}',
                            const Color(0xFF9D4EDD)),
                        _miniStat(
                            'Active',
                            '${data['active_mesh_sessions'] ?? 0}',
                            const Color(0xFF22C55E)),
                      ],
                    );
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _miniStat(String label, String value, Color color) {
    return Column(
      children: [
        Text(value,
            style: TextStyle(
                color: color,
                fontSize: 20,
                fontWeight: FontWeight.bold,
                fontFamily: 'Courier')),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(color: Colors.grey, fontSize: 10)),
      ],
    );
  }

  Future<Map<String, dynamic>> _fetchCoachingMetrics() async {
    try {
      final url = '${AppConfig.apiBaseUrl}/api/coach/hierarchy/metrics';
      final resp = await http.get(
        Uri.parse(url),
        headers: {
          'Authorization': 'Bearer ${widget.currentUserProfile['token']}'
        },
      );
      if (resp.statusCode == 200)
        return jsonDecode(resp.body) as Map<String, dynamic>;
    } catch (_) {}
    return {};
  }

  Widget _buildCrisisTab() {
    final unresolvedCrisis =
        _crisisWatchlist.where((c) => !(c['resolved'] ?? false)).toList();

    if (unresolvedCrisis.isEmpty) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.check_circle, color: Color(0xFF00F5D4), size: 60),
            SizedBox(height: 16),
            Text("No active crisis alerts",
                style: TextStyle(color: Colors.grey)),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: unresolvedCrisis.length,
      itemBuilder: (context, index) {
        final alert = unresolvedCrisis[index];
        return CrisisAlertCard(
          alert: alert,
          onResolve: () => _resolveCrisis(alert['id'] ?? ''),
          onViewProfile: () {
            // Navigate to user detail view
            final userId = alert['user_id'] ?? alert['client_id'] ?? '';
            if (userId.isNotEmpty) {
              Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => Scaffold(
                    appBar: AppBar(title: Text('User: $userId')),
                    body: Center(
                        child: Text('Profile for $userId',
                            style: const TextStyle(fontSize: 18))),
                  ),
                ),
              );
            }
          },
        );
      },
    );
  }

  Widget _buildUsersTab() {
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _users.length,
      itemBuilder: (context, index) {
        final user = _users[index];
        final isPending =
            (user['subscription_status'] ?? '').toString().toUpperCase() ==
                'PENDING_VERIFICATION';
        final isCoach =
            (user['role'] ?? '').toString().toUpperCase() == 'COACH';
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A2E),
            borderRadius: BorderRadius.circular(12),
            border: isPending
                ? Border.all(color: const Color(0xFFFFD700).withOpacity(0.4))
                : null,
          ),
          child: Column(
            children: [
              Row(
                children: [
                  CircleAvatar(
                    backgroundColor:
                        _getRoleColor(user['role']).withOpacity(0.3),
                    child: Icon(
                      _getRoleIcon(user['role']),
                      color: _getRoleColor(user['role']),
                      size: 20,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          user['name'] ?? 'Unknown',
                          style: const TextStyle(
                              color: Colors.white, fontWeight: FontWeight.w500),
                        ),
                        Text(
                          "${user['role']} • ${user['subscription_status'] ?? 'Unknown'}",
                          style: TextStyle(
                              color: isPending
                                  ? const Color(0xFFFFD700)
                                  : Colors.grey[500],
                              fontSize: 11),
                        ),
                      ],
                    ),
                  ),
                  if (user['risk_level'] != null)
                    RiskBadge(riskLevel: user['risk_level']),
                  if (isPending)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFD700).withOpacity(0.15),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Text("PENDING",
                          style: TextStyle(
                              color: Color(0xFFFFD700),
                              fontSize: 10,
                              fontWeight: FontWeight.bold)),
                    ),
                ],
              ),
              // Inline approve/reject for pending coaches
              if (isPending && isCoach) ...[
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () => _rejectCoach(user['id'] ?? ''),
                        icon: const Icon(Icons.close, size: 14),
                        label: const Text("Reject",
                            style: TextStyle(fontSize: 11)),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: Colors.red,
                          side: const BorderSide(color: Colors.red),
                          padding: const EdgeInsets.symmetric(vertical: 4),
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: ElevatedButton.icon(
                        onPressed: () => _approveCoach(user['id'] ?? ''),
                        icon: const Icon(Icons.check, size: 14),
                        label: const Text("Approve",
                            style: TextStyle(fontSize: 11)),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF00F5D4),
                          foregroundColor: Colors.black,
                          padding: const EdgeInsets.symmetric(vertical: 4),
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _buildApprovalsTab() {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // --- SEARCH APPROVALS SECTION ---
        Container(
          margin: const EdgeInsets.only(bottom: 16),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A2E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFFFF9500).withOpacity(0.4)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.search, color: Color(0xFFFF9500), size: 18),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      "SEARCH APPROVALS",
                      style: TextStyle(
                        color: Color(0xFFFF9500),
                        fontFamily: 'Courier',
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        letterSpacing: 1,
                      ),
                    ),
                  ),
                  if (_pendingSearches.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFF9500),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        "${_pendingSearches.length}",
                        style: const TextStyle(
                            color: Colors.black,
                            fontWeight: FontWeight.bold,
                            fontSize: 11),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 4),
              const Text(
                "3-layer security: Coach Approve → 2FA → Admin Approve",
                style: TextStyle(color: Colors.grey, fontSize: 10),
              ),
              const SizedBox(height: 8),
              if (_pendingSearches.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(
                    child: Text("No pending search requests",
                        style: TextStyle(color: Colors.grey, fontSize: 12)),
                  ),
                )
              else
                ..._pendingSearches.map((req) => _buildSearchApprovalCard(req)),
            ],
          ),
        ),

        // --- COACH APPROVALS SECTION ---
        Container(
          margin: const EdgeInsets.only(bottom: 16),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A2E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.verified_user,
                      color: Color(0xFFFFD700), size: 18),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      "COACH APPROVALS",
                      style: TextStyle(
                        color: Color(0xFFFFD700),
                        fontFamily: 'Courier',
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        letterSpacing: 1,
                      ),
                    ),
                  ),
                  if (_pendingCoaches.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFFD700),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        "${_pendingCoaches.length}",
                        style: const TextStyle(
                            color: Colors.black,
                            fontWeight: FontWeight.bold,
                            fontSize: 11),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              if (_pendingCoaches.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(
                    child: Text("No pending coach approvals",
                        style: TextStyle(color: Colors.grey, fontSize: 12)),
                  ),
                )
              else
                ..._pendingCoaches
                    .map((coach) => _buildCoachApprovalCard(coach)),
            ],
          ),
        ),

        // --- CLIENT → COACH UPGRADE REQUESTS ---
        Container(
          margin: const EdgeInsets.only(bottom: 16),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A2E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.4)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.trending_up,
                      color: Color(0xFF4ECDC4), size: 18),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      "COACH UPGRADE REQUESTS",
                      style: TextStyle(
                        color: Color(0xFF4ECDC4),
                        fontFamily: 'Courier',
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        letterSpacing: 1,
                      ),
                    ),
                  ),
                  if (_pendingUpgrades.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: const Color(0xFF4ECDC4),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        "${_pendingUpgrades.length}",
                        style: const TextStyle(
                            color: Colors.black,
                            fontWeight: FontWeight.bold,
                            fontSize: 11),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 4),
              const Text(
                "Clients requesting to upgrade their account to Coach",
                style: TextStyle(color: Colors.grey, fontSize: 10),
              ),
              const SizedBox(height: 8),
              if (_pendingUpgrades.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(
                    child: Text("No pending upgrade requests",
                        style: TextStyle(color: Colors.grey, fontSize: 12)),
                  ),
                )
              else
                ..._pendingUpgrades.map((u) => _buildUpgradeApprovalCard(u)),
            ],
          ),
        ),

        // --- JUDGE DOJO: STUDENT VERIFICATIONS ---
        Container(
          margin: const EdgeInsets.only(bottom: 16),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xFF1A1A2E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.4)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.gavel, color: Color(0xFF9D4EDD), size: 18),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text(
                      "JUDGE STUDENT VERIFICATIONS",
                      style: TextStyle(
                        color: Color(0xFF9D4EDD),
                        fontFamily: 'Courier',
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        letterSpacing: 1,
                      ),
                    ),
                  ),
                  if (_pendingStudents.isNotEmpty)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: const Color(0xFF9D4EDD),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        "${_pendingStudents.length}",
                        style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 11),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 4),
              const Text(
                "Coaching lawyers verifying students for JUDGE DOJO access",
                style: TextStyle(color: Colors.grey, fontSize: 10),
              ),
              const SizedBox(height: 8),
              if (_pendingStudents.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Center(
                    child: Text("No pending student verifications",
                        style: TextStyle(color: Colors.grey, fontSize: 12)),
                  ),
                )
              else
                ..._pendingStudents
                    .map((s) => _buildStudentVerificationCard(s)),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildStudentVerificationCard(dynamic s) {
    final studentName = (s['student_name'] ?? 'Unknown').toString();
    final studentId = (s['student_id'] ?? '').toString();
    final coachName = (s['coach_name'] ?? 'Unknown').toString();
    final verificationType =
        (s['verification_type'] ?? 'bar_student').toString();
    final requestedAt = (s['requested_at'] ?? '').toString();

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF111122),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.school, color: Color(0xFF9D4EDD), size: 16),
              const SizedBox(width: 6),
              Expanded(
                child: Text(studentName,
                    style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 13)),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: const Color(0xFF9D4EDD).withOpacity(0.2),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(verificationType.replaceAll('_', ' ').toUpperCase(),
                    style: const TextStyle(
                        color: Color(0xFF9D4EDD),
                        fontSize: 9,
                        fontWeight: FontWeight.bold)),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text("Vouched by: $coachName",
              style: TextStyle(color: Colors.grey[400], fontSize: 11)),
          if (requestedAt.isNotEmpty)
            Text("Requested: ${requestedAt.substring(0, 10)}",
                style: TextStyle(color: Colors.grey[600], fontSize: 10)),
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: () {
                  _socket?.sink.add(jsonEncode({
                    "type": "admin_reject_student_verification",
                    "student_id": studentId,
                    "reason": "Admin rejected",
                  }));
                },
                child: const Text("REJECT",
                    style: TextStyle(
                        color: Color(0xFFEF4444),
                        fontSize: 12,
                        fontWeight: FontWeight.bold)),
              ),
              const SizedBox(width: 8),
              ElevatedButton(
                onPressed: () {
                  _socket?.sink.add(jsonEncode({
                    "type": "admin_approve_student_verification",
                    "student_id": studentId,
                  }));
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF9D4EDD),
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                ),
                child: const Text("VERIFY",
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSearchApprovalCard(dynamic req) {
    final coachName =
        (req['coach_name'] ?? req['coach_id'] ?? 'Unknown').toString();
    final query = (req['suggested_search'] ?? '').toString();
    final mode = (req['mode'] ?? '').toString().toUpperCase();
    final requestId = (req['request_id'] ?? '').toString();

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0F),
        borderRadius: BorderRadius.circular(10),
        border:
            Border(left: BorderSide(color: const Color(0xFFFF9500), width: 3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.person, color: Color(0xFFFF9500), size: 16),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  coachName,
                  style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.bold,
                      fontSize: 13),
                ),
              ),
              if (mode.isNotEmpty)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: const Color(0xFF9D4EDD).withOpacity(0.2),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(mode,
                      style: const TextStyle(
                          color: Color(0xFF9D4EDD),
                          fontSize: 9,
                          fontWeight: FontWeight.bold)),
                ),
            ],
          ),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.05),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              children: [
                const Icon(Icons.search, color: Colors.grey, size: 14),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    '"$query"',
                    style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 12,
                        fontStyle: FontStyle.italic),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () {
                    showDialog(
                      context: context,
                      builder: (ctx) {
                        final reasonCtrl = TextEditingController();
                        return AlertDialog(
                          backgroundColor: const Color(0xFF0A0A0F),
                          title: const Text("Deny Search",
                              style: TextStyle(color: Colors.red)),
                          content: TextField(
                            controller: reasonCtrl,
                            style: const TextStyle(color: Colors.white),
                            decoration: const InputDecoration(
                              hintText: "Reason (optional)",
                              hintStyle: TextStyle(color: Colors.grey),
                            ),
                          ),
                          actions: [
                            TextButton(
                                onPressed: () => Navigator.pop(ctx),
                                child: const Text("Cancel")),
                            ElevatedButton(
                              onPressed: () {
                                _denySearch(requestId, reasonCtrl.text);
                                Navigator.pop(ctx);
                              },
                              style: ElevatedButton.styleFrom(
                                  backgroundColor: Colors.red),
                              child: const Text("Deny"),
                            ),
                          ],
                        );
                      },
                    );
                  },
                  icon: const Icon(Icons.close, size: 14),
                  label: const Text("DENY", style: TextStyle(fontSize: 11)),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: Colors.red,
                    side: const BorderSide(color: Colors.red),
                    padding: const EdgeInsets.symmetric(vertical: 6),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: () => _approveSearch(requestId),
                  icon: const Icon(Icons.check, size: 14),
                  label: const Text("APPROVE", style: TextStyle(fontSize: 11)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF00F5D4),
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 6),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildCoachApprovalCard(dynamic coach) {
    final coachId = coach['hardware_id'] ?? coach['id'] ?? '';
    final name = coach['name'] ?? 'Unknown Coach';
    final email = coach['email'] ?? '';
    final phone = coach['phone'] ?? '';
    final w9 = coach['w9_data'] as Map<String, dynamic>? ?? {};
    final addressVerified = coach['address_verified'] == true;
    final tinDocUploaded = coach['tin_doc_uploaded'] == true;
    final tinMatchStatus =
        (coach['tin_match_status'] ?? 'not_submitted').toString();

    // Build verification checklist count
    int verifiedCount = 0;
    int totalChecks = 5;
    if (email.isNotEmpty) verifiedCount++;
    if (phone.isNotEmpty) verifiedCount++;
    if (addressVerified) verifiedCount++;
    if (coach['w9_submitted'] == true) verifiedCount++;
    if (tinDocUploaded || tinMatchStatus == 'verified') verifiedCount++;

    return GestureDetector(
      onTap: () => _showCoachDetailDialog(coach),
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF0A0A0F),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: const Color(0xFFFFD700).withOpacity(0.3),
                  radius: 16,
                  child: const Icon(Icons.school,
                      color: Color(0xFFFFD700), size: 16),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name,
                          style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold,
                              fontSize: 14)),
                      if (email.isNotEmpty)
                        Text(email,
                            style: TextStyle(
                                color: Colors.grey[500], fontSize: 11)),
                    ],
                  ),
                ),
                // Verification badge
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: verifiedCount == totalChecks
                        ? const Color(0xFF4ECDC4).withOpacity(0.15)
                        : Colors.orange.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    "$verifiedCount/$totalChecks",
                    style: TextStyle(
                      color: verifiedCount == totalChecks
                          ? const Color(0xFF4ECDC4)
                          : Colors.orange,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            // Quick status row
            Row(
              children: [
                _buildMiniStatusBadge(Icons.email, email.isNotEmpty),
                const SizedBox(width: 6),
                _buildMiniStatusBadge(Icons.phone, phone.isNotEmpty),
                const SizedBox(width: 6),
                _buildMiniStatusBadge(Icons.location_on, addressVerified),
                const SizedBox(width: 6),
                _buildMiniStatusBadge(
                    Icons.description, coach['w9_submitted'] == true),
                const SizedBox(width: 6),
                _buildMiniStatusBadge(Icons.upload_file, tinDocUploaded),
                const Spacer(),
                const Icon(Icons.chevron_right, color: Colors.grey, size: 18),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => _rejectCoach(coachId),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.red,
                      side: const BorderSide(color: Colors.red),
                      padding: const EdgeInsets.symmetric(vertical: 6),
                    ),
                    child: const Text("REJECT", style: TextStyle(fontSize: 11)),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => _showCoachDetailDialog(coach),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFFFFD700),
                      side: BorderSide(
                          color: const Color(0xFFFFD700).withOpacity(0.5)),
                      padding: const EdgeInsets.symmetric(vertical: 6),
                    ),
                    child: const Text("REVIEW", style: TextStyle(fontSize: 11)),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: ElevatedButton(
                    onPressed: () => _approveCoach(coachId),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF00F5D4),
                      foregroundColor: Colors.black,
                      padding: const EdgeInsets.symmetric(vertical: 6),
                    ),
                    child:
                        const Text("APPROVE", style: TextStyle(fontSize: 11)),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildMiniStatusBadge(IconData icon, bool ok) {
    return Icon(icon,
        size: 14,
        color: ok ? const Color(0xFF4ECDC4) : Colors.grey.withOpacity(0.4));
  }

  Widget _buildUpgradeApprovalCard(dynamic u) {
    final hwId = u['hardware_id'] ?? '';
    final name = u['name'] ?? 'Unknown';
    final username = u['username'] ?? '';
    final email = u['email'] ?? '';
    final dojos = (u['selected_dojos'] as List?)?.cast<String>() ?? [];
    final fee = u['coaching_fee'] ?? 0;
    final sessions = u['total_sessions_count'] ?? 0;
    final requestedAt = u['requested_at'] ?? '';
    const dojoLabels = {
      'therapist': 'Therapist',
      'project_pm': 'Project PM',
      'business': 'Business',
      'cnc': 'CNC',
      'mcat': 'MCAT',
      'teacher': 'Teacher',
      'judge': 'Judge',
      'coach_nate': 'Coach Nate',
    };

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0F),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            CircleAvatar(
              backgroundColor: const Color(0xFF4ECDC4).withOpacity(0.3),
              radius: 16,
              child: const Icon(Icons.trending_up,
                  color: Color(0xFF4ECDC4), size: 16),
            ),
            const SizedBox(width: 12),
            Expanded(
                child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(name,
                    style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 14)),
                Text('@$username',
                    style: TextStyle(color: Colors.grey[500], fontSize: 11)),
              ],
            )),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: const Color(0xFFC9A962).withOpacity(0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text('$sessions sessions',
                  style: const TextStyle(
                      color: Color(0xFFC9A962),
                      fontSize: 10,
                      fontWeight: FontWeight.bold)),
            ),
          ]),
          const SizedBox(height: 8),
          if (email.isNotEmpty)
            Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(email,
                    style: TextStyle(color: Colors.grey[400], fontSize: 11))),
          Wrap(
              spacing: 6,
              runSpacing: 4,
              children: dojos
                  .map((d) => Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                            color: const Color(0xFF9D4EDD).withOpacity(0.2),
                            borderRadius: BorderRadius.circular(6)),
                        child: Text(dojoLabels[d] ?? d,
                            style: const TextStyle(
                                color: Color(0xFF9D4EDD), fontSize: 10)),
                      ))
                  .toList()),
          if (fee > 0)
            Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('Fee: \$${fee}/hr',
                    style: TextStyle(color: Colors.grey[500], fontSize: 11))),
          if (requestedAt.isNotEmpty)
            Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text('Requested: ${requestedAt.split('.').first}',
                    style: TextStyle(color: Colors.grey[600], fontSize: 10))),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
                child: OutlinedButton(
              onPressed: () {
                _socket?.sink.add(jsonEncode({
                  "type": "admin_reject_upgrade",
                  "hardware_id": hwId,
                  "reason": "Declined by admin"
                }));
              },
              style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.red,
                  side: const BorderSide(color: Colors.red),
                  padding: const EdgeInsets.symmetric(vertical: 6)),
              child: const Text("REJECT", style: TextStyle(fontSize: 11)),
            )),
            const SizedBox(width: 8),
            Expanded(
                child: ElevatedButton(
              onPressed: () {
                _socket?.sink.add(jsonEncode(
                    {"type": "admin_approve_upgrade", "hardware_id": hwId}));
              },
              style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF00F5D4),
                  foregroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(vertical: 6)),
              child: const Text("APPROVE", style: TextStyle(fontSize: 11)),
            )),
          ]),
        ],
      ),
    );
  }

  void _showCoachDetailDialog(dynamic coach) {
    final coachId = coach['hardware_id'] ?? coach['id'] ?? '';
    final name = coach['name'] ?? 'Unknown Coach';
    final email = coach['email'] ?? '';
    final phone = coach['phone'] ?? '';
    final dob = coach['dob'] ?? '';
    final joinedDate = coach['joined_date'] ?? '';
    final registrationDate = coach['registration_date'] ?? '';
    final w9 = coach['w9_data'] as Map<String, dynamic>? ?? {};
    final addressVerified = coach['address_verified'] == true;
    final standardizedAddr =
        coach['standardized_address'] as Map<String, dynamic>? ?? {};
    final tinDocUploaded = coach['tin_doc_uploaded'] == true;
    final tinMatchStatus =
        (coach['tin_match_status'] ?? 'not_submitted').toString();
    final tinVerificationMethod =
        (coach['tin_verification_method'] ?? 'none').toString();
    final dojos = coach['selected_dojos'] as List? ?? [];
    final dojoSubs = coach['dojo_subscriptions'] as Map<String, dynamic>? ?? {};
    final dojoPrice = coach['dojo_monthly_price'] ?? 0;
    final dojoDiscount = coach['dojo_discount_pct'] ?? 0;

    showDialog(
      context: context,
      builder: (ctx) => Dialog(
        backgroundColor: const Color(0xFF0A0A0F),
        insetPadding: const EdgeInsets.all(16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: Container(
          constraints: const BoxConstraints(maxWidth: 500, maxHeight: 700),
          child: Column(
            children: [
              // Header
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFD700).withOpacity(0.08),
                  borderRadius:
                      const BorderRadius.vertical(top: Radius.circular(16)),
                ),
                child: Row(
                  children: [
                    CircleAvatar(
                      backgroundColor: const Color(0xFFFFD700).withOpacity(0.3),
                      radius: 22,
                      child: const Icon(Icons.school,
                          color: Color(0xFFFFD700), size: 22),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text("COACH APPLICATION REVIEW",
                              style: TextStyle(
                                  color: Color(0xFFFFD700),
                                  fontFamily: 'Courier',
                                  fontWeight: FontWeight.bold,
                                  fontSize: 11,
                                  letterSpacing: 1)),
                          const SizedBox(height: 2),
                          Text(name,
                              style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 16)),
                        ],
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, color: Colors.grey),
                      onPressed: () => Navigator.pop(ctx),
                    ),
                  ],
                ),
              ),

              // Scrollable content
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    // --- IDENTITY SECTION ---
                    _buildDetailSection(
                        "IDENTITY", Icons.person, const Color(0xFF4ECDC4), [
                      _buildDetailRow("Full Name", name),
                      _buildDetailRow("Date of Birth",
                          dob.isNotEmpty ? dob : "Not provided"),
                      _buildDetailRow(
                          "Email", email.isNotEmpty ? email : "Not provided",
                          statusIcon: email.isNotEmpty
                              ? Icons.check_circle
                              : Icons.error,
                          statusColor: email.isNotEmpty
                              ? const Color(0xFF4ECDC4)
                              : Colors.red),
                      _buildDetailRow(
                          "Phone", phone.isNotEmpty ? phone : "Not provided",
                          statusIcon: phone.isNotEmpty
                              ? Icons.check_circle
                              : Icons.error,
                          statusColor: phone.isNotEmpty
                              ? const Color(0xFF4ECDC4)
                              : Colors.red),
                      _buildDetailRow(
                          "Registered",
                          registrationDate.isNotEmpty
                              ? registrationDate
                              : joinedDate),
                    ]),
                    const SizedBox(height: 14),

                    // --- W-9 TAX INFORMATION ---
                    _buildDetailSection("W-9 TAX INFORMATION",
                        Icons.description, const Color(0xFFFFD700), [
                      if (w9.isEmpty)
                        const Padding(
                          padding: EdgeInsets.all(8),
                          child: Text("No W-9 data submitted",
                              style: TextStyle(
                                  color: Colors.redAccent, fontSize: 12)),
                        )
                      else ...[
                        _buildDetailRow(
                            "Legal Name", w9['legal_name'] ?? 'N/A'),
                        if ((w9['business_name'] ?? '').isNotEmpty)
                          _buildDetailRow("Business Name", w9['business_name']),
                        _buildDetailRow("Tax Classification",
                            _formatTaxClass(w9['tax_classification'] ?? '')),
                        _buildDetailRow(
                            "Address", _formatW9Address(w9, standardizedAddr),
                            statusIcon: addressVerified
                                ? Icons.verified
                                : Icons.warning,
                            statusColor: addressVerified
                                ? const Color(0xFF4ECDC4)
                                : Colors.orange),
                        if (addressVerified && standardizedAddr.isNotEmpty)
                          _buildDetailRow("USPS Standardized",
                              _formatStandardizedAddress(standardizedAddr),
                              statusIcon: Icons.local_post_office,
                              statusColor: const Color(0xFF4ECDC4)),
                        _buildDetailRow(
                            "TIN (SSN/EIN)", w9['tin_masked'] ?? '***-**-****',
                            statusIcon: Icons.lock, statusColor: Colors.grey),
                        _buildDetailRow(
                            "Certified", w9['certified'] == true ? "Yes" : "No",
                            statusIcon: w9['certified'] == true
                                ? Icons.check_circle
                                : Icons.cancel,
                            statusColor: w9['certified'] == true
                                ? const Color(0xFF4ECDC4)
                                : Colors.red),
                        _buildDetailRow("Signature", w9['signature'] ?? 'N/A'),
                        if (w9['signed_date'] != null)
                          _buildDetailRow("Signed Date",
                              w9['signed_date'].toString().substring(0, 10)),
                      ],
                    ]),
                    const SizedBox(height: 14),

                    // --- DOCUMENTATION ---
                    _buildDetailSection("DOCUMENTATION", Icons.folder_open,
                        const Color(0xFF9D4EDD), [
                      _buildDetailRow(
                        "W-9 Document",
                        tinDocUploaded ? "Uploaded" : "Not uploaded",
                        statusIcon:
                            tinDocUploaded ? Icons.check_circle : Icons.cancel,
                        statusColor: tinDocUploaded
                            ? const Color(0xFF4ECDC4)
                            : Colors.red,
                      ),
                      _buildDetailRow(
                        "TIN Match Status",
                        _formatTinMatchStatus(tinMatchStatus),
                        statusIcon: tinMatchStatus == 'verified'
                            ? Icons.verified
                            : Icons.pending,
                        statusColor: tinMatchStatus == 'verified'
                            ? const Color(0xFF4ECDC4)
                            : Colors.orange,
                      ),
                      if (tinDocUploaded)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: OutlinedButton.icon(
                            onPressed: () {
                              // Request document from backend
                              _socket?.sink.add(jsonEncode({
                                "type": "admin_get_coach_document",
                                "coach_id": coachId,
                              }));
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                    content: Text("Requesting document...")),
                              );
                            },
                            icon: const Icon(Icons.visibility, size: 16),
                            label: const Text("View W-9 Document",
                                style: TextStyle(fontSize: 12)),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: const Color(0xFF9D4EDD),
                              side: BorderSide(
                                  color:
                                      const Color(0xFF9D4EDD).withOpacity(0.5)),
                            ),
                          ),
                        ),
                    ]),
                    const SizedBox(height: 14),

                    // --- DOJO SUBSCRIPTIONS ---
                    _buildDetailSection("DOJO SUBSCRIPTIONS",
                        Icons.fitness_center, const Color(0xFFFF6B6B), [
                      if (dojos.isEmpty)
                        const Padding(
                          padding: EdgeInsets.all(8),
                          child: Text("No DOJOs selected",
                              style:
                                  TextStyle(color: Colors.grey, fontSize: 12)),
                        )
                      else ...[
                        ...dojos
                            .map((d) => _buildDetailRow("DOJO", d.toString())),
                        _buildDetailRow("Monthly Price", "\$${dojoPrice}"),
                        if (dojoDiscount > 0)
                          _buildDetailRow(
                              "Multi-DOJO Discount", "$dojoDiscount%",
                              statusIcon: Icons.local_offer,
                              statusColor: const Color(0xFF4ECDC4)),
                      ],
                    ]),
                    const SizedBox(height: 14),

                    // --- VERIFICATION STATUS CHECKLIST ---
                    _buildDetailSection("VERIFICATION STATUS", Icons.checklist,
                        Colors.white70, [
                      _buildChecklistRow("Email provided", email.isNotEmpty),
                      _buildChecklistRow("Phone provided", phone.isNotEmpty),
                      _buildChecklistRow(
                          "Address verified (USPS)", addressVerified),
                      _buildChecklistRow(
                          "TIN format valid", coach['w9_submitted'] == true),
                      _buildChecklistRow(
                          "W-9 document uploaded", tinDocUploaded),
                      _buildChecklistRow(
                          "TIN verified", tinMatchStatus == 'verified'),
                    ]),
                    const SizedBox(height: 20),
                  ],
                ),
              ),

              // Action buttons
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFF111111),
                  borderRadius:
                      const BorderRadius.vertical(bottom: Radius.circular(16)),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () {
                          Navigator.pop(ctx);
                          _rejectCoach(coachId);
                        },
                        style: OutlinedButton.styleFrom(
                          foregroundColor: Colors.red,
                          side: const BorderSide(color: Colors.red),
                          padding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                        child: const Text("REJECT"),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      flex: 2,
                      child: ElevatedButton(
                        onPressed: () {
                          Navigator.pop(ctx);
                          _approveCoach(coachId);
                        },
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF00F5D4),
                          foregroundColor: Colors.black,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                        child: const Text("APPROVE COACH",
                            style: TextStyle(fontWeight: FontWeight.bold)),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDetailSection(
      String title, IconData icon, Color color, List<Widget> children) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withOpacity(0.05),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withOpacity(0.2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: color, size: 16),
              const SizedBox(width: 8),
              Text(title,
                  style: TextStyle(
                      color: color,
                      fontFamily: 'Courier',
                      fontWeight: FontWeight.bold,
                      fontSize: 11,
                      letterSpacing: 1)),
            ],
          ),
          const SizedBox(height: 8),
          ...children,
        ],
      ),
    );
  }

  Widget _buildDetailRow(String label, String value,
      {IconData? statusIcon, Color? statusColor}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(label,
                style: TextStyle(color: Colors.grey[500], fontSize: 11)),
          ),
          if (statusIcon != null) ...[
            Icon(statusIcon, size: 14, color: statusColor ?? Colors.grey),
            const SizedBox(width: 4),
          ],
          Expanded(
            child: Text(value,
                style: const TextStyle(color: Colors.white, fontSize: 12)),
          ),
        ],
      ),
    );
  }

  Widget _buildChecklistRow(String label, bool passed) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Icon(
            passed ? Icons.check_circle : Icons.radio_button_unchecked,
            size: 16,
            color:
                passed ? const Color(0xFF4ECDC4) : Colors.grey.withOpacity(0.4),
          ),
          const SizedBox(width: 10),
          Text(
            label,
            style: TextStyle(
              color: passed ? Colors.white : Colors.grey,
              fontSize: 12,
              decoration: passed ? null : TextDecoration.lineThrough,
              decorationColor: Colors.grey,
            ),
          ),
        ],
      ),
    );
  }

  String _formatTaxClass(String tc) {
    switch (tc) {
      case 'individual':
        return 'Individual / Sole Proprietor';
      case 'llc':
        return 'LLC';
      case 'corporation':
        return 'Corporation';
      case 'partnership':
        return 'Partnership';
      default:
        return tc;
    }
  }

  String _formatW9Address(
      Map<String, dynamic> w9, Map<String, dynamic> stdAddr) {
    final street = w9['street'] ?? '';
    final city = w9['city'] ?? '';
    final state = w9['state'] ?? '';
    final zip = w9['zip'] ?? '';
    if (street.isEmpty && city.isEmpty) return 'Not provided';
    return '$street, $city, $state $zip';
  }

  String _formatStandardizedAddress(Map<String, dynamic> addr) {
    final street = addr['street'] ?? '';
    final city = addr['city'] ?? '';
    final state = addr['state'] ?? '';
    final zip5 = addr['zip5'] ?? '';
    final zip4 = addr['zip4'] ?? '';
    final zipFull = zip4.isNotEmpty ? '$zip5-$zip4' : zip5;
    return '$street, $city, $state $zipFull';
  }

  String _formatTinMatchStatus(String status) {
    switch (status) {
      case 'not_submitted':
        return 'Not submitted';
      case 'pending_admin_review':
        return 'Pending admin review';
      case 'verified':
        return 'Verified';
      case 'mismatch':
        return 'Mismatch detected';
      default:
        return status;
    }
  }

  Widget _buildStatCard(
      String label, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withOpacity(0.3)),
      ),
      child: Column(
        children: [
          Icon(icon, color: color, size: 28),
          const SizedBox(height: 8),
          Text(
            value,
            style: TextStyle(
                color: color,
                fontWeight: FontWeight.bold,
                fontSize: 24,
                fontFamily: 'Courier'),
          ),
          Text(label, style: TextStyle(color: Colors.grey[400], fontSize: 11)),
        ],
      ),
    );
  }

  Color _getRoleColor(String? role) {
    switch (role?.toUpperCase()) {
      case 'ADMIN':
        return const Color(0xFFFF006E);
      case 'COACH':
        return const Color(0xFFFFD700);
      case 'CLIENT':
        return const Color(0xFF4361EE);
      default:
        return Colors.grey;
    }
  }

  IconData _getRoleIcon(String? role) {
    switch (role?.toUpperCase()) {
      case 'ADMIN':
        return Icons.admin_panel_settings;
      case 'COACH':
        return Icons.school;
      case 'CLIENT':
        return Icons.person;
      default:
        return Icons.help;
    }
  }
}

// =============================================================================
// LOBBY SCREEN UPDATE - Add ADMIN login option
// Update the existing LobbyScreen to include admin access
// =============================================================================

// In the _LobbyScreenState class, update the _handlePacket method to include ADMIN routing:
/*
  if (role == 'ADMIN') {
    nextScreen = AdminDashboardScreen(currentUserProfile: profile, username: _tempUser, password: _tempPass);
  } else if (role == 'COACH') {
    nextScreen = CoachDashboardScreenV2(currentUserProfile: profile, username: _tempUser, password: _tempPass);
  } else {
    nextScreen = NeuralInterfaceV2(currentUserProfile: profile, username: _tempUser, password: _tempPass);
  }
*/

// And add an ADMIN button in the build method:
/*
  _buildGateButton(
    "ADMIN ACCESS", "System Control", Icons.security, const Color(0xFFFF006E),
    () => _showLoginDialog("ADMIN")
  ),
*/
