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
  int _safetyQueueCount = 0;
  bool _tgOnly = false;

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
      await _loadSafetyCount();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) {
      setState(() => _loading = false);
    }
  }

  Future<void> _loadSafetyCount() async {
    try {
      final uri = Uri.parse('$_base/api/coach/training-ground/safety-queue/count');
      final resp = await http
          .get(uri, headers: _headers)
          .timeout(const Duration(seconds: 15));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        _safetyQueueCount = (data['count'] as num?)?.toInt() ?? 0;
      }
    } catch (_) {}
  }

  Future<void> _patchCoachingStatus(Map<String, dynamic> part, String status) async {
    if (status == 'APPROVED' &&
        (part['origin']?.toString() ?? '') == 'training_ground') {
      final approved = await _approveTrainingGroundPartDialog(part);
      if (approved != true) return;
      return;
    }
    await _patchPartFields(part['id'], {'coaching_status': status});
  }

  Future<bool?> _approveTrainingGroundPartDialog(Map<String, dynamic> part) async {
    final notesCtl = TextEditingController(
      text: part['coaching_status_notes']?.toString() ?? '',
    );
    String category = part['part_category']?.toString() ?? 'manager';
    String ifsRole = part['ifs_role']?.toString() ?? category;
    if (ifsRole.isEmpty) ifsRole = category;

    return showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: Text(
            'Approve ${part['part_name']}',
            style: const TextStyle(color: Color(0xFFC9A962)),
          ),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'ILM archetype: ${part['ilm_archetype_base'] ?? '—'} '
                  '(coaching metaphor — confirm IFS mapping for Little Nate).',
                  style: const TextStyle(color: Colors.white70, fontSize: 13),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: category,
                  dropdownColor: const Color(0xFF111111),
                  decoration: const InputDecoration(labelText: 'IFS part category'),
                  items: const [
                    'manager',
                    'firefighter',
                    'protector',
                    'exile',
                    'self_energy',
                    'inner_critic',
                    'other',
                  ]
                      .map((k) => DropdownMenuItem(value: k, child: Text(k)))
                      .toList(),
                  onChanged: (v) => setLocal(() {
                    category = v ?? category;
                    if (ifsRole.isEmpty || ifsRole == part['part_category']) {
                      ifsRole = category;
                    }
                  }),
                ),
                DropdownButtonFormField<String>(
                  value: ifsRole,
                  dropdownColor: const Color(0xFF111111),
                  decoration: const InputDecoration(labelText: 'IFS role (dialogue label)'),
                  items: const [
                    'manager',
                    'firefighter',
                    'protector',
                    'exile',
                    'self_energy',
                  ]
                      .map((k) => DropdownMenuItem(value: k, child: Text(k)))
                      .toList(),
                  onChanged: (v) => setLocal(() => ifsRole = v ?? ifsRole),
                ),
                TextField(
                  controller: notesCtl,
                  maxLines: 3,
                  style: const TextStyle(color: Colors.white70),
                  decoration: const InputDecoration(
                    labelText: 'Coach notes for Training Ground (optional)',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () async {
                final id = part['id'];
                final ok = await _patchPartFields(id, {
                  'coaching_status': 'APPROVED',
                  'part_category': category,
                  'ifs_role': ifsRole,
                  'coaching_status_notes': notesCtl.text.trim().isEmpty
                      ? null
                      : notesCtl.text.trim(),
                });
                if (ctx.mounted) Navigator.pop(ctx, ok);
              },
              child: const Text('Approve'),
            ),
          ],
        ),
      ),
    );
  }

  Future<bool> _patchPartFields(dynamic id, Map<String, dynamic> fields) async {
    if (id == null) return false;
    final body = Map<String, dynamic>.from(fields)
      ..removeWhere((_, v) => v == null);
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/${widget.targetUserId}/parts-registry/$id',
    );
    final resp = await http.patch(
      uri,
      headers: _headers,
      body: jsonEncode(body),
    );
    if (!mounted) return resp.statusCode == 200;
    if (resp.statusCode == 200) {
      await _load();
      return true;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Update failed: ${resp.statusCode}')),
    );
    return false;
  }

  List<Map<String, dynamic>> get _visibleParts {
    if (!_tgOnly) return _parts;
    return _parts
        .where((p) => (p['origin']?.toString() ?? '') == 'training_ground')
        .toList();
  }

  Future<void> _partDialog([Map<String, dynamic>? existing]) async {
    final isEdit = existing != null;
    final nameCtl = TextEditingController(
      text: existing?['part_name']?.toString() ?? '',
    );
    final numCtl = TextEditingController(
      text: existing?['part_number']?.toString() ?? '1',
    );
    String category = existing?['part_category']?.toString() ?? 'protector';
    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: const Color(0xFF111111),
          title: Text(
            isEdit ? 'Edit part' : 'Register part',
            style: const TextStyle(color: Color(0xFFC9A962)),
          ),
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
                final path =
                    '$_base/api/coach/sensitive-profile/${widget.targetUserId}/parts-registry'
                    '${isEdit ? '/${existing['id']}' : ''}';
                final uri = Uri.parse(path);
                final body = jsonEncode({
                  'part_name': nameCtl.text.trim(),
                  'part_number': int.tryParse(numCtl.text.trim()) ?? 1,
                  'part_category': category,
                  'addiction_link': null,
                  'description': null,
                  'protected_exile_part_id': null,
                });
                final resp = await (isEdit
                        ? http.patch(uri, headers: _headers, body: body)
                        : http.post(uri, headers: _headers, body: body))
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

  Future<void> _retirePart(Map<String, dynamic> part) async {
    final id = part['id'];
    if (id == null) return;
    final uri = Uri.parse(
      '$_base/api/coach/sensitive-profile/${widget.targetUserId}/parts-registry/$id',
    );
    final resp = await http
        .delete(uri, headers: _headers)
        .timeout(const Duration(seconds: 15));
    if (!mounted) return;
    if (resp.statusCode == 200) {
      await _load();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Retire failed: ${resp.statusCode}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF050505),
      appBar: AppBar(
        backgroundColor: const Color(0xFF111111),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Color(0xFFC9A962)),
          tooltip: 'Back to Sensitive Bridge',
          onPressed: () => Navigator.of(context).maybePop(),
        ),
        title: Text(
          'Parts · ${widget.targetUserId}',
          style: const TextStyle(color: Color(0xFFC9A962), fontSize: 16),
        ),
        actions: [
          if (_safetyQueueCount > 0)
            Padding(
              padding: const EdgeInsets.only(right: 8, top: 12),
              child: Chip(
                label: Text('Safety $_safetyQueueCount',
                    style: const TextStyle(color: Colors.redAccent)),
                backgroundColor: const Color(0xFF1A1A1A),
              ),
            ),
          IconButton(
            icon: Icon(
              _tgOnly ? Icons.filter_alt : Icons.filter_alt_outlined,
              color: const Color(0xFF4ECDC4),
            ),
            tooltip: 'Training Ground parts only',
            onPressed: () => setState(() => _tgOnly = !_tgOnly),
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Color(0xFFC9A962)),
            onPressed: _loading ? null : _load,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        backgroundColor: const Color(0xFFC9A962),
        onPressed: () => _partDialog(),
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
                  itemCount: _visibleParts.length + 1,
                  itemBuilder: (_, i) {
                    if (i == 0) {
                      return const Card(
                        color: Color(0xFF111111),
                        child: Padding(
                          padding: EdgeInsets.all(12),
                          child: Text(
                            'IFS note: parts use coach-approved roles (manager, firefighter, exile, etc.). '
                            'ILM archetypes are coaching metaphors. Training Ground dialogue follows '
                            'the labels you set on approve.',
                            style: TextStyle(color: Colors.white70),
                          ),
                        ),
                      );
                    }
                    final idx = i - 1;
                    final p = _visibleParts[idx];
                    final origin = p['origin']?.toString() ?? 'sensitive_bridge';
                    final status = p['coaching_status']?.toString() ?? 'APPROVED';
                    return Card(
                      color: const Color(0xFF111111),
                      child: ListTile(
                        title: Text(
                          '${p['part_name']}',
                          style: const TextStyle(color: Color(0xFFC9A962)),
                        ),
                        subtitle: Text(
                          '${p['part_category']} · IFS ${p['ifs_role'] ?? p['part_category']} · '
                          '#${p['part_number']} · $origin · $status',
                          style: TextStyle(
                            color: status == 'PENDING_APPROVAL'
                                ? Colors.orangeAccent
                                : Colors.white54,
                          ),
                        ),
                        trailing: Wrap(
                          spacing: 4,
                          children: [
                            if (origin == 'training_ground' &&
                                status == 'PENDING_APPROVAL') ...[
                              IconButton(
                                tooltip: 'Approve',
                                icon: const Icon(Icons.check, color: Colors.greenAccent),
                                onPressed: () => _patchCoachingStatus(p, 'APPROVED'),
                              ),
                              IconButton(
                                tooltip: 'Hold',
                                icon: const Icon(Icons.pause, color: Colors.orangeAccent),
                                onPressed: () => _patchCoachingStatus(p, 'HOLD'),
                              ),
                            ],
                            IconButton(
                              tooltip: 'Edit part',
                              icon: const Icon(Icons.edit_outlined,
                                  color: Color(0xFFC9A962)),
                              onPressed: () => _partDialog(p),
                            ),
                            IconButton(
                              tooltip: 'Retire part',
                              icon: const Icon(Icons.archive_outlined,
                                  color: Colors.white54),
                              onPressed: () => _retirePart(p),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
    );
  }
}
