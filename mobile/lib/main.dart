import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kDebugMode, kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:flutter/services.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
// 1. ADDED: Permission Handler (Required for Vagus v2.6.1)
import 'package:permission_handler/permission_handler.dart';
// 2. UPDATED: Sound Engine (Switched from SoundStream to FlutterSound)
import 'package:audio_session/audio_session.dart'; 
import 'package:speech_to_text/speech_to_text.dart'; // Removed 'as stt' to match your code usage
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';
import 'package:local_auth/error_codes.dart' as auth_error;
import 'package:intl/intl.dart';
import 'dart:convert';
import 'dart:math';
import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' show PlatformDispatcher;
import 'package:url_launcher/url_launcher.dart';
import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_timezone/flutter_timezone.dart';

import 'metrics_widgets.dart';
import 'updated_screens.dart';
import 'avatar.dart';
import 'screens/onboarding_threshold_screen.dart';
import 'screens/onboarding_paid_screen.dart';
import 'screens/ai_consent_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'shared_widgets.dart';
import 'widgets/calendar_views.dart';
import 'services/device_shield.dart';
import 'services/nevedal_flutter.dart';
import 'config/app_config.dart';
import 'widgets/vault_attachment_button.dart';
import 'widgets/upload_progress_indicator.dart';
import 'widgets/nate_home_widget.dart';
import 'package:home_widget/home_widget.dart';
import 'screens/checkin_screen.dart';
import 'services/checkout_launcher.dart';
// Debug-only: inspection harness for sensitive_clinical_profile_screen.
// Reachable only via the kDebugMode-gated URL handler in _InitialRouteWidget;
// release builds short-circuit the gate, leaving this import unreferenced
// outside debug. Tree-shaking removes the harness from release bundles.
import 'screens/inspection/sensitive_profile_inspection_harness.dart';

/// Debug-only print: suppressed in production builds.
// ignore: avoid_print
void debugLog(Object? message) { if (kDebugMode) print(message); }

/// True when running as a native iOS app (not web on Safari).
/// Used to gate IAP-only flows per Apple Guideline 3.1.1.
bool get isNativeIOS => !kIsWeb && defaultTargetPlatform == TargetPlatform.iOS;

// =============================================================================

/// Canonical WS endpoint for all clients (Flutter + future HTML UIs).
/// - Web (Chrome): use the current page host (usually `localhost`)
/// - Mobile/Desktop: use LAN server IP (see `.cursorrules`)
String get defaultWsUrl {
  if (kIsWeb) {
    final uri = Uri.base;

    // Allow overriding WS endpoint on Flutter web. After Flutter upgrades, `Uri.base.fragment`
    // parsing can behave differently, so we parse from the full URL string (includes fragment).
    //
    // Supported:
    // - http://host:port/?ws=wss%3A%2F%2Fapi.sovereignsanctuary.net%2Fws
    // - http://host:port/#/?ws=wss%3A%2F%2Fapi.sovereignsanctuary.net%2Fws
    try {
      final full = uri.toString();
      final matches = RegExp(r'(^|[?&#])ws=([^&#]+)').allMatches(full).toList();
      if (matches.isNotEmpty) {
        final raw = matches.last.group(2) ?? '';
        final decoded = Uri.decodeComponent(raw).trim();
        if (decoded.isNotEmpty) return decoded;
      }
    } catch (_) {}

    // Fallback: normal query parameter (non-hash).
    final qpOverride = (uri.queryParameters['ws'] ?? '').trim();
    if (qpOverride.isNotEmpty) return qpOverride;

    final host = uri.host;
    final isLocal = host == 'localhost' || host == '127.0.0.1' || host.endsWith('.local');
    if (isLocal) {
      return 'wss://api.sovereignsanctuary.net/ws';
    }

    // When hosted on app/coach subdomains, use api.sovereignsanctuary.net for WebSocket
    if (host == 'app.sovereignsanctuary.net' || host.startsWith('app.') ||
        host == 'coach.sovereignsanctuary.net' || host.startsWith('coach.')) {
      return 'wss://api.sovereignsanctuary.net/ws';
    }

    final scheme = uri.scheme == 'https' ? 'wss' : 'ws';
    return '$scheme://$host/ws';
  }

  // Native mobile (iOS/Android) — use production WebSocket
  return 'wss://api.sovereignsanctuary.net/ws';
}

/// Returns the locked portal mode based on the web hostname.
/// - 'CLIENT' on app.sovereignsanctuary.net (universal gateway, client-focused)
/// - 'COACH'  on coach.sovereignsanctuary.net (coach-only)
/// - null     on localhost / dev (show full lobby for development)
String? get portalMode {
  if (!kIsWeb) return null;
  final host = Uri.base.host;
  if (host == 'coach.sovereignsanctuary.net' || host.startsWith('coach.')) return 'COACH';
  if (host == 'app.sovereignsanctuary.net' || host.startsWith('app.')) return 'CLIENT';
  return null; // localhost / dev — show full lobby
}

String _apiBaseFromWsUrl(String wsUrl) {
  try {
    final u = Uri.parse(wsUrl.trim());
    final scheme = (u.scheme == 'wss') ? 'https' : 'http';
    final host = u.host;
    if (host.isEmpty) return '';

    // If WS uses the bridge port (8765), map to backend port (8000) in dev.
    final port = (u.hasPort && u.port == 8765) ? 8000 : (u.hasPort ? u.port : null);
    return Uri(scheme: scheme, host: host, port: port).toString();
  } catch (_) {
    return '';
  }
}

/// Canonical HTTP base URL for REST endpoints (sessions, zoom, etc).
/// Supports a `api=` override on Flutter web (same parsing rules as `ws=`).
String get defaultApiBaseUrl {
  if (kIsWeb) {
    final uri = Uri.base;
    try {
      final full = uri.toString();
      final matches = RegExp(r'(^|[?&#])api=([^&#]+)').allMatches(full).toList();
      if (matches.isNotEmpty) {
        final raw = matches.last.group(2) ?? '';
        final decoded = Uri.decodeComponent(raw).trim();
        if (decoded.isNotEmpty) return decoded;
      }
    } catch (_) {}

    final qpOverride = (uri.queryParameters['api'] ?? '').trim();
    if (qpOverride.isNotEmpty) return qpOverride;

    // If the web app is hosted on app/coach subdomains, the API is on "api" subdomain.
    // This avoids calling `https://app.../api/...` which is typically a static host (404).
    final host = uri.host;
    if (host == 'app.sovereignsanctuary.net' || host.startsWith('app.') ||
        host == 'coach.sovereignsanctuary.net' || host.startsWith('coach.')) {
      return '${uri.scheme}://api.sovereignsanctuary.net';
    }

    // Default: derive from the selected WS URL (handles the `ws=` override case).
    final derived = _apiBaseFromWsUrl(defaultWsUrl);
    if (derived.isNotEmpty) return derived;

    // Last resort: use page host.
    final isLocal = host == 'localhost' || host == '127.0.0.1' || host.endsWith('.local');
    if (isLocal) return 'http://$host:8000';
    return '${uri.scheme}://$host';
  }

  // Production fallback — never expose internal IPs to clients
  return 'https://api.sovereignsanctuary.net';
}

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Prevent websocket connection failures from surfacing as uncaught
  // "RethrownDartError" in Flutter web debug runtime.
  FlutterError.onError = (details) {
    FlutterError.presentError(details);
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    // Log and mark handled.
    // ignore: avoid_print
    debugLog("UNCAUGHT (handled): $error");
    return true;
  };

  // ── Home Screen Widget initialization ──
  NateWidgetService.initialize();

  // ── HIVE DEFENSE v4.3: Device Shield — run full security check on launch ──
  if (!kIsWeb) {
    DeviceShield.instance.runFullCheck().then((report) {
      debugLog('>>> [DeviceShield] Launch check: ${report.overallStatus.name} '
          '(${report.checks.where((c) => c.passed).length}/${report.checks.length} passed)');
      if (report.overallStatus == ShieldStatus.locked) {
        debugLog('>>> [DeviceShield] CRITICAL: Device compromised — degraded mode');
      }
    }).catchError((e) {
      debugLog('>>> [DeviceShield] Non-blocking launch error: $e');
    });
  }

  runApp(const MaterialApp(
    home: _InitialRouteWidget(),
    debugShowCheckedModeBanner: false,
    // ... theme data ...
  ));
}

class SovereignHybridApp extends StatelessWidget {
  const SovereignHybridApp({super.key});
  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Sovereign Sanctuary',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF050505),
        primaryColor: const Color(0xFFFFD700), // Sovereign Gold
        cardColor: const Color(0xFF111111),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFFFFD700),
          secondary: Color(0xFF003366), // Deep Navy
          error: Colors.redAccent,
          surface: Color(0xFF1E1E1E),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xFF111111),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          enabledBorder: const OutlineInputBorder(borderSide: BorderSide(color: Color(0xFF333333))),
          focusedBorder: const OutlineInputBorder(borderSide: BorderSide(color: Color(0xFF003366))),
          hintStyle: const TextStyle(color: Colors.grey),
        ),
      ),
      // MIGRATION REQUIREMENT: Boot to Lobby for Role Selection
      home: const _InitialRouteWidget(),
    );
  }
}

/// Decides initial route:
/// - ResetPasswordScreen if ?reset_token= in URL (web)
/// - FamilyInviteAcceptScreen if /family-invite?code= in URL (web)
/// - LobbyScreen otherwise
class _InitialRouteWidget extends StatelessWidget {
  const _InitialRouteWidget();

  @override
  Widget build(BuildContext context) {
    if (kIsWeb) {
      // --- Password Reset ---
      String? resetToken;
      try {
        resetToken = Uri.base.queryParameters['reset_token'];
        if (resetToken == null || resetToken.isEmpty) {
          final frag = Uri.base.fragment;
          if (frag.isNotEmpty) {
            final params = Uri(query: frag.replaceFirst(RegExp(r'^[/?]+'), '')).queryParameters;
            resetToken = params['reset_token'];
          }
        }
      } catch (_) {}
      if (resetToken != null && resetToken.isNotEmpty) {
        return ResetPasswordScreen(initialToken: resetToken);
      }

      // --- Family Invite Deep Link ---
      String? familyCode;
      try {
        // Check path for /family-invite
        final path = Uri.base.path.toLowerCase();
        final isFamilyPath = path.contains('family-invite');
        // Get code from query params
        familyCode = Uri.base.queryParameters['code'];
        // Also check fragment (hash routing)
        if (familyCode == null || familyCode.isEmpty) {
          final frag = Uri.base.fragment;
          if (frag.isNotEmpty) {
            final fragParams = Uri(query: frag.replaceFirst(RegExp(r'^[/?]+'), '')).queryParameters;
            familyCode = fragParams['code'];
            // Also check if fragment contains family-invite
            if (familyCode == null && frag.contains('family-invite')) {
              final afterQ = frag.contains('?') ? frag.split('?').last : '';
              familyCode = Uri.tryParse('http://x?$afterQ')?.queryParameters['code'];
            }
          }
        }
        // Only route to invite screen if we have a code OR path matches
        if ((familyCode == null || familyCode.isEmpty) && isFamilyPath) {
          // Path matches but no code — show screen anyway (it will show error)
          familyCode = '';
        }
      } catch (_) {}
      if (familyCode != null) {
        return FamilyInviteAcceptScreen(inviteCode: familyCode);
      }

      // --- Stripe Registration Return ---
      try {
        final regStatus = Uri.base.queryParameters['registration'];
        if (regStatus == null || regStatus.isEmpty) {
          final frag = Uri.base.fragment;
          if (frag.contains('registration=')) {
            final p = Uri(query: frag.replaceFirst(RegExp(r'^[/?]+'), '')).queryParameters;
            if (p['registration'] == 'success') {
              return const LobbyScreen(registrationSuccess: true);
            }
          }
        }
        if (regStatus == 'success') {
          return const LobbyScreen(registrationSuccess: true);
        }
      } catch (_) {}

      // --- Debug-only: Sensitive Profile Inspection Harness ---
      // Reachable in `flutter run --debug` via either:
      //   http://localhost:PORT/?dev=sensitive-profile-inspection
      //   http://localhost:PORT/#/dev/sensitive-profile-inspection
      // The `kDebugMode` constant is `false` in release/profile builds, so this
      // entire branch is dead-stripped from production bundles along with the
      // harness widget tree it points at.
      if (kDebugMode) {
        try {
          bool wantsInspection = false;
          final dev = Uri.base.queryParameters['dev'];
          if (dev == 'sensitive-profile-inspection') {
            wantsInspection = true;
          }
          if (!wantsInspection) {
            final path = Uri.base.path.toLowerCase();
            if (path.contains('/dev/sensitive-profile-inspection')) {
              wantsInspection = true;
            }
          }
          if (!wantsInspection) {
            final frag = Uri.base.fragment.toLowerCase();
            if (frag.contains('dev/sensitive-profile-inspection') ||
                frag.contains('dev=sensitive-profile-inspection')) {
              wantsInspection = true;
            }
          }
          if (wantsInspection) {
            return const SensitiveProfileInspectionHarness();
          }
        } catch (_) {}
      }
    }
    return const LobbyScreen();
  }
}

// =============================================================================
// FAMILY INVITE ACCEPTANCE SCREEN (deep-link flow)
// =============================================================================

class FamilyInviteAcceptScreen extends StatefulWidget {
  final String inviteCode;
  const FamilyInviteAcceptScreen({super.key, required this.inviteCode});

  @override
  State<FamilyInviteAcceptScreen> createState() => _FamilyInviteAcceptScreenState();
}

class _FamilyInviteAcceptScreenState extends State<FamilyInviteAcceptScreen> {
  // Design tokens
  static const _bgVoid = Color(0xFF050505);
  static const _bgCard = Color(0xFF111111);
  static const _bgElevated = Color(0xFF1A1A1A);
  static const _gold = Color(0xFFC9A962);
  static const _goldBright = Color(0xFFE8D5A3);
  static const _cyan = Color(0xFF4ECDC4);
  static const _textPrimary = Color(0xFFFFFFFF);
  static const _textSecondary = Color(0xFF888888);
  static const _red = Color(0xFFEF4444);

  WebSocketChannel? _socket;
  String _status = 'loading'; // loading, valid, invalid, expired, accepted, error
  String _inviterName = '';
  String _inviteeName = '';
  String _role = 'DEPENDENT';
  String _errorMsg = '';

  // Consent checkboxes
  bool _privacyAgreed = false;
  bool _termsAgreed = false;
  bool _ageConfirmed = false;
  bool _accepting = false;

  // Auth state
  bool _isLoggedIn = false;
  String? _authUid;
  bool _showLoginForm = false;
  final _usernameCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  bool _loggingIn = false;
  String _loginError = '';
  bool _obscurePassword = true;

  @override
  void initState() {
    super.initState();
    if (widget.inviteCode.isEmpty) {
      setState(() {
        _status = 'invalid';
        _errorMsg = 'No invite code provided in the link.';
      });
    } else {
      _connectAndLookup();
    }
  }

  @override
  void dispose() {
    _socket?.sink.close();
    _usernameCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  void _connectAndLookup() {
    final wsUrl = defaultWsUrl;
    try {
      _socket = WebSocketChannel.connect(Uri.parse(wsUrl));
      _socket!.stream.listen(_onMessage, onError: (_) {
        if (mounted) setState(() { _status = 'error'; _errorMsg = 'Connection failed.'; });
      }, onDone: () {
        if (mounted && _status == 'loading') {
          setState(() { _status = 'error'; _errorMsg = 'Connection closed.'; });
        }
      });
      // Send lookup immediately (no auth required)
      _socket!.sink.add(jsonEncode({
        'type': 'lookup_family_invite',
        'token': widget.inviteCode.toUpperCase(),
      }));
    } catch (e) {
      setState(() { _status = 'error'; _errorMsg = 'Could not connect to server.'; });
    }
  }

  void _onMessage(dynamic raw) {
    try {
      final data = jsonDecode(raw) as Map<String, dynamic>;
      final type = (data['type'] ?? '').toString();

      if (type == 'family_invite_details') {
        final valid = data['valid'] == true;
        setState(() {
          if (valid) {
            _status = 'valid';
            _inviterName = data['inviter_name'] ?? 'A family member';
            _inviteeName = data['invitee_name'] ?? '';
            _role = data['role'] ?? 'DEPENDENT';
          } else {
            _status = data['message']?.toString().contains('expired') == true ? 'expired' : 'invalid';
            _errorMsg = data['message'] ?? 'Invalid invite code.';
          }
        });
      } else if (type == 'connected') {
        // Bridge sends connected on open — send lookup if we haven't yet
      } else if (type == 'login_success' || type == 'auth_success') {
        setState(() {
          _isLoggedIn = true;
          _authUid = (data['profile']?['hardware_id'] ?? '').toString();
          _loggingIn = false;
          _showLoginForm = false;
          _loginError = '';
        });
      } else if (type == 'login_failed' || type == 'login_failure') {
        setState(() {
          _loggingIn = false;
          _loginError = data['message']?.toString() ?? 'Login failed.';
        });
      } else if (type == 'family_invite_accepted') {
        setState(() { _status = 'accepted'; });
      } else if (type == 'family_invite_error') {
        setState(() {
          _accepting = false;
          _errorMsg = data['message'] ?? 'Could not accept invite.';
        });
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(_errorMsg),
          backgroundColor: _red,
        ));
      }
    } catch (_) {}
  }

  void _doLogin() {
    final user = _usernameCtrl.text.trim();
    final pass = _passwordCtrl.text.trim();
    if (user.isEmpty || pass.isEmpty) return;
    setState(() { _loggingIn = true; _loginError = ''; });
    _socket?.sink.add(jsonEncode({
      'type': 'login_request',
      'username': user,
      'password': pass,
    }));
  }

  void _acceptInvite() {
    if (!_privacyAgreed || !_termsAgreed || !_ageConfirmed) return;
    if (!_isLoggedIn) {
      setState(() { _showLoginForm = true; });
      return;
    }
    setState(() { _accepting = true; });
    _socket?.sink.add(jsonEncode({
      'type': 'accept_family_invite',
      'token': widget.inviteCode.toUpperCase(),
      'consent_agreed': true,
      'consent_version': 'v13.0_2026',
    }));
  }

  void _goHome() {
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LobbyScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgVoid,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 40),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: _buildContent(),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildContent() {
    switch (_status) {
      case 'loading':
        return _buildLoading();
      case 'valid':
        return _buildInviteForm();
      case 'accepted':
        return _buildAccepted();
      case 'expired':
        return _buildError('Invitation Expired', _errorMsg);
      case 'invalid':
        return _buildError('Invalid Invitation', _errorMsg);
      default:
        return _buildError('Something Went Wrong', _errorMsg);
    }
  }

  Widget _buildLoading() {
    return Column(
      children: [
        Text('SANCTUARY', style: TextStyle(color: _gold, fontSize: 28, fontFamily: 'Cormorant Garamond', fontWeight: FontWeight.w300, letterSpacing: 6)),
        const SizedBox(height: 40),
        const CircularProgressIndicator(color: _gold),
        const SizedBox(height: 20),
        const Text('Verifying invitation...', style: TextStyle(color: _textSecondary, fontSize: 14)),
      ],
    );
  }

  Widget _buildError(String title, String message) {
    return Column(
      children: [
        Text('SANCTUARY', style: TextStyle(color: _gold, fontSize: 28, fontFamily: 'Cormorant Garamond', fontWeight: FontWeight.w300, letterSpacing: 6)),
        const SizedBox(height: 40),
        Container(
          padding: const EdgeInsets.all(32),
          decoration: BoxDecoration(
            color: _bgCard,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _bgElevated),
          ),
          child: Column(
            children: [
              Icon(Icons.error_outline, color: _red, size: 48),
              const SizedBox(height: 16),
              Text(title, style: const TextStyle(color: _textPrimary, fontSize: 20, fontWeight: FontWeight.w600, fontFamily: 'Cormorant Garamond')),
              const SizedBox(height: 12),
              Text(message, style: const TextStyle(color: _textSecondary, fontSize: 14), textAlign: TextAlign.center),
              const SizedBox(height: 24),
              TextButton(onPressed: _goHome, child: const Text('Go to Home', style: TextStyle(color: _cyan))),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildAccepted() {
    return Column(
      children: [
        Text('SANCTUARY', style: TextStyle(color: _gold, fontSize: 28, fontFamily: 'Cormorant Garamond', fontWeight: FontWeight.w300, letterSpacing: 6)),
        const SizedBox(height: 40),
        Container(
          padding: const EdgeInsets.all(32),
          decoration: BoxDecoration(
            color: _bgCard,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _gold.withOpacity(0.3)),
          ),
          child: Column(
            children: [
              Icon(Icons.check_circle_outline, color: _gold, size: 56),
              const SizedBox(height: 16),
              const Text("You're In!", style: TextStyle(color: _goldBright, fontSize: 24, fontWeight: FontWeight.w600, fontFamily: 'Cormorant Garamond')),
              const SizedBox(height: 12),
              Text(
                "You've joined $_inviterName's Family Circle.\nLittle Nate is ready to welcome you.",
                style: const TextStyle(color: _textSecondary, fontSize: 14, height: 1.6),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 28),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: _gold,
                    foregroundColor: _bgVoid,
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  onPressed: _goHome,
                  child: const Text('ENTER THE SANCTUARY', style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1.5)),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildInviteForm() {
    final allConsented = _privacyAgreed && _termsAgreed && _ageConfirmed;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text('SANCTUARY', style: TextStyle(color: _gold, fontSize: 28, fontFamily: 'Cormorant Garamond', fontWeight: FontWeight.w300, letterSpacing: 6)),
        const SizedBox(height: 32),

        // Invitation card
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(28),
          decoration: BoxDecoration(
            color: _bgCard,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _gold.withOpacity(0.3)),
          ),
          child: Column(
            children: [
              const Icon(Icons.family_restroom, color: _gold, size: 40),
              const SizedBox(height: 12),
              const Text("You've Been Invited", style: TextStyle(color: _goldBright, fontSize: 22, fontWeight: FontWeight.w600, fontFamily: 'Cormorant Garamond')),
              const SizedBox(height: 8),
              Text.rich(TextSpan(children: [
                TextSpan(text: _inviterName, style: const TextStyle(color: _gold, fontWeight: FontWeight.w600)),
                const TextSpan(text: ' wants you to join their Family Circle in the Sovereign Sanctuary.'),
              ]), style: const TextStyle(color: _textSecondary, fontSize: 14, height: 1.5), textAlign: TextAlign.center),
              if (_inviteeName.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text('Welcome, $_inviteeName', style: const TextStyle(color: _textPrimary, fontSize: 15)),
              ],
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                decoration: BoxDecoration(color: _bgElevated, borderRadius: BorderRadius.circular(8)),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.verified_user, color: _cyan, size: 16),
                  const SizedBox(width: 8),
                  Text('Role: ${_role == "SPOUSE" ? "Spouse (free)" : "Dependent (free)"}', style: const TextStyle(color: _textSecondary, fontSize: 13)),
                ]),
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),

        // Features
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(color: _bgCard, borderRadius: BorderRadius.circular(12), border: Border.all(color: _bgElevated)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('As a family member, you get:', style: TextStyle(color: _textPrimary, fontSize: 14, fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              _featureRow(Icons.chat_bubble_outline, 'Unlimited conversations with Nate AI'),
              _featureRow(Icons.mic, 'Voice mode'),
              _featureRow(Icons.show_chart, 'Full progress tracking'),
              _featureRow(Icons.lock_outline, 'Private — your conversations remain yours alone'),
              const SizedBox(height: 8),
              const Text('At no cost to you.', style: TextStyle(color: _gold, fontSize: 13, fontWeight: FontWeight.w500)),
            ],
          ),
        ),
        const SizedBox(height: 20),

        // Legal consent section
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(color: _bgCard, borderRadius: BorderRadius.circular(12), border: Border.all(color: _bgElevated)),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('LEGAL AGREEMENTS', style: TextStyle(color: _gold, fontSize: 12, fontWeight: FontWeight.bold, letterSpacing: 2)),
              const SizedBox(height: 4),
              const Text('Please review and accept before continuing.', style: TextStyle(color: _textSecondary, fontSize: 12)),
              const SizedBox(height: 16),

              // Privacy Policy
              _consentTile(
                value: _privacyAgreed,
                onChanged: (v) => setState(() => _privacyAgreed = v ?? false),
                label: 'I have read and agree to the ',
                linkText: 'Privacy Policy',
                url: 'https://app.sovereignsanctuary.net/privacy.html',
              ),
              const SizedBox(height: 10),

              // Terms of Use
              _consentTile(
                value: _termsAgreed,
                onChanged: (v) => setState(() => _termsAgreed = v ?? false),
                label: 'I have read and agree to the ',
                linkText: 'Terms of Use & Therapeutic Waiver',
                url: 'https://app.sovereignsanctuary.net/terms.html',
              ),
              const SizedBox(height: 10),

              // Age confirmation
              _consentTile(
                value: _ageConfirmed,
                onChanged: (v) => setState(() => _ageConfirmed = v ?? false),
                label: 'I confirm I am at least 18 years of age',
                linkText: '',
                url: '',
              ),
            ],
          ),
        ),
        const SizedBox(height: 20),

        // Login form (shown if not logged in and they try to accept)
        if (_showLoginForm && !_isLoggedIn) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(color: _bgCard, borderRadius: BorderRadius.circular(12), border: Border.all(color: _cyan.withOpacity(0.3))),
            child: Column(
              children: [
                const Text('Sign In to Accept', style: TextStyle(color: _cyan, fontSize: 16, fontWeight: FontWeight.w600)),
                const SizedBox(height: 4),
                const Text('You need an account to join the family circle.', style: TextStyle(color: _textSecondary, fontSize: 12)),
                const SizedBox(height: 16),
                TextField(
                  controller: _usernameCtrl,
                  style: const TextStyle(color: _textPrimary),
                  decoration: InputDecoration(
                    hintText: 'Username',
                    hintStyle: const TextStyle(color: _textSecondary),
                    filled: true,
                    fillColor: _bgElevated,
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _passwordCtrl,
                  obscureText: _obscurePassword,
                  style: const TextStyle(color: _textPrimary),
                  decoration: InputDecoration(
                    hintText: 'Password',
                    hintStyle: const TextStyle(color: _textSecondary),
                    filled: true,
                    fillColor: _bgElevated,
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
                    suffixIcon: IconButton(
                      icon: Icon(_obscurePassword ? Icons.visibility_off : Icons.visibility, color: _textSecondary),
                      onPressed: () => setState(() => _obscurePassword = !_obscurePassword),
                    ),
                  ),
                ),
                if (_loginError.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(_loginError, style: const TextStyle(color: _red, fontSize: 12)),
                ],
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: _cyan,
                      foregroundColor: _bgVoid,
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                    ),
                    onPressed: _loggingIn ? null : _doLogin,
                    child: _loggingIn
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: _bgVoid))
                        : const Text('SIGN IN', style: TextStyle(fontWeight: FontWeight.bold, letterSpacing: 1)),
                  ),
                ),
                const SizedBox(height: 10),
                TextButton(
                  onPressed: _goHome,
                  child: const Text("Don't have an account? Create one first", style: TextStyle(color: _textSecondary, fontSize: 12)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 20),
        ],

        // Accept button
        if (_isLoggedIn && allConsented) ...[
          const SizedBox(height: 4),
          Row(children: [
            const Icon(Icons.check_circle, color: _cyan, size: 16),
            const SizedBox(width: 6),
            Text('Signed in as ${_usernameCtrl.text.trim().isNotEmpty ? _usernameCtrl.text.trim() : "you"}', style: const TextStyle(color: _cyan, fontSize: 12)),
          ]),
          const SizedBox(height: 12),
        ],

        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: allConsented ? _gold : _gold.withOpacity(0.3),
              foregroundColor: _bgVoid,
              padding: const EdgeInsets.symmetric(vertical: 16),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
            ),
            onPressed: (allConsented && !_accepting) ? _acceptInvite : null,
            child: _accepting
                ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: _bgVoid))
                : Text(
                    _isLoggedIn ? 'ACCEPT INVITATION' : 'CONTINUE',
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.5,
                      color: allConsented ? _bgVoid : _bgVoid.withOpacity(0.5),
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 16),
        TextButton(onPressed: _goHome, child: const Text('Cancel', style: TextStyle(color: _textSecondary, fontSize: 13))),
      ],
    );
  }

  Widget _featureRow(IconData icon, String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(children: [
        Icon(icon, color: _cyan, size: 18),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: const TextStyle(color: _textSecondary, fontSize: 13))),
      ]),
    );
  }

  Widget _consentTile({
    required bool value,
    required ValueChanged<bool?> onChanged,
    required String label,
    required String linkText,
    required String url,
  }) {
    return InkWell(
      onTap: () => onChanged(!value),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 24, height: 24,
            child: Checkbox(
              value: value,
              onChanged: onChanged,
              activeColor: _gold,
              checkColor: _bgVoid,
              side: const BorderSide(color: _textSecondary),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: linkText.isEmpty
                ? Text(label, style: const TextStyle(color: _textSecondary, fontSize: 13))
                : Text.rich(TextSpan(children: [
                    TextSpan(text: label, style: const TextStyle(color: _textSecondary, fontSize: 13)),
                    WidgetSpan(child: GestureDetector(
                      onTap: () { if (url.isNotEmpty) launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication); },
                      child: Text(linkText, style: const TextStyle(color: _cyan, fontSize: 13, decoration: TextDecoration.underline)),
                    )),
                  ])),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// RESET PASSWORD SCREEN (token-based flow)
// =============================================================================

class ResetPasswordScreen extends StatefulWidget {
  final String? initialToken;

  const ResetPasswordScreen({super.key, this.initialToken});

  @override
  State<ResetPasswordScreen> createState() => _ResetPasswordScreenState();
}

class _ResetPasswordScreenState extends State<ResetPasswordScreen> {
  WebSocketChannel? _channel;
  final _tokenCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _isSubmitting = false;
  bool _obscurePass = true;
  bool _obscureConfirm = true;
  String get _serverUrl => defaultWsUrl;

  @override
  void initState() {
    super.initState();
    if (widget.initialToken != null && widget.initialToken!.isNotEmpty) {
      _tokenCtrl.text = widget.initialToken!;
    }
    _connect();
  }

  void _connect() {
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_serverUrl));
      _channel!.stream.listen(
        _handlePacket,
        onError: (e) {
          debugLog("Connection error: $e");
          if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Connection interrupted. Reconnecting...")));
        },
        onDone: () {},
      );
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Could not connect: $e")));
    }
  }

  void _handlePacket(dynamic msg) {
    try {
      final data = jsonDecode(msg);
      if (data['type'] == 'password_reset_success') {
        if (mounted) {
          setState(() => _isSubmitting = false);
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Password updated. Please log in."),
            backgroundColor: Colors.green,
          ));
          Navigator.pushAndRemoveUntil(
            context,
            MaterialPageRoute(builder: (_) => const LobbyScreen()),
            (r) => false,
          );
        }
      } else if (data['type'] == 'error') {
        if (mounted) {
          setState(() => _isSubmitting = false);
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(data['message'] ?? "Error"),
            backgroundColor: Colors.red,
          ));
        }
      }
    } catch (_) {}
  }

  void _submit() {
    final token = _tokenCtrl.text.trim();
    final pass = _passCtrl.text.trim();
    final confirm = _confirmCtrl.text.trim();
    if (token.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Enter the reset code from your email.")));
      return;
    }
    if (pass.length < 6) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Password must be at least 6 characters.")));
      return;
    }
    if (pass != confirm) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Passwords do not match.")));
      return;
    }
    setState(() => _isSubmitting = true);
    _channel?.sink.add(jsonEncode({
      "type": "forgot_password_confirm",
      "token": token,
      "new_password": pass,
    }));
  }

  @override
  void dispose() {
    _channel?.sink.close();
    _tokenCtrl.dispose();
    _passCtrl.dispose();
    _confirmCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        title: const Text("Reset Password", style: TextStyle(color: Colors.white)),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const LobbyScreen())),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 40),
              const Text("Enter the reset code from your email and choose a new password.", style: TextStyle(color: Colors.white70, fontSize: 14)),
              const SizedBox(height: 24),
              TextField(
                controller: _tokenCtrl,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: "Reset code",
                  prefixIcon: Icon(Icons.vpn_key, color: Colors.grey),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _passCtrl,
                obscureText: _obscurePass,
                style: const TextStyle(color: Colors.white),
                decoration: InputDecoration(
                  labelText: "New password (min 6 characters)",
                  prefixIcon: const Icon(Icons.lock, color: Colors.grey),
                  suffixIcon: IconButton(
                    icon: Icon(_obscurePass ? Icons.visibility_off : Icons.visibility, color: Colors.grey),
                    onPressed: () => setState(() => _obscurePass = !_obscurePass),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _confirmCtrl,
                obscureText: _obscureConfirm,
                style: const TextStyle(color: Colors.white),
                decoration: InputDecoration(
                  labelText: "Confirm password",
                  prefixIcon: const Icon(Icons.lock_outline, color: Colors.grey),
                  suffixIcon: IconButton(
                    icon: Icon(_obscureConfirm ? Icons.visibility_off : Icons.visibility, color: Colors.grey),
                    onPressed: () => setState(() => _obscureConfirm = !_obscureConfirm),
                  ),
                ),
              ),
              const SizedBox(height: 32),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFFD700), foregroundColor: Colors.black, padding: const EdgeInsets.symmetric(vertical: 16)),
                onPressed: _isSubmitting ? null : _submit,
                child: _isSubmitting ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2)) : const Text("Reset Password"),
              ),
              const SizedBox(height: 16),
              TextButton(
                onPressed: () => Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const LobbyScreen())),
                child: const Text("Back to Login", style: TextStyle(color: Colors.grey)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// =============================================================================
// MODULE 1: HARDWARE IDENTITY ENGINE (CRASH-PROOF)
// Status: FIXED (Catches MissingPluginException to prevent Hang)
// =============================================================================
class HardwareIdentity {
  static const platform = MethodChannel('com.sovereign.lab/observer');
  
  // High-Security Storage (Preserved from your snippet - Excellent)
  final _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock)
  );
  
  final _auth = LocalAuthentication();
  String _hardwareID = "INITIALIZING...";

  // 1.1: Deep Hardware Fingerprinting (Fixed Logic)
  Future<String> getDeviceFingerprint() async {
    try {
      final String? result = await platform.invokeMethod('getHardwareID');
      if (result != null && result.length > 5) {
        _hardwareID = result;
        debugLog(">>> [IDENTITY] Hardware ID Verified: $_hardwareID");
        return _hardwareID;
      } else {
        throw PlatformException(code: "INVALID_ID", message: "ID too short/null");
      }
    } on MissingPluginException {
      // 1. CRITICAL FIX: Specifically catch the Missing Plugin error
      debugLog("âš ï¸ [WARN] Native Bridge Missing - Using Dev Fallback");
      _hardwareID = "DEV_BYPASS_${Random().nextInt(99999)}";
      return _hardwareID;
    } catch (e) {
      // Catch-all for any other weirdness
      debugLog("!!! [IDENTITY] General Error: $e");
      _hardwareID = "ERROR_BYPASS_${Random().nextInt(99999)}";
      return _hardwareID;
    }
  }

  // 1.2: Persistent Session Management
  Future<void> saveSession(String username, String token, Map<String, dynamic> profile) async {
    try {
      await _storage.write(key: 'session_token', value: token);
      await _storage.write(key: 'session_user', value: username);
      await _storage.write(key: 'user_profile', value: jsonEncode(profile)); // Fixed Key Name consistency
      await _storage.write(key: 'last_login', value: DateTime.now().toIso8601String());
      debugLog(">>> [IDENTITY] Session Secured in Vault.");
    } catch (e) {
      debugLog("!!! [IDENTITY] Write Error: $e");
    }
  }

  Future<Map<String, dynamic>?> recoverSession() async {
    try {
      String? token = await _storage.read(key: 'session_token');
      String? profileRaw = await _storage.read(key: 'user_profile'); // Matching key from saveSession
      
      if (token != null && profileRaw != null) {
        debugLog(">>> [IDENTITY] Found existing session token.");
        
        // 1.3: Biometric Gate
        bool authenticated = await _authenticateBiometrics();
        if (authenticated) {
          debugLog(">>> [IDENTITY] Biometric Auth Success. Unlocking Vault.");
          return jsonDecode(profileRaw);
        } else {
          debugLog("!!! [IDENTITY] Biometric Auth Failed or Cancelled.");
          // Security Choice: Do we clear session on failed bio? 
          // For now, return null but keep session (user can retry).
          return null; 
        }
      }
    } catch (e) {
      debugLog("!!! [IDENTITY] Recovery Error: $e");
      await clearSession();
    }
    return null;
  }

  Future<void> clearSession() async {
    await _storage.deleteAll();
    debugLog(">>> [IDENTITY] Secure Storage Wiped.");
  }

  // 1.4: Detailed Biometric Logic
  Future<bool> _authenticateBiometrics() async {
    try {
      bool canCheck = await _auth.canCheckBiometrics;
      bool isDeviceSupported = await _auth.isDeviceSupported();
      
      if (!canCheck || !isDeviceSupported) {
        debugLog(">>> [IDENTITY] Biometrics not available. Bypassing.");
        return true; 
      }

      return await _auth.authenticate(
        localizedReason: 'Sovereign Sanctuary Access Required',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: false,
          useErrorDialogs: true
        )
      );
    } catch (e) {
      debugLog("!!! [IDENTITY] Biometric Exception: $e");
      return true; // Fail Open for Development, switch to 'return false' for Prod
    }
  }

  // =========================================================================
  // 1.5: Biometric-Gated Auto-Login (Face ID / Fingerprint)
  // =========================================================================

  /// Save login credentials for biometric re-authentication.
  /// Only called for CLIENT and COACH roles — never for ADMIN.
  Future<void> saveCredentials(String username, String password, String role) async {
    try {
      await _storage.write(key: 'bio_username', value: username);
      await _storage.write(key: 'bio_password', value: password);
      await _storage.write(key: 'bio_role', value: role);
      await _storage.write(key: 'bio_enabled', value: 'true');
      debugLog(">>> [IDENTITY] Biometric credentials saved for $role.");
    } catch (e) {
      debugLog("!!! [IDENTITY] saveCredentials error: $e");
    }
  }

  /// Check whether saved biometric credentials exist (no biometric prompt).
  Future<bool> hasSavedCredentials() async {
    try {
      final enabled = await _storage.read(key: 'bio_enabled');
      if (enabled != 'true') return false;
      final user = await _storage.read(key: 'bio_username');
      final pass = await _storage.read(key: 'bio_password');
      return user != null && user.isNotEmpty && pass != null && pass.isNotEmpty;
    } catch (e) {
      debugLog("!!! [IDENTITY] hasSavedCredentials error: $e");
      return false;
    }
  }

  /// Retrieve the stored username for display (no biometric prompt).
  Future<String?> getSavedUsername() async {
    try {
      return await _storage.read(key: 'bio_username');
    } catch (_) {
      return null;
    }
  }

  /// Recover credentials behind a biometric gate (Face ID / Fingerprint).
  /// Returns {username, password, role} on success, null on failure/cancel.
  Future<Map<String, String>?> recoverCredentials() async {
    try {
      final enabled = await _storage.read(key: 'bio_enabled');
      if (enabled != 'true') return null;

      final user = await _storage.read(key: 'bio_username');
      final pass = await _storage.read(key: 'bio_password');
      final role = await _storage.read(key: 'bio_role');

      if (user == null || pass == null || role == null) return null;

      bool authenticated = await _authenticateBiometrics();
      if (!authenticated) {
        debugLog("!!! [IDENTITY] Biometric auth failed for auto-login.");
        return null;
      }

      debugLog(">>> [IDENTITY] Biometric credentials recovered for $role.");
      return {'username': user, 'password': pass, 'role': role};
    } catch (e) {
      debugLog("!!! [IDENTITY] recoverCredentials error: $e");
      return null;
    }
  }

  /// Check if biometrics are available on this device.
  Future<bool> isBiometricAvailable() async {
    try {
      if (kIsWeb) return false;
      final canCheck = await _auth.canCheckBiometrics;
      final isSupported = await _auth.isDeviceSupported();
      return canCheck && isSupported;
    } catch (_) {
      return false;
    }
  }

  /// Clear stored biometric credentials (logout / switch account).
  Future<void> clearCredentials() async {
    try {
      await _storage.delete(key: 'bio_username');
      await _storage.delete(key: 'bio_password');
      await _storage.delete(key: 'bio_role');
      await _storage.delete(key: 'bio_enabled');
      await _storage.delete(key: 'bio_declined');
      debugLog(">>> [IDENTITY] Biometric credentials cleared.");
    } catch (e) {
      debugLog("!!! [IDENTITY] clearCredentials error: $e");
    }
  }

  /// Set biometric login enabled/disabled (settings toggle).
  Future<void> setBiometricEnabled(bool enabled) async {
    try {
      if (enabled) {
        await _storage.write(key: 'bio_enabled', value: 'true');
      } else {
        await clearCredentials();
      }
    } catch (e) {
      debugLog("!!! [IDENTITY] setBiometricEnabled error: $e");
    }
  }

  /// Check if biometric login is currently enabled.
  Future<bool> isBiometricEnabled() async {
    try {
      final val = await _storage.read(key: 'bio_enabled');
      return val == 'true';
    } catch (_) {
      return false;
    }
  }

  /// Check if user previously declined the biometric opt-in prompt.
  Future<bool> hasBiometricDeclined() async {
    try {
      final val = await _storage.read(key: 'bio_declined');
      return val == 'true';
    } catch (_) {
      return false;
    }
  }

  /// Mark that the user declined the biometric opt-in prompt.
  Future<void> setBiometricDeclined(bool declined) async {
    try {
      if (declined) {
        await _storage.write(key: 'bio_declined', value: 'true');
      } else {
        await _storage.delete(key: 'bio_declined');
      }
    } catch (e) {
      debugLog("!!! [IDENTITY] setBiometricDeclined error: $e");
    }
  }
}
// -----------------------------------------------------------------------------
// END OF PART 1
// -----------------------------------------------------------------------------

class NervousSystemPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = const Color(0xFF00FFFF).withOpacity(0.05);
    for (double i = 0; i < size.width; i += 40) { for (double j = 0; j < size.height; j += 40) { canvas.drawCircle(Offset(i, j), 1, paint); }}
  }
  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

// =============================================================================
// MODULE 4: THE NEURAL INTERFACE (SMART CONNECTED v3.0)
// Status: UPGRADED (Handles Handshake, Debugs Silence, Shows Status)
// =============================================================================
class NeuralInterface extends StatefulWidget {
  final Map<String, dynamic>? currentUserProfile;
  final String? username;
  final String? password;
  
  const NeuralInterface({super.key, this.currentUserProfile, this.username, this.password});
  
  @override
  State<NeuralInterface> createState() => _NeuralInterfaceState();
}

class _NeuralInterfaceState extends State<NeuralInterface> with WidgetsBindingObserver {
  final VagusEngine _audio = VagusEngine(); 
  
  // Internal Socket Management
  WebSocketChannel? _socket;
  final String _serverUrl = defaultWsUrl;

  // State
  final List<String> _chatHistory = [];
  final TextEditingController _chatController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final SpeechToText _speech = SpeechToText();
  bool _isTalking = false; 
  bool _isListening = false;
  bool _speechAvailable = false;
  bool _isTextSelected = false;
  DateTime? _suppressSpeechUntil;
  String _connectionStatus = "Initializing..."; 
  // Real-time metrics from backend
  Map<String, dynamic>? _currentMetrics;
  List<dynamic>? _moodHistory;
  int _tokenBalance = 0;
  int _tokenUsage = 0;

  // Vault attachment upload progress
  UploadProgressState _uploadProgressState = UploadProgressState.idle();

  // Nevedal biometric integration
  final NevedalService _nevedal = NevedalService();
  bool _nevedalReady = false;

  // Avatar Mode (Top Tier / Sovereign Circle only)
  bool _avatarModeEnabled = false;
  AvatarVisualState _avatarState = const AvatarVisualState();
  AvatarAppearanceConfig _avatarAppearance = const AvatarAppearanceConfig();
  VoiceState _voiceState = VoiceState.idle;
  double _mouthOpenness = 0.0;

  // AI data-sharing consent (Apple 5.1.1(i) / 5.1.2(i))
  bool _aiDataConsentGiven = false;
  static const _aiConsentKey = 'ai_data_consent_v1';

  Future<void> _loadAiConsent() async {
    try {
      const storage = FlutterSecureStorage();
      final stored = await storage.read(key: _aiConsentKey);
      if (stored == 'true' && mounted) setState(() => _aiDataConsentGiven = true);
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
          child: SingleChildScrollView(child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Center(child: Icon(Icons.shield_outlined, color: Color(0xFFC9A962), size: 40)),
              const SizedBox(height: 12),
              const Center(child: Text("AI Data Processing Consent",
                style: TextStyle(color: Color(0xFFC9A962), fontSize: 18, fontWeight: FontWeight.bold))),
              const SizedBox(height: 16),
              const Text("Before you start chatting with Little Nate, please review how your data is processed:",
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
              RichText(text: const TextSpan(style: TextStyle(color: Colors.white60, fontSize: 12), children: [
                TextSpan(text: "Third-party AI provider: "),
                TextSpan(text: "Microsoft Azure OpenAI Service", style: TextStyle(color: Color(0xFFC9A962), fontWeight: FontWeight.w600)),
              ])),
              const SizedBox(height: 4),
              const Text("Full details in our Privacy Policy (Settings > Legal & Privacy).",
                style: TextStyle(color: Colors.white38, fontSize: 11)),
              const SizedBox(height: 20),
              Row(children: [
                Expanded(child: OutlinedButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  style: OutlinedButton.styleFrom(side: const BorderSide(color: Colors.white24),
                    padding: const EdgeInsets.symmetric(vertical: 14)),
                  child: const Text("Decline", style: TextStyle(color: Colors.white54)),
                )),
                const SizedBox(width: 12),
                Expanded(child: ElevatedButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962),
                    padding: const EdgeInsets.symmetric(vertical: 14)),
                  child: const Text("I Understand & Consent", style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 13)),
                )),
              ]),
            ],
          )),
        ),
      ),
    );
    if (agreed == true) {
      setState(() => _aiDataConsentGiven = true);
      try { const storage = FlutterSecureStorage(); await storage.write(key: _aiConsentKey, value: 'true'); } catch (_) {}
    }
  }

  static Widget _consentBullet(IconData icon, String title, String body) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: const Color(0xFF4ECDC4), size: 20),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13)),
          const SizedBox(height: 2),
          Text(body, style: const TextStyle(color: Colors.white60, fontSize: 12.5, height: 1.4)),
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

    // ── HIVE DEFENSE v4.3: Start periodic DeviceShield checks during session ──
    if (!kIsWeb) {
      DeviceShield.instance.startPeriodicChecks(
        interval: const Duration(minutes: 5),
      );
    }
  }

  // Track socket subscription to prevent "Stream already listened to"
  StreamSubscription? _socketSub;
  StreamSubscription? _socketErrSub; // FIX-G' broadcast errors from hub
  StreamSubscription? _socketDoneSub; // FIX-G' broadcast done from hub

  @override
  void dispose() {
    _nevedal.dispose();
    _socketSub?.cancel();
    _socketErrSub?.cancel(); // FIX-G'
    _socketDoneSub?.cancel(); // FIX-G'
    if (_socket != null && !identical(_socket, _ClientWsHub.channel)) {
      _socket?.sink.close();
    }
    _scrollController.dispose();
    _speech.stop();
    WidgetsBinding.instance.removeObserver(this);
    if (!kIsWeb) {
      DeviceShield.instance.stopPeriodicChecks();
    }
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    if (kIsWeb) return;
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      DeviceShield.instance.onAppBackground();
    } else if (state == AppLifecycleState.resumed) {
      DeviceShield.instance.onAppForeground();
    }
  }

  WebSocketChannel? get _wsCh => _ClientWsHub.channel ?? _socket;
  void _wsSend(String payload) => _wsCh?.sink.add(payload);

  void _bindSocketListeners() {
    _socketSub = _ClientWsHub.inbound.listen(_handleSocketMessage);
    _socketErrSub = _ClientWsHub.errors.listen((e) {
      if(mounted) setState(() => _connectionStatus = "ERROR: $e");
      _addSystemMsg("Connection Died: $e");
    });
    _socketDoneSub = _ClientWsHub.done.listen((_) {
      _nevedalReady = false;
      if(mounted) setState(() => _connectionStatus = "DISCONNECTED");
    });
  }

  // 1. ESTABLISH OR REUSE CONNECTION
  void _connectToCortex() {
    setState(() => _connectionStatus = "Dialing Neural Core...");
    
    _socketSub?.cancel();
    _socketSub = null;
    _socketErrSub?.cancel(); _socketErrSub = null; // FIX-G'
    _socketDoneSub?.cancel(); _socketDoneSub = null; // FIX-G'

    final existingHub = _ClientWsHub.channel;
    if (existingHub != null) {
      _socket = null;
      _bindSocketListeners();
      if (mounted) setState(() => _connectionStatus = "ONLINE (SECURE)");
      _addSystemMsg("Neural Link Established.");
      if (!_nevedalReady) {
        _nevedalReady = true;
        _nevedal.initialize(
          socket: existingHub,
          sessionId: 'session_${DateTime.now().millisecondsSinceEpoch}',
          userId: widget.username ?? 'unknown',
        );
      }
      return;
    }

    try {
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));

      // FIX-G' (HUB-OWNS-RAW-STREAM): hub is sole owner of `_socket.stream`.
      // NeuralInterface consumes via broadcast inbound/errors/done.
      _ClientWsHub.attach(_socket!);
      _bindSocketListeners();

      // 2. IMMEDIATE LOGIN
      debugLog(">>> NEURAL INTERFACE: Sending Login...");
      _wsSend(jsonEncode({
        "type": "login_request",
        "username": widget.username,
        "password": widget.password,
        "expected_role": "CLIENT",
        "client_context": kIsWeb ? 'client_web' : 'client_mobile',
      }));

    } catch (e) {
      debugLog("Connection error: $e");
    }

    // Audio Listeners
    _audio.onTranscription.listen((text) { 
      if (mounted) setState(() => _chatController.text = text); 
    });
  }

  // ===========================================================================
  // SPEECH-TO-TEXT (NEURAL INTERFACE)
  // ===========================================================================

  Future<void> _initSpeechToText() async {
    try {
      _speechAvailable = await _speech.initialize(
        onError: (error) {
          debugLog('Speech error: ${error.errorMsg}');
          if (mounted) setState(() => _isListening = false);
        },
        onStatus: (status) {
          debugLog('Speech status: $status');
          if (status == 'done' || status == 'notListening') {
            _suppressSpeechUntil = DateTime.now().add(const Duration(milliseconds: 1500));
            if (mounted) setState(() => _isListening = false);
          }
        },
      );
      if (mounted) setState(() {});
    } catch (e) {
      debugLog('Speech init error: $e');
      _speechAvailable = false;
    }
  }

  Future<void> _stopSpeechAndSuppressLateResults() async {
    _suppressSpeechUntil = DateTime.now().add(const Duration(milliseconds: 2500));
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

  void _toggleListening() async {
    if (!_speechAvailable) {
      _addSystemMsg('Speech recognition not available');
      return;
    }

    if (_isListening) {
      await _stopSpeechAndSuppressLateResults();
      return;
    }

    setState(() => _isListening = true);
    await _speech.listen(
      onResult: (result) {
        // Guard against "late" final callbacks repopulating input after Stop/Send.
        if (!_isListening) return;
        final until = _suppressSpeechUntil;
        if (until != null && DateTime.now().isBefore(until)) {
          return;
        }
        if (mounted) {
          setState(() {
            _chatController.text = _normalizeDictation(result.recognizedWords);
          });
        }
      },
      listenFor: const Duration(seconds: 30),
      pauseFor: const Duration(seconds: 3),
      partialResults: true,
      cancelOnError: true,
      listenMode: ListenMode.confirmation,
    );
  }

  void _handleSocketMessage(dynamic message) {
    try {
      final decoded = jsonDecode(message);
      if (decoded is! Map) {
        debugLog("Parse Error: expected JSON object, got ${decoded.runtimeType}");
        return;
      }
      final data = Map<String, dynamic>.from(decoded as Map);
      debugLog(">>> CORTEX SAYS: $data"); 

      if (data['type'] == 'login_success') {
        setState(() => _connectionStatus = "ONLINE (SECURE)");
        _addSystemMsg("Neural Link Established.");

        if (_socket != null && !_nevedalReady) {
          _nevedalReady = true;
          final sessionId = data['session_id'] as String? ??
              'session_${DateTime.now().millisecondsSinceEpoch}';
          _nevedal.initialize(
            socket: _wsCh!,
            sessionId: sessionId,
            userId: widget.username ?? 'unknown',
          );
          // FIX-G': hub already owns _socket from _connectToCortex; no re-attach needed.
        }
      }
      else if (data['type'] == 'nate_thinking') {
        final thinking = data['text'] ?? 'Little Nate is thinking...';
        setState(() {
          if (_chatHistory.isNotEmpty &&
              _chatHistory.last.startsWith("Little Nate:")) {
            _chatHistory[_chatHistory.length - 1] = "Little Nate: $thinking";
          } else {
            _chatHistory.add("Little Nate: $thinking");
          }
          _scrollToBottom();
        });
      }
      else if (data['type'] == 'nate_response' || data['type'] == 'chat_reply') {
        String reply = data['text'] ?? "";
        setState(() {
          // Update last NATE message if it exists, otherwise add new one
          if (_chatHistory.isNotEmpty && _chatHistory.last.startsWith("Little Nate:")) {
            _chatHistory[_chatHistory.length - 1] = "Little Nate: $reply";
          } else {
            _chatHistory.add("Little Nate: $reply");
          } 
          _scrollToBottom();
        });
      }
      else if (data['type'] == 'nate_audio_delta') {
         if (mounted) setState(() => _isTalking = true);
         final payload = data['payload'];
         if (payload != null) {
           _audio.processAudioChunk(payload);
           try {
             final bytes = base64Decode(payload as String);
             _nevedal.processNateAudio(bytes);
           } catch (_) {}
         }
         Future.delayed(const Duration(milliseconds: 200), () {
           if (mounted) setState(() => _isTalking = false);
         });
      }
      else if (data['type'] == 'nevedal_state') {
        _nevedal.handleServerUpdate(data['data'] ?? data);
      }
      else if (data['type'] == 'metrics_update') {
        debugLog('>>> METRICS: Real-time update received');
        setState(() {
          final metrics = data['metrics'];
          _currentMetrics = metrics is Map ? Map<String, dynamic>.from(metrics) : null;
          final moodHistory = data['mood_history'];
          _moodHistory = moodHistory is List ? List<dynamic>.from(moodHistory) : null;
          _tokenBalance = data['token_balance'] as int? ?? 0;
          _tokenUsage = data['token_usage'] as int? ?? 0;
        });
      }
      // ===== AVATAR MODE MESSAGES =====
      else if (data['type'] == 'avatar_response') {
        // AI response with avatar state updates
        final speechData = data['speech'] as Map<String, dynamic>?;
        final avatarState = data['avatar_state'] as Map<String, dynamic>?;
        
        if (avatarState != null) {
          setState(() {
            _avatarState = AvatarVisualState.fromJson(avatarState);
          });
        }
        
        if (speechData != null) {
          final text = speechData['text'] as String? ?? '';
          if (text.isNotEmpty) {
            setState(() {
              _chatHistory.add("Little Nate: $text");
              _scrollToBottom();
            });
          }
        }
      }
      else if (data['type'] == 'avatar_config') {
        // User's avatar customization preferences
        final config = data['config'] as Map<String, dynamic>?;
        if (config != null) {
          final appearanceData = config['appearance'] as Map<String, dynamic>?;
          if (appearanceData != null) {
            setState(() {
              _avatarAppearance = AvatarAppearanceConfig.fromJson(appearanceData);
            });
          }
        }
      }
      else if (data['type'] == 'avatar_state_update') {
        // Real-time expression/gesture updates
        setState(() {
          _avatarState = AvatarVisualState.fromJson(data);
        });
      }
      else if (data['type'] == 'avatar_error') {
        final msg = data['message'] ?? 'Avatar error';
        _addSystemMsg(msg);
        if (data['upgrade_required'] == true) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Upgrade to Sovereign Circle for Avatar Mode'),
              backgroundColor: Color(0xFFFFD700),
              duration: Duration(seconds: 4),
            ),
          );
        }
      }
    } catch (e) {
      debugLog("Parse Error: $e");
    }
  }

  void _addSystemMsg(String msg) {
    final tagged = "[SYSTEM]: $msg";
    if (_chatHistory.isNotEmpty && _chatHistory.last == tagged) return;
    setState(() {
      _chatHistory.add(tagged);
      _scrollToBottom();
    });
  }

  /// Check if user is eligible for Avatar Mode
  /// Uses backend-computed premium_features for integrity (family members inherit from head)
  bool _canUseVault() {
    if (!AppConfig.ENABLE_SOVEREIGN_VAULT) return false;
    final tier = (widget.currentUserProfile?['tier'] ?? '').toString().toUpperCase();
    final plan = (widget.currentUserProfile?['subscription_plan'] ?? '').toString().toUpperCase();
    const vaultTiers = {'STANDARD', 'INNER_CHAMBER', 'TOP_TIER', 'SOVEREIGN_CIRCLE'};
    return vaultTiers.contains(tier) || vaultTiers.contains(plan);
  }

  bool _canUseAvatarMode() {
    // Primary: Use backend-computed premium_features (authoritative)
    final premiumFeatures = widget.currentUserProfile?['premium_features'];
    if (premiumFeatures != null && premiumFeatures is Map) {
      return premiumFeatures['avatar'] == true;
    }
    
    // Fallback: Check tier/subscription_plan directly (for backwards compatibility)
    final tier = (widget.currentUserProfile?['tier'] ?? '').toString().toUpperCase();
    final subscriptionPlan = (widget.currentUserProfile?['subscription_plan'] ?? '').toString().toUpperCase();
    
    const premiumTiers = {'TOP_TIER', 'SOVEREIGN_CIRCLE'};
    return premiumTiers.contains(tier) || premiumTiers.contains(subscriptionPlan);
  }

  /// Toggle avatar mode on/off
  void _toggleAvatarMode(bool enabled) {
    if (!_canUseAvatarMode()) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Avatar Mode is available for Sovereign Circle members'),
          backgroundColor: Color(0xFF8B0000),
        ),
      );
      return;
    }
    
    setState(() => _avatarModeEnabled = enabled);
    
    if (enabled) {
      // Request avatar config from server
      _wsSend(jsonEncode({'type': 'fetch_avatar_config'}));
    }
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
      _addSystemMsg("Link is dead. Reconnecting...");
      _connectToCortex(); // Auto-heal
      return;
    }

    debugLog(">>> SENDING: $text");
    _wsSend(jsonEncode({
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
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut
      );
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
      MapEntry(RegExp(r'\bdot\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bcomma\b', caseSensitive: false), ','),
      MapEntry(RegExp(r'\bcolon\b', caseSensitive: false), ':'),
      MapEntry(RegExp(r'\bsemicolon\b', caseSensitive: false), ';'),
      MapEntry(RegExp(r'\bdash\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bhyphen\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bat sign\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bat symbol\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bhash\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bhashtag\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bpound sign\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bnumber sign\b', caseSensitive: false), '#'),
      // NOTE: `$` must be escaped in RegExp replacement strings.
      MapEntry(RegExp(r'\bdollar sign\b', caseSensitive: false), r'\$'),
      MapEntry(RegExp(r'\bpercent\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bpercent sign\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bampersand\b', caseSensitive: false), '&'),
      MapEntry(RegExp(r'\bunderscore\b', caseSensitive: false), '_'),
      MapEntry(RegExp(r'\bplus\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bplus sign\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bequals\b', caseSensitive: false), '='),
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
      MapEntry(RegExp(r'\basterisk\b', caseSensitive: false), '*'),
      MapEntry(RegExp(r'\bstar\b', caseSensitive: false), '*'),
      MapEntry(RegExp(r'\bcaret\b', caseSensitive: false), '^'),
      MapEntry(RegExp(r'\btilde\b', caseSensitive: false), '~'),
      MapEntry(RegExp(r'\bquote\b', caseSensitive: false), '"'),
      MapEntry(RegExp(r'\bnew line\b', caseSensitive: false), '\n'),
      MapEntry(RegExp(r'\bnew paragraph\b', caseSensitive: false), '\n\n'),
    ];
    for (final r in rules) {
      s = s.replaceAll(r.key, r.value);
    }

    // Dart `replaceAll` does NOT support `$1` capture substitution.
    // Use `replaceAllMapped` so punctuation is preserved.
    s = s.replaceAllMapped(RegExp(r'\s+([?.!,;:])'), (m) => m.group(1) ?? '');
    s = s.replaceAllMapped(RegExp(r'([?.!,;:])(?=\w)'), (m) => '${m.group(1) ?? ''} ');
    s = s.replaceAll(RegExp(r' {2,}'), ' ');
    return s;
  }


  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.currentUserProfile?['name'] ?? "SUBJECT", style: const TextStyle(fontFamily: "Courier", color: Colors.cyanAccent, fontSize: 16)),
            Text(_connectionStatus, style: TextStyle(fontFamily: "Courier", color: _connectionStatus.contains("ONLINE") ? Colors.green : Colors.red, fontSize: 10)),
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
                color: _avatarModeEnabled ? const Color(0xFFFFD700) : Colors.white54,
              ),
              tooltip: _avatarModeEnabled ? 'Avatar Mode ON' : 'Avatar Mode OFF',
              onPressed: () => _toggleAvatarMode(!_avatarModeEnabled),
            ),
          IconButton(
            icon: const Icon(Icons.logout, color: Colors.red),
            onPressed: () {
              _wsCh?.sink.close();
              Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const LobbyScreen()));
            }
          )
        ],
      ),
      body: Stack(
        children: [
          // Conditionally render Avatar (Top Tier) or Orb (standard)
          _avatarModeEnabled && _canUseAvatarMode()
            ? LittleNateAvatar(
                appearance: _avatarAppearance,
                visualState: _avatarState,
                voiceState: _voiceState,
                mouthOpenness: _mouthOpenness,
              )
            : VisualPersona(isTalking: _isTalking, isListening: _audio.isListening),
          Column(
            children: [
              Expanded(
                child: GestureDetector(
                  onTap: () {
                    if (_isTextSelected) {
                      setState(() => _isTextSelected = false);
                    }
                  },
                  child: SelectionArea(
                    onSelectionChanged: (value) {
                      final selecting = value != null && value.plainText.isNotEmpty;
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
                      itemBuilder: (ctx, i) => Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
                        child: Text(_chatHistory[i], style: TextStyle(fontFamily: "Courier", color: _chatHistory[i].startsWith("You:") ? Colors.grey : (_chatHistory[i].startsWith("[SYSTEM]") ? Colors.yellow : Colors.white), fontSize: 14)),
                      ),
                    ),
                  ),
                ),
              ),
              if (_uploadProgressState.isVisible)
                UploadProgressIndicator(
                  state: _uploadProgressState,
                  onCancel: () => setState(() => _uploadProgressState = UploadProgressState.idle()),
                  onDismiss: () => setState(() => _uploadProgressState = UploadProgressState.idle()),
                ),
              Padding(
                padding: const EdgeInsets.all(20),
                child: Row(
                  children: [
                    IconButton(
                      icon: Icon(
                        _isListening ? Icons.mic : Icons.mic_none,
                        color: _isListening
                            ? Colors.red
                            : (_speechAvailable ? Colors.white : Colors.grey),
                      ),
                      onPressed: _speechAvailable ? _toggleListening : null,
                      tooltip: _speechAvailable ? 'Speak your message' : 'Speech not available',
                    ),
                    if (_canUseVault()) ...[
                      const SizedBox(width: 4),
                      VaultAttachmentButton(
                        profile: widget.currentUserProfile,
                        socket: _socket,
                        onVaultItemSelected: (itemId) {
                          if (itemId != null && itemId.isNotEmpty) {
                            _chatController.text = '${_chatController.text}[Vault:$itemId] '.trim();
                          }
                        },
                        onUploadProgress: (s) => setState(() => _uploadProgressState = s),
                      ),
                    ],
                    const SizedBox(width: 10),
                    Expanded(
                      child: TextField(
                        controller: _chatController,
                        style: const TextStyle(color: Colors.white, fontFamily: "Courier"),
                        decoration: InputDecoration(
                          hintText: _isListening ? "Listening..." : "Input...",
                          filled: true,
                          fillColor: Colors.white10,
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(30)),
                        ),
                        onSubmitted: (_) => _sendMessage(),
                      ),
                    ),
                    const SizedBox(width: 10),
                    FloatingActionButton(mini: true, backgroundColor: Colors.cyan, onPressed: _sendMessage, child: const Icon(Icons.send, color: Colors.black))
                  ],
                ),
              )
            ],
          )
        ],
      ),
    );
  }
}

// =============================================================================
// COACH PORTAL DASHBOARD (Verified v16.1 - Self-Sufficient Connection)
// =============================================================================

class CoachDashboardScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final String username; // <--- The Key to Stability
  final String password; // <--- The Key to Stability

  const CoachDashboardScreen({
    super.key, 
    required this.currentUserProfile, 
    required this.username,
    required this.password
  });

  @override
  _CoachDashboardScreenState createState() => _CoachDashboardScreenState();
}

class _CoachDashboardScreenState extends State<CoachDashboardScreen> {
  // Internal Socket Management
  WebSocketChannel? _socket;
  final String _serverUrl = defaultWsUrl;

  // Dashboard Data
  List<dynamic> _clients = [];
  List<dynamic> _schedule = [];
  bool _isLoading = true;
  String _statusMessage = "Initializing...";

  @override
  void initState() {
    super.initState();
    _connectToBridge();
  }

  // Track socket subscription for clean reconnect
  StreamSubscription? _coachSocketSub;

  // 1. ESTABLISH FRESH CONNECTION (Stability Fix)
  void _connectToBridge() {
    setState(() => _statusMessage = "Connecting to HQ...");
    
    // Clean up previous connection
    _coachSocketSub?.cancel();
    _coachSocketSub = null;
    try { _socket?.sink.close(); } catch (_) {}
    _socket = null;

    try {
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));
      
      _coachSocketSub = _socket!.stream.listen(
        _handleSocketMessage,
        onError: (e) {
          debugLog("Coach Socket Error: $e");
          if (mounted) setState(() => _statusMessage = "Connection Failed");
        },
        onDone: () {
          debugLog("Coach Socket Closed");
          if (mounted) setState(() => _statusMessage = "Disconnected");
        }
      );

      // 2. IMMEDIATE LOGIN
      debugLog(">>> COACH DASHBOARD: Sending Login...");
      _socket!.sink.add(jsonEncode({
        "type": "login_request",
        "username": widget.username,
        "password": widget.password,
        "expected_role": "COACH",
        "client_context": kIsWeb ? 'coach_web' : 'coach_mobile',
      }));

    } catch (e) {
      debugLog("Fatal Connection Error: $e");
    }
  }

  void _fetchDashboard() {
    // Sends the command to bridge_server.py to run coach_nexus.get_dashboard()
    if (_socket != null) {
      _socket!.sink.add(jsonEncode({ "type": "fetch_coach_dashboard" }));
    }
  }

  void _handleSocketMessage(dynamic message) {
    try {
      final data = jsonDecode(message);

      // A. Login Confirmation
      if (data['type'] == 'login_success') {
        debugLog(">>> COACH AUTHENTICATED. Fetching Data...");
        _fetchDashboard(); // Load data only after login is confirmed
      }

      // B. Dashboard Data Arrived
      else if (data['type'] == 'coach_dashboard_data') {
        if (mounted) {
          setState(() {
            _clients = data['data']['clients'] ?? [];
            _schedule = data['data']['schedule'] ?? [];
            _isLoading = false;
          });
        }
      }

      // Security disconnect — push back to lobby
      else if (data['type'] == 'security_disconnect') {
        debugLog(">>> SECURITY DISCONNECT: ${data['reason']}");
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(data['reason']?.toString() ?? 'Session terminated for security.'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 6),
          ));
          Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LobbyScreen()), (r) => false);
        }
      }
      // C. Login Failed — show error, stay on screen (never navigate away)
      else if (data['type'] == 'login_failed' || data['type'] == 'login_failure' || data['type'] == 'error') {
        final msg = (data['message'] ?? 'Login failed').toString();
        final errorCode = (data['error_code'] ?? '').toString();
        debugLog(">>> COACH LOGIN FAILED: $msg (code=$errorCode)");
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(msg),
            backgroundColor: errorCode == 'WRONG_PORTAL'
                ? const Color(0xFFC9A962)
                : Colors.red,
            duration: Duration(seconds: errorCode == 'WRONG_PORTAL' ? 6 : 4),
          ));
        }
      }
    } catch (e) {
      debugLog("Error parsing socket message: $e");
    }
  }

  // --- DIALOGS (Your Features) ---

  void _showReportsDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("INTELLIGENCE VAULT", style: TextStyle(color: Colors.amber, fontFamily: 'Courier')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.description, color: Colors.blue),
              title: const Text("Client Observation Reports", style: TextStyle(color: Colors.white)),
              onTap: () { 
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Fetching Client Reports...")));
                _socket?.sink.add(jsonEncode({"type": "fetch_reports", "coach_id": widget.currentUserProfile['hardware_id'] ?? ''}));
              },
            ),
            ListTile(
              leading: const Icon(Icons.psychology, color: Colors.purple),
              title: const Text("My Coaching Analysis", style: TextStyle(color: Colors.white)),
              onTap: () { 
                Navigator.pop(ctx);
                _socket?.sink.add(jsonEncode({"type": "fetch_coaching_advice", "coach_id": widget.currentUserProfile['hardware_id'] ?? ''}));
              },
            ),
            ListTile(
              leading: const Icon(Icons.attach_money, color: Colors.green),
              title: const Text("Billing / Time Logs", style: TextStyle(color: Colors.white)),
              subtitle: const Text("View billable heartbeat data", style: TextStyle(color: Colors.grey, fontSize: 10)),
              onTap: () { 
                Navigator.pop(ctx);
                _socket?.sink.add(jsonEncode({"type": "coach_get_financials", "coach_id": widget.currentUserProfile['hardware_id'] ?? ''}));
              },
            ),
          ],
        ),
      ),
    );
  }

  void _showSchedulingDialog() {
    TextEditingController _timeController = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("MANAGE AVAILABILITY", style: TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
             TextField(
               controller: _timeController,
               style: const TextStyle(color: Colors.white),
               decoration: const InputDecoration(labelText: "Add Slot (e.g. 'Mon 10:00 AM')", labelStyle: TextStyle(color: Colors.grey)),
             ),
             const SizedBox(height: 20),
             ElevatedButton(
               style: ElevatedButton.styleFrom(backgroundColor: Colors.amber),
               child: const Text("Publish Slot"),
               onPressed: () {
                 _socket?.sink.add(jsonEncode({
                   "type": "update_availability",
                   "slots": [_timeController.text] 
                 }));
                 Navigator.pop(ctx);
                 ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Slot Published")));
               },
             )
          ],
        ),
      ),
    );
  }

  void _showNoteDialog() {
    TextEditingController _noteController = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.grey[900],
        title: const Text("NIGHT SCHOOL INGESTION", style: TextStyle(color: Colors.white)),
        content: TextField(
          controller: _noteController,
          maxLines: 5,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            hintText: "Speak or type session notes here for Little Nate to learn...",
            hintStyle: TextStyle(color: Colors.grey),
            border: OutlineInputBorder()
          ),
        ),
        actions: [
          TextButton(child: const Text("CANCEL"), onPressed: () => Navigator.pop(ctx)),
          ElevatedButton(
            child: const Text("UPLOAD MEMORY"),
            onPressed: () {
               _socket?.sink.add(jsonEncode({
                 "type": "upload_session_note",
                 "note_text": _noteController.text
               }));
               Navigator.pop(ctx);
               ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Notes sent to Night School.")));
            },
          )
        ],
      ),
    );
  }

  @override
  void dispose() {
    _socket?.sink.close();
    super.dispose();
  }

  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF121212), // Dark Mode Background
      appBar: AppBar(
        title: const Text("COACH COMMAND", style: TextStyle(fontFamily: 'Courier', color: Colors.amber, fontWeight: FontWeight.bold)),
        backgroundColor: Colors.black,
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.grey),
            onPressed: () { 
              setState(() => _isLoading = true); 
              _fetchDashboard(); 
            }
          ),
          IconButton(
            icon: const Icon(Icons.logout, color: Colors.red),
            onPressed: () {
               _socket?.sink.close();
               Navigator.of(context).pushReplacement(
                 MaterialPageRoute(builder: (_) => const LobbyScreen())
               );
            },
          )
        ],
      ),
      body: _isLoading 
        ? Center(child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const CircularProgressIndicator(color: Colors.amber),
              const SizedBox(height: 20),
              Text(_statusMessage, style: const TextStyle(color: Colors.grey))
            ],
          ))
        : SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildSectionHeader("Active Caseload"),
                  if (_clients.isEmpty) _buildEmptyState("No clients assigned."),
                  ..._clients.map((c) => _buildClientTile(c)).toList(),

                  const SizedBox(height: 30),

                  _buildSectionHeader("Today's Schedule"),
                  if (_schedule.isEmpty) _buildEmptyState("No sessions today."),
                  ..._schedule.map((s) => _buildScheduleTile(s)).toList(),
                  
                  const SizedBox(height: 30),
                  
                  _buildQuickActions()
                ],
              ),
            ),
          ),
    );
  }

  // --- UI HELPER WIDGETS ---

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Text(
        title.toUpperCase(), 
        style: const TextStyle(color: Colors.grey, letterSpacing: 1.5, fontWeight: FontWeight.bold, fontSize: 12)
      ),
    );
  }

  Widget _buildEmptyState(String text) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.white10), 
        borderRadius: BorderRadius.circular(8)
      ),
      child: Center(
        child: Text(text, style: TextStyle(color: Colors.grey[600], fontStyle: FontStyle.italic))
      ),
    );
  }

  Widget _buildClientTile(dynamic client) {
    return Card(
      color: Colors.grey[900],
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: Colors.blueGrey[900],
          child: const Icon(Icons.person, color: Colors.blueAccent),
        ),
        title: Text(client['name'], style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        subtitle: Text("ID: ${client['id']}", style: const TextStyle(color: Colors.grey, fontSize: 10)),
        trailing: IconButton(
          icon: const Icon(Icons.message, color: Colors.amber),
          onPressed: () {
            _openSecureRelay(client);
          },
        ),
      ),
    );
  }
  
  void _openSecureRelay(dynamic client) {
    final clientId = client['id']?.toString() ?? '';
    final clientName = client['name']?.toString() ?? 'Client';
    _socket?.sink.add(jsonEncode({
      "type": "secure_relay_open",
      "client_id": clientId,
    }));
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => _SecureRelayScreen(
          socket: _socket,
          clientId: clientId,
          clientName: clientName,
        ),
      ),
    );
  }

  Widget _buildScheduleTile(dynamic slot) {
    return Card(
      color: Colors.grey[900],
      child: ListTile(
        leading: const Icon(Icons.videocam, color: Colors.green),
        title: Text(slot['time'] ?? "Unknown Time", style: const TextStyle(color: Colors.white)),
        subtitle: Text(slot['client'] ?? "Open Slot", style: const TextStyle(color: Colors.grey)),
        trailing: const Icon(Icons.chevron_right, color: Colors.grey),
      ),
    );
  }

  Widget _buildQuickActions() {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: ElevatedButton.icon(
                icon: const Icon(Icons.mic, color: Colors.white),
                label: const Text("DICTATE NOTES"),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.blueGrey[800],
                  padding: const EdgeInsets.symmetric(vertical: 15)
                ),
                onPressed: _showNoteDialog,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: ElevatedButton.icon(
                icon: const Icon(Icons.calendar_today, color: Colors.white),
                label: const Text("SCHEDULER"),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.blueGrey[800],
                  padding: const EdgeInsets.symmetric(vertical: 15)
                ),
                onPressed: _showSchedulingDialog,
              ),
            ),
          ],
        ),
        const SizedBox(height: 15),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            icon: const Icon(Icons.analytics, color: Colors.amber),
            label: const Text("ACCESS INTELLIGENCE VAULT (REPORTS)"),
            style: OutlinedButton.styleFrom(
              side: const BorderSide(color: Colors.amber),
              foregroundColor: Colors.amber,
              padding: const EdgeInsets.symmetric(vertical: 15)
            ),
            onPressed: _showReportsDialog, 
          ),
        )
      ],
    );
  }
}

// =============================================================================
// SECURE RELAY — Encrypted messaging with a client
// =============================================================================
class _SecureRelayScreen extends StatefulWidget {
  final WebSocketChannel? socket;
  final String clientId;
  final String clientName;
  const _SecureRelayScreen({required this.socket, required this.clientId, required this.clientName});
  @override
  State<_SecureRelayScreen> createState() => _SecureRelayScreenState();
}

class _SecureRelayScreenState extends State<_SecureRelayScreen> {
  final _msgCtrl = TextEditingController();
  final List<Map<String, String>> _messages = [];
  WebSocketChannel? _ownSocket;
  StreamSubscription? _sub;

  @override
  void initState() {
    super.initState();
    _connectOwnSocket();
  }

  void _connectOwnSocket() {
    try {
      _ownSocket = WebSocketChannel.connect(Uri.parse(defaultWsUrl));
      _sub = _ownSocket!.stream.listen((msg) {
        try {
          final data = jsonDecode(msg);
          if (data['type'] == 'secure_relay_message' && data['client_id'] == widget.clientId) {
            if (mounted) {
              setState(() {
                _messages.add({'sender': 'client', 'text': data['message'] ?? ''});
              });
            }
          }
        } catch (_) {}
      });
    } catch (_) {}
  }

  @override
  void dispose() {
    _sub?.cancel();
    _ownSocket?.sink.close();
    _msgCtrl.dispose();
    super.dispose();
  }

  void _send() {
    final text = _msgCtrl.text.trim();
    if (text.isEmpty) return;
    _ownSocket?.sink.add(jsonEncode({
      "type": "secure_relay_message",
      "client_id": widget.clientId,
      "message": text,
    }));
    setState(() => _messages.add({'sender': 'coach', 'text': text}));
    _msgCtrl.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0A0A0A),
        title: Text('Secure Relay — ${widget.clientName}', style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16)),
        iconTheme: const IconThemeData(color: Color(0xFFC9A962)),
      ),
      body: Column(
        children: [
          Expanded(
            child: _messages.isEmpty
              ? const Center(child: Text('Send a secure message...', style: TextStyle(color: Colors.grey)))
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
                  itemCount: _messages.length,
                  itemBuilder: (_, i) {
                    final m = _messages[i];
                    final isCoach = m['sender'] == 'coach';
                    return Align(
                      alignment: isCoach ? Alignment.centerRight : Alignment.centerLeft,
                      child: Container(
                        margin: const EdgeInsets.only(bottom: 8),
                        padding: const EdgeInsets.all(12),
                        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.7),
                        decoration: BoxDecoration(
                          color: isCoach ? const Color(0xFFC9A962).withOpacity(0.15) : const Color(0xFF1A1A1A),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: isCoach ? const Color(0xFFC9A962).withOpacity(0.3) : Colors.white10),
                        ),
                        child: SelectableText(m['text'] ?? '', style: const TextStyle(color: Colors.white, fontSize: 13)),
                      ),
                    );
                  },
                ),
          ),
          Container(
            padding: const EdgeInsets.all(12),
            color: const Color(0xFF0A0A0A),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _msgCtrl,
                    style: const TextStyle(color: Colors.white, fontSize: 13),
                    decoration: InputDecoration(
                      hintText: 'Type a secure message...',
                      hintStyle: TextStyle(color: Colors.grey[600]),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: Colors.white10)),
                      filled: true,
                      fillColor: const Color(0xFF111111),
                      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    ),
                    onSubmitted: (_) => _send(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.send, color: Color(0xFFC9A962)),
                  onPressed: _send,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class FamilySanctuaryScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String? username;
  final String? password;
  
  const FamilySanctuaryScreen({
    Key? key,
    required this.profile,
    this.username,
    this.password,
  }) : super(key: key);

  @override
  State<FamilySanctuaryScreen> createState() => _FamilySanctuaryScreenState();
}

class _FamilySanctuaryScreenState extends State<FamilySanctuaryScreen> with WidgetsBindingObserver {
  WebSocketChannel? _channel;
  final String _serverUrl = defaultWsUrl;
  
  // Sanctuary state
  String? _sanctuaryId;
  String _sanctuaryStatus = 'LOADING';
  List<Map<String, dynamic>> _members = [];
  List<Map<String, dynamic>> _messages = [];
  bool _inPrivateCoaching = false;
  bool _coachingLimitReached = false;
  int _coachingMaxSteps = 5;
  List<Map<String, dynamic>> _coachingMessages = [];

  int _coachingAttempt = 0;
  final TextEditingController _coachingController = TextEditingController();
  bool _sanctuaryPaused = false;
  bool _pendingAssistedReturn = false;
  bool _showSessionSummary = false;
  bool _generatingSummary = false;
  Map<String, dynamic>? _sessionSummary;
  Map<String, dynamic>? _sessionStats;
  bool _showEntryQuestions = false;
  List<Map<String, dynamic>> _entryQuestions = [];
  Map<String, dynamic> _entryResponses = {};
  int _feelingScale = 5;
  DateTime? _lastResumedAt;
  String _pausedReason = '';
  // Authoritative from backend; start at 0 until first hydration message arrives.
  double _totalCharges = 0.0;
  // Itemized billing ledger from backend (last ~50)
  List<Map<String, dynamic>> _billingCharges = [];
  bool _isCreator = false;  // Only creator can complete sanctuary

  // Metrics (real-time updates)
  Map<String, dynamic>? _currentMetrics;
  List<dynamic>? _moodHistory;
  int _tokenBalance = 0;
  int _tokenUsage = 0;
  
  // UI state
  final TextEditingController _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _showCoachingModal = false;
  Map<String, dynamic>? _coachingOffer;
  String? _assistedResponse; // cached assisted response to post to group chat
  UploadProgressState _sanctuaryUploadState = UploadProgressState.idle();

  // Group Coaching ($20) - private "words to say"
  bool _hasSuggestedResponse = false;
  String _suggestedResponseText = '';
  String _suggestedRationale = '';
  String _suggestedTarget = 'the family';
  String _suggestedTone = 'supportive';
  final TextEditingController _suggestedController = TextEditingController();
  DateTime? _groupCoachingCooldownEndsAt;
  String? _groupCoachingPendingBy;
  double? _groupCoachingPendingRequestedAt;
  double? _groupCoachingLastDialogShownForRequestAt;
  Timer? _groupCoachingTimer;
  bool _groupCoachingRoundActive = false;
  List<String> _groupCoachingWaitingOn = [];
  String _groupCoachingMyState = '';
  
  // Speech-to-Text for accessibility
  final SpeechToText _speech = SpeechToText();
  bool _isListening = false;
  bool _speechAvailable = false;
  DateTime? _suppressSpeechUntil;
  bool _dictationArmed = false; // mic mode (auto-restart on pauses)
  String _dictationBaseText = ''; // text before current listen session
  String _dictationSessionText = ''; // rolling transcript for current session
  DateTime? _voiceCommandCooldownUntil;
  
  // WebSocket subscription
  StreamSubscription? _wsSubscription;

  // Reconnect backoff state (per endpoint-websocket-sustainability.mdc Pattern #2)
  int _reconnectAttempts = 0;
  static const int _maxReconnectAttempts = 10;
  Timer? _reconnectTimer;
  bool _isManuallyDisconnected = false;

  // ARCH-FIX (FAMILY-SANCTUARY-HUB-SHARE): when the chat screen's _ClientWsHub
  // already holds an authenticated socket for this user, Family Sanctuary
  // borrows it instead of opening a duplicate WS that the bridge would kick.
  // See voice-call-pipeline & endpoint-websocket-sustainability rules.
  bool _borrowedFromHub = false;
  StreamSubscription<Object>? _hubErrSub;
  StreamSubscription<void>? _hubDoneSub;
  Timer? _hubRejoinTimer;
  int _hubRejoinAttempts = 0;
  static const int _maxHubRejoinAttempts = 30;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initSpeechToText();
    _connectToServer();
    
    // Check if joining existing sanctuary
    final sanctuaryId = widget.profile['current_sanctuary_id'];
    if (sanctuaryId != null) {
      _joinExistingSanctuary(sanctuaryId);
    }
  }

  void _connectToServer() {
    // Defensive: a fresh connection cycle clears any stale manual-disconnect
    // state so onDone/onError can schedule reconnects normally.
    _isManuallyDisconnected = false;
    // Cancel previous subscriptions before re-attaching.
    _wsSubscription?.cancel(); _wsSubscription = null;
    _hubErrSub?.cancel(); _hubErrSub = null;
    _hubDoneSub?.cancel(); _hubDoneSub = null;
    _hubRejoinTimer?.cancel(); _hubRejoinTimer = null;

    // ARCH-FIX (FAMILY-SANCTUARY-HUB-SHARE): if the shared client hub already
    // owns an authenticated WS for this user (Lobby/NeuralInterface attached
    // it on login_success), reuse it. This eliminates the duplicate-session
    // kick storm that produced the reconnect loop. The hub is the SOLE owner
    // of the underlying stream; we subscribe via the broadcast inbound stream.
    if (_ClientWsHub.channel != null) {
      debugLog('>>> SANCTUARY: Borrowing _ClientWsHub channel (already authed)');
      _borrowedFromHub = true;
      _channel = _ClientWsHub.channel;
      _wsSubscription = _ClientWsHub.inbound.listen(
        (message) {
          try {
            _handleWebSocketMessage(json.decode(message as String));
          } catch (e) {
            debugLog('Error parsing hub message: $e');
          }
        },
      );
      _hubErrSub = _ClientWsHub.errors.listen((e) {
        debugLog('>>> SANCTUARY: Hub error: $e');
      });
      _hubDoneSub = _ClientWsHub.done.listen((_) {
        debugLog('>>> SANCTUARY: Hub channel closed; awaiting hub revival');
        if (!_isManuallyDisconnected && mounted) _scheduleHubRejoin();
      });
      // Hub is already authed -> jump straight to sanctuary join/create.
      _initiateSanctuaryFlow();
      return;
    }

    // Standalone fallback: hub not initialized yet (rare; defensive).
    debugLog('>>> SANCTUARY: Hub unavailable, opening standalone WS');
    _borrowedFromHub = false;
    try { _channel?.sink.close(); } catch (_) {}
    _channel = null;

    _channel = WebSocketChannel.connect(Uri.parse(_serverUrl));
    _listenToWebSocket();

    final username = widget.username ??
        widget.profile['username'] ??
        widget.profile['email']?.split('@')[0] ??
        'client1';

    debugLog('>>> SANCTUARY: Authenticating (standalone)...');
    _channel?.sink.add(json.encode({
      "type": "login_request",
      "username": username,
      "password": widget.password ?? "",
      "expected_role": "CLIENT",
      "client_context": kIsWeb ? 'sanctuary_web' : 'sanctuary_mobile',
    }));
  }

  @override
  void didChangeMetrics() {
    super.didChangeMetrics();
    final bottomInset = WidgetsBinding.instance.platformDispatcher.views.first.viewInsets.bottom;
    if (bottomInset > 0) {
      Future.delayed(const Duration(milliseconds: 150), () {
        if (mounted && _scrollController.hasClients) {
          _scrollController.animateTo(
            _scrollController.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  @override
  void dispose() {
    _isManuallyDisconnected = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _hubRejoinTimer?.cancel();
    _hubRejoinTimer = null;
    WidgetsBinding.instance.removeObserver(this);
    _messageController.dispose();
    _suggestedController.dispose();
    _groupCoachingTimer?.cancel();
    _scrollController.dispose();
    _wsSubscription?.cancel();
    _hubErrSub?.cancel();
    _hubDoneSub?.cancel();
    // CRITICAL: when borrowing _ClientWsHub.channel the chat screen owns the
    // socket lifetime. Closing it here would kill the chat screen's WS too.
    if (!_borrowedFromHub) {
      try { _channel?.sink.close(); } catch (_) {}
    }
    super.dispose();
  }

  String? get _groupCoachingIndicatorText {
    final now = DateTime.now();
    if (_groupCoachingPendingBy != null) {
      return 'GC pending (${_groupCoachingPendingBy!})';
    }
    final ends = _groupCoachingCooldownEndsAt;
    if (ends != null && ends.isAfter(now)) {
      final remaining = ends.difference(now);
      final m = remaining.inMinutes;
      final s = remaining.inSeconds % 60;
      return 'GC cooldown ${m}:${s.toString().padLeft(2, '0')}';
    }
    return null;
  }

  void _showMembersSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0D0D0D),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.group, color: Colors.white70),
                    const SizedBox(width: 8),
                    const Text('Members', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                    const Spacer(),
                    IconButton(
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close, color: Colors.white54),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: ListView.builder(
                    itemCount: _members.length,
                    itemBuilder: (context, index) {
                      final member = _members[index];
                      final isActive = member['status'] == 'ACTIVE';
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          isActive ? Icons.circle : Icons.circle_outlined,
                          color: isActive ? Colors.greenAccent : Colors.grey,
                          size: 12,
                        ),
                        title: Text(
                          (member['name'] ?? 'Member').toString(),
                          style: const TextStyle(color: Colors.white),
                        ),
                        subtitle: member['role'] != null
                            ? Text(
                                member['role'].toString(),
                                style: const TextStyle(color: Colors.white38, fontSize: 12),
                              )
                            : null,
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildMembersStrip() {
    if (_members.isEmpty) return const SizedBox();
    final isNarrow = MediaQuery.of(context).size.width < 420;
    final strip = Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        border: Border(bottom: BorderSide(color: Colors.white.withOpacity(0.06))),
      ),
      child: Row(
        children: [
          InkWell(
            onTap: _showMembersSheet,
            borderRadius: BorderRadius.circular(999),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: Colors.white.withOpacity(0.06),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: Colors.white.withOpacity(0.08)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.group, color: Colors.white70, size: 16),
                  const SizedBox(width: 6),
                  Text(
                    '${_members.length}',
                    style: const TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: _members.map((m) {
                  final name = (m['name'] ?? 'Member').toString();
                  final role = (m['role'] ?? '').toString();
                  final isActive = m['status'] == 'ACTIVE';
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: Colors.white.withOpacity(0.05),
                        borderRadius: BorderRadius.circular(999),
                        border: Border.all(color: Colors.white.withOpacity(0.08)),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            isActive ? Icons.circle : Icons.circle_outlined,
                            color: isActive ? Colors.greenAccent : Colors.grey,
                            size: 10,
                          ),
                          const SizedBox(width: 6),
                          Text(name, style: const TextStyle(color: Colors.white70, fontSize: 12)),
                          if (role.isNotEmpty) ...[
                            const SizedBox(width: 6),
                            Text(role, style: const TextStyle(color: Colors.white38, fontSize: 11)),
                          ],
                        ],
                      ),
                    ),
                  );
                }).toList(),
              ),
            ),
          ),
        ],
      ),
    );

    // On narrow screens, show GC status under the strip (AppBar hides it to avoid clustering)
    if (!isNarrow || _groupCoachingIndicatorText == null) return strip;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        strip,
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          color: const Color(0xFF0F0F0F),
          child: Text(
            _groupCoachingIndicatorText!,
            style: const TextStyle(color: Colors.white54, fontSize: 11),
          ),
        ),
      ],
    );
  }
  
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    debugLog('>>> SANCTUARY: App lifecycle changed to $state');

    // ── HIVE DEFENSE v4.3: DeviceShield lifecycle callbacks ──
    if (!kIsWeb) {
      if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
        DeviceShield.instance.onAppBackground();
      } else if (state == AppLifecycleState.resumed) {
        DeviceShield.instance.onAppForeground();
      }
    }
    
    if (state == AppLifecycleState.resumed) {
      debugLog('>>> SANCTUARY: App resumed, syncing state...');
      // Verify socket health on resume (handles iOS/Android background WS kills).
      _reconnectIfNeeded();
      // Auto-sync state when returning from background (handles missed broadcasts)
      if (_sanctuaryId != null) {
        Future.delayed(const Duration(milliseconds: 500), () {
          if (!mounted) return;
          _syncSanctuaryState();
        });
      }
    }
  }

  void _reconnectIfNeeded() {
    // Hub-borrow mode: the chat screen owns reconnects. We just verify the hub
    // socket is still alive and resync if needed.
    if (_borrowedFromHub) {
      if (_ClientWsHub.channel == null) {
        debugLog('>>> SANCTUARY: Resume; hub down, scheduling rejoin');
        _scheduleHubRejoin();
      } else {
        debugLog('>>> SANCTUARY: Resume; hub alive');
      }
      return;
    }
    // Standalone mode: check if WebSocket is still connected.
    if (_channel == null) {
      debugLog('>>> SANCTUARY: Reconnecting (standalone)...');
      _connectToServer();
    } else {
      try {
        _channel?.sink.add(json.encode({"type": "ping"}));
        debugLog('>>> SANCTUARY: Connection still alive');
      } catch (e) {
        debugLog('>>> SANCTUARY: Connection lost, reconnecting...');
        _channel = null;
        _connectToServer();
      }
    }
  }

  // ===========================================================================
  // SPEECH-TO-TEXT INITIALIZATION (ACCESSIBILITY FEATURE)
  // ===========================================================================
  
  Future<void> _initSpeechToText() async {
    try {
      _speechAvailable = await _speech.initialize(
        onError: (error) {
          debugLog('Speech error: ${error.errorMsg}');
          setState(() => _isListening = false);
        },
        onStatus: (status) {
          debugLog('Speech status: $status');
          if (status == 'done' || status == 'notListening') {
            if (mounted) setState(() => _isListening = false);
            // Keep dictation continuous for accessibility: if the user pauses and
            // STT stops, auto-restart without losing existing text.
            if (_dictationArmed) {
              final until = _suppressSpeechUntil;
              final now = DateTime.now();
              final waitMs = (until != null && until.isAfter(now))
                  ? until.difference(now).inMilliseconds + 200
                  : 200;
              Future.delayed(Duration(milliseconds: waitMs), () {
                if (!mounted) return;
                if (_dictationArmed && !_isListening) {
                  _startListeningSession();
                }
              });
            }
          }
        },
      );
      setState(() {});
    } catch (e) {
      debugLog('Speech init error: $e');
      _speechAvailable = false;
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

  String _deleteLastSentence(String input) {
    var s = input.trimRight();
    if (s.isEmpty) return s;

    final matches = RegExp(r'[.!?]+').allMatches(s).toList();
    if (matches.isEmpty) {
      final nl = s.lastIndexOf('\n');
      if (nl != -1) return s.substring(0, nl).trimRight();
      return '';
    }
    if (matches.length == 1) return '';
    final prev = matches[matches.length - 2];
    var cut = prev.end;
    while (cut < s.length && s[cut] == ' ') cut++;
    return s.substring(0, cut).trimRight();
  }

  ({String type, String body})? _extractVoiceCommand(String raw) {
    final lower = raw.trim().toLowerCase();
    final cooldown = _voiceCommandCooldownUntil;
    if (cooldown != null && DateTime.now().isBefore(cooldown)) return null;

    final sendSuffix = RegExp(r'\b(send message|send it|send)\b\s*$', caseSensitive: false);
    final clearExact = RegExp(r'^(delete message and start over|delete message|clear message|start over|clear)$', caseSensitive: false);
    final deleteLast = RegExp(r'^(delete last sentence|remove last sentence|delete last line)$', caseSensitive: false);

    if (clearExact.hasMatch(lower)) return (type: 'clear_all', body: '');
    if (deleteLast.hasMatch(lower)) return (type: 'delete_last_sentence', body: '');

    if (sendSuffix.hasMatch(lower)) {
      final body = raw.replaceAll(sendSuffix, '').trim();
      return (type: 'send', body: body);
    }
    return null;
  }

  Future<void> _handleVoiceCommand(String type, {String body = ''}) async {
    _voiceCommandCooldownUntil = DateTime.now().add(const Duration(seconds: 2));

    if (type == 'send') {
      final b = body.trim();
      if (b.isNotEmpty) {
        final normalized = _normalizeDictation(b);
        setState(() {
          _messageController.text = _composeDictation(_dictationBaseText, normalized);
        });
      }
      _sendMessage();
    } else if (type == 'clear_all') {
      setState(() {
        _messageController.clear();
        _dictationBaseText = '';
        _dictationSessionText = '';
      });
    } else if (type == 'delete_last_sentence') {
      setState(() {
        _messageController.text = _deleteLastSentence(_messageController.text);
        _dictationBaseText = _messageController.text;
        _dictationSessionText = '';
      });
    }

    if (_dictationArmed) {
      await _stopSpeechAndSuppressLateResults();
      Future.delayed(const Duration(milliseconds: 400), () {
        if (!mounted) return;
        if (_dictationArmed && !_isListening) _startListeningSession();
      });
    }
  }

  Future<void> _startListeningSession() async {
    if (!_speechAvailable) return;
    _dictationBaseText = _messageController.text;
    _dictationSessionText = '';

    if (mounted) setState(() => _isListening = true);
    await _speech.listen(
      onResult: (result) {
        if (!_isListening) return;
        final until = _suppressSpeechUntil;
        if (until != null && DateTime.now().isBefore(until)) {
          return;
        }

        final raw = result.recognizedWords.trim();
        if (raw.isEmpty) return;

        if (result.finalResult) {
          final cmd = _extractVoiceCommand(raw);
          if (cmd != null) {
            _handleVoiceCommand(cmd.type, body: cmd.body);
            return;
          }
        }

        final normalized = _normalizeDictation(raw);
        if (mounted) {
          setState(() {
            _dictationSessionText = normalized;
            _messageController.text = _composeDictation(_dictationBaseText, _dictationSessionText);
          });
        }
      },
      listenFor: const Duration(seconds: 30),
      pauseFor: const Duration(seconds: 3),
      partialResults: true,
      cancelOnError: true,
      listenMode: ListenMode.confirmation,
    );
  }

  void _toggleListening() async {
    if (!_speechAvailable) {
      _showError('Speech recognition not available');
      return;
    }

    if (_dictationArmed) {
      _dictationArmed = false;
      await _stopSpeechAndSuppressLateResults();
      return;
    }

    _dictationArmed = true;
    await _startListeningSession();
  }

  String _normalizeDictation(String input) {
    var s = (input).trimRight();
    if (s.isEmpty) return s;

    // Replace common spoken punctuation commands.
    // Order matters: multi-word phrases first.
    final rules = <MapEntry<RegExp, String>>[
      MapEntry(RegExp(r'\bquestion mark\b', caseSensitive: false), '?'),
      MapEntry(RegExp(r'\bexclamation point\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation mark\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bexclamation\b', caseSensitive: false), '!'),
      MapEntry(RegExp(r'\bfull stop\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bperiod\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bdot\b', caseSensitive: false), '.'),
      MapEntry(RegExp(r'\bcomma\b', caseSensitive: false), ','),
      MapEntry(RegExp(r'\bcolon\b', caseSensitive: false), ':'),
      MapEntry(RegExp(r'\bsemicolon\b', caseSensitive: false), ';'),
      MapEntry(RegExp(r'\bdash\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bhyphen\b', caseSensitive: false), '-'),
      MapEntry(RegExp(r'\bat sign\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bat symbol\b', caseSensitive: false), '@'),
      MapEntry(RegExp(r'\bhash\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bhashtag\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bpound sign\b', caseSensitive: false), '#'),
      MapEntry(RegExp(r'\bnumber sign\b', caseSensitive: false), '#'),
      // NOTE: `$` must be escaped in RegExp replacement strings.
      MapEntry(RegExp(r'\bdollar sign\b', caseSensitive: false), r'\$'),
      MapEntry(RegExp(r'\bpercent\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bpercent sign\b', caseSensitive: false), '%'),
      MapEntry(RegExp(r'\bampersand\b', caseSensitive: false), '&'),
      MapEntry(RegExp(r'\bunderscore\b', caseSensitive: false), '_'),
      MapEntry(RegExp(r'\bplus\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bplus sign\b', caseSensitive: false), '+'),
      MapEntry(RegExp(r'\bequals\b', caseSensitive: false), '='),
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
      MapEntry(RegExp(r'\basterisk\b', caseSensitive: false), '*'),
      MapEntry(RegExp(r'\bstar\b', caseSensitive: false), '*'),
      MapEntry(RegExp(r'\bcaret\b', caseSensitive: false), '^'),
      MapEntry(RegExp(r'\btilde\b', caseSensitive: false), '~'),
      MapEntry(RegExp(r'\bquote\b', caseSensitive: false), '"'),
      MapEntry(RegExp(r'\bnew line\b', caseSensitive: false), '\n'),
      MapEntry(RegExp(r'\bnew paragraph\b', caseSensitive: false), '\n\n'),
    ];
    for (final r in rules) {
      s = s.replaceAll(r.key, r.value);
    }

    // Clean up spacing around punctuation.
    // Dart `replaceAll` does NOT support `$1` capture substitution.
    // Use `replaceAllMapped` so punctuation is preserved.
    s = s.replaceAllMapped(RegExp(r'\s+([?.!,;:])'), (m) => m.group(1) ?? '');
    s = s.replaceAllMapped(RegExp(r'([?.!,;:])(?=\w)'), (m) => '${m.group(1) ?? ''} ');
    s = s.replaceAll(RegExp(r' {2,}'), ' ');
    return s;
  }

  Future<void> _stopSpeechAndSuppressLateResults() async {
    // Prevent a "final" onResult from repopulating the input after we send/clear.
    _suppressSpeechUntil = DateTime.now().add(const Duration(milliseconds: 2500));
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

  // ===========================================================================
  // WEBSOCKET HANDLERS
  // ===========================================================================

  void _listenToWebSocket() {
    _wsSubscription = _channel?.stream.listen(
      (message) {
        try {
          final data = json.decode(message);
          _handleWebSocketMessage(data);
        } catch (e) {
          debugLog('Error parsing message: $e');
        }
      },
      onError: (error) {
        debugLog('>>> SANCTUARY: WebSocket error: $error');
        if (mounted) _showError('Connection interrupted. Reconnecting...');
        _scheduleReconnect();
      },
      onDone: () {
        debugLog('>>> SANCTUARY: WebSocket closed');
        if (!_isManuallyDisconnected && mounted) {
          _showError('Reconnecting...');
          _scheduleReconnect();
        }
      },
    );
  }

  /// Schedule a reconnect with exponential backoff + 20% jitter.
  /// Per endpoint-websocket-sustainability.mdc Pattern #2 and the lobby pattern at
  /// _LobbyScreenState._connectToBridge. Caps at ~30s, gives up after _maxReconnectAttempts.
  void _scheduleReconnect() {
    if (_isManuallyDisconnected || !mounted) return;

    // Hub-borrow mode: chat screen owns reconnect. Don't open a duplicate WS;
    // poll for hub channel revival and resend sanctuary_join when it returns.
    if (_borrowedFromHub) {
      _scheduleHubRejoin();
      return;
    }

    _reconnectTimer?.cancel();

    if (_reconnectAttempts >= _maxReconnectAttempts) {
      debugLog('>>> SANCTUARY: Reconnect ceiling reached ($_reconnectAttempts attempts)');
      if (mounted) _showError('Unable to reach Family Sanctuary. Pull down to retry.');
      return;
    }

    final attempt = _reconnectAttempts.clamp(0, 10);
    final baseMs = (1000 * (1 << attempt)).clamp(1000, 30000);
    final jitterMs = (baseMs * 0.2 *
            (DateTime.now().millisecondsSinceEpoch % 100) /
            100)
        .toInt();
    final delayMs = baseMs + jitterMs;
    _reconnectAttempts++;

    debugLog('>>> SANCTUARY: Reconnect attempt $_reconnectAttempts in ${delayMs}ms');
    _reconnectTimer = Timer(Duration(milliseconds: delayMs), () {
      if (!mounted || _isManuallyDisconnected) return;
      _connectToServer();
    });
  }

  /// Hub-borrow rejoin path: chat screen reconnects the hub socket on its own
  /// schedule. We poll once per second for `_ClientWsHub.channel` revival, then
  /// re-attach + resend sanctuary_join. Caps at _maxHubRejoinAttempts (~30s).
  void _scheduleHubRejoin() {
    if (_isManuallyDisconnected || !mounted) return;
    _hubRejoinTimer?.cancel();

    if (_hubRejoinAttempts >= _maxHubRejoinAttempts) {
      debugLog('>>> SANCTUARY: Hub rejoin ceiling reached ($_hubRejoinAttempts)');
      if (mounted) _showError('Connection lost. Pull down to retry.');
      return;
    }
    _hubRejoinAttempts++;

    _hubRejoinTimer = Timer(const Duration(milliseconds: 1000), () {
      if (!mounted || _isManuallyDisconnected) return;
      if (_ClientWsHub.channel != null) {
        debugLog('>>> SANCTUARY: Hub channel revived; re-attaching');
        _hubRejoinAttempts = 0;
        _connectToServer();
      } else {
        _scheduleHubRejoin();
      }
    });
  }

  /// Send sanctuary_join (rejoin) or sanctuary_get_or_create (fresh) on the
  /// already-authed hub socket. Mirrors the `case 'login_success'` handler so
  /// hub-borrow and standalone paths produce identical sanctuary state.
  void _initiateSanctuaryFlow() {
    if (!mounted || _channel == null) return;
    _reconnectAttempts = 0;
    if (_sanctuaryId != null) {
      debugLog('>>> SANCTUARY: hub mode rejoin -> sanctuary_join $_sanctuaryId');
      _channel?.sink.add(json.encode({
        "type": "sanctuary_join",
        "sanctuary_id": _sanctuaryId,
      }));
    } else {
      final familyId = widget.profile['family_id'];
      final hardwareId = widget.profile['hardware_id'] ?? 'GUEST';
      debugLog('>>> SANCTUARY: hub mode -> sanctuary_get_or_create family=$familyId');
      _channel?.sink.add(json.encode({
        "type": "sanctuary_get_or_create",
        "family_id": familyId,
        "member_id": hardwareId,
        "member_name": widget.profile['name'] ?? 'Family Member',
      }));
    }
  }

  void _postAssistedResponse() {
    final assisted = _assistedResponse;
    if (assisted != null && assisted.isNotEmpty) {
      if (_channel == null) {
        _showError('Connection lost. Reconnecting...');
        return;
      }
      _channel!.sink.add(jsonEncode({
        "type": "sanctuary_post_assisted_response",
        "sanctuary_id": _sanctuaryId,
        "assisted_response": assisted
      }));
      setState(() {
        _assistedResponse = null;
      });
      _showSuccess('Shared to family!');
    }
  }

  void _approveGroupCoaching() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_group_coaching_approve',
      'sanctuary_id': _sanctuaryId,
    }));
  }

  void _declineGroupCoaching({String? reason, String? note}) {
    final msg = <String, dynamic>{
      'type': 'sanctuary_group_coaching_decline',
      'sanctuary_id': _sanctuaryId,
    };
    if (reason != null) msg['decline_reason'] = reason;
    if (note != null && note.trim().isNotEmpty) msg['decline_note'] = note.trim();
    _channel?.sink.add(jsonEncode(msg));
  }

  void _showDeclineExplanationDialog() {
    String? selectedReason;
    final noteController = TextEditingController();

    const reasons = <Map<String, String>>[
      {'key': 'budget_tight', 'label': 'We need to watch our budget right now', 'group': 'Financial'},
      {'key': 'unexpected_expense', 'label': 'We had an unexpected expense this period', 'group': 'Financial'},
      {'key': 'not_in_budget', 'label': "This wasn't planned in our budget", 'group': 'Financial'},
      {'key': 'not_right_time', 'label': "It's not the right time for this", 'group': 'Timing'},
      {'key': 'too_late_tonight', 'label': "It's getting late, maybe next time", 'group': 'Timing'},
      {'key': 'need_to_think', 'label': "I'd like to think about it first", 'group': 'Timing'},
      {'key': 'not_needed', 'label': "I don't think we need this right now", 'group': "We're okay"},
      {'key': 'can_handle_ourselves', 'label': 'We can work this out ourselves', 'group': "We're okay"},
      {'key': 'too_much_help', 'label': "I think we've had enough help for now", 'group': "We're okay"},
      {'key': 'child_not_ready', 'label': "I don't think they're ready for this", 'group': 'Other'},
      {'key': 'family_doing_fine', 'label': "We're doing fine without it", 'group': 'Other'},
      {'key': 'dont_want_to_discuss', 'label': "I'd rather not go into it", 'group': 'Other'},
    ];

    final groups = <String>['Financial', 'Timing', "We're okay", 'Other'];

    showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: const Color(0xFF1a1a2e),
          title: Row(
            children: const [
              Icon(Icons.chat_bubble_outline, color: Color(0xFFC9A962), size: 22),
              SizedBox(width: 8),
              Expanded(child: Text('Help us understand', style: TextStyle(color: Colors.white, fontSize: 17))),
            ],
          ),
          content: SizedBox(
            width: double.maxFinite,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Your feedback helps us serve your family better. This is completely optional.",
                    style: TextStyle(color: Colors.white54, fontSize: 13),
                  ),
                  const SizedBox(height: 16),
                  for (final group in groups) ...[
                    Padding(
                      padding: const EdgeInsets.only(top: 8, bottom: 6),
                      child: Text(group, style: const TextStyle(color: Color(0xFFC9A962), fontSize: 13, fontWeight: FontWeight.w600)),
                    ),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: reasons.where((r) => r['group'] == group).map((r) {
                        final isSelected = selectedReason == r['key'];
                        return ChoiceChip(
                          label: Text(r['label']!, style: TextStyle(color: isSelected ? Colors.black : Colors.white70, fontSize: 12)),
                          selected: isSelected,
                          selectedColor: const Color(0xFFC9A962),
                          backgroundColor: const Color(0xFF2A2A3E),
                          onSelected: (_) => setDialogState(() => selectedReason = r['key']),
                        );
                      }).toList(),
                    ),
                  ],
                  const SizedBox(height: 16),
                  TextField(
                    controller: noteController,
                    maxLines: 2,
                    style: const TextStyle(color: Colors.white, fontSize: 13),
                    decoration: InputDecoration(
                      hintText: 'Anything else you\'d like to share? (optional)',
                      hintStyle: const TextStyle(color: Colors.white30, fontSize: 12),
                      filled: true,
                      fillColor: const Color(0xFF2A2A3E),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
                      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                    ),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () {
                Navigator.pop(ctx);
                _declineGroupCoaching();
              },
              child: const Text('Skip', style: TextStyle(color: Colors.white30, fontSize: 13)),
            ),
            ElevatedButton(
              onPressed: () {
                Navigator.pop(ctx);
                _declineGroupCoaching(reason: selectedReason ?? 'other', note: noteController.text);
              },
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF3A3A5E)),
              child: const Text('Submit', style: TextStyle(color: Colors.white)),
            ),
          ],
        ),
      ),
    ).then((_) => noteController.dispose());
  }

  void _showGroupCoachingApprovalDialog(Map<String, dynamic> data) {
    final cost = (data['cost'] as num?)?.toDouble() ?? 20.00;
    final triggeredBy = (data['triggered_by'] ?? 'A family member').toString();

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Row(
          children: const [
            Icon(Icons.record_voice_over, color: Colors.amber),
            SizedBox(width: 8),
            Text('Group Coaching', style: TextStyle(color: Colors.white)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              (data['message'] ?? '$triggeredBy is asking for guidance.').toString(),
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.amber.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Little Nate will craft words for each family member to say — creating connection and healing.',
                    style: TextStyle(color: Colors.white70, fontSize: 13),
                  ),
                  SizedBox(height: 8),
                  Text(
                    '• Personalized for each person\n'
                    '• Designed to repair and connect\n'
                    '• Members can edit or skip',
                    style: TextStyle(color: Colors.white54, fontSize: 12),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Cost: \$${cost.toStringAsFixed(2)}',
              style: const TextStyle(color: Colors.amber, fontWeight: FontWeight.bold, fontSize: 18),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _showDeclineExplanationDialog();
            },
            child: const Text('Not Now', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _approveGroupCoaching();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.amber),
            child: Text('Approve (\$${cost.toStringAsFixed(0)})'),
          ),
        ],
      ),
    );
  }

  void _startGroupCoachingTimer() {
    _groupCoachingTimer?.cancel();
    _groupCoachingTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) return;
      final ends = _groupCoachingCooldownEndsAt;
      if (ends == null) {
        _groupCoachingTimer?.cancel();
        _groupCoachingTimer = null;
        return;
      }
      if (DateTime.now().isAfter(ends)) {
        setState(() {
          _groupCoachingCooldownEndsAt = null;
        });
        _groupCoachingTimer?.cancel();
        _groupCoachingTimer = null;
        return;
      }
      setState(() {}); // refresh countdown label
    });
  }

  void _sendSuggestedResponse() {
    final text = _suggestedController.text.trim();
    if (text.isEmpty) return;
    final wasEdited = text != _suggestedResponseText;

    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_send_suggested_response',
      'sanctuary_id': _sanctuaryId,
      'response_text': text,
      'was_edited': wasEdited,
    }));

    setState(() {
      _hasSuggestedResponse = false;
      _suggestedResponseText = '';
      _suggestedRationale = '';
      _groupCoachingMyState = 'SENT';
    });
  }

  void _declineSuggestedResponse() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_decline_suggested_response',
      'sanctuary_id': _sanctuaryId,
    }));

    setState(() {
      _hasSuggestedResponse = false;
      _suggestedResponseText = '';
      _suggestedRationale = '';
      _groupCoachingMyState = 'DECLINED';
    });
  }

  void _handleWebSocketMessage(Map<String, dynamic> data) {
    final type = data['type'];
    debugLog('>>> SANCTUARY RECEIVED: $type');
    
    switch (type) {
      // LOGIN
      case 'login_success':
        debugLog('>>> SANCTUARY: Authenticated successfully');
        // Successful auth -> reset reconnect backoff so future drops start fast,
        // and clear manual-disconnect state in case it was set by a prior path.
        _reconnectAttempts = 0;
        _isManuallyDisconnected = false;
        // If we already had an active sanctuary in this state (i.e. this is a
        // reconnect, not a fresh entry), rejoin via sanctuary_join so the
        // backend's add_or_reconnect_member() emits `sanctuary_reconnected`
        // with the last-50 message history. Otherwise, fresh entry path.
        if (_sanctuaryId != null) {
          debugLog('>>> SANCTUARY: Reconnect path -> sanctuary_join $_sanctuaryId');
          _channel?.sink.add(json.encode({
            "type": "sanctuary_join",
            "sanctuary_id": _sanctuaryId,
          }));
        } else {
          final familyId = widget.profile['family_id'];
          final hardwareId = widget.profile['hardware_id'] ?? 'GUEST';
          debugLog('>>> SANCTUARY: Checking for existing sanctuary for family $familyId');
          _channel?.sink.add(json.encode({
            "type": "sanctuary_get_or_create",
            "family_id": familyId,
            "member_id": hardwareId,
            "member_name": widget.profile['name'] ?? 'Family Member',
          }));
        }
        break;
        
      case 'metrics_update':
        debugLog('>>> METRICS: Real-time update received');
        setState(() {
          final metrics = data['metrics'];
          _currentMetrics = metrics is Map ? Map<String, dynamic>.from(metrics) : null;
          final moodHistory = data['mood_history'];
          _moodHistory = moodHistory is List ? List<dynamic>.from(moodHistory) : null;
          _tokenBalance = data['token_balance'] as int? ?? 0;
          _tokenUsage = data['token_usage'] as int? ?? 0;
        });
        break;

      // SANCTUARY CREATION
      case 'sanctuary_created':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'WAITING_FOR_MEMBERS';
          // Backend sends `total_charges`; `base_fee_charged` is a bool (do not treat as amount).
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) {
            _totalCharges = total;
          } else {
            final baseCharged = (data['base_fee_charged'] == true);
            _totalCharges = baseCharged ? 20.0 : 0.0;
          }
          // Creator (and/or head-of-household) can complete the sanctuary session.
          // Backend reliably includes is_creator only on "created", not always on rejoin/reconnect.
          _isCreator = data['is_creator'] == true || _isCurrentUserHead();
        });
        _showSuccess('Family Sanctuary created!');
        break;
        
      // JOINING (new member)
      case 'sanctuary_joined':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;
          _members = _parseMembersList(data['members']);
          // Backend doesn't always include is_creator here; infer from roster role.
          _isCreator = data['is_creator'] == true || _isCurrentUserHead(_members);
        });
        // Load message history if provided (new member catches up)
        final joinMessages = data['messages'] as List<dynamic>?;
        if (joinMessages != null && joinMessages.isNotEmpty) {
          setState(() {
            _messages = joinMessages.map((m) => Map<String, dynamic>.from(m as Map)).toList();
          });
          debugLog('>>> SANCTUARY: Loaded \${joinMessages.length} messages from history');
        }
        _showSuccess('Joined Family Sanctuary!');
        break;
        
      // RECONNECTION (returning after disconnect/refresh)
      case 'sanctuary_reconnected':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;
          _members = _parseMembersList(data['members']);
          _isCreator = data['is_creator'] == true || _isCurrentUserHead(_members);
          // Load message history
          if (data['messages'] != null) {
            _messages = (data['messages'] as List).map((m) => Map<String, dynamic>.from(m)).toList();
          }
        });
        _addSystemMessage(data['message'] ?? 'Reconnected to sanctuary');
        break;
        
      // REJOINING (returning after exit)
      case 'sanctuary_rejoined':
        setState(() {
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;
          _members = _parseMembersList(data['members']);
          _isCreator = data['is_creator'] == true || _isCurrentUserHead(_members);
        });
        // Load message history if provided
        final rejoinMessages = data['messages'] as List<dynamic>? ?? [];
        if (rejoinMessages.isNotEmpty) {
          setState(() {
            _messages = rejoinMessages.map((m) => Map<String, dynamic>.from(m)).toList();
          });
        }
        _addSystemMessage(data['message'] ?? 'Welcome back!');
        _showSuccess('Welcome back to the sanctuary!');
        break;
        
      case 'sanctuary_state_sync':
        debugLog('>>> SANCTUARY: State sync received');
        final isPaused = data['is_paused'] ?? false;
        final activeCoaching = data['active_coaching'] as List? ?? [];
        final myCoachingActive = data['my_coaching_active'] ?? false;

        // Refresh recent messages if provided (prevents missed broadcasts after background/refresh)
        final recent = data['recent_messages'] ?? data['messages'];
        if (recent is List && recent.isNotEmpty) {
          try {
            final incoming = recent.map((m) => Map<String, dynamic>.from(m as Map)).toList();
            // Merge by message_id if possible, otherwise replace with incoming snapshot.
            final existingIds = _messages.map((m) => (m['message_id'] ?? '').toString()).where((id) => id.isNotEmpty).toSet();
            final incomingIds = incoming.map((m) => (m['message_id'] ?? '').toString()).where((id) => id.isNotEmpty).toSet();
            if (existingIds.isEmpty || incomingIds.isEmpty) {
              setState(() => _messages = incoming);
            } else if (!existingIds.containsAll(incomingIds) || incoming.length >= _messages.length) {
              final merged = <Map<String, dynamic>>[];
              final byId = <String, Map<String, dynamic>>{};
              for (final m in _messages) {
                final id = (m['message_id'] ?? '').toString();
                if (id.isNotEmpty) byId[id] = m;
              }
              for (final m in incoming) {
                final id = (m['message_id'] ?? '').toString();
                if (id.isNotEmpty) byId[id] = m;
              }
              // Preserve time order best-effort
              merged.addAll(byId.values);
              merged.sort((a, b) => (a['timestamp'] ?? '').toString().compareTo((b['timestamp'] ?? '').toString()));
              setState(() => _messages = merged);
            }
          } catch (_) {}
        }

        setState(() {
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;

          final bc = data['billing_charges'];
          if (bc is List) {
            try {
              _billingCharges = bc.map((e) => Map<String, dynamic>.from(e as Map)).toList();
            } catch (_) {
              _billingCharges = [];
            }
          }

          // Group coaching status hydration (pending + cooldown)
          final gc = data['group_coaching'];
          if (gc is Map) {
            final pending = gc['pending_request'];
            if (pending is Map) {
              _groupCoachingPendingBy = (pending['requested_by_name'] ?? pending['requested_by'] ?? '').toString().isEmpty
                  ? null
                  : (pending['requested_by_name'] ?? pending['requested_by']).toString();
              _groupCoachingPendingRequestedAt = (pending['requested_at'] as num?)?.toDouble();
              // If I'm HEAD and we haven't shown this request yet, surface approval dialog
              final isHead = _isCurrentUserHead();
              final reqAt = _groupCoachingPendingRequestedAt;
              if (isHead && reqAt != null && reqAt != _groupCoachingLastDialogShownForRequestAt) {
                _groupCoachingLastDialogShownForRequestAt = reqAt;
                WidgetsBinding.instance.addPostFrameCallback((_) {
                  if (!mounted) return;
                  _showGroupCoachingApprovalDialog({
                    'cost': 20.0,
                    'triggered_by': _groupCoachingPendingBy,
                    'message': 'A family member is asking for guidance. Approve Group Coaching (\$20) to generate private, personalized words for each member.',
                    'requested_text': pending['requested_text'],
                  });
                });
              }
            } else {
              _groupCoachingPendingBy = null;
              _groupCoachingPendingRequestedAt = null;
            }

            final ends = gc['cooldown_ends_at'];
            if (ends is int) {
              _groupCoachingCooldownEndsAt = DateTime.fromMillisecondsSinceEpoch(ends * 1000);
              _startGroupCoachingTimer();
            } else {
              _groupCoachingCooldownEndsAt = null;
            }

            final round = gc['round'];
            if (round is Map && round['status']?.toString() == 'ACTIVE') {
              _groupCoachingRoundActive = true;
              // derive waiting_on from round.responses
              final responses = round['responses'];
              if (responses is Map) {
                final pendingIds = <String>[];
                responses.forEach((k, v) {
                  if (v is Map && v['state']?.toString() == 'PENDING') pendingIds.add(k.toString());
                });
                final nameMap = {for (final m in _members) (m['user_id'] ?? m['id'] ?? '').toString(): (m['name'] ?? '').toString()};
                _groupCoachingWaitingOn = pendingIds.map((id) => nameMap[id] ?? id).where((x) => x.isNotEmpty).toList();
                final myId = (widget.profile['hardware_id'] ?? '').toString();
                final my = responses[myId];
                if (my is Map && my['state'] != null) _groupCoachingMyState = my['state'].toString();
              }
            } else {
              _groupCoachingRoundActive = false;
              _groupCoachingWaitingOn = [];
              _hasSuggestedResponse = false;
              _groupCoachingMyState = '';
            }
          }

          if (myCoachingActive) {
            // I'm in coaching - don't show paused
            _sanctuaryPaused = false;
          } else if (isPaused && activeCoaching.isNotEmpty) {
            // Someone else is in coaching
            _sanctuaryPaused = true;
            final coachingMember = activeCoaching.first['member_name'] ?? 'A family member';
            _pausedReason = '$coachingMember is in private coaching.';
          } else {
            // Nobody in coaching - resume
            _sanctuaryPaused = false;
            _pausedReason = '';
          }
          
          // Update members list
          if (data['members'] != null) {
            _members = _parseMembersList(data['members']);
            // Recompute ability to complete from latest roster
            _isCreator = _isCreator || _isCurrentUserHead(_members);
          }
        });
        
        if (!isPaused && !myCoachingActive) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Sanctuary is active! 💙'), backgroundColor: Colors.green),
          );
        }
        break;
      

      // ONBOARDING
      case 'sanctuary_onboarding':
        _showOnboardingDialog(data['message']);
        break;
        
      // MEMBER EVENTS
      case 'sanctuary_member_joined':
        final member = data['member'] as Map<String, dynamic>;
        final memberId = member['id'] ?? member['user_id'];
        if (!_members.any((m) => (m['id'] ?? m['user_id']) == memberId)) {
          setState(() => _members.add(member));
        }
        _addSystemMessage('${member['name']} joined');
        break;
        
      case 'sanctuary_member_returned':
        // Null-safe handling - member data may not always be present
        final memberData = data['member'];
        if (memberData != null && memberData is Map<String, dynamic>) {
          _addSystemMessage('${memberData['name'] ?? 'A member'} has returned to the sanctuary');
        } else {
          _addSystemMessage(data['message'] ?? 'A member has returned to the sanctuary');
        }
        break;
        
      case 'sanctuary_member_exited':
        _addSystemMessage(data['message'] ?? 'A member has left');
        break;
        
      // SESSION START
      case 'sanctuary_started':
        setState(() {
          _sanctuaryStatus = 'ACTIVE';
          _members = _parseMembersList(data['members']);
          _isCreator = data['is_creator'] == true || _isCurrentUserHead(_members);
        });
        _addLittleNateMessage(data['opening_message']);
        break;
        
      // MESSAGES
      case 'sanctuary_message':
        // Server may wrap the actual message in `message`
        final rawMsg = data['message'];
        if (rawMsg is Map) {
          _addMessage(Map<String, dynamic>.from(rawMsg));
        } else {
          _addMessage(data);
        }
        break;
        
      // COACHING

      case 'sanctuary_coaching_offer':
        debugLog('>>> SANCTUARY: Coaching offer received');
        setState(() {
          _showCoachingModal = true;
          _coachingOffer = data;
        });
        break;
        break;

      // GROUP COACHING ($20) - HEAD approval
      case 'sanctuary_group_coaching_offer':
        _showGroupCoachingApprovalDialog(data);
        break;

      // Private "words to say" for each member
      case 'sanctuary_suggested_response':
        setState(() {
          _hasSuggestedResponse = true;
          _suggestedResponseText = (data['suggested_text'] ?? '').toString();
          _suggestedRationale = (data['rationale'] ?? '').toString();
          _suggestedTarget = (data['target_audience'] ?? 'the family').toString();
          _suggestedTone = (data['emotional_tone'] ?? 'supportive').toString();
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;
          _suggestedController.text = _suggestedResponseText;
          _groupCoachingRoundActive = true;
          _groupCoachingMyState = 'PENDING';
        });
        break;

      case 'sanctuary_charge_update':
        setState(() {
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;
          final latest = data['latest_charge'];
          if (latest is Map) {
            _billingCharges.insert(0, Map<String, dynamic>.from(latest));
          }
        });
        break;

      case 'sanctuary_billing_summary':
        setState(() {
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;
          final charges = data['charges'];
          if (charges is List) {
            _billingCharges = charges.map((e) => Map<String, dynamic>.from(e as Map)).toList();
          }
        });
        break;

      case 'sanctuary_group_coaching_status':
        setState(() {
          final state = (data['state'] ?? '').toString();
          if (state == 'PENDING_APPROVAL') {
            _groupCoachingPendingBy = (data['requested_by'] ?? '').toString().isEmpty ? null : (data['requested_by'] ?? '').toString();
            _groupCoachingCooldownEndsAt = null;
            _groupCoachingRoundActive = false;
            _groupCoachingWaitingOn = [];
          } else if (state == 'COOLDOWN') {
            _groupCoachingPendingBy = null;
            final ends = data['cooldown_ends_at'];
            if (ends is int) {
              _groupCoachingCooldownEndsAt = DateTime.fromMillisecondsSinceEpoch(ends * 1000);
              _startGroupCoachingTimer();
            }
            _groupCoachingRoundActive = false;
            _groupCoachingWaitingOn = [];
            _hasSuggestedResponse = false;
            _groupCoachingMyState = '';
          } else if (state == 'ACTIVE') {
            _groupCoachingPendingBy = null;
            _groupCoachingRoundActive = true;
            final waiting = data['waiting_on'];
            if (waiting is List) {
              _groupCoachingWaitingOn = waiting.map((e) => e.toString()).toList();
            }
            final my = data['my_state'];
            if (my != null) _groupCoachingMyState = my.toString();
          } else {
            _groupCoachingPendingBy = null;
            _groupCoachingCooldownEndsAt = null;
            _groupCoachingRoundActive = false;
            _groupCoachingWaitingOn = [];
          }
        });
        break;

      case 'sanctuary_suggestion_declined':
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text((data['message'] ?? 'No problem.').toString()), backgroundColor: Colors.blueGrey),
        );
        break;

      // COACHING STARTED - Enter private coaching mode
      case 'sanctuary_coaching_started':
        debugLog('>>> SANCTUARY: Entering private coaching');
        setState(() {
          _inPrivateCoaching = true;
          _showCoachingModal = false;  // Close any open modal
          _sanctuaryPaused = false;     // Not paused if we're IN coaching
          _coachingMessages = [];
          _coachingAttempt = 1;
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) {
            _totalCharges = total;
          } else {
            // Back-compat: if server didn't send total, fall back to local increment
            final charge = (data['charge_amount'] as num?)?.toDouble() ?? 0.0;
            if (charge > 0) _totalCharges += charge;
          }
        });
        // Add Little Nate's first message
        final startMsg = data['coaching_message'];
        if (startMsg != null) {
          setState(() {
            _coachingMessages.add({
              'role': startMsg['role'] ?? 'assistant',
              'content': startMsg['content'] ?? '',
              'attempt': startMsg['attempt_number'] ?? 1,
            });
          });
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Private coaching started'), backgroundColor: Colors.blue),
        );
        break;
      
      // COACHING RESUMED - User reconnected while in coaching session
      case 'sanctuary_coaching_resumed':
        debugLog('>>> SANCTUARY: Resuming private coaching session');
        setState(() {
          _inPrivateCoaching = true;
          _showCoachingModal = false;  // Close any open modal
          _sanctuaryPaused = false;     // Not paused if we're IN coaching
        });
        final resumeSession = data['coaching_session'];
        if (resumeSession != null) {
          final resumeMessages = resumeSession['messages'] as List<dynamic>? ?? [];
          setState(() {
            _coachingMessages = resumeMessages.map((m) => {
              'role': m['role'] ?? 'assistant',
              'content': m['content'] ?? '',
              'attempt': m['attempt_number'] ?? 1,
            }).toList();
            _coachingAttempt = resumeSession['attempt_number'] ?? 1;
          });
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Resuming coaching session'), backgroundColor: Colors.blue),
        );
        break;
      
      // COACHING RESPONSE from Little Nate
      case 'sanctuary_coaching_response':
        final respMsg = data['coaching_message'];
        setState(() {
          _coachingAttempt = respMsg?['attempt_number'] ?? _coachingAttempt;
          if (respMsg != null) {
            _coachingMessages.add({
              'role': 'assistant',
              'content': respMsg['content'] ?? '',
              'attempt': respMsg['attempt_number'],
            });
          }
        });
        break;
      
      // COACHING LIMIT REACHED - Offer continuation or return
      case 'sanctuary_coaching_limit_reached':
        debugLog('>>> SANCTUARY: Coaching limit reached');
        setState(() {
          _coachingLimitReached = true;
          _coachingMaxSteps = data['max_steps'] ?? 5;
        });
        _showCoachingLimitDialog(data);
        break;
      
      // COACHING EXTENDED - Session extended after $5 payment
      case 'sanctuary_coaching_extended':
        debugLog('>>> SANCTUARY: Coaching extended');
        setState(() {
          _coachingLimitReached = false;
          _coachingMaxSteps = data['new_max_steps'] ?? 10;
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) {
            _totalCharges = total;
          } else {
            final charge = (data['charge_amount'] as num?)?.toDouble() ?? 0.0;
            if (charge > 0) _totalCharges += charge;
          }
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(data['message'] ?? 'Coaching extended!'), backgroundColor: Colors.green),
        );
        break;
      
      // ASSISTED RESPONSE GENERATED
      case 'sanctuary_assisted_response_generated':
        debugLog('>>> SANCTUARY: Assisted response received');
        final assistedResponse = data['assisted_response'] ?? data['response'] ?? '';
        if (assistedResponse.isNotEmpty) {
          final shouldReturn = _pendingAssistedReturn;
          setState(() {
            _assistedResponse = assistedResponse;
            _pendingAssistedReturn = false;
            final total = (data['total_charges'] as num?)?.toDouble();
            if (total != null) {
              _totalCharges = total;
            } else {
              final charge = (data['charge_amount'] as num?)?.toDouble() ?? 0.0;
              if (charge > 0) _totalCharges += charge;
            }
            _coachingMessages.add({
              'role': 'assisted',
              'content': '✨ SUGGESTED RESPONSE:\n\n$assistedResponse',
              'is_assisted': true,
            });
          });
          if (shouldReturn) {
            _completeCoaching();
          }
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('Assisted response ready! Tap "Share to Family" below.'),
              backgroundColor: Colors.green,
              duration: const Duration(seconds: 6),
            ),
          );
        }
        break;
      
      // COACHING COMPLETED - Return to sanctuary
      case 'sanctuary_coaching_completed':
        final bool sanctuaryResumed = data['sanctuary_resumed'] ?? false;
        final int othersInCoaching = data['others_in_coaching'] ?? 0;
        final assisted = data['assisted_response'];
        setState(() {
          _inPrivateCoaching = false;
          _coachingMessages = [];
          _coachingLimitReached = false;
          if (assisted is String && assisted.isNotEmpty) {
            _assistedResponse = assisted;
          }
          // Only unpause if sanctuary is actually resumed (no others in coaching)
          if (sanctuaryResumed) {
            _sanctuaryPaused = false;
            _pausedReason = '';
          } else if (othersInCoaching > 0) {
            _sanctuaryPaused = true;
            _pausedReason = 'Waiting for other family members to finish coaching...';
          }
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(data['message'] ?? 'Welcome back'),
            backgroundColor: Colors.green,
            action: (_assistedResponse != null && _assistedResponse!.isNotEmpty)
                ? SnackBarAction(
                    label: 'Share',
                    textColor: Colors.white,
                    onPressed: _postAssistedResponse,
                  )
                : null,
          ),
        );
        break;
      
      // OTHER MEMBER IN COACHING - Sanctuary paused for us
      case 'sanctuary_member_coaching':
        // Ignore if we just finished coaching (prevent stale message race condition)
        if (!_inPrivateCoaching) {
          setState(() {
            _sanctuaryPaused = true;
            _pausedReason = data['message'] ?? 'A family member is in private coaching.';
          });
        }
        break;
      
      // MEMBER RETURNED from coaching
      case 'sanctuary_member_returned':
        _addSystemMessage(data['message'] ?? 'A family member has returned.');
        break;
      
      // SANCTUARY RESUMED - Everyone back
      case 'sanctuary_resumed':
        setState(() {
          _sanctuaryPaused = false;
          _pausedReason = '';
        });
        _addSystemMessage(data['message'] ?? 'Sanctuary resumed. 💙');
        break;
      case 'sanctuary_generating_summary':
        debugLog('>>> SANCTUARY: Generating summary...');
        setState(() {
          _generatingSummary = true;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Generating session summary... 💙'), backgroundColor: Colors.blue),
        );
        break;

      case 'sanctuary_summary':
        debugLog('>>> SANCTUARY: Summary received');
        setState(() {
          _generatingSummary = false;
          _showSessionSummary = true;
          _sessionSummary = data['summary'] as Map<String, dynamic>?;
          _sessionStats = data['session_stats'] as Map<String, dynamic>?;
        });
        break;

      case 'sanctuary_entry_questions':
        debugLog('>>> SANCTUARY: Entry questions received');
        setState(() {
          _showEntryQuestions = true;
          _entryQuestions = (data['questions'] as List<dynamic>?)?.map((q) => Map<String, dynamic>.from(q as Map)).toList() ?? [];
          _entryResponses = {};
          _feelingScale = 5;
        });
        break;
      case 'sanctuary_entry_complete':
        debugLog('>>> SANCTUARY: Entry complete');
        break;
      case 'sanctuary_entry_ready':
        debugLog('>>> SANCTUARY: Entry ready');
        setState(() {
          _showEntryQuestions = false;
          _sanctuaryId = data['sanctuary_id'];
          _sanctuaryStatus = data['status'] ?? 'ACTIVE';
          final total = (data['total_charges'] as num?)?.toDouble();
          // Never allow the UI to "downgrade" charges to a lower number due to
          // a stale/legacy backend snapshot (e.g. missing ledger -> returns 0).
          if (total != null) {
            if (total >= _totalCharges - 0.001) {
              _totalCharges = total;
            }
          }
          _members = _parseMembersList(data['members']);
          _isCreator = false;  // Joining, not creating
        });
        if (data['messages'] != null) {
          setState(() { _messages = (data['messages'] as List).map((m) => Map<String, dynamic>.from(m)).toList(); });
        }
        _addSystemMessage('Welcome to the sanctuary!');
        break;


      case 'sanctuary_coaching_fer':
        setState(() {
          _coachingOffer = data;
          _showCoachingModal = true;
        });
        break;
        
      case 'sanctuary_coaching':
        _showCoachingDialog(data);
        break;
        
      case 'sanctuary_coaching_notification':
        _showInfo(data['message']);
        break;
        
      // EXIT FLOW
      case 'sanctuary_exit_checkin':
        _showExitDialog(data['message']);
        break;
        
      case 'sanctuary_exited':
        _showInfo('You have exited the sanctuary. You can rejoin anytime.');
        Navigator.pop(context);
        break;
        
      // BILLING
      case 'sanctuary_threshold_notification':
        setState(() {
          final total = (data['total_charges'] as num?)?.toDouble();
          if (total != null) _totalCharges = total;
        });
        _showThresholdDialog(data);
        break;

      case 'sanctuary_spending_alert':
        if (mounted) {
          final msg = data['message']?.toString() ?? '';
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(msg, style: const TextStyle(fontSize: 12)),
            backgroundColor: const Color(0xFF2A2A3E),
            duration: const Duration(seconds: 4),
            action: SnackBarAction(
              label: 'View',
              textColor: const Color(0xFFC9A962),
              onPressed: _showBillingLedgerSheet,
            ),
          ));
        }
        break;

      case 'sanctuary_pre_session_estimate':
        _showPreSessionEstimate(data);
        break;

      // COMPLETION
      case 'sanctuary_completed':
        _showCompletionDialog(data);
        break;
        
      // SECURITY
      case 'security_disconnect':
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(data['reason']?.toString() ?? 'Session terminated for security.'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 6),
          ));
          Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LobbyScreen()), (r) => false);
        }
        break;

      // ERRORS
      case 'error':
        final errMsg = (data['message'] ?? 'An error occurred').toString();
        _showError(errMsg);
        if (errMsg.contains('UPGRADE_REQUIRED') || errMsg.contains('COACH_ONLY') || errMsg.contains('Not authenticated')) {
          Future.delayed(const Duration(seconds: 2), () {
            if (mounted) Navigator.pop(context);
          });
        }
        break;
        
      default:
        debugLog('>>> SANCTUARY: Unhandled message type: $type');
    }
  }

  // Helper: Parse members list (handles different formats)
  List<Map<String, dynamic>> _parseMembersList(dynamic members) {
    if (members == null) return [];
    
    if (members is List) {
      return members.map((m) {
        if (m is String) {
          return {'name': m, 'status': 'ACTIVE'};
        } else if (m is Map) {
          return Map<String, dynamic>.from(m);
        }
        return {'name': m.toString(), 'status': 'ACTIVE'};
      }).toList().cast<Map<String, dynamic>>();
    }
    
    return [];
  }

  bool _isCurrentUserHead([List<Map<String, dynamic>>? members]) {
    final myId = (widget.profile['hardware_id'] ?? '').toString();
    if (myId.isEmpty) return false;
    final list = members ?? _members;
    for (final m in list) {
      final userId = (m['user_id'] ?? m['id'] ?? m['member_id'] ?? '').toString();
      if (userId != myId) continue;
      final role = (m['role'] ?? '').toString().toUpperCase();
      if (role == 'HEAD' || role == 'HEAD_OF_HOUSEHOLD') return true;
    }
    return false;
  }

  bool get _canCompleteSanctuary => _isCreator || _isCurrentUserHead();

  // ===========================================================================
  // SANCTUARY ACTIONS
  // ===========================================================================

  void _joinExistingSanctuary(String sanctuaryId) {
    _channel!.sink.add(json.encode({
      'type': 'sanctuary_join',
      'sanctuary_id': sanctuaryId,
    }));
  }

  void _sendMessage() {
    // If speech-to-text is active, stop it first so it can't re-fill the field after send.
    // (Speech engines often emit a "final" result right after you clear the controller.)
    _stopSpeechAndSuppressLateResults();

    final text = _normalizeDictation(_messageController.text).trim();
    if (text.isEmpty || _sanctuaryId == null) return;

    _channel!.sink.add(json.encode({
      'type': 'sanctuary_message',
      'sanctuary_id': _sanctuaryId,
      'message': text,
    }));

    _messageController.clear();
    _scrollToBottom();
  }

  void _acceptCoaching({bool assistedResponse = false}) {
    if (_coachingOffer == null) return;

    _channel!.sink.add(json.encode({
      'type': 'sanctuary_coaching_accept',
      'sanctuary_id': _sanctuaryId,
      'intervention_id': _coachingOffer!['intervention_id'],
      'assisted_response': assistedResponse,
    }));

    setState(() {
      _showCoachingModal = false;
      _coachingOffer = null;
    });
  }


  Widget _buildEntryQuestionsOverlay() {
    if (!_showEntryQuestions) return const SizedBox.shrink();
    return Container(
      color: Colors.black.withOpacity(0.95),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            children: [
              const Icon(Icons.favorite, color: Colors.cyan, size: 48),
              const SizedBox(height: 16),
              const Text('Before We Begin', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.white)),
              const Text('Help Little Nate understand where you are', style: TextStyle(color: Colors.grey)),
              const SizedBox(height: 24),
              ..._entryQuestions.map((q) {
                final id = q['id'] as String;
                final type = q['type'] as String;
                return Container(
                  margin: const EdgeInsets.only(bottom: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(q['question'] as String, style: const TextStyle(color: Colors.white, fontSize: 16)),
                      const SizedBox(height: 8),
                      if (type == 'text')
                        TextField(
                          onChanged: (v) => setState(() => _entryResponses[id] = v),
                          style: const TextStyle(color: Colors.white),
                          maxLines: 2,
                          decoration: InputDecoration(
                            hintText: q['placeholder'] as String? ?? '',
                            hintStyle: const TextStyle(color: Colors.grey),
                            filled: true,
                            fillColor: const Color(0xFF1a1a2e),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                          ),
                        )
                      else if (type == 'scale')
                        Column(
                          children: [
                            Slider(
                              value: _feelingScale.toDouble(),
                              min: 1, max: 10, divisions: 9,
                              activeColor: _feelingScale <= 3 ? Colors.red : _feelingScale <= 6 ? Colors.orange : Colors.green,
                              onChanged: (v) => setState(() { _feelingScale = v.round(); _entryResponses[id] = _feelingScale; }),
                            ),
                            Text('$_feelingScale / 10', style: TextStyle(color: _feelingScale <= 3 ? Colors.red : _feelingScale <= 6 ? Colors.orange : Colors.green, fontSize: 24, fontWeight: FontWeight.bold)),
                          ],
                        ),
                    ],
                  ),
                );
              }).toList(),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    _entryResponses['feeling_scale'] = _feelingScale;
                    _channel?.sink.add(jsonEncode({'type': 'sanctuary_entry_responses', 'sanctuary_id': _sanctuaryId, 'responses': _entryResponses}));
                  },
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.cyan, padding: const EdgeInsets.symmetric(vertical: 16)),
                  child: const Text('Begin Session', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  
  Widget _buildSessionSummaryOverlay() {
    if (_generatingSummary) {
      return Container(
        color: Colors.black87,
        child: const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(color: Colors.cyan),
              SizedBox(height: 24),
              Text('Generating session summary...', style: TextStyle(color: Colors.white, fontSize: 18)),
              Text('💙', style: TextStyle(fontSize: 32)),
            ],
          ),
        ),
      );
    }
    if (!_showSessionSummary || _sessionSummary == null) return const SizedBox.shrink();
    
    final summary = _sessionSummary!;
    final stats = _sessionStats ?? {};
    final insights = summary['your_insights'] as Map<String, dynamic>? ?? {};
    
    return Container(
      color: Colors.black.withOpacity(0.95),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(children: [
                Icon(Icons.summarize, color: Colors.cyan, size: 32),
                SizedBox(width: 12),
                Text('Session Summary', style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Colors.white)),
              ]),
              const SizedBox(height: 16),
              // Stats
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: const Color(0xFF1a1a2e), borderRadius: BorderRadius.circular(12)),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    Column(children: [Text('${stats['duration_minutes'] ?? 0}m', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.cyan)), const Text('Duration', style: TextStyle(color: Colors.grey, fontSize: 12))]),
                    Column(children: [Text('${stats['total_messages'] ?? 0}', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.cyan)), const Text('Messages', style: TextStyle(color: Colors.grey, fontSize: 12))]),
                    Column(children: [Text('${summary['overall_progress'] ?? 5}/10', style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.cyan)), const Text('Progress', style: TextStyle(color: Colors.grey, fontSize: 12))]),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              // Conflicts
              if ((summary['key_conflicts'] as List?)?.isNotEmpty ?? false) ...[
                const Row(children: [Icon(Icons.warning_amber, color: Colors.orange, size: 20), SizedBox(width: 8), Text('Key Conflicts', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))]),
                const SizedBox(height: 8),
                ...((summary['key_conflicts'] as List?) ?? []).map((c) => Padding(padding: const EdgeInsets.only(left: 28, bottom: 4), child: Text('• $c', style: const TextStyle(color: Colors.grey)))),
                const SizedBox(height: 16),
              ],
              // Agreement
              if ((summary['points_of_agreement'] as List?)?.isNotEmpty ?? false) ...[
                const Row(children: [Icon(Icons.handshake, color: Colors.green, size: 20), SizedBox(width: 8), Text('Points of Agreement', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))]),
                const SizedBox(height: 8),
                ...((summary['points_of_agreement'] as List?) ?? []).map((c) => Padding(padding: const EdgeInsets.only(left: 28, bottom: 4), child: Text('• $c', style: const TextStyle(color: Colors.grey)))),
                const SizedBox(height: 16),
              ],
              // Your Insights
              if (insights.isNotEmpty) ...[
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(colors: [Colors.cyan.withOpacity(0.2), Colors.blue.withOpacity(0.1)]),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.cyan.withOpacity(0.5)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(children: [Icon(Icons.person, color: Colors.cyan), SizedBox(width: 8), Text('Your Personal Insights', style: TextStyle(color: Colors.cyan, fontWeight: FontWeight.bold, fontSize: 16))]),
                      const SizedBox(height: 12),
                      if (insights['patterns_observed'] != null) _insightRow('Patterns', insights['patterns_observed']),
                      if (insights['growth_areas'] != null) _insightRow('Growth Areas', insights['growth_areas']),
                      if (insights['strengths_shown'] != null) _insightRow('Strengths', insights['strengths_shown']),
                      if (insights['suggested_focus'] != null) _insightRow('Focus', insights['suggested_focus']),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
              ],
              // Next Steps
              if ((summary['next_steps'] as List?)?.isNotEmpty ?? false) ...[
                const Row(children: [Icon(Icons.arrow_forward, color: Colors.blue, size: 20), SizedBox(width: 8), Text('Next Steps', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))]),
                const SizedBox(height: 8),
                ...((summary['next_steps'] as List?) ?? []).map((c) => Padding(padding: const EdgeInsets.only(left: 28, bottom: 4), child: Text('• $c', style: const TextStyle(color: Colors.grey)))),
              ],
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    setState(() { _showSessionSummary = false; _sessionSummary = null; });
                    Navigator.of(context).pop();
                  },
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.cyan, padding: const EdgeInsets.symmetric(vertical: 16)),
                  child: const Text('Close & Exit', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
  
  Widget _insightRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(color: Colors.cyan, fontSize: 12, fontWeight: FontWeight.bold)),
          Text(value, style: const TextStyle(color: Colors.white)),
        ],
      ),
    );
  }

  void _saveConversation() {
    if (_messages.isEmpty) return;
    final buffer = StringBuffer();
    buffer.writeln('--- Sanctuary Conversation ---');
    buffer.writeln('Date: ${DateTime.now().toIso8601String()}');
    buffer.writeln('');
    for (final msg in _messages) {
      final sender = (msg['sender_name'] ?? msg['sender'] ?? 'Unknown').toString();
      final content = (msg['content'] ?? '').toString();
      buffer.writeln('$sender: $content');
      buffer.writeln('');
    }
    final text = buffer.toString();
    Clipboard.setData(ClipboardData(text: text));
    _channel?.sink.add(json.encode({
      'type': 'export_conversation',
      'format': 'full',
    }));

    final token = widget.profile['token'] as String?;
    final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
    http.post(
      Uri.parse('$base/api/v1/vault/save-conversation'),
      headers: {
        'Content-Type': 'application/json',
        if (token != null && token.isNotEmpty) 'Authorization': 'Bearer $token',
      },
      body: json.encode({
        'content': text,
        'title': 'Sanctuary Session — ${DateTime.now().toIso8601String().split("T").first}',
        'source': 'sanctuary',
      }),
    ).catchError((_) {});

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Conversation saved to vault & copied'),
          duration: Duration(seconds: 2),
        ),
      );
    }
  }

  void _exitSanctuary() {
    _channel!.sink.add(json.encode({
      'type': 'sanctuary_exit',
      'sanctuary_id': _sanctuaryId,
    }));
  }

  void _confirmExit(String reason, bool informFamily) {
    _channel!.sink.add(json.encode({
      'type': 'sanctuary_exit_confirm',
      'sanctuary_id': _sanctuaryId,
      'reason': reason,
      'inform_family': informFamily,
    }));
  }

  void _completeSanctuary() {
    _channel!.sink.add(json.encode({
      'type': 'sanctuary_complete',
      'sanctuary_id': _sanctuaryId,
    }));
  }

  // ===========================================================================
  // MESSAGE HANDLING
  // ===========================================================================

  void _addMessage(Map<String, dynamic> data) {
    // Some server events wrap message payload as { type: 'sanctuary_message', message: {...} }
    final maybeWrapped = data['message'];
    if (maybeWrapped is Map) {
      data = Map<String, dynamic>.from(maybeWrapped);
    }

    final messageType = (data['message_type'] ?? data['type'])?.toString();
    final senderId = (data['sender_id'] ?? '').toString();
    final senderName = (data['sender_name'] ?? data['sender'] ?? data['name'] ?? 'Unknown').toString();
    final content = (data['content'] ?? '').toString();
    final timestamp = (data['timestamp'] ?? DateTime.now().toIso8601String()).toString();

    setState(() {
      _messages.add({
        'type': messageType,
        'sender_id': senderId,
        'sender_name': senderName,
        'content': content,
        'timestamp': timestamp,
      });
    });
    _scrollToBottom();
  }

  void _addLittleNateMessage(String content) {
    setState(() {
      _messages.add({
        'type': 'LITTLE_NATE',
        'sender_id': 'LITTLE_NATE',
        'sender_name': 'Little Nate',
        'content': content,
        'timestamp': DateTime.now().toIso8601String(),
      });
    });
    _scrollToBottom();
  }

  void _addSystemMessage(String content) {
    setState(() {
      _messages.add({
        'type': 'SYSTEM',
        'sender_id': 'SYSTEM',
        'sender_name': 'System',
        'content': content,
        'timestamp': DateTime.now().toIso8601String(),
      });
    });
    _scrollToBottom();
  }

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // ===========================================================================
  // UI DIALOGS
  // ===========================================================================

  void _showOnboardingDialog(String message) {
    final reasonController = TextEditingController();
    final goalController = TextEditingController();
    final concernsController = TextEditingController();

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E1E),
        title: const Text('Welcome to Family Sanctuary', style: TextStyle(color: Colors.white)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(message, style: const TextStyle(color: Colors.white70)),
              const SizedBox(height: 20),
              TextField(
                controller: reasonController,
                style: const TextStyle(color: Colors.white),
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: '1. Why did you come here today?',
                  labelStyle: TextStyle(color: Colors.white70),
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: goalController,
                style: const TextStyle(color: Colors.white),
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: "2. What's your goal?",
                  labelStyle: TextStyle(color: Colors.white70),
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: concernsController,
                style: const TextStyle(color: Colors.white),
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: '3. What concerns do you have?',
                  labelStyle: TextStyle(color: Colors.white70),
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
        ),
        actions: [
          ElevatedButton(
            onPressed: () {
              _channel!.sink.add(json.encode({
                'type': 'sanctuary_onboarding_complete',
                'sanctuary_id': _sanctuaryId,
                'responses': {
                  'reason': reasonController.text,
                  'goal': goalController.text,
                  'concerns': concernsController.text,
                },
              }));
              Navigator.pop(context);
            },
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF003366)),
            child: const Text('Continue', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  void _showCoachingDialog(Map<String, dynamic> data) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E1E),
        title: Row(
          children: const [
            Text('💙 ', style: TextStyle(fontSize: 24)),
            Text('Coaching from Little Nate', style: TextStyle(color: Colors.white)),
          ],
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                data['coaching_content'],
                style: const TextStyle(color: Colors.white70, fontSize: 16),
              ),
              const SizedBox(height: 20),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF2A2A2A),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      data['is_free'] ? '🎁 FREE Coaching' : 'Charged: \$${data['charge_amount']}',
                      style: TextStyle(
                        color: data['is_free'] ? Colors.greenAccent : Colors.amber,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text(
                      'Coaching #${data['coaching_number']}',
                      style: const TextStyle(color: Colors.white70),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close', style: TextStyle(color: Colors.white70)),
          ),
        ],
      ),
    );
  }

  void _showExitDialog(String message) {
    final reasonController = TextEditingController();
    bool informFamily = true;

    showDialog(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: const Color(0xFF1E1E1E),
          title: const Text("Exit Sanctuary?", style: TextStyle(color: Colors.white)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(message, style: const TextStyle(color: Colors.white70)),
              const SizedBox(height: 20),
              TextField(
                controller: reasonController,
                style: const TextStyle(color: Colors.white),
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: "How are you feeling?",
                  labelStyle: TextStyle(color: Colors.white70),
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 16),
              CheckboxListTile(
                title: const Text("Let family know I'm taking a break", style: TextStyle(color: Colors.white70)),
                value: informFamily,
                onChanged: (value) => setDialogState(() => informFamily = value!),
                activeColor: const Color(0xFF003366),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text("Stay", style: TextStyle(color: Colors.white70)),
            ),
            ElevatedButton(
              onPressed: () {
                _confirmExit(reasonController.text, informFamily);
                Navigator.pop(context);
              },
              style: ElevatedButton.styleFrom(backgroundColor: Colors.redAccent),
              child: const Text("Exit", style: TextStyle(color: Colors.white)),
            ),
          ],
        ),
      ),
    );
  }

  void _showThresholdDialog(Map<String, dynamic> data) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E1E),
        title: Row(
          children: const [
            Text("💰 ", style: TextStyle(fontSize: 24)),
            Text("Cost Milestone", style: TextStyle(color: Colors.white)),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              "Current charges: \$${data["total_charges"]}",
              style: const TextStyle(color: Colors.amber, fontSize: 18, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            Text(data["message"], style: const TextStyle(color: Colors.white70)),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("Continue", style: TextStyle(color: Colors.white70)),
          ),
          if (data["offer_coach"] == true)
            ElevatedButton(
              onPressed: () {
                _channel?.sink.add(json.encode({
                  "type": "sanctuary_request_coach",
                  "sanctuary_id": _sanctuaryId,
                }));
                Navigator.pop(context);
              },
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF003366)),
              child: const Text("Request Coach", style: TextStyle(color: Colors.white)),
            ),
        ],
      ),
    );
  }

  void _showPreSessionEstimate(Map<String, dynamic> data) {
    final items = (data['items'] as List?)?.cast<Map<String, dynamic>>() ?? [];
    final minEstimate = (data['minimum_estimate'] as num?)?.toDouble() ?? 0;
    final currentTotal = (data['current_total'] as num?)?.toDouble() ?? 0;
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Row(children: const [
          Icon(Icons.receipt_long, color: Color(0xFF4ECDC4), size: 20),
          SizedBox(width: 8),
          Text('Session Cost Estimate', style: TextStyle(color: Colors.white, fontSize: 16)),
        ]),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (currentTotal > 0)
              Text('Current session total: \$${currentTotal.toStringAsFixed(2)}',
                  style: const TextStyle(color: Colors.amber, fontSize: 13)),
            const SizedBox(height: 8),
            ...items.map((item) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(child: Text(
                    '${item["type"]}${item["note"] != null ? " (${item["note"]})" : ""}',
                    style: const TextStyle(color: Colors.white70, fontSize: 12),
                  )),
                  Text('\$${(item["amount"] as num).toStringAsFixed(2)}',
                      style: const TextStyle(color: Colors.white, fontSize: 12)),
                ],
              ),
            )),
            if (minEstimate > 0) ...[
              const Divider(color: Colors.white10),
              Text('Minimum additional cost: \$${minEstimate.toStringAsFixed(2)}',
                  style: const TextStyle(color: Colors.amber, fontSize: 13, fontWeight: FontWeight.w600)),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Got it', style: TextStyle(color: Color(0xFFC9A962))),
          ),
        ],
      ),
    );
  }

  void _showCompletionDialog(Map<String, dynamic> data) {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E1E),
        title: const Text("🎉 Sanctuary Complete", style: TextStyle(color: Colors.white)),
        content: SingleChildScrollView(
          child: Text(data["summary"], style: const TextStyle(color: Colors.white70)),
        ),
        actions: [
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              Navigator.pop(context);
            },
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF003366)),
            child: const Text("Done", style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

void _showCoachingLimitDialog(Map<String, dynamic> data) {
    final isDeescalated = data['is_deescalated'] ?? false;
    final continueCost = data['options']?['continue_cost'] ?? 5.00;
    final assistedCost = data['options']?['assisted_response_cost'] ?? 3.00;
    
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1a1a2e),
        title: Row(
          children: [
            Icon(isDeescalated ? Icons.check_circle : Icons.info, color: Colors.blue),
            const SizedBox(width: 8),
            Text(
              isDeescalated ? 'Great Progress!' : 'Coaching Checkpoint',
              style: const TextStyle(color: Colors.white),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              data['message'] ?? "You've completed your coaching exchanges.",
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 16),
            const Text(
              'What would you like to do?',
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              _completeCoaching();
            },
            child: const Text('Return to Family', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              setState(() {
                _pendingAssistedReturn = true;
              });
              _requestAssistedResponse();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.amber[700]),
            child: Text('Get Help + Return (\$${assistedCost.toStringAsFixed(0)})'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _extendCoaching();
            },
            style: ElevatedButton.styleFrom(backgroundColor: Colors.blue),
            child: Text('Continue Coaching (\$${continueCost.toStringAsFixed(0)})'),
          ),
        ],
      ),
    );
  }

  void _extendCoaching() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_coaching_extend',
      'sanctuary_id': _sanctuaryId,
    }));
    setState(() {
      _coachingLimitReached = false;
    });
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.redAccent),
    );
  }

  void _showSuccess(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.green),
    );
  }

  void _showInfo(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: const Color(0xFF003366)),
    );
  }

  // ===========================================================================
  // BUILD UI
  // ===========================================================================
  // SANCTUARY PAUSED OVERLAY (while others are in private coaching)
  // ===========================================================================
  Widget _buildSanctuaryPausedOverlay() {
  return Container(
    color: const Color(0xFF0D1B2A),
    child: Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.pause_circle_outline, color: Colors.blue, size: 80),
          const SizedBox(height: 24),
          const Text(
            'Sanctuary Paused',
            style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 16),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              _pausedReason.isNotEmpty ? _pausedReason : 'A family member is receiving private coaching from Little Nate.',
              style: const TextStyle(color: Colors.white70, fontSize: 16),
              textAlign: TextAlign.center,
            ),
          ),
          const SizedBox(height: 32),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.blue.withOpacity(0.1),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.blue.withOpacity(0.3)),
            ),
            child: Column(
              children: const [
                Icon(Icons.favorite, color: Colors.blue, size: 32),
                SizedBox(height: 8),
                Text(
                  'Take this moment to breathe',
                  style: TextStyle(color: Colors.white70),
                ),
                SizedBox(height: 4),
                Text(
                  'The sanctuary will resume when everyone returns',
                  style: TextStyle(color: Colors.white54, fontSize: 12),
                ),
              ],
            ),
          ),
          const SizedBox(height: 40),
          // NEW: Refresh and Exit buttons
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Refresh button - sync state from server
              OutlinedButton.icon(
                onPressed: _syncSanctuaryState,
                icon: const Icon(Icons.refresh, color: Colors.blue),
                label: const Text('Refresh Status', style: TextStyle(color: Colors.blue)),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Colors.blue),
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                ),
              ),
              const SizedBox(width: 16),
              // Exit button - leave sanctuary
              OutlinedButton.icon(
                onPressed: _exitSanctuary,
                icon: const Icon(Icons.exit_to_app, color: Colors.redAccent),
                label: const Text('Exit Sanctuary', style: TextStyle(color: Colors.redAccent)),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Colors.redAccent),
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                ),
              ),
            ],
          ),
        ],
      ),
    ),
  );
}

void _syncSanctuaryState() {
  debugLog('>>> SANCTUARY: Requesting state sync...');
  _channel?.sink.add(jsonEncode({
    'type': 'sanctuary_sync_state',
    'sanctuary_id': _sanctuaryId,
  }));
}

  // ===========================================================================
  // COACHING OFFER MODAL
  // ===========================================================================
  Widget _buildCoachingOfferModal() {
    if (!_showCoachingModal || _coachingOffer == null) return const SizedBox();
    
    final isFree = _coachingOffer!['is_free'] ?? false;
    final cost = _coachingOffer!['cost'] ?? 5.00;
    
    return Container(
      color: Colors.black54,
      child: Center(
        child: Container(
          margin: const EdgeInsets.all(32),
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(
            color: const Color(0xFF1a1a2e),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: Colors.blue.withOpacity(0.3)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.favorite, color: Colors.blue, size: 40),
              const SizedBox(height: 16),
              Text(
                'Hi ${widget.profile['name']?.split(' ')[0] ?? 'Friend'},',
                style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              const Text(
                'I notice an opportunity to provide support.',
                style: TextStyle(color: Colors.white70),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.blue.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(isFree ? Icons.card_giftcard : Icons.attach_money, color: Colors.amber),
                    const SizedBox(width: 8),
                    Text(
                      isFree ? 'First coaching FREE!' : 'Coaching: \$${cost.toStringAsFixed(2)}',
                      style: const TextStyle(color: Colors.amber, fontWeight: FontWeight.bold),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextButton(
                    onPressed: () {
                      setState(() {
                        _showCoachingModal = false;
                        _coachingOffer = null;
                      });
                      _channel?.sink.add(jsonEncode({
                        'type': 'sanctuary_coaching_decline',
                        'sanctuary_id': _sanctuaryId,
                        'intervention_id': _coachingOffer?['intervention_id'],
                      }));
                    },
                    child: const Text('No Thanks', style: TextStyle(color: Colors.grey)),
                  ),
                  const SizedBox(width: 16),
                  ElevatedButton(
                    onPressed: () {
                      setState(() => _showCoachingModal = false);
                      _channel?.sink.add(jsonEncode({
                        'type': 'sanctuary_coaching_accept',
                        'sanctuary_id': _sanctuaryId,
                        'intervention_id': _coachingOffer?['intervention_id'],
                      }));
                    },
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.blue),
                    child: Text(isFree ? 'Get Coaching' : 'Get Coaching (\$${cost.toStringAsFixed(2)})'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ===========================================================================

  
  // ===========================================================================
  // PRIVATE COACHING UI
  // ===========================================================================
  Widget _buildPrivateCoachingUI() {
    return Container(
      color: const Color(0xFF0D1B2A),
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.blue.withOpacity(0.2),
              border: Border(bottom: BorderSide(color: Colors.blue.withOpacity(0.3))),
            ),
            child: Row(
              children: [
                const Icon(Icons.lock, color: Colors.blue, size: 24),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Private Coaching', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                      Text('This conversation is confidential', style: TextStyle(color: Colors.blue[200], fontSize: 12)),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(color: Colors.blue.withOpacity(0.3), borderRadius: BorderRadius.circular(12)),
                  child: Text('Step $_coachingAttempt/5', style: const TextStyle(color: Colors.white, fontSize: 12)),
                ),
              ],
            ),
          ),
          // Messages
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.all(16),
              itemCount: _coachingMessages.length,
              itemBuilder: (context, index) {
                final msg = _coachingMessages[index];
                final isNate = msg['role'] == 'assistant';
                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Row(
                    mainAxisAlignment: isNate ? MainAxisAlignment.start : MainAxisAlignment.end,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (isNate) ...[
                        CircleAvatar(radius: 16, backgroundColor: Colors.blue, child: const Icon(Icons.psychology, color: Colors.white, size: 18)),
                        const SizedBox(width: 8),
                      ],
                      Flexible(
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: isNate ? Colors.blue.withOpacity(0.2) : Colors.grey[800],
                            borderRadius: BorderRadius.circular(12),
                            border: isNate ? Border.all(color: Colors.blue.withOpacity(0.3)) : null,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              if (isNate) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('Little Nate', style: TextStyle(color: Colors.blue[300], fontSize: 11, fontWeight: FontWeight.bold))),
                              Text(msg['content'] ?? '', style: const TextStyle(color: Colors.white, fontSize: 14)),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          // Input
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(color: const Color(0xFF0D1B2A), border: Border(top: BorderSide(color: Colors.blue.withOpacity(0.2)))),
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _coachingController,
                        style: const TextStyle(color: Colors.white),
                        minLines: 1,
                        maxLines: 5,
                        keyboardType: TextInputType.multiline,
                        textInputAction: TextInputAction.newline,
                        scrollPhysics: const BouncingScrollPhysics(),
                        decoration: InputDecoration(
                          hintText: 'Share with Little Nate (confidential)...',
                          hintStyle: TextStyle(color: Colors.grey[500]),
                          filled: true, fillColor: Colors.grey[900],
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
                          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(onPressed: _sendCoachingMessage, icon: const Icon(Icons.send, color: Colors.blue)),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    TextButton.icon(
                      onPressed: _completeCoaching,
                      icon: const Icon(Icons.arrow_back, size: 18),
                      label: const Text('Return to Sanctuary'),
                      style: TextButton.styleFrom(foregroundColor: Colors.grey[400]),
                    ),
                    if (_coachingAttempt >= 3 && !_pendingAssistedReturn)
                      TextButton.icon(
                        onPressed: () {
                          setState(() { _pendingAssistedReturn = true; });
                          _requestAssistedResponse();
                        },
                        icon: const Icon(Icons.auto_fix_high, size: 18),
                        label: const Text('Get Help (+\$3)'),
                        style: TextButton.styleFrom(foregroundColor: Colors.amber),
                      ),
                    if (_pendingAssistedReturn)
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.amber)),
                          const SizedBox(width: 8),
                          Text('Generating response...', style: TextStyle(color: Colors.amber.shade200, fontSize: 13)),
                        ],
                      ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _sendCoachingMessage() {
    final message = _coachingController.text.trim();
    if (message.isEmpty) return;
    setState(() {
      _coachingMessages.add({'role': 'user', 'content': message, 'attempt': _coachingAttempt});
    });
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_coaching_message',
      'sanctuary_id': _sanctuaryId,
      'message': message,
    }));
    _coachingController.clear();
  }

  void _completeCoaching() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_coaching_complete',
      'sanctuary_id': _sanctuaryId,
      'request_assisted_response': false,
    }));
  }

  void _requestAssistedResponse() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_request_assisted_response',
      'sanctuary_id': _sanctuaryId,
    }));
  }

  void _showBillingLedgerSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0F),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) {
        final charges = List<Map<String, dynamic>>.from(_billingCharges);
        charges.sort((a, b) => (b['timestamp'] ?? '').toString().compareTo((a['timestamp'] ?? '').toString()));

        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  "Billing Ledger",
                  style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
                ),
                const SizedBox(height: 6),
                Text(
                  "Total: \$${_totalCharges.toStringAsFixed(2)}",
                  style: const TextStyle(color: Colors.amber, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 12),
                if (charges.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 18),
                    child: Text("No charges yet.", style: TextStyle(color: Colors.white54)),
                  )
                else
                  Flexible(
                    child: ListView.separated(
                      shrinkWrap: true,
                      itemCount: charges.length,
                      separatorBuilder: (_, __) => const Divider(color: Colors.white10),
                      itemBuilder: (context, i) {
                        final c = charges[i];
                        final type = (c['type'] ?? 'CHARGE').toString();
                        final status = (c['status'] ?? '').toString();
                        final recipient = (c['recipient'] ?? c['billed_to'] ?? '').toString();
                        final ts = (c['timestamp'] ?? '').toString();
                        final amount = (c['amount'] is num) ? (c['amount'] as num).toDouble() : double.tryParse((c['amount'] ?? '0').toString()) ?? 0.0;
                        return ListTile(
                          dense: true,
                          title: Text(
                            "$type  •  \$${amount.toStringAsFixed(2)}",
                            style: const TextStyle(color: Colors.white),
                          ),
                          subtitle: Text(
                            [
                              if (recipient.isNotEmpty) "recipient: $recipient",
                              if (status.isNotEmpty) "status: $status",
                              if (ts.isNotEmpty) ts,
                            ].join("  •  "),
                            style: const TextStyle(color: Colors.white54, fontSize: 12),
                          ),
                        );
                      },
                    ),
                  ),
                const SizedBox(height: 10),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    TextButton.icon(
                      icon: const Icon(Icons.receipt_long, size: 14, color: Color(0xFF4ECDC4)),
                      label: const Text("Cost Schedule", style: TextStyle(color: Color(0xFF4ECDC4), fontSize: 12)),
                      onPressed: () {
                        Navigator.pop(ctx);
                        _showCostScheduleSheet();
                      },
                    ),
                    TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text("Close", style: TextStyle(color: Color(0xFFFFD700))),
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _showCostScheduleSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0A0A0F),
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.7,
        maxChildSize: 0.9,
        minChildSize: 0.4,
        expand: false,
        builder: (_, scrollCtrl) => Padding(
          padding: const EdgeInsets.all(16),
          child: ListView(
            controller: scrollCtrl,
            children: [
              const Text("Master Cost Schedule", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 17)),
              const SizedBox(height: 4),
              const Text("All Family Sanctuary charges", style: TextStyle(color: Colors.white54, fontSize: 12)),
              const SizedBox(height: 14),
              _costRow("Base Session Fee", "\$20.00", "Charged once per session"),
              _costRow("Assisted Response", "\$3.00", "AI-crafted group message"),
              _costRow("Coaching (1st/member)", "FREE", "First coaching per member"),
              _costRow("Coaching (additional)", "\$5.00", "Per additional session"),
              _costRow("Group Coaching", "\$20.00", "Per round, HoH approval required"),
              const Divider(color: Colors.white10, height: 24),
              const Text("Membership Tiers", style: TextStyle(color: Color(0xFFC9A962), fontWeight: FontWeight.w600, fontSize: 14)),
              const SizedBox(height: 8),
              _costRow("Threshold (Trial)", "Free 14 days", "50K tokens, 300 AI min"),
              _costRow("Inner Chamber", "\$49/mo", "Yearly: \$490 (17% savings)"),
              _costRow("Sovereign Circle", "\$149/mo", "Yearly: \$1,490 (17% savings)"),
              if (!isNativeIOS) ...[
                const Divider(color: Colors.white10, height: 24),
                const Text("Payment Methods", style: TextStyle(color: Color(0xFFC9A962), fontWeight: FontWeight.w600, fontSize: 14)),
                const SizedBox(height: 8),
                _costRow("Credit/Debit Card", "2.9% + \$0.30", "Standard processing"),
                _costRow("ACH Bank Debit", "0.8% (max \$5)", "Lower fees, 4-5 day settlement"),
              ],
              const SizedBox(height: 16),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text("Close", style: TextStyle(color: Color(0xFFFFD700))),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _costRow(String item, String price, String note) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 3,
            child: Text(item, style: const TextStyle(color: Colors.white, fontSize: 13)),
          ),
          SizedBox(
            width: 80,
            child: Text(price, style: const TextStyle(color: Colors.amber, fontSize: 13, fontWeight: FontWeight.w600), textAlign: TextAlign.right),
          ),
          const SizedBox(width: 10),
          Expanded(
            flex: 3,
            child: Text(note, style: const TextStyle(color: Colors.white38, fontSize: 11)),
          ),
        ],
      ),
    );
  }


  @override
  Widget build(BuildContext context) {
    final isNarrow = MediaQuery.of(context).size.width < 420;
    return Scaffold(
      resizeToAvoidBottomInset: true,
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF1E1E1E),
        title: const Text('Family Sanctuary', style: TextStyle(color: Colors.white)),
        actions: [
          InkWell(
            onTap: _showBillingLedgerSheet,
            borderRadius: BorderRadius.circular(12),
            child: Container(
              padding: EdgeInsets.symmetric(horizontal: isNarrow ? 10 : 12, vertical: isNarrow ? 4 : 6),
              decoration: BoxDecoration(
                color: const Color(0xFF2A2A2A),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    '\$${_totalCharges.toStringAsFixed(2)}',
                    style: TextStyle(
                      color: Colors.amber,
                      fontWeight: FontWeight.bold,
                      fontSize: isNarrow ? 14 : 16,
                    ),
                  ),
                  if (!isNarrow && _groupCoachingIndicatorText != null) ...[
                    const SizedBox(height: 2),
                    Text(
                      _groupCoachingIndicatorText!,
                      style: const TextStyle(color: Colors.white54, fontSize: 10),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(width: 6),
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert, color: Colors.white),
            onSelected: (value) {
              if (value == 'exit') _exitSanctuary();
              if (value == 'complete') _completeSanctuary();
              if (value == 'save_chat') _saveConversation();
            },
            itemBuilder: (context) => [
              const PopupMenuItem(value: 'save_chat', child: Row(children: [
                Icon(Icons.save_alt, size: 18, color: Colors.white70),
                SizedBox(width: 8),
                Text('Save Conversation'),
              ])),
              const PopupMenuItem(value: 'exit', child: Text('Exit Sanctuary')),
              PopupMenuItem(
                value: 'complete',
                enabled: _canCompleteSanctuary,
                child: Text(_canCompleteSanctuary ? 'Complete Sanctuary' : 'Complete Sanctuary (HEAD only)'),
              ),
            ],
          ),
        ],
      ),
      body: Stack(
        children: [
          // Main content
          _inPrivateCoaching 
            ? _buildPrivateCoachingUI()
            : _sanctuaryPaused
              ? _buildSanctuaryPausedOverlay()
              : Column(
                  children: [
                    _buildMembersStrip(),
                    if (_groupCoachingRoundActive) _buildGroupCoachingRoundBanner(),
                    if (_sanctuaryStatus == 'WAITING_FOR_MEMBERS')
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        color: Colors.orange.shade900,
                        child: const Text(
                          'Waiting for family members to join...',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: Colors.white),
                        ),
                      ),
                    Expanded(
                      child: ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.all(16),
                        itemCount: _messages.length,
                        itemBuilder: (context, index) => _buildMessage(_messages[index]),
                      ),
                    ),
                    if (_hasSuggestedResponse) _buildSuggestedResponseUI(),
                    if (_groupCoachingRoundActive && !_hasSuggestedResponse && (_groupCoachingMyState.isEmpty || _groupCoachingMyState.toUpperCase() == 'PENDING'))
                      _buildGroupCoachingSuggestionLoading(),
                    if (!_inPrivateCoaching && _assistedResponse != null && _assistedResponse!.isNotEmpty)
                      _buildAssistedShareBanner(),
                    (_groupCoachingRoundActive && (_groupCoachingMyState.isEmpty || _groupCoachingMyState.toUpperCase() == 'PENDING'))
                        ? _buildGroupCoachingLockedFooter()
                        : _buildInputArea(),
                  ],
                ),
          
          // Coaching offer modal overlay
          if (_showCoachingModal) _buildCoachingOfferModal(),
          if (_showSessionSummary) _buildSessionSummaryOverlay(),
        ],
      ),
    );
  }

  Widget _buildMessage(Map<String, dynamic> msg) {
    final type = (msg['type'] ?? msg['message_type'])?.toString();
    final isFromSelf = msg['sender_id'] == widget.profile['hardware_id'];
    
    if (type == 'SYSTEM') {
      return Center(
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 8),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          decoration: BoxDecoration(
            color: const Color(0xFF2A2A2A),
            borderRadius: BorderRadius.circular(16),
          ),
          child: Text(
            (msg['content'] ?? '').toString(),
            style: const TextStyle(color: Colors.white70, fontSize: 12),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    
    final isLittleNate = msg['sender_id'] == 'LITTLE_NATE';
    final senderName = (msg['sender_name'] ?? msg['sender'] ?? msg['name'] ?? 'Unknown').toString();
    final content = (msg['content'] ?? '').toString();
    
    return Align(
      alignment: isFromSelf ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(12),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.7),
        decoration: BoxDecoration(
          color: isLittleNate
              ? const Color(0xFF003366)
              : isFromSelf
                  ? const Color(0xFF2A2A2A)
                  : const Color(0xFF1E1E1E),
          borderRadius: BorderRadius.circular(12),
          border: isLittleNate ? Border.all(color: const Color(0xFF0055AA), width: 2) : null,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (isLittleNate) const Text('💙 ', style: TextStyle(fontSize: 16)),
                Text(
                  senderName,
                  style: TextStyle(
                    color: isLittleNate ? Colors.cyanAccent : Colors.amber,
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            SelectableText(
              content,
              style: const TextStyle(color: Colors.white, fontSize: 15),
              contextMenuBuilder: (context, editableTextState) {
                return AdaptiveTextSelectionToolbar.buttonItems(
                  anchors: editableTextState.contextMenuAnchors,
                  buttonItems: [
                    ...editableTextState.contextMenuButtonItems,
                    ContextMenuButtonItem(
                      label: 'Push to Nate',
                      onPressed: () {
                        editableTextState.hideToolbar();
                        final sel = editableTextState.textEditingValue.selection;
                        final text = sel.isValid && !sel.isCollapsed
                            ? editableTextState.textEditingValue.text.substring(sel.start, sel.end)
                            : content;
                        _messageController.text = text;
                      },
                    ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSuggestedResponseUI() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1a1a2e),
        border: Border(top: BorderSide(color: Colors.amber.withOpacity(0.3))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              const Icon(Icons.record_voice_over, color: Colors.amber, size: 20),
              const SizedBox(width: 8),
              Text(
                'Say this to $_suggestedTarget:',
                style: const TextStyle(color: Colors.amber, fontWeight: FontWeight.bold),
              ),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.close, color: Colors.grey, size: 18),
                onPressed: _declineSuggestedResponse,
              ),
            ],
          ),
          const SizedBox(height: 4),
          if (_suggestedRationale.isNotEmpty)
            Text(
              _suggestedRationale,
              style: const TextStyle(color: Colors.white38, fontSize: 11, fontStyle: FontStyle.italic),
            ),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.05),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.amber.withOpacity(0.3)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.format_quote, color: Colors.amber.withOpacity(0.5), size: 16),
                    const SizedBox(width: 4),
                    Text(
                      'Your words:',
                      style: TextStyle(color: Colors.amber.withOpacity(0.7), fontSize: 11),
                    ),
                    const Spacer(),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: Colors.blue.withOpacity(0.2),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        _suggestedTone,
                        style: const TextStyle(color: Colors.blue, fontSize: 11),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _suggestedController,
                  style: const TextStyle(color: Colors.white, fontSize: 15),
                  maxLines: 4,
                  decoration: const InputDecoration(
                    border: InputBorder.none,
                    hintText: 'Edit before sending...',
                    hintStyle: TextStyle(color: Colors.white38),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              TextButton(
                onPressed: _declineSuggestedResponse,
                child: const Text('Not right now', style: TextStyle(color: Colors.grey)),
              ),
              const Spacer(),
              ElevatedButton.icon(
                onPressed: _sendSuggestedResponse,
                icon: const Icon(Icons.send, size: 16),
                label: const Text('Send to Family'),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.amber),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildGroupCoachingRoundBanner() {
    final waiting = _groupCoachingWaitingOn.where((s) => s.trim().isNotEmpty).toList();
    final waitingText = waiting.isEmpty ? 'Waiting on family responses...' : 'Waiting on: ${waiting.join(', ')}';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF1A1A1A),
        border: Border(
          bottom: BorderSide(color: Colors.amber.shade700.withOpacity(0.4), width: 1),
        ),
      ),
      child: Row(
        children: [
          const Icon(Icons.groups, color: Colors.amber, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Group Coaching in progress. $waitingText',
              style: const TextStyle(color: Colors.white70, fontSize: 13),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGroupCoachingLockedFooter() {
    final my = _groupCoachingMyState.toUpperCase();
    final subtitle = (my == 'PENDING' || my.isEmpty)
        ? 'Please use your suggested words (or decline) before chat continues.'
        : 'Thanks. Chat will resume after everyone responds.';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      color: const Color(0xFF0F0F0F),
      child: Text(
        subtitle,
        style: const TextStyle(color: Colors.white60, fontSize: 13),
        textAlign: TextAlign.center,
      ),
    );
  }

  Widget _buildGroupCoachingSuggestionLoading() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        border: Border(
          top: BorderSide(color: Colors.amber.shade700.withOpacity(0.25), width: 1),
        ),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 10),
          const Expanded(
            child: Text(
              'Preparing your private coaching suggestion...',
              style: TextStyle(color: Colors.white60, fontSize: 13),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          TextButton(
            onPressed: _syncSanctuaryState,
            child: const Text('Refresh'),
          ),
        ],
      ),
    );
  }

  bool _sanctuaryCanUseVault() {
    if (!AppConfig.ENABLE_SOVEREIGN_VAULT) return false;
    final tier = (widget.profile['tier'] ?? '').toString().toUpperCase();
    final plan = (widget.profile['subscription_plan'] ?? '').toString().toUpperCase();
    const vaultTiers = {'STANDARD', 'INNER_CHAMBER', 'TOP_TIER', 'SOVEREIGN_CIRCLE'};
    return vaultTiers.contains(tier) || vaultTiers.contains(plan);
  }

  Widget _buildAssistedShareBanner() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.amber.shade900.withOpacity(0.2),
        border: Border(top: BorderSide(color: Colors.amber.shade700, width: 1)),
      ),
      child: Row(
        children: [
          const Icon(Icons.auto_awesome, color: Colors.amber, size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Little Nate prepared a response for you',
              style: TextStyle(color: Colors.amber.shade200, fontSize: 13),
            ),
          ),
          const SizedBox(width: 8),
          ElevatedButton.icon(
            onPressed: _postAssistedResponse,
            icon: const Icon(Icons.send, size: 16),
            label: const Text('Share to Family'),
            style: ElevatedButton.styleFrom(
              backgroundColor: Colors.amber.shade700,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              textStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
            ),
          ),
          const SizedBox(width: 4),
          IconButton(
            onPressed: () {
              setState(() { _assistedResponse = null; });
            },
            icon: const Icon(Icons.close, size: 18, color: Colors.white54),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(),
          ),
        ],
      ),
    );
  }

  Widget _buildInputArea() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (_sanctuaryUploadState.isVisible)
          UploadProgressIndicator(
            state: _sanctuaryUploadState,
            onCancel: () => setState(() => _sanctuaryUploadState = UploadProgressState.idle()),
            onDismiss: () => setState(() => _sanctuaryUploadState = UploadProgressState.idle()),
          ),
        Container(
          padding: const EdgeInsets.all(16),
          decoration: const BoxDecoration(
            color: Color(0xFF1E1E1E),
            boxShadow: [
              BoxShadow(
                color: Colors.black26,
                blurRadius: 8,
                offset: Offset(0, -2),
              ),
            ],
          ),
          child: Row(
            children: [
              IconButton(
                icon: Icon(
                  _isListening ? Icons.mic : Icons.mic_none,
                  color: _isListening ? Colors.red : (_speechAvailable ? Colors.white : Colors.grey),
                ),
                onPressed: _speechAvailable ? _toggleListening : null,
                tooltip: _speechAvailable ? 'Speak your message' : 'Speech not available',
              ),
              if (_sanctuaryCanUseVault()) ...[
                const SizedBox(width: 4),
                VaultAttachmentButton(
                  profile: widget.profile,
                  socket: _channel,
                  onVaultItemSelected: (itemId) {
                    if (itemId != null && itemId.isNotEmpty) {
                      _messageController.text = '${_messageController.text}[Vault:$itemId] '.trim();
                    }
                  },
                  onUploadProgress: (s) => setState(() => _sanctuaryUploadState = s),
                ),
              ],
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: _messageController,
                  style: const TextStyle(color: Colors.white),
                  minLines: 1,
                  maxLines: 5,
                  keyboardType: TextInputType.multiline,
                  textInputAction: TextInputAction.newline,
                  scrollPhysics: const BouncingScrollPhysics(),
                  decoration: InputDecoration(
                    hintText: _isListening ? 'Listening...' : 'Type your message...',
                    hintStyle: TextStyle(
                      color: _isListening ? Colors.redAccent : Colors.white38,
                    ),
                    border: const OutlineInputBorder(),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.send, color: Color(0xFF003366)),
                onPressed: _sendMessage,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// -----------------------------------------------------------------------------
// END OF PART 3
// -----------------------------------------------------------------------------
// =============================================================================
// MODULE 3: THE LOBBY (SELF-HEALING v4.0)
// Status: UPGRADED (Visual Connection Status + Retry Logic)
// =============================================================================

class LobbyScreen extends StatefulWidget {
  final bool registrationSuccess;
  const LobbyScreen({super.key, this.registrationSuccess = false});

  @override
  _LobbyScreenState createState() => _LobbyScreenState();
}

class _LobbyScreenState extends State<LobbyScreen> with TickerProviderStateMixin {
  final HardwareIdentity _identity = HardwareIdentity();
  WebSocketChannel? _channel;
  StreamSubscription? _lobbySub;
  StreamSubscription? _lobbyErrSub; // FIX-G' broadcast errors from hub
  StreamSubscription? _lobbyDoneSub; // FIX-G' broadcast done from hub
  
  // Connection State
  bool _isConnected = false;
  String _statusMessage = "Initializing...";
  bool _isLoading = false;

  // Credentials for Handoff
  String _tempUser = "";
  String _tempPass = "";
  String _lastExpectedRole = "CLIENT";

  // Admin gate-check: true when we are verifying admin credentials before redirect
  bool _adminGateCheck = false;

  // Biometric auto-login state
  bool _hasBiometricCreds = false;

  // Login dialog state (shared with StatefulBuilder)
  void Function(void Function())? _dialogSetState;
  String _dialogError = '';
  int _dialogRemainingAttempts = 5;
  int _dialogCooldownSeconds = 0;
  bool _dialogVerifying = false;
  int _loginAttemptCounter = 0;
  AnimationController? _shakeController;
  bool _biometricAvailable = false;
  String? _savedUsername;

  // Biometric opt-in prompt state (shown after successful manual login)
  bool _showBiometricOptIn = false;
  String _pendingBioUser = "";
  String _pendingBioPass = "";
  String _pendingBioRole = "";
  
  // Resolve dynamically so `/#/?ws=...` overrides apply without rebuilding.
  String get _serverUrl => defaultWsUrl;

  String? _pendingWidgetAction;

  @override
  void initState() {
    super.initState();
    _connectToBridge();
    _checkBiometricLogin();
    _checkWidgetLaunch();
    if (widget.registrationSuccess) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Payment received! Sign in with the username you created.'),
          backgroundColor: Color(0xFF22C55E),
          duration: Duration(seconds: 8),
        ));
      });
    }
  }

  Future<void> _checkWidgetLaunch() async {
    if (kIsWeb) return;
    try {
      final uri = await HomeWidget.initiallyLaunchedFromHomeWidget();
      if (uri != null) _pendingWidgetAction = uri.queryParameters['action'];
    } catch (_) {}
  }

  /// Check if saved biometric credentials exist for quick login.
  Future<void> _checkBiometricLogin() async {
    final hasCreds = await _identity.hasSavedCredentials();
    final bioAvail = await _identity.isBiometricAvailable();
    final savedUser = await _identity.getSavedUsername();
    if (mounted) {
      setState(() {
        _hasBiometricCreds = hasCreds;
        _biometricAvailable = bioAvail;
        _savedUsername = savedUser;
      });
    }
  }

  @override
  void dispose() {
    _lobbySub?.cancel();
    _lobbyErrSub?.cancel(); // FIX-G'
    _lobbyDoneSub?.cancel(); // FIX-G'
    _channel?.sink.close();
    super.dispose();
  }

  int _reconnectAttempts = 0;
  static const _maxReconnectAttempts = 5;

  void _connectToBridge() {
    setState(() {
      _statusMessage = "Connecting to $_serverUrl...";
      _isConnected = false;
    });

    try {
      _lobbySub?.cancel();
      _lobbyErrSub?.cancel(); // FIX-G'
      _lobbyDoneSub?.cancel(); // FIX-G'
      _channel?.sink.close();
      _channel = WebSocketChannel.connect(Uri.parse(_serverUrl));

      // FIX-G' (HUB-OWNS-RAW-STREAM): hub is sole owner of `_channel.stream`.
      // Lobby consumes via broadcast inbound/errors/done — safe to subscribe
      // alongside Schedule, Neural, etc.
      _ClientWsHub.attach(_channel!);
      _lobbySub = _ClientWsHub.inbound.listen(_handlePacket);
      _lobbyErrSub = _ClientWsHub.errors.listen((e) {
        debugLog("Lobby Socket Error: $e");
        if (mounted) {
          setState(() {
            _isConnected = false;
            _statusMessage = "Connection Failed.\n$_serverUrl";
          });
          _scheduleReconnect();
        }
      });
      _lobbyDoneSub = _ClientWsHub.done.listen((_) {
        debugLog("Lobby Socket Closed");
        if (mounted) {
          setState(() {
            _isConnected = false;
            _statusMessage = "Disconnected.\n$_serverUrl";
          });
          _scheduleReconnect();
        }
      });

      // Allow login attempts immediately — onError/onDone will flip state back.
      // Some browser/websocket timing edge-cases can miss the server's "connected" greeting.
      if (mounted) {
        setState(() {
          _isConnected = true;
          _reconnectAttempts = 0;
          _statusMessage = "Awaiting handshake...\n$_serverUrl";
        });
      }

    } catch (e) {
      if (mounted) setState(() => _statusMessage = "Fatal Connection Error: $e");
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_reconnectAttempts >= _maxReconnectAttempts) {
      if (mounted) {
        setState(() => _statusMessage = "Unable to reach server. Pull down to retry.");
      }
      return;
    }
    _reconnectAttempts++;
    final delay = Duration(milliseconds: 500 * (1 << (_reconnectAttempts - 1)).clamp(1, 16));
    debugLog("Reconnect attempt $_reconnectAttempts in ${delay.inMilliseconds}ms");
    Future.delayed(delay, () {
      if (mounted && !_isConnected) _connectToBridge();
    });
  }

  /// Biometric auto-login: prompt Face ID / Fingerprint, then send stored
  /// credentials over WebSocket automatically.
  Future<void> _attemptBiometricLogin() async {
    if (!_isConnected) {
      _connectToBridge();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Reconnecting — please try again in a moment.")),
        );
      }
      return;
    }

    setState(() => _isLoading = true);

    final creds = await _identity.recoverCredentials();
    if (creds == null) {
      if (mounted) {
        setState(() => _isLoading = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Biometric authentication cancelled or failed."),
            backgroundColor: Color(0xFFEF4444),
          ),
        );
      }
      return;
    }

    _tempUser = creds['username']!;
    _tempPass = creds['password']!;
    final role = creds['role']!;
    _lastExpectedRole = role;

    _channel?.sink.add(jsonEncode({
      "type": "login_request",
      "username": _tempUser,
      "password": _tempPass,
      "expected_role": role,
      "client_context": kIsWeb ? 'client_web' : 'client_mobile',
    }));

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Authenticating...")),
      );
    }
  }

  /// Clear biometric login and show manual login.
  void _switchAccount() {
    _identity.clearCredentials();
    setState(() {
      _hasBiometricCreds = false;
      _savedUsername = null;
    });
  }

  void _showForcePasswordResetDialog(String token, String username) {
    final newPassCtrl = TextEditingController();
    final confirmPassCtrl = TextEditingController();
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Create New Password", style: TextStyle(color: Color(0xFFC9A962))),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              "You must set a new password before continuing.",
              style: TextStyle(color: Colors.white70, fontSize: 14),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: newPassCtrl,
              obscureText: true,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: "New Password",
                labelStyle: TextStyle(color: Colors.white54),
                enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Colors.white24)),
                focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFFC9A962))),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: confirmPassCtrl,
              obscureText: true,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: "Confirm Password",
                labelStyle: TextStyle(color: Colors.white54),
                enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Colors.white24)),
                focusedBorder: UnderlineInputBorder(borderSide: BorderSide(color: Color(0xFFC9A962))),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              final np = newPassCtrl.text.trim();
              final cp = confirmPassCtrl.text.trim();
              if (np.length < 6) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text("Password must be at least 6 characters"), backgroundColor: Colors.red),
                );
                return;
              }
              if (np != cp) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text("Passwords do not match"), backgroundColor: Colors.red),
                );
                return;
              }
              _channel?.sink.add(jsonEncode({
                "type": "force_password_change",
                "token": token,
                "username": username,
                "new_password": np,
              }));
              _tempPass = np;
              Navigator.pop(ctx);
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text("Updating password..."), backgroundColor: Color(0xFFC9A962)),
              );
            },
            child: const Text("Set Password", style: TextStyle(color: Color(0xFFC9A962))),
          ),
        ],
      ),
    );
  }

  /// Show biometric opt-in dialog after successful manual login.
  Future<void> _showBiometricOptInDialog() async {
    if (!mounted) return;
    final isWeb = kIsWeb;
    final result = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(
              isWeb ? Icons.lock_open : Icons.fingerprint,
              color: const Color(0xFFC9A962),
              size: 28,
            ),
            const SizedBox(width: 12),
            const Expanded(
              child: Text(
                "Enable Quick Login?",
                style: TextStyle(color: Color(0xFFE8D5A3), fontSize: 18, fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
        content: Text(
          isWeb
              ? "Save your credentials for one-tap login next time. Your password is stored securely in your browser."
              : "Enable Face ID or Fingerprint to log in instantly next time. Your credentials are encrypted on-device.",
          style: const TextStyle(color: Color(0xFFAAAAAA), fontSize: 14, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text("Not Now", style: TextStyle(color: Color(0xFF888888))),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFC9A962),
              foregroundColor: Colors.black,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(isWeb ? "Enable Quick Login" : "Enable Biometric Login"),
          ),
        ],
      ),
    );

    if (result == true) {
      await _identity.saveCredentials(_pendingBioUser, _pendingBioPass, _pendingBioRole);
      await _identity.setBiometricDeclined(false);
    } else {
      await _identity.setBiometricDeclined(true);
    }
    _pendingBioUser = "";
    _pendingBioPass = "";
    _pendingBioRole = "";
  }

  Future<void> _checkBiometricOptIn(String role) async {
    try {
      final alreadyEnabled = await _identity.isBiometricEnabled();
      final hasDeclined = await _identity.hasBiometricDeclined();
      if (alreadyEnabled) {
        _identity.saveCredentials(_tempUser, _tempPass, role);
      } else if (!hasDeclined) {
        _pendingBioUser = _tempUser;
        _pendingBioPass = _tempPass;
        _pendingBioRole = role;
        _showBiometricOptIn = true;
      }
    } catch (e) {
      debugLog("!!! [BIO] opt-in check error: $e");
    }
  }

  void _handlePacket(dynamic message) {
    // If we receive ANYTHING, we are definitely connected
    if (!_isConnected) setState(() => _isConnected = true);

    try {
      final data = jsonDecode(message);
      debugLog("Lobby Received: $data");

      if (data['type'] == 'login_success') {
        setState(() => _isLoading = false);
        if (_dialogSetState != null) {
          _dialogSetState = null;
          try { Navigator.of(context).pop(); } catch (_) {}
        }
        
        Map<String, dynamic> profile = data['profile'];
        String role = profile['role'] ?? "CLIENT";
        String token = data['token'] ?? "";

        // Persist session token so sub-screens (Coherence Dashboard, etc.) can authenticate
        if (token.isNotEmpty) {
          HardwareIdentity().saveSession(
            _tempUser,
            token,
            profile,
          );
          NateWidgetService.fetchAndUpdate(token);
        }

        // ---------------------------------------------------------------
        // ADMIN GATE-CHECK: If we were verifying admin credentials at the
        // gateway (app.*), redirect the browser to command.* instead of
        // navigating to the admin dashboard within Flutter.
        // ---------------------------------------------------------------
        if (_adminGateCheck) {
          _adminGateCheck = false;
          if (kIsWeb) {
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                content: Text("Admin verified. Redirecting to Sovereign Command..."),
                backgroundColor: Color(0xFFC9A962),
              ));
            }
            Future.delayed(const Duration(milliseconds: 300), () {
              launchUrl(
                Uri.parse('https://command.sovereignsanctuary.net'),
                webOnlyWindowName: '_self',
              );
            });
          }
          return;
        }

        // ---------------------------------------------------------------
        // BIOMETRIC: Offer opt-in for Face ID / Fingerprint re-login
        // Only for CLIENT and COACH roles (never ADMIN).
        // Only ask if not already enabled AND not previously declined.
        // ---------------------------------------------------------------
        if (role == 'CLIENT' || role == 'COACH') {
          _checkBiometricOptIn(role);
        }
        
        // Close the Lobby socket - next screen will create its own authenticated connection.
        // Cancel subscription FIRST to prevent Uncaught Error from onDone firing after navigation.
        _lobbySub?.cancel();
        _lobbySub = null;
        _lobbyErrSub?.cancel(); _lobbyErrSub = null; // FIX-G'
        _lobbyDoneSub?.cancel(); _lobbyDoneSub = null; // FIX-G'
        // Don't close inside the stream callback — let dispose() handle it.
        // On Flutter web, closing inside the callback causes an unhandled async error
        // that can block Navigator.pushReplacement from completing.

        // Defer navigation to next frame so it runs OUTSIDE the stream callback,
        // avoiding the Flutter web "Uncaught Error" from MutationObserver conflicts.
        final user = _tempUser;
        final pass = _tempPass;
        final consentNeeded = data['consent_update_needed'] == true;
        final coachEthicsNeeded = data['coach_ethics_needed'] == true && role == 'COACH';
        
        WidgetsBinding.instance.addPostFrameCallback((_) async {
          if (!mounted) return;

          // Show biometric opt-in dialog before navigating
          if (_showBiometricOptIn) {
            _showBiometricOptIn = false;
            await _showBiometricOptInDialog();
          }

          if (!mounted) return;

          if (consentNeeded) {
            Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => ReConsentScreen(
              username: user,
              password: pass,
              profile: profile,
              token: token,
            )));
            return;
          }

          if (coachEthicsNeeded) {
            Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => CoachEthicsScreen(
              username: user,
              password: pass,
              profile: profile,
              token: token,
            )));
            return;
          }

          // C1: Trial welcome walkthrough (Threshold users)
          final subPlan = (profile['subscription_plan'] ?? profile['tier'] ?? '').toString().toUpperCase();
          final hasSeenOnboarding = profile['has_seen_onboarding'] == true;
          final hasSeenPaidOnboarding = profile['has_seen_paid_onboarding'] == true;
          final isTrial = subPlan.contains('TRIAL') || subPlan.isEmpty ||
              (!subPlan.contains('STANDARD') && !subPlan.contains('INNER') &&
               !subPlan.contains('TOP') && !subPlan.contains('SOVEREIGN'));
          final isPaid = subPlan.contains('STANDARD') || subPlan.contains('INNER_CHAMBER') ||
              subPlan.contains('TOP_TIER') || subPlan.contains('SOVEREIGN_CIRCLE');

          if (role == 'CLIENT' && isTrial && !hasSeenOnboarding) {
            final profileWithToken = {...profile, "token": token};
            Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => OnboardingThresholdScreen(
              profileWithToken: profileWithToken,
              username: user,
              password: pass,
            )));
            return;
          }

          // C2: Inner Chamber / Sovereign Circle welcome walkthrough (paid users)
          if (role == 'CLIENT' && isPaid && !hasSeenPaidOnboarding) {
            final profileWithToken = {...profile, "token": token};
            final tier = subPlan.contains('TOP') || subPlan.contains('SOVEREIGN') ? 'TOP_TIER' : 'STANDARD';
            final isFoundingMember = profile['is_founding_member'] == true;
            Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => OnboardingPaidScreen(
              profileWithToken: profileWithToken,
              username: user,
              password: pass,
              tier: tier,
              isFoundingMember: isFoundingMember,
            )));
            return;
          }

          // Check if onboarding tutorial needs to be shown (mandatory for first-time users)
          final onboardingDone = profile['onboarding_completed'] == true;

          if (!onboardingDone && role != 'ADMIN') {
            // Route to onboarding tutorial first
            Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => OnboardingTutorialScreen(
              role: role,
              userData: {...profile, "token": token, "username": user, "password": pass},
            )));
          } else {
            // Include token in profile so Settings/Invite Family Member auth works
            final profileWithToken = {...profile, "token": token};
            // Navigate - each screen handles its own WebSocket auth via username/password
            Widget nextScreen;
            if (role == 'ADMIN') {
              nextScreen = AdminDashboardScreen(currentUserProfile: profileWithToken, username: user, password: pass);
            } else if (role == 'COACH') {
              nextScreen = CoachDashboardScreenV2(currentUserProfile: profileWithToken, username: user, password: pass);
            } else {
              // FIX-G' (HUB-OWNS-RAW-STREAM): hub already attached at connect
              // (line ~6326). Just clear lobby's reference so dispose() can't
              // re-close the channel that Schedule/NeuralInterface still need.
              _channel = null;
              // Check if COACH_ONLY client
              final subPlan = (profile['subscription_plan'] ?? '').toString().toUpperCase();
              final canAccessNate = profile['can_access_nate'] ?? true;
              if (subPlan == 'COACH_ONLY' || canAccessNate == false) {
                nextScreen = ClientScheduleScreen(currentUserProfile: profileWithToken, username: user, password: pass);
              } else {
                // AI consent gate — required before chat access
                final hasConsent = profileWithToken['ai_consent_granted_at'] != null;
                bool localConsent = false;
                if (!hasConsent) {
                  try {
                    final prefs = await SharedPreferences.getInstance();
                    localConsent = prefs.getString('ai_consent_granted_at') != null;
                  } catch (_) {}
                }
                if (!hasConsent && !localConsent) {
                  nextScreen = AiConsentScreen(
                    profile: profileWithToken,
                    username: user,
                    password: pass,
                    buildNextScreen: () => NeuralInterfaceV2(
                      currentUserProfile: profileWithToken,
                      username: user,
                      password: pass,
                    ),
                  );
                } else {
                  nextScreen = NeuralInterfaceV2(currentUserProfile: profileWithToken, username: user, password: pass);
                }
              }
            }

            Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => nextScreen));
            if (_pendingWidgetAction == 'open_checkin' && role == 'CLIENT') {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (!mounted) return;
                Navigator.push(context, MaterialPageRoute(builder: (_) => CheckinScreen(profile: profileWithToken)));
              });
            }
          }
        });
        
      } else if (data['type'] == 'force_password_reset') {
        setState(() => _isLoading = false);
        final resetToken = data['token'] ?? '';
        final resetUser = data['username'] ?? _tempUser;
        _showForcePasswordResetDialog(resetToken, resetUser);

      } else if (data['type'] == 'security_disconnect') {
        _lobbySub?.cancel();
        _lobbySub = null;
        _lobbyErrSub?.cancel(); _lobbyErrSub = null; // FIX-G'
        _lobbyDoneSub?.cancel(); _lobbyDoneSub = null; // FIX-G'
        if (mounted) {
          setState(() => _isLoading = false);
          showDialog(
            context: context,
            barrierDismissible: false,
            builder: (_) => AlertDialog(
              backgroundColor: const Color(0xFF111111),
              title: const Row(children: [
                Icon(Icons.security, color: Color(0xFFEF4444)),
                SizedBox(width: 8),
                Text('Security Alert', style: TextStyle(color: Color(0xFFEF4444))),
              ]),
              content: Text(
                data['reason'] ?? 'Your session was terminated due to suspicious activity.',
                style: const TextStyle(color: Colors.white70),
              ),
              actions: [
                TextButton(
                  onPressed: () { Navigator.pop(context); _connectToBridge(); },
                  child: const Text('Log In Again', style: TextStyle(color: Color(0xFFC9A962))),
                ),
              ],
            ),
          );
        }
      } else if (data['type'] == 'login_failed') {
        if (mounted) {
          final errorCode = data['error_code'] ?? '';
          final msg = data['message'] ?? 'Login failed';
          final remaining = data['remaining_attempts'] as int? ?? 5;
          final cooldown = data['cooldown_seconds'] as int? ?? 0;
          setState(() => _isLoading = false);

          if (_dialogSetState != null) {
            _dialogError = msg;
            _dialogRemainingAttempts = remaining;
            _dialogCooldownSeconds = cooldown;
            _dialogVerifying = false;
            try { _dialogSetState!(() {}); } catch (_) {}
            _shakeController?.forward(from: 0.0);
            if (cooldown > 0) {
              _startDialogCooldownTimer();
            }
          } else {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(msg),
              backgroundColor: errorCode == 'WRONG_PORTAL'
                  ? const Color(0xFFC9A962)
                  : Colors.red,
              duration: Duration(seconds: errorCode == 'WRONG_PORTAL' ? 6 : 4),
            ));
          }
        }
      } else if (data['type'] == 'forgot_password_sent') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("If that email exists, a reset link was sent."),
            backgroundColor: Color(0xFF22d3ee),
          ));
        }
      } else if (data['type'] == 'forgot_username_sent') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("If that email is registered, your username was sent."),
            backgroundColor: Color(0xFF22d3ee),
          ));
        }
      } else if (data['type'] == 'password_reset_success') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Password updated. Logging you in..."),
            backgroundColor: Colors.green,
          ));
          if (_tempUser.isNotEmpty && _tempPass.isNotEmpty) {
            setState(() => _isLoading = true);
            _channel?.sink.add(jsonEncode({
              "type": "login_request",
              "username": _tempUser,
              "password": _tempPass,
              "expected_role": _lastExpectedRole,
              "client_context": kIsWeb ? 'client_web' : 'client_mobile',
            }));
          }
        }
      } else if (data['type'] == 'forgot_password_phone_sent') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("If that phone is on file, a code was sent via SMS."),
            backgroundColor: Color(0xFF4ECDC4),
          ));
        }
      } else if (data['type'] == 'password_reset_phone_success') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Password updated. Please log in."),
            backgroundColor: Colors.green,
          ));
        }
      }
    } catch (e) {
      debugLog("Parse Error: $e");
    }
  }

  /// Admin gate-check: verifies ADMIN credentials at the gateway before
  /// redirecting to command.sovereignsanctuary.net. On success, _handlePacket
  /// sees _adminGateCheck==true and opens the command portal URL.
  void _showAdminGateDialog() {
    if (!_isConnected) {
      _connectToBridge();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Reconnecting...")));
    }

    TextEditingController userCtrl = TextEditingController();
    TextEditingController passCtrl = TextEditingController();
    bool obscurePass = true;

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: const Text("ADMIN VERIFICATION", style: TextStyle(color: Color(0xFFFF006E), fontFamily: 'Courier')),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                "Verify your admin credentials to access Sovereign Command.",
                style: TextStyle(color: Colors.white70, fontSize: 12),
              ),
              const SizedBox(height: 16),
              TextField(controller: userCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "IDENTITY", prefixIcon: Icon(Icons.fingerprint))),
              const SizedBox(height: 10),
              TextField(
                controller: passCtrl,
                obscureText: obscurePass,
                style: const TextStyle(color: Colors.white),
                decoration: InputDecoration(
                  labelText: "KEY",
                  prefixIcon: const Icon(Icons.vpn_key),
                  suffixIcon: IconButton(
                    icon: Icon(obscurePass ? Icons.visibility_off : Icons.visibility, color: Colors.grey),
                    onPressed: () => setDialogState(() => obscurePass = !obscurePass),
                  ),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(child: const Text("ABORT"), onPressed: () => Navigator.pop(ctx)),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFF006E), foregroundColor: Colors.white),
              child: const Text("VERIFY & ENTER"),
              onPressed: () {
                _tempUser = userCtrl.text.trim();
                _tempPass = passCtrl.text.trim();
                _adminGateCheck = true;

                _channel?.sink.add(jsonEncode({
                  "type": "login_request",
                  "username": _tempUser,
                  "password": _tempPass,
                  "expected_role": "ADMIN",
                  "client_context": kIsWeb ? 'admin_web' : 'admin_mobile',
                }));

                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Verifying admin credentials...")));
              },
            ),
          ],
        ),
      ),
    );
  }

  void _startDialogCooldownTimer() {
    Future.doWhile(() async {
      await Future.delayed(const Duration(seconds: 1));
      if (!mounted || _dialogCooldownSeconds <= 0) return false;
      _dialogCooldownSeconds--;
      try { _dialogSetState?.call(() {}); } catch (_) {}
      return _dialogCooldownSeconds > 0;
    });
  }

  void _showLoginDialog(String expectedRole) {
    if (!_isConnected) {
      _connectToBridge();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Reconnecting...")));
    }

    TextEditingController userCtrl = TextEditingController();
    TextEditingController passCtrl = TextEditingController();
    bool obscurePass = true;
    _dialogError = '';
    _dialogRemainingAttempts = 5;
    _dialogCooldownSeconds = 0;
    _dialogVerifying = false;
    _shakeController?.dispose();
    _shakeController = AnimationController(vsync: this, duration: const Duration(milliseconds: 500));

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) {
          _dialogSetState = setDialogState;
          final bool locked = _dialogCooldownSeconds > 0;
          final int mins = _dialogCooldownSeconds ~/ 60;
          final int secs = _dialogCooldownSeconds % 60;
          return AlertDialog(
            backgroundColor: const Color(0xFF111111),
            title: Text("$expectedRole ACCESS", style: const TextStyle(color: Color(0xFFFFD700), fontFamily: 'Courier')),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(controller: userCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "IDENTITY", prefixIcon: Icon(Icons.fingerprint))),
                const SizedBox(height: 10),
                ValueListenableBuilder<double>(
                  valueListenable: _shakeController!,
                  builder: (context, value, _) {
                    final double offset = value == 0 ? 0 : sin(value * pi * 4) * 10;
                    return Transform.translate(
                      offset: Offset(offset, 0),
                      child: TextField(
                        controller: passCtrl,
                        obscureText: obscurePass,
                        style: const TextStyle(color: Colors.white),
                        decoration: InputDecoration(
                          labelText: "KEY",
                          prefixIcon: const Icon(Icons.vpn_key),
                          suffixIcon: IconButton(
                            icon: Icon(obscurePass ? Icons.visibility_off : Icons.visibility, color: Colors.grey),
                            onPressed: () => setDialogState(() => obscurePass = !obscurePass),
                          ),
                          errorText: _dialogError.isNotEmpty ? _dialogError : null,
                          errorStyle: const TextStyle(color: Color(0xFFEF4444), fontSize: 11),
                        ),
                      ),
                    );
                  },
                ),
                if (locked)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      "Try again in $mins:${secs.toString().padLeft(2, '0')}",
                      style: const TextStyle(color: Color(0xFFEF4444), fontSize: 12),
                    ),
                  ),
                if (!locked && _dialogRemainingAttempts < 3 && _dialogRemainingAttempts > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      "$_dialogRemainingAttempts attempt${_dialogRemainingAttempts == 1 ? '' : 's'} remaining",
                      style: const TextStyle(color: Color(0xFFC9A962), fontSize: 11),
                    ),
                  ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(
                      onPressed: () { _dialogSetState = null; Navigator.pop(ctx); _showForgotUsernameDialog(); },
                      child: const Text("Forgot username?", style: TextStyle(color: Colors.grey, fontSize: 12)),
                    ),
                    TextButton(
                      onPressed: () { _dialogSetState = null; Navigator.pop(ctx); _showForgotPasswordMethodDialog(); },
                      child: const Text("Forgot password?", style: TextStyle(color: Colors.grey, fontSize: 12)),
                    ),
                  ],
                ),
              ],
            ),
            actions: [
              TextButton(child: const Text("ABORT"), onPressed: () { _dialogSetState = null; Navigator.pop(ctx); }),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: locked || _dialogVerifying ? Colors.grey : const Color(0xFFFFD700),
                  foregroundColor: Colors.black,
                ),
                onPressed: locked || _dialogVerifying ? null : () {
                  _tempUser = userCtrl.text.trim();
                  _tempPass = passCtrl.text.trim();
                  if (_tempUser.isEmpty || _tempPass.isEmpty) return;
                  _lastExpectedRole = expectedRole;
                  _dialogVerifying = true;
                  _dialogError = '';
                  setDialogState(() {});
                  _loginAttemptCounter += 1;
                  _channel?.sink.add(jsonEncode({
                    "type": "login_request",
                    "username": _tempUser,
                    "password": _tempPass,
                    "expected_role": expectedRole,
                    "client_context": kIsWeb ? '${expectedRole.toLowerCase()}_web' : '${expectedRole.toLowerCase()}_mobile',
                    "client_telemetry": {
                      "attempt_number": _loginAttemptCounter,
                      "username_length": _tempUser.length,
                      "password_length": _tempPass.length,
                      "username_has_at": _tempUser.contains('@'),
                      "username_leading_trailing_space": userCtrl.text != userCtrl.text.trim(),
                      "client_timestamp": DateTime.now().toIso8601String(),
                      "surface": "landing_login_dialog",
                    },
                  }));
                },
                child: _dialogVerifying
                    ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                    : const Text("VERIFY"),
              )
            ],
          );
        },
      ),
    ).then((_) => _dialogSetState = null);
  }

  void _showForgotPasswordMethodDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Reset Password", style: TextStyle(color: Color(0xFFFFD700), fontFamily: 'Courier')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Choose how to reset your password:", style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 20),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFFFFD700),
                  foregroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                icon: const Icon(Icons.email),
                label: const Text("Reset via Email"),
                onPressed: () {
                  Navigator.pop(ctx);
                  _showForgotPasswordDialog();
                },
              ),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF4ECDC4),
                  foregroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                icon: const Icon(Icons.phone_android),
                label: const Text("Reset via Phone (SMS)"),
                onPressed: () {
                  Navigator.pop(ctx);
                  _showForgotPasswordPhoneDialog();
                },
              ),
            ),
            const SizedBox(height: 16),
            TextButton(
              onPressed: () {
                Navigator.pop(ctx);
                Navigator.push(context, MaterialPageRoute(builder: (_) => const ResetPasswordScreen()));
              },
              child: const Text("I already have a reset code", style: TextStyle(color: Colors.grey, fontSize: 12)),
            ),
          ],
        ),
        actions: [
          TextButton(child: const Text("Cancel"), onPressed: () => Navigator.pop(ctx)),
        ],
      ),
    );
  }

  void _showForgotPasswordDialog() {
    TextEditingController ctrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Reset via Email", style: TextStyle(color: Color(0xFFFFD700), fontFamily: 'Courier')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Enter your email or username. If an account exists, a reset link will be sent.", style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 16),
            TextField(
              controller: ctrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: "Email or username",
                prefixIcon: Icon(Icons.email, color: Colors.grey),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(child: const Text("Cancel"), onPressed: () => Navigator.pop(ctx)),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFFD700), foregroundColor: Colors.black),
            child: const Text("Send Reset Link"),
            onPressed: () {
              final val = ctrl.text.trim();
              if (val.isEmpty) return;
              if (val.contains("@")) {
                _channel?.sink.add(jsonEncode({"type": "forgot_password_request", "email": val}));
              } else {
                _channel?.sink.add(jsonEncode({"type": "forgot_password_request", "username": val}));
              }
              Navigator.pop(ctx);
            },
          ),
        ],
      ),
    );
  }

  void _showForgotPasswordPhoneDialog() {
    TextEditingController phoneCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Reset via Phone", style: TextStyle(color: Color(0xFF4ECDC4), fontFamily: 'Courier')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Enter the phone number associated with your account. A 6-digit code will be sent via SMS.", style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 16),
            TextField(
              controller: phoneCtrl,
              keyboardType: TextInputType.phone,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: "Phone number",
                hintText: "+1 (555) 123-4567",
                hintStyle: TextStyle(color: Colors.grey),
                prefixIcon: Icon(Icons.phone, color: Colors.grey),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(child: const Text("Cancel"), onPressed: () => Navigator.pop(ctx)),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4ECDC4), foregroundColor: Colors.black),
            child: const Text("Send Code"),
            onPressed: () {
              final phone = phoneCtrl.text.trim();
              if (phone.isEmpty) return;
              _channel?.sink.add(jsonEncode({"type": "forgot_password_phone_request", "phone": phone}));
              Navigator.pop(ctx);
              _showForgotPasswordPhoneCodeDialog(phone);
            },
          ),
        ],
      ),
    );
  }

  void _showForgotPasswordPhoneCodeDialog(String phone) {
    TextEditingController codeCtrl = TextEditingController();
    TextEditingController passCtrl = TextEditingController();
    TextEditingController confirmCtrl = TextEditingController();
    bool obscurePass = true;
    bool obscureConfirm = true;
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Enter Code", style: TextStyle(color: Color(0xFF4ECDC4), fontFamily: 'Courier')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text("A code was sent to $phone", style: const TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 16),
            TextField(
              controller: codeCtrl,
              keyboardType: TextInputType.number,
              maxLength: 6,
              style: const TextStyle(color: Colors.white, fontSize: 24, letterSpacing: 8),
              textAlign: TextAlign.center,
              decoration: const InputDecoration(
                labelText: "6-digit code",
                counterText: "",
                prefixIcon: Icon(Icons.lock_clock, color: Colors.grey),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: passCtrl,
              obscureText: obscurePass,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: "New password",
                prefixIcon: const Icon(Icons.vpn_key, color: Colors.grey),
                suffixIcon: IconButton(
                  icon: Icon(obscurePass ? Icons.visibility_off : Icons.visibility, color: Colors.grey),
                  onPressed: () => setDialogState(() => obscurePass = !obscurePass),
                ),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: confirmCtrl,
              obscureText: obscureConfirm,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: "Confirm password",
                prefixIcon: const Icon(Icons.vpn_key, color: Colors.grey),
                suffixIcon: IconButton(
                  icon: Icon(obscureConfirm ? Icons.visibility_off : Icons.visibility, color: Colors.grey),
                  onPressed: () => setDialogState(() => obscureConfirm = !obscureConfirm),
                ),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(child: const Text("Cancel"), onPressed: () => Navigator.pop(ctx)),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF4ECDC4), foregroundColor: Colors.black),
            child: const Text("Reset Password"),
            onPressed: () {
              final code = codeCtrl.text.trim();
              final pass = passCtrl.text.trim();
              final confirm = confirmCtrl.text.trim();
              if (code.isEmpty || code.length != 6) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Enter the 6-digit code")));
                return;
              }
              if (pass.isEmpty || pass.length < 6) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Password must be at least 6 characters")));
                return;
              }
              if (pass != confirm) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Passwords do not match")));
                return;
              }
              _channel?.sink.add(jsonEncode({
                "type": "forgot_password_phone_confirm",
                "phone": phone,
                "code": code,
                "new_password": pass,
              }));
              Navigator.pop(ctx);
            },
          ),
        ],
      ),
      ),
    );
  }

  void _showForgotUsernameDialog() {
    TextEditingController ctrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text("Forgot Username", style: TextStyle(color: Color(0xFFFFD700), fontFamily: 'Courier')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text("Enter your email. If an account exists, your username will be sent.", style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 16),
            TextField(
              controller: ctrl,
              keyboardType: TextInputType.emailAddress,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: "Email",
                prefixIcon: Icon(Icons.email, color: Colors.grey),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(child: const Text("Cancel"), onPressed: () => Navigator.pop(ctx)),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFFD700), foregroundColor: Colors.black),
            child: const Text("Send Username"),
            onPressed: () {
              final email = ctrl.text.trim();
              if (email.isEmpty) return;
              _channel?.sink.add(jsonEncode({
                "type": "forgot_username_request",
                "email": email,
              }));
              Navigator.pop(ctx);
            },
          ),
        ],
      ),
    );
  }

  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    final mode = portalMode; // null = dev/localhost, 'CLIENT' = app.*, 'COACH' = coach.*

    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 40.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // --- CONNECTION STATUS HEADER ---
              Container(
                padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
                decoration: BoxDecoration(
                  color: _isConnected ? Colors.green.withOpacity(0.1) : Colors.red.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: _isConnected ? Colors.green : Colors.red)
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.circle, size: 10, color: _isConnected ? Colors.green : Colors.red),
                    const SizedBox(width: 10),
                    Text(_statusMessage, style: TextStyle(color: _isConnected ? Colors.green : Colors.red, fontSize: 10, fontFamily: "Courier")),
                  ],
                ),
              ),
              if (!_isConnected) 
                TextButton(
                  onPressed: _connectToBridge, 
                  child: const Text("RETRY CONNECTION", style: TextStyle(color: Colors.white54))
                ),
              // --------------------------------

              const SizedBox(height: 40),
              const Icon(Icons.shield_moon, size: 80, color: Color(0xFF333333)),
              const SizedBox(height: 20),

              // --- PORTAL-AWARE TITLE ---
              Text(
                mode == 'COACH'
                    ? "SOVEREIGN SANCTUARY\nCoach Portal"
                    : mode == 'CLIENT'
                        ? "SOVEREIGN SANCTUARY"
                        : "SOVEREIGN SANCTUARY",
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white, letterSpacing: 4, fontFamily: 'Courier', fontSize: 18),
              ),

              const SizedBox(height: 60),

              // =============================================================
              // BIOMETRIC QUICK LOGIN (Face ID / Fingerprint)
              // Shown when saved credentials exist for CLIENT or COACH
              // =============================================================
              if (_hasBiometricCreds && !_isLoading && mode != 'ADMIN') ...[
                Container(
                  width: double.infinity,
                  margin: const EdgeInsets.only(bottom: 24),
                  padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
                  decoration: BoxDecoration(
                    color: const Color(0xFF111111),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.4)),
                  ),
                  child: Column(children: [
                    Text(
                      'Welcome back${_savedUsername != null ? ", $_savedUsername" : ""}',
                      style: const TextStyle(
                        color: Color(0xFFE8D5A3),
                        fontSize: 14,
                        fontFamily: 'Cormorant Garamond',
                      ),
                    ),
                    const SizedBox(height: 16),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFFC9A962),
                          foregroundColor: Colors.black,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                        ),
                        onPressed: _attemptBiometricLogin,
                        icon: Icon(
                          _biometricAvailable ? Icons.fingerprint : Icons.lock_open,
                          size: 24,
                        ),
                        label: Text(
                          _biometricAvailable ? 'Login with Face ID / Fingerprint' : 'Quick Login',
                          style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 1,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    TextButton(
                      onPressed: _switchAccount,
                      child: const Text(
                        'Use a different account',
                        style: TextStyle(color: Colors.white38, fontSize: 12),
                      ),
                    ),
                  ]),
                ),
              ],

              if (_isLoading) ...[
                const SizedBox(height: 20),
                const CircularProgressIndicator(color: Color(0xFFC9A962)),
                const SizedBox(height: 12),
                const Text('Authenticating...', style: TextStyle(color: Colors.white54, fontSize: 12)),
                const SizedBox(height: 20),
              ],

              // =============================================================
              // COACH MODE (coach.sovereignsanctuary.net) — coach-only login
              // =============================================================
              if (mode == 'COACH') ...[
                _buildGateButton(
                  "COACH ACCESS", "Supervision & Admin", Icons.admin_panel_settings, const Color(0xFFFFD700),
                  () => _showLoginDialog("COACH")
                ),
              ]
              // =============================================================
              // CLIENT / GATEWAY MODE (app.sovereignsanctuary.net)
              // Shows role chooser: Client stays, Coach redirects, Admin gate-checks
              // =============================================================
              else if (mode == 'CLIENT') ...[
                // --- "Who are you?" gateway ---
                const Text(
                  "Welcome. How would you like to proceed?",
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.white70, fontSize: 13, fontFamily: 'Courier'),
                ),
                const SizedBox(height: 30),

                _buildGateButton(
                  "I AM A CLIENT", "Therapy & Growth", Icons.spa, Colors.blueAccent,
                  () => _showLoginDialog("CLIENT")
                ),
                const SizedBox(height: 20),

                _buildGateButton(
                  "I AM A COACH", "Go to Coach Portal", Icons.admin_panel_settings, const Color(0xFFFFD700),
                  () {
                    // Redirect to the coach subdomain
                    if (kIsWeb) {
                      launchUrl(
                        Uri.parse('https://coach.sovereignsanctuary.net'),
                        mode: LaunchMode.externalApplication,
                      );
                    }
                  }
                ),
                const SizedBox(height: 20),

                _buildGateButton(
                  "ADMINISTRATION", "System Control", Icons.security, const Color(0xFFFF006E),
                  () => _showAdminGateDialog()
                ),
              ]
              // =============================================================
              // DEV / LOCALHOST MODE — show all buttons (original behavior)
              // =============================================================
              else ...[
                _buildGateButton(
                  "CLIENT PORTAL", "Therapy & Growth", Icons.spa, Colors.blueAccent,
                  () => _showLoginDialog("CLIENT")
                ),
                const SizedBox(height: 20),

                _buildGateButton(
                  "COACH ACCESS", "Supervision & Admin", Icons.admin_panel_settings, const Color(0xFFFFD700),
                  () => _showLoginDialog("COACH")
                ),
                const SizedBox(height: 20),

                _buildGateButton(
                  "ADMIN ACCESS", "System Control", Icons.security, const Color(0xFFFF006E),
                  () => _showLoginDialog("ADMIN")
                ),
              ],

              const SizedBox(height: 40),

              // "CREATE NEW ACCOUNT" — visible on app.* and dev, hidden on coach.*
              if (mode != 'COACH')
                TextButton(
                  onPressed: () {
                    Navigator.push(context, MaterialPageRoute(
                      builder: (_) => const SignUpWizard()
                    ));
                  },
                  child: const Text("CREATE NEW ACCOUNT", style: TextStyle(color: Colors.white, decoration: TextDecoration.underline, letterSpacing: 1.5, fontSize: 13, fontWeight: FontWeight.w500)),
                ),
          ],
        ),
       ),
      ),
    );
  }

  Widget _buildGateButton(String title, String sub, IconData icon, Color color, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          border: Border.all(color: color.withOpacity(0.3)),
          borderRadius: BorderRadius.circular(12),
          color: color.withOpacity(0.05),
        ),
        child: Row(
          children: [
            Icon(icon, color: color, size: 32),
            const SizedBox(width: 20),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 16)),
                Text(sub, style: TextStyle(color: Colors.grey[600], fontSize: 12)),
              ],
            ),
            const Spacer(),
            Icon(Icons.arrow_forward_ios, color: color, size: 16)
          ],
        ),
      ),
    );
  }
}

class _LobbyButton extends StatelessWidget {
  final String title, subtitle;
  final Color color;
  final IconData icon;
  final VoidCallback onTap;
  const _LobbyButton({required this.title, required this.subtitle, required this.color, required this.icon, required this.onTap});

  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          border: Border.all(color: color.withOpacity(0.5)),
          borderRadius: BorderRadius.circular(12),
          color: color.withOpacity(0.05),
        ),
        child: Row(
          children: [
            Icon(icon, color: color, size: 32),
            const SizedBox(width: 20),
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 16, letterSpacing: 1.2)),
              const SizedBox(height: 4),
              Text(subtitle, style: TextStyle(color: Colors.white54, fontSize: 12)),
            ]),
            const Spacer(),
            Icon(Icons.arrow_forward_ios, color: color.withOpacity(0.5), size: 16),
          ],
        ),
      ),
    );
  }
}

// -----------------------------------------------------------------------------
// SIGN UP WIZARD (Sanitized Session Logic)
// -----------------------------------------------------------------------------
class SignUpWizard extends StatefulWidget {
  final String? role; // null = user picks during wizard
  const SignUpWizard({super.key, this.role});
  @override
  State<SignUpWizard> createState() => _SignUpWizardState();
}

class _SignUpWizardState extends State<SignUpWizard> {
  int _step = 0; // 0: consent+role, 1: tier/dojo, 2: form, 3: order review (paid only)
  bool _consentGiven = false;
  String? _selectedRole; // CLIENT or COACH
  String _selectedTier = 'TRIAL'; // COACH_ONLY, TRIAL, STANDARD, TOP_TIER
  List<String> _selectedDojos = []; // coach dojo picks
  DateTime? _dob;
  final _nameCtrl = TextEditingController();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _obscurePass = true;
  final List<String> _endpoints = [defaultWsUrl];
  bool _isDependent = false;
  TextEditingController _parentCtrl = TextEditingController();
  WebSocketChannel? _regSocket;
  bool _isRegistering = false;
  Timer? _regTimeoutTimer;
  /// After Stripe trial setup (Checkout mode=setup); sent with register_request.
  String? _trialStripeSessionId;

  // Dojo pricing
  static const Map<String, double> _dojoPrices = {
    'therapist': 175.0,
    'project_pm': 250.0,
    'business': 325.0,
    'cnc': 150.0,
    'mcat': 500.0,
    'teacher': 225.0,
    'judge': 2100.0,
    'coach_nate': 90.0,
  };
  static const Map<String, String> _dojoLabels = {
    'cnc': 'CNC Machining',
    'therapist': 'Therapist',
    'teacher': 'Teacher',
    'project_pm': 'Project PM',
    'business': 'Business',
    'mcat': 'MCAT',
    'judge': 'Judge',
    'coach_nate': 'Coach Nate',
  };
  // JUDGE is excluded from multi-DOJO volume discounts
  static const List<int> _dojoDiscounts = [0, 0, 10, 15, 20, 25, 30, 35]; // index = count (excl. JUDGE)

  // Discount code (replaces old invite code for both client and coach)
  final _inviteCodeCtrl = TextEditingController();
  final _discountCodeCtrl = TextEditingController();
  bool _discountValidated = false;
  bool _discountValidating = false;
  String? _discountError;
  Map<String, dynamic> _discountDetails = {};
  bool get _isInviteCodeEntered => _inviteCodeCtrl.text.trim().isNotEmpty;

  // Coach invite token (from URL ?invite=TOKEN when client arrives via coach invite link)
  String? _coachInviteToken;

  // Contact fields
  final _emailCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();
  final _timezoneCtrl = TextEditingController();
  /// Device-detected IANA zone at signup (sent as browser_timezone; sticky policy on server).
  String? _browserIanaForSignup;

  // W-9 fields (coaches only)
  final _w9LegalNameCtrl = TextEditingController();
  final _w9BusinessNameCtrl = TextEditingController();
  final _w9StreetCtrl = TextEditingController();
  final _w9CityCtrl = TextEditingController();
  final _w9StateCtrl = TextEditingController();
  final _w9ZipCtrl = TextEditingController();
  final _w9TinCtrl = TextEditingController();
  final _w9SignatureCtrl = TextEditingController();
  String _w9TaxClass = 'individual';
  bool _w9Certified = false;

  // W-9 document upload
  String? _w9DocFileName;
  String? _w9DocBase64;
  Uint8List? _w9DocBytes;

  // SSN/EIN validation helper
  String? _validateTin(String value) {
    final digits = value.replaceAll(RegExp(r'[^0-9]'), '');
    if (digits.isEmpty) return null; // Not filled yet
    if (digits.length != 9) return "Must be exactly 9 digits";
    // SSN checks
    if (digits.startsWith('000') || digits.startsWith('999') || digits.startsWith('666')) {
      return "Invalid SSN prefix";
    }
    if (digits.substring(3, 5) == '00' || digits.substring(5) == '0000') {
      return "Invalid SSN group/serial";
    }
    return null; // Valid format
  }

  String get _effectiveRole => _selectedRole ?? widget.role ?? "CLIENT";

  bool get _isPaidTier {
    if (isNativeIOS) return false; // Apple Guideline 3.1.1 — no Stripe on iOS
    if (_effectiveRole == 'COACH') return _selectedDojos.isNotEmpty;
    return _selectedTier == 'STANDARD' || _selectedTier == 'TOP_TIER';
  }

  bool _isLaunchingStripe = false;
  String? _stripeError;

  @override
  void initState() {
    super.initState();
    _selectedRole = widget.role; // Pre-set if passed
    _parseCoachInviteFromUrl();
    _sanitizeSession();
    _loadSignupIanaForSignup();
  }

  Future<void> _loadSignupIanaForSignup() async {
    try {
      final tz = await FlutterTimezone.getLocalTimezone();
      final s = tz.trim();
      if (s.isEmpty || !mounted) return;
      _browserIanaForSignup = s;
      setState(() => _timezoneCtrl.text = s);
    } catch (_) {}
  }

  void _parseCoachInviteFromUrl() {
    try {
      final uri = Uri.base;
      String? invite = uri.queryParameters['invite'];
      if (invite == null && uri.fragment.isNotEmpty) {
        final q = uri.fragment.contains('?') ? uri.fragment.split('?').last : uri.fragment;
        invite = Uri.tryParse('http://x?$q')?.queryParameters['invite'];
      }
      if (invite != null && invite.trim().length >= 8) {
        _coachInviteToken = invite.trim().toUpperCase();
      }
    } catch (_) {}
  }

  @override
  void dispose() {
    _regTimeoutTimer?.cancel();
    _regSocket?.sink.close();
    _regSocket = null;
    super.dispose();
  }

  Future<void> _sanitizeSession() async {
    debugLog(">>> [INTAKE] Sanitizing session to prevent auto-linking...");
    await HardwareIdentity().clearSession();
  }

  int _calculateAge(DateTime birthDate) {
    final now = DateTime.now();
    int age = now.year - birthDate.year;
    if (now.month < birthDate.month || (now.month == birthDate.month && now.day < birthDate.day)) age--;
    return age;
  }

  Future<void> _submitRegistration() async {
    if (_isRegistering) return;

    // 1. Validation
    if (_nameCtrl.text.trim().isEmpty) {
       ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Full Name is required")));
       return;
    }
    if (_dob == null) {
       ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Date of Birth is Required")));
       return;
    }
    if (_calculateAge(_dob!) < 18) {
       ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Error: Primary Account Holder must be 18+.")));
       return;
    }
    if (_isDependent && _parentCtrl.text.trim().isEmpty) {
       ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Please enter the Head of Household username, or turn off the Dependent toggle.")));
       return;
    }
    // Coach-specific validations (always required for production)
    if (_effectiveRole == "COACH") {
      if (_emailCtrl.text.trim().isEmpty || !_emailCtrl.text.contains('@') || !_emailCtrl.text.contains('.')) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("A valid email address is required")));
        return;
      }
      final phoneDigits = _phoneCtrl.text.replaceAll(RegExp(r'[^0-9]'), '');
      if (phoneDigits.length < 10) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("A valid 10-digit phone number is required")));
        return;
      }
      // SSN/EIN format validation
      if (_w9TinCtrl.text.trim().isNotEmpty) {
        final tinError = _validateTin(_w9TinCtrl.text.trim());
        if (tinError != null) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Taxpayer ID: $tinError")));
          return;
        }
      }
    }
    if (_effectiveRole == "CLIENT") {
      final emailT = _emailCtrl.text.trim();
      final phoneDigits = _phoneCtrl.text.replaceAll(RegExp(r'[^0-9]'), '');
      if (emailT.isEmpty && phoneDigits.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Please provide an email address or phone number.")),
        );
        return;
      }
      if (emailT.isNotEmpty && (!emailT.contains('@') || !emailT.contains('.'))) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Please enter a valid email address")),
        );
        return;
      }
      if (phoneDigits.isNotEmpty && phoneDigits.length < 10) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text("Phone number must be at least 10 digits")),
        );
        return;
      }
    }
    if (_timezoneCtrl.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Time zone is required. Confirm or edit the detected value.")),
      );
      return;
    }
    if (_userCtrl.text.trim().isEmpty || _passCtrl.text.trim().isEmpty) {
       ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Username and Password are required")));
       return;
    }

    if (_effectiveRole == "CLIENT" && _selectedTier == "TRIAL") {
      final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
      String? sid = _trialStripeSessionId;
      if (sid == null || sid.isEmpty) {
        final emailT = _emailCtrl.text.trim();
        final phoneDigits = _phoneCtrl.text.replaceAll(RegExp(r'[^0-9]'), '');
        try {
          final q = Uri.parse('$base/api/registration/trial/billing-status').replace(
            queryParameters: {
              if (emailT.isNotEmpty) 'email': emailT,
              if (phoneDigits.length >= 10) 'phone_digits': phoneDigits,
            },
          );
          final poll = await http.get(q).timeout(const Duration(seconds: 12));
          if (poll.statusCode == 200) {
            final pj = jsonDecode(poll.body) as Map<String, dynamic>;
            if (pj['ready'] == true && (pj['session_id']?.toString().isNotEmpty ?? false)) {
              sid = pj['session_id'].toString();
              _trialStripeSessionId = sid;
            }
          }
        } catch (_) {}
      }

      if (sid == null || sid.isEmpty) {
        if (isNativeIOS) {
          final nameQ = Uri.encodeComponent(_nameCtrl.text.trim());
          final emailQ = Uri.encodeComponent(_emailCtrl.text.trim());
          final webUrl = 'https://app.sovereignsanctuary.net/trial-setup.html?name=$nameQ&email=$emailQ';
          await launchUrl(Uri.parse(webUrl), mode: LaunchMode.externalApplication);
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
              content: Text('Complete billing on the website, then return and tap Create Account again.'),
              duration: Duration(seconds: 8),
            ));
          }
          return;
        }
        setState(() => _isRegistering = true);
        try {
          final uri = Uri.parse('$base/api/registration/trial/setup-billing');
          final emailT = _emailCtrl.text.trim();
          final phoneDigits = _phoneCtrl.text.replaceAll(RegExp(r'[^0-9]'), '');
          final discountForSetup = _discountValidated && _discountCodeCtrl.text.trim().isNotEmpty
              ? _discountCodeCtrl.text.trim()
              : (_inviteCodeCtrl.text.trim().isNotEmpty ? _inviteCodeCtrl.text.trim() : null);
          final resp = await http
              .post(
                uri,
                headers: {'Content-Type': 'application/json'},
                body: jsonEncode({
                  'name': _nameCtrl.text.trim(),
                  if (emailT.isNotEmpty) 'email': emailT,
                  if (phoneDigits.length >= 10) 'phone_digits': phoneDigits,
                  if (discountForSetup != null) 'discount_code': discountForSetup,
                }),
              )
              .timeout(const Duration(seconds: 20));
          if (!mounted) return;
          setState(() => _isRegistering = false);
          if (resp.statusCode == 200) {
            final data = jsonDecode(resp.body) as Map<String, dynamic>;
            final checkoutUrl = data['checkout_url'] as String?;
            final newSid = data['session_id'] as String?;
            if (checkoutUrl != null && checkoutUrl.isNotEmpty) {
              if (newSid != null && newSid.isNotEmpty) {
                _trialStripeSessionId = newSid;
              }
              if (kIsWeb) {
                // Same-tab redirect on Web — never blocked. We won't return
                // to this screen, so show the message before navigating.
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text('Opening secure checkout…'),
                  duration: Duration(seconds: 3),
                ));
              } else {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text('After you add your card, return here and tap Create Account again.'),
                  duration: Duration(seconds: 6),
                ));
              }
              await launchCheckoutUrl(checkoutUrl);
            }
          } else {
            var msg = 'Billing setup failed';
            try {
              final err = jsonDecode(resp.body);
              msg = err['detail']?.toString() ?? msg;
            } catch (_) {}
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text(msg), backgroundColor: Colors.red),
            );
          }
        } catch (e) {
          if (mounted) {
            setState(() => _isRegistering = false);
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Connection error: $e'), backgroundColor: Colors.red),
            );
          }
        }
        return;
      }
    }

    setState(() => _isRegistering = true);
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Sending Data to Neural Core...")));

    _regTimeoutTimer?.cancel();
    _regTimeoutTimer = Timer(const Duration(seconds: 30), () {
      if (!mounted) return;
      setState(() => _isRegistering = false);
      try { _regSocket?.sink.close(); } catch (_) {}
      _regSocket = null;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text("Registration timed out. Please check your connection and try again."),
        backgroundColor: Colors.red,
        duration: Duration(seconds: 6),
      ));
    });

    // 3. Build Registration Payload FIRST
    final role = _effectiveRole;
    final regPayload = {
      "type": "register_request",
      "consent_agreed": true,
      "consent_version": "v13.0_2026",
      "role": role,
      "username": _userCtrl.text.trim(),
      "password": _passCtrl.text.trim(),
      "name": _nameCtrl.text.trim(),
      "dob": DateFormat('yyyy-MM-dd').format(_dob!),
      "modality": "General",
      "parent_username": _isDependent ? _parentCtrl.text.trim() : null,
      "invite_code": _inviteCodeCtrl.text.trim(),
      "discount_code": _discountCodeCtrl.text.trim().isNotEmpty ? _discountCodeCtrl.text.trim() : (_inviteCodeCtrl.text.trim().isNotEmpty ? _inviteCodeCtrl.text.trim() : null),
      // Contact info
      "email": _emailCtrl.text.trim(),
      "phone": _phoneCtrl.text.trim(),
      "timezone": _timezoneCtrl.text.trim(),
      if (_browserIanaForSignup != null && _browserIanaForSignup!.trim().isNotEmpty)
        "browser_timezone": _browserIanaForSignup!.trim(),
      // Tier/plan selection (clients)
      "registration_type": role == "CLIENT" ? _selectedTier : null,
      // Coach invite token (when client arrives via coach invite link)
      if (role == "CLIENT" && _coachInviteToken != null) "coach_invite_token": _coachInviteToken,
      if (role == "CLIENT" && _selectedTier == "TRIAL" && (_trialStripeSessionId ?? "").isNotEmpty)
        "stripe_session_id": _trialStripeSessionId,
      // Dojo selection (coaches)
      "selected_dojos": role == "COACH" ? _selectedDojos : null,
      "dojo_discount_pct": role == "COACH" ? _calculateDojoDiscount() : null,
      "dojo_monthly_price": role == "COACH" ? _calculateDojoPrice() : null,
      "coach_ethics_accepted": role == "COACH" ? true : null,
    };

    // Include W-9 data for coach registration
    if (role == "COACH" && _w9LegalNameCtrl.text.trim().isNotEmpty) {
      regPayload["w9_data"] = {
        "legal_name": _w9LegalNameCtrl.text.trim(),
        "business_name": _w9BusinessNameCtrl.text.trim(),
        "tax_classification": _w9TaxClass,
        "street": _w9StreetCtrl.text.trim(),
        "city": _w9CityCtrl.text.trim(),
        "state": _w9StateCtrl.text.trim(),
        "zip": _w9ZipCtrl.text.trim(),
        "tin": _w9TinCtrl.text.trim(),
        "certified": _w9Certified,
        "signature": _w9SignatureCtrl.text.trim(),
        "signed_date": DateTime.now().toIso8601String(),
      };
      // Include W-9 document upload if provided
      if (_w9DocBase64 != null && _w9DocFileName != null) {
        regPayload["w9_doc"] = {
          "filename": _w9DocFileName,
          "data": _w9DocBase64,
        };
      }
    }

    debugLog(">>> [REG] Payload built: ${regPayload['username']} / ${regPayload['role']}");

    // 2. THE BURNER SOCKET — stored as instance var to prevent GC
    _regSocket = WebSocketChannel.connect(Uri.parse(_endpoints[0]));
    final regSocket = _regSocket!;
    bool regSent = false;

    regSocket.stream.listen((message) {
      final data = jsonDecode(message);
      debugLog(">>> [REG] SERVER SAYS: $data");

      // When server confirms connection ready, NOW send the registration payload
      if (data['type'] == 'connected') {
        if (!regSent) {
          regSent = true;
          debugLog(">>> [REG] Connection confirmed — sending register_request NOW");
          regSocket.sink.add(jsonEncode(regPayload));
        }
        return;
      }

      // CASE A: Server created account AND logged us in (Ideal)
      if (data['type'] == 'login_success') {
        _regTimeoutTimer?.cancel();
        _trialStripeSessionId = null;
        final profile = Map<String, dynamic>.from(data['profile'] ?? {});
        final regRole = (profile['role'] ?? _effectiveRole).toString();
        final token = data['token'] ?? "";

        HardwareIdentity().saveSession(_userCtrl.text, token.isNotEmpty ? token : "REG_${DateTime.now().millisecondsSinceEpoch}", profile);

        Future.microtask(() {
          try { regSocket.sink.close(); } catch (_) {}
          _regSocket = null;
        });

        if (!mounted) return;
        setState(() => _isRegistering = false);

        if (regRole == "COACH") {
          _showCoachPendingDialog();
        } else {
          Navigator.pushAndRemoveUntil(
            context,
            MaterialPageRoute(builder: (_) => OnboardingTutorialScreen(
               role: regRole,
               userData: {...profile, "token": token, "username": _userCtrl.text.trim(), "password": _passCtrl.text.trim()},
            )),
            (route) => false
          );
        }
      } 
      
      // CASE B: Server created account but waits for login
      else if (data['type'] == 'register_success' || data['type'] == 'registration_success') {
        final regRole = _effectiveRole;
        if (regRole == "COACH") {
          _regTimeoutTimer?.cancel();
          Future.microtask(() {
            try { regSocket.sink.close(); } catch (_) {}
            _regSocket = null;
          });
          if (!mounted) return;
          setState(() => _isRegistering = false);
          _showCoachPendingDialog();
        } else {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Identity Created. Logging in...")));
          }
          regSocket.sink.add(jsonEncode({
             "type": "login_request",
             "username": _userCtrl.text.trim(),
             "password": _passCtrl.text.trim(),
             "expected_role": regRole,
             "client_context": kIsWeb ? '${regRole.toLowerCase()}_web' : '${regRole.toLowerCase()}_mobile',
          }));
        }
      }
      
      // CASE C: Error
      else if (data['type'] == 'error' || data['type'] == 'registration_failed') {
        _regTimeoutTimer?.cancel();
        if (mounted) {
          setState(() => _isRegistering = false);
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text("FAILURE: ${data['message'] ?? 'Registration failed'}"),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 8),
          ));
        }
      }

      // CASE D: Unknown response
      else {
        debugLog(">>> [REG] Unhandled response type: ${data['type']}");
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text("Server: ${data['type']} — ${data['message'] ?? jsonEncode(data)}"),
            duration: const Duration(seconds: 5),
          ));
        }
      }
    }, onError: (e) {
      debugLog(">>> [REG] WebSocket error: $e");
      _regTimeoutTimer?.cancel();
      if (mounted) {
        setState(() => _isRegistering = false);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Connection Error: $e"), backgroundColor: Colors.red));
      }
    }, onDone: () {
      debugLog(">>> [REG] WebSocket closed (regSent=$regSent)");
      _regTimeoutTimer?.cancel();
      _regSocket = null;
      if (!mounted) return;
      setState(() => _isRegistering = false);
      if (!regSent) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Connection dropped before registration could be sent. Please try again."),
          backgroundColor: Colors.red,
        ));
      }
    });
  }

  void _handleLoginSuccess(Map<String, dynamic> data, WebSocketChannel burnerSocket) {
        final loginToken = data['token']?.toString() ?? "REG_${DateTime.now().millisecondsSinceEpoch}";
        HardwareIdentity().saveSession(_userCtrl.text, loginToken, data['profile'] ?? {});
        burnerSocket.sink.close();
        final chatSocket = WebSocketChannel.connect(Uri.parse(_endpoints[0]));
        chatSocket.sink.add(jsonEncode({
           "type": "login_request",
           "username": _userCtrl.text.trim(),
           "password": _passCtrl.text.trim(),
           "expected_role": _effectiveRole,
           "client_context": kIsWeb ? '${_effectiveRole.toLowerCase()}_web' : '${_effectiveRole.toLowerCase()}_mobile',
        }));
        Navigator.pushAndRemoveUntil(
          context, 
          MaterialPageRoute(builder: (_) => NeuralInterface(
             currentUserProfile: data['profile'],
             username: _userCtrl.text.trim(),
             password: _passCtrl.text.trim(),
          )),
          (route) => false
        );
  }

  void _showCoachPendingDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A1A1A),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16), side: const BorderSide(color: Color(0xFFFFD700), width: 1)),
        title: Row(
          children: [
            const Icon(Icons.hourglass_top, color: Color(0xFFFFD700), size: 28),
            const SizedBox(width: 12),
            const Expanded(child: Text("Application Submitted", style: TextStyle(color: Color(0xFFFFD700), fontFamily: 'Courier', fontWeight: FontWeight.bold, fontSize: 18))),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              "Your Coach Command application has been received and is pending admin approval.",
              style: TextStyle(color: Colors.white70, fontSize: 14, height: 1.5),
            ),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFFFD700).withOpacity(0.08),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    const Icon(Icons.check_circle, color: Colors.green, size: 16),
                    const SizedBox(width: 8),
                    Text("Dojos selected: ${_selectedDojos.length}", style: const TextStyle(color: Colors.white70, fontSize: 12)),
                  ]),
                  const SizedBox(height: 4),
                  Row(children: [
                    const Icon(Icons.check_circle, color: Colors.green, size: 16),
                    const SizedBox(width: 8),
                    const Text("W-9 information submitted", style: TextStyle(color: Colors.white70, fontSize: 12)),
                  ]),
                  const SizedBox(height: 4),
                  Row(children: [
                    const Icon(Icons.schedule, color: Color(0xFFFFD700), size: 16),
                    const SizedBox(width: 8),
                    const Text("Awaiting admin review", style: TextStyle(color: Colors.white70, fontSize: 12)),
                  ]),
                ],
              ),
            ),
            const SizedBox(height: 12),
            Text(
              "You will be notified once your application is approved. You can then log in with your credentials.",
              style: TextStyle(color: Colors.grey[500], fontSize: 12, height: 1.4),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              Navigator.of(context).popUntil((route) => route.isFirst);
            },
            child: const Text("RETURN TO LOBBY", style: TextStyle(color: Color(0xFFFFD700), fontWeight: FontWeight.bold, letterSpacing: 1)),
          ),
        ],
      ),
    );
  }

  // Dojo pricing helpers — JUDGE excluded from volume discounts
  int _calculateDojoDiscount() {
    // Only count non-JUDGE dojos for discount tier
    final count = _selectedDojos.where((d) => d != 'judge').length;
    if (count < 0 || count > 6) return 0;
    return _dojoDiscounts[count];
  }

  double _calculateDojoBaseTotal() {
    double total = 0;
    for (final d in _selectedDojos) {
      total += _dojoPrices[d] ?? 0;
    }
    return total;
  }

  double _calculateDojoPrice() {
    final disc = _calculateDojoDiscount();
    // Apply discount only to non-JUDGE dojos; JUDGE always at full price
    double discountedTotal = 0;
    double judgeTotal = 0;
    for (final d in _selectedDojos) {
      final price = _dojoPrices[d] ?? 0;
      if (d == 'judge') {
        judgeTotal += price;
      } else {
        discountedTotal += price;
      }
    }
    discountedTotal = discountedTotal * (1 - disc / 100);
    return double.parse((discountedTotal + judgeTotal).toStringAsFixed(2));
  }

  Future<void> _verifyDiscountCode() async {
    final code = _discountCodeCtrl.text.trim();
    if (code.isEmpty) return;
    setState(() { _discountValidating = true; _discountError = null; _discountValidated = false; _discountDetails = {}; });
    try {
      final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
      final tierParam = _effectiveRole == 'CLIENT' ? '?tier=$_selectedTier' : '';
      final uri = Uri.parse('$base/api/billing/verify-discount-code/${Uri.encodeComponent(code)}$tierParam');
      final resp = await http.get(uri).timeout(const Duration(seconds: 10));
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _discountValidated = true;
          _discountDetails = Map<String, dynamic>.from(data);
          _discountError = null;
        });
      } else {
        final body = jsonDecode(resp.body);
        setState(() {
          _discountValidated = false;
          _discountDetails = {};
          _discountError = body['detail'] ?? 'Invalid or expired code';
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _discountValidated = false;
        _discountError = 'Could not verify code. Please try again.';
      });
    } finally {
      if (mounted) setState(() => _discountValidating = false);
    }
  }

  Future<void> _selectDate(BuildContext context) async {
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: DateTime.now().subtract(const Duration(days: 6570)), 
      firstDate: DateTime(1900),
      lastDate: DateTime.now(),
      builder: (context, child) => Theme(data: ThemeData.dark(), child: child!)
    );
    if (picked != null) setState(() => _dob = picked);
  }

  Widget _buildRegTaxChip(String value, String label) {
    final isSelected = _w9TaxClass == value;
    return GestureDetector(
      onTap: () => setState(() => _w9TaxClass = value),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: isSelected ? const Color(0xFFFFD700).withOpacity(0.15) : const Color(0xFF1A1A1A),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: isSelected ? const Color(0xFFFFD700) : Colors.white10),
        ),
        child: Text(label, style: TextStyle(color: isSelected ? const Color(0xFFFFD700) : Colors.grey, fontSize: 12)),
      ),
    );
  }

  String get _appBarTitle {
    if (_step == 0) return "CREATE ACCOUNT";
    if (_step == 1) {
      return _effectiveRole == "COACH" ? "SELECT DOJOS" : "SELECT PLAN";
    }
    if (_step == 3) return "REVIEW ORDER";
    return "NEW ${_effectiveRole}";
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF111111),
      appBar: AppBar(
        title: Text(_appBarTitle, style: const TextStyle(color: Colors.white, fontFamily: 'Courier', fontWeight: FontWeight.bold, letterSpacing: 2)), 
        backgroundColor: Colors.transparent,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.redAccent),
          onPressed: () {
            if (_step > 0) {
              setState(() => _step--);
            } else {
              Navigator.pop(context);
            }
          },
        ),
      ),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: _step == 0 
          ? _buildConsentAndRoleStep()
          : _step == 1
            ? (_effectiveRole == "COACH" ? _buildCoachDojoSelection() : _buildClientTierSelection())
            : _step == 3
              ? _buildOrderReview()
              : _buildForm(),
      ),
    );
  }

  // ─── STEP 0: CONSENT + ROLE CHOICE ───
  Widget _buildConsentAndRoleStep() {
    if (!_consentGiven) {
      // Show full covenant with checkbox — uses Expanded internally
      return SovereignCovenantDoc(
        consentGiven: _consentGiven,
        onChanged: (v) => setState(() => _consentGiven = v!),
        color: Colors.blueAccent,
        btnText: null,
        onNext: null,
      );
    }
    // Consent given — show role choice
    return Column(
      children: [
        // Compact consent confirmation
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: Colors.green.withOpacity(0.1),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.green.withOpacity(0.3)),
          ),
          child: Row(
            children: [
              const Icon(Icons.check_circle, color: Colors.green, size: 18),
              const SizedBox(width: 8),
              const Expanded(child: Text("Covenant accepted", style: TextStyle(color: Colors.green, fontSize: 13))),
              GestureDetector(
                onTap: () => setState(() => _consentGiven = false),
                child: Text("Review", style: TextStyle(color: Colors.grey[500], fontSize: 12, decoration: TextDecoration.underline)),
              ),
            ],
          ),
        ),
        const Spacer(),
        const Text("CHOOSE YOUR PATH", style: TextStyle(color: Colors.white, fontFamily: 'Courier', fontWeight: FontWeight.bold, fontSize: 18, letterSpacing: 2)),
        const SizedBox(height: 6),
        Text("Select how you'll use Sovereign Sanctuary", style: TextStyle(color: Colors.grey[500], fontSize: 13)),
        const SizedBox(height: 28),
        _buildRoleCard(
          "I'm a Client",
          "Between session AI companion - 24/7, wellness coaching, family deep",
          Icons.self_improvement,
          Colors.blueAccent,
          "CLIENT",
        ),
        const SizedBox(height: 16),
        _buildRoleCard(
          "I'm a Coach",
          "AI assisted coaching platform all-in-one suite, scheduling, DOJO training, financials, records",
          Icons.psychology,
          const Color(0xFFFFD700),
          "COACH",
        ),
        const Spacer(flex: 2),
      ],
    );
  }

  Widget _buildRoleCard(String title, String subtitle, IconData icon, Color accent, String roleValue) {
    final isSelected = _selectedRole == roleValue;
    return GestureDetector(
      onTap: () {
        setState(() => _selectedRole = roleValue);
        Future.delayed(const Duration(milliseconds: 300), () {
          if (mounted) setState(() => _step = 1);
        });
      },
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: isSelected ? accent.withOpacity(0.12) : const Color(0xFF1A1A1A),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: isSelected ? accent : Colors.white12, width: isSelected ? 2 : 1),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: accent.withOpacity(0.15),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, color: accent, size: 30),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: TextStyle(color: accent, fontWeight: FontWeight.bold, fontSize: 16, fontFamily: 'Courier')),
                  const SizedBox(height: 4),
                  Text(subtitle, style: TextStyle(color: Colors.grey[400], fontSize: 12, height: 1.3)),
                ],
              ),
            ),
            Icon(Icons.arrow_forward_ios, color: accent.withOpacity(0.5), size: 18),
          ],
        ),
      ),
    );
  }

  // ─── STEP 1C: CLIENT TIER SELECTION ───
  Widget _buildClientTierSelection() {
    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text("SELECT YOUR TIER", style: TextStyle(color: Colors.white, fontFamily: 'Courier', fontWeight: FontWeight.bold, fontSize: 16, letterSpacing: 2)),
          const SizedBox(height: 6),
          const SizedBox(height: 20),
          _buildTierOption(
            "COACH-ONLY",
            "COACH_ONLY",
            "Free",
            "Scheduling with your assigned coach only. No AI access.",
            Icons.calendar_today,
            Colors.tealAccent,
            ["Coach scheduling", "Session booking", "No AI features"],
          ),
          const SizedBox(height: 12),
          _buildTierOption(
            "THRESHOLD (Trial)",
            "TRIAL",
            "Free / 7 days",
            "Explore Little Nate with limited AI conversations and basic tracking.",
            Icons.explore,
            Colors.blueAccent,
            ["Limited AI conversations", "Basic emotional tracking", "7-day trial period"],
          ),
          // Paid tiers hidden on native iOS — Apple Guideline 3.1.1 requires IAP.
          // Users register free and upgrade via In-App Purchase after login.
          if (!isNativeIOS) ...[
            const SizedBox(height: 12),
            _buildTierOption(
              "INNER CHAMBER",
              "STANDARD",
              "\$49/mo",
              "Unlimited AI access with voice mode and full biometric metrics.",
              Icons.favorite,
              const Color(0xFF9D4EDD),
              ["Unlimited AI conversations", "Voice mode", "Full emotional metrics", "Session history"],
            ),
            const SizedBox(height: 12),
            _buildTierOption(
              "SOVEREIGN CIRCLE",
              "TOP_TIER",
              "\$149/mo",
              "Everything plus Avatar Mode, Family Sanctuary, and live coaching.",
              Icons.diamond,
              const Color(0xFFFFD700),
              ["Everything in Inner Chamber", "Avatar Mode", "Family Sanctuary", "Live coaching sessions", "Priority support"],
            ),
          ],

          if (isNativeIOS) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A1A),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.info_outline, color: Color(0xFFC9A962), size: 20),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      "Premium plans (Inner Chamber & Sovereign Circle) can be unlocked after sign-up from your account settings.",
                      style: TextStyle(color: Colors.grey[400], fontSize: 12, height: 1.4),
                    ),
                  ),
                ],
              ),
            ),
          ],

          // Discount code section — hidden on iOS per Apple Guideline 3.1.1
          if (!isNativeIOS) ...[
            const SizedBox(height: 20),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A1A),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: _discountValidated ? const Color(0xFF22C55E) : const Color(0xFFC9A962).withOpacity(0.3)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.local_offer, color: const Color(0xFFC9A962), size: 20),
                      const SizedBox(width: 8),
                      const Text("DISCOUNT CODE", style: TextStyle(color: Color(0xFFC9A962), fontFamily: 'Courier', fontWeight: FontWeight.bold, fontSize: 13, letterSpacing: 1.5)),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text("Have a promo, school, or corporate discount code?", style: TextStyle(color: Colors.grey[500], fontSize: 12)),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _discountCodeCtrl,
                          style: const TextStyle(color: Colors.white, fontFamily: 'Courier', letterSpacing: 1),
                          textCapitalization: TextCapitalization.characters,
                          decoration: InputDecoration(
                            labelText: "Discount Code (optional)",
                            labelStyle: TextStyle(color: Colors.grey[600], fontSize: 13),
                            filled: true,
                            fillColor: const Color(0xFF111111),
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.white12)),
                            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.white12)),
                            focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: Color(0xFFC9A962))),
                            contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                          ),
                          onChanged: (_) {
                            if (_discountValidated) setState(() { _discountValidated = false; _discountDetails = {}; _discountError = null; });
                          },
                        ),
                      ),
                      const SizedBox(width: 10),
                      SizedBox(
                        height: 48,
                        child: ElevatedButton(
                          onPressed: _discountValidating ? null : _verifyDiscountCode,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: const Color(0xFFC9A962),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                          ),
                          child: _discountValidating
                              ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                              : const Text("APPLY", style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold, letterSpacing: 1)),
                        ),
                      ),
                    ],
                  ),
                  if (_discountValidated && _discountDetails.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: const Color(0xFF22C55E).withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: const Color(0xFF22C55E).withOpacity(0.3)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.check_circle, color: Color(0xFF22C55E), size: 18),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              _discountDetails['discount_type'] == 'pays_full'
                                  ? "${_discountDetails['name']} — Fully sponsored"
                                  : _discountDetails['discount_type'] == 'percent'
                                      ? "${_discountDetails['name']} — ${_discountDetails['discount_value']}% off"
                                      : "${_discountDetails['name']} — \$${((_discountDetails['discount_value'] ?? 0) / 100).toStringAsFixed(2)} off",
                              style: const TextStyle(color: Color(0xFF22C55E), fontSize: 13, fontWeight: FontWeight.w600),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  if (_discountError != null) ...[
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: const Color(0xFFEF4444).withOpacity(0.1),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.3)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.error_outline, color: Color(0xFFEF4444), size: 18),
                          const SizedBox(width: 8),
                          Expanded(child: Text(_discountError!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 13))),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],

          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: () => setState(() => _step = 2),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.blueAccent,
                minimumSize: const Size(double.infinity, 50),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              child: const Text("CONTINUE", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, letterSpacing: 1.5)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTierOption(String name, String value, String price, String desc, IconData icon, Color accent, List<String> features) {
    final isSelected = _selectedTier == value;
    return GestureDetector(
      onTap: () => setState(() => _selectedTier = value),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: isSelected ? accent.withOpacity(0.1) : const Color(0xFF1A1A1A),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: isSelected ? accent : Colors.white12, width: isSelected ? 2 : 1),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, color: accent, size: 22),
                const SizedBox(width: 10),
                Expanded(child: Text(name, style: TextStyle(color: accent, fontWeight: FontWeight.bold, fontFamily: 'Courier', fontSize: 14))),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: accent.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(price, style: TextStyle(color: accent, fontWeight: FontWeight.bold, fontSize: 12)),
                ),
                if (isSelected) ...[
                  const SizedBox(width: 8),
                  Icon(Icons.check_circle, color: accent, size: 22),
                ],
              ],
            ),
            const SizedBox(height: 8),
            Text(desc, style: TextStyle(color: Colors.grey[400], fontSize: 12, height: 1.3)),
            if (isSelected) ...[
              const SizedBox(height: 10),
              ...features.map((f) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(children: [
                  Icon(Icons.check, color: accent.withOpacity(0.7), size: 14),
                  const SizedBox(width: 8),
                  Text(f, style: const TextStyle(color: Colors.white70, fontSize: 12)),
                ]),
              )),
            ],
          ],
        ),
      ),
    );
  }

  // ─── STEP 1K: COACH DOJO SELECTION ───
  Widget _buildCoachDojoSelection() {
    final baseTotal = _calculateDojoBaseTotal();
    final discount = _calculateDojoDiscount();
    final finalPrice = _calculateDojoPrice();
    final isAllAccess = _selectedDojos.length == _dojoPrices.length;
    final aLaCarteSavings = baseTotal - finalPrice;

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text("SELECT YOUR DOJOS", style: TextStyle(color: Color(0xFFFFD700), fontFamily: 'Courier', fontWeight: FontWeight.bold, fontSize: 16, letterSpacing: 2)),
          const SizedBox(height: 6),
          Text("Choose your mentoring domains. More dojos = bigger discount.\nNote: Judge (\$2,100/mo) is billed at full price — not eligible for multi-DOJO discount.", style: TextStyle(color: Colors.grey[500], fontSize: 13)),
          const SizedBox(height: 20),

          // Dojo checkboxes
          ..._dojoPrices.entries.map((e) {
            final key = e.key;
            final price = e.value;
            final label = _dojoLabels[key] ?? key;
            final isChecked = _selectedDojos.contains(key);
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: GestureDetector(
                onTap: () {
                  setState(() {
                    if (isChecked) {
                      _selectedDojos.remove(key);
                    } else {
                      _selectedDojos.add(key);
                    }
                  });
                },
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                  decoration: BoxDecoration(
                    color: isChecked ? const Color(0xFFFFD700).withOpacity(0.08) : const Color(0xFF1A1A1A),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: isChecked ? const Color(0xFFFFD700) : Colors.white12),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        isChecked ? Icons.check_box : Icons.check_box_outline_blank,
                        color: isChecked ? const Color(0xFFFFD700) : Colors.grey,
                        size: 22,
                      ),
                      const SizedBox(width: 14),
                      Expanded(child: Text(label, style: TextStyle(color: isChecked ? Colors.white : Colors.grey[400], fontWeight: FontWeight.w600, fontSize: 15))),
                      Text("\$${price.toStringAsFixed(0)}/mo", style: TextStyle(color: isChecked ? const Color(0xFFFFD700) : Colors.grey[600], fontWeight: FontWeight.bold, fontSize: 14)),
                    ],
                  ),
                ),
              ),
            );
          }),

          const SizedBox(height: 20),

          // Live pricing summary
          if (_selectedDojos.isNotEmpty) ...[
            AnimatedContainer(
              duration: const Duration(milliseconds: 300),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A1A),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: isAllAccess ? const Color(0xFFFFD700) : Colors.white24),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (isAllAccess) ...[
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(colors: [Color(0xFFFFD700), Color(0xFFE8D5A3)]),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: const Text("ALL-ACCESS BUNDLE", style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold, fontSize: 12, letterSpacing: 1)),
                    ),
                    const SizedBox(height: 12),
                  ],
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text("Dojos selected", style: TextStyle(color: Colors.grey[400], fontSize: 13)),
                      Text("${_selectedDojos.length} of ${_dojoPrices.length}", style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (_selectedDojos.length >= 2) ...[
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text("A la carte total", style: TextStyle(color: Colors.grey[500], fontSize: 13)),
                        Text("\$${baseTotal.toStringAsFixed(2)}/mo", style: TextStyle(color: Colors.grey[500], fontSize: 13, decoration: TextDecoration.lineThrough)),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text("Discount", style: TextStyle(color: Colors.green[400], fontSize: 13)),
                        Text("$discount% off", style: TextStyle(color: Colors.green[400], fontWeight: FontWeight.bold, fontSize: 13)),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text("You save", style: TextStyle(color: Colors.green[300], fontSize: 13)),
                        Text("\$${aLaCarteSavings.toStringAsFixed(2)}/mo", style: TextStyle(color: Colors.green[300], fontWeight: FontWeight.bold, fontSize: 13)),
                      ],
                    ),
                  ],
                  const Divider(color: Colors.white12, height: 20),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text("Monthly total", style: TextStyle(color: Color(0xFFFFD700), fontWeight: FontWeight.bold, fontSize: 15)),
                      Text("\$${finalPrice.toStringAsFixed(2)}/mo", style: const TextStyle(color: Color(0xFFFFD700), fontWeight: FontWeight.bold, fontSize: 18)),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),
          ],

          // Included features
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.03),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text("INCLUDED WITH EVERY PLAN", style: TextStyle(color: Colors.grey[500], fontFamily: 'Courier', fontSize: 11, letterSpacing: 1)),
                const SizedBox(height: 8),
                ...["Clients Tab", "Schedule", "Insights", "Briefings", "Classroom"].map((f) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(children: [
                    const Icon(Icons.check, color: Colors.tealAccent, size: 14),
                    const SizedBox(width: 8),
                    Text(f, style: const TextStyle(color: Colors.white54, fontSize: 12)),
                  ]),
                )),
              ],
            ),
          ),
          const SizedBox(height: 12),

          // Subscription terms note
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFFFD700).withOpacity(0.08),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.3)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.info_outline, color: Color(0xFFFFD700), size: 18),
                    const SizedBox(width: 10),
                    Expanded(child: Text("SUBSCRIPTION TERMS", style: TextStyle(color: const Color(0xFFFFD700).withOpacity(0.9), fontSize: 12, fontWeight: FontWeight.bold))),
                  ],
                ),
                const SizedBox(height: 8),
                Padding(
                  padding: const EdgeInsets.only(left: 28),
                  child: Text(
                    "Each DOJO is a 12-month subscription term. "
                    "30-day cancellation notice required. "
                    "You can manage subscriptions in the Financials tab after registration.",
                    style: TextStyle(color: Colors.grey[500], fontSize: 11, height: 1.4),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _selectedDojos.isNotEmpty ? () => setState(() => _step = 2) : null,
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFFFD700),
                disabledBackgroundColor: Colors.grey[800],
                minimumSize: const Size(double.infinity, 50),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              child: Text(
                _selectedDojos.isEmpty ? "SELECT AT LEAST 1 DOJO" : "CONTINUE",
                style: TextStyle(color: _selectedDojos.isEmpty ? Colors.grey : Colors.black, fontWeight: FontWeight.bold, letterSpacing: 1.5),
              ),
            ),
          ),
        ],
      ),
    );
  }


  Widget _buildForm() {
    return Theme(
      data: ThemeData.dark().copyWith(
        inputDecorationTheme: InputDecorationTheme(
          labelStyle: const TextStyle(color: Colors.white70),
          hintStyle: const TextStyle(color: Colors.white38),
          prefixIconColor: Colors.white54,
          enabledBorder: const OutlineInputBorder(borderSide: BorderSide(color: Colors.white24)),
          focusedBorder: const OutlineInputBorder(borderSide: BorderSide(color: Colors.blueAccent)),
        ),
        textTheme: const TextTheme(bodyMedium: TextStyle(color: Colors.white)),
        textSelectionTheme: const TextSelectionThemeData(
          cursorColor: Colors.blueAccent,
          selectionColor: Colors.blueAccent,
          selectionHandleColor: Colors.blueAccent,
        ),
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. STANDARD FIELDS
            TextField(controller: _nameCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "Full Name", prefixIcon: Icon(Icons.person))),
            const SizedBox(height: 10),
            
            GestureDetector(
              onTap: () => _selectDate(context),
              child: AbsorbPointer(child: TextField(style: const TextStyle(color: Colors.white), decoration: InputDecoration(
                labelText: _dob == null ? "DOB (Required)" : "DOB: ${DateFormat('yyyy-MM-dd').format(_dob!)}", 
                suffixIcon: const Icon(Icons.calendar_today)
              ))),
            ),
            const SizedBox(height: 20),

            // 2. FAMILY LINK SECTION (The Missing Piece)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                border: Border.all(color: _isDependent ? Colors.blue : Colors.white12),
                borderRadius: BorderRadius.circular(10),
                color: Colors.white.withOpacity(0.05)
              ),
              child: Column(
                children: [
                  SwitchListTile(
                    title: const Text("Is this a Child/Dependent Account?", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                    subtitle: const Text("Link this account to a Head of Household", style: TextStyle(color: Colors.grey, fontSize: 12)),
                    value: _isDependent,
                    activeColor: Colors.blue,
                    onChanged: (val) => setState(() => _isDependent = val),
                  ),
                  
                  if (_isDependent) ...[
                    const SizedBox(height: 10),
                    TextField(
                      controller: _parentCtrl,
                      style: const TextStyle(color: Colors.white),
                      decoration: const InputDecoration(
                        labelText: "Head of Household IDENTITY", 
                        hintText: "Enter Parent's Username",
                        prefixIcon: Icon(Icons.family_restroom, color: Colors.blue)
                      )
                    ),
                  ]
                ],
              ),
            ),
            const SizedBox(height: 20),

            // 2.4 DISCOUNT CODE (Coaches only — hidden on iOS per Apple Guideline 3.1.1)
            if (_effectiveRole == "COACH" && !isNativeIOS) ...[
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  border: Border.all(color: _discountValidated ? const Color(0xFF22C55E) : const Color(0xFFC9A962).withOpacity(0.3)),
                  borderRadius: BorderRadius.circular(12),
                  color: const Color(0xFF1A1A1A),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.local_offer, color: Color(0xFFC9A962), size: 20),
                        const SizedBox(width: 8),
                        const Text("DISCOUNT CODE", style: TextStyle(color: Color(0xFFC9A962), fontWeight: FontWeight.bold, fontFamily: 'Courier', fontSize: 13, letterSpacing: 1.5)),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      "Have a promo, school, or corporate discount code?",
                      style: TextStyle(color: Colors.grey[500], fontSize: 12),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _discountCodeCtrl,
                            style: const TextStyle(color: Colors.white, fontFamily: 'Courier', letterSpacing: 1),
                            textCapitalization: TextCapitalization.characters,
                            decoration: InputDecoration(
                              labelText: "Discount Code (optional)",
                              labelStyle: TextStyle(color: Colors.grey[600], fontSize: 13),
                              filled: true,
                              fillColor: const Color(0xFF111111),
                              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.white12)),
                              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: Colors.white12)),
                              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: Color(0xFFC9A962))),
                              contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                            ),
                            onChanged: (_) {
                              if (_discountValidated) setState(() { _discountValidated = false; _discountDetails = {}; _discountError = null; });
                            },
                          ),
                        ),
                        const SizedBox(width: 10),
                        SizedBox(
                          height: 48,
                          child: ElevatedButton(
                            onPressed: _discountValidating ? null : _verifyDiscountCode,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: const Color(0xFFC9A962),
                              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                            ),
                            child: _discountValidating
                                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                                : const Text("APPLY", style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold, letterSpacing: 1)),
                          ),
                        ),
                      ],
                    ),
                    if (_discountValidated && _discountDetails.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: const Color(0xFF22C55E).withOpacity(0.1),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: const Color(0xFF22C55E).withOpacity(0.3)),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.check_circle, color: Color(0xFF22C55E), size: 18),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                _discountDetails['discount_type'] == 'pays_full'
                                    ? "${_discountDetails['name']} — Fully sponsored"
                                    : _discountDetails['discount_type'] == 'percent'
                                        ? "${_discountDetails['name']} — ${_discountDetails['discount_value']}% off"
                                        : "${_discountDetails['name']} — \$${((_discountDetails['discount_value'] ?? 0) / 100).toStringAsFixed(2)} off",
                                style: const TextStyle(color: Color(0xFF22C55E), fontSize: 13, fontWeight: FontWeight.w600),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                    if (_discountError != null) ...[
                      const SizedBox(height: 10),
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: const Color(0xFFEF4444).withOpacity(0.1),
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.3)),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.error_outline, color: Color(0xFFEF4444), size: 18),
                            const SizedBox(width: 8),
                            Expanded(child: Text(_discountError!, style: const TextStyle(color: Color(0xFFEF4444), fontSize: 13))),
                          ],
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 20),
            ],

            // 2.5 CONTACT INFO (Coaches - both required; Clients - at least one)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.4)),
                borderRadius: BorderRadius.circular(12),
                color: const Color(0xFF4ECDC4).withOpacity(0.05),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.contact_mail, color: Color(0xFF4ECDC4), size: 20),
                      const SizedBox(width: 8),
                      const Text("CONTACT INFORMATION", style: TextStyle(color: Color(0xFF4ECDC4), fontWeight: FontWeight.bold, fontFamily: 'Courier', fontSize: 13)),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _effectiveRole == "COACH"
                        ? "Required for identity verification and communication."
                        : "Provide an email or phone number for account recovery.",
                    style: TextStyle(color: Colors.grey[500], fontSize: 12),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _emailCtrl,
                    keyboardType: TextInputType.emailAddress,
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      labelText: _effectiveRole == "COACH" ? "Email Address *" : "Email Address",
                      prefixIcon: const Icon(Icons.email),
                      suffixIcon: _emailCtrl.text.isNotEmpty && _emailCtrl.text.contains('@') && _emailCtrl.text.contains('.')
                          ? const Icon(Icons.check_circle, color: Color(0xFF4ECDC4), size: 20)
                          : null,
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _phoneCtrl,
                    keyboardType: TextInputType.phone,
                    style: const TextStyle(color: Colors.white),
                    decoration: InputDecoration(
                      labelText: _effectiveRole == "COACH" ? "Phone Number *" : "Phone Number",
                      hintText: "(XXX) XXX-XXXX",
                      prefixIcon: const Icon(Icons.phone),
                      suffixIcon: _phoneCtrl.text.replaceAll(RegExp(r'[^0-9]'), '').length >= 10
                          ? const Icon(Icons.check_circle, color: Color(0xFF4ECDC4), size: 20)
                          : null,
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: _timezoneCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: "Time zone (IANA) *",
                      hintText: "e.g. America/Los_Angeles",
                      prefixIcon: Icon(Icons.schedule),
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),

            // 3. W-9 TAX FORM (Coaches only)
            if (_effectiveRole == "COACH") ...[
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  border: Border.all(color: const Color(0xFFFFD700).withOpacity(0.4)),
                  borderRadius: BorderRadius.circular(12),
                  color: const Color(0xFFFFD700).withOpacity(0.05),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.description, color: Color(0xFFFFD700), size: 20),
                        const SizedBox(width: 8),
                        const Text("W-9 TAX INFORMATION", style: TextStyle(color: Color(0xFFFFD700), fontWeight: FontWeight.bold, fontFamily: 'Courier', fontSize: 13)),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text("As an independent contractor (1099), we need your tax info.", style: TextStyle(color: Colors.grey[500], fontSize: 12)),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _w9LegalNameCtrl,
                      style: const TextStyle(color: Colors.white),
                      decoration: const InputDecoration(labelText: "Legal Name (as on tax return)", prefixIcon: Icon(Icons.badge)),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _w9BusinessNameCtrl,
                      style: const TextStyle(color: Colors.white),
                      decoration: const InputDecoration(labelText: "Business Name (if different)", prefixIcon: Icon(Icons.business)),
                    ),
                    const SizedBox(height: 12),
                    const Text("Tax Classification", style: TextStyle(color: Colors.white70, fontSize: 12)),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      children: [
                        _buildRegTaxChip('individual', 'Individual / Sole Proprietor'),
                        _buildRegTaxChip('llc', 'LLC'),
                        _buildRegTaxChip('corporation', 'Corporation'),
                        _buildRegTaxChip('partnership', 'Partnership'),
                      ],
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _w9StreetCtrl,
                      style: const TextStyle(color: Colors.white),
                      decoration: const InputDecoration(labelText: "Street Address", prefixIcon: Icon(Icons.home)),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(flex: 3, child: TextField(controller: _w9CityCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "City"))),
                        const SizedBox(width: 8),
                        Expanded(flex: 1, child: TextField(controller: _w9StateCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "State"))),
                        const SizedBox(width: 8),
                        Expanded(flex: 2, child: TextField(controller: _w9ZipCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "ZIP"))),
                      ],
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _w9TinCtrl,
                      obscureText: true,
                      keyboardType: TextInputType.number,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        labelText: "Taxpayer ID (SSN or EIN) *",
                        prefixIcon: const Icon(Icons.lock),
                        hintText: "XXX-XX-XXXX",
                        suffixIcon: _w9TinCtrl.text.trim().isEmpty
                            ? null
                            : _validateTin(_w9TinCtrl.text.trim()) == null
                                ? const Icon(Icons.check_circle, color: Color(0xFF4ECDC4), size: 20)
                                : Tooltip(
                                    message: _validateTin(_w9TinCtrl.text.trim()) ?? '',
                                    child: const Icon(Icons.error, color: Colors.redAccent, size: 20),
                                  ),
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                    const SizedBox(height: 12),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Checkbox(
                          value: _w9Certified,
                          onChanged: (v) => setState(() => _w9Certified = v ?? false),
                          activeColor: const Color(0xFFFFD700),
                        ),
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.only(top: 12),
                            child: Text(
                              "Under penalties of perjury, I certify that the information provided is correct and I am a U.S. person.",
                              style: TextStyle(color: Colors.grey[400], fontSize: 11),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: _w9SignatureCtrl,
                      style: const TextStyle(color: Colors.white),
                      decoration: const InputDecoration(labelText: "Electronic Signature (type full name)", prefixIcon: Icon(Icons.draw)),
                    ),
                    const SizedBox(height: 16),
                    // W-9 Document Upload
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.white12),
                        borderRadius: BorderRadius.circular(8),
                        color: Colors.white.withOpacity(0.03),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text("W-9 Documentation", style: TextStyle(color: Colors.grey[400], fontSize: 12, fontWeight: FontWeight.bold)),
                          const SizedBox(height: 4),
                          Text(
                            "Upload a copy of your signed W-9 form to expedite verification. "
                            "Accepted formats: PDF, JPG, PNG.",
                            style: TextStyle(color: Colors.grey[600], fontSize: 11),
                          ),
                          const SizedBox(height: 10),
                          Row(
                            children: [
                              Expanded(
                                child: OutlinedButton.icon(
                                  onPressed: () async {
                                    try {
                                      final result = await FilePicker.platform.pickFiles(
                                        type: FileType.custom,
                                        allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png'],
                                        withData: true,
                                      );
                                      if (result != null && result.files.isNotEmpty) {
                                        final file = result.files.first;
                                        if (file.bytes != null) {
                                          setState(() {
                                            _w9DocFileName = file.name;
                                            _w9DocBytes = file.bytes;
                                            _w9DocBase64 = base64Encode(file.bytes!);
                                          });
                                        }
                                      }
                                    } catch (e) {
                                      ScaffoldMessenger.of(context).showSnackBar(
                                        SnackBar(content: Text("File pick error: $e")),
                                      );
                                    }
                                  },
                                  icon: const Icon(Icons.upload_file, size: 18),
                                  label: Text(
                                    _w9DocFileName ?? "Upload W-9 Document",
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  style: OutlinedButton.styleFrom(
                                    foregroundColor: const Color(0xFFFFD700),
                                    side: BorderSide(color: const Color(0xFFFFD700).withOpacity(0.5)),
                                  ),
                                ),
                              ),
                              if (_w9DocFileName != null) ...[
                                const SizedBox(width: 8),
                                IconButton(
                                  icon: const Icon(Icons.close, color: Colors.redAccent, size: 18),
                                  onPressed: () => setState(() {
                                    _w9DocFileName = null;
                                    _w9DocBase64 = null;
                                    _w9DocBytes = null;
                                  }),
                                ),
                              ],
                            ],
                          ),
                          if (_w9DocFileName != null) ...[
                            const SizedBox(height: 6),
                            Row(
                              children: [
                                const Icon(Icons.check_circle, color: Color(0xFF4ECDC4), size: 16),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: Text(
                                    _w9DocFileName!,
                                    style: const TextStyle(color: Color(0xFF4ECDC4), fontSize: 12),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
            ],

            // 4. CREDENTIALS
            TextField(controller: _userCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "Create Username", prefixIcon: Icon(Icons.alternate_email))),
            const SizedBox(height: 10),
            TextField(
              controller: _passCtrl,
              obscureText: _obscurePass,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: "Create Password",
                prefixIcon: const Icon(Icons.lock),
                suffixIcon: IconButton(
                  icon: Icon(_obscurePass ? Icons.visibility_off : Icons.visibility, color: Colors.grey),
                  onPressed: () => setState(() => _obscurePass = !_obscurePass),
                ),
              ),
            ),
            
            const SizedBox(height: 40),
            ElevatedButton(
              onPressed: _isRegistering
                  ? null
                  : (_isPaidTier ? _goToOrderReview : () => _submitRegistration()), 
              style: ElevatedButton.styleFrom(
                backgroundColor: _isRegistering ? Colors.grey : Colors.blueAccent,
                minimumSize: const Size(double.infinity, 50),
              ),
              child: _isRegistering
                ? const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
                    SizedBox(width: 12),
                    Text("CREATING ACCOUNT...", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                  ])
                : Text(_isPaidTier ? "REVIEW ORDER" : "CREATE ACCOUNT",
                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold))
            )
          ],
        ),
      ), 
    );
  }

  void _goToOrderReview() {
    if (_nameCtrl.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Full Name is required")));
      return;
    }
    if (_dob == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Date of Birth is required")));
      return;
    }
    if (_calculateAge(_dob!) < 18) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Error: Primary Account Holder must be 18+.")));
      return;
    }
    if (_userCtrl.text.trim().isEmpty || _passCtrl.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Username and Password are required")));
      return;
    }
    if (_effectiveRole == "COACH") {
      if (_emailCtrl.text.trim().isEmpty || !_emailCtrl.text.contains('@')) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("A valid email is required")));
        return;
      }
      final phoneDigits = _phoneCtrl.text.replaceAll(RegExp(r'[^0-9]'), '');
      if (phoneDigits.length < 10) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("A valid phone number is required")));
        return;
      }
    }
    setState(() { _step = 3; _stripeError = null; });
  }

  Widget _buildOrderReview() {
    final role = _effectiveRole;
    final isCoach = role == 'COACH';
    String planName;
    double monthlyTotal;

    if (isCoach) {
      planName = '${_selectedDojos.length} DOJO${_selectedDojos.length > 1 ? 's' : ''}';
      monthlyTotal = _calculateDojoPrice();
    } else {
      planName = _selectedTier == 'TOP_TIER' ? 'Sovereign Circle' : 'Inner Chamber';
      monthlyTotal = _selectedTier == 'TOP_TIER' ? 149.0 : 49.0;
    }

    final discountPct = _discountValidated ? (_discountDetails['discount_pct'] ?? 0) : 0;
    final discountedTotal = discountPct > 0
        ? double.parse((monthlyTotal * (1 - discountPct / 100)).toStringAsFixed(2))
        : monthlyTotal;

    return SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('ORDER SUMMARY', style: TextStyle(color: Color(0xFFC9A962), fontSize: 18,
              fontWeight: FontWeight.bold, fontFamily: 'Courier', letterSpacing: 2)),
          const SizedBox(height: 20),
          _reviewRow('Name', _nameCtrl.text.trim()),
          _reviewRow('Username', _userCtrl.text.trim()),
          _reviewRow('Role', role),
          const Divider(color: Colors.white24, height: 32),
          _reviewRow('Plan', planName),
          if (isCoach) ...[
            for (final d in _selectedDojos)
              _reviewRow('  ${_dojoLabels[d] ?? d}', '\$${_dojoPrices[d]?.toStringAsFixed(0) ?? "?"}/mo'),
          ],
          if (discountPct > 0) ...[
            _reviewRow('Discount', '-$discountPct%', valueColor: const Color(0xFF22C55E)),
            _reviewRow('Monthly Total', '\$${discountedTotal.toStringAsFixed(2)}',
                valueColor: const Color(0xFFC9A962)),
          ] else
            _reviewRow('Monthly Total', '\$${monthlyTotal.toStringAsFixed(2)}',
                valueColor: const Color(0xFFC9A962)),
          if (_emailCtrl.text.trim().isNotEmpty)
            _reviewRow('Receipt Email', _emailCtrl.text.trim()),
          const Divider(color: Colors.white24, height: 32),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFF1A1A2E),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: Colors.white12),
            ),
            child: const Row(
              children: [
                Icon(Icons.lock, color: Color(0xFFC9A962), size: 18),
                SizedBox(width: 8),
                Expanded(child: Text(
                  'You\'ll complete payment on our secure checkout page. '
                  'Your account is created once payment confirms.',
                  style: TextStyle(color: Colors.white60, fontSize: 12),
                )),
              ],
            ),
          ),
          if (_stripeError != null) ...[
            const SizedBox(height: 12),
            Text(_stripeError!, style: const TextStyle(color: Colors.redAccent, fontSize: 13)),
          ],
          const SizedBox(height: 24),
          ElevatedButton(
            onPressed: _isLaunchingStripe ? null : _launchStripeCheckout,
            style: ElevatedButton.styleFrom(
              backgroundColor: _isLaunchingStripe ? Colors.grey : const Color(0xFFC9A962),
              minimumSize: const Size(double.infinity, 50),
            ),
            child: _isLaunchingStripe
              ? const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black)),
                  SizedBox(width: 12),
                  Text('PREPARING PAYMENT...', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
                ])
              : const Text('CONTINUE TO PAYMENT', style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold)),
          ),
          const SizedBox(height: 12),
          Center(
            child: TextButton(
              onPressed: _isLaunchingStripe ? null : () => setState(() => _step = 2),
              child: const Text('← Back to Edit', style: TextStyle(color: Colors.white54)),
            ),
          ),
        ],
      ),
    );
  }

  Widget _reviewRow(String label, String value, {Color? valueColor}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.white60, fontSize: 14)),
          Text(value, style: TextStyle(color: valueColor ?? Colors.white, fontSize: 14, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  Future<void> _launchStripeCheckout() async {
    if (_isLaunchingStripe) return;
    setState(() { _isLaunchingStripe = true; _stripeError = null; });

    try {
      final base = AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');
      final uri = Uri.parse('$base/api/registration/checkout/prepare');

      final body = <String, dynamic>{
        'role': _effectiveRole,
        'username': _userCtrl.text.trim(),
        'password': _passCtrl.text.trim(),
        'email': _emailCtrl.text.trim(),
        'name': _nameCtrl.text.trim(),
        'dob': _dob != null ? DateFormat('yyyy-MM-dd').format(_dob!) : '',
        'phone': _phoneCtrl.text.trim(),
      };

      if (_effectiveRole == 'CLIENT') {
        body['tier'] = _selectedTier;
      } else {
        body['selected_dojos'] = _selectedDojos;
      }

      if (_discountValidated && _discountCodeCtrl.text.trim().isNotEmpty) {
        body['discount_code'] = _discountCodeCtrl.text.trim();
      }

      if (_coachInviteToken != null) {
        body['coach_invite_token'] = _coachInviteToken;
      }

      if (_isDependent && _parentCtrl.text.trim().isNotEmpty) {
        body['parent_username'] = _parentCtrl.text.trim();
      }

      if (_effectiveRole == 'COACH' && _w9LegalNameCtrl.text.trim().isNotEmpty) {
        body['w9_data'] = {
          'legal_name': _w9LegalNameCtrl.text.trim(),
          'business_name': _w9BusinessNameCtrl.text.trim(),
          'tax_classification': _w9TaxClass,
          'street': _w9StreetCtrl.text.trim(),
          'city': _w9CityCtrl.text.trim(),
          'state': _w9StateCtrl.text.trim(),
          'zip': _w9ZipCtrl.text.trim(),
          'tin': _w9TinCtrl.text.trim(),
          'certified': _w9Certified,
          'signature': _w9SignatureCtrl.text.trim(),
          'signed_date': DateTime.now().toIso8601String(),
        };
      }

      final resp = await http.post(uri,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      ).timeout(const Duration(seconds: 15));

      if (!mounted) return;

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);

        // Dependent path: backend created the user under the parent's
        // Sovereign Circle plan with no Stripe charge. Auto-login.
        if (data['dependent_created'] == true) {
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
              content: Text('Dependent account linked under head-of-household. Logging in...'),
            ));
          }
          await _loginAfterDependentCreate();
          return;
        }

        final checkoutUrl = data['checkout_url'] as String?;
        if (checkoutUrl != null && checkoutUrl.isNotEmpty) {
          final launched = await launchCheckoutUrl(checkoutUrl);
          if (!launched && mounted) {
            setState(() => _stripeError = 'Could not open payment page. Please try again.');
          }
        } else {
          setState(() => _stripeError = 'No checkout URL received.');
        }
      } else {
        final errBody = jsonDecode(resp.body);
        setState(() => _stripeError = errBody['detail'] ?? 'Payment preparation failed (${resp.statusCode})');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _stripeError = 'Connection error: ${e.toString().split('\n').first}');
    } finally {
      if (mounted) setState(() => _isLaunchingStripe = false);
    }
  }

  /// Called after `/checkout/prepare` returns `dependent_created: true`.
  /// The user already exists in PostgreSQL under the parent's family.
  /// Open a websocket and send a `login_request` directly — skip
  /// `register_request` because the dependent is already provisioned.
  Future<void> _loginAfterDependentCreate() async {
    final username = _userCtrl.text.trim();
    final password = _passCtrl.text.trim();
    final role = _effectiveRole;

    final loginSocket = WebSocketChannel.connect(Uri.parse(_endpoints[0]));
    Timer? loginTimeout;
    bool resolved = false;

    loginTimeout = Timer(const Duration(seconds: 30), () {
      if (resolved || !mounted) return;
      resolved = true;
      try { loginSocket.sink.close(); } catch (_) {}
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
        content: Text('Dependent created, but auto-login timed out. Please log in manually.'),
        backgroundColor: Colors.orange,
        duration: Duration(seconds: 6),
      ));
    });

    loginSocket.stream.listen((message) {
      if (resolved) return;
      try {
        final data = jsonDecode(message);
        if (data['type'] == 'login_success') {
          resolved = true;
          loginTimeout?.cancel();
          if (!mounted) return;
          _handleLoginSuccess(Map<String, dynamic>.from(data), loginSocket);
        } else if (data['type'] == 'error' || data['type'] == 'registration_failed') {
          resolved = true;
          loginTimeout?.cancel();
          try { loginSocket.sink.close(); } catch (_) {}
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Login after dependent create failed: ${data['message'] ?? 'unknown'}'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 6),
          ));
        }
      } catch (_) {}
    }, onError: (e) {
      if (resolved) return;
      resolved = true;
      loginTimeout?.cancel();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('Login connection error: $e'),
        backgroundColor: Colors.red,
      ));
    });

    loginSocket.sink.add(jsonEncode({
      'type': 'login_request',
      'username': username,
      'password': password,
      'expected_role': role,
    }));
  }
}

// =============================================================================
// MODULE 6: LEGAL ENGINE (FIXED STATE CLASSES)
// =============================================================================

class ReConsentScreen extends StatefulWidget {
  final String username, password;
  final Map<String, dynamic>? profile;
  final String? token;
  const ReConsentScreen({super.key, required this.username, required this.password, this.profile, this.token});
  @override
  State<ReConsentScreen> createState() => _ReConsentScreenState();
}

class _ReConsentScreenState extends State<ReConsentScreen> {
  bool _agreed = false;
  
  void _send() {
    final role = widget.profile?['role'] ?? 'CLIENT';
    final ws = WebSocketChannel.connect(Uri.parse(defaultWsUrl));
    bool loginDone = false;
    ws.stream.listen((message) {
      final data = jsonDecode(message);
      if (data['type'] == 'login_success' && !loginDone) {
        loginDone = true;
        Future.delayed(const Duration(milliseconds: 300), () {
          ws.sink.add(jsonEncode({"type": "accept_consent_update"}));
        });
      } else if (data['type'] == 'consent_updated') {
        final updatedProfile = data['profile'] as Map<String, dynamic>? ?? widget.profile ?? {};
        final tok = widget.token ?? '';
        final profileWithToken = {...updatedProfile, "token": tok};
        Widget nextScreen;
        if (role == 'ADMIN') {
          nextScreen = AdminDashboardScreen(currentUserProfile: profileWithToken, username: widget.username, password: widget.password);
        } else if (role == 'COACH') {
          nextScreen = CoachDashboardScreenV2(currentUserProfile: profileWithToken, username: widget.username, password: widget.password);
        } else {
          nextScreen = NeuralInterfaceV2(currentUserProfile: profileWithToken, username: widget.username, password: widget.password);
        }
        Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => nextScreen), (r) => false);
      } else if (data['type'] == 'login_failed') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(data['message']?.toString() ?? 'Login failed. Please try again.'),
            backgroundColor: Colors.red,
          ));
        }
      }
    });
    ws.sink.add(jsonEncode({
      "type": "login_request",
      "username": widget.username,
      "password": widget.password,
      "expected_role": role,
      "client_context": kIsWeb ? '${role.toLowerCase()}_web' : '${role.toLowerCase()}_mobile',
    }));
  }

  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF111111),
      appBar: AppBar(title: const Text("LEGAL UPDATE"), backgroundColor: Colors.amber, automaticallyImplyLeading: false),
      body: Padding(
        padding: const EdgeInsets.all(24), 
        child: SovereignCovenantDoc(
          consentGiven: _agreed, 
          onChanged: (v) => setState(() => _agreed = v!), 
          color: Colors.amber, 
          btnText: "I ACCEPT NEW TERMS", 
          onNext: _agreed ? _send : null
        )
      ),
    );
  }
}

// =============================================================================
// MODULE 6B: COACH ETHICS & CODE OF CONDUCT GATE
// =============================================================================

class CoachEthicsScreen extends StatefulWidget {
  final String username, password;
  final Map<String, dynamic>? profile;
  final String? token;
  const CoachEthicsScreen({super.key, required this.username, required this.password, this.profile, this.token});
  @override
  State<CoachEthicsScreen> createState() => _CoachEthicsScreenState();
}

class _CoachEthicsScreenState extends State<CoachEthicsScreen> {
  final List<bool> _checks = List.filled(6, false);
  bool _submitting = false;
  bool _allChecked = false;

  void _updateCheck(int idx, bool? val) {
    if (!mounted) return;
    setState(() {
      _checks[idx] = val ?? false;
      _allChecked = _checks.every((c) => c);
    });
  }

  void _submit() {
    if (_submitting || !_allChecked) return;
    setState(() => _submitting = true);

    final role = widget.profile?['role'] ?? 'COACH';
    final ws = WebSocketChannel.connect(Uri.parse(defaultWsUrl));
    bool done = false;
    bool loginDone = false;

    Future.delayed(const Duration(seconds: 30), () {
      if (!done && mounted) {
        setState(() => _submitting = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Request timed out. Please try again.')),
        );
      }
    });

    ws.stream.listen((message) {
      final data = jsonDecode(message);
      if (data['type'] == 'login_success' && !loginDone) {
        loginDone = true;
        Future.delayed(const Duration(milliseconds: 300), () {
          ws.sink.add(jsonEncode({"type": "accept_coach_ethics"}));
        });
      } else if (data['type'] == 'coach_ethics_updated') {
        done = true;
        final updatedProfile = data['profile'] as Map<String, dynamic>? ?? widget.profile ?? {};
        final tok = widget.token ?? '';
        final profileWithToken = {...updatedProfile, "token": tok};
        if (mounted) {
          Navigator.pushAndRemoveUntil(
            context,
            MaterialPageRoute(builder: (_) => CoachDashboardScreenV2(
              currentUserProfile: profileWithToken,
              username: widget.username,
              password: widget.password,
            )),
            (r) => false,
          );
        }
      } else if (data['type'] == 'login_failed') {
        done = true;
        if (mounted) {
          setState(() => _submitting = false);
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(data['message']?.toString() ?? 'Login failed. Please try again.'),
            backgroundColor: Colors.red,
          ));
        }
      }
    });

    ws.sink.add(jsonEncode({
      "type": "login_request",
      "username": widget.username,
      "password": widget.password,
      "expected_role": role,
      "client_context": kIsWeb ? '${role.toLowerCase()}_web' : '${role.toLowerCase()}_mobile',
    }));
  }

  Widget _sectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(top: 24, bottom: 8),
      child: Text(title,
        style: const TextStyle(color: Color(0xFFC9A962), fontSize: 18,
          fontWeight: FontWeight.bold, fontFamily: 'Cormorant Garamond')),
    );
  }

  Widget _bodyText(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text(text,
        style: const TextStyle(color: Color(0xFFCCCCCC), fontSize: 14, height: 1.6,
          fontFamily: 'DM Sans')),
    );
  }

  Widget _checkbox(int idx, String label) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 24, height: 24,
            child: Checkbox(
              value: _checks[idx],
              onChanged: (v) => _updateCheck(idx, v),
              activeColor: const Color(0xFFC9A962),
              checkColor: const Color(0xFF050505),
              side: const BorderSide(color: Color(0xFF8B7355)),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: GestureDetector(
              onTap: () => _updateCheck(idx, !_checks[idx]),
              child: Text(label,
                style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 13, height: 1.5)),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        title: const Text('COACH ETHICS & CODE OF CONDUCT',
          style: TextStyle(fontFamily: 'Cormorant Garamond', fontSize: 18, letterSpacing: 1.5)),
        backgroundColor: const Color(0xFF111111),
        foregroundColor: const Color(0xFFC9A962),
        automaticallyImplyLeading: false,
      ),
      body: Column(
        children: [
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _sectionHeader('A. Professional Ethics'),
                  _bodyText(
                    'As a coach utilizing the Sovereign Sanctuary platform, I acknowledge that I am '
                    'independently responsible for maintaining ethical standards consistent with my '
                    'professional certification body (e.g., ICF, CCE, NBHWC, or equivalent). I understand '
                    'that Sovereign Sanctuary does not grant, validate, or replace any professional credential.'
                  ),
                  _checkbox(0,
                    'I confirm I am bound by the ethics and code of conduct of my professional '
                    'certification body and will maintain active compliance.'
                  ),
                  _checkbox(1,
                    'I understand that my coaching credentials are independent of Sovereign Sanctuary '
                    'and I am solely responsible for maintaining them.'
                  ),

                  _sectionHeader('B. Sovereign Sanctuary Code of Conduct'),
                  _bodyText(
                    'All client and coachee data encountered on this platform is strictly confidential. '
                    'You must never extract, download, or transfer platform-generated data including session '
                    'transcripts, AI insights, coherence metrics, or progress reports.\n\n'
                    'Clients or coachees who wish to share their history with a departing coach must do so '
                    'manually and independently. Sovereign Sanctuary will not facilitate or assist in any '
                    'data transfer to departing coaches.\n\n'
                    'You agree to maintain professional boundaries in all platform interactions.'
                  ),
                  _checkbox(2,
                    'I accept Sovereign Sanctuary\'s Code of Conduct and will uphold confidentiality, '
                    'data protection, and professional boundaries.'
                  ),

                  _sectionHeader('C. Fraud & Intellectual Property Protection'),
                  _bodyText(
                    'Any fraudulent activity against the platform, its users, or coachees will result in '
                    'immediate account freeze pending investigation. During a fraud investigation, the coach '
                    'waives the right to object to the account freeze and all account data will be inaccessible.\n\n'
                    'Coaches may retain their client relationships but NO platform data, session history, '
                    'AI-generated insights, or analytical reports may be taken.\n\n'
                    'The platform\'s algorithms, data structures, therapeutic methodologies, coherence formulas, '
                    'and AI training systems are patent-protected intellectual property owned by Sovereign '
                    'Sanctuary. Unauthorized disclosure or reproduction of proprietary information constitutes '
                    'IP infringement and is actionable under applicable law.'
                  ),
                  _checkbox(3,
                    'I understand that fraudulent activity will result in immediate account freeze, '
                    'and I waive the right to contest the freeze during investigation.'
                  ),
                  _checkbox(4,
                    'I acknowledge that all platform algorithms, AI systems, and therapeutic methodologies '
                    'are proprietary intellectual property protected by patent, and I will not disclose, '
                    'reproduce, or misappropriate them.'
                  ),

                  _sectionHeader('D. Final Acknowledgment'),
                  _checkbox(5,
                    'I have read, understood, and agree to all sections above. I accept both my professional '
                    'ethical obligations and Sovereign Sanctuary\'s Code of Conduct, Fraud Policy, and '
                    'IP Protection terms.'
                  ),
                  const SizedBox(height: 24),
                ],
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: const BoxDecoration(
              color: Color(0xFF111111),
              border: Border(top: BorderSide(color: Color(0xFF333333))),
            ),
            child: SizedBox(
              width: double.infinity,
              height: 52,
              child: ElevatedButton(
                onPressed: (_allChecked && !_submitting) ? _submit : null,
                style: ElevatedButton.styleFrom(
                  backgroundColor: _allChecked ? const Color(0xFFC9A962) : const Color(0xFF333333),
                  foregroundColor: const Color(0xFF050505),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                ),
                child: _submitting
                  ? const SizedBox(width: 24, height: 24,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Color(0xFF050505)))
                  : Text(_allChecked ? 'ACCEPT & CONTINUE' : 'REVIEW ALL SECTIONS',
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16,
                        letterSpacing: 1.2)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class EmancipationScreen extends StatefulWidget {
  final String username, password;
  const EmancipationScreen({super.key, required this.username, required this.password});
  @override
  State<EmancipationScreen> createState() => _EmancipationScreenState();
}

class _EmancipationScreenState extends State<EmancipationScreen> {
  bool _agreed = false;
  
  void _send() {
    final ws = WebSocketChannel.connect(Uri.parse(defaultWsUrl));
    ws.stream.listen((message) { 
      if (jsonDecode(message)['type'] == 'login_success') {
        Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LobbyScreen()), (r) => false); 
      }
    });
    ws.sink.add(jsonEncode({
      "type": "submit_emancipation", 
      "username": widget.username, 
      "password": widget.password
    }));
  }

  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF111111),
      appBar: AppBar(title: const Text("HAPPY BIRTHDAY"), backgroundColor: Colors.amber, automaticallyImplyLeading: false),
      body: Padding(
        padding: const EdgeInsets.all(24), 
        child: SovereignCovenantDoc(
          consentGiven: _agreed, 
          onChanged: (v) => setState(() => _agreed = v!), 
          color: Colors.amber, 
          btnText: "I CLAIM SOVEREIGNTY", 
          onNext: _agreed ? _send : null
        )
      ),
    );
  }
}

class SovereignCovenantDoc extends StatelessWidget {
  final bool consentGiven;
  final ValueChanged<bool?> onChanged;
  final Color color;
  final String? btnText;
  final VoidCallback? onNext;

  const SovereignCovenantDoc({super.key, required this.consentGiven, required this.onChanged, required this.color, this.btnText, this.onNext});

  
  // ===========================================================================
  // PRIVATE COACHING UI



  @override
  Widget build(BuildContext context) {
    return Column(children: [
      const Text("SOVEREIGN COVENANT", style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      const SizedBox(height: 10),
      Expanded(
        child: Container(
          padding: const EdgeInsets.all(16), 
          decoration: BoxDecoration(border: Border.all(color: Colors.white24), color: Colors.white.withOpacity(0.05)),
          child: SingleChildScrollView(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [
              _Header("1. PRIVATE MEMBERSHIP (1st AMENDMENT)"),
              Text("You acknowledge this is a Private Membership Association operating under the First Amendment. Interactions are private exercises of speech.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("2. AI IDENTITY & LICENSING (CA AB 489)"),
              Text("DISCLOSURE: 'Little Nate' is an AI, NOT a human. Neither the AI nor the App holds a medical license. Do not form a 'reasonable belief' that you are interacting with a licensed healthcare professional.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("3. AUTOMATED PROFILING CONSENT"),
              Text("This system uses 'Automated Profiling'. By proceeding, you explicitly WAIVE any state-level rights (e.g., IN, KY, RI) to 'opt-out' of profiling, as it is the core function of this service.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("4. AGE & FAMILY ACCOUNTS (CA SB 243)"),
              Text("You affirm you are 18+ years of age. Minors are prohibited from creating primary accounts. Parents must create the account and add minors as dependents under strict supervision.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("5. TEXAS 'TRAIGA' DISCLOSURE"),
              Text("Pursuant to Texas law: This practitioner uses Generative AI in the formulation of guidance plans.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("6. CRISIS PROTOCOL"),
              Text("STOP: If you are in crisis:\nâ€¢ Call 988 (Suicide & Crisis Lifeline)\nâ€¢ Go to an Emergency Room immediately.", style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold)),
              SizedBox(height: 15),
              
              _Header("7. ZERO TOLERANCE POLICY"),
              Text("Immediate termination for: Pornography, Solicitation, or Illegal Acts.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("8. PLATFORM IMMUNITY"),
              Text("Sovereign Sanctuary is a Technology Provider, not a Clinic. Coaches are Independent Practitioners. You look solely to the Coach for claims arising from live sessions.", style: TextStyle(color: Colors.amber)),
              SizedBox(height: 15),
              
              _Header("9. BIOMETRIC DATA & AI DATA SHARING"),
              Text("1. VIDEO & VOICE: You explicitly consent to the AI analysis of your Voice (Voiceprint) AND Facial Geometry (Video Biometrics).\n2. AI DATA SHARING: Your text messages and voice transcriptions are sent to Microsoft Azure OpenAI Service (a third-party AI provider) to generate AI companion responses. Your data is NOT used to train their AI models. See our Privacy Policy Section 13a for full details.\n3. DATA SENT: Conversation text, session context, and anonymized emotional metrics. PII (name, email, phone) is stripped before transmission.\n4. DATA NOT SENT: Raw audio/video, passwords, payment information.\n5. SOVEREIGNTY: You retain the 'Right to Delete.' You may revoke AI data consent at any time via Settings.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("10. YOUR RECORDS ARE YOUR RESPONSIBILITY"),
              Text("Sovereign Sanctuary is NOT the custodian of your life story. Conversation history and session data has a limited time frame of existence and may be summarized, aged out, or removed during normal operation. If any insight, reflection, or information from your interactions is important to you, it is YOUR responsibility to save and preserve it outside the platform. Use the Data Export feature in Settings regularly. We make no guarantee that any specific conversation or AI-generated insight will remain available indefinitely.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("11. HOLD HARMLESS WAIVER"),
              Text("You voluntarily agree to hold the Developers harmless from any claims arising from data breaches, Coach interactions, or AI outputs.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("12. DISPUTE RESOLUTION"),
              Text("BINDING ARBITRATION: You agree that any disputes shall be resolved by binding individual arbitration. You explicitly WAIVE your right to a jury trial or to participate in any CLASS ACTION.", style: TextStyle(color: Colors.white70, fontWeight: FontWeight.bold)),
              SizedBox(height: 20),
              _Header("FULL LEGAL AGREEMENT"),
              Text("This consent summary covers the key points. The complete Terms of Use, Privacy Policy, Therapeutic Setting Waiver, Patent & Proprietary Technology Notice, and Dispute Resolution agreement (v13.0_2026) is available in Settings > Legal & Privacy after you log in.", style: TextStyle(color: Colors.amber, fontSize: 12)),
            ]),
          ),
        ),
      ),
      CheckboxListTile(
        title: const Text("I AM 18+, WAIVE CLASS ACTION RIGHTS & CONSENT", style: TextStyle(fontSize: 11, color: Colors.white)), 
        value: consentGiven, 
        activeColor: color, 
        onChanged: onChanged,
        controlAffinity: ListTileControlAffinity.leading,
        contentPadding: EdgeInsets.zero,
      ),
      if (btnText != null)
        ElevatedButton(
          onPressed: onNext, 
          style: ElevatedButton.styleFrom(backgroundColor: consentGiven ? color : Colors.grey, minimumSize: const Size(double.infinity, 50)), 
          child: Text(btnText!, style: const TextStyle(color: Colors.black))
        )
    ]);
  }
}

class _Header extends StatelessWidget {
  final String text; const _Header(this.text);
  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.only(bottom: 5), child: Text(text, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)));
}


// SCHEDULE-SHARED-WS: lobby hands off authenticated `/ws`; broadcast inbound so ClientScheduleScreen never opens a second login socket.
// FIX-G' (HUB-OWNS-RAW-STREAM): WebSocketChannel.stream is single-subscription
// (web_socket_channel ^2.4.0 → StreamChannelController default ctor). Hub is the
// SOLE owner of `ch.stream.listen`. All consumers (Lobby, NeuralInterface,
// Schedule) must subscribe via `inbound`/`errors`/`done` (broadcast).
class _ClientWsHub {
  static WebSocketChannel? channel;
  static StreamSubscription<dynamic>? _hubPipe;
  static final StreamController<dynamic> _hubIn = StreamController<dynamic>.broadcast();
  static final StreamController<Object> _hubErr = StreamController<Object>.broadcast();
  static final StreamController<void> _hubDone = StreamController<void>.broadcast();
  static Stream<dynamic> get inbound => _hubIn.stream;
  static Stream<Object> get errors => _hubErr.stream;
  static Stream<void> get done => _hubDone.stream;
  static void attach(WebSocketChannel ch) {
    channel = ch;
    _hubPipe?.cancel();
    _hubPipe = ch.stream.listen(
      (m) { if (!_hubIn.isClosed) _hubIn.add(m); },
      onError: (e) { if (!_hubErr.isClosed) _hubErr.add(e is Object ? e : Object()); },
      onDone: () { channel = null; if (!_hubDone.isClosed) _hubDone.add(null); },
    );
  }
}

// Public façade for cross-library reuse (e.g. NeuralInterfaceV2). # FIX-H
class ClientWsHub {
  ClientWsHub._();
  static WebSocketChannel? get channel => _ClientWsHub.channel;
  static Stream<dynamic> get inbound => _ClientWsHub.inbound;
  static Stream<Object> get errors => _ClientWsHub.errors;
  static Stream<void> get done => _ClientWsHub.done;
  static void attach(WebSocketChannel ch) => _ClientWsHub.attach(ch);
}

// =============================================================================
// CLIENT SCHEDULE SCREEN (COACH_ONLY & TOP_TIER)
// =============================================================================

class ClientScheduleScreen extends StatefulWidget {
  final Map<String, dynamic>? currentUserProfile;
  final String? username;
  final String? password;
  
  const ClientScheduleScreen({super.key, this.currentUserProfile, this.username, this.password});
  
  @override
  State<ClientScheduleScreen> createState() => _ClientScheduleScreenState();
}

class _ClientScheduleScreenState extends State<ClientScheduleScreen> {
  WebSocketChannel? _socket;
  StreamSubscription<dynamic>? _hubSub;
  final String _serverUrl = defaultWsUrl;
  List<Map<String, dynamic>> _upcomingSessions = [];
  List<Map<String, dynamic>> _availableSlots = [];
  String? _selectedDate;
  bool _isLoading = true;
  bool _isBooking = false;
  String _coachId = '';

  // ===== Coach calendar overview (client view) =====
  DateTime _calMonth = DateTime(DateTime.now().year, DateTime.now().month, 1);
  Set<int> _calRecurringDays = {}; // Mon=0..Sun=6
  Set<String> _calBlockedDates = {}; // YYYY-MM-DD
  bool _calLoadedOnce = false;
  CalendarView _calView = CalendarView.month;
  DateTime _calFocusedDate = DateTime.now();

  List<CalendarEvent> _buildCalendarEvents() {
    final out = <CalendarEvent>[];
    for (final s in _upcomingSessions) {
      final startStr = (s['scheduled_start'] ?? '').toString();
      final endStr = (s['scheduled_end'] ?? '').toString();
      if (startStr.isEmpty) continue;
      DateTime? st;
      DateTime? en;
      try {
        st = DateTime.parse(startStr).toLocal();
      } catch (_) {
        continue;
      }
      try {
        en = endStr.isEmpty ? null : DateTime.parse(endStr).toLocal();
      } catch (_) {}
      en ??= st.add(const Duration(minutes: 60));
      final status = (s['status'] ?? '').toString();
      final coach = (s['coach_name'] ?? 'Coach').toString();
      final color = status == 'pending_approval'
          ? const Color(0xFFE8D5A3)
          : const Color(0xFF4ECDC4);
      out.add(CalendarEvent(
        id: (s['session_id'] ?? s['id'] ?? '').toString(),
        start: st,
        end: en,
        title: coach,
        subtitle: status == 'pending_approval' ? 'Pending' : (s['session_type'] ?? '').toString(),
        color: color,
        tooltip: '$coach\n${s['date'] ?? ''} ${s['time'] ?? ''}\n${status}',
        source: 'sanctuary',
        raw: s,
      ));
    }
    return out;
  }
  
  Timer? _loadingTimeout;

  // Coach directory + request state
  List<Map<String, dynamic>> _directoryCoaches = [];
  bool _directoryLoading = false;
  Map<String, dynamic>? _pendingRequest;
  List<Map<String, dynamic>> _requestMessages = [];
  bool _submittingRequest = false;
  String? _coachAvailErr;
  String? _coachAvailDetail;
  /// IANA zone from bridge `coach_availability.availability.timezone` (coach’s published calendar).
  String? _coachAvailabilityIana;

  bool get _hasCoach => _coachId.isNotEmpty;

  String _friendlyCoachTzSubtitle(String? iana) {
    if (iana == null || iana.isEmpty) return 'Coach’s published time zone';
    if (iana == 'America/New_York') return 'Eastern Time (US & Canada)';
    return iana;
  }

  String _formatClientSlotRangeLocal(String startIso, String endIso) {
    try {
      final a = DateTime.parse(startIso).toLocal();
      final b = DateTime.parse(endIso).toLocal();
      final jm = DateFormat.jm();
      return '${jm.format(a)} – ${jm.format(b)}';
    } catch (_) {
      return startIso;
    }
  }

  @override
  void initState() {
    super.initState();
    _coachId = (widget.currentUserProfile?['assigned_coach_id'] ?? '').toString();
    // SCHEDULE-SHARED-WS
    if (_ClientWsHub.channel != null) {
      _socket = _ClientWsHub.channel;
      _hubSub = _ClientWsHub.inbound.listen(_handleMessage,
          onError: (e) => debugLog('WS Error: $e'),
          onDone: () {
            if (mounted && _isLoading) setState(() => _isLoading = false);
          });
      if (_hasCoach) {
        _requestUpcomingSessions();
        _requestMonthOverview();
      } else {
        _fetchCoachDirectory();
        _fetchRequestStatus();
      }
    } else {
      _connect();
    }
    _loadingTimeout = Timer(const Duration(seconds: 8), () {
      if (mounted && _isLoading) setState(() => _isLoading = false);
    });
  }
  
  void _connect() {
    // Fix E (COACH-AVAIL-ERROR-HANDLER): never send login_request with empty creds.
    // Empty password silently fails bridge auth → uid=GUEST on subsequent sends.
    final u = (widget.username ?? '').trim();
    final p = (widget.password ?? '');
    if (u.isEmpty || p.isEmpty) {
      debugLog('Schedule _connect skipped: missing credentials and no hub channel');
      if (mounted) {
        setState(() {
          _isLoading = false;
          _coachAvailErr = 'Session expired';
          _coachAvailDetail = 'Return to the home screen and reopen Schedule.';
        });
      }
      return;
    }
    try {
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));
      _socket!.stream.listen(_handleMessage, onError: (e) => debugLog('WS Error: $e'), onDone: () {
        if (mounted && _isLoading) setState(() => _isLoading = false);
      });
      _socket!.sink.add(jsonEncode({
        "type": "login_request",
        "username": u,
        "password": p,
        "expected_role": "CLIENT",
        "client_context": kIsWeb ? 'client_web' : 'client_mobile',
      }));
    } catch (e) {
      debugLog('Connection error: $e');
      if (mounted) setState(() => _isLoading = false);
    }
  }
  
  void _handleMessage(dynamic event) {
    try {
      final data = jsonDecode(event.toString());
      final type = data['type']?.toString() ?? '';
      
      if (type == 'login_success') {
        _loadingTimeout?.cancel();
        if (_hasCoach) {
          _requestUpcomingSessions();
          _requestMonthOverview();
        } else {
          _fetchCoachDirectory();
          _fetchRequestStatus();
        }
      } else if (type == 'login_failed' || type == 'wrong_portal') {
        _loadingTimeout?.cancel();
        if (mounted) setState(() => _isLoading = false);
      } else if (type == 'client_upcoming_sessions') {
        setState(() {
          _upcomingSessions = List<Map<String, dynamic>>.from(
            (data['sessions'] ?? []).map((s) => Map<String, dynamic>.from(s))
          );
          _isLoading = false;
        });
      } else if (type == 'coach_availability') {
        final av = data['availability'];
        final tz = av is Map ? av['timezone']?.toString() : null;
        setState(() {
          _coachAvailErr = null;
          _coachAvailDetail = null;
          _coachAvailabilityIana = (tz != null && tz.isNotEmpty) ? tz : _coachAvailabilityIana;
          _availableSlots = List<Map<String, dynamic>>.from(
            (data['available_slots'] ?? []).map((s) => Map<String, dynamic>.from(s))
          );
        });
      } else if (type == 'coach_availability_error') {
        // COACH-AVAIL-ERROR-HANDLER
        setState(() {
          _coachAvailErr = data['error']?.toString() ?? 'unknown';
          _coachAvailDetail = data['detail']?.toString();
          _availableSlots = [];
          _coachAvailabilityIana = null;
        });
      } else if (type == 'coach_month_overview') {
        setState(() {
          _calRecurringDays = (data['recurring_days'] as List? ?? [])
              .map((e) => (e as num).toInt())
              .toSet();
          _calBlockedDates = (data['blocked_dates'] as List? ?? [])
              .map((e) => e.toString())
              .toSet();
          _calLoadedOnce = true;
        });
      } else if (type == 'session_booked') {
        setState(() => _isBooking = false);
        _requestUpcomingSessions();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Session booked successfully!'), backgroundColor: Colors.green),
          );
        }
      } else if (type == 'session_cancelled') {
        _requestUpcomingSessions();
      } else if (type == 'coach_request_status') {
        if (data['status'] == 'none') {
          setState(() { _pendingRequest = null; _requestMessages = []; _isLoading = false; });
        } else {
          setState(() {
            _pendingRequest = Map<String, dynamic>.from(data);
            _requestMessages = List<Map<String, dynamic>>.from(
              (data['messages'] ?? []).map((m) => Map<String, dynamic>.from(m)),
            );
            _isLoading = false;
          });
        }
      } else if (type == 'coach_request_accepted') {
        setState(() {
          _coachId = data['coach_user_id']?.toString() ?? '';
          _pendingRequest = null;
          _requestMessages = [];
        });
        _requestUpcomingSessions();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('${data['coach_name'] ?? 'Your coach'} accepted your request!'), backgroundColor: Colors.green),
          );
        }
      } else if (type == 'coach_request_declined') {
        setState(() { _pendingRequest = null; _requestMessages = []; });
        _fetchCoachDirectory();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Coach declined — you can request another'), backgroundColor: Colors.orange),
          );
        }
      } else if (type == 'coach_request_cancelled') {
        setState(() { _pendingRequest = null; _requestMessages = []; _submittingRequest = false; });
      } else if (type == 'coach_request_nudge_sent') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Nudge sent to your coach'), backgroundColor: Color(0xFF4ECDC4)),
          );
        }
      } else if (type == 'coach_request_nudge_error') {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Nudge limit: try again after ${data['next_allowed_at'] ?? '24h'}'), backgroundColor: Colors.orange),
          );
        }
      } else if (type == 'coach_message_received') {
        setState(() {
          _requestMessages.add(Map<String, dynamic>.from(data));
        });
      } else if (type == 'error') {
        setState(() { _isBooking = false; _submittingRequest = false; });
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(data['detail'] ?? data['message'] ?? 'Error'), backgroundColor: Colors.red),
          );
        }
      }
    } catch (e) {
      debugLog('Parse error: $e');
    }
  }
  
  void _requestUpcomingSessions() {
    _socket?.sink.add(jsonEncode({"type": "client_get_upcoming_sessions"}));
  }
  
  void _requestAvailability(String date) {
    setState(() {
      _selectedDate = date;
      _coachAvailErr = null;
      _coachAvailDetail = null;
    });
    _socket?.sink.add(jsonEncode({
      "type": "client_get_coach_availability",
      "coach_id": _coachId,
      "date": date,
    }));
  }

  void _requestMonthOverview() {
    if (_coachId.isEmpty) return;
    final ym =
        '${_calMonth.year.toString().padLeft(4, '0')}-${_calMonth.month.toString().padLeft(2, '0')}';
    _socket?.sink.add(jsonEncode({
      "type": "client_get_coach_month_overview",
      "coach_id": _coachId,
      "year_month": ym,
    }));
  }

  // Mon=0..Sun=6 (matches backend day_of_week convention)
  int _dowMonZero(DateTime d) => (d.weekday - 1) % 7;
  String _ymd(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  static const List<String> _monthNames = [
    'January','February','March','April','May','June',
    'July','August','September','October','November','December'
  ];

  Widget _buildSwitchedCalendar() {
    final events = _buildCalendarEvents();
    void onTap(CalendarEvent ev) {
      final raw = ev.raw is Map<String, dynamic> ? ev.raw as Map<String, dynamic> : <String, dynamic>{};
      showDialog(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: Text(ev.title, style: const TextStyle(color: Color(0xFFC9A962))),
          content: Text(
            '${raw['date'] ?? ''} ${raw['time'] ?? ''}\n${raw['session_type'] ?? ''}\nStatus: ${raw['status'] ?? ''}',
            style: const TextStyle(color: Colors.white),
          ),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close'))],
        ),
      );
    }
    switch (_calView) {
      case CalendarView.week:
        return CalendarWeekGrid(focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.day:
        return CalendarDayGrid(focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.list:
        return CalendarListView(focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.timeline:
        return CalendarTimelineView(focusedDate: _calFocusedDate, events: events, onEventTap: onTap);
      case CalendarView.month:
        return _buildClientCalendarGrid();
    }
  }

  Widget _buildClientCalendarGrid() {
    final firstOfMonth = DateTime(_calMonth.year, _calMonth.month, 1);
    final lastOfMonth =
        DateTime(_calMonth.year, _calMonth.month + 1, 1).subtract(const Duration(days: 1));
    final daysInMonth = lastOfMonth.day;
    final leadingBlanks = (firstOfMonth.weekday) % 7; // Sun=0..Sat=6 columns
    final today = DateTime.now();
    final todayKey = _ymd(DateTime(today.year, today.month, today.day));

    final cells = <Widget>[];
    // Sun-Sat header
    const dowHeader = ['S','M','T','W','T','F','S'];
    for (final h in dowHeader) {
      cells.add(Center(
        child: Text(h,
          style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11, fontWeight: FontWeight.w600)),
      ));
    }
    for (int i = 0; i < leadingBlanks; i++) {
      cells.add(const SizedBox.shrink());
    }
    // Build a map of ISO date -> list of sessions (booked + pending)
    final Map<String, List<Map<String, dynamic>>> sessionsByDate = {};
    for (final raw in _upcomingSessions) {
      final start = (raw['scheduled_start'] ?? raw['date'] ?? '').toString();
      if (start.isEmpty) continue;
      try {
        final dt = DateTime.parse(start).toLocal();
        final key = _ymd(DateTime(dt.year, dt.month, dt.day));
        sessionsByDate.putIfAbsent(key, () => []).add(raw);
      } catch (_) {}
    }

    for (int day = 1; day <= daysInMonth; day++) {
      final d = DateTime(_calMonth.year, _calMonth.month, day);
      final iso = _ymd(d);
      final isPast = d.isBefore(DateTime(today.year, today.month, today.day));
      final isToday = iso == todayKey;
      final isBlocked = _calBlockedDates.contains(iso);
      final hasRecurring = _calRecurringDays.contains(_dowMonZero(d));
      final isAvailable = hasRecurring && !isBlocked && !isPast;
      final isSelected = _selectedDate == iso;
      final daySessions = sessionsByDate[iso] ?? const <Map<String, dynamic>>[];
      final hasBooked = daySessions.any((s) => (s['status'] ?? '') == 'scheduled' || (s['status'] ?? '') == 'active');
      final hasPending = daySessions.any((s) => (s['status'] ?? '') == 'pending_approval');

      Color bg;
      Color fg = Colors.white;
      if (isPast) {
        bg = const Color(0xFF1A1A1A);
        fg = const Color(0xFF555555);
      } else if (hasBooked) {
        bg = const Color(0xFF1A2A3A);
        fg = const Color(0xFFB6D5FF);
      } else if (hasPending) {
        bg = const Color(0xFF2A2410);
        fg = const Color(0xFFE8D5A3);
      } else if (isBlocked) {
        bg = const Color(0xFF2A1A1A);
        fg = const Color(0xFF888888);
      } else if (isAvailable) {
        bg = const Color(0xFF1A2A1A);
        fg = const Color(0xFFB6E3B6);
      } else {
        bg = const Color(0xFF111111);
        fg = const Color(0xFFAAAAAA);
      }
      if (isSelected) {
        bg = const Color(0xFFC9A962);
        fg = Colors.black;
      }

      // Build tooltip text for booked/pending days
      String tooltipText = '';
      if (daySessions.isNotEmpty) {
        final lines = <String>[];
        for (final s in daySessions) {
          final coach = (s['coach_name'] ?? 'Coach').toString();
          final tm = (s['time'] ?? '').toString();
          String pretty = tm;
          try {
            final dtFull = DateTime.parse((s['scheduled_start'] ?? '').toString()).toLocal();
            final h12 = dtFull.hour == 0 ? 12 : (dtFull.hour > 12 ? dtFull.hour - 12 : dtFull.hour);
            final ap = dtFull.hour >= 12 ? 'PM' : 'AM';
            pretty = '$h12:${dtFull.minute.toString().padLeft(2, '0')} $ap';
          } catch (_) {}
          final st = (s['status'] ?? '').toString();
          final tag = st == 'pending_approval' ? ' (pending)' : '';
          lines.add('$coach • $pretty$tag');
        }
        tooltipText = lines.join('\n');
      }

      Widget cell = Container(
        margin: const EdgeInsets.all(2),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(6),
          border: isToday
              ? Border.all(color: const Color(0xFFC9A962), width: 1.5)
              : Border.all(
                  color: hasBooked
                      ? const Color(0xFF4ECDC4).withOpacity(0.5)
                      : (hasPending ? const Color(0xFFC9A962).withOpacity(0.5) : const Color(0xFF252525)),
                  width: hasBooked || hasPending ? 1.0 : 0.5,
                ),
        ),
        alignment: Alignment.center,
        child: Stack(
          alignment: Alignment.center,
          children: [
            Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text('$day',
                    style: TextStyle(color: fg, fontSize: 13, fontWeight: FontWeight.w600)),
                if (daySessions.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 1),
                    child: Text(
                      (() {
                        final s = daySessions.first;
                        final coach = (s['coach_name'] ?? 'Coach').toString();
                        return coach.length > 7 ? coach.substring(0, 7) : coach;
                      })(),
                      style: TextStyle(
                        color: hasBooked ? const Color(0xFF4ECDC4) : const Color(0xFFC9A962),
                        fontSize: 8,
                        fontWeight: FontWeight.w700,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
            ),
            if (isAvailable && !isSelected && daySessions.isEmpty)
              Positioned(
                bottom: 4,
                child: Container(
                  width: 4, height: 4,
                  decoration: const BoxDecoration(
                    color: Color(0xFF4ADE80),
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            if (isBlocked && daySessions.isEmpty)
              Positioned(
                bottom: 4,
                child: Container(
                  width: 4, height: 4,
                  decoration: const BoxDecoration(
                    color: Color(0xFFEF4444),
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            if (hasBooked)
              Positioned(
                top: 2,
                right: 3,
                child: Container(
                  width: 5, height: 5,
                  decoration: const BoxDecoration(
                    color: Color(0xFF4ECDC4),
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            if (hasPending && !hasBooked)
              Positioned(
                top: 2,
                right: 3,
                child: Container(
                  width: 5, height: 5,
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
        cell = Tooltip(
          message: tooltipText,
          waitDuration: const Duration(milliseconds: 200),
          child: cell,
        );
      }

      cells.add(GestureDetector(
        onTap: isPast || isBlocked
            ? null
            : () => _requestAvailability(iso),
        child: cell,
      ));
    }

    return Container(
      padding: const EdgeInsets.all(12),
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
              IconButton(
                icon: const Icon(Icons.chevron_left, color: Color(0xFFC9A962)),
                onPressed: () {
                  setState(() {
                    _calMonth = DateTime(_calMonth.year, _calMonth.month - 1, 1);
                  });
                  _requestMonthOverview();
                },
              ),
              Expanded(
                child: Center(
                  child: Text(
                    '${_monthNames[_calMonth.month - 1]} ${_calMonth.year}',
                    style: const TextStyle(
                        color: Color(0xFFC9A962),
                        fontSize: 15,
                        fontWeight: FontWeight.w600),
                  ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.chevron_right, color: Color(0xFFC9A962)),
                onPressed: () {
                  setState(() {
                    _calMonth = DateTime(_calMonth.year, _calMonth.month + 1, 1);
                  });
                  _requestMonthOverview();
                },
              ),
            ],
          ),
          const SizedBox(height: 4),
          GridView.count(
            crossAxisCount: 7,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            childAspectRatio: 1.0,
            children: cells,
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 12,
            runSpacing: 4,
            children: const [
              _CalLegendDot(color: Color(0xFF4ADE80), label: 'Available'),
              _CalLegendDot(color: Color(0xFF4ECDC4), label: 'Booked'),
              _CalLegendDot(color: Color(0xFFC9A962), label: 'Pending'),
              _CalLegendDot(color: Color(0xFFEF4444), label: 'Blocked'),
            ],
          ),
          if (!_calLoadedOnce)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                'Loading coach availability...',
                style: TextStyle(color: Colors.grey, fontSize: 11),
              ),
            )
          else if (_calRecurringDays.isEmpty && _calBlockedDates.isEmpty)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                'Your coach has not published hours yet.',
                style: TextStyle(color: Colors.grey, fontSize: 11),
              ),
            ),
        ],
      ),
    );
  }
  
  void _bookSession(String start, String end) {
    _showBookingIntakeDialog(start, end);
  }

  void _showBookingIntakeDialog(String start, String end) {
    final noteCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text('Session Note', style: TextStyle(color: Color(0xFFC9A962))),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Anything your coach should know before this session? (optional)', style: TextStyle(color: Colors.grey, fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
              controller: noteCtrl,
              maxLines: 3,
              maxLength: 300,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'Topics, goals, or concerns...',
                hintStyle: const TextStyle(color: Colors.grey),
                filled: true, fillColor: const Color(0xFF1A1A1A),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              _confirmBookSession(start, end, '');
            },
            child: const Text('Skip', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962), foregroundColor: Colors.black),
            onPressed: () {
              Navigator.pop(ctx);
              _confirmBookSession(start, end, noteCtrl.text.trim());
            },
            child: const Text('Book Session'),
          ),
        ],
      ),
    );
  }

  void _confirmBookSession(String start, String end, String intakeNote) {
    setState(() => _isBooking = true);
    final payload = <String, dynamic>{
      "type": "client_book_session",
      "coach_id": _coachId,
      "scheduled_start": start,
      "scheduled_end": end,
    };
    if (intakeNote.isNotEmpty) payload["intake_note"] = intakeNote;
    _socket?.sink.add(jsonEncode(payload));
  }
  
  void _cancelSession(String sessionId) {
    _socket?.sink.add(jsonEncode({
      "type": "client_cancel_session",
      "session_id": sessionId,
    }));
  }

  void _fetchCoachDirectory() async {
    setState(() => _directoryLoading = true);
    try {
      final token = widget.currentUserProfile?['token'] ?? '';
      final uri = Uri.parse('${AppConfig.apiBaseUrl}/api/coach/directory');
      final resp = await http.get(uri, headers: {'Authorization': 'Bearer $token'});
      if (resp.statusCode == 200) {
        final body = jsonDecode(resp.body);
        if (mounted) {
          setState(() {
            _directoryCoaches = List<Map<String, dynamic>>.from(
              (body['coaches'] ?? []).map((c) => Map<String, dynamic>.from(c)),
            );
            _directoryLoading = false;
          });
        }
      } else {
        if (mounted) setState(() => _directoryLoading = false);
      }
    } catch (e) {
      debugLog('Directory fetch error: $e');
      if (mounted) setState(() => _directoryLoading = false);
    }
  }

  void _fetchRequestStatus() {
    _socket?.sink.add(jsonEncode({"type": "coach_get_request_status"}));
  }

  void _submitCoachRequest(String coachUserId, String intakeNote) {
    setState(() => _submittingRequest = true);
    _socket?.sink.add(jsonEncode({
      "type": "coach_request_submit",
      "coach_user_id": coachUserId,
      "intake_note": intakeNote,
    }));
    Future.delayed(const Duration(milliseconds: 500), () {
      _fetchRequestStatus();
    });
  }

  void _cancelCoachRequest(String requestId) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_request_cancel",
      "request_id": requestId,
    }));
  }

  void _nudgeCoach(String requestId) {
    _socket?.sink.add(jsonEncode({
      "type": "coach_request_nudge",
      "request_id": requestId,
    }));
  }

  @override
  void dispose() {
    _loadingTimeout?.cancel();
    _hubSub?.cancel();
    if (_hubSub == null) _socket?.sink.close();
    super.dispose();
  }
  
  @override
  Widget build(BuildContext context) {
    final name = widget.currentUserProfile?['name'] ?? 'Client';
    final plan = (widget.currentUserProfile?['subscription_plan'] ?? '').toString().toUpperCase();
    
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0A0A0A),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Color(0xFFC9A962)),
          onPressed: () {
            if (Navigator.canPop(context)) {
              Navigator.pop(context);
            } else {
              Navigator.pushReplacement(
                context,
                MaterialPageRoute(builder: (_) => const LobbyScreen()),
              );
            }
          },
        ),
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(name, style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16, fontWeight: FontWeight.bold)),
            Text(plan == 'COACH_ONLY' ? 'Scheduling Only' : 'Schedule', style: const TextStyle(color: Colors.grey, fontSize: 12)),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Color(0xFFC9A962)),
            onPressed: _requestUpcomingSessions,
          ),
        ],
      ),
      body: _isLoading
        ? const Center(child: CircularProgressIndicator(color: Color(0xFFC9A962)))
        : _hasCoach
          ? _buildScheduleView()
          : _pendingRequest != null
            ? _buildPendingRequestView()
            : _buildCoachDirectoryView(),
    );
  }
  
  Widget _buildScheduleView() {
    final coachName = (widget.currentUserProfile?['assigned_coach'] ?? widget.currentUserProfile?['assigned_coach_name'] ?? 'Your Coach').toString();
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.all(14),
            margin: const EdgeInsets.only(bottom: 18),
            decoration: BoxDecoration(
              color: const Color(0xFF111111),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.4)),
            ),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 20,
                  backgroundColor: const Color(0xFF252525),
                  child: Text(coachName.isNotEmpty ? coachName[0].toUpperCase() : 'C', style: const TextStyle(color: Color(0xFFC9A962), fontSize: 18)),
                ),
                const SizedBox(width: 12),
                Expanded(child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('YOUR COACH', style: TextStyle(color: Colors.grey, fontSize: 10, letterSpacing: 1.2)),
                    const SizedBox(height: 2),
                    Text(coachName, style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16, fontWeight: FontWeight.bold)),
                  ],
                )),
                TextButton(
                  onPressed: () => _showCoachChangeRequestDialog(coachName),
                  child: const Text('Change Coach', style: TextStyle(color: Color(0xFF4ECDC4), fontSize: 12)),
                ),
              ],
            ),
          ),
          const Text('UPCOMING SESSIONS', style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          if (_upcomingSessions.isEmpty)
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF252525)),
              ),
              child: const Center(child: Text('No upcoming sessions', style: TextStyle(color: Colors.grey))),
            )
          else
            ..._upcomingSessions.map((s) => _buildSessionCard(s)),
          const SizedBox(height: 24),
          const Text('BOOK A SESSION', style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
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
            _buildClientCalendarGrid()
          else
            SizedBox(height: 480, child: _buildSwitchedCalendar()),
          if (_selectedDate != null) ...[
            const SizedBox(height: 12),
            Row(
              children: [
                const Icon(Icons.event_available, color: Color(0xFFC9A962), size: 18),
                const SizedBox(width: 8),
                Text('Selected: $_selectedDate',
                    style: const TextStyle(color: Color(0xFFC9A962), fontSize: 13, fontWeight: FontWeight.w600)),
              ],
            ),
          ],
          if (_availableSlots.isNotEmpty) ...[
            const SizedBox(height: 16),
            const Text('Available Time Slots', style: TextStyle(color: Color(0xFFC9A962), fontSize: 14, fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            Text(
              'Shown in your device’s local time · ${_friendlyCoachTzSubtitle(_coachAvailabilityIana)}${_coachAvailabilityIana != null && _coachAvailabilityIana!.isNotEmpty ? ' (${_coachAvailabilityIana})' : ''}',
              style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11, height: 1.3),
            ),
            const SizedBox(height: 8),
            ..._availableSlots.map((slot) => _buildSlotCard(slot)),
          ] else if (_selectedDate != null) ...[
            const SizedBox(height: 16),
            if (_coachAvailErr != null)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFF111111),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: const Color(0xFFEF4444).withOpacity(0.35)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Availability request failed',
                        style: TextStyle(color: Color(0xFFEF4444), fontSize: 14, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 6),
                    Text(_coachAvailDetail ?? _coachAvailErr ?? 'Error',
                        style: const TextStyle(color: Colors.grey, fontSize: 13)),
                    if (_coachAvailErr == 'auth_role_mismatch') ...[
                      const SizedBox(height: 10),
                      TextButton(
                        onPressed: () => _requestAvailability(_selectedDate!),
                        child: const Text('Retry', style: TextStyle(color: Color(0xFFC9A962))),
                      ),
                    ],
                  ],
                ),
              )
            else
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFF111111),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: const Color(0xFF252525)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    Text('No published hours for this date',
                        style: TextStyle(color: Color(0xFFC9A962), fontSize: 14, fontWeight: FontWeight.w600)),
                    SizedBox(height: 6),
                    Text('Your coach has not published available hours yet. Check back soon or contact them directly.',
                        style: TextStyle(color: Colors.grey, fontSize: 13)),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }

  Widget _buildCoachDirectoryView() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('FIND YOUR COACH', style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          const Text('Select a coach to begin your journey', style: TextStyle(color: Colors.grey, fontSize: 13)),
          const SizedBox(height: 16),
          if (_directoryLoading)
            const Center(child: Padding(
              padding: EdgeInsets.all(32),
              child: CircularProgressIndicator(color: Color(0xFFC9A962)),
            ))
          else if (_directoryCoaches.isEmpty)
            Container(
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: const Color(0xFF111111),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFF252525)),
              ),
              child: const Center(child: Text('No coaches are currently accepting new clients.\nCheck back soon.', textAlign: TextAlign.center, style: TextStyle(color: Colors.grey))),
            )
          else
            ..._directoryCoaches.map((coach) => _buildCoachCard(coach)),
        ],
      ),
    );
  }

  Widget _buildCoachCard(Map<String, dynamic> coach) {
    final name = coach['display_name'] ?? 'Coach';
    final bio = coach['bio'] ?? '';
    final tags = List<String>.from((coach['specialty_tags'] ?? []).map((t) => t.toString()));
    final years = coach['years_experience'] ?? 0;
    final duration = coach['session_duration_minutes'] ?? 60;
    final coachUserId = coach['coach_user_id'] ?? '';
    final photo = coach['photo_url']?.toString() ?? '';

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
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
              CircleAvatar(
                radius: 24,
                backgroundColor: const Color(0xFF252525),
                backgroundImage: photo.isNotEmpty ? NetworkImage(photo) : null,
                child: photo.isEmpty ? Text(name.isNotEmpty ? name[0] : 'C', style: const TextStyle(color: Color(0xFFC9A962), fontSize: 20)) : null,
              ),
              const SizedBox(width: 12),
              Expanded(child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 16)),
                  if (years > 0) Text('$years years experience · ${duration}min sessions', style: const TextStyle(color: Colors.grey, fontSize: 12)),
                ],
              )),
            ],
          ),
          if (bio.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(bio, maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Color(0xFFBBBBBB), fontSize: 13)),
          ],
          if (tags.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(spacing: 6, runSpacing: 4, children: tags.map((t) => Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(color: const Color(0xFF4ECDC4).withOpacity(0.12), borderRadius: BorderRadius.circular(12)),
              child: Text(t, style: const TextStyle(color: Color(0xFF4ECDC4), fontSize: 11)),
            )).toList()),
          ],
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962), foregroundColor: Colors.black),
              onPressed: _submittingRequest ? null : () => _showIntakeDialog(coachUserId, name),
              child: _submittingRequest
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black))
                : const Text('Request This Coach', style: TextStyle(fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
    );
  }

  void _showCoachChangeRequestDialog(String currentCoachName) {
    final reasonCtrl = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text('Request Coach Change', style: TextStyle(color: Color(0xFFC9A962))),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('You are currently assigned to $currentCoachName. To change coaches, submit a request — your current coach or admin will review it.',
                style: const TextStyle(color: Colors.grey, fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
              controller: reasonCtrl,
              maxLines: 3,
              maxLength: 300,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'Reason for change request (optional)...',
                hintStyle: const TextStyle(color: Colors.grey),
                filled: true,
                fillColor: const Color(0xFF1A1A1A),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962), foregroundColor: Colors.black),
            onPressed: () {
              _socket?.sink.add(jsonEncode({
                "type": "coach_change_request",
                "current_coach_id": _coachId,
                "reason": reasonCtrl.text.trim(),
              }));
              Navigator.pop(ctx);
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Coach change request submitted. You will be notified when reviewed.'),
                    backgroundColor: Color(0xFF4ECDC4),
                  ),
                );
              }
            },
            child: const Text('Submit Request', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  void _showIntakeDialog(String coachUserId, String coachName) {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: Text('Request $coachName', style: const TextStyle(color: Color(0xFFC9A962))),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Briefly share what brings you to coaching (optional):', style: TextStyle(color: Colors.grey, fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              maxLines: 4,
              maxLength: 500,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                hintText: 'What are you hoping to work on?',
                hintStyle: const TextStyle(color: Colors.grey),
                filled: true, fillColor: const Color(0xFF1A1A1A),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
              ),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: Colors.grey))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFC9A962), foregroundColor: Colors.black),
            onPressed: () {
              Navigator.pop(ctx);
              _submitCoachRequest(coachUserId, controller.text.trim());
            },
            child: const Text('Send Request'),
          ),
        ],
      ),
    );
  }

  Widget _buildPendingRequestView() {
    final coachName = _pendingRequest?['coach_name'] ?? 'Coach';
    final requestId = _pendingRequest?['request_id'] ?? '';
    final requestedAt = _pendingRequest?['requested_at'] ?? '';

    String timeAgo = '';
    try {
      final dt = DateTime.parse(requestedAt);
      final diff = DateTime.now().difference(dt);
      if (diff.inDays > 0) { timeAgo = '${diff.inDays}d ago'; }
      else if (diff.inHours > 0) { timeAgo = '${diff.inHours}h ago'; }
      else { timeAgo = '${diff.inMinutes}m ago'; }
    } catch (_) {}

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('PENDING COACH REQUEST', style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF111111),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.3)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  const Icon(Icons.hourglass_top, color: Color(0xFFC9A962), size: 20),
                  const SizedBox(width: 8),
                  Expanded(child: Text('Awaiting $coachName\'s response', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
                ]),
                if (timeAgo.isNotEmpty) Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text('Requested $timeAgo', style: const TextStyle(color: Colors.grey, fontSize: 12)),
                ),
                const SizedBox(height: 16),
                Row(children: [
                  Expanded(child: OutlinedButton.icon(
                    icon: const Icon(Icons.notifications_active, size: 16),
                    label: const Text('Nudge'),
                    style: OutlinedButton.styleFrom(foregroundColor: const Color(0xFF4ECDC4), side: const BorderSide(color: Color(0xFF4ECDC4))),
                    onPressed: () => _nudgeCoach(requestId),
                  )),
                  const SizedBox(width: 12),
                  Expanded(child: OutlinedButton.icon(
                    icon: const Icon(Icons.close, size: 16),
                    label: const Text('Cancel'),
                    style: OutlinedButton.styleFrom(foregroundColor: Colors.red, side: const BorderSide(color: Colors.red)),
                    onPressed: () => _cancelCoachRequest(requestId),
                  )),
                ]),
              ],
            ),
          ),
          if (_requestMessages.isNotEmpty) ...[
            const SizedBox(height: 24),
            const Text('MESSAGES FROM COACH', style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 12),
            ..._requestMessages.map((m) => Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFF1A1A2E),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: const Color(0xFF4ECDC4).withOpacity(0.2)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(m['message_text'] ?? '', style: const TextStyle(color: Colors.white, fontSize: 14)),
                  const SizedBox(height: 4),
                  Text(_formatMsgTime(m['created_at']), style: const TextStyle(color: Colors.grey, fontSize: 11)),
                ],
              ),
            )),
          ],
        ],
      ),
    );
  }

  String _formatMsgTime(dynamic ts) {
    if (ts == null) return '';
    try {
      final dt = DateTime.parse(ts.toString());
      return '${dt.month}/${dt.day} ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) { return ''; }
  }

  Widget _buildSessionCard(Map<String, dynamic> session) {
    final start = (session['scheduled_start'] ?? '').toString();
    final zoomLink = (session['zoom_link'] ?? '').toString();
    final status = (session['status'] ?? 'scheduled').toString();
    final coachName = (session['coach_name'] ?? 'Coach').toString();
    final notes = (session['notes'] ?? '').toString();
    final sessionType = (session['session_type'] ?? 'COACH').toString();
    final platform = (session['platform'] ?? 'Zoom').toString();
    final durationMin = session['duration_minutes'] is int
        ? session['duration_minutes'] as int
        : int.tryParse('${session['duration_minutes'] ?? ''}') ?? 50;

    String formattedDate = '';
    String formattedTime = '';
    try {
      final dt = DateTime.parse(start).toLocal();
      const months = ['', 'Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      const weekdays = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
      formattedDate = '${weekdays[dt.weekday - 1]}, ${months[dt.month]} ${dt.day}, ${dt.year}';
      final hour12 = dt.hour == 0 ? 12 : (dt.hour > 12 ? dt.hour - 12 : dt.hour);
      final ampm = dt.hour >= 12 ? 'PM' : 'AM';
      formattedTime = '$hour12:${dt.minute.toString().padLeft(2, '0')} $ampm';
    } catch (_) {
      formattedDate = start;
    }

    Color statusColor;
    String statusLabel = status.toUpperCase();
    switch (status) {
      case 'pending_approval':
        statusColor = const Color(0xFFC9A962);
        statusLabel = 'PENDING';
        break;
      case 'scheduled':
        statusColor = const Color(0xFF4ECDC4);
        break;
      case 'active':
        statusColor = const Color(0xFF22C55E);
        break;
      case 'declined':
      case 'cancelled':
        statusColor = const Color(0xFFEF4444);
        break;
      default:
        statusColor = Colors.grey;
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111111),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: statusColor.withOpacity(0.4), width: 1.2),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.calendar_today, color: statusColor, size: 18),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  coachName,
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 15),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: statusColor.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: statusColor.withOpacity(0.4)),
                ),
                child: Text(statusLabel, style: TextStyle(color: statusColor, fontSize: 10, fontWeight: FontWeight.w700)),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              const Icon(Icons.event, color: Color(0xFFC9A962), size: 14),
              const SizedBox(width: 6),
              Expanded(child: Text(formattedDate, style: const TextStyle(color: Colors.white70, fontSize: 12.5))),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              const Icon(Icons.access_time, color: Color(0xFFC9A962), size: 14),
              const SizedBox(width: 6),
              Text('$formattedTime  •  $durationMin min  •  $sessionType  •  $platform',
                  style: const TextStyle(color: Colors.white70, fontSize: 12.5)),
            ],
          ),
          if (notes.isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFF050505),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.notes, color: Color(0xFF9D4EDD), size: 14),
                  const SizedBox(width: 6),
                  Expanded(child: Text(notes, style: const TextStyle(color: Colors.white70, fontSize: 12, fontStyle: FontStyle.italic))),
                ],
              ),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              if (zoomLink.isNotEmpty && status != 'pending_approval')
                Expanded(
                  child: ElevatedButton.icon(
                    icon: const Icon(Icons.videocam, size: 16),
                    label: const Text('Join Zoom', style: TextStyle(fontSize: 12)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF2D8CFF),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                    onPressed: () async {
                      final uri = Uri.parse(zoomLink);
                      if (await canLaunchUrl(uri)) {
                        await launchUrl(uri, mode: LaunchMode.externalApplication);
                      }
                    },
                  ),
                ),
              if (zoomLink.isNotEmpty && status != 'pending_approval') const SizedBox(width: 8),
              if (status == 'pending_approval')
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: const Color(0xFFC9A962).withOpacity(0.10),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.3)),
                    ),
                    child: const Text('Awaiting Coach Approval',
                        style: TextStyle(color: Color(0xFFC9A962), fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                ),
              if (status == 'pending_approval') const SizedBox(width: 8),
              TextButton(
                onPressed: () => _cancelSession(session['session_id'] ?? ''),
                child: const Text('Cancel', style: TextStyle(color: Colors.red, fontSize: 12)),
              ),
            ],
          ),
        ],
      ),
    );
  }
  
  Widget _buildDatePicker() {
    return GestureDetector(
      onTap: () async {
        final picked = await showDatePicker(
          context: context,
          initialDate: DateTime.now().add(const Duration(days: 1)),
          firstDate: DateTime.now(),
          lastDate: DateTime.now().add(const Duration(days: 90)),
          builder: (ctx, child) {
            return Theme(
              data: ThemeData.dark().copyWith(
                colorScheme: const ColorScheme.dark(
                  primary: Color(0xFFC9A962),
                  surface: Color(0xFF111111),
                ),
              ),
              child: child!,
            );
          },
        );
        if (picked != null) {
          _requestAvailability(picked.toIso8601String().split('T')[0]);
        }
      },
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.3)),
        ),
        child: Row(
          children: [
            const Icon(Icons.calendar_month, color: Color(0xFFC9A962)),
            const SizedBox(width: 12),
            Text(
              _selectedDate ?? 'Select a date to see available slots',
              style: TextStyle(color: _selectedDate != null ? Colors.white : Colors.grey, fontSize: 14),
            ),
            const Spacer(),
            const Icon(Icons.arrow_drop_down, color: Color(0xFFC9A962)),
          ],
        ),
      ),
    );
  }
  
  Widget _buildSlotCard(Map<String, dynamic> slot) {
    final start = slot['start'] ?? '';
    final end = slot['end'] ?? '';
    final label = (start.toString().isNotEmpty && end.toString().isNotEmpty)
        ? _formatClientSlotRangeLocal(start.toString(), end.toString())
        : start.toString();
    
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      child: ListTile(
        tileColor: const Color(0xFF111111),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        leading: const Icon(Icons.access_time, color: Color(0xFF4ECDC4)),
        title: Text(label, style: const TextStyle(color: Colors.white)),
        trailing: _isBooking
          ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2, color: Color(0xFFC9A962)))
          : ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFC9A962),
                foregroundColor: Colors.black,
              ),
              onPressed: () => _bookSession(start, end),
              child: const Text('Book', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
            ),
      ),
    );
  }
}

class _CalLegendDot extends StatelessWidget {
  final Color color;
  final String label;
  const _CalLegendDot({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(color: Color(0xFF8B7355), fontSize: 10)),
      ],
    );
  }
}
