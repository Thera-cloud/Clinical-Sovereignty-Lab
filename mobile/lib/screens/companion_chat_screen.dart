// =============================================================================
// COMPANION CHAT SCREEN — In-App Relay coaching
//
// Paste external conversation, get Nate's coaching via WebSocket.
// Quick actions: What should I say?, What are they really saying?, Is this abusive?
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config/app_config.dart';

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

const _questionActions = [
  ('what_to_say', 'What should I say?', Icons.reply),
  ('interpret', 'What are they really saying?', Icons.psychology),
  ('abusive_check', 'Is this abusive language?', Icons.warning_amber_rounded),
];

const _platforms = [
  ('sms', 'SMS'),
  ('facebook_messenger', 'Facebook Messenger'),
  ('linkedin', 'LinkedIn'),
  ('x', 'X'),
  ('instagram', 'Instagram'),
];

// =============================================================================
// COMPANION CHAT SCREEN
// =============================================================================

class CompanionChatScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String? contactAlias;
  final String? initialPlatform;

  const CompanionChatScreen({
    super.key,
    required this.profile,
    this.contactAlias,
    this.initialPlatform,
  });

  @override
  State<CompanionChatScreen> createState() => _CompanionChatScreenState();
}

class _CompanionChatScreenState extends State<CompanionChatScreen> {
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  String? _token;
  bool _authConfirmed = false;
  bool _connecting = true;
  String? _error;

  final _conversationController = TextEditingController();
  final _scrollController = ScrollController();
  String _selectedPlatform = 'sms';
  String? _contactAlias;
  bool _loading = false;

  final List<_ResponseCard> _cards = [];

  String get _userId => widget.profile['hardware_id']?.toString() ?? '';

