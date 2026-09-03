import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../main.dart' show ClientWsHub, FamilySanctuaryScreen, LobbyScreen, defaultWsUrl;

/// Daily Reconnect — Nate-fronted connection ritual (TOP_TIER gated).
class DailyReconnectScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String? username;
  final String? password;

  const DailyReconnectScreen({
    super.key,
    required this.profile,
    this.username,
    this.password,
  });

  @override
  State<DailyReconnectScreen> createState() => _DailyReconnectScreenState();
}

class _DailyReconnectScreenState extends State<DailyReconnectScreen> {
  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  String _status = 'connecting';
  String? _sessionId;
  String _state = 'LOADING';
  String _consentText = '';
  bool _consentRequired = true;
  String? _rewardMessage;
  String? _coupleDiscussionMessage;
  String _promptPhase = 'connection';
  int _currentPromptIndex = 0;
  String _promptText = '';
  String? _currentTurnUserId;
  String? _nateMessage;
  String? _warmReturnMessage;
  String? _missEncouragement;
  String? _sanctuaryId;
  List<dynamic> _participants = const [];
  List<Map<String, dynamic>> _turns = const [];
  final _turnController = TextEditingController();
  final _scrollController = ScrollController();
  int _reconnectAttempts = 0;
  Timer? _reconnectTimer;
  bool _borrowedFromHub = false;

  @override
  void initState() {
    super.initState();
    _connect();
  }

