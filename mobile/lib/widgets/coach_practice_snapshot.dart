import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'print_html_stub.dart' if (dart.library.html) 'print_html_web.dart';

/// Roster healing scatter + mean line. Hover names (UI only). Print is nameless.
class CoachPracticeSnapshotCard extends StatefulWidget {
  final String apiBase;
  final Map<String, String> headers;
  final String? targetCoachUsername;
  final bool compact;
  final String? headlineHint;

  const CoachPracticeSnapshotCard({
    super.key,
    required this.apiBase,
    required this.headers,
    this.targetCoachUsername,
    this.compact = false,
    this.headlineHint,
  });

  @override
  State<CoachPracticeSnapshotCard> createState() =>
      _CoachPracticeSnapshotCardState();
}

class _CoachPracticeSnapshotCardState extends State<CoachPracticeSnapshotCard> {
  int _days = 90;
  bool _loading = false;
  bool _printing = false;
  Map<String, dynamic>? _snap;
  String? _hover;
  double _zoomStart = 0;
  double _zoomEnd = 1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant CoachPracticeSnapshotCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.targetCoachUsername != widget.targetCoachUsername) {
      _load();
    }
  }

  Future<void> _load() async {
    if (_loading) return;
    setState(() => _loading = true);
    try {
      final q = <String, String>{'days': '$_days'};
      if ((widget.targetCoachUsername ?? '').isNotEmpty) {
        q['coach'] = widget.targetCoachUsername!;
      }
      final uri = Uri.parse('${widget.apiBase}/api/coach/practice/snapshot')
          .replace(queryParameters: q);
      final resp = await http.get(uri, headers: widget.headers);
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _snap = Map<String, dynamic>.from(data['snapshot'] ?? {});
          _zoomStart = 0;
          _zoomEnd = 1;
        });
      }
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _print() async {
    if (_printing) return;
    setState(() => _printing = true);
    try {
      final resp = await http.post(
        Uri.parse('${widget.apiBase}/api/coach/practice/report'),
        headers: {
          ...widget.headers,
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'days': _days,
          if ((widget.targetCoachUsername ?? '').isNotEmpty)
            'coach_username': widget.targetCoachUsername,
        }),
      );
      if (!mounted) return;
      if (resp.statusCode != 200) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Print failed (${resp.statusCode})'),
          backgroundColor: Colors.red.shade800,
        ));
        return;
      }
      final data = jsonDecode(resp.body);
      final printUrl = data['print_url']?.toString() ?? '';
      if (printUrl.isEmpty) return;
      final htmlResp = await http.get(
        Uri.parse('${widget.apiBase}$printUrl'),
        headers: widget.headers,
      );
      if (htmlResp.statusCode == 200 && htmlResp.body.contains('Sovereign Sanctuary')) {
        if (kIsWeb) openPrintHtml(htmlResp.body);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Print failed: $e'),
          backgroundColor: Colors.red.shade800,
        ));
      }
    }
    if (mounted) setState(() => _printing = false);
  }

  void _onWheel(PointerScrollEvent e, Size size) {
    if (e.scrollDelta.dy == 0) return;
    final local = e.localPosition;
    final t = (local.dx / size.width).clamp(0.0, 1.0);
    final span = _zoomEnd - _zoomStart;
    final next = e.scrollDelta.dy > 0
        ? (span * 1.12).clamp(0.12, 1.0)
        : (span * 0.88).clamp(0.12, 1.0);
    var start = t - next * ((t - _zoomStart) / span);
    var end = start + next;
    if (start < 0) {
      end -= start;
      start = 0;
    }
    if (end > 1) {
      start -= (end - 1);
      end = 1;
    }
    setState(() {
      _zoomStart = start.clamp(0.0, 1.0);
      _zoomEnd = end.clamp(0.0, 1.0);
    });
  }

  @override
  Widget build(BuildContext context) {
    final coach = (_snap?['coach'] as Map?) ?? {};
    final master = _snap?['master'] as Map?;
    final totals = (_snap?['totals'] as Map?) ?? {};
    final height = widget.compact ? 148.0 : 228.0;
    final title = widget.headlineHint ??
        '${coach['display_name'] ?? 'Practice'} · ${_days}d snapshot';

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: const Color(0xFF0A0A0A),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFC9A962).withOpacity(0.28)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.insights, color: Color(0xFFC9A962), size: 16),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    color: Color(0xFFE8D5A3),
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              ...[30, 90, 180].map((d) {
                final on = _days == d;
                return Padding(
                  padding: const EdgeInsets.only(left: 4),
                  child: InkWell(
                    onTap: () {
                      setState(() => _days = d);
                      _load();
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: on
                            ? const Color(0xFFC9A962).withOpacity(0.2)
                            : Colors.transparent,
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(
                          color: on
                              ? const Color(0xFFC9A962)
                              : Colors.white24,
                        ),
                      ),
                      child: Text('${d}d',
                          style: TextStyle(
                              color: on
                                  ? const Color(0xFFC9A962)
                                  : Colors.white54,
                              fontSize: 10,
                              fontWeight: FontWeight.bold)),
                    ),
                  ),
                );
              }),
              const SizedBox(width: 8),
              TextButton(
                onPressed: () => setState(() {
                  _zoomStart = 0;
                  _zoomEnd = 1;
                }),
                child: const Text('Reset',
                    style: TextStyle(color: Color(0xFF8B7355), fontSize: 11)),
              ),
              if (_printing)
                const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                        strokeWidth: 1.4, color: Color(0xFFC9A962)))
              else
                IconButton(
                  tooltip: 'Print review (no client names)',
                  icon: const Icon(Icons.print,
                      color: Color(0xFFC9A962), size: 18),
                  onPressed: _print,
                ),
            ],
          ),
          if (master != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                'Master: ${master['display_name'] ?? ''} · @${master['username'] ?? ''}',
                style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11),
              ),
            ),
          if (_loading && _snap == null)
            const SizedBox(
              height: 80,
              child: Center(
                child: CircularProgressIndicator(
                    strokeWidth: 1.5, color: Color(0xFFC9A962)),
              ),
            )
          else
            SizedBox(
              height: height,
              child: LayoutBuilder(
                builder: (context, box) {
                  final size = Size(box.maxWidth, height);
                  return Listener(
                    onPointerSignal: (sig) {
                      if (sig is PointerScrollEvent) _onWheel(sig, size);
                    },
                    child: MouseRegion(
                      onHover: (e) {
                        final series = List<Map<String, dynamic>>.from(
                            _snap?['series'] ?? []);
                        final scatter = List<Map<String, dynamic>>.from(
                            _snap?['scatter'] ?? []);
                        final label = _hoverAt(
                            e.localPosition, size, series, scatter);
                        if (label != _hover) setState(() => _hover = label);
                      },
                      onExit: (_) => setState(() => _hover = null),
                      child: CustomPaint(
                        size: size,
                        painter: _PracticePainter(
                          series: List<Map<String, dynamic>>.from(
                              _snap?['series'] ?? []),
                          scatter: List<Map<String, dynamic>>.from(
                              _snap?['scatter'] ?? []),
                          zoomStart: _zoomStart,
                          zoomEnd: _zoomEnd,
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
          if (_hover != null)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(_hover!,
                  style: const TextStyle(
                      color: Color(0xFF4ECDC4), fontSize: 11)),
            ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 10,
            runSpacing: 4,
            children: [
              _stat('Healing', _fmt(totals['healing_mean'])),
              _stat('Dips', '${totals['cycle_dips'] ?? 0}'),
              _stat('LN', '${totals['ln_turns'] ?? 0}'),
              _stat('Live', '${totals['live_sessions'] ?? 0}'),
              _stat('Book', '${totals['roster'] ?? 0}'),
            ],
          ),
        ],
      ),
    );
  }

  String _fmt(dynamic v) {
    if (v is num) return v.toStringAsFixed(3);
    return '—';
  }

  Widget _stat(String k, String v) {
    return Text('$k $v',
        style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11));
  }

  String? _hoverAt(
    Offset pos,
    Size size,
    List<Map<String, dynamic>> series,
    List<Map<String, dynamic>> scatter,
  ) {
    if (series.isEmpty) return null;
    final vis = _visible(series);
    if (vis.isEmpty) return null;
    String? best;
    var bestD = 14.0;
    for (final p in scatter) {
      final date = p['date']?.toString();
      final idx = vis.indexWhere((s) => s['date'] == date);
      if (idx < 0) continue;
      final h = p['healing'];
      if (h is! num) continue;
      final x = size.width * (idx / math.max(vis.length - 1, 1));
      final y = size.height * (1 - h.toDouble().clamp(0.0, 1.0));
      final d = (Offset(x, y) - pos).distance;
      if (d < bestD) {
        bestD = d;
        final name = p['client']?.toString();
        final kind = p['kind']?.toString() ?? '';
        best = name == null
            ? '${p['date']} · $kind'
            : '$name · ${p['date']} · healing ${h.toStringAsFixed(3)}';
      }
    }
    return best;
  }

  List<Map<String, dynamic>> _visible(List<Map<String, dynamic>> series) {
    if (series.isEmpty) return series;
    final a = (_zoomStart * series.length).floor().clamp(0, series.length - 1);
    final b = (_zoomEnd * series.length).ceil().clamp(a + 1, series.length);
    return series.sublist(a, b);
  }
}

