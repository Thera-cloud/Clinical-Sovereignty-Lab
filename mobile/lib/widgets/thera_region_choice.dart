import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

/// Story-path chips. The list comes from the API so a new region appears
/// without a new layout.
class TheraRegionChoice extends StatefulWidget {
  final String token;
  final String? initialRegion;
  final List<Map<String, String>>? initialChoices;

  const TheraRegionChoice({
    super.key,
    required this.token,
    this.initialRegion,
    this.initialChoices,
  });

  @override
  State<TheraRegionChoice> createState() => _TheraRegionChoiceState();
}

class _TheraRegionChoiceState extends State<TheraRegionChoice> {
  static const List<Map<String, String>> _fallback = [
    {
      'id': 'wander',
      'label': 'Let the path choose',
      'detail': 'Origin and Neuro take turns. Your archetype walks both.',
    },
    {
      'id': 'origin',
      'label': 'Origin',
      'detail': 'The path you already know, with your archetype.',
    },
    {
      'id': 'neuro',
      'label': 'Neuro',
      'detail': 'The places of change, with the same archetype.',
    },
  ];

  List<Map<String, String>> _regions = _fallback;
  String _selected = 'wander';
  bool _busy = false;

  String get _base =>
      AppConfig.apiBaseUrl.replaceAll(RegExp(r'/api/?$'), '').replaceAll(RegExp(r'/+$'), '');

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (widget.token.isNotEmpty) 'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _selected = (widget.initialRegion ?? 'wander').toString();
    if (widget.initialChoices != null && widget.initialChoices!.isNotEmpty) {
      _regions = widget.initialChoices!;
    }
    _load();
  }

  Future<void> _load() async {
    if (widget.token.isEmpty) return;
    try {
      final resp = await http.get(
        Uri.parse('$_base/api/sse-client/explore-regions'),
        headers: _headers,
      );
      if (resp.statusCode != 200 || !mounted) return;
      final data = jsonDecode(resp.body);
      if (data is! Map) return;
      final raw = data['regions'];
      final next = <Map<String, String>>[];
      if (raw is List) {
        for (final item in raw) {
          if (item is Map) {
            next.add({
              'id': (item['id'] ?? '').toString(),
              'label': (item['label'] ?? '').toString(),
              'detail': (item['detail'] ?? '').toString(),
            });
          }
        }
      }
      if (!mounted) return;
      setState(() {
        if (next.isNotEmpty) _regions = next;
        final sel = (data['selected'] ?? _selected).toString();
        if (sel.isNotEmpty) _selected = sel;
      });
    } catch (_) {}
  }

  Future<void> _pick(String id) async {
    if (_busy || id.isEmpty || widget.token.isEmpty) return;
    setState(() {
      _busy = true;
      _selected = id;
    });
    try {
      await http.post(
        Uri.parse('$_base/api/sse-client/explore-region'),
        headers: _headers,
        body: jsonEncode({'region': id}),
      );
    } catch (_) {}
    if (mounted) setState(() => _busy = false);
  }

  @override
  Widget build(BuildContext context) {
    if (_regions.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Where your archetype walks next',
            style: TextStyle(color: Color(0xFFE8D5A3), fontSize: 12, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final r in _regions)
                ChoiceChip(
                  label: Text(r['label'] ?? r['id'] ?? ''),
                  selected: _selected == r['id'],
                  onSelected: _busy ? null : (_) => _pick(r['id'] ?? ''),
                  selectedColor: const Color(0xFFC9A962),
                  backgroundColor: const Color(0xFF111111),
                  labelStyle: TextStyle(
                    color: _selected == r['id'] ? const Color(0xFF050505) : const Color(0xFFE8D5A3),
                    fontSize: 12,
                  ),
                ),
            ],
          ),
          if (_selected.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                _regions.firstWhere(
                  (r) => r['id'] == _selected,
                  orElse: () => const {'detail': ''},
                )['detail'] ??
                    '',
                style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11),
              ),
            ),
        ],
      ),
    );
  }
}
