// Clinician cross-addiction profile capsule (stored in profile_data.cross_addiction_profile).

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart' as cfg;

class ClientCrossAddictionProfileScreen extends StatefulWidget {
  final Map<String, dynamic> currentUserProfile;
  final String targetUserId;

  const ClientCrossAddictionProfileScreen({
    super.key,
    required this.currentUserProfile,
    required this.targetUserId,
  });

  @override
  State<ClientCrossAddictionProfileScreen> createState() =>
      _ClientCrossAddictionProfileScreenState();
}

class _ClientCrossAddictionProfileScreenState
    extends State<ClientCrossAddictionProfileScreen> {
  bool _loading = true;
  bool _saving = false;
  String? _error;
  bool _crossActive = false;
  bool _overlayApplied = false;
  final TextEditingController _notes = TextEditingController();

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

  @override
  void dispose() {
    _notes.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final uri = Uri.parse(
        '$_base/api/coach/sensitive-profile/${widget.targetUserId}',
      );
      final resp = await http
          .get(uri, headers: _headers)
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode != 200) throw Exception('HTTP ${resp.statusCode}');
      final data = jsonDecode(resp.body) as Map<String, dynamic>;
      final cap = data['cross_addiction_profile'];
      Map<String, dynamic> m = {};
      if (cap is Map) {
        m = Map<String, dynamic>.from(
          cap.map((k, v) => MapEntry(k.toString(), v)),
        );
      }
      _crossActive = m['cross_addiction_active'] == true;
      _overlayApplied = m['overlay_applied'] == true;
      _notes.text = (m['coach_notes'] ?? '').toString();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      final uri = Uri.parse(
        '$_base/api/coach/sensitive-profile/${widget.targetUserId}/cross-addiction-profile',
      );
      final payload = {
        'cross_addiction_profile': {
          'cross_addiction_active': _crossActive,
          'overlay_applied': _overlayApplied,
          'coach_notes': _notes.text.trim(),
        },
      };
      final resp = await http
          .put(uri, headers: _headers, body: jsonEncode(payload))
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
          'Cross-addiction · ${widget.targetUserId}',
          style: const TextStyle(color: Color(0xFFC9A962), fontSize: 15),
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
                  padding: const EdgeInsets.all(16),
                  children: [
                    SwitchListTile(
                      title: const Text('Cross-addiction active',
                          style: TextStyle(color: Colors.white70)),
                      value: _crossActive,
                      activeThumbColor: const Color(0xFFC9A962),
                      onChanged: (v) => setState(() => _crossActive = v),
                    ),
                    SwitchListTile(
                      title: const Text('Overlay applied (clinical record)',
                          style: TextStyle(color: Colors.white70)),
                      value: _overlayApplied,
                      activeThumbColor: const Color(0xFFC9A962),
                      onChanged: (v) => setState(() => _overlayApplied = v),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _notes,
                      maxLines: 6,
                      style: const TextStyle(color: Colors.white70),
                      decoration: const InputDecoration(
                        labelText: 'Coach notes',
                        labelStyle: TextStyle(color: Colors.white54),
                        enabledBorder: OutlineInputBorder(
                          borderSide: BorderSide(color: Colors.white24),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderSide: BorderSide(color: Color(0xFFC9A962)),
                        ),
                      ),
                    ),
                  ],
                ),
    );
  }
}
