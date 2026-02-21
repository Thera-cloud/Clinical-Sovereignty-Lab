import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'dart:convert';
import 'dart:async';
import 'dart:math';
import '../config/app_config.dart';
import 'secure_search_screen.dart';

class _Design {
  static const bgVoid = Color(0xFF050505);
  static const bgChamber = Color(0xFF0A0A0A);
  static const bgElevated = Color(0xFF111111);
  static const gold = Color(0xFFC9A962);
  static const goldBright = Color(0xFFE8D5A3);
  static const goldDim = Color(0xFF8B7355);
  static const cyan = Color(0xFF4ECDC4);
  static const purple = Color(0xFF9D4EDD);
  static const green = Color(0xFF00FF88);
  static const red = Color(0xFFEF4444);
  static const textPrimary = Color(0xFFFFFFFF);
  static const textSecondary = Color(0xFF888888);
  static const textMuted = Color(0xFF555555);
  static const driftGray = Color(0xFF333333);
}

class NevedalReportsScreen extends StatefulWidget {
  final Map<String, dynamic> profile;

  const NevedalReportsScreen({super.key, required this.profile});

  @override
  State<NevedalReportsScreen> createState() => _NevedalReportsScreenState();
}

class _NevedalReportsScreenState extends State<NevedalReportsScreen> {
  WebSocketChannel? _socket;
  StreamSubscription? _socketSub;

  bool _authenticating = true;
  bool _authenticated = false;
  bool _loading = true;
  String? _error;
  Map<String, dynamic>? _report;

  String _selectedRange = 'All';
  bool _showCEE = true;

  static const _ranges = ['This Week', 'Last Week', 'This Month', 'Last Month', 'YTD', 'All'];

  @override
  void initState() {
    super.initState();
    _connectAndLoad();
  }

  Future<void> _connectAndLoad() async {
    try {
      _socket = WebSocketChannel.connect(Uri.parse(AppConfig.wsUrl));
      _socketSub = _socket!.stream.listen(
        (msg) { try { _handleMessage(jsonDecode(msg)); } catch (_) {} },
        onError: (_) { if (mounted) setState(() { _error = 'Connection lost.'; _authenticating = false; _loading = false; }); },
      );

      final hwId = (widget.profile['hardware_id'] ?? '').toString();
      if (hwId.isEmpty) { setState(() { _error = 'Missing identity.'; _authenticating = false; _loading = false; }); return; }

      const storage = FlutterSecureStorage(aOptions: AndroidOptions(encryptedSharedPreferences: true));
      final token = await storage.read(key: 'session_token');
      if (token == null || token.isEmpty) { setState(() { _error = 'Session expired.'; _authenticating = false; _loading = false; }); return; }

      _socket!.sink.add(jsonEncode({'type': 'auth', 'hardware_id': hwId, 'token': token}));
    } catch (e) {
      if (mounted) setState(() { _error = 'Failed to connect: $e'; _authenticating = false; _loading = false; });
    }
  }

  void _handleMessage(Map<String, dynamic> data) {
    if (!mounted) return;
    final type = data['type']?.toString() ?? '';

    switch (type) {
      case 'auth_success':
      case 'login_success':
        setState(() { _authenticated = true; _authenticating = false; });
        _requestReport();
        break;

      case 'auth_failed':
      case 'login_failed':
        setState(() { _authenticated = false; _authenticating = false; _loading = false;
          _error = data['message']?.toString() ?? 'Authentication failed.'; });
        break;

      case 'coherence_report':
        setState(() { _report = data; _loading = false; _error = null; });
        break;

      case 'coherence_report_error':
        setState(() { _error = data['error']?.toString() ?? 'Failed to load report'; _loading = false; });
        break;
    }
  }

  void _requestReport() {
    final dates = _computeDateRange(_selectedRange);
    final msg = <String, dynamic>{'type': 'get_coherence_report'};
    if (dates != null) {
      msg['date_from'] = dates['from'];
      msg['date_to'] = dates['to'];
    }
    setState(() { _loading = true; });
    _socket?.sink.add(jsonEncode(msg));
  }

