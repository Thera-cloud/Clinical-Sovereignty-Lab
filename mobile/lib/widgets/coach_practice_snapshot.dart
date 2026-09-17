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
  final _nameCtrl = TextEditingController();
  final List<String> _picked = [];
  double _x0 = 0;
  double _x1 = 1;
  double _y0 = 0;
  double _y1 = 1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant CoachPracticeSnapshotCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.targetCoachUsername != widget.targetCoachUsername) {
      _picked.clear();
      _nameCtrl.clear();
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
      if (_picked.isNotEmpty) {
        q['clients'] = _picked.join(',');
      }
      final uri = Uri.parse('${widget.apiBase}/api/coach/practice/snapshot')
          .replace(queryParameters: q);
      final resp = await http.get(uri, headers: widget.headers);
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _snap = Map<String, dynamic>.from(data['snapshot'] ?? {});
          _resetView(notify: false);
          _hover = null;
        });
      }
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _print() async {
    if (_printing) return;
    final sheet = kIsWeb ? openPrintWindow() : null;
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
          if (_picked.isNotEmpty) 'clients': _picked,
        }),
      );
      if (!mounted) {
        closePrintWindow(sheet);
        return;
      }
      if (resp.statusCode != 200) {
        closePrintWindow(sheet);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Print failed (${resp.statusCode})'),
          backgroundColor: Colors.red.shade800,
        ));
        return;
      }
      final data = jsonDecode(resp.body);
      final printUrl = data['print_url']?.toString() ?? '';
      if (printUrl.isEmpty) {
        closePrintWindow(sheet);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Print failed: no report URL'),
          backgroundColor: Color(0xFF8B7355),
        ));
        return;
      }
      final htmlResp = await http.get(
        Uri.parse('${widget.apiBase}$printUrl'),
        headers: widget.headers,
      );
      if (!mounted) {
        closePrintWindow(sheet);
        return;
      }
      if (htmlResp.statusCode == 200 &&
          htmlResp.body.contains('Sovereign Sanctuary')) {
        writePrintHtml(sheet, htmlResp.body);
      } else {
        closePrintWindow(sheet);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Print page failed (${htmlResp.statusCode})'),
          backgroundColor: Colors.red.shade800,
        ));
      }
    } catch (e) {
      closePrintWindow(sheet);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Print failed: $e'),
          backgroundColor: Colors.red.shade800,
        ));
      }
    } finally {
      if (mounted) setState(() => _printing = false);
    }
  }

  List<Map<String, dynamic>> _rosterMembers() {
    return List<Map<String, dynamic>>.from(_snap?['roster_members'] ?? []);
  }

  void _applyTypedNames() {
    final raw = _nameCtrl.text.trim();
    if (raw.isEmpty) {
      setState(_picked.clear);
      _load();
      return;
    }
    final tokens = raw
        .split(RegExp(r'[,;\n]+'))
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    final book = _rosterMembers();
    final matched = <String>{};
    for (final t in tokens) {
      final needle = t.toLowerCase();
      for (final m in book) {
        final un = (m['username'] ?? '').toString();
        final dn = (m['display_name'] ?? '').toString();
        if (un.toLowerCase().contains(needle) ||
            dn.toLowerCase().contains(needle)) {
          if (un.isNotEmpty) matched.add(un);
        }
      }
    }
    if (matched.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('No roster match for "$raw"'),
        backgroundColor: const Color(0xFF8B7355),
      ));
      return;
    }
    setState(() {
      _picked
        ..clear()
        ..addAll(matched);
    });
    _load();
  }

  void _toggleMember(String username) {
    setState(() {
      if (_picked.contains(username)) {
        _picked.remove(username);
      } else {
        _picked.add(username);
      }
    });
    _load();
  }

  void _resetView({bool notify = true}) {
    void apply() {
      _x0 = 0;
      _x1 = 1;
      _y0 = 0;
      _y1 = 1;
    }

    if (notify) {
      setState(apply);
    } else {
      apply();
    }
  }

  double _minSpanX(int seriesLen) =>
      math.max(7.0 / math.max(seriesLen, 7), 0.06);

  void _onWheel(PointerScrollEvent e, Size size, int seriesLen) {
    GestureBinding.instance.pointerSignalResolver.register(e, (event) {
      final ev = event as PointerScrollEvent;
      if (ev.scrollDelta.dy == 0) return;
      final geom = _ChartGeom(
        size,
        math.max(seriesLen, 1),
        x0: _x0,
        x1: _x1,
        y0: _y0,
        y1: _y1,
      );
      if (!geom.plot.contains(ev.localPosition)) return;
      final fx = ((ev.localPosition.dx - geom.plot.left) / geom.plot.width)
          .clamp(0.0, 1.0);
      final fy = ((ev.localPosition.dy - geom.plot.top) / geom.plot.height)
          .clamp(0.0, 1.0);
      final anchorX = _x0 + fx * (_x1 - _x0);
      final anchorY = _y0 + (1 - fy) * (_y1 - _y0);
      final factor = ev.scrollDelta.dy > 0 ? 1.12 : 0.88;
      final spanX =
          ((_x1 - _x0) * factor).clamp(_minSpanX(seriesLen), 1.0);
      final spanY = ((_y1 - _y0) * factor).clamp(0.08, 1.0);
      var x0 = anchorX - fx * spanX;
      var y0 = anchorY - (1 - fy) * spanY;
      if (x0 < 0) x0 = 0;
      if (x0 + spanX > 1) x0 = 1 - spanX;
      if (y0 < 0) y0 = 0;
      if (y0 + spanY > 1) y0 = 1 - spanY;
      setState(() {
        _x0 = x0;
        _x1 = x0 + spanX;
        _y0 = y0;
        _y1 = y0 + spanY;
      });
    });
  }

  void _onDateWindow(RangeValues v, int seriesLen) {
    final minSpan = _minSpanX(seriesLen);
    var a = v.start.clamp(0.0, 1.0);
    var b = v.end.clamp(0.0, 1.0);
    if (b - a < minSpan) {
      final mid = ((v.start + v.end) / 2).clamp(minSpan / 2, 1 - minSpan / 2);
      a = (mid - minSpan / 2).clamp(0.0, 1.0);
      b = (a + minSpan).clamp(0.0, 1.0);
      a = b - minSpan;
    }
    setState(() {
      _x0 = a;
      _x1 = b;
    });
  }

  String _dateAt(List<Map<String, dynamic>> series, double t) {
    if (series.isEmpty) return '';
    final i = (t * (series.length - 1)).round().clamp(0, series.length - 1);
    return _shortDate(series[i]['date']);
  }

  String _shortDate(dynamic raw) {
    final s = raw?.toString() ?? '';
    if (s.length >= 10) return '${s.substring(5, 7)}/${s.substring(8, 10)}';
    return s;
  }

  @override
  Widget build(BuildContext context) {
    final coach = (_snap?['coach'] as Map?) ?? {};
    final master = _snap?['master'] as Map?;
    final totals = (_snap?['totals'] as Map?) ?? {};
    final height = widget.compact ? 236.0 : 320.0;
    final title = widget.headlineHint ??
        '${coach['display_name'] ?? 'Practice'} · ${_days}d snapshot';
    final series = List<Map<String, dynamic>>.from(_snap?['series'] ?? []);
    final scatter = List<Map<String, dynamic>>.from(_snap?['scatter'] ?? []);

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
                onPressed: _resetView,
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
          _nameFilterBar(),
          const Padding(
            padding: EdgeInsets.only(bottom: 6),
            child: Text(
              'Wheel zooms at cursor (X+Y). Slider searches dates. Gold = roster mean   ● client   ◯ live   ● dip',
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
                  return Listener(
                    behavior: HitTestBehavior.opaque,
                    onPointerSignal: (sig) {
                      if (sig is PointerScrollEvent) {
                        _onWheel(sig, size, series.length);
                      }
                    },
                    child: GestureDetector(
                      onDoubleTap: () => _resetView(),
                      child: MouseRegion(
                        onHover: (e) {
                          final label = _hoverAt(
                              e.localPosition, size, series, scatter);
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
                                series: series,
                                scatter: scatter,
                                x0: _x0,
                                x1: _x1,
                                y0: _y0,
                                y1: _y1,
                                windowDays: _days,
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
          if (series.isNotEmpty) _dateSlider(series),
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

  Widget _nameFilterBar() {
    final book = _rosterMembers();
    final typed = _nameCtrl.text.trim().toLowerCase();
    final suggestions = typed.isEmpty
        ? book.take(8).toList()
        : book
            .where((m) {
              final un = (m['username'] ?? '').toString().toLowerCase();
              final dn = (m['display_name'] ?? '').toString().toLowerCase();
              return un.contains(typed) || dn.contains(typed);
            })
            .take(8)
            .toList();
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            height: 36,
            child: TextField(
              controller: _nameCtrl,
              style: const TextStyle(color: Color(0xFFE8D5A3), fontSize: 12),
              decoration: InputDecoration(
                isDense: true,
                hintText: 'Type a name, or several separated by commas',
                hintStyle:
                    const TextStyle(color: Color(0xFF8B7355), fontSize: 11),
                filled: true,
                fillColor: const Color(0xFF111111),
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                  borderSide: const BorderSide(color: Color(0x55C9A962)),
                ),
                suffixIcon: IconButton(
                  tooltip: 'Show named set',
                  icon: const Icon(Icons.person_search,
                      color: Color(0xFFC9A962), size: 18),
                  onPressed: _applyTypedNames,
                ),
              ),
              onSubmitted: (_) => _applyTypedNames(),
              onChanged: (_) => setState(() {}),
            ),
          ),
          if (book.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  ...suggestions.map((m) {
                    final un = (m['username'] ?? '').toString();
                    final dn = (m['display_name'] ?? un).toString();
                    final on = _picked.contains(un);
                    return FilterChip(
                      label: Text(dn,
                          style: TextStyle(
                              color: on
                                  ? const Color(0xFF050505)
                                  : const Color(0xFFE8D5A3),
                              fontSize: 10)),
                      selected: on,
                      selectedColor: const Color(0xFFC9A962),
                      backgroundColor: const Color(0xFF111111),
                      side: const BorderSide(color: Color(0x55C9A962)),
                      visualDensity: VisualDensity.compact,
                      onSelected: (_) => _toggleMember(un),
                    );
                  }),
                  if (_picked.isNotEmpty)
                    ActionChip(
                      label: const Text('All',
                          style: TextStyle(
                              color: Color(0xFFC9A962), fontSize: 10)),
                      backgroundColor: const Color(0xFF111111),
                      side: const BorderSide(color: Color(0x55C9A962)),
                      visualDensity: VisualDensity.compact,
                      onPressed: () {
                        _nameCtrl.clear();
                        setState(_picked.clear);
                        _load();
                      },
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _dateSlider(List<Map<String, dynamic>> series) {
    final start = _dateAt(series, _x0);
    final end = _dateAt(series, _x1);
    final lo = (_x0 * math.max(series.length - 1, 1)).round();
    final hi = (_x1 * math.max(series.length - 1, 1)).round();
    return Padding(
      padding: const EdgeInsets.fromLTRB(48, 2, 8, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Text('Dates',
                  style: TextStyle(color: Color(0xFFE8D5A3), fontSize: 10)),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Day $lo ($start)  →  Day $hi ($end)',
                  style: const TextStyle(color: Color(0xFFC9A962), fontSize: 10),
                ),
              ),
            ],
          ),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: const Color(0xFFC9A962),
              inactiveTrackColor: const Color(0x33C9A962),
              thumbColor: const Color(0xFFE8D5A3),
              overlayColor: const Color(0x33C9A962),
              rangeThumbShape:
                  const RoundRangeSliderThumbShape(enabledThumbRadius: 7),
              rangeTrackShape: const RoundedRectRangeSliderTrackShape(),
              overlayShape: const RoundSliderOverlayShape(overlayRadius: 14),
            ),
            child: RangeSlider(
              values: RangeValues(_x0.clamp(0.0, 1.0), _x1.clamp(0.0, 1.0)),
              min: 0,
              max: 1,
              divisions: math.max(series.length - 1, 1),
              onChanged: (v) => _onDateWindow(v, series.length),
            ),
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
    final geom = _ChartGeom(
      size,
      series.length,
      x0: _x0,
      x1: _x1,
      y0: _y0,
      y1: _y1,
    );
    if (!geom.plot.contains(pos)) {
      return _meanAt(pos, series, geom);
    }
    String? best;
    var bestD = 16.0;
    for (final p in scatter) {
      final date = p['date']?.toString();
      final idx = series.indexWhere((s) => s['date'] == date);
      if (idx < 0) continue;
      final h = p['healing'];
      if (h is! num) continue;
      if (!geom.inX(idx)) continue;
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
    return best ?? _meanAt(pos, series, geom);
  }

  String? _meanAt(
      Offset pos, List<Map<String, dynamic>> series, _ChartGeom geom) {
    if (series.isEmpty) return null;
    final wx = geom.screenToWorldX(pos.dx);
    final idx = (wx * (series.length - 1)).round().clamp(0, series.length - 1);
    final h = series[idx]['healing_mean'];
    if (h is! num) return null;
    return 'Roster mean · ${series[idx]['date']} · ${h.toStringAsFixed(3)}';
  }
}

class _ChartGeom {
  final Size size;
  final int count;
  final double x0;
  final double x1;
  final double y0;
  final double y1;
  static const padL = 56.0;
  static const padR = 16.0;
  static const padT = 14.0;
  static const padB = 48.0;

  _ChartGeom(
    this.size,
    this.count, {
    required this.x0,
    required this.x1,
    required this.y0,
    required this.y1,
  });

  Rect get plot => Rect.fromLTWH(
        padL,
        padT,
        math.max(1, size.width - padL - padR),
        math.max(1, size.height - padT - padB),
      );

  double get spanX => math.max(x1 - x0, 1e-6);
  double get spanY => math.max(y1 - y0, 1e-6);

  double worldX(int idx) => count <= 1 ? 0.0 : idx / (count - 1);

  bool inX(int idx) {
    final wx = worldX(idx);
    return wx >= x0 - 0.002 && wx <= x1 + 0.002;
  }

  Offset mapped(int idx, double healing) {
    final sx = plot.left + plot.width * ((worldX(idx) - x0) / spanX);
    final sy = plot.top +
        plot.height * (1 - ((healing.clamp(0.0, 1.0) - y0) / spanY));
    return Offset(sx, sy);
  }

  Offset point(int idx, double healing, String jitterKey) {
    final base = mapped(idx, healing);
    final h = jitterKey.hashCode;
    return Offset(
      base.dx + ((h % 13) - 6).toDouble(),
      base.dy + (((h ~/ 13) % 15) - 7).toDouble(),
    );
  }

  double screenToWorldX(double dx) =>
      x0 + ((dx - plot.left) / plot.width).clamp(0.0, 1.0) * spanX;
}

class _PracticePainter extends CustomPainter {
  final List<Map<String, dynamic>> series;
  final List<Map<String, dynamic>> scatter;
  final double x0;
  final double x1;
  final double y0;
  final double y1;
  final int windowDays;

  _PracticePainter({
    required this.series,
    required this.scatter,
    required this.x0,
    required this.x1,
    required this.y0,
    required this.y1,
    required this.windowDays,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final count = math.max(series.length, 2);
    final geom = _ChartGeom(
      size,
      series.isEmpty ? count : series.length,
      x0: x0,
      x1: x1,
      y0: y0,
      y1: y1,
    );
    final plot = geom.plot;
    final nDays = math.max(series.isEmpty ? windowDays : series.length, 1);
    final dayLo = (x0 * (nDays - 1)).round();
    final dayHi = (x1 * (nDays - 1)).round();

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

    final yTicks = <double>[];
    for (var i = 0; i < 6; i++) {
      yTicks.add(y0 + (y1 - y0) * (i / 5));
    }
    for (final t in yTicks) {
      final y = plot.top + plot.height * (1 - ((t - y0) / geom.spanY));
      canvas.drawLine(Offset(plot.left, y), Offset(plot.right, y), grid);
    }
    canvas.drawLine(
        Offset(plot.left, plot.top), Offset(plot.left, plot.bottom), axis);
    canvas.drawLine(
        Offset(plot.left, plot.bottom), Offset(plot.right, plot.bottom), axis);
    if (x0 <= 0.001 && y0 <= 0.001) {
      canvas.drawCircle(Offset(plot.left, plot.bottom), 3.2,
          Paint()..color = const Color(0xFFE8D5A3));
    }

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
      final y = plot.top + plot.height * (1 - ((t - y0) / geom.spanY));
      drawLabel(t.toStringAsFixed(2), Offset(14, y - 7));
    }

    const xCount = 6;
    for (var k = 0; k < xCount; k++) {
      final t = k / (xCount - 1);
      final wx = x0 + t * (x1 - x0);
      final x = plot.left + plot.width * t;
      canvas.drawLine(Offset(x, plot.top), Offset(x, plot.bottom), grid);
      canvas.drawLine(Offset(x, plot.bottom), Offset(x, plot.bottom + 5), axis);
      final day = (wx * (nDays - 1)).round();
      final date = series.isEmpty
          ? ''
          : _shortDate(series[(wx * (series.length - 1))
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
      'Days $dayLo–$dayHi',
      Offset(plot.center.dx - 32, size.height - 13),
      const TextStyle(
        color: Color(0xFFE8D5A3),
        fontSize: 11,
        fontWeight: FontWeight.w700,
      ),
    );

    if (series.isEmpty) return;

    canvas.save();
    canvas.clipRect(plot);

    final tick = Paint()
      ..color = const Color(0x40C9A962)
      ..strokeWidth = 1;
    for (var i = 0; i < series.length; i++) {
      if (series[i]['live'] == true && geom.inX(i)) {
        final p = geom.mapped(i, y0);
        canvas.drawLine(Offset(p.dx, plot.top), Offset(p.dx, plot.bottom), tick);
      }
    }

    final path = Path();
    var started = false;
    for (var i = 0; i < series.length; i++) {
      final h = series[i]['healing_mean'];
      if (h is! num) continue;
      final pt = geom.mapped(i, h.toDouble());
      if (!started) {
        path.moveTo(pt.dx, pt.dy);
        started = true;
      } else {
        path.lineTo(pt.dx, pt.dy);
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
      if (idx < 0 || !geom.inX(idx)) continue;
      final h = p['healing'];
      if (h is! num) continue;
      final pt = geom.point(
          idx, h.toDouble(), p['client']?.toString() ?? p['user']?.toString() ?? '');
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
    canvas.restore();
  }

  String _shortDate(dynamic raw) {
    final s = raw?.toString() ?? '';
    if (s.length >= 10) return '${s.substring(5, 7)}/${s.substring(8, 10)}';
    return s;
  }

  @override
  bool shouldRepaint(covariant _PracticePainter old) =>
      old.series != series ||
      old.scatter != scatter ||
      old.x0 != x0 ||
      old.x1 != x1 ||
      old.y0 != y0 ||
      old.y1 != y1 ||
      old.windowDays != windowDays;
}
