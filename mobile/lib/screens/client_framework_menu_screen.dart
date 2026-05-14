// Per-client framework menu toggles (Sensitive Bridge v1.4).

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart' as cfg;

class ClientFrameworkMenuScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final String targetUserId;

  const ClientFrameworkMenuScreen({
    super.key,
    required this.currentUserProfile,
    required this.targetUserId,
  });

  @override
  State<ClientFrameworkMenuScreen> createState() =>
      _ClientFrameworkMenuScreenState();
}

class _ClientFrameworkMenuScreenState extends State<ClientFrameworkMenuScreen> {
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _menu = [];
  String? _defaultLens;
  bool _knowledgeGraph = false;
  bool _saving = false;

  String get _token => (widget.currentUserProfile['token'] ?? '').toString();
  String get _base => cfg.AppConfig.apiBaseUrl;

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $_token',
        'Content-Type': 'application/json',
      };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final uri = Uri.parse(
        '$_base/api/coach/sensitive-profile/${widget.targetUserId}/framework-menu',
      );
      final resp = await http
          .get(uri, headers: _headers)
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode != 200) throw Exception('HTTP ${resp.statusCode}');
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      final raw = (data['menu'] as List?) ?? [];
      _menu = raw.map((e) => Map<String, dynamic>.from(e as Map)).toList();
      _defaultLens = data['default_lens']?.toString();
      _knowledgeGraph = data['crystal_knowledge_graph_opt_in'] == true;
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      final enabled = <String, bool>{};
      for (final row in _menu) {
        final k = row['key']?.toString() ?? '';
        if (k.isEmpty) continue;
        enabled[k] = row['enabled'] == true;
      }
      final uri = Uri.parse(
        '$_base/api/coach/sensitive-profile/${widget.targetUserId}/framework-menu',
      );
      final body = jsonEncode({
        'enabled_frameworks': enabled,
        'default_lens_for_today': _defaultLens,
        'crystal_knowledge_graph_opt_in': _knowledgeGraph,
      });
      final resp = await http
          .put(uri, headers: _headers, body: body)
          .timeout(const Duration(seconds: 20));
      if (!mounted) return;
      if (resp.statusCode != 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Save failed: ${resp.statusCode}')),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Saved')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF111111),
        title: Text(
          'Frameworks · ${widget.targetUserId}',
          style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16),
        ),
        actions: [
          TextButton(
            onPressed: (_loading || _saving) ? null : _save,
            child: Text(
              _saving ? '…' : 'Save',
              style: const TextStyle(color: Color(0xFFC9A962)),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Color(0xFFC9A962)),
            onPressed: _loading ? null : _load,
          ),
        ],
      ),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(color: Color(0xFFC9A962)))
          : _error != null
              ? Center(
                  child: Text(_error!,
                      style: const TextStyle(color: Colors.white54)))
              : ListView(
                  padding: const EdgeInsets.all(12),
                  children: [
                    SwitchListTile(
                      title: const Text('Crystal knowledge graph opt-in',
                          style: TextStyle(color: Colors.white70)),
                      subtitle: const Text(
                        'Default OFF. Phase G graph traversal stays disabled unless explicitly opted in.',
                        style: TextStyle(color: Colors.white38, fontSize: 11),
                      ),
                      value: _knowledgeGraph,
                      activeThumbColor: const Color(0xFFC9A962),
                      onChanged: (v) => setState(() => _knowledgeGraph = v),
                    ),
                    DropdownButtonFormField<String?>(
                      value: _defaultLens,
                      dropdownColor: const Color(0xFF111111),
                      style: const TextStyle(color: Colors.white70),
                      decoration: const InputDecoration(
                        labelText: 'Default lens for today',
                        labelStyle:
                            TextStyle(color: Colors.white54, fontSize: 12),
                      ),
                      items: <DropdownMenuItem<String?>>[
                        const DropdownMenuItem<String?>(
                          value: null,
                          child: Text('No override',
                              style: TextStyle(color: Colors.white70)),
                        ),
                        ..._menu.map(
                          (row) => DropdownMenuItem<String?>(
                            value: row['key']?.toString(),
                            child: Text(
                              row['label']?.toString() ??
                                  row['key']?.toString() ??
                                  '',
                              style: const TextStyle(color: Colors.white70),
                            ),
                          ),
                        ),
                      ],
                      onChanged: (v) => setState(() => _defaultLens = v),
                    ),
                    const Divider(color: Colors.white24),
                    ..._menu.map((row) {
                      final key = row['key']?.toString() ?? '';
                      final label = row['label']?.toString() ?? key;
                      final en = row['enabled'] == true;
                      return SwitchListTile(
                        title: Text(label,
                            style: const TextStyle(color: Color(0xFFC9A962))),
                        subtitle: Text(
                          '${row['applies_to']}',
                          style: const TextStyle(
                              color: Colors.white38, fontSize: 11),
                        ),
                        value: en,
                        activeThumbColor: const Color(0xFFC9A962),
                        onChanged: (v) {
                          setState(() => row['enabled'] = v);
                        },
                      );
                    }),
                  ],
                ),
    );
  }
}
