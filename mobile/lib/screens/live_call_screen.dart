// =============================================================================
// LIVE CALL SCREEN — Twilio-powered live call coaching
//
// Phone calls with real-time Nate coaching via WebSocket liminal_call_coaching.
// © 2026 Clinical Sovereignty Lab. All rights reserved.
// =============================================================================

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

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

// =============================================================================
// LIVE CALL SCREEN
// =============================================================================

class LiveCallScreen extends StatefulWidget {
  final Map<String, dynamic> profile;

  const LiveCallScreen({super.key, required this.profile});

  @override
  State<LiveCallScreen> createState() => _LiveCallScreenState();
}

class _LiveCallScreenState extends State<LiveCallScreen> {
  final _phoneController = TextEditingController();
  final _contactAliasController = TextEditingController();
  final _coachingScrollController = ScrollController();

  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  String? _token;

  bool _connecting = true;
  bool _authConfirmed = false;
  String? _error;

  bool _callActive = false;
  String? _callSid;
  String? _sessionId;
  int _callTimerSeconds = 0;
  Timer? _timer;
  bool _muted = false;
  bool _speakerOn = false;

  final List<String> _coachingCards = [];
  String? _postCallSummary;
  List<String> _postCallNotes = [];
  bool _loadingInitiate = false;

  int? _tokenRate;
  int _tokenBalance = 0;

  String get _userId => widget.profile['hardware_id']?.toString() ?? '';

  @override
  void initState() {
    super.initState();
    _tokenBalance = (widget.profile['token_balance'] as int?) ?? 0;
    _resolveTokenAndConnect();
    _loadTokenBalance();
  }