class _PracticePainter extends CustomPainter {
  final List<Map<String, dynamic>> series;
  final List<Map<String, dynamic>> scatter;
  final double zoomStart;
  final double zoomEnd;

  _PracticePainter({
    required this.series,
    required this.scatter,
    required this.zoomStart,
    required this.zoomEnd,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (series.isEmpty) return;
    final a = (zoomStart * series.length).floor().clamp(0, series.length - 1);
    final b = (zoomEnd * series.length).ceil().clamp(a + 1, series.length);
    final vis = series.sublist(a, b);
    final n = math.max(vis.length - 1, 1);

    final grid = Paint()
      ..color = const Color(0x22FFFFFF)
      ..strokeWidth = 1;
    for (var i = 1; i < 4; i++) {
      final y = size.height * (i / 4);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    final tick = Paint()
      ..color = const Color(0x59C9A962)
      ..strokeWidth = 1;
    for (var i = 0; i < vis.length; i++) {
      if (vis[i]['live'] == true) {
        final x = size.width * (i / n);
        canvas.drawLine(Offset(x, 0), Offset(x, size.height), tick);
      }
    }

    final path = Path();
    var started = false;
    for (var i = 0; i < vis.length; i++) {
      final h = vis[i]['healing_mean'];
      if (h is! num) continue;
      final x = size.width * (i / n);
      final y = size.height * (1 - h.toDouble().clamp(0.0, 1.0));
      if (!started) {
        path.moveTo(x, y);
        started = true;
      } else {
        path.lineTo(x, y);
      }
    }
    if (started) {
      canvas.drawPath(
        path,
        Paint()
          ..color = const Color(0xFFC9A962)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2,
      );
    }

    final gold = Paint()..color = const Color(0xFFE8D5A3);
    final dip = Paint()..color = const Color(0xFFEF4444);
    final live = Paint()
      ..color = const Color(0xFFC9A962)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4;
    for (final p in scatter) {
      final date = p['date']?.toString();
      final idx = vis.indexWhere((s) => s['date'] == date);
      if (idx < 0) continue;
      final h = p['healing'];
      if (h is! num) continue;
      final x = size.width * (idx / n);
      final y = size.height * (1 - h.toDouble().clamp(0.0, 1.0));
      final kind = p['kind']?.toString() ?? '';
      canvas.drawCircle(Offset(x, y), 3.2, kind == 'cycle_dip' ? dip : gold);
      if (kind == 'live_session') {
        canvas.drawCircle(Offset(x, y), 5.2, live);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _PracticePainter old) =>
      old.series != series ||
      old.zoomStart != zoomStart ||
      old.zoomEnd != zoomEnd;
}
