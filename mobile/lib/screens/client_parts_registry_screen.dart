// Coach-facing Parts Registry (IFS-style parts) for Sensitive Bridge v1.4.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart' as cfg;

class ClientPartsRegistryScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final String targetUserId;

  const ClientPartsRegistryScreen({
    super.key,
    required this.currentUserProfile,
    required this.targetUserId,
  });

  @override
  State<ClientPartsRegistryScreen> createState() =>
      _ClientPartsRegistryScreenState();
}

class _ClientPartsRegistryScreenState extends State<ClientPartsRegistryScreen> {
  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _parts = [];

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
        '$_base/api/coach/sensitive-profile/${widget.targetUserId}/parts-registry',
      );
      final resp = await http
          .get(uri, headers: _headers)
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode != 200) {
        throw Exception('HTTP ${resp.statusCode}');
      }
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      final raw = (data['parts'] as List?) ?? [];
      _parts = raw.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) {
      setState(() => _loading = false);
    }
  }

  Future<void> _addPartDialog() async {
    final nameCtl = TextEditingController();
    final numCtl = TextEditingController(text: '1');
    String category = 'protector';
    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: const Text('Register part',
              style: TextStyle(color: Color(0xFFC9A962))),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: nameCtl,
                  style: const TextStyle(color: Colors.white70),
                  decoration: const InputDecoration(labelText: 'Part name'),
                ),
                TextField(
                  controller: numCtl,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(color: Colors.white70),
                  decoration: const InputDecoration(labelText: 'Part number'),
                ),
                DropdownButton<String>(
                  value: category,
                  dropdownColor: const Color(0xFF111111),
                  items: const [
                    'protector',
                    'exile',
                    'firefighter',
                    'manager',
                    'addict_part',
                    'other',
                  ]
                      .map(
                        (k) => DropdownMenuItem(
                          value: k,
                          child: Text(k,
                              style: const TextStyle(color: Colors.white70)),
                        ),
                      )
                      .toList(),
                  onChanged: (v) => setLocal(() => category = v ?? category),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel')),
            TextButton(
              onPressed: () async {
                final uri = Uri.parse(
                  '$_base/api/coach/sensitive-profile/${widget.targetUserId}/parts-registry',
                );
                final body = jsonEncode({
                  'part_name': nameCtl.text.trim(),
                  'part_number': int.tryParse(numCtl.text.trim()) ?? 1,
                  'part_category': category,
                  'addiction_link': null,
                  'description': null,
                  'protected_exile_part_id': null,
                });
                final resp = await http
                    .post(uri, headers: _headers, body: body)
                    .timeout(const Duration(seconds: 15));
                if (!mounted) return;
                Navigator.pop(ctx);
                if (resp.statusCode == 200) {
                  await _load();
                } else {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Save failed: ${resp.statusCode}')),
                  );
                }
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF111111),
        title: Text(
          'Parts · ${widget.targetUserId}',
          style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Color(0xFFC9A962)),
            onPressed: _loading ? null : _load,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        backgroundColor: const Color(0xFFC9A962),
        onPressed: _addPartDialog,
        child: const Icon(Icons.add, color: Color(0xFF050505)),
      ),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(color: Color(0xFFC9A962)))
          : _error != null
              ? Center(
                  child: Text(_error!,
                      style: const TextStyle(color: Colors.white54)))
              : ListView.builder(
                  padding: const EdgeInsets.all(12),
                  itemCount: _parts.length,
                  itemBuilder: (_, i) {
                    final p = _parts[i];
                    return Card(
                      color: const Color(0xFF111111),
                      child: ListTile(
                        title: Text(
                          '${p['part_name']}',
                          style: const TextStyle(color: Color(0xFFC9A962)),
                        ),
                        subtitle: Text(
                          '${p['part_category']} · #${p['part_number']}',
                          style: const TextStyle(color: Colors.white54),
                        ),
                      ),
                    );
                  },
                ),
    );
  }
}