  Future<void> _loadTokenBalance() async {
    final token = _token ?? widget.profile['token']?.toString();
    if (token == null) return;
    try {
      final resp = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/users/me'),
        headers: {'Authorization': 'Bearer $token'},
      ).timeout(const Duration(seconds: 10));
      if (resp.statusCode == 200 && mounted) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final profile = data['profile_data'] ?? data;
        setState(() {
          _tokenBalance = (profile['token_balance'] as int?) ?? _tokenBalance;
        });
      }
    } catch (_) {}
  }

  Future<void> _resolveTokenAndConnect() async {
    _token = widget.profile['token']?.toString();
    if (_token == null || _token!.isEmpty) {
      setState(() {
        _connecting = false;
        _error = 'Session expired. Please log in again.';
      });
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
        if (mounted) setState(() => _connecting = false);
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
            _error = 'Authentication failed.';
          });
          break;
        case 'liminal_call_coaching':
          setState(() {
            final coaching = data['coaching']?.toString();
            if (coaching != null && coaching.isNotEmpty) {
              _coachingCards.add(coaching);
              _scrollToBottom();
            }
          });
          break;
      }
    } catch (_) {}
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_coachingScrollController.hasClients) {
        _coachingScrollController.animateTo(
          _coachingScrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _initiateCall() async {
    final number = _phoneController.text.trim().replaceAll(RegExp(r'[^\d+]'), '');
    if (number.length < 10) {
      setState(() => _error = 'Enter a valid phone number.');
      return;
    }
    if (_loadingInitiate || !_authConfirmed) return;

    setState(() {
      _loadingInitiate = true;
      _error = null;
    });

    try {
      final resp = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/calls/initiate'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $_token',
        },
        body: jsonEncode({
          'to_number': number.startsWith('+') ? number : '+1$number',
          'user_id': _userId,
          'contact_alias': _contactAliasController.text.trim().isNotEmpty
              ? _contactAliasController.text.trim()
              : null,
        }),
      ).timeout(const Duration(seconds: 15));

      if (!mounted) return;
      final data = resp.statusCode == 200
          ? jsonDecode(resp.body) as Map<String, dynamic>
          : null;

      if (resp.statusCode == 200 && data != null) {
        setState(() {
          _callActive = true;
          _callSid = data['call_sid']?.toString();
          _sessionId = data['session_id']?.toString();
          _tokenRate = (data['token_rate'] as int?) ?? 50;
          _coachingCards.clear();
          _postCallSummary = null;
          _postCallNotes = [];
          _callTimerSeconds = 0;
          _timer?.cancel();
          _timer = Timer.periodic(const Duration(seconds: 1), (_) {
            if (mounted) setState(() => _callTimerSeconds++);
          });
        });
      } else {
        final err = data?['detail']?.toString() ?? 'Failed to initiate call.';
        setState(() => _error = err is List ? err.join(', ') : err);
      }
    } catch (e) {
      if (mounted) setState(() => _error = 'Network error: $e');
    } finally {
      if (mounted) setState(() => _loadingInitiate = false);
    }
  }

  Future<void> _endCall() async {
    _timer?.cancel();
    _timer = null;
    setState(() {
      _callActive = false;
      _callSid = null;
      _sessionId = null;
    });
    await _loadTokenBalance();
  }

  void _sendQuickAction(String action) {
    if (!_authConfirmed || _coachingCards.isEmpty) return;
    final last = _coachingCards.last;
    _channel?.sink.add(jsonEncode({
      'type': 'liminal_quick_action',
      'action': action,
      'context': last,
      'call_sid': _callSid,
    }));
  }

  @override
  void dispose() {
    _timer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    _phoneController.dispose();
    _contactAliasController.dispose();
    _coachingScrollController.dispose();
    super.dispose();
  }

  String get _formattedTimer {
    final m = _callTimerSeconds ~/ 60;
    final s = _callTimerSeconds % 60;
    return '${m.toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  }

  int get _estimatedCostPerMinute => _tokenRate ?? 50;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _D.bgVoid,
      appBar: AppBar(
        backgroundColor: _D.bgChamber,
        title: Text(
          'Live Call with Nate',
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
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Center(
              child: Text(
                '$_tokenBalance tokens',
                style: GoogleFonts.dmSans(
                  color: _D.gold,
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ),
        ],
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
                    _errorBanner(),
                    const SizedBox(height: 16),
                  ],
                  if (!_callActive) ...[
                    _phoneInputSection(),
                    const SizedBox(height: 16),
                    _tokenEstimator(),
                    const SizedBox(height: 24),
                    _callButton(),
                  ] else ...[
                    _activeCallSection(),
                    const SizedBox(height: 16),
                    _coachingPanel(),
                    const SizedBox(height: 16),
                    _quickActions(),
                    const SizedBox(height: 16),
                    _endCallButton(),
                  ],
                  if (_postCallSummary != null) ...[
                    const SizedBox(height: 24),
                    _postCallDebrief(),
                  ],
                ],
              ),
            ),
    );
  }

  Widget _errorBanner() {
    return Container(
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
            child: Text(_error!, style: GoogleFonts.dmSans(color: _D.red, fontSize: 13)),
          ),
        ],
      ),
    );
  }

  Widget _phoneInputSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Phone number',
          style: GoogleFonts.cormorantGaramond(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: _D.gold,
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _phoneController,
          keyboardType: TextInputType.phone,
          inputFormatters: [
            FilteringTextInputFormatter.allow(RegExp(r'[\d\s\-\(\)\+]')),
          ],
          decoration: InputDecoration(
            hintText: '+1 (555) 123-4567',
            hintStyle: const TextStyle(color: _D.textMuted),
            filled: true,
            fillColor: _D.bgChamber,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: _D.border),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: _D.gold),
            ),
          ),
          style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 16),
        ),
        const SizedBox(height: 12),
        Text(
          'Contact alias (optional)',
          style: GoogleFonts.cormorantGaramond(
            fontSize: 14,
            fontWeight: FontWeight.w500,
            color: _D.textSecondary,
          ),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: _contactAliasController,
          decoration: InputDecoration(
            hintText: 'e.g. Mom, Boss, Sarah',
            hintStyle: const TextStyle(color: _D.textMuted),
            filled: true,
            fillColor: _D.bgChamber,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: _D.border),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: _D.gold),
            ),
          ),
          style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 14),
        ),
      ],
    );
  }

  Widget _tokenEstimator() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _D.bgChamber,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _D.border),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            'Rate',
            style: GoogleFonts.dmSans(color: _D.textSecondary, fontSize: 13),
          ),
          Text(
            '$_estimatedCostPerMinute tokens/min',
            style: GoogleFonts.dmSans(color: _D.gold, fontSize: 13, fontWeight: FontWeight.w500),
          ),
        ],
      ),
    );
  }

  Widget _callButton() {
    return FilledButton.icon(
      onPressed: _loadingInitiate ? null : _initiateCall,
      icon: _loadingInitiate
          ? const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2, color: _D.bgVoid),
            )
          : const Icon(Icons.call),
      label: Text(
        _loadingInitiate ? 'Connecting…' : 'Call',
        style: GoogleFonts.dmSans(fontSize: 16, fontWeight: FontWeight.w600),
      ),
      style: FilledButton.styleFrom(
        backgroundColor: _D.cyan,
        foregroundColor: _D.bgVoid,
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    );
  }

  Widget _activeCallSection() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _D.bgChamber,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: _D.gold.withValues(alpha: 0.5)),
      ),
      child: Column(
        children: [
          Icon(Icons.call, size: 48, color: _D.cyan),
          const SizedBox(height: 12),
          Text(
            _formattedTimer,
            style: GoogleFonts.cormorantGaramond(
              fontSize: 36,
              fontWeight: FontWeight.w600,
              color: _D.goldBright,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              IconButton.filled(
                onPressed: () => setState(() => _muted = !_muted),
                icon: Icon(_muted ? Icons.mic_off : Icons.mic),
                style: IconButton.styleFrom(
                  backgroundColor: _muted ? _D.red : _D.bgElevated,
                  foregroundColor: _D.textPrimary,
                ),
              ),
              const SizedBox(width: 16),
              IconButton.filled(
                onPressed: () => setState(() => _speakerOn = !_speakerOn),
                icon: Icon(_speakerOn ? Icons.volume_up : Icons.volume_down),
                style: IconButton.styleFrom(
                  backgroundColor: _speakerOn ? _D.gold : _D.bgElevated,
                  foregroundColor: _D.textPrimary,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _coachingPanel() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          "Nate's coaching",
          style: GoogleFonts.cormorantGaramond(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: _D.gold,
          ),
        ),
        const SizedBox(height: 8),
        Container(
          height: 140,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: _D.bgChamber,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _D.border),
          ),
          child: _coachingCards.isEmpty
              ? Center(
                  child: Text(
                    'Coaching cards will appear here during the call.',
                    style: GoogleFonts.dmSans(color: _D.textMuted, fontSize: 13),
                  ),
                )
              : ListView.builder(
                  controller: _coachingScrollController,
                  itemCount: _coachingCards.length,
                  itemBuilder: (_, i) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: _D.bgElevated,
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: _D.cyan.withValues(alpha: 0.3)),
                        ),
                        child: Text(
                          _coachingCards[i],
                          style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 13),
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _quickActions() {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        _quickActionChip('What do they mean?', 'interpret'),
        _quickActionChip('Help me respond', 'what_to_say'),
        _quickActionChip('Is this healthy?', 'abusive_check'),
      ],
    );
  }

  Widget _quickActionChip(String label, String action) {
    return ActionChip(
      label: Text(label, style: GoogleFonts.dmSans(fontSize: 12)),
      onPressed: () => _sendQuickAction(action),
      backgroundColor: _D.bgChamber,
      side: const BorderSide(color: _D.gold),
      labelStyle: const TextStyle(color: _D.goldBright),
    );
  }

  Widget _endCallButton() {
    return OutlinedButton.icon(
      onPressed: _endCall,
      icon: const Icon(Icons.call_end),
      label: Text(
        'End call',
        style: GoogleFonts.dmSans(fontSize: 16, fontWeight: FontWeight.w600),
      ),
      style: OutlinedButton.styleFrom(
        foregroundColor: _D.red,
        side: const BorderSide(color: _D.red),
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    );
  }

  Widget _postCallDebrief() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _D.bgChamber,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _D.cyan.withValues(alpha: 0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Post-call debrief',
            style: GoogleFonts.cormorantGaramond(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: _D.gold,
            ),
          ),
          const SizedBox(height: 12),
          if (_postCallSummary != null)
            Text(
              _postCallSummary!,
              style: GoogleFonts.dmSans(color: _D.textPrimary, fontSize: 14),
            ),
          if (_postCallNotes.isNotEmpty) ...[
            const SizedBox(height: 12),
            ..._postCallNotes.map((n) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text('• $n', style: GoogleFonts.dmSans(color: _D.textSecondary, fontSize: 13)),
                )),
          ],
        ],
      ),
    );
  }
}