  Map<String, String>? _computeDateRange(String range) {
    final now = DateTime.now();
    switch (range) {
      case 'This Week':
        final monday = now.subtract(Duration(days: now.weekday - 1));
        return {'from': _isoDate(monday), 'to': _isoDate(now)};
      case 'Last Week':
        final monday = now.subtract(Duration(days: now.weekday + 6));
        final sunday = monday.add(const Duration(days: 6));
        return {'from': _isoDate(monday), 'to': _isoDate(sunday)};
      case 'This Month':
        return {'from': '${now.year}-${now.month.toString().padLeft(2, '0')}-01', 'to': _isoDate(now)};
      case 'Last Month':
        final prev = DateTime(now.year, now.month - 1, 1);
        final lastDay = DateTime(now.year, now.month, 0);
        return {'from': _isoDate(prev), 'to': _isoDate(lastDay)};
      case 'YTD':
        return {'from': '${now.year}-01-01', 'to': _isoDate(now)};
      default:
        return null;
    }
  }

  String _isoDate(DateTime dt) => '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';

  @override
  void dispose() {
    _socketSub?.cancel();
    _socket?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Design.bgVoid,
      appBar: AppBar(
        backgroundColor: _Design.bgChamber, elevation: 0,
        title: const Text('Coherence Dashboard',
            style: TextStyle(color: _Design.textPrimary, fontSize: 20, fontWeight: FontWeight.bold)),
        iconTheme: const IconThemeData(color: _Design.gold),
      ),
      body: _authenticating || (_loading && _report == null)
          ? _buildLoading()
          : _error != null && _report == null
              ? _buildError()
              : _report != null
                  ? _buildDashboard()
                  : _buildEmpty(),
    );
  }

  Widget _buildLoading() {
    return const Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      CircularProgressIndicator(valueColor: AlwaysStoppedAnimation<Color>(_Design.gold)),
      SizedBox(height: 16),
      Text('Loading your coherence data...', style: TextStyle(color: _Design.textSecondary)),
    ]));
  }

  Widget _buildError() {
    return Center(child: Padding(padding: const EdgeInsets.all(32), child: Column(
      mainAxisAlignment: MainAxisAlignment.center, children: [
        const Icon(Icons.error_outline, color: _Design.red, size: 48),
        const SizedBox(height: 16),
        Text(_error!, textAlign: TextAlign.center, style: const TextStyle(color: _Design.textSecondary, fontSize: 16)),
        const SizedBox(height: 24),
        ElevatedButton.icon(onPressed: () => Navigator.pop(context),
          icon: const Icon(Icons.arrow_back), label: const Text('Go Back'),
          style: ElevatedButton.styleFrom(backgroundColor: _Design.gold, foregroundColor: _Design.bgVoid)),
      ],
    )));
  }

  Widget _buildEmpty() {
    return const Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
      Icon(Icons.assessment, color: _Design.goldDim, size: 64),
      SizedBox(height: 16),
      Text('No coherence data yet', style: TextStyle(color: _Design.textPrimary, fontSize: 18, fontWeight: FontWeight.bold)),
      SizedBox(height: 8),
      Padding(padding: EdgeInsets.symmetric(horizontal: 48), child: Text(
        'Chat with Little Nate to start building your coherence profile.',
        textAlign: TextAlign.center, style: TextStyle(color: _Design.textSecondary, fontSize: 14))),
    ]));
  }

  // =========================================================================
  // DASHBOARD
  // =========================================================================
  Widget _buildDashboard() {
    final current = _report!['current'] as Map<String, dynamic>? ?? {};
    final trends = _report!['trends'] as Map<String, dynamic>? ?? {};
    final history = _report!['history'] as List? ?? [];
    final ceeExperiences = _report!['cee_experiences'] as List? ?? [];
    final driftPeriods = _report!['drift_periods'] as List? ?? [];
    final replyTherapy = _report!['reply_therapy'] as Map<String, dynamic>? ?? {};
    final moodHistory = _report!['mood_history'] as List? ?? [];
    final ceeTotal = _report!['cee_total'] as int? ?? 0;

    final cEmo = (current['C_emo'] as num?)?.toDouble() ?? 0;
    final gap = (current['GAP'] as num?)?.toDouble() ?? 0;
    final quantum = (current['Quantum'] as num?)?.toDouble() ?? 0;
    final sessionCount = current['session_count'] as int? ?? 0;

    final cEmoTrends = trends['C_emo'] as Map<String, dynamic>? ?? {};
    final gapTrends = trends['GAP'] as Map<String, dynamic>? ?? {};
    final quantumTrends = trends['Quantum'] as Map<String, dynamic>? ?? {};

    final cEmoVals = (cEmoTrends['values'] as List?)?.map((v) => (v as num).toDouble()).toList() ?? [];
    final gapVals = (gapTrends['values'] as List?)?.map((v) => (v as num).toDouble()).toList() ?? [];
    final quantumVals = (quantumTrends['values'] as List?)?.map((v) => (v as num).toDouble()).toList() ?? [];
    final timestamps = (cEmoTrends['timestamps'] as List?)?.map((t) => t.toString()).toList() ?? [];

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // Current snapshot
        _sectionLabel('CURRENT STATE'),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: _metricCard('C_emo', cEmo, _Design.cyan)),
          const SizedBox(width: 8),
          Expanded(child: _metricCard('GAP', gap, _Design.gold)),
          const SizedBox(width: 8),
          Expanded(child: _metricCard('Quantum', quantum, _Design.purple)),
        ]),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: _infoCard('Sessions', '$sessionCount', _Design.goldDim)),
          const SizedBox(width: 8),
          Expanded(child: _infoCard('CEE Moments', '$ceeTotal', _Design.green)),
          const SizedBox(width: 8),
          Expanded(child: _infoCard('Mood', _moodEmoji(current['mood']?.toString() ?? 'neutral'), _Design.goldDim)),
        ]),
        const SizedBox(height: 20),

        // Date range selector
        _sectionLabel('DATE RANGE'),
        const SizedBox(height: 8),
        SizedBox(
          height: 36,
          child: ListView(
            scrollDirection: Axis.horizontal,
            children: _ranges.map((r) => Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(r, style: TextStyle(
                  color: _selectedRange == r ? _Design.bgVoid : _Design.textSecondary,
                  fontSize: 12, fontWeight: FontWeight.w600)),
                selected: _selectedRange == r,
                selectedColor: _Design.gold,
                backgroundColor: _Design.bgElevated,
                side: BorderSide(color: _selectedRange == r ? _Design.gold : _Design.goldDim.withOpacity(0.3)),
                onSelected: (selected) {
                  if (selected) {
                    setState(() { _selectedRange = r; });
                    _requestReport();
                  }
                },
              ),
            )).toList(),
          ),
        ),
        const SizedBox(height: 20),

        // Multi-line chart
        if (cEmoVals.length >= 2) ...[
          _sectionLabel('COHERENCE METRICS'),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: _Design.bgElevated, borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _Design.goldDim.withOpacity(0.2))),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              LayoutBuilder(builder: (ctx, constraints) {
                final chartW = constraints.maxWidth;
                const chartH = 180.0;
                return GestureDetector(
                  onTapUp: _showCEE && ceeExperiences.isNotEmpty
                    ? (details) => _onChartCEETap(details.localPosition, chartW, chartH, ceeExperiences, timestamps, cEmoVals.length)
                    : null,
                  child: SizedBox(
                    height: chartH,
                    child: CustomPaint(
                      size: Size(chartW, chartH),
                      painter: _MultiLinePainter(
                        cEmoVals: cEmoVals,
                        gapVals: gapVals,
                        quantumVals: quantumVals,
                        ceeExperiences: _showCEE ? ceeExperiences : [],
                        driftPeriods: driftPeriods,
                        timestamps: timestamps,
                      ),
                    ),
                  ),
                );
              }),
              const SizedBox(height: 12),
              // Legend
              Row(children: [
                _legendDot(_Design.cyan, 'C_emo'),
                const SizedBox(width: 16),
                _legendDot(_Design.gold, 'GAP'),
                const SizedBox(width: 16),
                _legendDot(_Design.purple, 'Quantum'),
                if (driftPeriods.isNotEmpty) ...[
                  const SizedBox(width: 16),
                  _legendDot(_Design.driftGray, 'Away'),
                ],
              ]),
              const SizedBox(height: 12),
              // CEE toggle
              GestureDetector(
                onTap: () { setState(() { _showCEE = !_showCEE; }); },
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(
                    color: _showCEE ? _Design.green.withOpacity(0.15) : _Design.bgChamber,
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: _showCEE ? _Design.green : _Design.textMuted)),
                  child: Row(mainAxisSize: MainAxisSize.min, children: [
                    Icon(Icons.flash_on, color: _showCEE ? _Design.green : _Design.textMuted, size: 16),
                    const SizedBox(width: 6),
                    Text('CEE Moments', style: TextStyle(
                      color: _showCEE ? _Design.green : _Design.textMuted,
                      fontSize: 13, fontWeight: FontWeight.w600)),
                    Text(' (${ceeExperiences.length})', style: TextStyle(
                      color: _showCEE ? _Design.green.withOpacity(0.7) : _Design.textMuted, fontSize: 12)),
                  ]),
                ),
              ),
            ]),
          ),
          const SizedBox(height: 20),
        ],

        // CEE Experiences list
        if (ceeExperiences.isNotEmpty && _showCEE) ...[
          _sectionLabel('CORRECTIVE EMOTIONAL EXPERIENCES'),
          const SizedBox(height: 8),
          ...ceeExperiences.reversed.take(10).map((ce) => _buildCEECard(Map<String, dynamic>.from(ce as Map))),
          const SizedBox(height: 20),
        ],

        // Reply Therapy progress
        if ((replyTherapy['themes'] as Map?)?.isNotEmpty == true) ...[
          _sectionLabel('REPLY THERAPY PROGRESS (3+3+3)'),
          const SizedBox(height: 8),
          _buildReplyTherapyCard(replyTherapy),
          const SizedBox(height: 20),
        ],

        // Drift periods
        if (driftPeriods.isNotEmpty) ...[
          _sectionLabel('DRIFT PERIODS'),
          const SizedBox(height: 8),
          ...driftPeriods.map((dp) => _buildDriftCard(Map<String, dynamic>.from(dp as Map))),
          const SizedBox(height: 20),
        ],

        // Mood history
        if (moodHistory.isNotEmpty) ...[
          _sectionLabel('MOOD HISTORY'),
          const SizedBox(height: 8),
          _moodHistoryCard(moodHistory),
          const SizedBox(height: 32),
        ],
      ]),
    );
  }

  // =========================================================================
  // WIDGETS
  // =========================================================================

  Widget _sectionLabel(String text) {
    return Text(text, style: const TextStyle(
      color: _Design.goldDim, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 1.5));
  }

  Widget _legendDot(Color color, String label) {
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Container(width: 10, height: 10, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 11)),
    ]);
  }

  Widget _metricCard(String label, double value, Color color) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _Design.bgElevated, borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withOpacity(0.3))),
      child: Column(children: [
        Text(value.toStringAsFixed(2),
          style: TextStyle(color: color, fontSize: 28, fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 12)),
      ]),
    );
  }

  void _onChartCEETap(Offset tapPos, double totalWidth, double totalHeight,
      List<dynamic> cees, List<String> ts, int maxPoints) {
    if (maxPoints < 2 || ts.isEmpty) return;
    const chartLeft = 30.0;
    final chartWidth = totalWidth - chartLeft - 8;
    const chartTop = 8.0;
    final chartHeight = totalHeight - chartTop - 20;

    Map<String, dynamic>? closest;
    double closestDist = 24.0; // tap radius threshold

    for (final ce in cees) {
      if (ce is! Map) continue;
      final ceTs = ce['timestamp']?.toString() ?? '';
      final ceDate = ceTs.length >= 10 ? ceTs.substring(0, 10) : '';
      final cemoAfter = (ce['c_emo_after'] as num?)?.toDouble() ?? 0.75;
      int idx = 0;
      double best = double.infinity;
      for (var i = 0; i < ts.length; i++) {
        final tDate = ts[i].length >= 10 ? ts[i].substring(0, 10) : '';
        final dist = (tDate.compareTo(ceDate)).abs().toDouble();
        if (dist < best) { best = dist; idx = i; }
      }
      final x = chartLeft + (idx / (maxPoints - 1)) * chartWidth;
      final y = chartTop + chartHeight * (1 - cemoAfter.clamp(0, 1));
      final d = (tapPos - Offset(x, y)).distance;
      if (d < closestDist) {
        closestDist = d;
        closest = Map<String, dynamic>.from(ce);
      }
    }

    if (closest != null) _showCEEBottomSheet(closest);
  }

  void _showCEEBottomSheet(Map<String, dynamic> ce) {
    final ts = ce['timestamp']?.toString() ?? '';
    final before = (ce['c_emo_before'] as num?)?.toDouble() ?? 0;
    final after = (ce['c_emo_after'] as num?)?.toDouble() ?? 0;
    final delta = (ce['delta'] as num?)?.toDouble() ?? 0;
    final moodBefore = ce['mood_before']?.toString() ?? '';
    final moodAfter = ce['mood_after']?.toString() ?? '';

    showModalBottomSheet(
      context: context,
      backgroundColor: _Design.bgChamber,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => Padding(
        padding: const EdgeInsets.all(20),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Center(child: Container(width: 40, height: 4,
            decoration: BoxDecoration(color: _Design.textMuted, borderRadius: BorderRadius.circular(2)))),
          const SizedBox(height: 16),
          Row(children: [
            Container(width: 36, height: 36,
              decoration: BoxDecoration(color: _Design.green.withOpacity(0.15), borderRadius: BorderRadius.circular(10)),
              child: const Icon(Icons.flash_on, color: _Design.green, size: 20)),
            const SizedBox(width: 12),
            const Expanded(child: Text('Corrective Emotional Experience',
              style: TextStyle(color: _Design.gold, fontSize: 16, fontWeight: FontWeight.bold))),
          ]),
          const SizedBox(height: 16),
          Text(_formatTs(ts), style: const TextStyle(color: _Design.textMuted, fontSize: 12)),
          const SizedBox(height: 8),
          Text('C_emo: ${before.toStringAsFixed(3)} \u2192 ${after.toStringAsFixed(3)}',
            style: const TextStyle(color: _Design.green, fontSize: 15, fontWeight: FontWeight.w600)),
          Text('\u0394 +${delta.toStringAsFixed(3)}',
            style: const TextStyle(color: _Design.green, fontSize: 13)),
          if (moodBefore.isNotEmpty || moodAfter.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('Mood: ${_moodEmoji(moodBefore)} \u2192 ${_moodEmoji(moodAfter)}',
              style: const TextStyle(color: _Design.textSecondary, fontSize: 14)),
          ],
          const SizedBox(height: 20),
          Row(children: [
            Expanded(child: ElevatedButton.icon(
              icon: const Icon(Icons.search, size: 16),
              label: const Text('Search Conversations'),
              style: ElevatedButton.styleFrom(
                backgroundColor: _Design.cyan.withOpacity(0.15),
                foregroundColor: _Design.cyan),
              onPressed: () {
                Navigator.pop(context);
                Navigator.push(context, MaterialPageRoute(
                  builder: (_) => SecureSearchScreen(
                    profile: widget.profile,
                    prefillQuery: ts.length >= 10 ? ts.substring(0, 10) : null,
                  ),
                ));
              },
            )),
            const SizedBox(width: 10),
            Expanded(child: ElevatedButton.icon(
              icon: const Icon(Icons.send, size: 16),
              label: const Text('Push to Nate'),
              style: ElevatedButton.styleFrom(
                backgroundColor: _Design.green.withOpacity(0.15),
                foregroundColor: _Design.green),
              onPressed: () {
                _socket?.sink.add(jsonEncode({
                  'type': 'memory_push_to_nate',
                  'entries': [{'timestamp': ts, 'user_preview': 'CEE moment at $ts'}],
                }));
                Navigator.pop(context);
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Pushed to Little Nate'), backgroundColor: _Design.green));
              },
            )),
          ]),
          const SizedBox(height: 12),
        ]),
      ),
    );
  }

  Widget _infoCard(String label, String value, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
      decoration: BoxDecoration(
        color: _Design.bgElevated, borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.goldDim.withOpacity(0.15))),
      child: Column(children: [
        Text(value, style: TextStyle(color: color, fontSize: 20, fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 11), textAlign: TextAlign.center),
      ]),
    );
  }

  Widget _buildCEECard(Map<String, dynamic> ce) {
    final ts = ce['timestamp']?.toString() ?? '';
    final before = (ce['c_emo_before'] as num?)?.toDouble() ?? 0;
    final after = (ce['c_emo_after'] as num?)?.toDouble() ?? 0;
    final delta = (ce['delta'] as num?)?.toDouble() ?? 0;
    final moodBefore = ce['mood_before']?.toString() ?? '';
    final moodAfter = ce['mood_after']?.toString() ?? '';

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _Design.bgElevated, borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _Design.green.withOpacity(0.25))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(width: 32, height: 32,
            decoration: BoxDecoration(color: _Design.green.withOpacity(0.15), borderRadius: BorderRadius.circular(8)),
            child: const Icon(Icons.flash_on, color: _Design.green, size: 18)),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(_formatTs(ts), style: const TextStyle(color: _Design.textMuted, fontSize: 11)),
            Text('C_emo ${before.toStringAsFixed(3)} \u2192 ${after.toStringAsFixed(3)} (+${delta.toStringAsFixed(3)})',
              style: const TextStyle(color: _Design.green, fontSize: 13, fontWeight: FontWeight.w600)),
          ])),
        ]),
        if (moodBefore.isNotEmpty || moodAfter.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6, left: 42),
            child: Text('${_moodEmoji(moodBefore)} \u2192 ${_moodEmoji(moodAfter)}',
              style: const TextStyle(color: _Design.textSecondary, fontSize: 13)),
          ),
        const SizedBox(height: 8),
        Row(children: [
          const SizedBox(width: 42),
          _miniButton('Search Conversations', Icons.search, () {
            Navigator.push(context, MaterialPageRoute(
              builder: (_) => SecureSearchScreen(
                profile: widget.profile,
                prefillQuery: ts.length >= 10 ? ts.substring(0, 10) : null,
              ),
            ));
          }),
          const SizedBox(width: 8),
          _miniButton('Push to Nate', Icons.send, () {
            _socket?.sink.add(jsonEncode({
              'type': 'memory_push_to_nate',
              'entries': [{'timestamp': ts, 'user_preview': 'CEE moment at $ts'}],
            }));
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Pushed to Little Nate'), backgroundColor: _Design.green));
          }),
        ]),
      ]),
    );
  }

  Widget _miniButton(String label, IconData icon, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: _Design.bgChamber, borderRadius: BorderRadius.circular(6),
          border: Border.all(color: _Design.goldDim.withOpacity(0.3))),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, color: _Design.goldDim, size: 14),
          const SizedBox(width: 4),
          Text(label, style: const TextStyle(color: _Design.textSecondary, fontSize: 11)),
        ]),
      ),
    );
  }

  Widget _buildReplyTherapyCard(Map<String, dynamic> rt) {
    final themes = rt['themes'] as Map<String, dynamic>? ?? {};
    final completedCount = rt['completed_count'] as int? ?? 0;
    final activeTheme = rt['active_theme']?.toString();

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _Design.bgElevated, borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.purple.withOpacity(0.3))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (activeTheme != null)
          Container(
            margin: const EdgeInsets.only(bottom: 10),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: _Design.purple.withOpacity(0.15), borderRadius: BorderRadius.circular(8)),
            child: Row(children: [
              const Icon(Icons.auto_awesome, color: _Design.purple, size: 16),
              const SizedBox(width: 6),
              Text('Active: ${activeTheme.replaceAll('_', ' ').toUpperCase()}',
                style: const TextStyle(color: _Design.purple, fontSize: 12, fontWeight: FontWeight.w700)),
            ]),
          ),
        if (completedCount > 0)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text('$completedCount completed Reply Therapy cycles',
              style: const TextStyle(color: _Design.green, fontSize: 13, fontWeight: FontWeight.w600)),
          ),
        ...themes.entries.map((e) {
          final theme = e.key;
          final data = e.value as Map<String, dynamic>? ?? {};
          final m = data['mismatch'] as int? ?? 0;
          final r = data['reconsolidation'] as int? ?? 0;
          final ev = data['evocative'] as int? ?? 0;
          final met = data['threshold_met'] == true;
          final done = data['reply_completed'] == true;
          return Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(children: [
              Expanded(
                flex: 3,
                child: Text(theme.replaceAll('_', ' '),
                  style: TextStyle(color: met ? _Design.green : _Design.textPrimary, fontSize: 13)),
              ),
              _countDot(m, 3, _Design.cyan, 'M'),
              const SizedBox(width: 6),
              _countDot(r, 3, _Design.gold, 'R'),
              const SizedBox(width: 6),
              _countDot(ev, 3, _Design.purple, 'E'),
              const SizedBox(width: 8),
              if (done)
                const Icon(Icons.check_circle, color: _Design.green, size: 18)
              else if (met)
                const Icon(Icons.auto_awesome, color: _Design.purple, size: 18),
            ]),
          );
        }),
      ]),
    );
  }

  Widget _countDot(int current, int target, Color color, String label) {
    final filled = current >= target;
    return Container(
      width: 28, height: 28,
      decoration: BoxDecoration(
        color: filled ? color.withOpacity(0.2) : Colors.transparent,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: filled ? color : _Design.textMuted)),
      child: Center(child: Text('$current', style: TextStyle(
        color: filled ? color : _Design.textMuted, fontSize: 11, fontWeight: FontWeight.bold))),
    );
  }

  Widget _buildDriftCard(Map<String, dynamic> dp) {
    final leftAt = dp['left_at']?.toString() ?? '';
    final returnedAt = dp['returned_at']?.toString() ?? '';
    final gapDays = dp['gap_days'] as int? ?? 0;
    final explored = dp['explored'] == true;

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _Design.bgElevated, borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _Design.driftGray.withOpacity(0.5))),
      child: Row(children: [
        Container(width: 32, height: 32,
          decoration: BoxDecoration(color: _Design.driftGray.withOpacity(0.3), borderRadius: BorderRadius.circular(8)),
          child: const Icon(Icons.flight_takeoff, color: _Design.textMuted, size: 18)),
        const SizedBox(width: 10),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('$gapDays days away', style: const TextStyle(color: _Design.textPrimary, fontSize: 14, fontWeight: FontWeight.w600)),
          Text('${_formatTs(leftAt)} \u2192 ${_formatTs(returnedAt)}',
            style: const TextStyle(color: _Design.textMuted, fontSize: 11)),
        ])),
        if (explored)
          const Icon(Icons.check_circle_outline, color: _Design.green, size: 18)
        else
          const Icon(Icons.explore, color: _Design.goldDim, size: 18),
      ]),
    );
  }

  Widget _moodHistoryCard(List moodHistory) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: _Design.bgElevated, borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Design.goldDim.withOpacity(0.15))),
      child: Wrap(spacing: 6, runSpacing: 6,
        children: moodHistory.reversed.take(14).map((m) {
          final entry = Map<String, dynamic>.from(m as Map);
          final mood = entry['mood']?.toString() ?? 'neutral';
          final date = entry['date']?.toString() ?? '';
          return Tooltip(message: '$date: $mood',
            child: Container(
              width: 38, height: 38,
              decoration: BoxDecoration(
                color: _moodColor(mood).withOpacity(0.15), borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _moodColor(mood).withOpacity(0.3))),
              child: Center(child: Text(_moodEmoji(mood), style: const TextStyle(fontSize: 16))),
            ),
          );
        }).toList(),
      ),
    );
  }

  // =========================================================================
  // HELPERS
  // =========================================================================

  String _moodEmoji(String mood) {
    switch (mood.toLowerCase()) {
      case 'happy': return '\u{1F60A}';
      case 'sad': return '\u{1F614}';
      case 'anxious': return '\u{1F630}';
      case 'angry': return '\u{1F624}';
      case 'calm': return '\u{1F60C}';
      default: return '\u{1F610}';
    }
  }

  Color _moodColor(String mood) {
    switch (mood.toLowerCase()) {
      case 'happy': return _Design.green;
      case 'sad': return _Design.purple;
      case 'anxious': return _Design.red;
      case 'angry': return _Design.red;
      case 'calm': return _Design.cyan;
      default: return _Design.goldDim;
    }
  }

  String _formatTs(String raw) {
    try {
      final dt = DateTime.parse(raw);
      final months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      final h = dt.hour > 12 ? dt.hour - 12 : (dt.hour == 0 ? 12 : dt.hour);
      final ap = dt.hour >= 12 ? 'pm' : 'am';
      return '${months[dt.month - 1]} ${dt.day} at $h:${dt.minute.toString().padLeft(2, '0')} $ap';
    } catch (_) { return raw; }
  }
}

