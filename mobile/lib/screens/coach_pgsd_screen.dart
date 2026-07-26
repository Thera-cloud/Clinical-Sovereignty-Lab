/// Coach PGSD field view — QUANTUM-CRYSTAL-ARCH (Tier 2)
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/app_config.dart';

class _PG {
  static const bg = Color(0xFF050505);
  static const card = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const text = Color(0xFFE8E8E8);
  static const muted = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
}

Map<String, String> _authHeaders(Map profile) {
  final token = (profile['token'] ?? '').toString();
  return {
    'Content-Type': 'application/json',
    if (token.isNotEmpty) 'Authorization': 'Bearer $token',
  };
}

/// Client-scoped PGSD ACCESS/FIELD briefing for coaches.
class CoachPgsdScreen extends StatefulWidget {
  final Map profile;
  final String clientId;
  final String? clientName;

  const CoachPgsdScreen({
    super.key,
    required this.profile,
    required this.clientId,
    this.clientName,
  });

  @override
  State<CoachPgsdScreen> createState() => _CoachPgsdScreenState();
}

class _CoachPgsdScreenState extends State<CoachPgsdScreen> {
  Map<String, dynamic>? _data;
  Map<String, dynamic>? _flags;
  String? _error;
  bool _loading = true;

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
      final headers = _authHeaders(widget.profile);
      final base = AppConfig.apiBaseUrl;
      final fResp = await http.get(
        Uri.parse('$base/api/coach/pgsd/flags'),
        headers: headers,
      );
      final cResp = await http.get(
        Uri.parse('$base/api/coach/pgsd/client/${widget.clientId}'),
        headers: headers,
      );
      if (!mounted) return;
      if (fResp.statusCode == 200) {
        _flags = jsonDecode(fResp.body) as Map<String, dynamic>;
      }
      if (cResp.statusCode == 200) {
        _data = jsonDecode(cResp.body) as Map<String, dynamic>;
        _error = null;
      } else {
        _error = 'PGSD load failed (${cResp.statusCode})';
      }
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    final title = widget.clientName?.isNotEmpty == true
        ? 'PGSD · ${widget.clientName}'
        : 'PGSD Field';
    return Scaffold(
      backgroundColor: _PG.bg,
      appBar: AppBar(
        backgroundColor: _PG.bg,
        title: Text(title,
            style: const TextStyle(
                color: _PG.gold, fontFamily: 'CormorantGaramond')),
        iconTheme: const IconThemeData(color: _PG.gold),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _load,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _PG.gold))
          : _error != null
              ? Center(
                  child: Text(_error!,
                      style: const TextStyle(color: Colors.redAccent)))
              : RefreshIndicator(
                  color: _PG.gold,
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      _flagsCard(),
                      const SizedBox(height: 12),
                      _briefingCard(),
                      const SizedBox(height: 12),
                      _snapshotCard(),
                      const SizedBox(height: 12),
                      _discernmentCard(),
                      const SizedBox(height: 12),
                      _crossDomainCard(),
                      const SizedBox(height: 12),
                      _fieldCard(),
                    ],
                  ),
                ),
    );
  }

  Widget _card(String title, List<Widget> children) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _PG.card,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _PG.gold.withOpacity(0.25)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: const TextStyle(
                  color: _PG.gold,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1)),
          const SizedBox(height: 10),
          ...children,
        ],
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(
          children: [
            SizedBox(
                width: 120,
                child: Text(k, style: const TextStyle(color: _PG.muted))),
            Expanded(
                child: Text(v, style: const TextStyle(color: _PG.text))),
          ],
        ),
      );

  Widget _flagsCard() {
    final f = _flags ?? {};
    return _card('FLAGS', [
      _kv('PGSD', '${f['PGSD_ENABLED']}'),
      _kv('ACCESS', '${f['ENABLE_PGSD_ACCESS']}'),
      _kv('FIELD', '${f['ENABLE_PGSD_FIELD']}'),
      _kv('HEARTBEAT', '${f['ENABLE_PGSD_HEARTBEAT']}'),
    ]);
  }

  Widget _briefingCard() {
    final brief = (_data?['briefing'] ?? '').toString();
    return _card('BRIEFING', [
      Text(
        brief.isEmpty ? 'No briefing (ACCESS/FIELD off or no rows).' : brief,
        style: const TextStyle(color: _PG.cyan, height: 1.35),
      ),
    ]);
  }

  Widget _snapshotCard() {
    final s = _data?['snapshot'];
    if (s is! Map) {
      return _card('SNAPSHOT', [
        const Text('None', style: TextStyle(color: _PG.muted)),
      ]);
    }
    return _card('SNAPSHOT', [
      _kv('coherence', '${s['coherence']}'),
      _kv('d4', '${s['d4_temporal_depth']}'),
      _kv('region', '${s['session_region'] ?? '—'}'),
      _kv('source', '${s['trigger_source'] ?? '—'}'),
      _kv('at', '${s['computed_at'] ?? '—'}'),
    ]);
  }

  Widget _discernmentCard() {
    final d = _data?['discernment'];
    if (d is! Map) {
      return _card('DISCERNMENT', [
        const Text('None (ACCESS)', style: TextStyle(color: _PG.muted)),
      ]);
    }
    return _card('DISCERNMENT', [
      _kv('composite', '${d['composite']}'),
      _kv('past', '${d['past']}'),
      _kv('present', '${d['present']}'),
      _kv('future', '${d['future']}'),
    ]);
  }

  Widget _crossDomainCard() {
    final c = _data?['cross_domain'];
    if (c is! Map) {
      return _card('CROSS-DOMAIN', [
        const Text('None (ACCESS)', style: TextStyle(color: _PG.muted)),
      ]);
    }
    return _card('CROSS-DOMAIN', [
      _kv('agreement', '${c['agreement_score']}'),
      _kv('surfaces', '${c['surfaces']}'),
    ]);
  }

  Widget _fieldCard() {
    final fieldOn = _data?['field'] == true;
    if (!fieldOn) {
      return _card('FIELD (Patent 12)', [
        const Text('ENABLE_PGSD_FIELD is off',
            style: TextStyle(color: _PG.muted)),
      ]);
    }
    final wells = (_data?['trauma_wells'] as List?) ?? const [];
    final g = _data?['ground_state'];
    final kids = <Widget>[
      if (g is Map) ...[
        _kv('ground E', '${g['ground_energy']}'),
        _kv('relocation', '${g['relocation']}'),
      ],
      if (wells.isEmpty)
        const Text('No trauma wells', style: TextStyle(color: _PG.muted)),
      for (final w in wells)
        if (w is Map)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text(
              '${w['temporal_class']} · depth=${w['depth']} · collapsed=${w['collapsed']}',
              style: const TextStyle(color: _PG.text, fontSize: 13),
            ),
          ),
    ];
    return _card('FIELD (Patent 12)', kids);
  }
}