  @override
  void initState() {
    super.initState();
    _selectedPlatform = widget.initialPlatform ?? 'sms';
    _contactAlias = widget.contactAlias;
    _resolveTokenAndConnect();
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
        case 'liminal_coaching_response':
          _handleCoachingResponse(data);
          break;
        case 'error':
          setState(() {
            _loading = false;
            _error = data['message']?.toString() ?? 'Unknown error';
          });
          break;
      }
    } catch (_) {}
  }

  void _handleCoachingResponse(Map<String, dynamic> data) {
    if (!mounted) return;
    final coaching = data['coaching']?.toString() ?? '';
    final observations = (data['observations'] as List<dynamic>?)
            ?.map((e) => e.toString())
            .where((s) => s.isNotEmpty)
            .toList() ??
        [];
    final flags = (data['flags'] as List<dynamic>?)
            ?.map((e) => e.toString())
            .where((s) => s.isNotEmpty)
            .toList() ??
        [];

    setState(() {
      _loading = false;
      _cards.clear();
      for (final f in flags) {
        _cards.add(_ResponseCard(kind: _CardKind.flag, text: f));
      }
      for (final o in observations) {
        _cards.add(_ResponseCard(kind: _CardKind.observation, text: o));
      }
      if (coaching.isNotEmpty) {
        _cards.add(_ResponseCard(kind: _CardKind.coaching, text: coaching));
      }
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _sendCoachingRequest(String questionType) {
    final context = _conversationController.text.trim();
    if (!_authConfirmed) return;
    setState(() {
      _loading = true;
      _error = null;
      _cards.clear();
    });
    _channel?.sink.add(jsonEncode({
      'type': 'liminal_context_update',
      'conversation_context': context.isEmpty ? '(No conversation pasted yet)' : context,
      'platform': _selectedPlatform,
      'question_type': questionType,
      'contact_alias': _contactAlias,
    }));
  }

  @override
  void dispose() {
    _subscription?.cancel();
    _channel?.sink.close();
    _conversationController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgChamber,
        title: Text(
          'In-App Relay',
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
          : Column(
              children: [
                // Top half: Paste Conversation
                Expanded(
                  flex: 1,
                  child: Container(
                    margin: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: _D.bgChamber,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: _D.border),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                          child: Row(
                            children: [
                              Text(
                                'Paste Conversation',
                                style: GoogleFonts.cormorantGaramond(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w600,
                                  color: _D.gold,
                                ),
                              ),
                              const Spacer(),
                              // Platform dropdown
                              DropdownButtonHideUnderline(
                                child: DropdownButton<String>(
                                  value: _selectedPlatform,
                                  dropdownColor: _D.bgElevated,
                                  borderRadius: BorderRadius.circular(8),
                                  style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 12),
                                  icon: const Icon(Icons.arrow_drop_down, color: _D.gold),
                                  items: _platforms
                                      .map((e) => DropdownMenuItem(
                                            value: e.$1,
                                            child: Text(e.$2, style: const TextStyle(fontSize: 12)),
                                          ))
                                      .toList(),
                                  onChanged: (v) => setState(() => _selectedPlatform = v ?? 'sms'),
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (_contactAlias != null && _contactAlias!.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                            child: Text(
                              'With $_contactAlias',
                              style: GoogleFonts.dmSans(color: _D.textMuted, fontSize: 12),
                            ),
                          ),
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                            child: TextField(
                              controller: _conversationController,
                              maxLines: null,
                              expands: true,
                              textAlignVertical: TextAlignVertical.top,
                              decoration: InputDecoration(
                                hintText: 'Paste messages from SMS, Messenger, DMs…',
                                hintStyle: const TextStyle(color: _D.textMuted, fontSize: 13),
                                filled: true,
                                fillColor: _D.bgElevated,
                                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                                enabledBorder: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(8),
                                  borderSide: const BorderSide(color: _D.border),
                                ),
                                focusedBorder: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(8),
                                  borderSide: const BorderSide(color: _D.gold),
                                ),
                              ),
                              style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 14),
                            ),
                          ),
                        ),
                        // Quick actions
                        Padding(
                          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                          child: Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: _questionActions.map((e) {
                              final key = e.$1;
                              final label = e.$2;
                              final icon = e.$3;
                              return FilledButton.tonalIcon(
                                onPressed: _loading ? null : () => _sendCoachingRequest(key),
                                icon: Icon(icon, size: 18, color: _D.gold),
                                label: Text(
                                  label,
                                  style: GoogleFonts.dmSans(fontSize: 12, fontWeight: FontWeight.w500),
                                ),
                                style: FilledButton.styleFrom(
                                  backgroundColor: _D.gold.withValues(alpha: 0.2),
                                  foregroundColor: _D.goldBright,
                                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                                ),
                              );
                            }).toList(),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                // Divider
                Container(height: 1, color: _D.border),
                // Bottom half: Nate's response
                Expanded(
                  flex: 1,
                  child: Container(
                    color: _D.bgChamber,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                          child: Row(
                            children: [
                              Icon(Icons.auto_awesome, color: _D.cyan, size: 18),
                              const SizedBox(width: 8),
                              Text(
                                "Nate's Coaching",
                                style: GoogleFonts.cormorantGaramond(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w600,
                                  color: _D.cyan,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (_error != null)
                          Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 16),
                            child: Container(
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
                                  Expanded(
                                    child: Text(
                                      _error!,
                                      style: GoogleFonts.dmSans(color: _D.red, fontSize: 13),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        if (_loading)
                          const Padding(
                            padding: EdgeInsets.all(24),
                            child: Center(
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  CircularProgressIndicator(color: _D.cyan),
                                  SizedBox(height: 12),
                                  Text(
                                    "Nate is thinking…",
                                    style: TextStyle(color: _D.textSecondary, fontSize: 13),
                                  ),
                                ],
                              ),
                            ),
                          )
                        else if (_cards.isEmpty && !_loading)
                          Expanded(
                            child: Center(
                              child: Text(
                                'Paste a conversation and tap a quick action to get coaching.',
                                style: GoogleFonts.dmSans(color: _D.textMuted, fontSize: 14),
                                textAlign: TextAlign.center,
                              ),
                            ),
                          )
                        else
                          Expanded(
                            child: ListView.builder(
                              controller: _scrollController,
                              padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                              itemCount: _cards.length,
                              itemBuilder: (ctx, i) => _buildCard(_cards[i], i),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _buildCard(_ResponseCard card, int index) {
    Color bg;
    Color borderColor;
    IconData? icon;
    switch (card.kind) {
      case _CardKind.flag:
        bg = _D.red.withValues(alpha: 0.15);
        borderColor = _D.red;
        icon = Icons.warning_amber_rounded;
        break;
      case _CardKind.observation:
        bg = _D.gold.withValues(alpha: 0.12);
        borderColor = _D.goldDim;
        icon = Icons.visibility_outlined;
        break;
      case _CardKind.coaching:
        bg = _D.cyan.withValues(alpha: 0.12);
        borderColor = _D.cyan;
        icon = Icons.auto_awesome;
        break;
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: borderColor),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon!, size: 22, color: borderColor),
            const SizedBox(width: 12),
            Expanded(
              child: SelectableText(
                card.text,
                style: GoogleFonts.dmSans(
                  color: _D.textPrimary,
                  fontSize: 14,
                  height: 1.5,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// =============================================================================
// HELPERS
// =============================================================================

enum _CardKind { flag, observation, coaching }

class _ResponseCard {
  final _CardKind kind;
  final String text;
  _ResponseCard({required this.kind, required this.text});
}