  @override
  void dispose() {
    if (_sessionId != null) {
      _send({'type': 'reconnect_exit', 'session_id': _sessionId});
    }
    _sub?.cancel();
    if (!_borrowedFromHub) {
      _channel?.sink.close();
    }
    _reconnectTimer?.cancel();
    _turnController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _connect() {
    _sub?.cancel();
    _reconnectTimer?.cancel();
    if (ClientWsHub.channel != null) {
      _borrowedFromHub = true;
      _channel = ClientWsHub.channel;
      _sub = ClientWsHub.inbound.listen(_onMessage, onDone: _scheduleReconnect, onError: (_) => _scheduleReconnect);
      _status = 'ready';
      _send({'type': 'reconnect_get_or_create'});
      return;
    }
    _borrowedFromHub = false;
    _channel = WebSocketChannel.connect(Uri.parse(defaultWsUrl));
    _sub = _channel!.stream.listen(_onMessage, onDone: _scheduleReconnect, onError: (_) => _scheduleReconnect);
  }

  void _scheduleReconnect() {
    if (!mounted) return;
    final attempt = _reconnectAttempts.clamp(0, 10);
    final baseMs = (1000 * (1 << attempt)).clamp(1000, 30000);
    _reconnectAttempts++;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(Duration(milliseconds: baseMs), () {
      if (mounted) _connect();
    });
  }

  void _send(Map<String, dynamic> payload) {
    _channel?.sink.add(jsonEncode(payload));
  }

  void _openFamilySanctuary() {
    if (!mounted) return;
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => FamilySanctuaryScreen(
          profile: widget.profile,
          username: widget.username,
          password: widget.password,
        ),
      ),
    );
  }

  void _maybeHandoffToSanctuary(Map<String, dynamic> msg) {
    final state = msg['state'] as String? ?? _state;
    final sid = msg['sanctuary_id'] as String? ?? _sanctuaryId;
    if (state == 'ENTER_FS' && sid != null) {
      _openFamilySanctuary();
    }
  }

  void _logoutToLobby() {
    try {
      ClientWsHub.channel?.sink.close();
    } catch (_) {}
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LobbyScreen()),
      (route) => false,
    );
  }

  void _applySessionFields(Map<String, dynamic> msg) {
    _sessionId = msg['session_id'] as String? ?? _sessionId;
    _state = msg['state'] as String? ?? _state;
    _sanctuaryId = msg['sanctuary_id'] as String? ?? _sanctuaryId;
    _consentText = msg['consent_text'] as String? ?? _consentText;
    _consentRequired = msg['consent_required'] as bool? ?? _consentRequired;
    _participants = msg['participants'] as List<dynamic>? ?? _participants;
    _rewardMessage = msg['reward_message'] as String? ?? _rewardMessage;
    _promptText = msg['prompt_text'] as String? ?? _promptText;
    _promptPhase = msg['prompt_phase'] as String? ?? _promptPhase;
    _currentPromptIndex = msg['current_prompt_index'] as int? ?? _currentPromptIndex;
    _coupleDiscussionMessage = msg['couple_discussion_message'] as String? ?? _coupleDiscussionMessage;
    _currentTurnUserId = msg['current_turn_user_id'] as String?;
    _warmReturnMessage = msg['warm_return_message'] as String?;
    _missEncouragement = msg['miss_encouragement'] as String?;
    _nateMessage = msg['nate_message'] as String?;
    final rawTurns = msg['turns'];
    if (rawTurns is List) {
      _turns = rawTurns
          .whereType<Map>()
          .map((t) => Map<String, dynamic>.from(t))
          .toList();
    }
  }

  void _scrollToLatestTurn() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  bool get _inRitualChat =>
      !_consentRequired &&
      (_state == 'ACTIVE' || _state == 'SOFT_DEESCALATION') &&
      _promptText.isNotEmpty;

  bool get _inWrapUp => _state == 'WRAP_UP';

  static const _ritualPrompts = <String>[
    'Share one thing you appreciate about your partner today.',
    "What's one thing from today you'd like them to know?",
    'What are you feeling, and what do you need?',
    "What's one small request that would help you feel more connected?",
    'What are you noticing in yourself right now — without trying to fix anything?',
    'What do you need from yourself to feel a little steadier tonight?',
    'What felt meaningful to you in what you shared today?',
  ];

  String _phaseLabel(int index, {bool isCurrent = false}) {
    final reflection = isCurrent
        ? _promptPhase == 'reflection'
        : index >= 4;
    if (reflection) {
      return isCurrent ? 'Self-reflection for you' : 'Self-reflection';
    }
    return isCurrent ? 'Question for both of you' : 'Question';
  }

  String _promptTextForIndex(int index, [Map<String, dynamic>? turn]) {
    final fromTurn = turn?['prompt_text']?.toString();
    if (fromTurn != null && fromTurn.isNotEmpty) return fromTurn;
    if (index >= 0 && index < _ritualPrompts.length) return _ritualPrompts[index];
    return _promptText;
  }

  Widget _buildPromptDivider(String question, {bool isCurrent = false, int index = 0}) {
    const gold = Color(0xFFC9A962);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12, top: 4),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: isCurrent ? const Color(0xFF15120C) : const Color(0xFF0D0D0D),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: isCurrent ? gold : gold.withOpacity(0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _phaseLabel(index, isCurrent: isCurrent),
            style: TextStyle(
              color: isCurrent ? gold : Colors.white54,
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.4,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            question,
            style: TextStyle(
              color: isCurrent ? Colors.white : Colors.white70,
              fontSize: isCurrent ? 16 : 14,
              height: 1.35,
              fontWeight: isCurrent ? FontWeight.w600 : FontWeight.normal,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCurrentPromptCard() {
    return _buildPromptDivider(
      _promptText,
      isCurrent: true,
      index: _currentPromptIndex,
    );
  }

  List<Widget> _buildThreadWidgets() {
    final widgets = <Widget>[];
    int? lastPromptIndex;
    for (final turn in _turns) {
      final pi = turn['prompt_index'] is int
          ? turn['prompt_index'] as int
          : int.tryParse('${turn['prompt_index']}') ?? 0;
      if (pi != lastPromptIndex) {
        widgets.add(_buildPromptDivider(_promptTextForIndex(pi, turn), index: pi));
        lastPromptIndex = pi;
      }
      widgets.add(_buildTurnBubble(turn));
    }
    return widgets;
  }

  String _displayNameFor(String userId) {
    if (userId == _me) return 'You';
    final at = userId.indexOf('@');
    if (at > 0) return userId.substring(0, at);
    return userId;
  }

  Widget _buildTurnBubble(Map<String, dynamic> turn) {
    const gold = Color(0xFFC9A962);
    final userId = turn['user_id']?.toString() ?? '';
    final content = turn['content']?.toString() ?? '';
    final mine = userId == _me;
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
        decoration: BoxDecoration(
          color: mine ? const Color(0xFF1A1510) : const Color(0xFF111111),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: mine ? gold.withOpacity(0.45) : Colors.white12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _displayNameFor(userId),
              style: TextStyle(
                color: mine ? gold : Colors.white54,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 4),
            Text(content, style: const TextStyle(color: Colors.white, height: 1.35)),
          ],
        ),
      ),
    );
  }

  void _onMessage(dynamic raw) {
    try {
      final msg = jsonDecode(raw as String) as Map<String, dynamic>;
      final type = msg['type'] as String? ?? '';
      if (type == 'connected' || type == 'login_success') {
        if (_borrowedFromHub) {
          if (type == 'login_success') {
            setState(() => _status = 'ready');
            _send({'type': 'reconnect_get_or_create'});
          }
          return;
        }
        if (type == 'connected') {
          _send({
            'type': 'login_request',
            'username': widget.username ?? widget.profile['username'],
            'password': widget.password ?? widget.profile['password'],
            'expected_role': widget.profile['role'] ?? 'CLIENT',
          });
        } else {
          setState(() => _status = 'ready');
          _send({'type': 'reconnect_get_or_create'});
        }
        return;
      }
      if (type == 'reconnect_state' || type == 'reconnect_consent_result') {
        setState(() {
          _applySessionFields(msg);
        });
        _scrollToLatestTurn();
        return;
      }
      if (type == 'reconnect_fs_response') {
        setState(() {
          _state = msg['state'] as String? ?? _state;
          _sanctuaryId = msg['sanctuary_id'] as String? ?? _sanctuaryId;
        });
        _maybeHandoffToSanctuary(msg);
        return;
      }
      if (type == 'reconnect_turn_ack' || type == 'reconnect_wrap_up') {
        setState(() {
          _applySessionFields(msg);
        });
        if (type == 'reconnect_turn_ack') _turnController.clear();
        _scrollToLatestTurn();
        return;
      }
      if (type == 'reconnect_error') {
        setState(() => _status = msg['message'] as String? ?? 'error');
      }
    } catch (_) {}
  }

  bool get _isMyTurn {
    final me = _me;
    return _currentTurnUserId != null && me != null && _currentTurnUserId == me;
  }

  String? get _me =>
      (widget.username ?? widget.profile['username'])?.toString();

  /// Whether *this* user has already acknowledged consent for the session.
  bool get _iConsented {
    final me = _me;
    if (me == null) return false;
    for (final p in _participants) {
      if (p is Map && p['user_id']?.toString() == me) {
        return p['consented'] == true;
      }
    }
    return false;
  }

  int get _consentedCount =>
      _participants.where((p) => p is Map && p['consented'] == true).length;

  @override
  Widget build(BuildContext context) {
    const gold = Color(0xFFC9A962);
    const voidBg = Color(0xFF050505);
    return Scaffold(
      backgroundColor: voidBg,
      appBar: AppBar(
        backgroundColor: const Color(0xFF0A0A0A),
        title: const Text('Daily Reconnect', style: TextStyle(color: gold)),
        iconTheme: const IconThemeData(color: gold),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout, color: Colors.red),
            tooltip: 'Log out',
            onPressed: _logoutToLobby,
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_rewardMessage != null && _rewardMessage!.isNotEmpty)
              Text(
                _rewardMessage!,
                style: const TextStyle(color: gold, fontSize: 16, fontWeight: FontWeight.w600),
                textAlign: TextAlign.center,
              ),
            if (_warmReturnMessage != null) ...[
              const SizedBox(height: 8),
              Text(_warmReturnMessage!, style: const TextStyle(color: Colors.white70), textAlign: TextAlign.center),
            ],
            if (_missEncouragement != null && _state == 'CONSENT_CHECKPOINT') ...[
              const SizedBox(height: 8),
              Text(_missEncouragement!, style: const TextStyle(color: Colors.white54), textAlign: TextAlign.center),
            ],
            const SizedBox(height: 16),
            Text('State: $_state', style: const TextStyle(color: Colors.white54)),
            if (_nateMessage != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFF111111),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: gold.withOpacity(0.3)),
                ),
                child: Text(_nateMessage!, style: const TextStyle(color: Colors.white)),
              ),
            ],
            // Show consent UI whenever we're at the checkpoint — never gate
            // on `_consentRequired` alone, because a stale/race state can flip
            // it to false and strand both users on a blank screen.
            if (_state == 'CONSENT_CHECKPOINT' && _consentText.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text(_consentText, style: const TextStyle(color: Colors.white70)),
              const SizedBox(height: 12),
              if (!_iConsented)
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: gold),
                  onPressed: _sessionId == null
                      ? null
                      : () => _send({
                            'type': 'reconnect_consent_ack',
                            'session_id': _sessionId,
                            'accepted': true,
                          }),
                  child: const Text('I acknowledge — continue'),
                )
              else ...[
                const Icon(Icons.check_circle_outline, color: gold, size: 28),
                const SizedBox(height: 8),
                Text(
                  _participants.length < 2
                      ? 'You\'re in. Waiting for your family member to open Daily Reconnect and acknowledge — this is a shared ritual.'
                      : 'You\'ve acknowledged. Waiting for the other person to acknowledge ($_consentedCount of ${_participants.length} ready).',
                  style: const TextStyle(color: Colors.white70),
                  textAlign: TextAlign.center,
                ),
              ],
            ],
            if (_inRitualChat) ...[
              if (_turns.isNotEmpty) ...[
                const SizedBox(height: 12),
                Expanded(
                  child: ListView(
                    controller: _scrollController,
                    children: _buildThreadWidgets(),
                  ),
                ),
                const SizedBox(height: 12),
              ] else
                const Spacer(),
              _buildCurrentPromptCard(),
              const SizedBox(height: 12),
              if (_isMyTurn) ...[
                TextField(
                  controller: _turnController,
                  maxLines: 4,
                  style: const TextStyle(color: Colors.white),
                  decoration: InputDecoration(
                    hintText: 'Your answer to the question above…',
                    hintStyle: const TextStyle(color: Colors.white38),
                    border: const OutlineInputBorder(),
                    labelText: 'Your share',
                    labelStyle: TextStyle(color: gold.withOpacity(0.8)),
                  ),
                ),
                const SizedBox(height: 8),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: gold),
                  onPressed: () {
                    final text = _turnController.text.trim();
                    if (text.isEmpty || _sessionId == null) return;
                    _send({'type': 'reconnect_turn', 'session_id': _sessionId, 'content': text});
                  },
                  child: const Text('Share'),
                ),
              ] else
                Text(
                  _isMyTurn ? 'Your turn to answer above.' : 'Listening for their answer…',
                  style: TextStyle(color: Colors.white.withOpacity(0.5)),
                  textAlign: TextAlign.center,
                ),
            ],
            if (_inWrapUp) ...[
              if (_turns.isNotEmpty) ...[
                const SizedBox(height: 12),
                Expanded(
                  child: ListView(
                    controller: _scrollController,
                    children: _buildThreadWidgets(),
                  ),
                ),
              ] else
                const Spacer(),
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF15120C),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: gold),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Talk together',
                      style: TextStyle(
                        color: gold,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.4,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _coupleDiscussionMessage ??
                          'Take a few minutes together to talk about what you each shared.',
                      style: const TextStyle(color: Colors.white, height: 1.4, fontSize: 15),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'Would you like to continue in Family Sanctuary for deeper support?',
                style: TextStyle(color: Colors.white70),
              ),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => _send({
                        'type': 'reconnect_finish',
                        'session_id': _sessionId,
                      }),
                      child: const Text('Done for today'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(backgroundColor: gold),
                      onPressed: () => _send({
                        'type': 'reconnect_fs_offer_response',
                        'session_id': _sessionId,
                        'accepted': true,
                      }),
                      child: const Text('Open Sanctuary'),
                    ),
                  ),
                ],
              ),
            ],
            if (_state == 'OFFER_FS') ...[
              const SizedBox(height: 16),
              const Text(
                'Would you like to continue in Family Sanctuary for deeper support?',
                style: TextStyle(color: Colors.white70),
              ),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => _send({
                        'type': 'reconnect_fs_offer_response',
                        'session_id': _sessionId,
                        'accepted': false,
                      }),
                      child: const Text('Not now'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(backgroundColor: gold),
                      onPressed: () => _send({
                        'type': 'reconnect_fs_offer_response',
                        'session_id': _sessionId,
                        'accepted': true,
                      }),
                      child: const Text('Yes, open Sanctuary'),
                    ),
                  ),
                ],
              ),
            ],
            if (!_inRitualChat && !_inWrapUp) const Spacer(),
            Text('Status: $_status', style: const TextStyle(color: Colors.white24, fontSize: 11)),
          ],
        ),
      ),
    );
  }
}
