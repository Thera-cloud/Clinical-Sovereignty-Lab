// Sovereign Studio S1 — Show Setup + Mirror Capture. QUANTUM-CRYSTAL-ARCH
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import '../config/app_config.dart';
import '../services/coach_web_recorder.dart';
import '../services/studio_livekit_room.dart';
import '../services/studio_part_player.dart';
import 'coach_studio_persona_tools.dart';

const _lnLabel = 'Little Nate (co-host)';
const _verticals = <String>[
  'life_coaching',
  'grief',
  'relationships_intimacy',
  'trauma_modalities',
  'neuroscience_education',
];

Future<Uint8List?> _pickedFileBytes(PlatformFile file) async {
  if (file.bytes != null && file.bytes!.isNotEmpty) {
    return file.bytes;
  }
  final stream = file.readStream;
  if (stream != null) {
    final chunks = <int>[];
    await for (final part in stream) {
      chunks.addAll(part);
    }
    if (chunks.isNotEmpty) {
      return Uint8List.fromList(chunks);
    }
  }
  return null;
}

class CoachSovereignStudioTab extends StatefulWidget {
  final String token;
  const CoachSovereignStudioTab({super.key, required this.token});

  @override
  State<CoachSovereignStudioTab> createState() => _CoachSovereignStudioTabState();
}

