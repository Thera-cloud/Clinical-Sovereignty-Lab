// =============================================================================
// LIMINAL PRESENCE SCREEN — Main hub for external conversation coaching
//
// Tier gate: TRIAL, STANDARD, TOP_TIER clients only.
// Platforms: SMS, Facebook Messenger, LinkedIn DMs, X DMs, Instagram DMs.
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config/app_config.dart';
import 'companion_chat_screen.dart';
import 'live_call_screen.dart';

// =============================================================================
// DESIGN TOKENS
// =============================================================================

class _D {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const red = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const textMuted = Color(0xFF555555);
  static const border = Color(0xFF252525);
}

const _allowedPlatforms = [
  ('sms', 'SMS'),
  ('facebook_messenger', 'Facebook Messenger'),
  ('linkedin', 'LinkedIn DMs'),
  ('x', 'X DMs'),
  ('instagram', 'Instagram DMs'),
];

const _allowedTiers = {'TRIAL', 'STANDARD', 'TOP_TIER', 'THRESHOLD', 'INNER_CHAMBER', 'SOVEREIGN_CIRCLE'};

// =============================================================================
// LIMINAL PRESENCE SCREEN
// =============================================================================

class LiminalPresenceScreen extends StatefulWidget {
  final Map<String, dynamic> profile;

  const LiminalPresenceScreen({super.key, required this.profile});

  @override
  State<LiminalPresenceScreen> createState() => _LiminalPresenceScreenState();
}

class _LiminalPresenceScreenState extends State<LiminalPresenceScreen> {
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  String? _token;
  bool _authConfirmed = false;
  bool _connecting = true;
  String? _error;
  final Set<String> _selectedPlatforms = {'sms'};
  final _recallController = TextEditingController();
  List<Map<String, dynamic>> _recallSessions = [];
  bool _recallLoading = false;
  bool _notificationListenerEnabled = false;

  String get _userId => widget.profile['hardware_id']?.toString() ?? '';

  bool get _isTierAllowed {
    final plan = (widget.profile['subscription_plan'] ?? widget.profile['tier'] ?? '').toString().toUpperCase();
    return _allowedTiers.any((t) => plan.contains(t) || plan.contains(t.replaceAll('_', ' ')));
  }

  @override
  void initState() {
    super.initState();
    _resolveTokenAndConnect();
    _loadNotificationPrefs();
  }

  Future<void> _loadNotificationPrefs() async {
    if (kIsWeb) return;
    try {
      const storage = FlutterSecureStorage(aOptions: AndroidOptions(encryptedSharedPreferences: true));
      final enabled = await storage.read(key: 'liminal_notification_listener');
      if (!mounted) return;
      setState(() {
        _notificationListenerEnabled = enabled == 'true';
      });
    } catch (_) {}
  }

  Future<void> _resolveTokenAndConnect() async {
    _token = widget.profile['token']?.toString();
    if (_token == null || _token!.isEmpty) {
      try {
        const storage = FlutterSecureStorage(aOptions: AndroidOptions(encryptedSharedPreferences: true));
        _token = await storage.read(key: 'session_token');
      } catch (_) {}
    }
    if (_token == null || _token!.isEmpty) {
      if (mounted) {
        setState(() {
          _connecting = false;
          _error = 'Session expired. Please log in again.';
        });
      }
      return;
    }
    _connect();
  }

  void _connect() {
    setState(() {
      _connecting = true;
      _error = null;
      _authConfirmed = false;
    });
    _channel?.sink.close();
    _channel = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
    _subscription?.cancel();
    _subscription = _channel!.stream.listen(
      _onMessage,
      onError: (e) {
        if (mounted) {
          setState(() {
            _connecting = false;
            _error = 'Connection error: $e';
          });
        }
      },
      onDone: () {
        if (mounted) setState(() => _connecting = false);
      },
    );
    _channel!.sink.add(jsonEncode({
      'type': 'auth',
      'token': _token,
      'hardware_id': _userId,
    }));
  }

  void _onMessage(dynamic raw) {
    if (!mounted) return;
    try {
      final data = jsonDecode(raw.toString()) as Map<String, dynamic>;
      final type = data['type'] as String? ?? '';
      switch (type) {
        case 'auth_success':
          setState(() {
            _authConfirmed = true;
            _connecting = false;
            _error = null;
          });
          break;
        case 'auth_failed':
          setState(() {
            _authConfirmed = false;
            _connecting = false;
            _error = 'Authentication failed. Please log in again.';
          });
          break;
        case 'liminal_recall_response':
          setState(() {
            _recallLoading = false;
            final sessions = data['sessions'];
            _recallSessions = sessions is List
                ? (sessions as List<dynamic>).map<Map<String, dynamic>>((e) => Map<String, dynamic>.from(e as Map)).toList()
                : <Map<String, dynamic>>[];
          });
          break;
        case 'error':
          setState(() {
            _recallLoading = false;
            _error = data['message']?.toString() ?? 'Unknown error';
          });
          break;
      }
    } catch (_) {}
  }

