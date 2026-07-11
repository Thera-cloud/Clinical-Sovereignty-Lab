import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/app_config.dart';

/// Client view of commitments Nate is tracking ("What Nate's holding onto").
class NateCommitmentsScreen extends StatefulWidget {
  final Map<String, dynamic> profile;

  const NateCommitmentsScreen({super.key, required this.profile});

  @override
  State<NateCommitmentsScreen> createState() => _NateCommitmentsScreenState();
}

class _NateCommitmentsScreenState extends State<NateCommitmentsScreen> {
  static const _gold = Color(0xFFC9A962);
  static const _bg = Color(0xFF050505);
  static const _card = Color(0xFF111111);
  static const _textSecondary = Color(0xFF888888);

  List<Map<String, dynamic>> _items = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<Map<String, dynamic>> _wsRequest(Map<String, dynamic> request, Set<String> expected) async {
    final token = (widget.profile['token'] ?? '').toString();
    final hwId = (widget.profile['hardware_id'] ?? '').toString();
    if (token.isEmpty) throw Exception('Not authenticated');

    WebSocketChannel? socket;
    StreamSubscription? sub;
    final completer = Completer<Map<String, dynamic>>();
    try {
      socket = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      sub = socket.stream.listen((raw) {
        if (completer.isCompleted) return;
        try {
          final data = jsonDecode(raw as String) as Map<String, dynamic>;
          final type = (data['type'] ?? '').toString();
          if (type == 'connected') {
            socket?.sink.add(jsonEncode({
              'type': 'auth',
              'token': token,
              'hardware_id': hwId,
            }));
          } else if (type == 'auth_success' || type == 'login_success') {
            socket?.sink.add(jsonEncode(request));
          } else if (type == 'auth_failed') {
            completer.completeError(Exception('Authentication failed'));
          } else if (expected.contains(type)) {
            completer.complete(data);
          }
        } catch (_) {}
      }, onError: (e) {
        if (!completer.isCompleted) completer.completeError(Exception('$e'));
      }, onDone: () {
        if (!completer.isCompleted) {
          completer.completeError(Exception('Connection closed'));
        }
      });
      return await completer.future.timeout(const Duration(seconds: 30));
    } finally {
      await sub?.cancel();
      try {
        await socket?.sink.close();
      } catch (_) {}
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final resp = await _wsRequest(
        {'type': 'client_get_commitments'},
        {'client_commitments_list', 'error'},
      );
      if (!mounted) return;
      final list = resp['commitments'];
      setState(() {
        _items = list is List
            ? list.map((e) => Map<String, dynamic>.from(e as Map)).toList()
            : [];
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _dismiss(String id) async {
    try {
      await _wsRequest(
        {'type': 'client_dismiss_commitment', 'commitment_id': id},
        {'commitment_dismissed', 'error'},
      );
      await _load();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not dismiss — try again')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bg,
      appBar: AppBar(
        backgroundColor: _bg,
        title: const Text("What Nate's Holding Onto", style: TextStyle(color: Colors.white)),
        iconTheme: const IconThemeData(color: _gold),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _gold))
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(_error!, style: const TextStyle(color: _textSecondary)),
                  ),
                )
              : _items.isEmpty
                  ? const Center(
                      child: Text(
                        'Nothing tracked yet.\nNate will add items when you share goals or plans.',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: _textSecondary, height: 1.4),
                      ),
                    )
                  : RefreshIndicator(
                      color: _gold,
                      onRefresh: _load,
                      child: ListView.separated(
                        padding: const EdgeInsets.all(16),
                        itemCount: _items.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 12),
                        itemBuilder: (context, i) {
                          final c = _items[i];
                          final text = (c['text'] ?? '').toString();
                          final target = (c['target_date'] ?? '').toString();
                          final sensitive = (c['sensitivity'] ?? 'routine').toString() == 'sensitive';
                          return Container(
                            padding: const EdgeInsets.all(16),
                            decoration: BoxDecoration(
                              color: _card,
                              borderRadius: BorderRadius.circular(12),
                              border: Border.all(color: const Color(0xFF252525)),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(text, style: const TextStyle(color: Colors.white, fontSize: 15)),
                                if (target.isNotEmpty) ...[
                                  const SizedBox(height: 6),
                                  Text(target, style: const TextStyle(color: _textSecondary, fontSize: 12)),
                                ],
                                if (sensitive)
                                  const Padding(
                                    padding: EdgeInsets.only(top: 6),
                                    child: Text('Sensitive — gentle reminders only',
                                        style: TextStyle(color: _gold, fontSize: 11)),
                                  ),
                                const SizedBox(height: 12),
                                Align(
                                  alignment: Alignment.centerRight,
                                  child: TextButton(
                                    onPressed: () => _dismiss((c['id'] ?? '').toString()),
                                    child: const Text('Dismiss', style: TextStyle(color: _textSecondary)),
                                  ),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
                    ),
    );
  }
}
