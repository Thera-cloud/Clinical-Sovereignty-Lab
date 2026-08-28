// QUANTUM-CRYSTAL-ARCH — A/C/D persona review, suggestion diff, private booth.
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../config/app_config.dart';

class CoachStudioPersonaTools extends StatefulWidget {
  final String token;
  final int epoch;
  final List<Map<String, dynamic>> pendingDiff;
  const CoachStudioPersonaTools({
    super.key,
    required this.token,
    this.epoch = 0,
    this.pendingDiff = const [],
  });

  @override
  State<CoachStudioPersonaTools> createState() => _CoachStudioPersonaToolsState();
}

class _CoachStudioPersonaToolsState extends State<CoachStudioPersonaTools> {
  static const _gold = Color(0xFFC9A962);
  static const _muted = Color(0xFF8B7355);
  static const _text = Color(0xFFE8D5A3);

  final _suggestCtrl = TextEditingController();
  final _boothCtrl = TextEditingController();
  final Map<String, TextEditingController> _strCtrls = {};
  final Map<String, TextEditingController> _listAdd = {};
  Map<String, dynamic> _style = {};
  List<String> _stringKeys = const [];
  List<String> _listKeys = const [];
  List<Map<String, dynamic>> _diff = [];
  String _boothKind = 'newsletter_open';
  String _boothReply = '';
  bool _busy = false;

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _diff = List<Map<String, dynamic>>.from(widget.pendingDiff);
    _load();
  }

  @override
  void didUpdateWidget(CoachStudioPersonaTools old) {
    super.didUpdateWidget(old);
    if (old.epoch != widget.epoch) {
      _diff = List<Map<String, dynamic>>.from(widget.pendingDiff);
      _load();
    }
  }

  @override
  void dispose() {
    _suggestCtrl.dispose();
    _boothCtrl.dispose();
    for (final c in _strCtrls.values) {
      c.dispose();
    }
    for (final c in _listAdd.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _syncCtrls() {
    for (final k in _stringKeys) {
      _strCtrls.putIfAbsent(k, () => TextEditingController());
      _strCtrls[k]!.text = (_style[k] ?? '').toString();
    }
    for (final k in _listKeys) {
      _listAdd.putIfAbsent(k, () => TextEditingController());
    }
  }

  Future<void> _load() async {
    try {
      final r = await http.get(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/persona'),
        headers: _h,
      );
      if (!mounted || r.statusCode != 200) return;
      final j = json.decode(r.body) as Map<String, dynamic>;
      setState(() {
        _style = Map<String, dynamic>.from(j['style'] ?? {});
        final ed = Map<String, dynamic>.from(j['editable'] ?? {});
        _stringKeys = List<String>.from(ed['strings'] ?? []);
        _listKeys = List<String>.from(ed['lists'] ?? []);
        _syncCtrls();
      });
    } catch (_) {}
  }

  List<String> _listOf(String key) =>
      List<String>.from((_style[key] as List?) ?? const []);

  Future<void> _save() async {
    final payload = <String, dynamic>{};
    for (final k in _stringKeys) {
      payload[k] = _strCtrls[k]?.text.trim() ?? '';
    }
    for (final k in _listKeys) {
      payload[k] = _listOf(k);
    }
    setState(() => _busy = true);
    try {
      final r = await http.put(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/persona'),
        headers: _h,
        body: json.encode({'style': payload}),
      );
      if (!mounted) return;
      if (r.statusCode == 200) {
        final j = json.decode(r.body) as Map<String, dynamic>;
        setState(() {
          _style = Map<String, dynamic>.from(j['style'] ?? payload);
          _syncCtrls();
        });
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(r.statusCode == 200
              ? 'Persona saved — LN will use your edits'
              : 'Save failed (${r.statusCode})')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _suggest() async {
    final note = _suggestCtrl.text.trim();
    if (note.isEmpty) return;
    setState(() => _busy = true);
    try {
      final r = await http.post(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/finalize'),
        headers: _h,
        body: json.encode({'coach_note': note}),
      );
      if (!mounted) return;
      if (r.statusCode == 200) {
        final j = json.decode(r.body) as Map<String, dynamic>;
        setState(() {
          _diff = List<Map<String, dynamic>>.from(j['diff'] ?? []);
          if (j['style'] is Map) {
            _style = Map<String, dynamic>.from(j['style'] as Map);
            _syncCtrls();
          }
        });
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(r.statusCode == 200
              ? 'Suggestion applied as a diff — accept or reject lines'
              : 'Suggestion failed (${r.statusCode})')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _applyOps(List<Map<String, dynamic>> ops) async {
    if (ops.isEmpty) return;
    setState(() => _busy = true);
    try {
      final r = await http.post(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/style/apply'),
        headers: _h,
        body: json.encode({'accept': ops}),
      );
      if (!mounted) return;
      if (r.statusCode == 200) {
        final j = json.decode(r.body) as Map<String, dynamic>;
        setState(() {
          _style = Map<String, dynamic>.from(j['style'] ?? _style);
          _diff = _diff
              .where((d) => !ops.any((o) =>
                  o['key'] == d['key'] &&
                  o['op'] == d['op'] &&
                  '${o['value']}' == '${d['value']}'))
              .toList();
          _syncCtrls();
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _booth() async {
    setState(() => _busy = true);
    try {
      final r = await http.post(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/booth'),
        headers: _h,
        body: json.encode({
          'kind': _boothKind,
          'text': _boothCtrl.text.trim(),
        }),
      );
      if (!mounted) return;
      if (r.statusCode == 200) {
        final j = json.decode(r.body) as Map<String, dynamic>;
        setState(() => _boothReply = (j['reply'] ?? '').toString());
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Booth failed (${r.statusCode})')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verdict(String v) async {
    setState(() => _busy = true);
    try {
      final r = await http.post(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/booth/feedback'),
        headers: _h,
        body: json.encode({
          'verdict': v,
          'note': _suggestCtrl.text.trim(),
          'reply': _boothReply,
        }),
      );
      if (!mounted) return;
      if (r.statusCode == 200) {
        final j = json.decode(r.body) as Map<String, dynamic>;
        setState(() {
          _style = Map<String, dynamic>.from(j['style'] ?? _style);
          _syncCtrls();
        });
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(r.statusCode == 200
              ? 'Booth note saved to persona'
              : 'Feedback failed (${r.statusCode})')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('PERSONA REVIEW',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        const Text(
          'This is what LN thinks you sound like. Edit anything that is not you, then save.',
          style: TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 8),
        ..._stringKeys.map((k) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: TextField(
                controller: _strCtrls[k],
                style: const TextStyle(color: _text, fontSize: 13),
                decoration: InputDecoration(
                  labelText: k.replaceAll('_', ' '),
                  labelStyle: const TextStyle(color: _muted, fontSize: 11),
                ),
              ),
            )),
        ..._listKeys.map((k) {
          final items = _listOf(k);
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(k.replaceAll('_', ' '),
                    style: const TextStyle(color: _muted, fontSize: 11)),
                Wrap(
                  spacing: 6,
                  children: items
                      .map((item) => InputChip(
                            label: Text(item,
                                style: const TextStyle(fontSize: 11)),
                            onDeleted: _busy
                                ? null
                                : () => setState(() {
                                      _style[k] = items
                                          .where((x) => x != item)
                                          .toList();
                                    }),
                          ))
                      .toList(),
                ),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _listAdd[k],
                        style: const TextStyle(color: _text, fontSize: 12),
                        decoration: const InputDecoration(
                          hintText: 'Add line',
                          hintStyle: TextStyle(color: _muted),
                        ),
                      ),
                    ),
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () {
                              final v = _listAdd[k]?.text.trim() ?? '';
                              if (v.isEmpty) return;
                              setState(() {
                                _style[k] = [...items, v];
                                _listAdd[k]!.clear();
                              });
                            },
                      child: const Text('Add'),
                    ),
                  ],
                ),
              ],
            ),
          );
        }),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: _gold),
          onPressed: _busy ? null : _save,
          child: const Text('Save persona edits',
              style: TextStyle(color: Colors.black)),
        ),
        const SizedBox(height: 16),
        const Text('SUGGESTION BOX',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        TextField(
          controller: _suggestCtrl,
          maxLines: 2,
          style: const TextStyle(color: _text, fontSize: 12),
          decoration: const InputDecoration(
            hintText: 'I never say journey. I close with one invitation.',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        TextButton(
          onPressed: _busy ? null : _suggest,
          child: const Text('Apply suggestion → show diff'),
        ),
        if (_diff.isNotEmpty) ...[
          const Text('Proposed changes',
              style: TextStyle(color: _muted, fontSize: 12)),
          ..._diff.map((d) => ListTile(
                dense: true,
                title: Text(
                  '${d['op']} ${d['key']}: ${d['value']}',
                  style: const TextStyle(color: _text, fontSize: 12),
                ),
                trailing: TextButton(
                  onPressed: _busy ? null : () => _applyOps([d]),
                  child: const Text('Accept'),
                ),
              )),
          TextButton(
            onPressed: _busy
                ? null
                : () => _applyOps(_diff
                    .where((d) => d['op'] == 'add' || d['op'] == 'set')
                    .toList()),
            child: const Text('Accept additions'),
          ),
        ],
        const SizedBox(height: 16),
        const Text('LIKENESS BOOTH (not public)',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const Text(
          'Private test. Nothing publishes. Mark not-me to add a do-not.',
          style: TextStyle(color: _muted, fontSize: 12),
        ),
        DropdownButton<String>(
          value: _boothKind,
          dropdownColor: const Color(0xFF111111),
          isExpanded: true,
          items: const [
            DropdownMenuItem(
                value: 'newsletter_open',
                child: Text('Newsletter open',
                    style: TextStyle(color: _text, fontSize: 12))),
            DropdownMenuItem(
                value: 'toss',
                child: Text('Toss to Nate',
                    style: TextStyle(color: _text, fontSize: 12))),
            DropdownMenuItem(
                value: 'caller_recovery',
                child: Text('Caller recovery',
                    style: TextStyle(color: _text, fontSize: 12))),
            DropdownMenuItem(
                value: 'free',
                child: Text('Free prompt',
                    style: TextStyle(color: _text, fontSize: 12))),
          ],
          onChanged: (v) => setState(() => _boothKind = v ?? _boothKind),
        ),
        TextField(
          controller: _boothCtrl,
          maxLines: 2,
          style: const TextStyle(color: _text, fontSize: 12),
          decoration: const InputDecoration(
            hintText: 'Paste a line or topic to test',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        TextButton(
          onPressed: _busy ? null : _booth,
          child: const Text('Generate private sample'),
        ),
        if (_boothReply.isNotEmpty) ...[
          Text(_boothReply,
              style: const TextStyle(color: _text, fontSize: 13)),
          Wrap(
            spacing: 8,
            children: [
              TextButton(
                  onPressed: _busy ? null : () => _verdict('like_me'),
                  child: const Text('Like me')),
              TextButton(
                  onPressed: _busy ? null : () => _verdict('not_me'),
                  child: const Text('Not me')),
              TextButton(
                  onPressed: _busy ? null : () => _verdict('too_soft'),
                  child: const Text('Too soft')),
            ],
          ),
        ],
      ],
    );
  }
}
