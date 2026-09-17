import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'print_html_stub.dart' if (dart.library.html) 'print_html_web.dart';

/// Roster mean (gold line) + client scatter. Hover names UI-only. Print nameless.
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
  Offset? _hoverPos;
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
          _hover = null;
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
      if (htmlResp.statusCode == 200 &&
          htmlResp.body.contains('Sovereign Sanctuary')) {
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

  void _resetZoom() {
    setState(() {
      _zoomStart = 0;
      _zoomEnd = 1;
    });
  }

  void _onWheel(PointerScrollEvent e, Size size, int seriesLen) {
    GestureBinding.instance.pointerSignalResolver.register(e, (event) {
      final ev = event as PointerScrollEvent;
      if (ev.scrollDelta.dy == 0) return;
      final geom = _ChartGeom(size, math.max(seriesLen, 1));
      if (!geom.plot.contains(ev.localPosition)) return;
      final minSpan = math.max(7.0 / math.max(seriesLen, 7), 0.22);
      final next = ev.scrollDelta.dy > 0
          ? (_zoomEnd * 1.12).clamp(minSpan, 1.0)
          : (_zoomEnd * 0.88).clamp(minSpan, 1.0);
      setState(() {
        _zoomStart = 0;
        _zoomEnd = next;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final coach = (_snap?['coach'] as Map?) ?? {};
    final master = _snap?['master'] as Map?;
    final totals = (_snap?['totals'] as Map?) ?? {};
    final height = widget.compact ? 236.0 : 320.0;
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
                onPressed: _resetZoom,
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
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                'Master: ${master['display_name'] ?? ''} · @${master['username'] ?? ''}',
                style: const TextStyle(color: Color(0xFF8B7355), fontSize: 11),
              ),
            ),
          const Padding(
            padding: EdgeInsets.only(bottom: 6),
            child: Text(
              'Origin bottom-left. Days → right. Healing 0–1 ↑. Gold = roster mean   ● client   ◯ live   ● dip',
              style: TextStyle(color: Color(0xFF8B7355), fontSize: 10),
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
                  final series = List<Map<String, dynamic>>.from(
                      _snap?['series'] ?? []);
                  final scatter = List<Map<String, dynamic>>.from(
                      _snap?['scatter'] ?? []);
                  final vis = _visible(series);
                  return Listener(
                    behavior: HitTestBehavior.opaque,
                    onPointerSignal: (sig) {
                      if (sig is PointerScrollEvent) {
                        _onWheel(sig, size, series.length);
                      }
                    },
                    child: GestureDetector(
                      onDoubleTap: _resetZoom,
                      child: MouseRegion(
                        onHover: (e) {
                          final label = _hoverAt(
                              e.localPosition, size, vis, scatter);
                          if (label != _hover || _hoverPos != e.localPosition) {
                            setState(() {
                              _hover = label;
                              _hoverPos = e.localPosition;
                            });
                          }
                        },
                        onExit: (_) => setState(() {
                          _hover = null;
                          _hoverPos = null;
                        }),
                        child: Stack(
                          clipBehavior: Clip.hardEdge,
                          children: [
                            CustomPaint(
                              size: size,
                              painter: _PracticePainter(
                                series: vis,
                                scatter: scatter,
                                dayMax: vis.isEmpty ? _days : vis.length,
                              ),
                            ),
                            if (_hover != null && _hoverPos != null)
                              Positioned(
                                left: (_hoverPos!.dx + 12)
                                    .clamp(0.0, math.max(0.0, size.width - 220)),
                                top: (_hoverPos!.dy - 52)
                                    .clamp(0.0, math.max(0.0, size.height - 56)),
                                child: IgnorePointer(
                                  child: Container(
                                    constraints:
                                        const BoxConstraints(maxWidth: 220),
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 8, vertical: 6),
                                    decoration: BoxDecoration(
                                      color: const Color(0xF0111111),
                                      borderRadius: BorderRadius.circular(6),
                                      border: Border.all(
                                          color: const Color(0xFF4ECDC4)
                                              .withOpacity(0.55)),
                                    ),
                                    child: Text(
                                      _hover!,
                                      style: const TextStyle(
                                        color: Color(0xFFE8D5A3),
                                        fontSize: 11,
                                        height: 1.35,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
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
    List<Map<String, dynamic>> vis,
    List<Map<String, dynamic>> scatter,
  ) {
    if (vis.isEmpty) return null;
    final geom = _ChartGeom(size, vis.length);
    if (!geom.plot.contains(pos)) {
      final mean = _meanAt(pos, vis, geom);
      return mean;
    }
    String? best;
    var bestD = 16.0;
    for (final p in scatter) {
      final date = p['date']?.toString();
      final idx = vis.indexWhere((s) => s['date'] == date);
      if (idx < 0) continue;
      final h = p['healing'];
      if (h is! num) continue;
      final pt = geom.point(idx, h.toDouble(), p['client']?.toString() ?? '');
      final d = (pt - pos).distance;
      if (d < bestD) {
        bestD = d;
        final name = p['client']?.toString();
        final kind = p['kind']?.toString() ?? '';
        final ln = p['ln'] ?? 0;
        final live = p['live'] == true ? 'yes' : 'no';
        final label = name == null || name.isEmpty ? 'Client' : name;
        best =
            '$label\n${p['date']} · $kind ${h.toStringAsFixed(3)}\nLN $ln that day · Live $live';
      }
    }
    return best ?? _meanAt(pos, vis, geom);
  }

  String? _meanAt(
      Offset pos, List<Map<String, dynamic>> vis, _ChartGeom geom) {
    if (vis.isEmpty) return null;
    final t = ((pos.dx - geom.plot.left) / geom.plot.width).clamp(0.0, 1.0);
    final idx = (t * (vis.length - 1)).round().clamp(0, vis.length - 1);
    final h = vis[idx]['healing_mean'];
    if (h is! num) return null;
    return 'Roster mean · ${vis[idx]['date']} · ${h.toStringAsFixed(3)}';
  }

  List<Map<String, dynamic>> _visible(List<Map<String, dynamic>> series) {
    if (series.isEmpty) return series;
    final b = (_zoomEnd * series.length).ceil().clamp(1, series.length);
    return series.sublist(0, b);
  }
}

class _ChartGeom {
  final Size size;
  final int count;
  static const padL = 56.0;
  static const padR = 16.0;
  static const padT = 14.0;
  static const padB = 48.0;

  _ChartGeom(this.size, this.count);

  Rect get plot => Rect.fromLTWH(
        padL,
        padT,
        math.max(1, size.width - padL - padR),
        math.max(1, size.height - padT - padB),
      );

  Offset point(int idx, double healing, String jitterKey) {
    final n = math.max(count - 1, 1);
    final x = plot.left + plot.width * (idx / n);
    final y = plot.top + plot.height * (1 - healing.clamp(0.0, 1.0));
    final h = jitterKey.hashCode;
    return Offset(
      x + ((h % 13) - 6).toDouble(),
      y + (((h ~/ 13) % 15) - 7).toDouble(),
    );
  }
}

class _PracticePainter extends CustomPainter {
  final List<Map<String, dynamic>> series;
  final List<Map<String, dynamic>> scatter;
  final int dayMax;

  _PracticePainter({
    required this.series,
    required this.scatter,
    required this.dayMax,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final count = math.max(series.length, 2);
    final geom = _ChartGeom(size, count);
    final plot = geom.plot;
    final n = math.max(count - 1, 1);
    final xMax = math.max(dayMax, 1);

    final grid = Paint()
      ..color = const Color(0x33FFFFFF)
      ..strokeWidth = 1;
    final axis = Paint()
      ..color = const Color(0xE8C9A962)
      ..strokeWidth = 1.6;
    canvas.drawRect(
      plot,
      Paint()..color = const Color(0x180C0C0C),
    );
    const yTicks = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0];
    for (final t in yTicks) {
      final y = plot.top + plot.height * (1 - t);
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), grid);
    }
    canvas.drawLine(
        Offset(plot.left, plot.top), Offset(plot.left, plot.bottom), axis);
    canvas.drawLine(
        Offset(plot.left, plot.bottom), Offset(plot.right, plot.bottom), axis);
    canvas.drawCircle(Offset(plot.left, plot.bottom), 3.2, Paint()
      ..color = const Color(0xFFE8D5A3));

    final labelStyle = const TextStyle(
      color: Color(0xFFE8D5A3),
      fontSize: 10,
      fontWeight: FontWeight.w600,
    );
    final muteStyle = const TextStyle(color: Color(0xFFC9A962), fontSize: 9);
    void drawLabel(String text, Offset at, [TextStyle? style]) {
      final tp = TextPainter(
        text: TextSpan(text: text, style: style ?? labelStyle),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, at);
    }

    canvas.save();
    canvas.translate(11, plot.center.dy);
    canvas.rotate(-math.pi / 2);
    final yTitle = TextPainter(
      text: const TextSpan(
        text: 'Healing 0–1',
        style: TextStyle(
          color: Color(0xFFE8D5A3),
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    yTitle.paint(canvas, Offset(-yTitle.width / 2, -8));
    canvas.restore();

    for (final t in yTicks) {
      final y = plot.top + plot.height * (1 - t);
      drawLabel(t.toStringAsFixed(1), Offset(18, y - 7));
    }

    final xCount = xMax <= 8 ? math.max(xMax, 2) : 6;
    for (var k = 0; k < xCount; k++) {
      final day = xCount == 1 ? 0 : ((k / (xCount - 1)) * xMax).round();
      final t = day / xMax;
      final x = plot.left + plot.width * t;
      canvas.drawLine(Offset(x, plot.top), Offset(x, plot.bottom), grid);
      canvas.drawLine(Offset(x, plot.bottom), Offset(x, plot.bottom + 5), axis);
      final date = series.isEmpty
          ? ''
          : _shortDate(series[((day / xMax) * (series.length - 1))
              .round()
              .clamp(0, series.length - 1)]['date']);
      final label = date.isEmpty ? 'Day $day' : 'Day $day\n$date';
      final tp = TextPainter(
        text: TextSpan(text: label, style: muteStyle),
        textAlign: TextAlign.center,
        textDirection: TextDirection.ltr,
      )..layout();
      var dx = x - tp.width / 2;
      if (k == 0) dx = x - 2;
      if (k == xCount - 1) dx = x - tp.width;
      tp.paint(canvas, Offset(dx, plot.bottom + 6));
    }
    drawLabel(
      'Days 0–$xMax',
      Offset(plot.center.dx - 28, size.height - 13),
      const TextStyle(
        color: Color(0xFFE8D5A3),
        fontSize: 11,
        fontWeight: FontWeight.w700,
      ),
    );

    if (series.isEmpty) return;

    final tick = Paint()
      ..color = const Color(0x40C9A962)
      ..strokeWidth = 1;
    for (var i = 0; i < series.length; i++) {
      if (series[i]['live'] == true) {
        final x = plot.left + plot.width * (i / n);
        canvas.drawLine(Offset(x, plot.top), Offset(x, plot.bottom), tick);
      }
    }

    final path = Path();
    var started = false;
    for (var i = 0; i < series.length; i++) {
      final h = series[i]['healing_mean'];
      if (h is! num) continue;
      final x = plot.left + plot.width * (i / n);
      final y = plot.top + plot.height * (1 - h.toDouble().clamp(0.0, 1.0));
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
          ..strokeWidth = 2.2
          ..strokeJoin = StrokeJoin.round,
      );
    }

    final gold = Paint()..color = const Color(0xFFE8D5A3);
    final goldDim = Paint()..color = const Color(0x59C9A962);
    final dip = Paint()..color = const Color(0xFFEF4444);
    final liveRing = Paint()
      ..color = const Color(0xFFC9A962)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6;
    for (final p in scatter) {
      final date = p['date']?.toString();
      final idx = series.indexWhere((s) => s['date'] == date);
      if (idx < 0) continue;
      final h = p['healing'];
      if (h is! num) continue;
      final pt = geom.point(idx, h.toDouble(), p['client']?.toString() ?? p['user']?.toString() ?? '');
      final kind = p['kind']?.toString() ?? '';
      if (kind == 'cycle_dip') {
        canvas.drawCircle(pt, 4.0, dip);
      } else if (kind == 'live_session') {
        canvas.drawCircle(pt, 3.2, gold);
        canvas.drawCircle(pt, 6.0, liveRing);
      } else if (kind == 'carried' || kind == 'coherence') {
        canvas.drawCircle(pt, 2.4, goldDim);
      } else {
        canvas.drawCircle(pt, 4.0, gold);
      }
    }
  }

  String _shortDate(dynamic raw) {
    final s = raw?.toString() ?? '';
    if (s.length >= 10) return '${s.substring(5, 7)}/${s.substring(8, 10)}';
    return s;
  }

  @override
  bool shouldRepaint(covariant _PracticePainter old) =>
      old.series != series || old.scatter != scatter || old.dayMax != dayMax;
}