  void _sendRecallRequest() {
    final alias = _recallController.text.trim();
    if (alias.isEmpty || !_authConfirmed) return;
    setState(() => _recallLoading = true);
    _channel?.sink.add(jsonEncode({
      'type': 'liminal_recall_request',
      'contact_alias': alias,
    }));
  }

  void _togglePlatform(String key) {
    setState(() {
      if (_selectedPlatforms.contains(key)) {
        if (_selectedPlatforms.length > 1) {
          _selectedPlatforms.remove(key);
        }
      } else {
        _selectedPlatforms.add(key);
      }
    });
  }

  Future<void> _saveNotificationPref(bool enabled) async {
    if (kIsWeb) return;
    try {
      const storage = FlutterSecureStorage(aOptions: AndroidOptions(encryptedSharedPreferences: true));
      await storage.write(key: 'liminal_notification_listener', value: enabled ? 'true' : 'false');
    } catch (_) {}
  }

  void _openCompanionChat({String? contactAlias}) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (ctx) => CompanionChatScreen(
          profile: widget.profile,
          contactAlias: contactAlias ?? (_recallController.text.trim().isEmpty ? null : _recallController.text.trim()),
          initialPlatform: _selectedPlatforms.isNotEmpty ? _selectedPlatforms.first : 'sms',
        ),
      ),
    );
  }

  void _openLiveCall() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (ctx) => LiveCallScreen(profile: widget.profile),
      ),
    );
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _channel?.sink.close();
    _recallController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_isTierAllowed) {
      return Scaffold(
        backgroundColor: _D.bgVoid,
        appBar: AppBar(
          backgroundColor: _D.bgChamber,
          title: Text(
            'Liminal Presence',
            style: GoogleFonts.cormorantGaramond(
              fontSize: 20,
              fontWeight: FontWeight.w600,
              color: _D.goldBright,
            ),
          ),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back, color: _D.textPrimary),
            onPressed: () => Navigator.of(context).pop(),
          ),
        ),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.lock, size: 48, color: _D.goldDim),
                const SizedBox(height: 16),
                Text(
                  'Liminal Presence is available for Threshold, Inner Chamber, and Sovereign Circle members.',
                  style: GoogleFonts.dmSans(color: _D.textSecondary, fontSize: 14),
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgChamber,
        title: Text(
          'Liminal Presence',
          style: GoogleFonts.cormorantGaramond(
            fontSize: 20,
            fontWeight: FontWeight.w600,
            color: _D.goldBright,
          ),
        ),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: _D.textPrimary),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
      body: _connecting && !_authConfirmed
          ? Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const CircularProgressIndicator(color: _D.gold),
                  const SizedBox(height: 16),
                  Text(
                    'Connecting…',
                    style: GoogleFonts.dmSans(color: _D.textSecondary, fontSize: 14),
                  ),
                ],
              ),
            )
          : SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (_error != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: _D.red.withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: _D.red.withValues(alpha: 0.5)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.error_outline, color: _D.red, size: 20),
                          const SizedBox(width: 8),
                          Expanded(child: Text(_error!, style: GoogleFonts.dmSans(color: _D.red, fontSize: 13))),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],
                  // a. Platform selector
                  Text(
                    'Platforms',
                    style: GoogleFonts.cormorantGaramond(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: _D.gold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: _allowedPlatforms.map((e) {
                      final key = e.$1;
                      final label = e.$2;
                      final selected = _selectedPlatforms.contains(key);
                      return FilterChip(
                        label: Text(label, style: GoogleFonts.dmSans(fontSize: 12)),
                        selected: selected,
                        onSelected: (_) => _togglePlatform(key),
                        backgroundColor: _D.bgChamber,
                        selectedColor: _D.gold.withValues(alpha: 0.25),
                        checkmarkColor: _D.gold,
                        side: BorderSide(color: selected ? _D.gold : _D.border),
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: 24),
                  // b. Active conversations (placeholder — backend could provide via API)
                  Text(
                    'Recent Conversations',
                    style: GoogleFonts.cormorantGaramond(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: _D.gold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: _D.bgChamber,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: _D.border),
                    ),
                    child: Text(
                      'Conversations Nate has observed appear here after you use In-App Relay.',
                      style: GoogleFonts.dmSans(color: _D.textMuted, fontSize: 13),
                    ),
                  ),
                  const SizedBox(height: 24),
                  // c. Bring up conversation
                  Text(
                    'Bring up conversation with',
                    style: GoogleFonts.cormorantGaramond(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: _D.gold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _recallController,
                          decoration: InputDecoration(
                            hintText: 'e.g. Mom, Boss, Sarah',
                            hintStyle: const TextStyle(color: _D.textMuted),
                            filled: true,
                            fillColor: _D.bgChamber,
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: _D.border)),
                            focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: const BorderSide(color: _D.gold)),
                          ),
                          style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 14),
                          onSubmitted: (_) => _sendRecallRequest(),
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton.filled(
                        onPressed: _recallLoading ? null : _sendRecallRequest,
                        icon: _recallLoading
                            ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: _D.gold))
                            : const Icon(Icons.search),
                        style: IconButton.styleFrom(backgroundColor: _D.gold, foregroundColor: _D.bgVoid),
                      ),
                    ],
                  ),
                  if (_recallSessions.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    ..._recallSessions.take(5).map((s) => Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: InkWell(
                            onTap: () => _openCompanionChat(contactAlias: _recallController.text.trim()),
                            borderRadius: BorderRadius.circular(8),
                            child: Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: _D.bgElevated,
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(color: _D.border),
                              ),
                              child: Row(
                                children: [
                                  Icon(Icons.chat_bubble_outline, color: _D.cyan, size: 20),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      '${s['platform'] ?? 'conversation'} • ${(s['message_count'] ?? 0)} exchanges',
                                      style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 13),
                                    ),
                                  ),
                                  const Icon(Icons.arrow_forward_ios, size: 12, color: _D.textMuted),
                                ],
                              ),
                            ),
                          ),
                        )),
                  ],
                  const SizedBox(height: 24),
                  // d. Quick-launch Companion Chat
                  FilledButton.icon(
                    onPressed: _openCompanionChat,
                    icon: const Icon(Icons.chat),
                    label: Text(
                      'Open In-App Relay',
                      style: GoogleFonts.dmSans(fontSize: 15, fontWeight: FontWeight.w600),
                    ),
                    style: FilledButton.styleFrom(
                      backgroundColor: _D.cyan,
                      foregroundColor: _D.bgVoid,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  // e. Start Live Call
                  OutlinedButton.icon(
                    onPressed: _openLiveCall,
                    icon: const Icon(Icons.phone_in_talk),
                    label: Text(
                      'Start Live Call',
                      style: GoogleFonts.dmSans(fontSize: 15, fontWeight: FontWeight.w600),
                    ),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: _D.gold,
                      side: const BorderSide(color: _D.gold),
                      padding: const EdgeInsets.symmetric(vertical: 16),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                  const SizedBox(height: 24),
                  // f. Settings
                  Text(
                    'Settings',
                    style: GoogleFonts.cormorantGaramond(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: _D.gold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  if (!kIsWeb) ...[
                    SwitchListTile(
                      value: _notificationListenerEnabled,
                      onChanged: (v) {
                        setState(() => _notificationListenerEnabled = v);
                        _saveNotificationPref(v);
                      },
                      title: Text(
                        'Notification listener (Android)',
                        style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 14),
                      ),
                      subtitle: Text(
                        'Allow Nate to observe incoming message notifications',
                        style: GoogleFonts.dmSans(color: _D.textMuted, fontSize: 12),
                      ),
                      activeThumbColor: _D.gold,
                      tileColor: _D.bgChamber,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                    const SizedBox(height: 8),
                  ],
                  ListTile(
                    leading: const Icon(Icons.ios_share, color: _D.gold),
                    title: Text(
                      'Share sheet instructions (iOS)',
                      style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 14),
                    ),
                    subtitle: Text(
                      'Use the Share sheet to send conversation snippets to Little Nate',
                      style: GoogleFonts.dmSans(color: _D.textMuted, fontSize: 12),
                    ),
                    onTap: () {
                      HapticFeedback.mediumImpact();
                      showDialog(
                        context: context,
                        builder: (ctx) => AlertDialog(
                          backgroundColor: _D.bgElevated,
                          title: Text(
                            'Share to Nate',
                            style: GoogleFonts.cormorantGaramond(color: _D.goldBright),
                          ),
                          content: SingleChildScrollView(
                            child: Text(
                              '1. Copy the conversation text from Messages, social apps, or email.\n'
                              '2. Open Little Nate and go to In-App Relay.\n'
                              '3. Paste the text in the "Paste Conversation" area.\n'
                              '4. Tap a quick action (e.g. "What should I say?") to get Nate\'s coaching.',
                              style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 14),
                            ),
                          ),
                          actions: [
                            TextButton(
                              onPressed: () {
                                Navigator.of(ctx).pop();
                                if (!kIsWeb) {
                                  FlutterSecureStorage(aOptions: const AndroidOptions(encryptedSharedPreferences: true))
                                      .write(key: 'liminal_share_instructions_shown', value: 'true');
                                }
                              },
                              child: Text('Got it', style: GoogleFonts.dmSans(color: _D.cyan)),
                            ),
                          ],
                        ),
                      );
                    },
                    tileColor: _D.bgChamber,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                ],
              ),
            ),
    );
  }
}