class _CoachSovereignStudioTabState extends State<CoachSovereignStudioTab>
    with SingleTickerProviderStateMixin {
  static const _gold = Color(0xFFC9A962);
  static const _muted = Color(0xFF8B7355);
  static const _text = Color(0xFFE8D5A3);
  late final TabController _studioTabs;

  final _nameCtrl = TextEditingController();
  final _descCtrl = TextEditingController();
  final _hostCtrl = TextEditingController();
  final _rtmpCtrl = TextEditingController();
  String _vertical = 'life_coaching';
  bool _ytConnected = false;
  String _ytChannel = '';
  String _ytWatch = '';
  String _ytHint = '';
  bool _smsOptIn = false;
  String _lkNote = '';
  String _roomUrl = '';
  List<Offset> _envelope = const [];
  List<Map<String, dynamic>> _shows = [];
  Map<String, dynamic>? _selected;
  List<Map<String, dynamic>> _parts = [];
  List<Map<String, dynamic>> _episodes = [];
  int _callersLogged = 0;
  int _callersOpted = 0;
  List<String> _recentTopics = [];
  String _delayNote = '';
  String _meterNote = '';
  Map<String, dynamic>? _queueBoard;
  List<Map<String, dynamic>> _episodeFlags = [];
  String? _sessionId;
  int _complete = 0;
  bool _cloneConsent = false;
  bool _busy = false;
  final Set<int> _uploading = {};
  final Set<int> _locallyComplete = {};
  int? _recordingPart;
  final _recorder = CoachWebRecorder();
  final _noteCtrl = TextEditingController();
  final _cutsCtrl = TextEditingController();
  final List<_KeepRange> _keepRows = [];
  String _editEid = '';
  String _tapeUrl = '';
  Timer? _tick;
  Timer? _egressRetry;
  Timer? _callerPoll;
  int _egressAttempts = 0;
  int _secs = 0;
  int _personaEpoch = 0;
  List<Map<String, dynamic>> _lastDiff = const [];

  Map<String, String> get _h => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ${widget.token}',
      };

  @override
  void initState() {
    super.initState();
    _studioTabs = TabController(length: 5, vsync: this);
    _refresh();
  }

  @override
  void dispose() {
    _tick?.cancel();
    _egressRetry?.cancel();
    _callerPoll?.cancel();
    stopStudioPlayback();
    if (_recordingPart != null) {
      _recorder.stop();
    }
    _nameCtrl.dispose();
    _descCtrl.dispose();
    _hostCtrl.dispose();
    _rtmpCtrl.dispose();
    _noteCtrl.dispose();
    _cutsCtrl.dispose();
    _studioTabs.dispose();
    _clearKeepRows(disposeOnly: true);
    super.dispose();
  }

  void _clearKeepRows({bool disposeOnly = false}) {
    for (final row in _keepRows) {
      row.start.dispose();
      row.end.dispose();
    }
    _keepRows.clear();
    if (!disposeOnly && mounted) setState(() {});
  }

  void _addKeepRow([double? startS, double? endS]) {
    setState(() {
      _keepRows.add(_KeepRange(
        start: TextEditingController(
            text: startS == null ? '' : startS.toStringAsFixed(1)),
        end: TextEditingController(
            text: endS == null ? '' : endS.toStringAsFixed(1)),
      ));
    });
  }

  List<Map<String, double>> _cutsFromKeepRows() {
    final out = <Map<String, double>>[];
    for (final row in _keepRows) {
      final a = double.tryParse(row.start.text.trim());
      final b = double.tryParse(row.end.text.trim());
      if (a == null || b == null || b <= a) continue;
      out.add({'start_s': a, 'end_s': b});
    }
    return out;
  }

  void _loadCuts(dynamic raw) {
    _clearKeepRows(disposeOnly: true);
    final list = (raw is List) ? raw : const [];
    for (final item in list) {
      if (item is! Map) continue;
      final a = (item['start_s'] ?? item['start']) as num?;
      final b = (item['end_s'] ?? item['end']) as num?;
      if (a == null || b == null) continue;
      _keepRows.add(_KeepRange(
        start: TextEditingController(text: a.toString()),
        end: TextEditingController(text: b.toString()),
      ));
    }
    if (_keepRows.isEmpty) {
      _keepRows.add(_KeepRange(
        start: TextEditingController(),
        end: TextEditingController(),
      ));
    }
  }

  Future<void> _openEditor(Map<String, dynamic> episode) async {
    final eid = (episode['id'] ?? '').toString();
    if (eid.isEmpty) return;
    _editEid = eid;
    _tapeUrl = (episode['tape_url'] ?? '').toString();
    _loadCuts(episode['cuts']);
    setState(() {});
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/episodes/$eid'),
        headers: _h,
      );
      if (!mounted || r.statusCode != 200) return;
      final j = json.decode(r.body) as Map<String, dynamic>;
      final ep = Map<String, dynamic>.from((j['episode'] ?? {}) as Map);
      _loadCuts(ep['cuts']);
      _episodeFlags =
          List<Map<String, dynamic>>.from((j['flags'] ?? []) as List);
      final url = (ep['tape_url'] ?? '').toString();
      if (url.isNotEmpty) _tapeUrl = url;
      setState(() {});
    } catch (_) {}
    _studioTabs.animateTo(2);
  }

  List<Map<String, dynamic>> get _displayParts {
    if (_parts.isNotEmpty) return _parts;
    return List.generate(
      7,
      (i) => {
        'index': i + 1,
        'title': 'Part ${i + 1}',
        'prompt': '',
        'complete': false,
      },
    );
  }

  void _applyServerParts(dynamic raw, int? completeCount) {
    final list = List<Map<String, dynamic>>.from((raw as List?) ?? []);
    for (final p in list) {
      final idx = (p['index'] as num?)?.toInt();
      if (idx != null && _locallyComplete.contains(idx)) {
        p['complete'] = true;
      }
    }
    _parts = list;
    _complete = list.isEmpty
        ? _locallyComplete.length
        : list.where((p) => p['complete'] == true).length;
    if (completeCount != null && completeCount > _complete) {
      _complete = completeCount;
    }
  }

  void _markPartComplete(int n) {
    _locallyComplete.add(n);
    final list =
        _displayParts.map((p) => Map<String, dynamic>.from(p)).toList();
    for (final p in list) {
      if ((p['index'] as num?)?.toInt() == n) {
        p['complete'] = true;
      }
    }
    _parts = list;
    _complete = list.where((p) => p['complete'] == true).length;
  }

  Future<void> _refreshMirrorOnly() async {
    try {
      final statusR = await http.get(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/status'),
        headers: _h,
      );
      if (!mounted || statusR.statusCode != 200) return;
      final j = json.decode(statusR.body) as Map<String, dynamic>;
      setState(() {
        _applyServerParts(j['parts'], (j['complete_count'] as num?)?.toInt());
        _cloneConsent = j['clone_consent'] == true;
      });
    } catch (_) {}
  }

  Widget _spin() => const SizedBox(
        width: 14,
        height: 14,
        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.black),
      );

  Future<void> _refreshCallerBoard() async {
    final sid = _sessionId ?? '';
    if (sid.isEmpty) return;
    try {
      final r = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/sessions/$sid/queue'),
        headers: _h,
      );
      if (!mounted || r.statusCode != 200) return;
      setState(() {
        _queueBoard = json.decode(r.body) as Map<String, dynamic>;
      });
    } catch (_) {}
  }

  void _startCallerPoll() {
    _callerPoll?.cancel();
    if ((_sessionId ?? '').isEmpty) return;
    _refreshCallerBoard();
    _callerPoll = Timer.periodic(const Duration(seconds: 3), (_) {
      if ((_sessionId ?? '').isEmpty) return;
      _refreshCallerBoard();
    });
  }

  void _stopCallerPoll() {
    _callerPoll?.cancel();
    _callerPoll = null;
  }

  Future<void> _queueOp(String op, {String? callerId}) async {
    final sid = _sessionId ?? '';
    if (sid.isEmpty) return;
    setState(() => _busy = true);
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}/api/studio/sessions/$sid/queue'),
      headers: _h,
      body: json.encode({
        'op': op,
        if (callerId != null && callerId.isNotEmpty) 'caller_id': callerId,
      }),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    if (r.statusCode == 200) {
      await _refreshCallerBoard();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Queue ${r.statusCode}')),
      );
    }
  }

  Future<void> _loadShowOps() async {
    final sid = (_selected?['id'] ?? '').toString();
    if (sid.isEmpty) return;
    try {
      final showR = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/shows/$sid'),
        headers: _h,
      );
      final delayR = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/shows/$sid/delay'),
        headers: _h,
      );
      final meterR = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/shows/$sid/meter'),
        headers: _h,
      );
      if (!mounted) return;
      if (showR.statusCode == 200) {
        final j = json.decode(showR.body) as Map<String, dynamic>;
        final show = Map<String, dynamic>.from((j['show'] ?? j) as Map);
        _rtmpCtrl.text = (show['rtmp_url'] ?? '').toString();
        if (show.isNotEmpty) {
          _selected = {...?_selected, ...show};
        }
      }
      if (delayR.statusCode == 200) {
        final j = json.decode(delayR.body) as Map<String, dynamic>;
        final unlocked = j['live_unlocked'] == true;
        final delay = j['delay_s'] ?? 45;
        _delayNote = unlocked
            ? 'Live unlocked · ${j['dump'] ?? 'armed'} · ${delay}s delay'
            : 'Dump locked until tier unlock · ${delay}s delay when live';
      }
      if (meterR.statusCode == 200) {
        final j = json.decode(meterR.body) as Map<String, dynamic>;
        final days = (j['days'] as List?) ?? [];
        if (days.isNotEmpty && days.first is Map) {
          final d = days.first as Map;
          _meterNote =
              '${d['day']}: ${d['session_minutes']} min session · ${d['caller_minutes']} caller min';
        } else {
          _meterNote = 'No meter rows yet';
        }
      }
    } catch (_) {}
  }

  Future<void> _verifyHost() async {
    final sid = (_selected?['id'] ?? '').toString();
    if (sid.isEmpty) return;
    await _post('/api/studio/shows/$sid/verify-host-number', {
      'host_number': _hostCtrl.text.trim(),
    });
  }

  Future<void> _saveRtmp() async {
    final sid = (_selected?['id'] ?? '').toString();
    if (sid.isEmpty) return;
    await _post('/api/studio/shows/$sid/rtmp-key', {
      'rtmp_url': _rtmpCtrl.text.trim(),
    });
  }

  Future<void> _copyRss() async {
    final sid = (_selected?['id'] ?? '').toString();
    if (sid.isEmpty) return;
    final url = '${AppConfig.apiBaseUrl}/api/studio/feeds/$sid/rss';
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('RSS feed URL copied')),
    );
  }

  Future<void> _resolveFlag(String flagId) async {
    if (_editEid.isEmpty) return;
    final reason = _noteCtrl.text.trim();
    if (reason.length < 8) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Type an 8+ char reason in coach note')),
      );
      return;
    }
    await _post('/api/studio/episodes/$_editEid/flags/$flagId/resolve', {
      'reason': reason,
    });
    await _openEditor({'id': _editEid});
  }

  Widget _callerBoard() {
    final q = Map<String, dynamic>.from(
        (_queueBoard?['queue'] ?? {}) as Map? ?? {});
    final labels = Map<String, dynamic>.from(
        (q['labels'] ?? {}) as Map? ?? {});
    final active = (q['active'] ?? '').toString();
    final waiting = List<String>.from((q['waiting'] as List?) ?? []);
    String label(String id) =>
        (labels[id] ?? id).toString().replaceAll('caller-', 'Caller ');

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('CALLER BOARD',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        Text(
          active.isEmpty
              ? 'On air: —'
              : 'On air: ${label(active)}',
          style: const TextStyle(color: _text, fontSize: 12),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            OutlinedButton(
              onPressed: _busy || active.isNotEmpty
                  ? null
                  : () => _queueOp('bring_on'),
              child: const Text('Bring on next', style: TextStyle(fontSize: 11)),
            ),
            OutlinedButton(
              onPressed: _busy || active.isEmpty
                  ? null
                  : () => _queueOp('hold'),
              child: const Text('Hold', style: TextStyle(fontSize: 11)),
            ),
            OutlinedButton(
              onPressed: _busy || active.isEmpty
                  ? null
                  : () => _queueOp('drop'),
              child: const Text('Drop', style: TextStyle(fontSize: 11)),
            ),
          ],
        ),
        if (waiting.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Text('Waiting room empty',
                style: TextStyle(color: _muted, fontSize: 11)),
          ),
        ...waiting.map((id) {
          return Card(
            color: const Color(0xFF111111),
            margin: const EdgeInsets.only(top: 6),
            child: ListTile(
              dense: true,
              title: Text(label(id),
                  style: const TextStyle(color: _text, fontSize: 12)),
              subtitle: Text(id,
                  style: const TextStyle(color: _muted, fontSize: 10)),
              trailing: Wrap(
                spacing: 0,
                children: [
                  IconButton(
                    icon: const Icon(Icons.arrow_upward, size: 16),
                    color: _gold,
                    onPressed: _busy
                        ? null
                        : () => _queueOp('move_up', callerId: id),
                  ),
                  IconButton(
                    icon: const Icon(Icons.arrow_downward, size: 16),
                    color: _gold,
                    onPressed: _busy
                        ? null
                        : () => _queueOp('move_down', callerId: id),
                  ),
                  TextButton(
                    onPressed: _busy || active.isNotEmpty
                        ? null
                        : () => _queueOp('bring_on', callerId: id),
                    child: const Text('Air', style: TextStyle(fontSize: 11)),
                  ),
                ],
              ),
            ),
          );
        }),
      ],
    );
  }

  Future<void> _refresh() async {
    try {
      final showsR = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/shows'),
        headers: _h,
      );
      final statusR = await http.get(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/status'),
        headers: _h,
      );
      final ytR = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/youtube/status'),
        headers: _h,
      );
      final envR = await http.get(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/avatar/envelope?level=0.4'),
      );
      if (!mounted) return;
      if (showsR.statusCode == 200) {
        final j = json.decode(showsR.body);
        final list = j is Map ? (j['shows'] ?? j['items'] ?? []) : j;
        _shows = List<Map<String, dynamic>>.from(list as List? ?? []);
        if (_shows.isNotEmpty && _selected == null) {
          _selected = _shows.first;
        }
      }
      if (statusR.statusCode == 200) {
        final j = json.decode(statusR.body) as Map<String, dynamic>;
        _applyServerParts(j['parts'], (j['complete_count'] as num?)?.toInt());
        _cloneConsent = j['clone_consent'] == true;
      }
      if (ytR.statusCode == 200) {
        final j = json.decode(ytR.body) as Map<String, dynamic>;
        _ytConnected = j['connected'] == true;
        _ytChannel = (j['channel_name'] ?? '').toString();
        _ytHint = (j['live_hint'] ?? '').toString();
      }
      if (envR.statusCode == 200) {
        final j = json.decode(envR.body) as Map<String, dynamic>;
        final pts = (j['points'] as List?) ?? [];
        _envelope = pts
            .whereType<Map>()
            .map((p) => Offset(
                  (p['x'] as num?)?.toDouble() ?? 0,
                  (p['y'] as num?)?.toDouble() ?? 0,
                ))
            .toList();
      }
      final sid = (_selected?['id'] ?? '').toString();
      if (sid.isNotEmpty) {
        final epR = await http.get(
          Uri.parse('${AppConfig.apiBaseUrl}/api/studio/shows/$sid/episodes'),
          headers: _h,
        );
        final memR = await http.get(
          Uri.parse('${AppConfig.apiBaseUrl}/api/studio/shows/$sid/caller-memory'),
          headers: _h,
        );
        if (epR.statusCode == 200) {
          final j = json.decode(epR.body);
          _episodes = List<Map<String, dynamic>>.from((j['episodes'] ?? []) as List);
        }
        if (memR.statusCode == 200) {
          final j = json.decode(memR.body) as Map<String, dynamic>;
          _callersLogged = (j['logged'] as num?)?.toInt() ?? 0;
          _callersOpted = (j['opted_in'] as num?)?.toInt() ?? 0;
          _recentTopics = List<String>.from(
              (j['recent_topics'] as List?)?.map((e) => e.toString()) ?? []);
        }
        await _loadShowOps();
      }
      if ((_sessionId ?? '').isNotEmpty) {
        await _refreshCallerBoard();
      }
      setState(() {});
    } catch (_) {}
  }

  Future<void> _post(String path, [Map<String, dynamic>? body]) async {
    if (path.contains('/end')) {
      _egressRetry?.cancel();
      _stopCallerPoll();
      _studioTabs.animateTo(2);
    }
    setState(() => _busy = true);
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}$path'),
      headers: _h,
      body: json.encode(body ?? {}),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    String msg = '${r.statusCode}';
    if (r.statusCode == 200) {
      msg = 'OK';
      try {
        final j = json.decode(r.body);
        if (j is Map) {
          if (j['uploaded'] == true) {
            msg = 'YouTube ${j['video_id'] ?? 'ok'}';
          } else if (j['live'] == true) {
            _ytWatch = (j['watch_url'] ?? '').toString();
            msg = _ytWatch.isNotEmpty ? 'Live $_ytWatch' : 'YouTube live armed';
          } else if (j['applied'] == true) {
            msg = 'Cuts applied';
          } else if (j['reason'] != null && '${j['reason']}'.isNotEmpty) {
            msg = j['reason'].toString();
          }
        }
      } catch (_) {}
    } else {
      msg =
          '${r.statusCode}: ${r.body.length > 80 ? r.body.substring(0, 80) : r.body}';
    }
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    if (path == '/api/studio/sessions' && r.statusCode == 200) {
      final j = json.decode(r.body) as Map<String, dynamic>;
      _sessionId = (j['session']?['id'] ?? j['id'] ?? '').toString();
      _studioTabs.animateTo(1);
      if ((_sessionId ?? '').isNotEmpty) {
        await _joinRoom();
        _startCallerPoll();
      }
    }
    await _refresh();
    if (path.contains('/end') && r.statusCode == 200 && _episodes.isNotEmpty) {
      await _openEditor(_episodes.first);
    }
  }

  Future<void> _connectYoutube() async {
    final r = await http.get(
      Uri.parse('${AppConfig.apiBaseUrl}/api/studio/youtube/connect'),
      headers: _h,
    );
    if (!mounted) return;
    if (r.statusCode != 200) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('YouTube connect failed (${r.statusCode})')));
      return;
    }
    final url = (json.decode(r.body)['url'] ?? '').toString();
    if (url.isEmpty) return;
    await launchUrl(Uri.parse(url),
        mode: LaunchMode.externalApplication, webOnlyWindowName: '_blank');
  }

  Future<void> _goYoutubeLive() async {
    final sid = (_selected?['id'] ?? '').toString();
    if (sid.isEmpty) return;
    final title = _nameCtrl.text.trim().isEmpty
        ? 'Sovereign Studio live'
        : _nameCtrl.text.trim();
    await _post('/api/studio/shows/$sid/youtube-go-live', {
      'title': title,
      'privacy': 'unlisted',
      'session_id': _sessionId ?? '',
    });
  }

  Future<void> _pickLiveShare() async {
    final sid = (_sessionId ?? '').trim();
    if (sid.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Start a session first, then pick a file for Nate.')));
      return;
    }
    try {
      final picked = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: const [
          'jpg',
          'jpeg',
          'png',
          'webp',
          'gif',
          'pdf',
          'txt',
          'doc',
          'docx',
          'md',
          'mp4',
          'webm',
          'mov',
        ],
        withData: true,
      );
      if (picked == null || picked.files.isEmpty) return;
      final file = picked.files.first;
      final ext = (file.extension ?? '').toLowerCase();
      if (['mp4', 'webm', 'mov', 'm4v'].contains(ext)) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text(
                'Video: Open studio room → ON SCREEN → Video so Nate gets a still.')));
        return;
      }
      final bytes = await _pickedFileBytes(file);
      if (bytes == null || bytes.isEmpty) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Could not read that file')));
        return;
      }
      if (bytes.length > 8 * 1024 * 1024) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('File is over 8 MB')));
        return;
      }
      setState(() => _busy = true);
      final req = http.MultipartRequest(
        'POST',
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/studio/sessions/$sid/share-asset'),
      );
      req.headers['Authorization'] = 'Bearer ${widget.token}';
      req.files.add(http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: file.name,
      ));
      final streamed = await req.send();
      final r = await http.Response.fromStream(streamed);
      if (!mounted) return;
      setState(() => _busy = false);
      String msg = '${r.statusCode}';
      if (r.statusCode == 200) {
        try {
          final j = json.decode(r.body) as Map<String, dynamic>;
          msg = j['seen'] == true
              ? 'Nate can read ${(j['name'] ?? file.name)}'
              : (j['reason'] ?? 'Uploaded').toString();
        } catch (_) {
          msg = 'Uploaded';
        }
      } else {
        msg = r.body.length > 80 ? r.body.substring(0, 80) : r.body;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Picker failed: $e')));
    }
  }

  Future<void> _toggleSms(bool on) async {
    final sid = (_selected?['id'] ?? '').toString();
    if (sid.isEmpty) return;
    setState(() => _smsOptIn = on);
    await _post('/api/studio/shows/$sid/sms-consent', {
      'granted': on,
      'consent_kind': 'sms_opt_in',
    });
  }

  Future<void> _joinRoom() async {
    if ((_sessionId ?? '').isEmpty) return;
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}/api/studio/sessions/$_sessionId/join-token'),
      headers: _h,
      body: json.encode({'role': 'host'}),
    );
    if (!mounted) return;
    if (r.statusCode == 200) {
      final j = json.decode(r.body) as Map<String, dynamic>;
      final roomUrl = (j['room_url'] ?? '').toString();
      final note = j['jwt'] == true
          ? 'LiveKit JWT ready (guest audio-only). Tape starts after you are in the room.'
          : 'LiveKit pending URL — envelope avatar local.';
      setState(() {
        _roomUrl = roomUrl;
        _lkNote = note;
      });
      _egressAttempts = 0;
      _scheduleEgress(const Duration(seconds: 8));
    }
  }

  void _scheduleEgress(Duration delay) {
    _egressRetry?.cancel();
    _egressRetry = Timer(delay, _startEgress);
  }

  Future<void> _startEgress() async {
    final sid = _sessionId ?? '';
    if (!mounted || sid.isEmpty) return;
    try {
      final eg = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/api/studio/sessions/$sid/egress'),
        headers: _h,
        body: json.encode({}),
      );
      if (!mounted) return;
      if (eg.statusCode == 200) {
        final ej = json.decode(eg.body) as Map<String, dynamic>;
        final started = ej['started'] == true;
        final reason = (ej['reason'] ?? 'pending').toString();
        setState(() {
          _lkNote = started
              ? 'LiveKit JWT ready. Egress started.'
              : 'LiveKit JWT ready. Egress: $reason.';
        });
        if (started) return;
        _egressAttempts += 1;
        if (_egressAttempts < 3 &&
            (reason == 'room_empty' || reason == 'egress_worker_or_api')) {
          _scheduleEgress(Duration(seconds: _egressAttempts == 1 ? 12 : 25));
        }
      }
    } catch (_) {}
  }

  List<Map<String, double>> _parseCuts(String raw) {
    final out = <Map<String, double>>[];
    for (final part in raw.split(',')) {
      final bits = part.trim().replaceAll('–', '-').split('-');
      if (bits.length != 2) continue;
      final a = double.tryParse(bits[0].trim());
      final b = double.tryParse(bits[1].trim());
      if (a == null || b == null || b <= a) continue;
      out.add({'start_s': a, 'end_s': b});
    }
    return out;
  }

  Future<void> _applyCuts(String eid) async {
    var cuts = _cutsFromKeepRows();
    if (cuts.isEmpty) cuts = _parseCuts(_cutsCtrl.text);
    if (cuts.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Cuts required (e.g. 10-40,90-120)')));
      return;
    }
    await _post('/api/studio/episodes/$eid/apply-cuts', {'cuts': cuts});
  }

  Future<void> _openTranscript(String eid) async {
    final r = await http.get(
      Uri.parse('${AppConfig.apiBaseUrl}/api/studio/episodes/$eid'),
      headers: _h,
    );
    if (!mounted) return;
    if (r.statusCode != 200) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Transcript failed (${r.statusCode})')));
      return;
    }
    final j = json.decode(r.body) as Map<String, dynamic>;
    final segs = List<Map<String, dynamic>>.from(
        ((j['episode']?['transcript'] ?? []) as List));
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: const Text('Speaker transcript',
            style: TextStyle(color: _text, fontSize: 14)),
        content: SizedBox(
          width: 420,
          child: segs.isEmpty
              ? const Text('No speaker lines yet',
                  style: TextStyle(color: _muted, fontSize: 12))
              : ListView(
                  shrinkWrap: true,
                  children: segs
                      .map((s) => Text(
                            '${s['speaker'] ?? '?'}: ${s['text'] ?? ''}',
                            style: const TextStyle(color: _text, fontSize: 12),
                          ))
                      .toList(),
                ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Close')),
        ],
      ),
    );
  }

  Future<void> _createShow() async {
    setState(() => _busy = true);
    final r = await http.post(
      Uri.parse('${AppConfig.apiBaseUrl}/api/studio/shows'),
      headers: _h,
      body: json.encode({
        'name': _nameCtrl.text.trim(),
        'vertical': _vertical,
        'description': _descCtrl.text.trim(),
        'host_number': _hostCtrl.text.trim(),
      }),
    );
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Show created'
            : 'Create failed (${r.statusCode})')));
    await _refresh();
  }

  Future<void> _signClone() async {
    final r = await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/consent-clone'),
      headers: _h,
      body: json.encode({'signed': true}),
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Likeness consent recorded — clone never used as LN on-air voice'
            : 'Consent failed (${r.statusCode})')));
    await _refresh();
  }

  Future<void> _finalize() async {
    setState(() => _busy = true);
    final r = await http.post(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/finalize'),
      headers: _h,
      body: json.encode({}),
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (r.statusCode == 200) {
        try {
          final j = json.decode(r.body) as Map<String, dynamic>;
          _lastDiff = List<Map<String, dynamic>>.from(j['diff'] ?? []);
        } catch (_) {
          _lastDiff = const [];
        }
        _personaEpoch += 1;
      }
    });
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(r.statusCode == 200
            ? 'Persona style updated — review the card below'
            : 'Finalize failed (${r.statusCode})')));
    await _refresh();
  }

  Future<void> _showTranscript(int n) async {
    final r = await http.get(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/parts/$n/transcript'),
      headers: _h,
    );
    if (!mounted) return;
    if (r.statusCode != 200) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Transcript failed (${r.statusCode})')));
      return;
    }
    final j = json.decode(r.body) as Map<String, dynamic>;
    final text = (j['transcript'] ?? '').toString();
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF111111),
        title: Text('Part $n transcript',
            style: const TextStyle(color: _text, fontSize: 14)),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Text(
              text.isEmpty ? 'No transcript yet — STT may still be running' : text,
              style: const TextStyle(color: _text, fontSize: 12),
            ),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Close')),
        ],
      ),
    );
  }

  Future<void> _playPart(int n) async {
    final r = await http.get(
      Uri.parse(
          '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/parts/$n/audio'),
      headers: _h,
    );
    if (!mounted) return;
    if (r.statusCode != 200 || r.bodyBytes.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Play failed (${r.statusCode})')));
      return;
    }
    final mime = r.headers['content-type'] ?? 'audio/webm';
    playStudioBytes(r.bodyBytes, mime);
  }

  Future<void> _uploadPart(int n, Uint8List bytes, String contentType) async {
    if (bytes.length > 15 * 1024 * 1024) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Audio over 15 MB')));
      return;
    }
    if (_uploading.contains(n)) return;
    setState(() => _uploading.add(n));
    try {
      final r = await http.post(
        Uri.parse(
            '${AppConfig.apiBaseUrl}/api/coach/integrations/mirror-capture/parts/$n/upload'),
        headers: _h,
        body: json.encode({
          'audio_b64': base64Encode(bytes),
          'content_type': contentType,
          'media_kind': 'audio',
          'clone_consent': _cloneConsent,
        }),
      );
      if (!mounted) return;
      final saved = r.statusCode == 200;
      final timedOut = r.statusCode == 504 || r.statusCode == 408;
      if (saved || timedOut) {
        setState(() => _markPartComplete(n));
        unawaited(_refreshMirrorOnly());
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(saved
              ? 'Part $n stored (re-record overwrites)'
              : (timedOut
                  ? 'Part $n still saving in background — other parts stay open'
                  : 'Upload failed (${r.statusCode})'))));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Upload failed: $e')));
    } finally {
      if (mounted) setState(() => _uploading.remove(n));
    }
  }

  Future<void> _toggleRecord(int n) async {
    if (!CoachWebRecorder.isSupported) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('In-app record is available on web')));
      return;
    }
    if (_recordingPart == n) {
      _tick?.cancel();
      setState(() => _recordingPart = null);
      try {
        final bytes = await _recorder.stop();
        if (bytes.isEmpty) {
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('No audio captured')));
          return;
        }
        unawaited(_uploadPart(n, bytes, _recorder.contentType));
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Record failed: $e')));
      }
      return;
    }
    try {
      await _recorder.start();
      _secs = 0;
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!mounted) return;
        setState(() => _secs += 1);
        if (_secs >= 180) {
          _toggleRecord(n);
        }
      });
      setState(() => _recordingPart = n);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Mic failed: $e')));
    }
  }

  Future<void> _pickPart(int n) async {
    try {
      final picked = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: const ['wav', 'mp3', 'm4a', 'ogg', 'webm'],
        withData: true,
        withReadStream: true,
      );
      if (picked == null || picked.files.isEmpty) return;
      final file = picked.files.first;
      final bytes = await _pickedFileBytes(file);
      if (bytes == null || bytes.isEmpty) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Could not read audio bytes')));
        return;
      }
      final ext = (file.extension ?? '').toLowerCase();
      final ctype = {
        'wav': 'audio/wav',
        'mp3': 'audio/mpeg',
        'm4a': 'audio/m4a',
        'ogg': 'audio/ogg',
        'webm': 'audio/webm',
      }[ext] ?? 'audio/webm';
      unawaited(_uploadPart(n, bytes, ctype));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Picker failed: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final clean = (_selected?['clean_published'] as num?)?.toInt() ?? 0;
    final liveReady = clean >= 1;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('$_lnLabel is live in the room with you and callers.',
            style: const TextStyle(color: _text, fontSize: 13)),
        const SizedBox(height: 6),
        Text(
          liveReady
              ? 'Live tier unlocked (1 clean published episode).'
              : 'Live tier: $clean/1 clean published episode.',
          style: const TextStyle(color: _muted, fontSize: 12),
        ),
        TabBar(
          controller: _studioTabs,
          isScrollable: true,
          indicatorColor: _gold,
          labelColor: _gold,
          unselectedLabelColor: _muted,
          tabs: const [
            Tab(text: 'SHOW'),
            Tab(text: 'LIVE'),
            Tab(text: 'EDIT'),
            Tab(text: 'PERSONA'),
            Tab(text: 'ON AIR'),
          ],
        ),
        Expanded(
          child: TabBarView(
            controller: _studioTabs,
            children: [
              _showPane(),
              _livePane(liveReady),
              _editPane(),
              _personaPane(),
              _onAirPane(liveReady),
            ],
          ),
        ),
      ],
    );
  }

  Widget _showPane() {
    return ListView(
      padding: const EdgeInsets.only(top: 12),
      children: [
        const Text('SHOW SETUP',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 8),
        TextField(
          controller: _nameCtrl,
          style: const TextStyle(color: _text),
          decoration: const InputDecoration(
            hintText: 'Show name',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        const SizedBox(height: 8),
        DropdownButton<String>(
          value: _vertical,
          dropdownColor: const Color(0xFF111111),
          isExpanded: true,
          items: _verticals
              .map((v) => DropdownMenuItem(
                    value: v,
                    child: Text(v.replaceAll('_', ' '),
                        style: const TextStyle(color: _text)),
                  ))
              .toList(),
          onChanged: (v) => setState(() => _vertical = v ?? _vertical),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _descCtrl,
          maxLines: 2,
          style: const TextStyle(color: _text),
          decoration: const InputDecoration(
            hintText: 'Description (not clinical / therapy / diagnose)',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _hostCtrl,
          style: const TextStyle(color: _text),
          decoration: const InputDecoration(
            hintText: 'Host number (Google Voice OK)',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: _busy || _selected == null ? null : _verifyHost,
          child: const Text('Verify host number', style: TextStyle(fontSize: 11)),
        ),
        if ((_selected?['did_e164'] ?? '').toString().isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(
            'Listener line: ${_selected?['did_e164']}',
            style: const TextStyle(color: _muted, fontSize: 11),
          ),
        ],
        const SizedBox(height: 8),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: _verticals
              .map((v) => ChoiceChip(
                    label: Text(v.replaceAll('_', ' '),
                        style: const TextStyle(fontSize: 11)),
                    selected: _vertical == v,
                    selectedColor: _gold,
                    onSelected: (_) => setState(() => _vertical = v),
                  ))
              .toList(),
        ),
        const SizedBox(height: 8),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: _gold),
          onPressed: _busy ? null : _createShow,
          child: const Text('Create show',
              style: TextStyle(color: Colors.black)),
        ),
        if (_shows.isNotEmpty) ...[
          const SizedBox(height: 12),
          ..._shows.map((s) => ListTile(
                dense: true,
                title: Text((s['name'] ?? '').toString(),
                    style: const TextStyle(color: _text, fontSize: 13)),
                subtitle: Text(
                    '${s['vertical'] ?? ''} · ${s['did_e164'] ?? 'no DID'}',
                    style: const TextStyle(color: _muted, fontSize: 11)),
                onTap: () {
                  setState(() => _selected = s);
                  _refresh();
                },
              )),
        ],
        const SizedBox(height: 12),
        const Text('STREAM / RSS',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        TextField(
          controller: _rtmpCtrl,
          style: const TextStyle(color: _text, fontSize: 12),
          decoration: const InputDecoration(
            hintText: 'RTMP ingest URL (YouTube/Facebook live)',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        const SizedBox(height: 6),
        Wrap(
          spacing: 8,
          children: [
            TextButton(
              onPressed: _busy || _selected == null ? null : _saveRtmp,
              child: const Text('Save RTMP'),
            ),
            TextButton(
              onPressed: _selected == null ? null : _copyRss,
              child: const Text('Copy RSS feed URL'),
            ),
          ],
        ),
        if (_delayNote.isNotEmpty)
          Text('Delay: $_delayNote',
              style: const TextStyle(color: _muted, fontSize: 11)),
        if (_meterNote.isNotEmpty)
          Text('Meter: $_meterNote',
              style: const TextStyle(color: _muted, fontSize: 11)),
        if (_recentTopics.isNotEmpty) ...[
          const SizedBox(height: 8),
          const Text('Recent caller topics (de-identified)',
              style: TextStyle(color: _muted, fontSize: 11)),
          ..._recentTopics.map(
            (t) => Text('• $t',
                style: const TextStyle(color: _text, fontSize: 11)),
          ),
        ],
        const SizedBox(height: 16),
        const Text('LN PERSONA (L1/L2 platform-locked)',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          children: const [
            Chip(label: Text('L1 guardrail', style: TextStyle(fontSize: 11))),
            Chip(label: Text('L2 vertical', style: TextStyle(fontSize: 11))),
            Chip(label: Text('L3 style = capture', style: TextStyle(fontSize: 11))),
          ],
        ),
        const SizedBox(height: 16),
        const Text('YOUTUBE (coach-owned channel)',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        Text(_ytConnected ? 'Connected' : 'Not connected',
            style: const TextStyle(color: _muted, fontSize: 12)),
        TextButton(
          onPressed: _busy ? null : _connectYoutube,
          child: const Text('Connect YouTube'),
        ),
        CheckboxListTile(
          value: _smsOptIn,
          activeColor: _gold,
          title: const Text('Caller SMS opt-in (counts only, not therapy)',
              style: TextStyle(color: _text, fontSize: 12)),
          onChanged: _busy || _selected == null
              ? null
              : (v) => _toggleSms(v ?? false),
        ),
        if (_envelope.isNotEmpty)
          SizedBox(
            height: 80,
            width: 80,
            child: CustomPaint(painter: _EnvelopePainter(_envelope)),
          ),
      ],
    );
  }

  Widget _onAirPane(bool liveReady) {
    final channel = _ytChannel.isEmpty ? 'not connected' : _ytChannel;
    final sessionOn = (_sessionId ?? '').isNotEmpty;
    return ListView(
      padding: const EdgeInsets.only(top: 12),
      children: [
        const Text('YOUTUBE LIVE',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        Text(
          _ytConnected
              ? 'Assigned channel: $channel'
              : 'Connect your YouTube channel, then Go live.',
          style: const TextStyle(color: _text, fontSize: 13),
        ),
        const SizedBox(height: 6),
        const Text(
          'Go live creates a YouTube Live event on that channel and writes the RTMP ingest. Start a session first if you want Studio to push the room to YouTube in the same step.',
          style: TextStyle(color: _muted, fontSize: 12),
        ),
        if (_ytHint.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(_ytHint, style: const TextStyle(color: _muted, fontSize: 11)),
        ],
        if (_ytWatch.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(_ytWatch, style: const TextStyle(color: _text, fontSize: 12)),
        ],
        Wrap(
          spacing: 8,
          children: [
            TextButton(
              onPressed: _busy ? null : _connectYoutube,
              child: const Text('Connect YouTube'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: _busy || !_ytConnected || _selected == null
                  ? null
                  : _goYoutubeLive,
              child: const Text('Go live on YouTube',
                  style: TextStyle(color: Colors.black)),
            ),
          ],
        ),
        if (!liveReady)
          const Text(
            'RTMP egress waits until 1 clean published episode unlocks live tier.',
            style: TextStyle(color: _muted, fontSize: 11),
          ),
        const SizedBox(height: 16),
        const Text('ON SCREEN FOR LITTLE NATE',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        const Text(
          'Pick an image, PDF, or document. Nate reads the extracted text / still. For video, open the studio room and use ON SCREEN → Video.',
          style: TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: _busy || !sessionOn ? null : _pickLiveShare,
              child: const Text('Pick file for Nate',
                  style: TextStyle(color: Colors.black)),
            ),
            if (_roomUrl.isNotEmpty)
              TextButton(
                onPressed: _busy
                    ? null
                    : () async {
                        final tab = openStudioRoomPlaceholder();
                        await _joinRoom();
                        if (!mounted || _roomUrl.isEmpty) return;
                        navigateStudioRoomTab(tab, _roomUrl);
                      },
                child: const Text('Open studio room'),
              ),
          ],
        ),
        if (!sessionOn)
          const Text('Start a session on LIVE first.',
              style: TextStyle(color: _muted, fontSize: 11)),
      ],
    );
  }

  Widget _livePane(bool liveReady) {
    return ListView(
      padding: const EdgeInsets.only(top: 12),
      children: [
        if (_lkNote.isNotEmpty)
          Text(_lkNote, style: const TextStyle(color: _muted, fontSize: 11)),
        if ((_sessionId ?? '').isNotEmpty) ...[
          const Text('SESSION VIEW',
              style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
          const Text(
              'Host tile · LN avatar · callers (audio) · waiting room. Dock: Mute, Camera, Share, File, Look up. ON SCREEN tabs: Screen · Image · Document · Video · Lookup.',
              style: TextStyle(color: _muted, fontSize: 11)),
          const SizedBox(height: 6),
        ],
        if (_roomUrl.isNotEmpty) ...[
          TextButton(
            onPressed: _busy
                ? null
                : () async {
                    final tab = openStudioRoomPlaceholder();
                    await _joinRoom();
                    if (!mounted || _roomUrl.isEmpty) return;
                    navigateStudioRoomTab(tab, _roomUrl);
                  },
            child: const Text('Open studio room'),
          ),
        ],
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: _busy || _selected == null
                  ? null
                  : () {
                      _studioTabs.animateTo(1);
                      _post('/api/studio/sessions',
                          {'show_id': (_selected?['id'] ?? '').toString()});
                    },
              child: const Text('Start session',
                  style: TextStyle(color: Colors.black)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _gold),
              onPressed: _busy || (_sessionId ?? '').isEmpty
                  ? null
                  : () => _post('/api/studio/sessions/$_sessionId/end'),
              child: const Text('End → review',
                  style: TextStyle(color: Colors.black)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                  backgroundColor: liveReady ? _gold : _muted),
              onPressed: _busy || !liveReady || (_sessionId ?? '').isEmpty
                  ? null
                  : () => _post('/api/studio/sessions/$_sessionId/dump'),
              child: Text(liveReady ? 'Dump (45s)' : 'Dump locked',
                  style: const TextStyle(color: Colors.black)),
            ),
          ],
        ),
        const SizedBox(height: 16),
        const Text('CALLER MEMORY (counts only)',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        Text(
            'logged $_callersLogged · opted-in $_callersOpted · no transcript browse',
            style: const TextStyle(color: _muted, fontSize: 12)),
        if ((_sessionId ?? '').isNotEmpty) ...[
          const SizedBox(height: 16),
          _callerBoard(),
        ],
      ],
    );
  }

  Widget _editPane() {
    return ListView(
      padding: const EdgeInsets.only(top: 12),
      children: [
        const Text('EPISODE REVIEW',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        const Text(
          'Keep-ranges stay. FFmpeg concatenates them into studio/{session}/cut.mp4. '
          'Watch the tape, add start/end seconds, then Apply cuts.',
          style: TextStyle(color: _muted, fontSize: 12),
        ),
        const SizedBox(height: 8),
        TextField(
          controller: _noteCtrl,
          style: const TextStyle(color: _text, fontSize: 12),
          decoration: const InputDecoration(
            hintText: 'Coach note for regenerate LN answer',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        TextField(
          controller: _cutsCtrl,
          style: const TextStyle(color: _text, fontSize: 12),
          decoration: const InputDecoration(
            hintText: 'FFmpeg cuts seconds e.g. 10-40,90-120',
            hintStyle: TextStyle(color: _muted),
          ),
        ),
        const SizedBox(height: 8),
        if (_editEid.isNotEmpty) _keepEditor(),
        if (_editEid.isNotEmpty && _episodeFlags.isNotEmpty) ...[
          const SizedBox(height: 12),
          const Text('COMPLIANCE FLAGS',
              style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
          ..._episodeFlags.map((f) {
            final fid = (f['id'] ?? '').toString();
            final status = (f['status'] ?? 'open').toString();
            return ListTile(
              dense: true,
              title: Text(
                  '${f['severity'] ?? ''} · ${f['rule_id'] ?? f['kind'] ?? 'flag'}',
                  style: const TextStyle(color: _text, fontSize: 11)),
              subtitle: Text(
                  '${f['detail'] ?? ''} · $status',
                  style: const TextStyle(color: _muted, fontSize: 10)),
              trailing: status == 'open'
                  ? TextButton(
                      onPressed: _busy ? null : () => _resolveFlag(fid),
                      child: const Text('Resolve',
                          style: TextStyle(fontSize: 11)),
                    )
                  : null,
            );
          }),
        ],
        if (_episodes.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 8),
            child: Text('No episodes yet',
                style: TextStyle(color: _muted, fontSize: 12)),
          ),
        ..._episodes.map((e) {
          final eid = (e['id'] ?? '').toString();
          final key = (e['media_r2_key'] ?? '').toString();
          final tape = e['media_ready'] == true && key.isNotEmpty
              ? 'tape ready'
              : (key.isNotEmpty ? 'tape pending' : 'no tape');
          final yt = (e['youtube_video_id'] ?? '').toString();
          final selected = eid == _editEid;
          return Card(
            color: selected ? const Color(0xFF1A1A12) : const Color(0xFF111111),
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text('${e['title'] ?? 'Episode'} · ${e['state']}',
                        style: const TextStyle(color: _text, fontSize: 12)),
                    subtitle: Text(
                        '$tape · open flags ${e['open_flags'] ?? 0}${yt.isEmpty ? '' : ' · yt $yt'}',
                        style: const TextStyle(color: _muted, fontSize: 11)),
                    onTap: _busy ? null : () => _openEditor(e),
                    trailing: const Text('Edit',
                        style: TextStyle(color: _gold, fontSize: 11)),
                  ),
                  Wrap(
                    spacing: 4,
                    children: [
                      TextButton(
                        onPressed: _busy ? null : () => _openTranscript(eid),
                        child: const Text('Transcript',
                            style: TextStyle(fontSize: 11)),
                      ),
                      if ((e['tape_url'] ?? '').toString().isNotEmpty ||
                          _tapeUrl.isNotEmpty)
                        TextButton(
                          onPressed: () {
                            final url = (e['tape_url'] ?? _tapeUrl).toString();
                            if (url.isEmpty) return;
                            launchUrl(Uri.parse(url),
                                mode: LaunchMode.externalApplication,
                                webOnlyWindowName: '_blank');
                          },
                          child: const Text('Watch tape',
                              style: TextStyle(fontSize: 11)),
                        ),
                      TextButton(
                        onPressed: _busy
                            ? null
                            : () => _post(
                                '/api/studio/episodes/$eid/youtube-upload'),
                        child: const Text('YouTube',
                            style: TextStyle(fontSize: 11)),
                      ),
                      TextButton(
                        onPressed: _busy ? null : () => _applyCuts(eid),
                        child: const Text('Apply cuts',
                            style: TextStyle(fontSize: 11)),
                      ),
                      TextButton(
                        onPressed: _busy
                            ? null
                            : () =>
                                _post('/api/studio/episodes/$eid/approve'),
                        child: const Text('Approve',
                            style: TextStyle(fontSize: 11)),
                      ),
                      if ((e['state'] ?? '').toString() == 'in_review')
                        TextButton(
                          onPressed: _busy
                              ? null
                              : () => _post(
                                  '/api/studio/episodes/$eid/reject'),
                          child: const Text('Reject',
                              style: TextStyle(fontSize: 11, color: Colors.red)),
                        ),
                      TextButton(
                        onPressed: _busy
                            ? null
                            : () =>
                                _post('/api/studio/episodes/$eid/publish'),
                        child: const Text('Publish',
                            style: TextStyle(fontSize: 11)),
                      ),
                      TextButton(
                        onPressed: _busy
                            ? null
                            : () => _post(
                                    '/api/studio/episodes/$eid/regenerate', {
                                  'segment_id': 'ln',
                                  'coach_note': _noteCtrl.text.trim(),
                                }),
                        child: const Text('Regen LN',
                            style: TextStyle(fontSize: 11)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          );
        }),
      ],
    );
  }

  Widget _keepEditor() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('KEEP RANGES (seconds)',
            style: TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 6),
        ..._keepRows.asMap().entries.map((entry) {
          final i = entry.key;
          final row = entry.value;
          return Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: row.start,
                    keyboardType: TextInputType.number,
                    style: const TextStyle(color: _text, fontSize: 12),
                    decoration: const InputDecoration(
                      labelText: 'Start',
                      labelStyle: TextStyle(color: _muted, fontSize: 11),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: row.end,
                    keyboardType: TextInputType.number,
                    style: const TextStyle(color: _text, fontSize: 12),
                    decoration: const InputDecoration(
                      labelText: 'End',
                      labelStyle: TextStyle(color: _muted, fontSize: 11),
                    ),
                  ),
                ),
                IconButton(
                  tooltip: 'Remove keep',
                  onPressed: _keepRows.length <= 1
                      ? null
                      : () {
                          setState(() {
                            row.start.dispose();
                            row.end.dispose();
                            _keepRows.removeAt(i);
                          });
                        },
                  icon: const Icon(Icons.remove_circle_outline,
                      color: _muted, size: 18),
                ),
              ],
            ),
          );
        }),
        Wrap(
          spacing: 8,
          children: [
            TextButton.icon(
              onPressed: _addKeepRow,
              icon: const Icon(Icons.add, color: _gold, size: 16),
              label: const Text('Add keep range',
                  style: TextStyle(color: _gold, fontSize: 12)),
            ),
            TextButton(
              onPressed: _busy ? null : () => _applyCuts(_editEid),
              child: const Text('Apply cuts',
                  style: TextStyle(color: _gold, fontSize: 12)),
            ),
          ],
        ),
      ],
    );
  }

  Widget _personaPane() {
    return ListView(
      padding: const EdgeInsets.only(top: 12),
      children: [
        Text('MIRROR CAPTURE  $_complete/7',
            style: const TextStyle(color: _gold, fontSize: 11, letterSpacing: 1)),
        const SizedBox(height: 8),
        ..._displayParts.map((p) {
          final n = (p['index'] as num?)?.toInt() ?? 0;
          final rec = _recordingPart == n;
          final saving = _uploading.contains(n);
          final micHeld = _recordingPart != null && !rec;
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${p['complete'] == true ? '✓' : (saving ? '…' : '○')} ${p['title'] ?? 'Part $n'}',
                  style: const TextStyle(color: _text, fontSize: 13),
                ),
                if ((p['prompt'] ?? '').toString().isNotEmpty)
                  Text(p['prompt'].toString(),
                      style: const TextStyle(color: _muted, fontSize: 12)),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 8,
                  children: [
                    if (CoachWebRecorder.isSupported)
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                            backgroundColor: rec
                                ? const Color(0xFFEF4444)
                                : _gold),
                        onPressed: saving
                            ? null
                            : (rec || !micHeld
                                ? () => _toggleRecord(n)
                                : null),
                        icon: saving
                            ? _spin()
                            : Icon(rec ? Icons.stop : Icons.mic,
                                color: Colors.black, size: 16),
                        label: Text(
                            saving
                                ? 'Saving…'
                                : (rec ? 'Stop ${_secs}s' : 'Record'),
                            style: const TextStyle(color: Colors.black)),
                      ),
                    ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(backgroundColor: _gold),
                      onPressed: saving || rec ? null : () => _pickPart(n),
                      icon: saving
                          ? _spin()
                          : const Icon(Icons.upload_file,
                              color: Colors.black, size: 16),
                      label: Text(saving ? 'Uploading…' : 'Upload',
                          style: const TextStyle(color: Colors.black)),
                    ),
                    if (p['complete'] == true ||
                        p['has_audio'] == true ||
                        _locallyComplete.contains(n))
                      TextButton.icon(
                        onPressed: saving ? null : () => _playPart(n),
                        icon: const Icon(Icons.play_arrow,
                            color: _gold, size: 16),
                        label: const Text('Play',
                            style: TextStyle(color: _gold, fontSize: 12)),
                      ),
                    if (p['complete'] == true ||
                        p['has_transcript'] == true ||
                        _locallyComplete.contains(n))
                      TextButton(
                        onPressed: saving ? null : () => _showTranscript(n),
                        child: const Text('Show transcript',
                            style: TextStyle(color: _gold, fontSize: 12)),
                      ),
                  ],
                ),
              ],
            ),
          );
        }),
        CheckboxListTile(
          value: _cloneConsent,
          activeColor: _gold,
          title: const Text(
            'Signed likeness consent for voice clone (never used as LN on-air voice)',
            style: TextStyle(color: _text, fontSize: 12),
          ),
          onChanged: (_) => _signClone(),
        ),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: _gold),
          onPressed: _busy || _uploading.isNotEmpty ? null : _finalize,
          child: const Text('Finalize capture → persona style',
              style: TextStyle(color: Colors.black)),
        ),
        const SizedBox(height: 20),
        CoachStudioPersonaTools(
          token: widget.token,
          epoch: _personaEpoch,
          pendingDiff: _lastDiff,
        ),
      ],
    );
  }
}

class _EnvelopePainter extends CustomPainter {
  final List<Offset> points;
  _EnvelopePainter(this.points);

  @override
  void paint(Canvas canvas, Size size) {
    if (points.length < 3) return;
    final paint = Paint()
      ..color = const Color(0xFFC9A962)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4;
    final sx = size.width / 160;
    final sy = size.height / 160;
    final path = Path()
      ..moveTo(points.first.dx * sx, points.first.dy * sy);
    for (final p in points.skip(1)) {
      path.lineTo(p.dx * sx, p.dy * sy);
    }
    path.close();
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant _EnvelopePainter old) => old.points != points;
}

class _KeepRange {
  final TextEditingController start;
  final TextEditingController end;
  _KeepRange({required this.start, required this.end});
}
