import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../main.dart' show FamilySanctuaryScreen, defaultWsUrl;

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
  int _totalReconnects = 0;
  String _promptText = '';
  String? _currentTurnUserId;
  String? _nateMessage;
  String? _warmReturnMessage;
  String? _missEncouragement;
  String? _sanctuaryId;
  final _turnController = TextEditingController();
  int _reconnectAttempts = 0;
  Timer? _reconnectTimer;

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
    _channel?.sink.close();
    _reconnectTimer?.cancel();
    _turnController.dispose();
    super.dispose();
  }

  void _connect() {
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
    Navigator.of(context).pushReplacement(
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

  void _onMessage(dynamic raw) {
    try {
      final msg = jsonDecode(raw as String) as Map<String, dynamic>;
      final type = msg['type'] as String? ?? '';
      if (type == 'connected' || type == 'login_success') {
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
          _sessionId = msg['session_id'] as String?;
          _state = msg['state'] as String? ?? _state;
          _sanctuaryId = msg['sanctuary_id'] as String? ?? _sanctuaryId;
          _consentText = msg['consent_text'] as String? ?? _consentText;
          _consentRequired = msg['consent_required'] as bool? ?? _consentRequired;
          _totalReconnects = msg['total_reconnects'] as int? ?? _totalReconnects;
          _promptText = msg['prompt_text'] as String? ?? _promptText;
          _currentTurnUserId = msg['current_turn_user_id'] as String?;
          _warmReturnMessage = msg['warm_return_message'] as String?;
          _missEncouragement = msg['miss_encouragement'] as String?;
          _nateMessage = msg['nate_message'] as String?;
        });
        _maybeHandoffToSanctuary(msg);
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
      if (type == 'reconnect_turn_ack') {
        setState(() {
          _state = msg['state'] as String? ?? _state;
          _totalReconnects = msg['total_reconnects'] as int? ?? _totalReconnects;
          _promptText = msg['prompt_text'] as String? ?? _promptText;
          _currentTurnUserId = msg['current_turn_user_id'] as String?;
          _nateMessage = msg['nate_message'] as String?;
        });
        _turnController.clear();
        return;
      }
      if (type == 'reconnect_error') {
        setState(() => _status = msg['message'] as String? ?? 'error');
      }
    } catch (_) {}
  }

  bool get _isMyTurn {
    final me = widget.profile['username']?.toString();
    return _currentTurnUserId != null && me != null && _currentTurnUserId == me;
  }

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
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_totalReconnects > 0)
              Text(
                "That's $_totalReconnects reconnects together.",
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
            if (_consentRequired && _consentText.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text(_consentText, style: const TextStyle(color: Colors.white70)),
              const SizedBox(height: 12),
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
              ),
            ],
            if (!_consentRequired && _state == 'ACTIVE' && _promptText.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text(_promptText, style: const TextStyle(color: Colors.white, fontSize: 15)),
              const SizedBox(height: 8),
              if (_isMyTurn) ...[
                TextField(
                  controller: _turnController,
                  maxLines: 4,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                    hintText: 'Your share…',
                    hintStyle: TextStyle(color: Colors.white38),
                    border: OutlineInputBorder(),
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
                  'Listening…',
                  style: TextStyle(color: Colors.white.withOpacity(0.5)),
                  textAlign: TextAlign.center,
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
            const Spacer(),
            Text('Status: $_status', style: const TextStyle(color: Colors.white24, fontSize: 11)),
          ],
        ),
      ),
    );
  }
}
