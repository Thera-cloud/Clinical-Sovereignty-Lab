import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kDebugMode, kIsWeb;
import 'package:flutter/services.dart';

/// Debug-only print: suppressed in production builds.
// ignore: avoid_print
void debugLog(Object? message) { if (kDebugMode) print(message); }
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

import 'metrics_widgets.dart';
import 'updated_screens.dart';
import 'avatar.dart';
import 'screens/onboarding_threshold_screen.dart';
import 'screens/onboarding_paid_screen.dart';

import 'shared_widgets.dart';
import 'services/device_shield.dart';


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

  // ── HIVE DEFENSE v4.3: Device Shield — run full security check on launch ──
  if (!kIsWeb) {
    DeviceShield.instance.runFullCheck().then((report) {
      debugLog('>>> [DeviceShield] Launch check: ${report.overallStatus.name} '
          '(${report.passedCount}/${report.totalChecks} passed)');
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
                  obscureText: true,
                  style: const TextStyle(color: _textPrimary),
                  decoration: InputDecoration(
                    hintText: 'Password',
                    hintStyle: const TextStyle(color: _textSecondary),
                    filled: true,
                    fillColor: _bgElevated,
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
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
                obscureText: true,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: "New password (min 6 characters)",
                  prefixIcon: Icon(Icons.lock, color: Colors.grey),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _confirmCtrl,
                obscureText: true,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: "Confirm password",
                  prefixIcon: Icon(Icons.lock_outline, color: Colors.grey),
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
  DateTime? _suppressSpeechUntil;
  String _connectionStatus = "Initializing..."; 
  // Real-time metrics from backend
  Map<String, dynamic>? _currentMetrics;
  List<dynamic>? _moodHistory;
  int _tokenBalance = 0;
  int _tokenUsage = 0;

  // Avatar Mode (Top Tier / Sovereign Circle only)
  bool _avatarModeEnabled = false;
  AvatarVisualState _avatarState = const AvatarVisualState();
  AvatarAppearanceConfig _avatarAppearance = const AvatarAppearanceConfig();
  VoiceState _voiceState = VoiceState.idle;
  double _mouthOpenness = 0.0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _connectToCortex();
    _initSpeechToText();

    // ── HIVE DEFENSE v4.3: Start periodic DeviceShield checks during session ──
    if (!kIsWeb) {
      DeviceShield.instance.startPeriodicChecks(
        interval: const Duration(minutes: 5),
      );
    }
  }

  @override
  void dispose() {
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

  // 1. ESTABLISH FRESH CONNECTION
  void _connectToCortex() {
    setState(() => _connectionStatus = "Dialing Neural Core...");
    
    try {
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));
      
      _socket!.stream.listen(
        _handleSocketMessage,
        onError: (e) {
          if(mounted) setState(() => _connectionStatus = "ERROR: $e");
          _addSystemMsg("Connection Died: $e");
        },
        onDone: () {
          if(mounted) setState(() => _connectionStatus = "DISCONNECTED");
        }
      );

      // 2. IMMEDIATE LOGIN
      debugLog(">>> NEURAL INTERFACE: Sending Login...");
      _socket!.sink.add(jsonEncode({
        "type": "login_request",
        "username": widget.username,
        "password": widget.password,
        "expected_role": "CLIENT"
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
      }
      else if (data['type'] == 'nate_response' || data['type'] == 'chat_reply') {
        String reply = data['text'] ?? "";
        setState(() {
          // Update last NATE message if it exists, otherwise add new one
          if (_chatHistory.isNotEmpty && _chatHistory.last.startsWith("[NATE]:")) {
            _chatHistory[_chatHistory.length - 1] = "[NATE]: $reply";
          } else {
            _chatHistory.add("[NATE]: $reply");
          } 
          _scrollToBottom();
        });
      }
      else if (data['type'] == 'nate_audio_delta') {
         if (mounted) setState(() => _isTalking = true);
         final payload = data['payload'];
         if (payload != null) {
           _audio.processAudioChunk(payload);
         }
         Future.delayed(const Duration(milliseconds: 200), () {
           if (mounted) setState(() => _isTalking = false);
         });
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
              _chatHistory.add("[NATE]: $text");
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
    setState(() {
      _chatHistory.add("[SYSTEM]: $msg");
      _scrollToBottom();
    });
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
      _socket?.sink.add(jsonEncode({'type': 'fetch_avatar_config'}));
    }
  }

  Future<void> _sendMessage() async {
    await _stopSpeechAndSuppressLateResults();
    String text = _chatController.text.trim();
    if (text.isEmpty) return;
    
    // Check our INTERNAL socket
    if (_socket == null || _connectionStatus.contains("DISCONNECTED")) {
      _addSystemMsg("Link is dead. Reconnecting...");
      _connectToCortex(); // Auto-heal
      return;
    }

    debugLog(">>> SENDING: $text");
    _socket!.sink.add(jsonEncode({
      "type": "nate_query", 
      "nate_query": text,
      "modality": "General" 
    }));

    setState(() {
      _chatHistory.add("[YOU]: $text");
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

  @override
  void dispose() {
    _scrollController.dispose();
    _speech.stop();
    super.dispose();
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
              _socket?.sink.close();
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
                child: ListView.builder(
                  controller: _scrollController,
                  itemCount: _chatHistory.length,
                  itemBuilder: (ctx, i) => Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
                    child: Text(_chatHistory[i], style: TextStyle(fontFamily: "Courier", color: _chatHistory[i].startsWith("[YOU]") ? Colors.grey : (_chatHistory[i].startsWith("[SYSTEM]") ? Colors.yellow : Colors.white), fontSize: 14)),
                  )
                ),
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

  // 1. ESTABLISH FRESH CONNECTION (Stability Fix)
  void _connectToBridge() {
    setState(() => _statusMessage = "Connecting to HQ...");
    
    try {
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));
      
      _socket!.stream.listen(
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
        "expected_role": "COACH"
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

      // C. Login Failed — show error and return to login screen
      else if (data['type'] == 'login_failed' || data['type'] == 'login_failure' || data['type'] == 'error') {
        final msg = (data['message'] ?? 'Login failed').toString();
        debugLog(">>> COACH LOGIN FAILED: $msg");
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(msg),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 4),
          ));
          // Navigate back to the login screen so user can retry
          Navigator.of(context).pop();
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
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Secure Relay Opening...")));
          },
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
    _channel = WebSocketChannel.connect(Uri.parse(_serverUrl));
    _listenToWebSocket();

    final username = widget.username ??
        widget.profile['username'] ??
        widget.profile['email']?.split('@')[0] ??
        'client1';

    debugLog('>>> SANCTUARY: Authenticating...');
    _channel?.sink.add(json.encode({
      "type": "login_request",
      "username": username,
      "password": widget.password ?? "",
      "expected_role": "CLIENT"
    }));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _messageController.dispose();
    _suggestedController.dispose();
    _groupCoachingTimer?.cancel();
    _scrollController.dispose();
    _wsSubscription?.cancel();
    _channel?.sink.close();
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
    // Check if WebSocket is still connected
    if (_channel == null) {
      debugLog('>>> SANCTUARY: Reconnecting...');
      _connectToServer();
    } else {
      // Send a ping to check connection, if it fails reconnect
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
        Future.delayed(const Duration(seconds: 2), () {
          if (mounted) _connectToServer();
        });
      },
      onDone: () {
        debugLog('>>> SANCTUARY: WebSocket closed');
        if (mounted) _showError('Reconnecting...');
        Future.delayed(const Duration(seconds: 2), () {
          if (mounted) _connectToServer();
        });
      },
    );
  }

  void _postAssistedResponse() {
    final assisted = _assistedResponse;
    if (assisted != null && assisted.isNotEmpty) {
      _channel?.sink.add(jsonEncode({
        "type": "sanctuary_post_assisted_response",
        "sanctuary_id": _sanctuaryId,
        "assisted_response": assisted
      }));
      setState(() {
        _assistedResponse = null; // Clear after posting
      });
    }
  }

  void _approveGroupCoaching() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_group_coaching_approve',
      'sanctuary_id': _sanctuaryId,
    }));
  }

  void _declineGroupCoaching() {
    _channel?.sink.add(jsonEncode({
      'type': 'sanctuary_group_coaching_decline',
      'sanctuary_id': _sanctuaryId,
    }));
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
              _declineGroupCoaching();
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
        // Now request or create the sanctuary (event-driven, not timer-based)
        final familyId = widget.profile['family_id'];
        final hardwareId = widget.profile['hardware_id'] ?? 'GUEST';
        debugLog('>>> SANCTUARY: Checking for existing sanctuary for family $familyId');
        _channel?.sink.add(json.encode({
          "type": "sanctuary_get_or_create",
          "family_id": familyId,
          "member_id": hardwareId,
          "member_name": widget.profile['name'] ?? 'Family Member',
        }));
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
          setState(() {
            _assistedResponse = assistedResponse;
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
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('Assisted response ready!'),
              backgroundColor: Colors.green,
              action: SnackBarAction(
                label: 'Share',
                textColor: Colors.white,
                onPressed: _postAssistedResponse,
              ),
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
        
      // COMPLETION
      case 'sanctuary_completed':
        _showCompletionDialog(data);
        break;
        
      // ERRORS
      case 'error':
        _showError(data['message'] ?? 'An error occurred');
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
              _requestAssistedResponse();
              Future.delayed(const Duration(seconds: 2), () {
                _completeCoaching();
              });
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
                        decoration: InputDecoration(
                          hintText: 'Share with Little Nate (confidential)...',
                          hintStyle: TextStyle(color: Colors.grey[500]),
                          filled: true, fillColor: Colors.grey[900],
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
                          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                        ),
                        onSubmitted: (_) => _sendCoachingMessage(),
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
                    if (_coachingAttempt >= 3)
                      TextButton.icon(
                        onPressed: _requestAssistedResponse,
                        icon: const Icon(Icons.auto_fix_high, size: 18),
                        label: const Text('Get Help (+\$3)'),
                        style: TextButton.styleFrom(foregroundColor: Colors.amber),
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
        );
      },
    );
  }


  @override
  Widget build(BuildContext context) {
    final isNarrow = MediaQuery.of(context).size.width < 420;
    return Scaffold(
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
            },
            itemBuilder: (context) => [
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
                    _groupCoachingRoundActive ? _buildGroupCoachingLockedFooter() : _buildInputArea(),
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
            Text(
              content,
              style: const TextStyle(color: Colors.white, fontSize: 15),
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

  Widget _buildInputArea() {
    return Container(
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
          // Speech-to-text button (ACCESSIBILITY)
          IconButton(
            icon: Icon(
              _isListening ? Icons.mic : Icons.mic_none,
              color: _isListening ? Colors.red : (_speechAvailable ? Colors.white : Colors.grey),
            ),
            onPressed: _speechAvailable ? _toggleListening : null,
            tooltip: _speechAvailable ? 'Speak your message' : 'Speech not available',
          ),
          
          // Text input
          Expanded(
            child: TextField(
              controller: _messageController,
              style: const TextStyle(color: Colors.white),
              maxLines: null,
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
          
          // Send button
          IconButton(
            icon: const Icon(Icons.send, color: Color(0xFF003366)),
            onPressed: _sendMessage,
          ),
        ],
      ),
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
  const LobbyScreen({super.key});

  @override
  _LobbyScreenState createState() => _LobbyScreenState();
}

class _LobbyScreenState extends State<LobbyScreen> {
  final HardwareIdentity _identity = HardwareIdentity();
  WebSocketChannel? _channel;
  StreamSubscription? _lobbySub;
  
  // Connection State
  bool _isConnected = false;
  String _statusMessage = "Initializing...";
  bool _isLoading = false;

  // Credentials for Handoff
  String _tempUser = "";
  String _tempPass = "";

  // Admin gate-check: true when we are verifying admin credentials before redirect
  bool _adminGateCheck = false;
  
  // Resolve dynamically so `/#/?ws=...` overrides apply without rebuilding.
  String get _serverUrl => defaultWsUrl;

  @override
  void initState() {
    super.initState();
    _connectToBridge();
  }

  @override
  void dispose() {
    _lobbySub?.cancel();
    _channel?.sink.close();
    super.dispose();
  }

  void _connectToBridge() {
    setState(() {
      _statusMessage = "Connecting to $_serverUrl...";
      _isConnected = false;
    });

    try {
      _lobbySub?.cancel();
      _channel?.sink.close();
      _channel = WebSocketChannel.connect(Uri.parse(_serverUrl));

      // On Flutter web, websocket failures can surface as unhandled async errors unless
      // we provide an explicit onError handler.
      _lobbySub = _channel!.stream.listen(
        _handlePacket,
        onError: (e) {
          debugLog("Lobby Socket Error: $e");
          if (mounted) {
            setState(() {
              _isConnected = false;
              _statusMessage = "Connection Failed.\n$_serverUrl";
            });
          }
        },
        onDone: () {
          debugLog("Lobby Socket Closed");
          if (mounted) {
            setState(() {
              _isConnected = false;
              _statusMessage = "Disconnected.\n$_serverUrl";
            });
          }
        },
        cancelOnError: true,
      );

      // IMPORTANT:
      // Don't block login on receiving a first packet. Some browser/websocket timing
      // edge-cases can miss the server's immediate "connected" greeting.
      // We'll allow login attempts immediately; onError/onDone will flip state back.
      if (mounted) {
        setState(() {
          _isConnected = true;
          _statusMessage = "Awaiting handshake...\n$_serverUrl";
        });
      }

    } catch (e) {
      if (mounted) setState(() => _statusMessage = "Fatal Connection Error: $e");
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
        
        Map<String, dynamic> profile = data['profile'];
        String role = profile['role'] ?? "CLIENT";
        String token = data['token'] ?? "";

        // ---------------------------------------------------------------
        // ADMIN GATE-CHECK: If we were verifying admin credentials at the
        // gateway (app.*), redirect the browser to command.* instead of
        // navigating to the admin dashboard within Flutter.
        // ---------------------------------------------------------------
        if (_adminGateCheck) {
          _adminGateCheck = false;
          if (kIsWeb) {
            // Use url_launcher to redirect to the admin command portal
            launchUrl(
              Uri.parse('https://command.sovereignsanctuary.net'),
              mode: LaunchMode.externalApplication,
            );
          }
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
              content: Text("Admin verified. Redirecting to Sovereign Command..."),
              backgroundColor: Color(0xFFC9A962),
            ));
          }
          return;
        }
        
        // Close the Lobby socket - next screen will create its own authenticated connection.
        // Cancel subscription FIRST to prevent Uncaught Error from onDone firing after navigation.
        _lobbySub?.cancel();
        _lobbySub = null;
        // Don't close inside the stream callback — let dispose() handle it.
        // On Flutter web, closing inside the callback causes an unhandled async error
        // that can block Navigator.pushReplacement from completing.

        // Defer navigation to next frame so it runs OUTSIDE the stream callback,
        // avoiding the Flutter web "Uncaught Error" from MutationObserver conflicts.
        final user = _tempUser;
        final pass = _tempPass;
        final consentNeeded = data['consent_update_needed'] == true;
        
        WidgetsBinding.instance.addPostFrameCallback((_) {
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
              // Check if COACH_ONLY client
              final subPlan = (profile['subscription_plan'] ?? '').toString().toUpperCase();
              final canAccessNate = profile['can_access_nate'] ?? true;
              if (subPlan == 'COACH_ONLY' || canAccessNate == false) {
                // COACH_ONLY clients get scheduling-only screen
                nextScreen = ClientScheduleScreen(currentUserProfile: profileWithToken, username: user, password: pass);
              } else {
                nextScreen = NeuralInterfaceV2(currentUserProfile: profileWithToken, username: user, password: pass);
              }
            }

            Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => nextScreen));
          }
        });
        
      } else if (data['type'] == 'login_failed') {
        // Safely close loading dialog if one is open
        try { Navigator.pop(context); } catch (_) {}
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text(data['message'] ?? 'Login failed'),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 4),
          ));
          setState(() => _isLoading = false);
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
            content: Text("Password updated. Please log in."),
            backgroundColor: Colors.green,
          ));
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

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
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
            TextField(controller: passCtrl, obscureText: true, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "KEY", prefixIcon: Icon(Icons.vpn_key))),
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
                "expected_role": "ADMIN"
              }));

              Navigator.pop(ctx);
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Verifying admin credentials...")));
            },
          ),
        ],
      ),
    );
  }

  void _showLoginDialog(String expectedRole) {
    if (!_isConnected) {
      // Try to reconnect, but don't block the coach from attempting login.
      _connectToBridge();
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Reconnecting...")));
    }

    TextEditingController userCtrl = TextEditingController();
    TextEditingController passCtrl = TextEditingController();
    
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: Text("$expectedRole ACCESS", style: const TextStyle(color: Color(0xFFFFD700), fontFamily: 'Courier')),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(controller: userCtrl, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "IDENTITY", prefixIcon: Icon(Icons.fingerprint))),
            const SizedBox(height: 10),
            TextField(controller: passCtrl, obscureText: true, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "KEY", prefixIcon: Icon(Icons.vpn_key))),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: () { Navigator.pop(ctx); _showForgotUsernameDialog(); },
                  child: const Text("Forgot username?", style: TextStyle(color: Colors.grey, fontSize: 12)),
                ),
                TextButton(
                  onPressed: () { Navigator.pop(ctx); _showForgotPasswordMethodDialog(); },
                  child: const Text("Forgot password?", style: TextStyle(color: Colors.grey, fontSize: 12)),
                ),
              ],
            ),
          ],
        ),
        actions: [
          TextButton(child: const Text("ABORT"), onPressed: () => Navigator.pop(ctx)),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFFFD700), foregroundColor: Colors.black),
            child: const Text("VERIFY"),
            onPressed: () {
              // 1. Save Credentials
              _tempUser = userCtrl.text.trim();
              _tempPass = passCtrl.text.trim();
              
              // 2. Send Login
              _channel?.sink.add(jsonEncode({
                "type": "login_request",
                "username": _tempUser,
                "password": _tempPass,
                "expected_role": expectedRole
              }));

              // 3. Show Loading (Don't close dialog yet, wait for response)
              Navigator.pop(ctx); 
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Verifying Credentials...")));
            },
          )
        ],
      ),
    );
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
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
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
              obscureText: true,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: "New password",
                prefixIcon: Icon(Icons.vpn_key, color: Colors.grey),
              ),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: confirmCtrl,
              obscureText: true,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: "Confirm password",
                prefixIcon: Icon(Icons.vpn_key, color: Colors.grey),
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
  int _step = 0; // 0: consent+role, 1: tier/dojo, 2: form
  bool _consentGiven = false;
  String? _selectedRole; // CLIENT or COACH
  String _selectedTier = 'TRIAL'; // COACH_ONLY, TRIAL, STANDARD, TOP_TIER
  List<String> _selectedDojos = []; // coach dojo picks
  DateTime? _dob;
  final _nameCtrl = TextEditingController();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final List<String> _endpoints = [defaultWsUrl];
  bool _isDependent = false;
  TextEditingController _parentCtrl = TextEditingController();
  WebSocketChannel? _regSocket;

  // Dojo pricing
  static const Map<String, double> _dojoPrices = {
    'therapist': 175.0,
    'project_pm': 250.0,
    'business': 325.0,
    'cnc': 150.0,
    'mcat': 500.0,
    'teacher': 225.0,
    'judge': 2100.0,
  };
  static const Map<String, String> _dojoLabels = {
    'cnc': 'CNC Machining',
    'therapist': 'Therapist',
    'teacher': 'Teacher',
    'project_pm': 'Project PM',
    'business': 'Business',
    'mcat': 'MCAT',
    'judge': 'Judge',
  };
  // JUDGE is excluded from multi-DOJO volume discounts
  static const List<int> _dojoDiscounts = [0, 0, 10, 15, 20, 25, 30]; // index = count (excl. JUDGE)

  // Beta invite code
  final _betaCodeCtrl = TextEditingController();
  bool get _isBetaCodeEntered => _betaCodeCtrl.text.trim().isNotEmpty;

  // Coach invite token (from URL ?invite=TOKEN when client arrives via coach invite link)
  String? _coachInviteToken;

  // Contact fields
  final _emailCtrl = TextEditingController();
  final _phoneCtrl = TextEditingController();

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

  @override
  void initState() {
    super.initState();
    _selectedRole = widget.role; // Pre-set if passed
    _parseCoachInviteFromUrl();
    _sanitizeSession();
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

  void _submitRegistration() {
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
    // Coach-specific validations (skipped when beta invite code is provided)
    if (_effectiveRole == "COACH" && !_isBetaCodeEntered) {
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
    if (_userCtrl.text.trim().isEmpty || _passCtrl.text.trim().isEmpty) {
       ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Username and Password are required")));
       return;
    }

    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Sending Data to Neural Core...")));

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
      // Beta invite code (if provided, skips verification)
      "beta_invite_code": _betaCodeCtrl.text.trim(),
      // Contact info
      "email": _emailCtrl.text.trim(),
      "phone": _phoneCtrl.text.trim(),
      // Tier/plan selection (clients)
      "registration_type": role == "CLIENT" ? _selectedTier : null,
      // Coach invite token (when client arrives via coach invite link)
      if (role == "CLIENT" && _coachInviteToken != null) "coach_invite_token": _coachInviteToken,
      // Dojo selection (coaches)
      "selected_dojos": role == "COACH" ? _selectedDojos : null,
      "dojo_discount_pct": role == "COACH" ? _calculateDojoDiscount() : null,
      "dojo_monthly_price": role == "COACH" ? _calculateDojoPrice() : null,
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
        HardwareIdentity().saveSession(_userCtrl.text, "NEW_REG_TOKEN", data['profile']);

        final profile = Map<String, dynamic>.from(data['profile'] ?? {});
        final regRole = (profile['role'] ?? _effectiveRole).toString();
        final token = data['token'] ?? "";

        // Defer sink close to avoid "Cannot add event after closing" — closing
        // synchronously inside the stream callback can race with the WebSocket impl.
        Future.microtask(() {
          try { regSocket.sink.close(); } catch (_) {}
          _regSocket = null;
        });

        // Coaches go to pending approval dialog, not onboarding
        if (regRole == "COACH") {
          _showCoachPendingDialog();
        } else {
          // Clients go to onboarding tutorial
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
        // Coaches with PENDING_VERIFICATION can't login — show pending dialog
        if (regRole == "COACH") {
          Future.microtask(() {
            try { regSocket.sink.close(); } catch (_) {}
            _regSocket = null;
          });
          _showCoachPendingDialog();
        } else {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Identity Created. Logging in...")));
          regSocket.sink.add(jsonEncode({
             "type": "login_request",
             "username": _userCtrl.text.trim(),
             "password": _passCtrl.text.trim(),
             "expected_role": regRole
          }));
        }
      }
      
      // CASE C: Error (handle all error-like response types)
      else if (data['type'] == 'error' || data['type'] == 'registration_failed') {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text("FAILURE: ${data['message'] ?? 'Registration failed'}"),
          backgroundColor: Colors.red,
          duration: const Duration(seconds: 8),
        ));
      }

      // CASE D: Unknown response - show it so we can debug
      else {
        debugLog(">>> [REG] Unhandled response type: ${data['type']}");
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text("Server: ${data['type']} — ${data['message'] ?? jsonEncode(data)}"),
          duration: const Duration(seconds: 5),
        ));
      }
    }, onError: (e) {
      debugLog(">>> [REG] WebSocket error: $e");
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("Connection Error: $e"), backgroundColor: Colors.red));
    }, onDone: () {
      debugLog(">>> [REG] WebSocket closed (regSent=$regSent)");
      _regSocket = null;
      if (!regSent) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text("Connection dropped before registration could be sent. Please try again."),
          backgroundColor: Colors.red,
        ));
      }
    });
  }

  void _handleLoginSuccess(Map<String, dynamic> data, WebSocketChannel burnerSocket) {
        HardwareIdentity().saveSession(_userCtrl.text, "NEW_REG_TOKEN", data['profile']);
        burnerSocket.sink.close();
        final chatSocket = WebSocketChannel.connect(Uri.parse(_endpoints[0]));
        chatSocket.sink.add(jsonEncode({
           "type": "login_request",
           "username": _userCtrl.text.trim(),
           "password": _passCtrl.text.trim(),
           "expected_role": _effectiveRole
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
          "AI companion, therapy, coaching, family wellness",
          Icons.self_improvement,
          Colors.blueAccent,
          "CLIENT",
        ),
        const SizedBox(height: 16),
        _buildRoleCard(
          "I'm a Coach",
          "Coach Command, DOJO training, mentoring — requires approval",
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
          Text("All tiers start free during beta", style: TextStyle(color: Colors.grey[500], fontSize: 13)),
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
          const SizedBox(height: 20),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.blueAccent.withOpacity(0.08),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.blueAccent.withOpacity(0.3)),
            ),
            child: Row(
              children: [
                const Icon(Icons.info_outline, color: Colors.blueAccent, size: 18),
                const SizedBox(width: 10),
                Expanded(child: Text("Beta: No charge during testing period", style: TextStyle(color: Colors.blueAccent[100], fontSize: 12))),
              ],
            ),
          ),
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
                    Expanded(child: Text("BETA: No charge during testing period", style: TextStyle(color: const Color(0xFFFFD700).withOpacity(0.9), fontSize: 12, fontWeight: FontWeight.bold))),
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

            // 2.4 BETA INVITE CODE (Coaches only)
            if (_effectiveRole == "COACH") ...[
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  border: Border.all(color: const Color(0xFF9D4EDD).withOpacity(0.5)),
                  borderRadius: BorderRadius.circular(12),
                  color: const Color(0xFF9D4EDD).withOpacity(0.06),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.science, color: Color(0xFF9D4EDD), size: 20),
                        const SizedBox(width: 8),
                        const Text("BETA ACCESS", style: TextStyle(color: Color(0xFF9D4EDD), fontWeight: FontWeight.bold, fontFamily: 'Courier', fontSize: 13)),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      "Have a beta invite code? Enter it below to skip identity verification during testing.",
                      style: TextStyle(color: Colors.grey[500], fontSize: 12),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _betaCodeCtrl,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        labelText: "Beta Invite Code (optional)",
                        prefixIcon: const Icon(Icons.vpn_key, color: Color(0xFF9D4EDD)),
                        suffixIcon: _isBetaCodeEntered
                            ? const Icon(Icons.check_circle, color: Color(0xFF9D4EDD), size: 20)
                            : null,
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                    if (_isBetaCodeEntered) ...[
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          const Icon(Icons.info_outline, color: Color(0xFF9D4EDD), size: 14),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              "Beta mode: contact info, W-9, and document upload are optional.",
                              style: TextStyle(color: Colors.grey[400], fontSize: 11, fontStyle: FontStyle.italic),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 20),
            ],

            // 2.5 CONTACT INFO (Coaches - required; Clients - optional)
            if (_effectiveRole == "COACH") ...[
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
                    Text("Required for identity verification and communication.", style: TextStyle(color: Colors.grey[500], fontSize: 12)),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _emailCtrl,
                      keyboardType: TextInputType.emailAddress,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        labelText: "Email Address *",
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
                        labelText: "Phone Number *",
                        hintText: "(XXX) XXX-XXXX",
                        prefixIcon: const Icon(Icons.phone),
                        suffixIcon: _phoneCtrl.text.replaceAll(RegExp(r'[^0-9]'), '').length >= 10
                            ? const Icon(Icons.check_circle, color: Color(0xFF4ECDC4), size: 20)
                            : null,
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
            ],

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
            TextField(controller: _passCtrl, obscureText: true, style: const TextStyle(color: Colors.white), decoration: const InputDecoration(labelText: "Create Password", prefixIcon: Icon(Icons.lock))),
            
            const SizedBox(height: 40),
            ElevatedButton(
              onPressed: _submitRegistration, 
              style: ElevatedButton.styleFrom(backgroundColor: Colors.blueAccent, minimumSize: const Size(double.infinity, 50)),
              child: const Text("CREATE ACCOUNT", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold))
            )
          ],
        ),
      ), 
    );
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
    final ws = WebSocketChannel.connect(Uri.parse(defaultWsUrl));
    ws.stream.listen((message) {
      final data = jsonDecode(message);
      if (data['type'] == 'login_success' || data['type'] == 'consent_updated') {
        Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LobbyScreen()), (r) => false); 
      }
    });
    // Login first, then accept consent
    ws.sink.add(jsonEncode({
      "type": "login_request",
      "username": widget.username, 
      "password": widget.password,
      "hardware_id": "WEB_RECONSENT"
    }));
    // After login succeeds, the stream handler above will see login_success
    // Send consent acceptance right after login
    Future.delayed(const Duration(milliseconds: 500), () {
      ws.sink.add(jsonEncode({"type": "accept_consent_update"}));
    });
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
              
              _Header("9. BIOMETRIC DATA & PRIVACY WAIVER"),
              Text("1. VIDEO & VOICE: You explicitly consent to the AI analysis of your Voice (Voiceprint) AND Facial Geometry (Video Biometrics).\n2. PROCESSING: Data is encrypted and processed by third-party cloud engines (Azure OpenAI).\n3. SOVEREIGNTY: You retain the 'Right to Delete.'", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("10. HOLD HARMLESS WAIVER"),
              Text("You voluntarily agree to hold the Developers harmless from any claims arising from data breaches, Coach interactions, or AI outputs.", style: TextStyle(color: Colors.white70)),
              SizedBox(height: 15),
              
              _Header("11. DISPUTE RESOLUTION"),
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
  final String _serverUrl = getWebSocketUrl();
  List<Map<String, dynamic>> _upcomingSessions = [];
  List<Map<String, dynamic>> _availableSlots = [];
  String? _selectedDate;
  bool _isLoading = true;
  bool _isBooking = false;
  String _coachId = '';
  
  @override
  void initState() {
    super.initState();
    _coachId = (widget.currentUserProfile?['assigned_coach_id'] ?? '').toString();
    _connect();
  }
  
  void _connect() {
    try {
      _socket = WebSocketChannel.connect(Uri.parse(_serverUrl));
      _socket!.stream.listen(_handleMessage, onError: (e) => debugLog('WS Error: $e'), onDone: () {
        Future.delayed(const Duration(seconds: 3), _connect);
      });
      _socket!.sink.add(jsonEncode({
        "type": "login_request",
        "username": widget.username ?? '',
        "password": widget.password ?? '',
      }));
    } catch (e) {
      debugLog('Connection error: $e');
    }
  }
  
  void _handleMessage(dynamic event) {
    try {
      final data = jsonDecode(event.toString());
      final type = data['type']?.toString() ?? '';
      
      if (type == 'login_success') {
        // Fetch upcoming sessions
        _requestUpcomingSessions();
      } else if (type == 'client_upcoming_sessions') {
        setState(() {
          _upcomingSessions = List<Map<String, dynamic>>.from(
            (data['sessions'] ?? []).map((s) => Map<String, dynamic>.from(s))
          );
          _isLoading = false;
        });
      } else if (type == 'coach_availability') {
        setState(() {
          _availableSlots = List<Map<String, dynamic>>.from(
            (data['available_slots'] ?? []).map((s) => Map<String, dynamic>.from(s))
          );
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
      } else if (type == 'error') {
        setState(() => _isBooking = false);
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
    setState(() => _selectedDate = date);
    _socket?.sink.add(jsonEncode({
      "type": "client_get_coach_availability",
      "coach_id": _coachId,
      "date": date,
    }));
  }
  
  void _bookSession(String start, String end) {
    setState(() => _isBooking = true);
    _socket?.sink.add(jsonEncode({
      "type": "client_book_session",
      "coach_id": _coachId,
      "scheduled_start": start,
      "scheduled_end": end,
    }));
  }
  
  void _cancelSession(String sessionId) {
    _socket?.sink.add(jsonEncode({
      "type": "client_cancel_session",
      "session_id": sessionId,
    }));
  }
  
  @override
  void dispose() {
    _socket?.sink.close();
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
        : SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Upcoming Sessions
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
                    child: const Center(
                      child: Text('No upcoming sessions', style: TextStyle(color: Colors.grey)),
                    ),
                  )
                else
                  ..._upcomingSessions.map((s) => _buildSessionCard(s)),
                
                const SizedBox(height: 24),
                
                // Book New Session
                const Text('BOOK A SESSION', style: TextStyle(color: Colors.grey, fontSize: 11, letterSpacing: 1.5, fontWeight: FontWeight.w600)),
                const SizedBox(height: 12),
                _buildDatePicker(),
                if (_availableSlots.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  const Text('Available Time Slots', style: TextStyle(color: Color(0xFFC9A962), fontSize: 14, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  ..._availableSlots.map((slot) => _buildSlotCard(slot)),
                ] else if (_selectedDate != null) ...[
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFF111111),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Text('No available slots for this date', style: TextStyle(color: Colors.grey)),
                  ),
                ],
              ],
            ),
          ),
    );
  }
  
  Widget _buildSessionCard(Map<String, dynamic> session) {
    final start = session['scheduled_start'] ?? '';
    final zoomLink = session['zoom_link'] ?? '';
    final status = session['status'] ?? 'scheduled';
    
    String formattedTime = start;
    try {
      final dt = DateTime.parse(start);
      formattedTime = '${dt.month}/${dt.day}/${dt.year} at ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) {}
    
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
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
              const Icon(Icons.calendar_today, color: Color(0xFF4ECDC4), size: 18),
              const SizedBox(width: 8),
              Expanded(child: Text(formattedTime, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: status == 'scheduled' ? const Color(0xFF4ECDC4).withOpacity(0.15) : Colors.grey.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(status.toUpperCase(), style: TextStyle(color: status == 'scheduled' ? const Color(0xFF4ECDC4) : Colors.grey, fontSize: 10, fontWeight: FontWeight.w600)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              if (zoomLink.isNotEmpty)
                Expanded(
                  child: ElevatedButton.icon(
                    icon: const Icon(Icons.videocam, size: 16),
                    label: const Text('Join Zoom', style: TextStyle(fontSize: 12)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF2D8CFF),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 8),
                    ),
                    onPressed: () async {
                      final uri = Uri.parse(zoomLink);
                      if (await canLaunchUrl(uri)) {
                        await launchUrl(uri, mode: LaunchMode.externalApplication);
                      }
                    },
                  ),
                ),
              if (zoomLink.isNotEmpty) const SizedBox(width: 8),
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
    
    String label = start;
    try {
      final dtStart = DateTime.parse(start);
      final dtEnd = DateTime.parse(end);
      label = '${dtStart.hour}:${dtStart.minute.toString().padLeft(2, '0')} - ${dtEnd.hour}:${dtEnd.minute.toString().padLeft(2, '0')}';
    } catch (_) {}
    
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