// =============================================================================
// MULTI-LINE CHART PAINTER
// =============================================================================
class _MultiLinePainter extends CustomPainter {
  final List<double> cEmoVals;
  final List<double> gapVals;
  final List<double> quantumVals;
  final List<dynamic> ceeExperiences;
  final List<dynamic> driftPeriods;
  final List<String> timestamps;

  _MultiLinePainter({
    required this.cEmoVals,
    required this.gapVals,
    required this.quantumVals,
    required this.ceeExperiences,
    required this.driftPeriods,
    required this.timestamps,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final maxPoints = cEmoVals.length;
    if (maxPoints < 2) return;

    final chartLeft = 30.0;
    final chartWidth = size.width - chartLeft - 8;
    final chartTop = 8.0;
    final chartHeight = size.height - chartTop - 20;

    // Y-axis labels
    final axisPaint = Paint()..color = const Color(0xFF333333)..strokeWidth = 0.5;
    final textStyle = const TextStyle(color: Color(0xFF555555), fontSize: 9);
    for (var i = 0; i <= 4; i++) {
      final y = chartTop + (chartHeight * (1 - i / 4));
      canvas.drawLine(Offset(chartLeft, y), Offset(size.width - 8, y), axisPaint);
      final tp = TextPainter(text: TextSpan(text: (i * 0.25).toStringAsFixed(2), style: textStyle),
        textDirection: TextDirection.ltr)..layout();
      tp.paint(canvas, Offset(0, y - 5));
    }

    // Drift period bands
    if (timestamps.isNotEmpty) {
      for (final dp in driftPeriods) {
        if (dp is! Map) continue;
        final leftAt = dp['left_at']?.toString() ?? '';
        final returnedAt = dp['returned_at']?.toString() ?? '';
        if (leftAt.isEmpty || returnedAt.isEmpty) continue;
        final leftDate = leftAt.length >= 10 ? leftAt.substring(0, 10) : '';
        final returnDate = returnedAt.length >= 10 ? returnedAt.substring(0, 10) : '';
        int startIdx = -1, endIdx = -1;
        for (var i = 0; i < timestamps.length; i++) {
          final tDate = timestamps[i].length >= 10 ? timestamps[i].substring(0, 10) : '';
          if (startIdx == -1 && tDate.compareTo(leftDate) >= 0) startIdx = i;
          if (tDate.compareTo(returnDate) <= 0) endIdx = i;
        }
        if (startIdx >= 0 && endIdx >= 0) {
          final x1 = chartLeft + (startIdx / (maxPoints - 1)) * chartWidth;
          final x2 = chartLeft + (endIdx / (maxPoints - 1)) * chartWidth;
          canvas.drawRect(
            Rect.fromLTRB(x1, chartTop, x2, chartTop + chartHeight),
            Paint()..color = const Color(0xFF333333).withOpacity(0.3),
          );
          final awayTp = TextPainter(
            text: const TextSpan(text: 'Away', style: TextStyle(color: Color(0xFF555555), fontSize: 9)),
            textDirection: TextDirection.ltr)..layout();
          awayTp.paint(canvas, Offset((x1 + x2) / 2 - awayTp.width / 2, chartTop + 2));
        }
      }
    }

    // Draw lines
    _drawLine(canvas, cEmoVals, const Color(0xFF4ECDC4), chartLeft, chartTop, chartWidth, chartHeight, maxPoints);
    if (gapVals.length == maxPoints) {
      _drawLine(canvas, gapVals, const Color(0xFFC9A962), chartLeft, chartTop, chartWidth, chartHeight, maxPoints);
    }
    if (quantumVals.length == maxPoints) {
      _drawLine(canvas, quantumVals, const Color(0xFF9D4EDD), chartLeft, chartTop, chartWidth, chartHeight, maxPoints);
    }

    // CEE dots
    if (ceeExperiences.isNotEmpty && timestamps.isNotEmpty) {
      final ceePaint = Paint()..color = const Color(0xFF00FF88);
      final ceeGlow = Paint()..color = const Color(0xFF00FF88).withOpacity(0.3);
      for (final ce in ceeExperiences) {
        if (ce is! Map) continue;
        final ceTs = ce['timestamp']?.toString() ?? '';
        final ceDate = ceTs.length >= 10 ? ceTs.substring(0, 10) : '';
        final cemoAfter = (ce['c_emo_after'] as num?)?.toDouble() ?? 0.75;
        int closestIdx = 0;
        double closestDist = double.infinity;
        for (var i = 0; i < timestamps.length; i++) {
          final tDate = timestamps[i].length >= 10 ? timestamps[i].substring(0, 10) : '';
          final dist = (tDate.compareTo(ceDate)).abs().toDouble();
          if (dist < closestDist) { closestDist = dist; closestIdx = i; }
        }
        final x = chartLeft + (closestIdx / (maxPoints - 1)) * chartWidth;
        final y = chartTop + chartHeight * (1 - cemoAfter.clamp(0, 1));
        canvas.drawCircle(Offset(x, y), 6, ceeGlow);
        canvas.drawCircle(Offset(x, y), 3.5, ceePaint);
      }
    }
  }

  void _drawLine(Canvas canvas, List<double> vals, Color color,
      double left, double top, double width, double height, int maxPoints) {
    if (vals.length < 2) return;
    final paint = Paint()..color = color..strokeWidth = 2..style = PaintingStyle.stroke..strokeCap = StrokeCap.round;
    final path = Path();
    for (var i = 0; i < vals.length; i++) {
      final x = left + (i / (maxPoints - 1)) * width;
      final y = top + height * (1 - vals[i].clamp(0, 1));
      if (i == 0) path.moveTo(x, y); else path.lineTo(x, y);
    }
    canvas.drawPath(path, paint);

    // Gradient fill
    final fillPath = Path.from(path);
    fillPath.lineTo(left + ((vals.length - 1) / (maxPoints - 1)) * width, top + height);
    fillPath.lineTo(left, top + height);
    fillPath.close();
    canvas.drawPath(fillPath, Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter, end: Alignment.bottomCenter,
        colors: [color.withOpacity(0.12), color.withOpacity(0.01)],
      ).createShader(Rect.fromLTWH(left, top, width, height)));

    // Endpoint dot
    final lastX = left + ((vals.length - 1) / (maxPoints - 1)) * width;
    final lastY = top + height * (1 - vals.last.clamp(0, 1));
    canvas.drawCircle(Offset(lastX, lastY), 3, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => true;
}
