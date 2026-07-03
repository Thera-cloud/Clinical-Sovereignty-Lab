import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../main.dart' show defaultWsUrl;

/// Training Ground — Inner Leadership Mapping (card/council v1).
class TrainingGroundScreen extends StatefulWidget {
  final Map<String, dynamic> profile;
  final String? username;
  final String? password;

  const TrainingGroundScreen({
    super.key,
    required this.profile,
    this.username,
    this.password,
  });

  @override
  State<TrainingGroundScreen> createState() => _TrainingGroundScreenState();
}

class _TrainingGroundScreenState extends State<TrainingGroundScreen> {
  WebSocketChannel? _channel;
  StreamSubscription? _sub;
  String _status = 'connecting';
  String? _sessionId;
  String _state = 'LOADING';
  bool _consentRequired = true;
  String _consentText = '';
  List<Map<String, dynamic>> _council = [];
  String? _lastMessage;
  String? _freezeMessage;
  bool _showCrisisResources = false;
  final _turnController = TextEditingController();
  final _partNameController = TextEditingController();
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
      _send({'type': 'ilm_exit', 'session_id': _sessionId});
    }
    _sub?.cancel();
    _channel?.sink.close();
    _reconnectTimer?.cancel();
    _turnController.dispose();
    _partNameController.dispose();
    super.dispose();
  }

  void _connect() {
    _channel = WebSocketChannel.connect(Uri.parse(defaultWsUrl));
    _sub = _channel!.stream.listen(
      _onMessage,
      onDone: _scheduleReconnect,
      onError: (_) => _scheduleReconnect,
    );
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

  void _send(Map<String, dynamic> msg) {
    _channel?.sink.add(jsonEncode(msg));
  }

  void _onMessage(dynamic raw) {
    final data = jsonDecode(raw as String) as Map<String, dynamic>;
    final type = data['type']?.toString() ?? '';
    if (type == 'login_success') {
      setState(() => _status = 'ready');
      _send({'type': 'ilm_get_state'});
      return;
    }
    if (type == 'connected') {
      final user = widget.username ?? widget.profile['username']?.toString() ?? '';
      final pass = widget.password ?? '';
      if (user.isNotEmpty && pass.isNotEmpty) {
        _send({
          'type': 'login_request',
          'username': user,
          'password': pass,
          'expected_role': widget.profile['role'] ?? 'CLIENT',
        });
      }
      return;
    }
    if (type == 'ilm_state') {
      setState(() {
        _sessionId = data['session_id']?.toString();
        _state = data['state']?.toString() ?? 'CONSENT';
        _consentRequired = data['consent_required'] == true;
        _consentText = data['consent_text']?.toString() ?? '';
        _council = (data['council'] as List?)
                ?.map((e) => Map<String, dynamic>.from(e as Map))
                .toList() ??
            [];
      });
      return;
    }
    if (type == 'ilm_safety_freeze') {
      setState(() {
        _state = 'FROZEN_SAFETY';
        _freezeMessage = data['message']?.toString();
        _showCrisisResources = data['show_crisis_resources'] == true;
      });
      return;
    }
    if (type == 'ilm_dialogue_blocked') {
      setState(() {
        _state = data['state']?.toString() ?? _state;
        _lastMessage = data['message']?.toString() ?? _blockedMessage(data['reason']?.toString());
      });
      return;
    }
    if (type == 'ilm_dialogue_response') {
      setState(() {
        _state = data['state']?.toString() ?? _state;
        _lastMessage = data['text']?.toString();
      });
      return;
    }
    if (type == 'ilm_propose_result' && data['ok'] == true) {
      _send({'type': 'ilm_get_state'});
    }
  }

  void _acceptConsent() {
    _send({
      'type': 'ilm_consent_ack',
      'accepted': true,
      'acknowledged_non_clinical': true,
      'acknowledged_coach_visibility': true,
      'acknowledged_persistence': true,
    });
    Future.delayed(const Duration(milliseconds: 400), () {
      if (mounted) _send({'type': 'ilm_get_state'});
    });
  }

  void _proposePart() {
    final name = _partNameController.text.trim();
    if (name.isEmpty) return;
    _send({
      'type': 'ilm_propose_member',
      'part_name': name,
      'part_category': 'protector',
      'ilm_archetype_base': 'Warrior',
    });
    _partNameController.clear();
  }

  void _sendTurn() {
    final text = _turnController.text.trim();
    if (text.isEmpty || _state == 'FROZEN_SAFETY') return;
    _send({'type': 'ilm_dialogue_turn', 'text': text, 'exercise_mode': 'hearing'});
    _turnController.clear();
  }

  String _blockedMessage(String? reason) {
    switch (reason) {
      case 'pending_approval':
        return "Let's finish setting up your council first — your coach needs to approve "
            'at least one member before Inner Team dialogue.';
      case 'frozen_safety':
        return _freezeMessage ??
            'Training Ground is paused for safety. Use the crisis resources below if you need immediate support.';
      default:
        return "This exercise isn't available yet. Finish council setup or check with your coach.";
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0A0A0A),
        title: const Text('Training Ground', style: TextStyle(color: Color(0xFFC9A962))),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Status: $_status · $_state', style: const TextStyle(color: Colors.white70)),
            const SizedBox(height: 12),
            if (_consentRequired) ...[
              Text(_consentText, style: const TextStyle(color: Colors.white70)),
              const SizedBox(height: 8),
              ElevatedButton(
                onPressed: _acceptConsent,
                child: const Text('I acknowledge — enter Training Ground'),
              ),
            ] else ...[
              TextField(
                controller: _partNameController,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Council member name',
                  labelStyle: TextStyle(color: Color(0xFFC9A962)),
                ),
              ),
              TextButton(onPressed: _proposePart, child: const Text('Propose council member')),
              if (_council.isNotEmpty)
                Expanded(
                  child: ListView(
                    children: _council
                        .map(
                          (p) => ListTile(
                            title: Text(
                              p['part_name']?.toString() ?? '',
                              style: const TextStyle(color: Colors.white),
                            ),
                            subtitle: Text(
                              '${p['coaching_status']} · ${p['origin'] ?? ''}',
                              style: const TextStyle(color: Colors.white54),
                            ),
                          ),
                        )
                        .toList(),
                  ),
                ),
              if (_state != 'FROZEN_SAFETY') ...[
                TextField(
                  controller: _turnController,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                    labelText: 'Inner Team dialogue',
                    labelStyle: TextStyle(color: Color(0xFFC9A962)),
                  ),
                  maxLines: 3,
                ),
                ElevatedButton(onPressed: _sendTurn, child: const Text('Send turn')),
              ],
              if (_lastMessage != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(_lastMessage!, style: const TextStyle(color: Color(0xFF4ECDC4))),
                ),
              if (_freezeMessage != null)
                Container(
                  margin: const EdgeInsets.only(top: 12),
                  padding: const EdgeInsets.all(12),
                  color: const Color(0xFF1A1A1A),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(_freezeMessage!, style: const TextStyle(color: Colors.orangeAccent)),
                      if (_showCrisisResources)
                        const Padding(
                          padding: EdgeInsets.only(top: 8),
                          child: Text(
                            '988 · Crisis Text Line: text HOME to 741741',
                            style: TextStyle(color: Colors.redAccent, fontWeight: FontWeight.bold),
                          ),
                        ),
                    ],
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}
